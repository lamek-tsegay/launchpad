"""Free text -> structured intake (spec section 1). LLM does the fuzzy
extraction (industry/location/concept); business_type is decided by a
keyword lookup with an LLM tiebreak, and the LLM's answer is validated
against the allowed enum before it's ever trusted -- hard constraint from
spec section 6 ("never let LLM output decide control flow without
validating it against an allowed set first").

Scenario scripts control tier/payment amount with plain `tier=paid` /
`amount=15.0` markers in the chat text -- deterministic and regex-parsed,
not left for the LLM to infer, since those are pipeline-routing decisions
and belong in section 6's "deterministic code for exact grammar" bucket.
"""

import re
from typing import Optional

import config
import llm
from shared_models import PaymentGateRequest, ParseRequest
from uagents import Context
from uagents_trace import trace, traced_send

parser = config.build_agent("parser")

ALLOWED_BUSINESS_TYPES = ("food", "retail", "saas", "services")

_KEYWORDS = {
    "food": ["food truck", "restaurant", "cafe", "bakery", "catering", "diner", "food"],
    "retail": ["boutique", "retail", "store", "shop", "e-commerce", "ecommerce"],
    "saas": ["saas", "app", "software", "platform", "subscription tool"],
}

_TIER_RE = re.compile(r"\btier=(paid|unpaid)\b", re.IGNORECASE)
_AMOUNT_RE = re.compile(r"\bamount=([\d.]+)\b")


def _classify_business_type_by_keyword(text: str) -> Optional[str]:
    lowered = text.lower()
    for business_type, keywords in _KEYWORDS.items():
        if any(kw in lowered for kw in keywords):
            return business_type
    return None


async def _classify_business_type(text: str) -> str:
    keyword_hit = _classify_business_type_by_keyword(text)
    if keyword_hit is not None:
        return keyword_hit

    try:
        data = await llm.call_asi1_json(
            "Classify the business description into exactly one of: food, retail, saas, services. "
            'Reply with strict JSON: {"business_type": <one of those four words>}.',
            text,
        )
        candidate = str(data.get("business_type", "")).strip().lower()
    except Exception:
        candidate = ""

    # Never trust the LLM's answer without validating it against the allowed
    # set -- an unrecognized value falls back to the safe default rather
    # than propagating arbitrary LLM output into control flow downstream.
    if candidate in ALLOWED_BUSINESS_TYPES:
        return candidate
    return "services"


async def _extract_fuzzy_fields(text: str, business_type: str) -> dict:
    try:
        data = await llm.call_asi1_json(
            "Extract fields from this business description. Reply with strict JSON: "
            '{"industry": str, "location": str, "concept": <one sentence>}.',
            text,
        )
        industry = str(data.get("industry") or business_type).strip()
        location = str(data.get("location") or "unspecified").strip()
        concept = str(data.get("concept") or text[:140]).strip()
        if not industry or not concept:
            raise ValueError("incomplete extraction")
        return {"industry": industry, "location": location, "concept": concept}
    except Exception:
        return {"industry": business_type, "location": "unspecified", "concept": text[:140].strip() or "a new small business"}


@parser.on_message(model=ParseRequest)
@trace
async def handle_parse_request(ctx: Context, sender: str, msg: ParseRequest) -> None:
    tier_match = _TIER_RE.search(msg.text)
    tier = tier_match.group(1).lower() if tier_match else "unpaid"

    amount_match = _AMOUNT_RE.search(msg.text)
    payment_amount = amount_match.group(1) if amount_match else "5.0"

    clean_text = _TIER_RE.sub("", _AMOUNT_RE.sub("", msg.text)).strip()

    business_type = await _classify_business_type(clean_text)
    fuzzy = await _extract_fuzzy_fields(clean_text, business_type)

    intake = {
        "business_type": business_type,
        "tier": tier,
        "payment_amount": payment_amount,
        "chat_sender": msg.chat_sender,
        **fuzzy,
    }

    await traced_send(ctx, config.AGENT_ADDRESSES["payment_gate"], PaymentGateRequest(intake=intake))
