# Launchpad

A ~33-agent [uAgents](https://github.com/fetchai/uAgents) system that turns a
one-line business idea into a starter kit (brand, website copy, market scan,
compliance checklist), built specifically to stress-test
[`uagents-trace`](../uagents-trace) — a passive observability tool that
records a span for every inter-agent message.

Wherever "simpler" and "produces a more interesting trace" were in tension,
this system chose the latter, but every fan-out, retry, and failure here is
real system behavior, not a debug flag. `FINDINGS.md` is the actual output of
the exercise: what the tracer got right, and where it didn't match what the
system actually did.

## Layout

```
launchpad/
  config.py            seeds, addresses, ports, resolver, FAILURES, tier gates
  shared_models.py      per-hop Request/Response pairs
  llm.py / llm_cache.py ASI:One client + disk cache
  worker_common.py       shared LLM-call/fallback/failure-injection runner
  agents/
    gateway.py parser.py payment_gate.py orchestrator.py
    assembler.py qa_critic.py delivery.py
    leads/       brand.py content.py market.py ops.py  (+ _common.py)
    workers/     brand.py content.py market.py ops.py   (21 leaf workers)
  run_gateway.py    process A0: gateway alone, standalone (see AGENTVERSE.md)
  run_core.py       process A: everything else above except leaf workers
  run_creative.py   process B: brand + content leaf workers
  run_market.py     process C: market leaf workers (incl. competitor/scout depth)
  run_ops.py        process D: ops leaf workers
  run_all.py        bring up all 5 processes + status table, one command
  scenarios/         scripted chat inputs, one per trace shape
  FINDINGS.md  AGENTVERSE.md
```

## Roster

Process A0 (`run_gateway.py`): `gateway` -- alone, standalone (not in a
Bureau). A Bureau's shared REST endpoints (`/agent_info`, which the
Agentverse inspector calls) can't disambiguate between agents sharing its
port without a header the inspector doesn't send; `gateway` is the only
agent that needs the inspector to work, so it's the only one pulled out.
See `AGENTVERSE.md`.

Process A (`run_core.py`): `parser`, `payment_gate`, `orchestrator`,
`brand_lead`, `content_lead`, `market_lead`, `ops_lead`, `assembler`,
`qa_critic`, `delivery`.

Process B (`run_creative.py`): `brand_name`, `brand_palette`,
`brand_logo_brief`, `brand_voice`, `content_hero`, `content_about`,
`content_services`, `content_faq`, `content_email`.

Process C (`run_market.py`): `market_competitor_finder`, `market_scout_1..3`,
`market_pricing`, `market_seo`, `market_ad_copy`.

Process D (`run_ops.py`): `ops_entity`, `ops_tax`, `ops_permits`,
`ops_health`, `ops_food_handler`.

`ops_insurance` is deliberately never started by any process — its address
and Request/Response pair exist, and `ops_lead` addresses it under
food/retail business types, but nothing ever answers. That's intentional
(see `config.FAILURES` and `FINDINGS.md`).

## Flow

```
user --chat--> gateway --> parser --> payment_gate --> orchestrator
                                                            |
                        brand_lead   content_lead   market_lead   ops_lead
                         4 workers    5 workers     competitor_finder   N workers
                                                       -> 1-3 scouts    (N by business_type)
                                                            |
                                                        assembler --> qa_critic
                                                                          |
                                                                    (retries loop
                                                                     back to leads)
                                                                          |
                                                                      delivery --> user
```

`delivery` replies directly to the original chat sender (threaded through
`intake["chat_sender"]`), not back through `gateway` — matching the flow
above. Depth on the market branch is four hops below `gateway`: `gateway ->
orchestrator -> market_lead -> market_competitor_finder -> market_scout_N`.

## Setup

```bash
cd launchpad
python3.12 -m venv .venv
./.venv/bin/pip install -e ../uagents-trace
./.venv/bin/pip install openai
```

