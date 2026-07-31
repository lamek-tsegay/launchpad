"""Process A0: gateway alone, standalone (not in a Bureau).

Split out from run_core.py so gateway's REST endpoints (/agent_info,
/connect, /disconnect -- what the Agentverse inspector calls) resolve
without ambiguity. A Bureau serves one shared set of REST routes for every
agent it hosts, disambiguated only by an `x-uagents-address` header on the
request; the Agentverse inspector page doesn't send that header, so its
"Connect" button can't find an agent sharing a Bureau's port at all
(confirmed: `curl http://127.0.0.1:8101/agent_info` from when gateway was
still in run_core.py's Bureau returned 400 "Multiple handlers found for
REST endpoint" with no header, 200 with one). gateway is the only agent
that ever needs the inspector, so it's the only one pulled out --
everyone else stays in their existing Bureau.

gateway's seed (and therefore its Almanac-registered address) is
unchanged -- config.py derives it the same way regardless of which
process constructs it.

Run this alongside run_core.py / run_creative.py / run_market.py /
run_ops.py. Spans are written to ./uagents_trace.db (override with
UAGENTS_TRACE_DB) -- point all five processes at the same file to see one
trace span the whole system.
"""

import config
from agents.gateway import gateway

if __name__ == "__main__":
    print(f"gateway (chat entry point) address: {gateway.address}")
    print(f"gateway local port: {config.process_port('gateway')}")
    print("Spans are written to ./uagents_trace.db (override with UAGENTS_TRACE_DB)")
    gateway.run()
