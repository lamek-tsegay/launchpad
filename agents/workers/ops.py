"""Ops team leaf workers (process D / run_ops.py).

`ops_insurance` is deliberately not defined here -- its Request/Response
pair and address exist (shared_models.py, config.py) but no agent is ever
constructed for it, so `ops_lead` sending to it is the "unreachable"
failure mode in spec section 7, not a bug to fix.
"""

import config
from shared_models import (
    OpsEntityRequest,
    OpsEntityResponse,
    OpsFoodHandlerRequest,
    OpsFoodHandlerResponse,
    OpsHealthRequest,
    OpsHealthResponse,
    OpsPermitsRequest,
    OpsPermitsResponse,
    OpsTaxRequest,
    OpsTaxResponse,
)
from uagents_trace import trace, traced_send
from worker_common import critique_line, run_worker

ops_entity = config.build_agent("ops_entity")
ops_tax = config.build_agent("ops_tax")
ops_permits = config.build_agent("ops_permits")
ops_health = config.build_agent("ops_health")
ops_food_handler = config.build_agent("ops_food_handler")


def _concept_line(intake: dict) -> str:
    return (
        f"Business concept: {intake.get('concept', 'a new small business')}\n"
        f"Industry: {intake.get('industry', 'general')}\n"
        f"Business type: {intake.get('business_type', 'services')}\n"
        f"Location: {intake.get('location', 'unspecified')}"
    )


@ops_entity.on_message(model=OpsEntityRequest)
@trace
async def handle_entity(ctx, sender: str, msg: OpsEntityRequest) -> None:
    system = "You are a small-business formation advisor. Reply with strict JSON: {\"content\": <2-3 sentence recommendation>, \"suggested_structure\": str}."
    user = _concept_line(msg.intake) + critique_line(msg.attempt, msg.critique)

    def fallback():
        return (
            "For most single-owner operations at this stage, an LLC balances liability protection against "
            "setup cost and paperwork. Confirm with a local accountant before filing."
        ), {"suggested_structure": "LLC"}

    resp = await run_worker(worker_name="ops_entity", section_id="ops.entity", response_type=OpsEntityResponse, system_prompt=system, user_prompt=user, fallback=fallback)
    await traced_send(ctx, sender, resp)


@ops_tax.on_message(model=OpsTaxRequest)
@trace
async def handle_tax(ctx, sender: str, msg: OpsTaxRequest) -> None:
    system = "You are a small-business tax advisor. Reply with strict JSON: {\"content\": <2-3 sentence overview>, \"registrations\": [str, ...]}."
    user = _concept_line(msg.intake) + critique_line(msg.attempt, msg.critique)

    def fallback():
        location = msg.intake.get("location", "your state")
        return (
            f"You'll need an EIN from the IRS and, depending on what you sell, a seller's permit in {location}. "
            "Set aside quarterly estimated tax payments from day one."
        ), {"registrations": ["EIN", "state seller's permit"]}

    resp = await run_worker(worker_name="ops_tax", section_id="ops.tax", response_type=OpsTaxResponse, system_prompt=system, user_prompt=user, fallback=fallback)
    await traced_send(ctx, sender, resp)


@ops_permits.on_message(model=OpsPermitsRequest)
@trace
async def handle_permits(ctx, sender: str, msg: OpsPermitsRequest) -> None:
    system = "You are a local-permitting advisor. Reply with strict JSON: {\"content\": <2-3 sentence overview>, \"permits\": [str, ...]}."
    user = _concept_line(msg.intake) + critique_line(msg.attempt, msg.critique)

    def fallback():
        business_type = msg.intake.get("business_type", "retail")
        permits = ["general business license", "zoning/use permit"]
        if business_type == "food":
            permits.append("mobile vending permit")
        return (
            "Start with your city or county clerk's office for the general business license, then check "
            "zoning for the specific address or vehicle you'll operate from."
        ), {"permits": permits}

    resp = await run_worker(worker_name="ops_permits", section_id="ops.permits", response_type=OpsPermitsResponse, system_prompt=system, user_prompt=user, fallback=fallback)
    await traced_send(ctx, sender, resp)


@ops_health.on_message(model=OpsHealthRequest)
@trace
async def handle_health(ctx, sender: str, msg: OpsHealthRequest) -> None:
    system = "You are a health-department compliance advisor. Reply with strict JSON: {\"content\": <2-3 sentence overview>}."
    user = _concept_line(msg.intake) + critique_line(msg.attempt, msg.critique)

    def fallback():
        return (
            "Schedule a pre-opening inspection with your county health department, post the resulting grade "
            "where customers can see it, and keep a written cleaning schedule on file."
        ), {}

    resp = await run_worker(worker_name="ops_health", section_id="ops.health", response_type=OpsHealthResponse, system_prompt=system, user_prompt=user, fallback=fallback)
    await traced_send(ctx, sender, resp)


@ops_food_handler.on_message(model=OpsFoodHandlerRequest)
@trace
async def handle_food_handler(ctx, sender: str, msg: OpsFoodHandlerRequest) -> None:
    system = "You are a food-safety compliance advisor. Reply with strict JSON: {\"content\": <2-3 sentence overview>}."
    user = _concept_line(msg.intake) + critique_line(msg.attempt, msg.critique)

    def fallback():
        return (
            "Every employee handling food needs a food handler card within 30 days of their start date; "
            "at least one certified food protection manager should be on staff."
        ), {}

    resp = await run_worker(worker_name="ops_food_handler", section_id="ops.food_handler", response_type=OpsFoodHandlerResponse, system_prompt=system, user_prompt=user, fallback=fallback)
    await traced_send(ctx, sender, resp)
