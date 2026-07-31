"""Returns the finished kit to the user (spec section 1 flow diagram:
delivery -> user directly, not routed back through gateway). Sends exactly
one ChatMessage with EndSessionContent -- the only "intermediate" chat
traffic is gateway's ack, per the anti-echo rule in spec section 8.
"""

import config
from shared_models import FinalDocument
from uagents import Context
from uagents_core.contrib.protocols.chat import ChatMessage, EndSessionContent, TextContent
from uagents_trace import trace, traced_send

delivery = config.build_agent("delivery")

_TEAM_TITLES = {
    "brand_lead": "Brand",
    "content_lead": "Website Copy",
    "market_lead": "Market Scan",
    "ops_lead": "Compliance Checklist",
}


def _render(intake: dict, sections: list) -> str:
    concept = intake.get("concept", "your business")
    lines = [f"Here's the starter kit for \"{concept}\":", ""]

    by_team: dict = {}
    for section in sections:
        by_team.setdefault(section.get("team", "other"), []).append(section)

    for team in ("brand_lead", "content_lead", "market_lead", "ops_lead"):
        team_sections = by_team.get(team)
        if not team_sections:
            continue
        lines.append(f"## {_TEAM_TITLES.get(team, team)}")
        for section in sorted(team_sections, key=lambda s: s["section_id"]):
            flag = " [needs another pass]" if section.get("flagged") else ""
            lines.append(f"- {section['section_id']}: {section['content']}{flag}")
        lines.append("")

    return "\n".join(lines).strip()


@delivery.on_message(model=FinalDocument)
@trace
async def handle_final_document(ctx: Context, sender: str, msg: FinalDocument) -> None:
    chat_sender = msg.intake.get("chat_sender")
    if not chat_sender:
        ctx.logger.warning("FinalDocument has no chat_sender in intake; dropping")
        return

    text = _render(msg.intake, msg.sections)
    message = ChatMessage(content=[TextContent(text=text), EndSessionContent()])
    await traced_send(ctx, chat_sender, message)
