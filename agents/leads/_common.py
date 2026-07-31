"""Generic fan-out/aggregate/retry state machine shared by brand_lead,
content_lead, and ops_lead: dispatch one Request per worker, collect
Responses keyed by `ctx.session`, send one `LeadResult` to `assembler` once
every dispatched worker has replied, and re-dispatch a single worker on
`SectionRetryRequest`.

`market_lead` has genuine extra structure (`market_competitor_finder`
dispatches the scout layer itself -- the depth in spec section 1) and is
hand-written in `market.py` instead of using this.
"""

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Set, Tuple

from uagents import Context

import config
from shared_models import LeadResult, SectionRetryRequest, SectionRetryResult
from uagents_trace import trace, traced_send


def is_unresolved(send_result) -> bool:
    """True if `traced_send`'s result says uAgents could not resolve the
    destination at all (config.py's "unreachable" FAILURES mode) -- as
    opposed to a timeout, where a reply may still arrive late (the "slow"
    mode) and the caller should keep waiting instead of giving up.
    """
    detail = str(getattr(send_result, "detail", "") or "")
    return "resolve" in detail.lower()


def unavailable_section(section_id: str, worker_name: str) -> dict:
    return {
        "section_id": section_id,
        "content": f"({worker_name} could not be reached this run)",
        "used_fallback": True,
        "details": {"unavailable": True},
    }


@dataclass
class _SessionState:
    intake: Dict
    expected: Set[str]
    collected: Dict[str, dict] = field(default_factory=dict)
    retry_in_flight: Set[str] = field(default_factory=set)
    sent_result: bool = False


class LeadWiring:
    def __init__(
        self,
        agent,
        team: str,
        request_type: type,
        workers: Dict[str, Tuple[type, type, str]],  # worker_name -> (request_type, response_type, section_id)
        select_workers: Optional[Callable[[object], List[str]]] = None,
    ):
        self.agent = agent
        self.team = team
        self.workers = workers
        self.select_workers = select_workers or (lambda msg: list(workers.keys()))
        self.state: Dict[str, _SessionState] = {}

        agent.on_message(model=request_type)(trace(self._handle_lead_request))
        for worker_name, (_, response_type, section_id) in workers.items():
            agent.on_message(model=response_type)(trace(self._make_response_handler(section_id)))
        agent.on_message(model=SectionRetryRequest)(trace(self._handle_retry))

    async def _handle_lead_request(self, ctx: Context, sender: str, msg) -> None:
        session = str(ctx.session)
        worker_names = self.select_workers(msg)
        section_ids = {self.workers[w][2] for w in worker_names}
        st = _SessionState(intake=msg.intake, expected=section_ids)
        self.state[session] = st
        for worker_name in worker_names:
            request_type, _, section_id = self.workers[worker_name]
            result = await traced_send(
                ctx,
                config.AGENT_ADDRESSES[worker_name],
                request_type(intake=msg.intake, attempt=1, critique=""),
                timeout=config.SEND_TIMEOUT_SECONDS,
            )
            if is_unresolved(result):
                # No process will ever answer this -- e.g. ops_insurance
                # (spec section 7's "unreachable" mode). Recording the span
                # already captured that; waiting forever for a reply that
                # structurally cannot arrive would just hang this lead, so
                # the section ships flagged unavailable instead.
                st.collected[section_id] = unavailable_section(section_id, worker_name)

        if not st.sent_result and st.expected <= st.collected.keys():
            st.sent_result = True
            await traced_send(
                ctx,
                config.AGENT_ADDRESSES["assembler"],
                LeadResult(team=self.team, intake=st.intake, sections=list(st.collected.values())),
            )

    def _make_response_handler(self, section_id: str):
        async def handler(ctx: Context, sender: str, msg) -> None:
            session = str(ctx.session)
            st = self.state.get(session)
            if st is None:
                return

            if section_id in st.retry_in_flight:
                st.retry_in_flight.discard(section_id)
                await traced_send(
                    ctx,
                    config.AGENT_ADDRESSES["qa_critic"],
                    SectionRetryResult(
                        section_id=section_id,
                        content=msg.content,
                        used_fallback=msg.used_fallback,
                        details=msg.details,
                    ),
                )
                return

            st.collected[section_id] = {
                "section_id": section_id,
                "content": msg.content,
                "used_fallback": msg.used_fallback,
                "details": msg.details,
            }
            if not st.sent_result and st.expected <= st.collected.keys():
                st.sent_result = True
                await traced_send(
                    ctx,
                    config.AGENT_ADDRESSES["assembler"],
                    LeadResult(team=self.team, intake=st.intake, sections=list(st.collected.values())),
                )

        return handler

    async def _handle_retry(self, ctx: Context, sender: str, msg) -> None:
        session = str(ctx.session)
        st = self.state.get(session)
        if st is None:
            return
        _owner_lead, worker_name = config.SECTION_OWNER[msg.section_id]
        request_type, _, section_id = self.workers[worker_name]
        st.retry_in_flight.add(section_id)
        result = await traced_send(
            ctx,
            config.AGENT_ADDRESSES[worker_name],
            request_type(intake=st.intake, attempt=2, critique=msg.critique),
            timeout=config.SEND_TIMEOUT_SECONDS,
        )
        if is_unresolved(result):
            st.retry_in_flight.discard(section_id)
            await traced_send(
                ctx,
                config.AGENT_ADDRESSES["qa_critic"],
                SectionRetryResult(section_id=section_id, content=f"({worker_name} could not be reached for retry)", used_fallback=True, details={"unavailable": True}),
            )
