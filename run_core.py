"""Process A: parser, payment_gate, orchestrator, the four leads,
assembler, qa_critic, delivery -- everything in the core pipeline except
the leaf workers and `gateway` itself.

`gateway` runs standalone in run_gateway.py, not here -- a Bureau's shared
REST endpoints (e.g. /agent_info, which the Agentverse inspector needs)
can't disambiguate between agents sharing its port without a header the
inspector page doesn't send, and gateway is the one agent that needs the
inspector to work. See AGENTVERSE.md.

Run this alongside run_gateway.py / run_creative.py / run_market.py /
run_ops.py. Spans are written to ./uagents_trace.db (override with
UAGENTS_TRACE_DB) -- point all five processes at the same file to see one
trace span the whole system.
"""

from uagents import Bureau

import config
from agents.assembler import assembler
from agents.delivery import delivery
from agents.leads.brand import brand_lead
from agents.leads.content import content_lead
from agents.leads.market import market_lead
from agents.leads.ops import ops_lead
from agents.orchestrator import orchestrator
from agents.parser import parser
from agents.payment_gate import payment_gate
from agents.qa_critic import qa_critic

CORE_AGENTS = [parser, payment_gate, orchestrator, brand_lead, content_lead, market_lead, ops_lead, assembler, qa_critic, delivery]

bureau = Bureau(agents=CORE_AGENTS, port=config.process_port("core"), endpoint=f"http://127.0.0.1:{config.process_port('core')}/submit")

if __name__ == "__main__":
    for agent in CORE_AGENTS:
        print(f"{agent.name}: {agent.address}")
    print("Spans are written to ./uagents_trace.db (override with UAGENTS_TRACE_DB)")
    bureau.run()
