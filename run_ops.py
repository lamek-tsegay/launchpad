"""Process D: the ops leaf workers. `ops_insurance` is deliberately never
started here (spec section 1) -- ops_lead still addresses it under
food/retail business types, and that send fails as an unresolved
destination (config.py excludes it from the resolver rules).

Run alongside run_core.py / run_creative.py / run_market.py.
"""

from uagents import Bureau

import config
from agents.workers.ops import ops_entity, ops_food_handler, ops_health, ops_permits, ops_tax

OPS_AGENTS = [ops_entity, ops_tax, ops_permits, ops_health, ops_food_handler]

_port = config.process_port("ops")
bureau = Bureau(agents=OPS_AGENTS, port=_port, endpoint=f"http://127.0.0.1:{_port}/submit")

if __name__ == "__main__":
    for agent in OPS_AGENTS:
        print(f"{agent.name}: {agent.address}")
    print(f"(never started) ops_insurance address: {config.AGENT_ADDRESSES['ops_insurance']}")
    print("Spans are written to ./uagents_trace.db (override with UAGENTS_TRACE_DB)")
    bureau.run()
