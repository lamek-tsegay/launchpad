"""market_lead has real extra structure compared to the other leads: it
dispatches `market_competitor_finder` directly, but the scout layer
(1-3 of `market_scout_1..3`, spec section 3) is dispatched by
`market_competitor_finder` itself, not by market_lead -- that's the depth
in spec section 1 (gateway -> orchestrator -> market_lead ->
market_competitor_finder -> market_scout_N, four levels).

market_lead only talks to scouts directly for a QA retry (spec section 5:
"re-dispatched to the originating lead, which re-dispatches to the same
worker" -- the retry skips the competitor_finder hop that produced the
scout dispatch in the first place).
"""

from dataclasses import dataclass, field
from typing import Dict, Set

from uagents import Context

import config
from agents.leads._common import is_unresolved, unavailable_section
from shared_models import LeadResult, MarketLeadRequest, SectionRetryRequest, SectionRetryResult, WORKER_REQUEST_TYPES, WORKER_RESPONSE_TYPES
from uagents_trace import trace, traced_send

market_lead = config.build_agent("market_lead")

_BASE_WORKER_NAMES = ["market_pricing", "market_seo", "market_ad_copy"]
_BASE = {
    name: (WORKER_REQUEST_TYPES[name], WORKER_RESPONSE_TYPES[name], f"market.{name.split('_', 1)[1]}")
    for name in _BASE_WORKER_NAMES
}
_FINDER_REQ = WORKER_REQUEST_TYPES["market_competitor_finder"]
_FINDER_RESP = WORKER_RESPONSE_TYPES["market_competitor_finder"]
_SCOUT_NAMES = ["market_scout_1", "market_scout_2", "market_scout_3"]
_SCOUT_REQ = {name: WORKER_REQUEST_TYPES[name] for name in _SCOUT_NAMES}
_SCOUT_RESP = {name: WORKER_RESPONSE_TYPES[name] for name in _SCOUT_NAMES}
_SCOUT_SECTION = {name: f"market.scout_{name.rsplit('_', 1)[1]}" for name in _SCOUT_NAMES}


@dataclass
class _MarketState:
    intake: Dict
    expected: Set[str]
    collected: Dict[str, dict] = field(default_factory=dict)
    retry_in_flight: Set[str] = field(default_factory=set)
    scout_retry_intake: Dict[str, Dict] = field(default_factory=dict)
    sent_result: bool = False


_state: Dict[str, _MarketState] = {}


@market_lead.on_message(model=MarketLeadRequest)
@trace
async def handle_request(ctx: Context, sender: str, msg: MarketLeadRequest) -> None:
    session = str(ctx.session)
    st = _MarketState(intake=msg.intake, expected={"market.competitors", *(w[2] for w in _BASE.values())})
    _state[session] = st

    result = await traced_send(
        ctx, config.AGENT_ADDRESSES["market_competitor_finder"], _FINDER_REQ(intake=msg.intake, attempt=1, critique=""), timeout=config.SEND_TIMEOUT_SECONDS
    )
    if is_unresolved(result):
        st.collected["market.competitors"] = unavailable_section("market.competitors", "market_competitor_finder")
    for worker_name, (request_type, _, section_id) in _BASE.items():
        result = await traced_send(
            ctx, config.AGENT_ADDRESSES[worker_name], request_type(intake=msg.intake, attempt=1, critique=""), timeout=config.SEND_TIMEOUT_SECONDS
        )
        if is_unresolved(result):
            st.collected[section_id] = unavailable_section(section_id, worker_name)
    await _maybe_send_result(ctx, session)


async def _maybe_send_result(ctx: Context, session: str) -> None:
    st = _state.get(session)
    if st is None or st.sent_result:
        return
    if st.expected <= st.collected.keys():
        st.sent_result = True
        await traced_send(
            ctx,
            config.AGENT_ADDRESSES["assembler"],
            LeadResult(team="market_lead", intake=st.intake, sections=list(st.collected.values())),
        )


