"""Brand team leaf workers (process B / run_creative.py)."""

import config
from shared_models import (
    BrandLogoBriefRequest,
    BrandLogoBriefResponse,
    BrandNameRequest,
    BrandNameResponse,
    BrandPaletteRequest,
    BrandPaletteResponse,
    BrandVoiceRequest,
    BrandVoiceResponse,
)
from uagents_trace import trace, traced_send
from worker_common import critique_line, run_worker

brand_name = config.build_agent("brand_name")
brand_palette = config.build_agent("brand_palette")
brand_logo_brief = config.build_agent("brand_logo_brief")
brand_voice = config.build_agent("brand_voice")


def _concept_line(intake: dict) -> str:
    return (
        f"Business concept: {intake.get('concept', 'a new small business')}\n"
        f"Industry: {intake.get('industry', 'general')}\n"
        f"Business type: {intake.get('business_type', 'services')}\n"
        f"Location: {intake.get('location', 'unspecified')}"
    )


@brand_name.on_message(model=BrandNameRequest)
@trace
async def handle_brand_name(ctx, sender: str, msg: BrandNameRequest) -> None:
    system = "You are a naming consultant. Reply with strict JSON: {\"content\": <chosen name>, \"candidates\": [{\"name\":str,\"rationale\":str}, ...3 items]}."
    user = _concept_line(msg.intake) + critique_line(msg.attempt, msg.critique)

    def fallback():
        industry = (msg.intake.get("industry") or "General").title()
        candidates = [
            {"name": f"{industry} Collective", "rationale": "Signals a community-oriented brand in this industry."},
            {"name": f"North & {industry}", "rationale": "Evokes reliability with a directional, memorable pairing."},
            {"name": f"{industry} Union Co.", "rationale": "Reads as an established, trustworthy operation."},
        ]
        return candidates[0]["name"], {"candidates": candidates}

    resp = await run_worker(
        worker_name="brand_name", section_id="brand.name", response_type=BrandNameResponse,
        system_prompt=system, user_prompt=user, fallback=fallback,
    )
    await _reply(ctx, sender, resp)


@brand_palette.on_message(model=BrandPaletteRequest)
@trace
async def handle_brand_palette(ctx, sender: str, msg: BrandPaletteRequest) -> None:
    system = "You are a brand designer. Reply with strict JSON: {\"content\": <one-paragraph palette rationale>, \"swatches\": [{\"name\":str,\"hex\":str}, ...4 items]}."
    user = _concept_line(msg.intake) + critique_line(msg.attempt, msg.critique)

    def fallback():
        swatches = [
            {"name": "Deep Slate", "hex": "#1F2933"},
            {"name": "Warm Sand", "hex": "#E8DCC8"},
            {"name": "Ember", "hex": "#C1521A"},
            {"name": "Chalk", "hex": "#F7F5F2"},
        ]
        content = "A grounded neutral base (slate and chalk) with a warm ember accent for calls to action -- reads as established rather than trendy."
        return content, {"swatches": swatches}

    resp = await run_worker(
        worker_name="brand_palette", section_id="brand.palette", response_type=BrandPaletteResponse,
        system_prompt=system, user_prompt=user, fallback=fallback,
    )
    await _reply(ctx, sender, resp)


@brand_logo_brief.on_message(model=BrandLogoBriefRequest)
@trace
async def handle_brand_logo_brief(ctx, sender: str, msg: BrandLogoBriefRequest) -> None:
    system = "You are a brand designer writing a logo design brief. Reply with strict JSON: {\"content\": <2-3 sentence brief>, \"style_tags\": [str, ...3-5 items]}."
    user = _concept_line(msg.intake) + critique_line(msg.attempt, msg.critique)

    def fallback():
        content = (
            "A simple wordmark with a single geometric icon that reduces cleanly to a favicon; "
            "no gradients, one accent color, works in solid black for signage and stitching."
        )
        return content, {"style_tags": ["geometric", "wordmark", "single-color", "minimal"]}

    resp = await run_worker(
        worker_name="brand_logo_brief", section_id="brand.logo_brief", response_type=BrandLogoBriefResponse,
        system_prompt=system, user_prompt=user, fallback=fallback,
    )
    await _reply(ctx, sender, resp)


@brand_voice.on_message(model=BrandVoiceRequest)
@trace
async def handle_brand_voice(ctx, sender: str, msg: BrandVoiceRequest) -> None:
    system = "You are a brand strategist. Reply with strict JSON: {\"content\": <one-paragraph voice description>, \"traits\": [str, ...4 items]}."
    user = _concept_line(msg.intake) + critique_line(msg.attempt, msg.critique)

    def fallback():
        content = "Plain-spoken and confident, favors short sentences, never uses jargon a first-time customer wouldn't know."
        return content, {"traits": ["plain-spoken", "confident", "concise", "warm"]}

    resp = await run_worker(
        worker_name="brand_voice", section_id="brand.voice", response_type=BrandVoiceResponse,
        system_prompt=system, user_prompt=user, fallback=fallback,
    )
    await _reply(ctx, sender, resp)


async def _reply(ctx, sender: str, resp) -> None:
    await traced_send(ctx, sender, resp)
