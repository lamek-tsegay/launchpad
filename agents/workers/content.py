"""Content team leaf workers (process B / run_creative.py)."""

import config
from shared_models import (
    ContentAboutRequest,
    ContentAboutResponse,
    ContentEmailRequest,
    ContentEmailResponse,
    ContentFaqRequest,
    ContentFaqResponse,
    ContentHeroRequest,
    ContentHeroResponse,
    ContentServicesRequest,
    ContentServicesResponse,
)
from uagents_trace import trace, traced_send
from worker_common import critique_line, run_worker

content_hero = config.build_agent("content_hero")
content_about = config.build_agent("content_about")
content_services = config.build_agent("content_services")
content_faq = config.build_agent("content_faq")
content_email = config.build_agent("content_email")


def _concept_line(intake: dict) -> str:
    return (
        f"Business concept: {intake.get('concept', 'a new small business')}\n"
        f"Industry: {intake.get('industry', 'general')}\n"
        f"Business type: {intake.get('business_type', 'services')}\n"
        f"Location: {intake.get('location', 'unspecified')}"
    )


@content_hero.on_message(model=ContentHeroRequest)
@trace
async def handle_hero(ctx, sender: str, msg: ContentHeroRequest) -> None:
    system = "You are a website copywriter. Reply with strict JSON: {\"content\": <hero headline + one-sentence subhead>}."
    user = _concept_line(msg.intake) + critique_line(msg.attempt, msg.critique)

    def fallback():
        concept = msg.intake.get("concept", "your business")
        return f"{concept.capitalize()}, done right. We handle the details so you don't have to.", {}

    resp = await run_worker(worker_name="content_hero", section_id="content.hero", response_type=ContentHeroResponse, system_prompt=system, user_prompt=user, fallback=fallback)
    await traced_send(ctx, sender, resp)


@content_about.on_message(model=ContentAboutRequest)
@trace
async def handle_about(ctx, sender: str, msg: ContentAboutRequest) -> None:
    system = "You are a website copywriter. Reply with strict JSON: {\"content\": <2-3 paragraph About page copy>}."
    user = _concept_line(msg.intake) + critique_line(msg.attempt, msg.critique)

    def fallback():
        location = msg.intake.get("location", "the local area")
        industry = msg.intake.get("industry", "our industry")
        return (
            f"We're a {industry} business based in {location}, started because we saw a better way to "
            f"do this than what was already out there. We keep things simple, show up on time, and stand "
            f"behind our work."
        ), {}

    resp = await run_worker(worker_name="content_about", section_id="content.about", response_type=ContentAboutResponse, system_prompt=system, user_prompt=user, fallback=fallback)
    await traced_send(ctx, sender, resp)


@content_services.on_message(model=ContentServicesRequest)
@trace
async def handle_services(ctx, sender: str, msg: ContentServicesRequest) -> None:
    system = "You are a website copywriter. Reply with strict JSON: {\"content\": <intro paragraph>, \"services\": [{\"name\":str,\"description\":str}, ...3-4 items]}."
    user = _concept_line(msg.intake) + critique_line(msg.attempt, msg.critique)

    def fallback():
        industry = msg.intake.get("industry", "General")
        services = [
            {"name": "Consultation", "description": f"A first conversation to scope what you need from a {industry} partner."},
            {"name": "Core Service", "description": "The main offering, delivered on the timeline we agree to up front."},
            {"name": "Ongoing Support", "description": "Check-ins and adjustments after the initial delivery."},
        ]
        return "Here's what we offer, in plain terms.", {"services": services}

    resp = await run_worker(worker_name="content_services", section_id="content.services", response_type=ContentServicesResponse, system_prompt=system, user_prompt=user, fallback=fallback)
    await traced_send(ctx, sender, resp)


@content_faq.on_message(model=ContentFaqRequest)
@trace
async def handle_faq(ctx, sender: str, msg: ContentFaqRequest) -> None:
    system = "You are a website copywriter. Reply with strict JSON: {\"content\": <intro line>, \"faqs\": [{\"q\":str,\"a\":str}, ...4 items]}."
    user = _concept_line(msg.intake) + critique_line(msg.attempt, msg.critique)

    def fallback():
        location = msg.intake.get("location", "our area")
        faqs = [
            {"q": "Where are you located?", "a": f"We're based in {location} and serve the surrounding area."},
            {"q": "How do I get started?", "a": "Reach out through the contact form and we'll follow up within a business day."},
            {"q": "What does it cost?", "a": "Pricing depends on scope -- we'll give you a clear number before any work starts."},
            {"q": "Do you offer support after delivery?", "a": "Yes, ongoing support is available as a separate add-on."},
        ]
        return "Common questions, answered up front.", {"faqs": faqs}

    resp = await run_worker(worker_name="content_faq", section_id="content.faq", response_type=ContentFaqResponse, system_prompt=system, user_prompt=user, fallback=fallback)
    await traced_send(ctx, sender, resp)


@content_email.on_message(model=ContentEmailRequest)
@trace
async def handle_email(ctx, sender: str, msg: ContentEmailRequest) -> None:
    system = "You are a copywriter. Reply with strict JSON: {\"content\": <email body>, \"subject\": str}."
    user = _concept_line(msg.intake) + critique_line(msg.attempt, msg.critique)

    def fallback():
        concept = msg.intake.get("concept", "our business")
        subject = "We're live -- here's what's new"
        body = f"Hi there,\n\nWe just launched {concept}. Reply to this email if you'd like to be among the first to try it.\n\nThanks,\nThe team"
        return body, {"subject": subject}

    resp = await run_worker(worker_name="content_email", section_id="content.email", response_type=ContentEmailResponse, system_prompt=system, user_prompt=user, fallback=fallback)
    await traced_send(ctx, sender, resp)