@market_lead.on_message(model=_FINDER_RESP)
@trace
async def handle_finder_response(ctx: Context, sender: str, msg) -> None:
    session = str(ctx.session)
    st = _state.get(session)
    if st is None:
        return

    if "market.competitors" in st.retry_in_flight:
        st.retry_in_flight.discard("market.competitors")
        await traced_send(
            ctx,
            config.AGENT_ADDRESSES["qa_critic"],
            SectionRetryResult(section_id="market.competitors", content=msg.content, used_fallback=msg.used_fallback, details=msg.details),
        )
        return

    st.collected["market.competitors"] = {
        "section_id": "market.competitors",
        "content": msg.content,
        "used_fallback": msg.used_fallback,
        "details": {"competitors": msg.details.get("competitors", [])},
    }
    for entry in msg.details.get("scouts", []):
        section_id = entry["section_id"]
        st.expected.add(section_id)
        st.collected[section_id] = {
            "section_id": section_id,
            "content": entry["content"],
            "used_fallback": entry["used_fallback"],
            "details": {"competitor": entry.get("competitor", {})},
        }
        st.scout_retry_intake[section_id] = {**st.intake, "competitor": entry.get("competitor", {})}
    await _maybe_send_result(ctx, session)


def _make_base_handler(section_id: str):
    async def handler(ctx: Context, sender: str, msg) -> None:
        session = str(ctx.session)
        st = _state.get(session)
        if st is None:
            return
        if section_id in st.retry_in_flight:
            st.retry_in_flight.discard(section_id)
            await traced_send(
                ctx,
                config.AGENT_ADDRESSES["qa_critic"],
                SectionRetryResult(section_id=section_id, content=msg.content, used_fallback=msg.used_fallback, details=msg.details),
            )
            return
        st.collected[section_id] = {"section_id": section_id, "content": msg.content, "used_fallback": msg.used_fallback, "details": msg.details}
        await _maybe_send_result(ctx, session)

    return handler


for _worker_name, (_, _resp_t, _section_id) in _BASE.items():
    market_lead.on_message(model=_resp_t)(trace(_make_base_handler(_section_id)))


def _make_scout_retry_handler(section_id: str):
    async def handler(ctx: Context, sender: str, msg) -> None:
        # Attempt-1 scout replies go to market_competitor_finder, not here --
        # market_lead only ever receives a scout Response directly as the
        # result of a retry it dispatched itself.
        session = str(ctx.session)
        st = _state.get(session)
        if st is None or section_id not in st.retry_in_flight:
            return
        st.retry_in_flight.discard(section_id)
        await traced_send(
            ctx,
            config.AGENT_ADDRESSES["qa_critic"],
            SectionRetryResult(section_id=section_id, content=msg.content, used_fallback=msg.used_fallback, details=msg.details),
        )

    return handler


for _scout_name, _section_id in _SCOUT_SECTION.items():
    market_lead.on_message(model=_SCOUT_RESP[_scout_name])(trace(_make_scout_retry_handler(_section_id)))


@market_lead.on_message(model=SectionRetryRequest)
@trace
async def handle_retry(ctx: Context, sender: str, msg: SectionRetryRequest) -> None:
    session = str(ctx.session)
    st = _state.get(session)
    if st is None:
        return
    _owner_lead, worker_name = config.SECTION_OWNER[msg.section_id]
    st.retry_in_flight.add(msg.section_id)

    if worker_name in _SCOUT_REQ:
        retry_intake = st.scout_retry_intake.get(msg.section_id, st.intake)
        await traced_send(
            ctx, config.AGENT_ADDRESSES[worker_name], _SCOUT_REQ[worker_name](intake=retry_intake, attempt=2, critique=msg.critique), timeout=config.SEND_TIMEOUT_SECONDS
        )
    elif worker_name == "market_competitor_finder":
        await traced_send(
            ctx, config.AGENT_ADDRESSES["market_competitor_finder"], _FINDER_REQ(intake=st.intake, attempt=2, critique=msg.critique), timeout=config.SEND_TIMEOUT_SECONDS
        )
    else:
        request_type, _, _section_id = _BASE[worker_name]
        await traced_send(
            ctx, config.AGENT_ADDRESSES[worker_name], request_type(intake=st.intake, attempt=2, critique=msg.critique), timeout=config.SEND_TIMEOUT_SECONDS
        )
