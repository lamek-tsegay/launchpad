# Agentverse registration: what's already true, what's a real decision

**Current status: `config.MAILBOX_AGENTS` defaults to all 32 running
agents** (see "Rollout: all 32 running agents" below) — this document
started with a gateway-only recommendation, verified the latency concern
that drove it empirically rather than assuming it, found the concern
didn't hold, and widened the rollout as a result. The sections below are
left in their original order (including the original recommendation) since
the reasoning trail is worth keeping; the "Rollout" and "Not done"
sections nearer the bottom are the ones describing current behavior.

## Two different things, easy to conflate

1. **Almanac registration** ("visible, `status: active`"). Automatic,
   already happening, free. Any agent constructed with a non-empty
   `endpoint` — which is every agent `config.build_agent()` makes today —
   registers itself with Agentverse's Almanac API in the background, no
   `AGENTVERSE_API_KEY`, no manual step. Confirmed live, not from docs:

   ```
   $ ./.venv/bin/python3 run_all.py
   ...
   AGENT                     PROCESS   LOCAL   AGENTVERSE       NOTES
   gateway                   core      alive   active (local)
   ... (all 32 running agents, same result)
   All 32 startable agents alive and Almanac-registered; ops_insurance intentionally down.
   ```

   Every one of the 32 running agents already shows `active` — this is
   what `run_all.py` checks. `"type": "local"` in the raw response is the
   tell: Agentverse knows the agent exists and last re-registered
   recently, but the endpoint it has on file is `http://127.0.0.1:81xx`,
   useless to anything outside this machine. **"Registered and Active in
   the Almanac" does not require mailbox and is not the open question.**

2. **Mailbox / real chat-reachability.** This is the actual decision.
   `mailbox=True` is what lets an agent receive a message that
   *originates outside this machine* — specifically, a `ChatMessage` from
   ASI:One's UI relayed through Agentverse. An agent only needs this if
   something outside the four local processes is meant to talk to it
   directly. In this system, that's `gateway`, and only `gateway` — every
   other agent's "sender" is always another Launchpad agent that already
   knows its address via `config.py`.

## The tradeoff, stated plainly

**Recommendation: mailbox `gateway` only. Leave the other 32 exactly as
validated.**

