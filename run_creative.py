"""Process B: the brand and content leaf workers. Run alongside
run_core.py / run_market.py / run_ops.py; all four must point at the same
UAGENTS_TRACE_DB for spans to correlate into a single trace.
"""

from uagents import Bureau

import config
from agents.workers.brand import brand_logo_brief, brand_name, brand_palette, brand_voice
from agents.workers.content import content_about, content_email, content_faq, content_hero, content_services

CREATIVE_AGENTS = [
    brand_name,
    brand_palette,
    brand_logo_brief,
    brand_voice,
    content_hero,
    content_about,
    content_services,
    content_faq,
    content_email,
]

_port = config.process_port("creative")
bureau = Bureau(agents=CREATIVE_AGENTS, port=_port, endpoint=f"http://127.0.0.1:{_port}/submit")

if __name__ == "__main__":
    for agent in CREATIVE_AGENTS:
        print(f"{agent.name}: {agent.address}")
    print("Spans are written to ./uagents_trace.db (override with UAGENTS_TRACE_DB)")
    bureau.run()
