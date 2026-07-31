# FINDINGS

What `uagents-trace` actually showed for each of the six questions posed in
the build spec, against real runs of Launchpad. No ASI1_API_KEY was
configured in the build environment, so every LLM call in every run below
raised immediately and fell through to its deterministic fallback
(`used_fallback=True` everywhere) — noted once here rather than on every
finding, since it doesn't change any of the answers below (the tracer
observes message flow, not content quality).

All runs used `UAGENTS_TRACE_DB=launchpad/uagents_trace.db`. Reproduce with
`./.venv/bin/uagents-trace show <trace_id>` or by querying
`uagents_trace.store.get_trace_spans` directly (used below for anything the
CLI's `show` doesn't surface — see finding 6).

---

## 1. One `trace_id` across four processes and four levels of nesting?

**Yes, cleanly.** Reference run: `scenarios/food_truck.py` (paid, food —
the widest fan-out this system produces), trace
`6978d754-fe31-4aef-874f-aa2e9bd61788`.

- 143 spans, 33 participants, every one of them under this single
  `trace_id` — `gateway`/`parser`/... in process A, all 9 brand+content
  workers in process B, all 7 market workers (including the scout layer)
  in process C, all 5 running ops workers in process D, plus the
  never-started `ops_insurance`'s address and the `user_proxy` test client.
- The scenario client independently confirms this from the outside: the
  `ctx.session` on its *outbound* send to `gateway` and the `ctx.session`
  on the *inbound* final `ChatMessage` it receives back from `delivery`
  (a different process entirely, four hops away) are identical.
- uAgents' session propagation (which `uagents-trace` trusts as `trace_id`,
  per `recorder.py`'s own docstring) held through every hop this system
  exercises: chat -> parse -> pay -> orchestrate -> fan out to 4 leads ->
  fan out to leads' own workers -> nested fan-out to scouts -> QA retry
  round-trips back through leads -> final reply. This was the single
  biggest open risk called out in the build spec (section 8, stage 3) and
  it did not materialize as a problem.

## 2. Does the market branch classify as `multi_level`, and does the tree render the scout layer?

**No — it classifies as `hub`, and the scout layer is invisible to `show`.**
Same trace as above; queried `classify_trace_shape` directly since the CLI
never got a chance to run it (finding 6 explains why).

```python
shape, hub = classify_trace_shape(spans)
# ('hub', 'agent1q2kprn...')  -- content_lead, not orchestrator or market_lead
```

Root cause, in `shape.py`: `classify_trace_shape` looks at the **whole
trace's flat span list**, finds the single busiest source by total send
count, and returns `HUB` if that one source has >=2 distinct destinations.
It never asks "is there nested depth *anywhere*" — it asks "is there one
dominant fan-out point." In this run, `content_lead` (5 distinct workers)
edges out `market_lead`/`market_competitor_finder` as the busiest single
source, so the whole 143-span trace — including the genuinely 4-level-deep
`market_lead -> market_competitor_finder -> market_scout_N` chain — gets
classified as a simple 2-level hub centered on `content_lead`.

This isn't specific to this one run's numbers: **any Launchpad trace with a
paid tier has at least one lead with >=2 workers**, so a hub-shaped
sub-structure always exists somewhere in the trace, and `MULTI_LEVEL` is
effectively unreachable for this system's traces. Per `shape.py`'s own
docstring, even a trace that *did* classify as `multi_level` gets no
dedicated tree renderer — `print_trace_detail` prints `"(multi-level trace,
showing flat view)"` and falls back to a flat span list. So there is no
code path in the CLI today that renders Launchpad's actual four-level
depth as a tree; the deepest structure it can show as a tree is `HUB`'s
one level of fan-out (`print_hub_tree`, with `--view tree`).