| | All 33 on mailbox | `gateway` only (recommended) |
|---|---|---|
| Agentverse dashboard | all 33 show connected/reachable | 1 shows connected/reachable, 32 show Almanac-`active` (already true today) |
| Internal hop transport | every hop (`brand_lead`→`brand_name`, `market_lead`→`market_competitor_finder`, ...) relays through Agentverse's mailbox | unchanged — local `RulesBasedResolver` over loopback HTTP, exactly what's in `FINDINGS.md` |
| Added latency per internal hop | Agentverse mailbox polls every `MAILBOX_POLL_INTERVAL_SECONDS = 1.0` (uAgents' own constant) + two real internet round trips (sender POST, receiver poll) — realistically **~100ms–2000ms per hop**, replacing today's ~10–30ms local hops | none |
| Effect on `FINDINGS.md` | **Invalidates it.** Finding 3's whole analysis is about relative send/receive timing for a QA retry; finding 1's clean single-`trace_id` propagation was verified at local speeds. Both would need to be re-run and re-written against materially different, network-jitter-dependent numbers. | none — every recorded trace ID and latency stays reproducible |
| Effect on item 3's reproducibility goal | Directly works against it — network jitter and 1s poll-interval quantization mean identical inputs stop producing comparable traces | preserved — only the LLM-call cache (already deterministic-on-purpose) affects reproducibility |
| Setup cost | 33 `register_in_agentverse()` calls (scriptable with one `AGENTVERSE_API_KEY`, not 33 manual browser clicks — see below) | 1 call |
| What it's *for* | Making every internal worker independently addressable/chattable from outside — nothing in this system's design wants that; `market_scout_3` isn't a product | Matches the actual product surface: one chat agent, 32 backend workers |

`dispatcher.contains()` (finding 5's `registered=True/False/None` question)
is **unaffected either way** — it's a check against the current process's
local dispatch table, unrelated to mailbox vs. endpoint transport. Worth
having asked, but it turns out not to be a live concern.

## Feasibility correction

Initially assumed "connect to Agentverse" meant a manual per-agent
browser action (the mailbox poll loop's own error message points at "the
agent inspector"). Checking `uagents/mailbox.py` directly: the connect
flow is a plain importable async function,
`register_in_agentverse(request, identity, prefix, agentverse, agent_details)`,
authenticated with one Bearer token (`user_token` — your personal
`AGENTVERSE_API_KEY`). So **both options are equally scriptable** — this
isn't a 32-vs-1-manual-click tradeoff, it's purely about what routing
through Agentverse costs the rest of the system once agents are on it.

## Implemented

Confirmed: gateway-only mailbox, plus fixing `delivery`'s external-user gap
in the same pass.

1. **`config.py`**: the single global `MAILBOX_MODE` bool is now a
   per-agent set, `MAILBOX_AGENTS = {"gateway"}` (override with
   `LAUNCHPAD_MAILBOX_AGENTS`, comma-separated, `""` for none).
   `build_agent(name)` branches on `name in MAILBOX_AGENTS`.

2. **`payment_gate` → `gateway` was briefly a non-issue, then became a real
   one once gateway moved to its own process (see "gateway's own process"
   below).** Originally assumed `payment_gate`'s `RulesBasedResolver`
   having no rule for a mailbox-only `gateway` would break their Payment
   Protocol exchange. Checked `uagents/context.py`'s `send_raw`: `if
   dispatcher.contains(parsed_address): result = await
   dispatch_local_message(...)` runs **before the configured resolver is
   ever consulted** — and at the time, `payment_gate` and `gateway` were
   both hosted by `run_core.py`'s one `Bureau`, i.e. the same OS process,
   i.e. the same `dispatcher`, so that send always short-circuited to an
   in-memory call regardless of `gateway`'s mailbox setting. Confirmed
   live at the time: sub-10ms latencies, `dest_registered: True`.

   That stopped being true the moment `gateway` was pulled into its own
   process (see "gateway's own process" below) -- `dispatcher.contains()`
   now correctly returns `False` for it from `payment_gate`'s side, a
   genuine cross-process edge like any other in `FINDINGS.md`. It didn't,
   however, end up needing the `GlobalResolver` fallback described next:
   `_RESOLVER_RULES` (`config.py`) includes **every** started agent's real
   local route, `gateway` included, via `local_endpoint()` -- regardless
   of `MAILBOX_AGENTS` membership. Mailbox is about how a genuinely
   external ASI:One user reaches `gateway` (they have no way to know
   about this machine's loopback address); it says nothing about how
   Launchpad's own other agents should reach it, and there's no reason
   for `payment_gate`'s side of the Payment Protocol conversation to
   depend on a live Agentverse mailbox connection when a fast, reliable
   local route is right there. So `payment_gate -> gateway` still
   resolves instantly over plain loopback HTTP; only `dest_registered`
   changed (`True` -> `False`), not the transport. Re-confirmed on a live
   paid-tier run (trace `cb2e5079-e49b-4394-833c-692deae2814e`): ladder
   still completes correctly. See `FINDINGS.md` finding 5's update for
   the exact span numbers.

   `delivery` → `chat_sender` is the one edge that's genuinely different.
   It sends the final reply to whatever address was on the original
   inbound `ChatMessage` — for a **real** ASI:One user, that address was
   never going to be in `_RESOLVER_RULES` at all (we don't control it the
   way we control our own five processes' topology), so this is the one
   case that actually needs to fall through to `GlobalResolver`. This was
   latent in the system already, unrelated to the mailbox decision — it
   just never showed up because all five scripted scenarios reuse the
   same pre-registered test identity (`user_proxy`, which *is* in the
   local table).

   **Implemented**: every agent gets the same `_FallbackResolver`
   (`config.py`): the local rules table (now including `gateway`) first,
   falling back to uAgents' `GlobalResolver` only for an address the
   table doesn't know about at all. For every agent except `delivery`,
   the fallback branch is dead code in practice -- every real destination
   they ever address is already in the table. For `delivery`, it's the
   actual fix: a real external chat user now resolves via Almanac instead
   of failing immediately.

3. **`run_all.py`**: now checks each agent's Almanac `type` against what
   it should be (`mailbox` for `MAILBOX_AGENTS`, `local` for everyone
   else), not just whether it's registered at all — `type` takes one
   registration cycle to flip after a config change, so a plain
   "registered: yes/no" check would have reported `gateway` as fine while
   it was still advertising a stale local endpoint. Verified live:
   `gateway` now shows `active (mailbox)` in the Almanac, every other
   agent shows `active (local)`, matching `MAILBOX_AGENTS` exactly.

## gateway's own process

Fixed a second, separate bug the inspector "Connect" step surfaced:
`gateway` originally ran inside `run_core.py`'s `Bureau` alongside 10
other agents, all sharing one port (8101). A `Bureau`'s REST endpoints
(`/agent_info`, `/connect`, `/disconnect` — what the inspector calls) are
shared across every agent it hosts, disambiguated only by an
`x-uagents-address` header the inspector page never sends:

```
$ curl http://127.0.0.1:8101/agent_info
{"error": "missing header: x-uagents-address", "message": "Multiple handlers found for REST endpoint."}
$ curl -H "x-uagents-address: agent1qgsf9hl..." http://127.0.0.1:8101/agent_info
200, gateway's real info
```

— so the inspector's Connect button couldn't find `gateway` at all, not
because it wasn't registered, but because the endpoint it was calling
gave a 400 with no way for a plain browser request to supply that header.

**Fixed**: `gateway` now runs standalone in `run_gateway.py`, its own
process, port **8100** (the other 10 core agents stay in `run_core.py`'s
Bureau on 8101, unaffected — same fix pattern would apply to any of them
if one ever needed the inspector too, but none do). Its declared port
also now matches what it actually listens on (`config.build_agent` passes
`port=` explicitly for every agent, not just `gateway` — the same
`/agent_info`-reports-8000-while-really-listening-elsewhere gap existed
for all 32 Bureau-hosted agents too, harmless there since nothing calls
their `/agent_info`, but cheap to fix uniformly). Seed unchanged, so the
Almanac-registered address (`agent1qgsf9hl...`) is exactly the same as
before — everything downstream that references it required no changes.

Verified: `curl http://127.0.0.1:8100/agent_info` with **no** header now
returns `200` and `gateway`'s info directly (`"port": 8100`, matching);
`run_all.py` reports all 32 agents alive across 5 processes, `gateway`
`active (mailbox)`, `ops_insurance` intentionally down; `scenarios/
food_truck.py` still completes end to end with a single `trace_id`
(`cb2e5079-e49b-4394-833c-692deae2814e`). The anti-echo cooldown/dedup
state in `agents/gateway.py` (`_last_reply_time`, `_seen_texts`) is a pair
of plain module-level dicts with no cross-agent or Bureau-specific
assumptions — moving `gateway` to its own process doesn't change how that
state is scoped or accessed, and the regression run above exercised it
without incident.

## Rollout: all 32 running agents (verified before rolling out, not assumed)

The tradeoff at the top of this document recommended gateway-only,
specifically over a latency concern: mailbox routes an agent's *inbound*
reachability through Agentverse, and the worry was that would drag every
internal hop through it too. That concern turned out not to apply, and
`config.MAILBOX_AGENTS` now defaults to all 32 running agents (still
excludes `ops_insurance`, which never starts).

**What changed the analysis**: `_RESOLVER_RULES` (`config.py`) gives every
agent a real local route via `local_endpoint()` *regardless of
MAILBOX_AGENTS membership* — this was already true for `gateway` (see
"gateway's own process" above) and applies identically to every other
agent. Adding an agent to `MAILBOX_AGENTS` only changes what a real
*external* caller is told to use to reach it; Launchpad's own
agent-to-agent traffic never consults `GlobalResolver` for a destination
that's already in the local table, mailbox or not.

**Verified, not assumed, before rolling out further than `gateway`.**
Added `parser` to `MAILBOX_AGENTS` alone first (`LAUNCHPAD_MAILBOX_AGENTS=gateway,parser`)
and re-ran a scenario:

| | `parser` local-only | `parser` mailbox-enabled |
|---|---|---|
| `gateway -> parser` send-ack latency | 75ms | 7ms |
| `dest_registered` | `False` (cross-process, unchanged) | `False` (cross-process, unchanged) |

Both solidly in loopback-HTTP range, nowhere near what an actual ~1s
Agentverse mailbox poll + real round trip would cost. Confirmed the same
holds at full scale: rolled `MAILBOX_AGENTS` out to all 32, re-ran the
full paid-tier pipeline (143 spans, same shape as every prior FINDINGS.md
run) — every cross-process send-ack latency stayed under 650ms, most
under 10ms; single `trace_id` preserved end to end.

Verified separately: `Bureau.run_async()` unconditionally starts
`self._server.serve()` before checking any agent's mailbox status — a
Bureau's shared local HTTP server keeps running even if *every* agent it
hosts is mailbox-enabled, so this holds for the 9-, 7-, and 5-agent
Bureaus (`run_creative.py`/`run_market.py`/`run_ops.py`) exactly as it
does for `run_core.py`'s 10.

`run_all.py`'s status table already distinguished `active (mailbox)` from
`active (local)` per agent generically (built that way from the start,
for whatever `MAILBOX_AGENTS` happens to contain) — no changes needed
there for the wider rollout; it now just shows 32 `active (mailbox)` rows
instead of 1.

## Not done — needs your own Agentverse credentials

**The actual "connect" step, for all 32.** Everything above makes every
agent *capable* of mailbox reachability and Almanac-visible as
`active (mailbox)`, and makes local testing not depend on any of it, but
none of them have been introduced to Agentverse yet — each one's
`MailboxClient` is currently logging "Agent mailbox not found: create one
using the agent inspector" on every poll. This is the one part of Task 4
I could not do myself: this environment has no `AGENTVERSE_API_KEY`, and
connecting an agent's mailbox requires your own account's credentials —
not something I should ask you to paste into chat either way. Two ways to
finish this, both yours to run:

- **Scripted (`agentverse_connect.py`, built and ready)**:

  ```bash
  export AGENTVERSE_API_KEY=...          # from your Agentverse account's API key settings
  ./.venv/bin/python3 agentverse_connect.py --dry-run   # see who it would connect, no API calls
  ./.venv/bin/python3 agentverse_connect.py             # connects all 32 -- reuses uAgents' own /connect handler
  ```

  Doesn't need any of the five Launchpad processes running -- constructs
  each agent in-process just long enough to run its own `/connect` logic,
  then exits. Idempotent, safe to re-run. **I built this from reading
  `uagents/mailbox.py`'s `register_in_agentverse` and the same `/connect`
  REST handler the agent inspector's button calls, but have not been able
  to run it end to end myself** — no key in this environment. `--dry-run`
  (no API calls) and `--only <names>` (connect a subset) both work today,
  confirmed; the actual `AGENTVERSE_API_KEY`-authenticated path is
  untested by me. Recommend trying `--only parser` first before the full
  32-agent batch.

- **Agent inspector (browser, one agent at a time)**: with the relevant
  process running, visit
  `https://agentverse.ai/inspect/?uri=http%3A%2F%2F127.0.0.1%3A<port>&address=<address>`
  (`run_all.py --status` prints this link for every `MAILBOX_AGENTS`
  member, not just `gateway`, now), log in, click connect. Fine for
  `gateway` alone; tedious for 32 -- the script above exists specifically
  so you don't have to do this 32 times.

Until one of those happens, all 32 are Almanac-visible (`active
(mailbox)`, confirmed above) but not yet actually receiving anything
Agentverse relays to them — see the testing walkthrough for exactly what
that looks like broken vs. working.
