"""Market team leaf workers (process C / run_market.py).

`market_competitor_finder` is the odd one out here: it's a leaf from
market_lead's point of view (one Request/Response pair, same shape as every
other worker) but internally fans out to 1-3 `market_scout_N` workers and
waits for all of them before replying -- the depth described in spec
section 1. On a QA retry (attempt 2) it skips that fan-out entirely and
just regenerates its own section, so the (source, dest, payload_type) pair
with market_lead stays identical across both attempts (spec section 5).
"""

from dataclasses import dataclass, field
from typing import Dict, List, Set

import config
from shared_models import (
    MarketAdCopyRequest,
    MarketAdCopyResponse,
    MarketCompetitorFinderRequest,
    MarketCompetitorFinderResponse,
    MarketPricingRequest,
    MarketPricingResponse,
    MarketScout1Request,
    MarketScout1Response,
    MarketScout2Request,
    MarketScout2Response,
    MarketScout3Request,
    MarketScout3Response,
    MarketSeoRequest,
    MarketSeoResponse,
)
from uagents import Context
from uagents_trace import trace, traced_send
from worker_common import critique_line, run_worker

market_competitor_finder = config.build_agent("market_competitor_finder")
market_scout_1 = config.build_agent("market_scout_1")
market_scout_2 = config.build_agent("market_scout_2")
market_scout_3 = config.build_agent("market_scout_3")
market_pricing = config.build_agent("market_pricing")
market_seo = config.build_agent("market_seo")
market_ad_copy = config.build_agent("market_ad_copy")

_SCOUT_AGENTS = {"market_scout_1": market_scout_1, "market_scout_2": market_scout_2, "market_scout_3": market_scout_3}
_SCOUT_REQUEST_TYPES = {"market_scout_1": MarketScout1Request, "market_scout_2": MarketScout2Request, "market_scout_3": MarketScout3Request}
_SCOUT_RESPONSE_TYPES = {"market_scout_1": MarketScout1Response, "market_scout_2": MarketScout2Response, "market_scout_3": MarketScout3Response}


def _concept_line(intake: dict) -> str:
    return (
        f"Business concept: {intake.get('concept', 'a new small business')}\n"
        f"Industry: {intake.get('industry', 'general')}\n"
        f"Location: {intake.get('location', 'unspecified')}"
    )


# ---------------------------------------------------------------------------
# market_competitor_finder: leaf to market_lead, sub-orchestrator to scouts
# ---------------------------------------------------------------------------


@dataclass
class _ScoutFanout:
    reply_to: str
    expected: Set[str]
    collected: Dict[str, dict] = field(default_factory=dict)
    chosen: List[dict] = field(default_factory=list)
    own_content: str = ""
    own_details: dict = field(default_factory=dict)
    own_fallback: bool = False


_fanout: Dict[str, _ScoutFanout] = {}

_FALLBACK_COMPETITORS = [
    {"name": "Established Local Co.", "url": "https://example.com/competitor-a", "notes": "Long-tenured, higher prices, weak online presence."},
    {"name": "Regional Chain", "url": "https://example.com/competitor-b", "notes": "Multiple locations, aggressive pricing, generic branding."},
    {"name": "New Entrant", "url": "https://example.com/competitor-c", "notes": "Launched in the last year, active on social media."},
]


def _competitor_finder_fallback():
    content = "Three comparable operators were identified nearby: an established local player, a regional chain, and a recent new entrant."
    return content, {"competitors": _FALLBACK_COMPETITORS}


@market_competitor_finder.on_message(model=MarketCompetitorFinderRequest)
@trace
async def handle_competitor_finder(ctx: Context, sender: str, msg: MarketCompetitorFinderRequest) -> None:
    system = "You are a market researcher. Reply with strict JSON: {\"content\": <2-3 sentence summary>, \"competitors\": [{\"name\":str,\"url\":str,\"notes\":str}, ...1-3 items]}."
    user = _concept_line(msg.intake) + critique_line(msg.attempt, msg.critique)

    resp = await run_worker(
        worker_name="market_competitor_finder", section_id="market.competitors", response_type=MarketCompetitorFinderResponse,
        system_prompt=system, user_prompt=user, fallback=_competitor_finder_fallback,
    )

    if msg.attempt >= 2:
        # QA retry: regenerate this section only, no scout re-dispatch.
        await traced_send(ctx, sender, resp)
        return

    competitors = resp.details.get("competitors") or []
    if not isinstance(competitors, list) or not competitors:
        competitors = _FALLBACK_COMPETITORS
    chosen = competitors[: min(3, max(1, len(competitors)))]
    scout_names = list(_SCOUT_AGENTS.keys())[: len(chosen)]

    session = str(ctx.session)
    _fanout[session] = _ScoutFanout(
        reply_to=sender,
        expected=set(scout_names),
        chosen=chosen,
        own_content=resp.content,
        own_details=resp.details,
        own_fallback=resp.used_fallback,
    )
    for worker_name, competitor in zip(scout_names, chosen):
        scout_intake = {**msg.intake, "competitor": competitor}
        await traced_send(
            ctx,
            config.AGENT_ADDRESSES[worker_name],
            _SCOUT_REQUEST_TYPES[worker_name](intake=scout_intake, attempt=1, critique=""),
            timeout=config.SEND_TIMEOUT_SECONDS,
        )


