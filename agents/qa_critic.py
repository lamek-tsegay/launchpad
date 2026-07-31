"""Scores each assembled section 0-10 and retries the worst offenders
(spec section 5): at most one retry per section, at most three retries per
run (the three lowest scores), and a retry that still scores below the
threshold ships anyway with `flagged=True`.

The score is a real, content-driven rubric -- length and whether the
section used its LLM fallback -- not a random number. Fallback templates
differ in length per worker by construction, so scores differ across
sections even when every section happens to be a fallback (e.g. when no
ASI1_API_KEY is configured), rather than needing an artificial tie-breaker.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Set

import config
from shared_models import DraftDocument, FinalDocument, SectionRetryRequest, SectionRetryResult
from uagents import Context
from uagents_trace import trace, traced_send

qa_critic = config.build_agent("qa_critic")


def score_section(content: str, used_fallback: bool) -> int:
    score = 10
    if used_fallback:
        score -= 5
    length = len(content or "")
    if length < 40:
        score -= 3
    elif length < 90:
        score -= 1
    return max(0, min(10, score))


@dataclass
class _QaState:
    intake: Dict
    sections: Dict[str, dict]  # section_id -> section dict (with "score")
    outstanding: Set[str] = field(default_factory=set)


_state: Dict[str, _QaState] = {}


@qa_critic.on_message(model=DraftDocument)
@trace
async def handle_draft(ctx: Context, sender: str, msg: DraftDocument) -> None:
    session = str(ctx.session)
    scored: List[dict] = []
    for section in msg.sections:
        section = dict(section)
        section["score"] = score_section(section.get("content", ""), section.get("used_fallback", False))
        section["flagged"] = False
        section["retried"] = False
        scored.append(section)

    failing = sorted(
        (s for s in scored if s["score"] < config.QA_PASS_THRESHOLD),
        key=lambda s: s["score"],
    )[: config.MAX_RETRIES_PER_RUN]

    sections_by_id = {s["section_id"]: s for s in scored}
    st = _QaState(intake=msg.intake, sections=sections_by_id, outstanding={s["section_id"] for s in failing})
    _state[session] = st

    if not failing:
        await _finalize(ctx, session)
        return

    for section in failing:
        owner_lead, _worker = config.SECTION_OWNER[section["section_id"]]
        await traced_send(
            ctx,
            config.AGENT_ADDRESSES[owner_lead],
            SectionRetryRequest(section_id=section["section_id"], critique=_critique_for(section)),
        )


def _critique_for(section: dict) -> str:
    if section.get("used_fallback"):
        return "Content reads as a generic template -- make it specific to this business's concept, industry, and location."
    return "Content is too thin -- expand with more concrete, specific detail."


@qa_critic.on_message(model=SectionRetryResult)
@trace
async def handle_retry_result(ctx: Context, sender: str, msg: SectionRetryResult) -> None:
    session = str(ctx.session)
    st = _state.get(session)
    if st is None:
        return

    new_score = score_section(msg.content, msg.used_fallback)
    st.sections[msg.section_id] = {
        **st.sections[msg.section_id],
        "content": msg.content,
        "used_fallback": msg.used_fallback,
        "details": msg.details,
        "score": new_score,
        "flagged": new_score < config.QA_PASS_THRESHOLD,
        "retried": True,
    }
    st.outstanding.discard(msg.section_id)

    if not st.outstanding:
        await _finalize(ctx, session)


async def _finalize(ctx: Context, session: str) -> None:
    st = _state.pop(session, None)
    if st is None:
        return
    await traced_send(
        ctx,
        config.AGENT_ADDRESSES["delivery"],
        FinalDocument(intake=st.intake, sections=list(st.sections.values())),
    )
