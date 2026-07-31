from dataclasses import dataclass, field
from typing import Dict, List, Set

import config
from shared_models import DraftDocument, LeadResult
from uagents import Context
from uagents_trace import trace, traced_send

assembler = config.build_agent("assembler")


@dataclass
class _AssemblyState:
    intake: Dict
    teams_seen: Set[str] = field(default_factory=set)
    sections: List[dict] = field(default_factory=list)
    sent: bool = False


_state: Dict[str, _AssemblyState] = {}


def _expected_teams(intake: Dict) -> Set[str]:
    if intake.get("tier") == "paid":
        return {"brand_lead", "content_lead", "market_lead", "ops_lead"}
    return {"brand_lead", "content_lead"}


@assembler.on_message(model=LeadResult)
@trace
async def handle_lead_result(ctx: Context, sender: str, msg: LeadResult) -> None:
    session = str(ctx.session)
    st = _state.setdefault(session, _AssemblyState(intake=msg.intake))

    st.teams_seen.add(msg.team)
    for section in msg.sections:
        section = dict(section)
        section["team"] = msg.team
        st.sections.append(section)

    if not st.sent and _expected_teams(st.intake) <= st.teams_seen:
        st.sent = True
        await traced_send(ctx, config.AGENT_ADDRESSES["qa_critic"], DraftDocument(intake=st.intake, sections=st.sections))
        del _state[session]