**Update: fixed, in the same pass that added `parent_span_id` (see item
3's update below for the full mechanism).** `classify_trace_shape` now
reads real depth off the causal tree instead of guessing from raw send
counts: `HUB` requires a genuinely flat, 2-level fan-out (the dispatcher's
own legs have no children of their own); anything deeper — including a
"hub" whose legs fan out further, exactly this system's shape — is
`MULTI_LEVEL`, and `MULTI_LEVEL` now gets the *same* tree renderer as
`HUB` (`--view tree` no longer requires `HUB` at all; the causal tree is
built independent of `shape`). Re-checked against a fresh capture of this
exact trace shape (`f5cf024c-574c-48ee-b611-c52512669765`,
`scenarios/food_truck.py`, 143 spans): `classify_trace_shape` now returns
`(multi_level, None)`, and `show --view tree` renders the real four-plus
level depth (`orchestrator → market_lead → market_competitor_finder →
market_scout_1/2/3`) instead of the old flat `content_lead`-centered
2-level guess. Regression tests:
`tests/test_shape.py::ClassifyTraceShapeWithParentageTests`.

## 3. Do QA retries render as two distinct hops with plausible latencies, or does send/receive matching cross them?

**In every real retry captured so far: two clean, correctly-ordered hops,
no crossing. But that's a property of Launchpad's own scheduling, not
evidence the matching algorithm is safe — a synthetic span set proves
`build_hops` *will* silently swap latencies (not just look wrong, actually
be wrong) the moment a retry is dispatched while the original attempt is
still outstanding.** Investigated using
`uagents_trace.store.get_trace_spans` + `uagents_trace.shape.build_hops`
directly against the DB (not `uagents-trace show`, since finding 6 means
`show` never gets far enough to run either function on this trace at all).

### Real data: three retries, three clean matches

Reference trace `6978d754-fe31-4aef-874f-aa2e9bd61788`
(`scenarios/food_truck.py`). `brand.name`, `content.faq`, and
`content.services` all scored below threshold on attempt 1 (all-fallback
content, matching `worker_common.run_worker`'s deterministic rubric input)
and were retried — `config.MAX_RETRIES_PER_RUN`'s cap of 3 bound exactly,
since more than 3 sections scored below 6. Raw spans for all three
`(source, dest, payload_type)` triples, request and response, ordered by
`enqueued_at`:

```
-- BrandNameRequest  brand_lead -> brand_name
  id=688dae8e  dir=send     state=delivered enq=1785474640512 ack=1785474640517  attempt=1
  id=593e01fb  dir=receive  state=delivered enq=1785474640518 ack=1785474640527  attempt=1
  id=44f92a1d  dir=send     state=delivered enq=1785474640822 ack=1785474640827  attempt=2
  id=06e51826  dir=receive  state=delivered enq=1785474640826 ack=1785474640840  attempt=2

-- BrandNameResponse  brand_name -> brand_lead
  id=63b4b7fe  dir=send     state=delivered enq=1785474640519 ack=1785474640523
  id=6f353f9e  dir=receive  state=delivered enq=1785474640548 ack=1785474640550
  id=26471a77  dir=send     state=delivered enq=1785474640827 ack=1785474640839
  id=feebca83  dir=receive  state=delivered enq=1785474640839 ack=1785474640845

-- ContentFaqRequest  content_lead -> content_faq
  send    enq=1785474640636 ack=1785474640645
  receive enq=1785474640645 ack=1785474640653
  send    enq=1785474640831 ack=1785474640835
  receive enq=1785474640835 ack=1785474640853

-- ContentFaqResponse  content_faq -> content_lead
  send    enq=1785474640647 ack=1785474640651
  receive enq=1785474640666 ack=1785474640667
  send    enq=1785474640837 ack=1785474640851
  receive enq=1785474640851 ack=1785474640853

-- ContentServicesRequest  content_lead -> content_services
  send    enq=1785474640629 ack=1785474640634
  receive enq=1785474640633 ack=1785474640642
  send    enq=1785474640824 ack=1785474640830
  receive enq=1785474640830 ack=1785474640837

-- ContentServicesResponse  content_services -> content_lead
  send    enq=1785474640635 ack=1785474640641
  receive enq=1785474640665 ack=1785474640665
  send    enq=1785474640832 ack=1785474640836
  receive enq=1785474640840 ack=1785474640843
```

`build_hops(spans)` output for the same six pairs (12 hops total — 2 per
pair, matching the 2 send-spans per pair, so hop count == logical message
count in every case):

```
BrandNameRequest       enq=1785474640512 ack=1785474640527 latency_ms=15
BrandNameResponse      enq=1785474640519 ack=1785474640550 latency_ms=31
BrandNameRequest       enq=1785474640822 ack=1785474640840 latency_ms=18
BrandNameResponse      enq=1785474640827 ack=1785474640845 latency_ms=18
ContentFaqRequest      enq=1785474640636 ack=1785474640653 latency_ms=17
ContentFaqRequest      enq=1785474640831 ack=1785474640853 latency_ms=22
ContentFaqResponse     enq=1785474640647 ack=1785474640667 latency_ms=20
ContentFaqResponse     enq=1785474640837 ack=1785474640853 latency_ms=16
ContentServicesRequest enq=1785474640629 ack=1785474640642 latency_ms=13
ContentServicesRequest enq=1785474640824 ack=1785474640837 latency_ms=13
ContentServicesResponse enq=1785474640635 ack=1785474640665 latency_ms=30
ContentServicesResponse enq=1785474640832 ack=1785474640843 latency_ms=11
```

Checked against every symptom in the investigation brief: zero hops with
`acked_at < enqueued_at`; every attempt-2 latency is consistent with the
gap to its own (correctly-paired) receive, not some earlier one; hop
count equals send-span count for all six pairs (2 and 2, not 1 or 3).
Hop 1 of each pair pairs attempt 1's send with attempt 1's receive; hop 2
pairs attempt 2 with attempt 2. **No crossing in any of the three real
retries.**

Why: attempt 1's full round trip always finishes (both request and
response acked) strictly before attempt 2's request is even sent — e.g.
`brand.name` attempt 1 finishes at `640550`, attempt 2 doesn't start
until `640822`, 272ms later. That's not luck. `qa_critic` only dispatches
any retry *after* scoring the complete `DraftDocument`, which `assembler`
only sends once every worker's attempt-1 response has already arrived.
So for any single worker, attempt 2 cannot be in flight while attempt 1
still is — Launchpad's control flow serializes them by construction,
independent of timing. The `failures_enabled.py` scenario (trace
`a648b53c-9c67-4186-9179-9d11c9d57440`) never reaches `qa_critic` at all
(`market_lead` never completes, per the "also observed" note below), so
it has no retries either — the food-truck trace above is the only
capturable example, and it's structurally incapable of exercising the
overlap case. No forcing was needed to get *a* retry (one occurred
naturally and reliably, every run so far), but forcing genuine *overlap*
would require changing `qa_critic`'s dispatch strategy itself, which is
past what a rubric-threshold tweak can produce — see below instead.

### Synthetic: proving the algorithm itself is not safe under overlap

Since Launchpad can't produce overlapping same-key sends as built, the
question "would `build_hops` cross them if it saw an overlap" can't be
answered from captured data — it has to be asked of the function
directly. Constructed the smallest span set that represents what
Launchpad *would* produce if a retry were dispatched while the original,
unusually slow attempt was still outstanding (e.g. imagine `qa_critic`
retried a section eagerly instead of waiting for full assembly): attempt
1 sent at `t=0` but not acked by its receiver until `t=100`; attempt 2
sent at `t=10` (while attempt 1 is still outstanding) and answered fast,
by `t=14`.

```python
S1 = {"id": "S1", "direction": "send",    "enqueued_at": 0,  "acked_at": 5}    # attempt 1
S2 = {"id": "S2", "direction": "send",    "enqueued_at": 10, "acked_at": 13}   # attempt 2
R2 = {"id": "R2", "direction": "receive", "enqueued_at": 12, "acked_at": 14}   # attempt 2's (fast) reply
R1 = {"id": "R1", "direction": "receive", "enqueued_at": 90, "acked_at": 100}  # attempt 1's (slow) reply
# all four share (source_agent="A", dest_agent="B", payload_type="X"); state="delivered"
```

Fed to `get_trace_spans`'s own ordering contract (`ORDER BY enqueued_at
ASC`: `[S1, S2, R2, R1]`) and then `build_hops`:

```
build_hops() output:
  hop id=S1  enq=0  ack=14   latency_ms=14
  hop id=S2  enq=10 ack=100  latency_ms=90
```

**Confirmed crossed.** `S1` (attempt 1, whose real reply didn't land
until `t=100`) is reported with `R2`'s ack (`14`) — a 14ms latency that
looks completely ordinary. `S2` (attempt 2, whose real reply landed at
`t=14`) is reported with `R1`'s ack (`100`) — a 90ms latency that also
looks completely ordinary. Neither hop has `acked_at < enqueued_at` (both
matched receives happen to postdate their assigned send, since
`build_hops` only ever assigns a receive whose own `enqueued_at` already
happened), so the "obviously impossible negative latency" symptom the
spec's background section describes **is not how this bug actually
manifests** in a plain two-send-two-receive overlap — I could not
construct a 2-attempt case with a negative latency at all (see next
paragraph for why). What actually happens is worse in a specific way: two
individually plausible, positive latencies, silently swapped, with
nothing in the rendered output to indicate anything is wrong. A human
reading a waterfall would see "attempt 1: 14ms, attempt 2: 90ms" and
conclude the retry was *slower* than the original — the exact opposite of
what happened.

(Negative latency *is* reachable in principle, but needs a third,
unrelated early receive of the same key hanging around unclaimed when a
much-later send arrives and wrongly claims it — not something a single
one-retry-per-section, two-sends-total pattern like Launchpad's can
produce, since by causality a message's own receive can never precede
that message's own send, and with only two sends/two receives sharing a
key there's no "spare" receive left over to be mismatched onto a much
later send. Bounded to the misattribution failure mode above for this
system's actual message pattern.)

### Root cause and a proposed fix (not applied)

`build_hops` matches on `(source, dest, payload_type)` plus "earliest
unclaimed receive" — it has no signal that distinguishes *which* send a
given receive actually answers beyond relative timing, and relative
timing is exactly what varies (worker load, `slow`-mode delays, retries)
between attempts. The algorithm implicitly assumes send order and receive
*arrival* order always agree; the moment a later-sent message's handler
finishes before an earlier-sent message's handler does, that assumption
breaks and every subsequent pairing for that key is one slot off.

Fixing this within the current span schema (`source_agent`, `dest_agent`,
`payload_type`, timestamps — no other correlation field) isn't really
possible in general: there is no data in a send-span and a receive-span
that ties them to the *same logical message* except the coincidence of
matching key plus favorable timing, and this synthetic case shows that
coincidence can point the wrong way. A real fix needs one more piece of
information captured at write time, not smarter matching after the fact
— e.g. `traced_send` and `trace` both already touch a uAgents message
object; if uAgents' own envelope exposes a stable per-message identifier
(worth checking — a `msg_id`/similar), threading that through as an
additional span column and matching send/receive pairs on `(source, dest,
payload_type, message_id)` instead of matching on relative arrival order
would make the pairing exact instead of probabilistic. Not applying this
here per the investigation brief — flagging it as the shape a fix should
take, for a separate pass.

**Update: it reproduces on real traffic — not the synthetic overlap above,
but the same underlying "which occurrence am I looking at" failure, hit
through `show --view tree` instead of `build_hops`.** Repro trace
`34990172-4dfc-4a54-84dc-e07e155a68ba` (`scenarios/food_truck.py`, 33
agents, 143 spans, completes end to end). `uagents-trace show
34990172-4dfc-4a54-84dc-e07e155a68ba --view tree` rendered:

```
└── assembler  [LeadResult] "..." … pending
    └── qa_critic  [DraftDocument] "..." … pending
        ├── brand_lead  [SectionRetryRequest] "...section_id":"brand.name"...  ✓ 273 ms
        │   └── brand_name  [BrandNameRequest] ..."attempt":1,"critique":""...  ✓ 256 ms
```

`brand_name`'s node under the *retry* dispatch shows **attempt 1's**
payload (`attempt:1, critique:""`) instead of attempt 2's. Root cause
wasn't actually `build_hops` — per this finding's own data above,
`build_hops` never mis-paired any of the three real retries, and that held
here too. It was `shape.py`'s old `build_interaction_tree`: it kept *one
tree node per agent*, deduped by name (`_find_node`), and `_leg_state`
resolved that single node's message/state by grabbing
`dispatch_spans[0]` — the *first chronological* send between that agent
pair — no matter which branch of the tree the renderer was currently
walking. `brand_lead → brand_name` happens twice (the original dispatch
and the retry); the tree collapsed both onto one node and always showed
attempt 1's payload, even directly under the node that dispatched attempt
2. Also visible in the same run: `LeadResult`/`DraftDocument`/
`FinalDocument`/the final `ChatMessage` all rendered `… pending` despite
`user_proxy` printing the full reply — `_leg_state` required the *child to
reply directly back to its own caller* to call an edge "completed", which
is wrong for a relay edge (`qa_critic → delivery` never replies to
`qa_critic`; it forwards to `user_proxy` instead) and wrong for a hop to
an uninstrumented recipient (`user_proxy`'s own handler was never wrapped
in `@trace`, so there's no receive span to complete on at all, ever).

**Fix:** `recorder.py` now stamps every send span with `parent_span_id` —
the id of the receive span whose handler was executing (via a
`contextvars.ContextVar`) when the send happened — no envelope changes,
no uAgents patching. `shape.build_interaction_tree` was rewritten to build
the tree from that real causal chain instead of agent-name deduplication:
every distinct dispatch is now its own node, so an attempt-1 node and an
attempt-2 node to the same agent never collide, and a node's own state
(`shape._edge_state`) comes from whether *that specific hop* delivered —
not from whether the destination replied to its own caller — which also
fixed the pending-forever bug as a byproduct (including the uninstrumented
`user_proxy` hop, which now completes on the send's own transport ack
since no receive-side span will ever exist for it). `build_hops` itself
picked up a narrower, real improvement too: same-key sends are now ranked
by their *causal parent's* timestamp when known, instead of the send's own
possibly-jittered insert time, which is immune to exactly the kind of
recorder-side write-order jitter a busy multi-process run can produce
(tested synthetically in `tests/test_shape.py::RetryHopMatchingTests`,
since real traffic still doesn't naturally produce genuine same-key
overlap — Launchpad's retries stay fully serialized, as this finding
already established). The fully general cross-process ambiguity this
finding's root-cause section describes — pairing a send at one agent to
its own receive-side twin at another with no shared identifier — is
unchanged and still needs a message id in the envelope to close
completely; `parent_span_id` fixes what it fixes (causal branch
attribution, same-agent request→response chaining) without touching that.

Re-verified against a freshly captured trace with the fix live end-to-end
(`f5cf024c-574c-48ee-b611-c52512669765`, same scenario, 143 spans, 34
participants): tree roots at `user_proxy → gateway`, nests through
`parser → payment_gate/Orchestrator → {brand,content,market,ops}_lead →
...` to real depth (`market_lead → market_competitor_finder →
market_scout_1/2/3` included), `brand.name`'s retry node now correctly
shows attempt 2's `critique` under the retry dispatch (confirmed
programmatically: attempt 1 sits under `Orchestrator → brand_lead`,
attempt 2 under `qa_critic → brand_lead`), `ops_insurance` renders as a
failed leg, all 34 participants are reachable in the tree with zero
unparented spans, and nothing renders `pending` that actually delivered.
Regression tests: `tests/test_shape.py` (`BuildInteractionTreeTests`,
`RetryHopMatchingTests`, `ClassifyTraceShapeWithParentageTests`),
`tests/test_recorder.py` (parentage capture, including
`asyncio.create_task` context propagation).

## 4. Does `ops_insurance` show as an unresolved destination, and is its registration state `False` or `None`?

**Unresolved: yes. Registration state: `False`, never `None`.** Same
trace; `ops_lead -> ops_insurance` span:

```
send OpsInsuranceRequest ops_lead -> ops_insurance
  state=dropped  error="Unable to resolve destination endpoint"
  source_registered=True  dest_registered=False
```

`config.py` excludes `ops_insurance` from the `RulesBasedResolver` rules
(no process ever starts it), so `ctx.send` fails resolution immediately —
fast, not a 10s timeout — and `traced_send`'s `_apply_send_result` detects
`"resolve" in detail` and explicitly forces `dest_registered=False`. See
finding 5 for why it's `False` and not `None` in the first place anyway.

(No receive-side span exists for this hop at all, since nothing ever
received it — expected.)

## 5. Do cross-process spans distinguish `source_registered=True` from `dest_registered=None`?

**No — `None` does not occur in practice; cross-process spans show a
definite `True`/`False` on both sides.** Queried every distinct
`(source_registered, dest_registered)` pair across the reference trace's
143 spans:

```python
{(False, True), (True, False), (True, True)}
```

`None` never appears. Reading why, in `recorder.py`'s
`_registration_status`: it calls `uagents.dispatch.dispatcher.contains(address)`,
which is a plain membership check against *this process's* local sink
table (`uagents/dispatch.py`) — it returns a real `bool`, never raises for
a well-formed address that just happens to live in another process. The
function's `Optional[bool]` / "`None` if it can't be determined" signature
only actually returns `None` if the `dispatcher` import itself throws,
which doesn't happen in normal operation. So in this system:

- A local (same-process) destination -> `True`.
- Any other well-formed address -- another process's live agent (e.g.
  `market_lead` in process A sending to `market_competitor_finder` in
  process C) or a never-started one (`ops_insurance`) -- both resolve to
  the *same* `False` at insert time, from the sender's point of view.
  They're only told apart afterward, and only for the unresolved case,
  by `_apply_send_result`'s explicit `"resolve" in detail` override.

Concretely, `market_lead -> market_competitor_finder`
(`MarketCompetitorFinderRequest`, both processes alive and the message
delivered successfully) shows `source_registered=True,
dest_registered=False` on the send span and `source_registered=False,
dest_registered=True` on the matching receive span — the *exact same*
`False` that a permanently-unreachable `ops_insurance` send also gets. The
`registered=None` ("unknown, not local") state the build spec describes
as the reason for splitting this system across four processes is real
code (the `Optional[bool]` return type, the "not local" comment) but not
reachable in this deployment shape — `False` already means "not local,"
and this codebase has no path that produces a genuine "couldn't
determine" `None`.

**Update:** `gateway` was later pulled out of `run_core.py`'s Bureau into
its own standalone process (`run_gateway.py`, port 8100) so Agentverse's
inspector could resolve it via `/agent_info` without the
`x-uagents-address` header a Bureau's shared REST routes need to
disambiguate agents sharing one port (unrelated to this finding — see
`AGENTVERSE.md`). One side effect belongs here: `gateway <-> parser` and
`gateway <-> payment_gate` were same-process edges when this finding was
written (both hosted by the same Bureau) and showed `registered=True` on
their local side, same as any other same-Bureau hop. They're genuine
cross-process edges now. Re-checked on a fresh paid-tier run (trace
`cb2e5079-e49b-4394-833c-692deae2814e`): `gateway -> parser`
(`ParseRequest`) and both payment ladder legs now show `source_registered=
True, dest_registered=False` on the send span and the flip on the receive
span — exactly the pattern this finding already documents for every other
cross-process edge (`market_lead -> market_competitor_finder`, etc.), not
a new pattern. The conclusion above (`None` unreachable, `False` covers
both "remote but alive" and "never started") is unchanged; only this one
edge's own registered value flipped from `True` to match it. Nothing else
in this document was re-run or rewritten.

## 6. Does the Payment Protocol ladder render request -> commit -> complete, and separately request -> reject?

**Both ladders render correctly in isolation — but `show` cannot render a
trace's payment ladder *and* the rest of that trace's shape at the same
time**, which matters here because every one of this system's paid-tier
traces is both.

Commit path, reference trace `6978d754-fe31-4aef-874f-aa2e9bd61788`
(`scenarios/food_truck.py`):

```
PAYMENT
 1. payment_gate -> gateway  RequestPayment   (5.0 FET)
 2. gateway -> payment_gate  CommitPayment    (5.0 FET)
 3. payment_gate -> gateway  CompletePayment  (verified)
```

Reject path, `scenarios/rejected_payment.py` (amount `15.0` > `gateway`'s
policy max of `10.0`), trace `3c5bb1a0-46f3-4c6c-88a1-0d91347aa668`:

```
PAYMENT
 1. payment_gate -> gateway  RequestPayment  (15.0 FET)
 2. gateway -> payment_gate  RejectPayment   (rejected: amount exceeds 10.0 FET policy max)
```

Two steps, no `CommitPayment`/`CompletePayment` — `payment_gate` still
forwarded to `orchestrator` afterward with `tier` downgraded to `unpaid`
(spec section 1: never hard-fail), so the run completed normally with just
the brand/content sections, no Payment Protocol retry or second attempt.

Both are correct and exactly match the shapes described in the spec. The
finding is what happens *around* them: `cli.py`'s `print_trace_detail` has

```python
if is_payment_trace(spans):
    print_payment(spans, alias_map, color)
    return
```

an unconditional early return the moment **any** span in the trace is a
recognized Payment Protocol message — before shape classification, before
the hub/flat renderer ever runs. The reference trace above has 143 spans
total; only 6 of them (3 sends + 3 receives) are payment-related. `show`
displays those 6 and silently drops the other 137 — the entire brand/
content/market/ops fan-out, the market depth, and the QA retries this
FINDINGS document otherwise relies on `get_trace_spans` (not the CLI) to
inspect. Since every paid-tier Launchpad run touches the Payment Protocol
exactly once near the start, **`uagents-trace show` can never display the
full shape of any paid-tier trace in this system** — only the unpaid
scenario's trace is fully visible through the CLI as-is.

**Update:** fixed in `uagents-trace` (`cli.py`'s `print_trace_detail`) in
the same pass that produced this document — the `return` after
`print_payment(...)` was removed so the ladder prints additively, ahead of
the normal shape-dispatched waterfall, instead of replacing it. Re-checked
against both trace IDs above post-fix: `show` now prints `PAYMENT` *and*
the full `HUB` waterfall for both. `classify_trace_shape`/`build_hops`
were only ever called on this trace's non-payment spans by accident of the
`return` — they were already written to take the full `spans` list, so no
other change was needed. This was isolated to `cli.py`'s `show`/`watch`
(both go through `print_trace_detail`); `live.py` (TUI), `server.py` (web
dashboard API), and `tui.py` all call `build_hops`/`classify_trace_shape`
directly with no payment-conditional branch, so they were never affected.
Regression test: `tests/test_show_payment_additive.py`.

---

## Also observed (not one of the six spec questions, but load-bearing for the system above)

**A lead that waits for every worker it dispatched will hang forever on a
structurally-unreachable one, unless the lead is written to notice.**
`ops_lead`'s and `market_lead`'s original implementation counted every
dispatched worker as "expected" unconditionally; `ops_insurance` being
permanently unresolvable meant `ops_lead` never reached "all expected
sections collected" and never sent its `LeadResult` to `assembler` — which
meant *no* food/retail paid run could ever complete, not even a clean one
with `FAILURES={}` on every other worker (`ops_insurance` isn't gated by
`FAILURES` at all; it's just never started, per spec section 1). Fixed by
having leads check `traced_send`'s own result for `"resolve" in detail`
immediately after each dispatch and treat that section as unavailable
right away rather than waiting on it — implemented in
`agents/leads/_common.py:is_unresolved` / `unavailable_section`, applied
in both `_common.py`'s generic lead and `market.py`'s hand-written one.
This is application code, not a `uagents-trace` change, and is the reason
finding 1's reference run completes with `ops.insurance: (ops_insurance
could not be reached this run)` rather than hanging.

**`market_scout_3`'s `raises` failure mode genuinely stalls the market
branch forever, by design, and that's the correct behavior to keep.**
`market_competitor_finder` fans out to 1-3 scouts and waits for every one
of them before replying to `market_lead` (spec section 1's depth). When
`market_scout_3` raises before replying, the *send* to it still succeeds
(the receiving process accepted the HTTP request; `traced_send` sees
`state=delivered`) — the failure happens entirely inside the receiver's
handler, after the point where a sender could detect it. So unlike
`ops_insurance` above, there is no signal `market_competitor_finder` can
act on; it legitimately cannot tell "still working" from "will never
reply." Confirmed with `scenarios/failures_enabled.py`
(trace `a648b53c-9c67-4186-9179-9d11c9d57440`): the receive-side span for
`MarketScout3Request` shows `state=dropped`,
`error="market_scout_3: simulated failure (...)"`, and no `market_lead`
`LeadResult` ever appears in that trace's spans — the run correctly never
reaches `delivery`. The same trace also confirms the other two default
failure modes behave as designed in the same run: `ops_insurance`'s send
is dropped immediately (`ops_lead` unaffected, sends its `LeadResult`
536ms later) and `brand_logo_brief`'s handler sleeps ~12016ms (> the 10s
`traced_send` timeout) but its reply still arrives and is processed
normally by `brand_lead` afterward — exactly the "reply may still arrive
afterwards" behavior spec section 7 calls out as worth observing.

**Gateway's own anti-echo cooldown/dedup is aggressive enough to bite
scenario testing, not just a real echo loop.** `scenarios/_client.py`
uses one fixed `user_proxy` identity (deterministic seed, per hard
constraint #7) for every scenario run. `gateway`'s 30s per-sender cooldown
and 120s exact-text dedup (spec section 8) apply to it exactly as they
would to a real ASI:One echo loop — back-to-back scenario runs, or two
runs with identical wording within 120s, get acked and then silently
dropped. Not a bug (this is the anti-echo mechanism working as specified),
but worth calling out since it wasn't obvious from the spec that test
tooling would need to account for it: `README.md` now says to space
scenario runs >=30s apart with distinct wording.

---

## Reference trace IDs

| scenario | trace_id | shape |
|---|---|---|
| `food_truck.py` (paid, food — widest ops fan-out) | `6978d754-fe31-4aef-874f-aa2e9bd61788` | hub (see finding 2) |
| `saas.py` (paid, saas — narrowest ops fan-out) | `330cb07a-2ab3-4427-8845-dfd956fb4e7a` | hub |
| `unpaid.py` (no Payment Protocol at all) | `8ae66a15-ae3f-4895-bfc6-76c347cf0ac6` | hub |
| `rejected_payment.py` (amount over policy max) | `3c5bb1a0-46f3-4c6c-88a1-0d91347aa668` | hub + payment (reject) |
| `failures_enabled.py` (default `FAILURES`, never completes) | `a648b53c-9c67-4186-9179-9d11c9d57440` | partial — no `delivery` |
