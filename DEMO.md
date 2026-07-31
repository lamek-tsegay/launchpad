# Running the Launchpad demo

Two terminals, one browser tab. Read the "Before you go on stage" section
at least once, in advance — it's the one part of this that needs your own
Agentverse account and can't be dry-run the night before a demo.

## Before you go on stage (do this once, ahead of time, not live)

`gateway` needs a real, *connected* Agentverse mailbox for ASI:One to
reach it at all — `mailbox=True` alone gets it Almanac-registered
(automatic, already working), but the actual mailbox has to be created
once against your account. If this was never done:

```bash
cd /Users/lamek/launchpad
export AGENTVERSE_API_KEY=...     # from your Agentverse account -> Profile -> API Keys
./.venv/bin/python3 agentverse_connect.py --only gateway
```

Then confirm it live: run `./.venv/bin/python3 run_all.py --demo` (below),
open the inspector link it prints for `gateway`, and check it shows
connected in the Agentverse UI — not "Agent mailbox not found." This step
needs your own account either way; nothing in this repo can do it for you
or verify it without your credentials. Do this well before the demo, not
as the first step on stage.

## 1. Start Launchpad

From a clean shell (nothing pre-exported):

```bash
cd /Users/lamek/launchpad
./.venv/bin/python3 run_all.py --demo
```

One command. It stops anything stale left over from a previous run,
starts all 5 processes in demo mode (fast — full run in a few seconds,
not real ASI:One-call latency) with `ops_insurance` as the one visible,
explained failure (structurally never started, not gated by any flag) and
everything else configured to complete cleanly — no `market_scout_3`
stall. Mailbox is scoped to `gateway` only, so it's the *only* agent that
shows up as chat-reachable; the other 31 stay Almanac-visible but
non-chat.

**Expect**, after ~15-20s: a status table ending in `All 32 startable
agents alive and Almanac-registered; ops_insurance intentionally down.`,
followed by:

```
========================================================================
ASI:One entry point -- this is the only chat-addressable agent.
  Search Agentverse/ASI:One for: launchpad-demo-gateway
  Address (unambiguous fallback): agent1qgsf9hl...
========================================================================
```

Copy the address (or note the handle) — you'll need it in step 3.

**If a row shows `DOWN`** (other than `ops_insurance`, which is supposed
to): check `.run_all_logs/<process>.log` for a traceback. **If a row
shows `NOT REGISTERED`**: usually clears on its own within the 5 retry
rounds this script already does; if it's still showing after the command
finishes, check network access to agentverse.ai.

## 2. Start the tracer

Second terminal:

```bash
cd /Users/lamek/launchpad
export UAGENTS_TRACE_DB=$(pwd)/uagents_trace.db
uagents-trace
```

If you've run this before, it resumes your saved setup automatically —
no prompts. (First time ever, or if you want to reconfigure which agents
it watches: `uagents-trace --setup`.)

**Expect**: the splash screen, then the live diagram — empty, waiting for
a trace. Leave this running; you'll watch step 3 build here live.

## 3. Send a real message from ASI:One

Open ASI:One in your browser (your own session — not something this repo
can link you to). Find `gateway` using the handle or address from step 1.
Send a real business idea, e.g.:

> I want to start a food truck serving Ethiopian food in Austin, Texas.

**Expect**, within a few seconds: `gateway` acks the message (you'll see
it in ASI:One), then — once the pipeline finishes — a full starter kit
(Brand / Website Copy / Market Scan / Compliance Checklist) posted back
**in the ASI:One chat window itself**, not just logged somewhere.

**What's verified vs. what's on you**: the pipeline handling a sender
that isn't the local `user_proxy` test identity — resolving via
`GlobalResolver`/Almanac instead of the local address table, `delivery`
addressing its reply correctly, the trace tool rooting correctly at a
sender with no send-side span of its own — all of that was verified this
session against a fresh, real, unregistered identity end to end
(`scenarios/external_sender.py`, reusable any time you want to re-check
this without ASI:One at all). What's specifically *not* verified, because
it needs a real Agentverse mailbox and a real ASI:One session neither of
which exist in this environment: the actual cross-machine relay through
Agentverse. That's the "before you go on stage" step above — do it ahead
of time.

**If nothing comes back**: check terminal 2 — the trace should already be
building (see step 4) even before the final reply lands, which tells you
whether the pipeline is running at all. If terminal 2 shows *nothing*,
the message never reached `gateway` — re-check the address/handle and the
mailbox connection from "before you go on stage." If terminal 2 shows the
trace building but ASI:One never gets the reply, the pipeline completed
locally but the reply couldn't relay back out — also a mailbox/connection
issue, not a pipeline one.

## 4. Watch it build live

Back in terminal 2 (from step 2): the sidebar gets a new row within
~3s of the message landing, and the diagram — **overview** by default —
starts filling in as spans arrive: boxes appearing left to right by
causal depth (`gateway → parser → payment_gate → orchestrator → 4 leads →
their own workers → ...`), each getting its own ✓/✗ and latency once its
call resolves.

**Expect**, once the run completes: all ~34 boxes on screen (scroll with
arrow keys / mouse wheel — both axes work, nothing is ever cut off to
make it fit), `ops_insurance` the one box reading `✗` with "Unable to
resolve destination endpoint", everything else `✓`. Press `v` to cycle to
**tree** (exact causal chain, full depth, useful if someone asks "wait,
how did it get from X to Y") or **linear** (the original hub-legs
waterfall). Click any box for its full detail — payload, timing,
delivery — in the right-hand panel; the overview itself deliberately
shows no payload text, just structure and outcome.

## Verification checklist

- [ ] `run_all.py --demo` completes with all 32 alive, `ops_insurance` intentionally down
- [ ] Gateway's handle/address printed clearly
- [ ] `uagents-trace` resumes with no prompts
- [ ] ASI:One message reaches `gateway` and the starter kit posts back in the chat window
- [ ] The live trace shows all ~34 boxes, `ops_insurance` the one clear failure
- [ ] `v` cycles overview → tree → linear and back
- [ ] Full test suite green: `cd /Users/lamek/uagents-trace && .venv/bin/python -m pytest -q` (181 passing as of this writing)

## Cleanup

```bash
cd /Users/lamek/launchpad
./.venv/bin/python3 run_all.py --stop
```
