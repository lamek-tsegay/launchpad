"""Per-hop Request/Response pairs (spec section 4).

No shared mutable state object and no god model: every hop gets its own
pair, and a worker only ever imports the one pair that names it. Nested
pydantic models are never used across a message boundary (hard constraint
#5) -- structured sub-fields are `Dict` / `List[Dict]`, with the expected
shape documented in a comment above the field.

The 21 leaf workers share one shape (`intake`/`attempt`/`critique` in,
`section_id`/`content`/`details`/`used_fallback` out), so their pairs are
generated rather than hand-duplicated 21 times; each generated class still
gets its own real name (`BrandNameRequest`, ...) so it appears under that
name in traces and in `isinstance`/type-based dispatch.
"""

from typing import Dict, List

from uagents import Model

# ---------------------------------------------------------------------------
# gateway -> parser -> payment_gate -> orchestrator
# ---------------------------------------------------------------------------


class ParseRequest(Model):
    text: str
    chat_sender: str  # original chat user's address; threaded through so
    # `delivery` can reply directly to the user without routing back
    # through `gateway` (see the flow diagram in the spec).


class PaymentGateRequest(Model):
    # intake shape: {"business_type": str, "industry": str, "location": str,
    #  "concept": str, "tier": "paid"|"unpaid", "chat_sender": str}
    intake: Dict


class OrchestratorRequest(Model):
    intake: Dict


# ---------------------------------------------------------------------------
# orchestrator -> leads, leads -> assembler
# ---------------------------------------------------------------------------


class BrandLeadRequest(Model):
    intake: Dict


class ContentLeadRequest(Model):
    intake: Dict


class MarketLeadRequest(Model):
    intake: Dict


class OpsLeadRequest(Model):
    intake: Dict
    ops_team: List[str]  # which ops workers apply this run (config.OPS_TEAM_BY_BUSINESS_TYPE)


class LeadResult(Model):
    # sections shape: [{"section_id": str, "content": str, "used_fallback": bool,
    #  "details": Dict}, ...] -- one entry per worker this lead dispatched to
    # that actually replied.
    team: str
    intake: Dict  # passed through so `assembler` knows tier/business_type
    # without a side channel back to `orchestrator`.
    sections: List[Dict]


# ---------------------------------------------------------------------------
# assembler -> qa_critic -> (retries to leads) -> delivery
# ---------------------------------------------------------------------------


class DraftDocument(Model):
    intake: Dict
    sections: List[Dict]


class SectionRetryRequest(Model):
    section_id: str
    critique: str


class SectionRetryResult(Model):
    section_id: str
    content: str
    used_fallback: bool
    details: Dict


class FinalDocument(Model):
    intake: Dict
    # sections shape adds "score": int and "flagged": bool (still below
    # threshold after its one allowed retry) on top of the DraftDocument shape.
    sections: List[Dict]


# ---------------------------------------------------------------------------
# Leaf worker pairs -- one Request/Response per worker (spec section 4 example).
# ---------------------------------------------------------------------------

WORKER_NAMES = [
    "brand_name",
    "brand_palette",
    "brand_logo_brief",
    "brand_voice",
    "content_hero",
    "content_about",
    "content_services",
    "content_faq",
    "content_email",
    "market_competitor_finder",
    "market_scout_1",
    "market_scout_2",
    "market_scout_3",
    "market_pricing",
    "market_seo",
    "market_ad_copy",
    "ops_entity",
    "ops_tax",
    "ops_permits",
    "ops_health",
    "ops_food_handler",
    "ops_insurance",
]


def _pascal(worker_name: str) -> str:
    return "".join(part.capitalize() for part in worker_name.split("_"))


WORKER_REQUEST_TYPES: Dict[str, type] = {}
WORKER_RESPONSE_TYPES: Dict[str, type] = {}

for _worker in WORKER_NAMES:
    _prefix = _pascal(_worker)

    _req = type(
        f"{_prefix}Request",
        (Model,),
        {
            "__annotations__": {"intake": Dict, "attempt": int, "critique": str},
            "attempt": 1,
            "critique": "",
        },
    )
    _resp = type(
        f"{_prefix}Response",
        (Model,),
        {
            "__annotations__": {
                "section_id": str,
                "content": str,
                "details": Dict,
                "used_fallback": bool,
            },
            "details": {},
            "used_fallback": False,
        },
    )

    globals()[_req.__name__] = _req
    globals()[_resp.__name__] = _resp
    WORKER_REQUEST_TYPES[_worker] = _req
    WORKER_RESPONSE_TYPES[_worker] = _resp

del _worker, _prefix, _req, _resp
