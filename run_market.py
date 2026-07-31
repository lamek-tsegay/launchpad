"""Process C: the market leaf workers, including market_competitor_finder's
scout sub-fan-out (spec section 1's four-level depth). Run alongside
run_core.py / run_creative.py / run_ops.py.
"""

from uagents import Bureau

import config
from agents.workers.market import (
    market_ad_copy,
    market_competitor_finder,
    market_pricing,
    market_scout_1,
    market_scout_2,
    market_scout_3,
    market_seo,
)

MARKET_AGENTS = [
    market_competitor_finder,
    market_scout_1,
    market_scout_2,
    market_scout_3,
    market_pricing,
    market_seo,
    market_ad_copy,
]

_port = config.process_port("market")
bureau = Bureau(agents=MARKET_AGENTS, port=_port, endpoint=f"http://127.0.0.1:{_port}/submit")

if __name__ == "__main__":
    for agent in MARKET_AGENTS:
        print(f"{agent.name}: {agent.address}")
    print("Spans are written to ./uagents_trace.db (override with UAGENTS_TRACE_DB)")
    bureau.run()