Requires uAgents' resolver strategy documented below — no Agentverse account
or funded wallet needed for local runs (see "How cross-process delivery
works").

Optional: `export ASI1_API_KEY=...` to exercise real ASI:One calls. Without
it every worker call raises immediately and falls through to its
deterministic fallback (`used_fallback=True`) — the pipeline still runs
end-to-end, it just never produces LLM-generated copy. All trace runs
referenced in `FINDINGS.md` were captured this way (no key configured in the
build environment). Model defaults to `asi1-extended` (larger/more capable
than `asi1-mini`, since call cost isn't a constraint here) — override with
`ASI1_MODEL` if your account's catalog differs; see `llm.py`.

Want `gateway` reachable from a real ASI:One conversation, not just the
scripted `scenarios/*.py`? See `AGENTVERSE.md` — one extra one-time step
with your own Agentverse credentials, not part of this Setup block since
it needs an account this repo doesn't have.

## Running

One command brings up all five processes and confirms every agent is alive
(process listening) and Agentverse-registered (`status: active` in the
public Almanac -- automatic, see `AGENTVERSE.md`, no API key needed for
this part):

```bash
export UAGENTS_TRACE_DB=$(pwd)/uagents_trace.db   # same file for all 5 + scenarios
./.venv/bin/python3 run_all.py            # start + verify, prints a status table, then exits (processes keep running)
./.venv/bin/python3 run_all.py --status   # re-check without restarting
./.venv/bin/python3 run_all.py --stop     # stop everything it started
```

Or start them individually (five terminals) if you want each process's own
logs inline instead of redirected to `.run_all_logs/`:

```bash
./.venv/bin/python3 run_gateway.py
./.venv/bin/python3 run_core.py
./.venv/bin/python3 run_creative.py
./.venv/bin/python3 run_market.py
./.venv/bin/python3 run_ops.py
```

Once everything is up, run a scenario:

```bash
./.venv/bin/python3 scenarios/food_truck.py
```

Then inspect the trace:

```bash
./.venv/bin/uagents-trace list
./.venv/bin/uagents-trace show <trace_id>
```

`scenarios/*.py` use a fixed-identity `user_proxy` (config.py) as the chat
sender, standing in for a real ASI:One user. Because `gateway` enforces a
30s per-sender cooldown (anti-echo, spec section 8) and `user_proxy`'s
identity is deterministic across runs, **wait at least 30s between scenario
runs** or the second message is silently dropped after being acked (this is
the cooldown working as designed, not a bug — see `FINDINGS.md`).

### Demo mode

`LAUNCHPAD_MODE=demo` (default `live`) changes how much real work happens,
never the shape of the system: same 33 agents, same 5 processes, same
topology (including `competitor_finder -> scouts` depth), same
business-type/scout-count/paid-unpaid variance, same QA retry loop, same
three failure modes, same Payment Protocol. In demo mode, workers skip
ASI:One entirely (straight to their deterministic fallback -- the same
path live mode takes on any LLM failure, just always taken here) and
sleep a small per-worker-jittered interval (~80-250ms) instead, so the
waterfall still shows realistic spread instead of collapsing to a few
milliseconds per hop. `brand_logo_brief`'s `slow` failure mode is scaled
down alongside it (2.0s sleep vs. a 1s send-side timeout, same
sleep-exceeds-timeout relationship as live mode's 12s/10s) so it's still a
clear, visible outlier in the trace without dominating the run:

```bash
export LAUNCHPAD_MODE=demo LAUNCHPAD_FAILURES='{}'   # all 5 processes
./.venv/bin/python3 run_all.py
./.venv/bin/python3 scenarios/food_truck.py
```

A full paid food-truck run completes in ~2-4s wall clock this way (measured,
not estimated), comfortably under the 15s target. QA's retry loop needs no
demo-specific scoring: `qa_critic.score_section` was already a pure,
deterministic function of content length and `used_fallback`, and three
sections (`brand.name`, `content.faq`, `content.services`) have fallback
content short enough to fail the rubric regardless of scenario input text
-- demo mode forcing every worker into fallback makes the existing retry
path fire reliably for free, nothing new was needed there.

`LAUNCHPAD_MODE=live` (the default, unset) is unchanged from before this
existed -- `SEND_TIMEOUT_SECONDS`/`SLOW_FAILURE_SLEEP_SECONDS` just resolve
to the same 10/12 values every send already used implicitly.

### Failure injection

`config.FAILURES` defaults to:

```python
{"ops_insurance": "unreachable", "brand_logo_brief": "slow", "market_scout_3": "raises"}
```

Override per-launch with `LAUNCHPAD_FAILURES='{}'` (the four worker-hosting
processes -- `run_gateway.py` doesn't read `FAILURES` at all) for a
clean run, or a custom JSON dict to target different workers. The default
combination is what `scenarios/failures_enabled.py` expects, and it does
**not** produce a final reply — see `FINDINGS.md` for why that's the correct
outcome, not a bug.

### Payment tier / amount

Scenario chat text carries two plain markers the parser strips out before
further processing: `tier=paid` / `tier=unpaid` (default unpaid) and
`amount=<number>` (default `5.0`, `gateway`'s policy max is `10.0` — set a
higher amount to trigger the reject branch).

## How cross-process delivery works

31 of the 32 running agents route messages through a `RulesBasedResolver`
(`config.py`) built from a fixed seed -> address -> `http://127.0.0.1:PORT`
table, rather than Almanac/mailbox lookups — this is what keeps every trace
in `FINDINGS.md` fast and reproducible. `gateway` is the one exception:
`config.MAILBOX_AGENTS` (default `{"gateway"}`, override with
`LAUNCHPAD_MAILBOX_AGENTS`) gives it a real Agentverse mailbox instead, so
it's reachable from outside this machine (hard constraint #6: never both
mailbox and endpoint on the same agent). Every agent's outbound resolver is
actually the same `_FallbackResolver` regardless — local table first,
falling back to uAgents' `GlobalResolver` for anything not in it, which
only ever matters for `delivery` replying to a real external chat user.
Full writeup, including what turned out *not* to need this (`payment_gate`
-> `gateway`, same-process local dispatch bypasses the resolver entirely):
`AGENTVERSE.md`.

## Notes on design choices worth knowing before reading the code

- **Payment Protocol counterparty**: the flow diagram draws `payment_gate`
  as a single hop between `parser` and `orchestrator`, but Payment Protocol
  messages need two parties. `gateway` plays buyer (proxying "the user"),
  `payment_gate` plays seller — both already in the roster, so no new agent
  was added. A rejected payment still reaches `orchestrator`, downgraded to
  unpaid features, rather than aborting the run.
- **Retry routing bypasses intermediate hops**: `qa_critic` re-dispatches a
  failing section straight to *the originating lead*, which re-dispatches to
  *the same worker* — skipping `market_competitor_finder` even for a retried
  scout section, since the spec's rule is "same worker," not "same path."
- **Unresolvable destinations don't hang a lead forever**: a lead treats an
  immediately-unresolved send (`"resolve" in error detail`, i.e.
  `ops_insurance`) as "this section is unavailable" and moves on, rather
  than waiting on a reply that structurally cannot arrive. A *slow* reply
  (`brand_logo_brief`) is not treated this way — the lead keeps waiting past
  `traced_send`'s own 10s timeout, because that reply really may still show
  up. A *raised* reply (`market_scout_3`) can't be distinguished from
  "still working" by the sender at all, so that branch genuinely stalls —
  see `FINDINGS.md`.