def _make_scout_collector(worker_name: str, scout_index: int):
    async def handler(ctx: Context, sender: str, msg) -> None:
        session = str(ctx.session)
        st = _fanout.get(session)
        if st is None:
            return
        competitor = st.chosen[scout_index - 1] if scout_index - 1 < len(st.chosen) else {}
        st.collected[worker_name] = {
            "worker": worker_name,
            "section_id": f"market.scout_{scout_index}",
            "competitor": competitor,
            "content": msg.content,
            "used_fallback": msg.used_fallback,
        }
        if st.expected <= st.collected.keys():
            final = MarketCompetitorFinderResponse(
                section_id="market.competitors",
                content=st.own_content,
                details={"competitors": st.chosen, "scouts": list(st.collected.values())},
                used_fallback=st.own_fallback,
            )
            await traced_send(ctx, st.reply_to, final)
            del _fanout[session]

    return handler


for _name, _agent in _SCOUT_AGENTS.items():
    _idx = int(_name.rsplit("_", 1)[1])
    market_competitor_finder.on_message(model=_SCOUT_RESPONSE_TYPES[_name])(trace(_make_scout_collector(_name, _idx)))


# ---------------------------------------------------------------------------
# scouts -- plain leaf workers, one competitor each (via intake["competitor"])
# ---------------------------------------------------------------------------


def _make_scout_handler(worker_name: str):
    async def handler(ctx: Context, sender: str, msg) -> None:
        competitor = msg.intake.get("competitor", {})
        system = "You are a competitive analyst. Reply with strict JSON: {\"content\": <2-3 sentence competitive read>}."
        user = (
            f"Competitor: {competitor.get('name', 'unknown')}\n"
            f"URL: {competitor.get('url', 'n/a')}\n"
            f"Notes: {competitor.get('notes', 'n/a')}\n"
            + _concept_line(msg.intake)
            + critique_line(msg.attempt, msg.critique)
        )

        def fallback():
            name = competitor.get("name", "this competitor")
            return f"{name} appears to compete mainly on price rather than experience -- there's room to differentiate on service quality.", {}

        response_type = _SCOUT_RESPONSE_TYPES[worker_name]
        section_id = f"market.scout_{worker_name.rsplit('_', 1)[1]}"
        resp = await run_worker(worker_name=worker_name, section_id=section_id, response_type=response_type, system_prompt=system, user_prompt=user, fallback=fallback)
        await traced_send(ctx, sender, resp)

    return handler


for _name, _agent in _SCOUT_AGENTS.items():
    _agent.on_message(model=_SCOUT_REQUEST_TYPES[_name])(trace(_make_scout_handler(_name)))


# ---------------------------------------------------------------------------
# flat market workers
# ---------------------------------------------------------------------------


@market_pricing.on_message(model=MarketPricingRequest)
@trace
async def handle_pricing(ctx: Context, sender: str, msg: MarketPricingRequest) -> None:
    system = "You are a pricing strategist. Reply with strict JSON: {\"content\": <2-3 sentence rationale>, \"tiers\": [{\"name\":str,\"price\":str,\"notes\":str}, ...2-3 items]}."
    user = _concept_line(msg.intake) + critique_line(msg.attempt, msg.critique)

    def fallback():
        tiers = [
            {"name": "Starter", "price": "$—", "notes": "Entry point, single unit or session."},
            {"name": "Standard", "price": "$—", "notes": "Most customers land here; bundles the core offering."},
            {"name": "Premium", "price": "$—", "notes": "Highest-touch option, priced for margin over volume."},
        ]
        return "Anchor on three tiers so the middle option looks like the obvious choice.", {"tiers": tiers}

    resp = await run_worker(worker_name="market_pricing", section_id="market.pricing", response_type=MarketPricingResponse, system_prompt=system, user_prompt=user, fallback=fallback)
    await traced_send(ctx, sender, resp)


@market_seo.on_message(model=MarketSeoRequest)
@trace
async def handle_seo(ctx: Context, sender: str, msg: MarketSeoRequest) -> None:
    system = "You are an SEO strategist. Reply with strict JSON: {\"content\": <2-3 sentence strategy note>, \"keywords\": [str, ...6 items]}."
    user = _concept_line(msg.intake) + critique_line(msg.attempt, msg.critique)

    def fallback():
        industry = msg.intake.get("industry", "business")
        location = msg.intake.get("location", "your city")
        keywords = [f"{industry} {location}", f"best {industry} near me", f"{industry} services", f"affordable {industry}", f"{location} {industry} reviews", industry]
        return f"Prioritize local-intent keywords pairing '{industry}' with '{location}' over generic national terms.", {"keywords": keywords}

    resp = await run_worker(worker_name="market_seo", section_id="market.seo", response_type=MarketSeoResponse, system_prompt=system, user_prompt=user, fallback=fallback)
    await traced_send(ctx, sender, resp)


@market_ad_copy.on_message(model=MarketAdCopyRequest)
@trace
async def handle_ad_copy(ctx: Context, sender: str, msg: MarketAdCopyRequest) -> None:
    system = "You are an ad copywriter. Reply with strict JSON: {\"content\": <2-3 sentence angle note>, \"ads\": [{\"headline\":str,\"body\":str}, ...3 items]}."
    user = _concept_line(msg.intake) + critique_line(msg.attempt, msg.critique)

    def fallback():
        concept = msg.intake.get("concept", "our business")
        ads = [
            {"headline": f"Try {concept} today", "body": "See what everyone's talking about -- first-time customers save on their first order."},
            {"headline": "Local, reliable, done right", "body": "We show up on time and stand behind the work."},
            {"headline": "Now booking", "body": "Limited availability this month -- reach out to reserve your spot."},
        ]
        return "Lead with urgency and local trust rather than feature lists.", {"ads": ads}

    resp = await run_worker(worker_name="market_ad_copy", section_id="market.ad_copy", response_type=MarketAdCopyResponse, system_prompt=system, user_prompt=user, fallback=fallback)
    await traced_send(ctx, sender, resp)
