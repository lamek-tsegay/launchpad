"""Seeds, addresses, process/port layout, and the two run-to-run variance
knobs (FAILURES, tier gates) for the Launchpad system.

Every agent gets a fixed seed here so all four processes agree on every
other agent's address without a discovery step (hard constraint #7).
Cross-process delivery between Launchpad's own agents is done via explicit
HTTP endpoints resolved through a `RulesBasedResolver` built from this
file, not via Almanac/mailbox lookups -- that's what keeps every trace in
FINDINGS.md fast and reproducible. `gateway` is the one exception (see
MAILBOX_AGENTS below and AGENTVERSE.md): it needs a real Agentverse
mailbox to be reachable from outside this machine at all (a real ASI:One
user), which every other agent doesn't.
"""

import json
import os

from uagents import Agent
from uagents.crypto import Identity
from uagents.resolver import GlobalResolver, Resolver, RulesBasedResolver

SEED_PREFIX = "launchpad-v1"


def _seed(name: str) -> str:
    return f"{SEED_PREFIX}-{name}"


def _address(name: str) -> str:
    return Identity.from_seed(_seed(name), 0).address


# name -> which process's HTTP port serves it
AGENT_PROCESS = {
    # Process A0 -- run_gateway.py. Standalone, not in the core Bureau: a
    # Bureau's shared REST endpoints (e.g. /agent_info) can't disambiguate
    # between the agents sharing its port without an explicit
    # x-uagents-address header, which the Agentverse inspector page doesn't
    # send -- its "Connect" button silently can't find an agent sharing a
    # Bureau's port. gateway is the only agent that needs the inspector to
    # ever work, so it's the only one pulled out.
    "gateway": "gateway",
    # Process A -- run_core.py
    "parser": "core",
    "payment_gate": "core",
    "orchestrator": "core",
    "brand_lead": "core",
    "content_lead": "core",
    "market_lead": "core",
    "ops_lead": "core",
    "assembler": "core",
    "qa_critic": "core",
    "delivery": "core",
    # Process B -- run_creative.py
    "brand_name": "creative",
    "brand_palette": "creative",
    "brand_logo_brief": "creative",
    "brand_voice": "creative",
    "content_hero": "creative",
    "content_about": "creative",
    "content_services": "creative",
    "content_faq": "creative",
    "content_email": "creative",
    # Process C -- run_market.py
    "market_competitor_finder": "market",
    "market_scout_1": "market",
    "market_scout_2": "market",
    "market_scout_3": "market",
    "market_pricing": "market",
    "market_seo": "market",
    "market_ad_copy": "market",
    # Process D -- run_ops.py
    "ops_entity": "ops",
    "ops_tax": "ops",
    "ops_permits": "ops",
    "ops_health": "ops",
    "ops_food_handler": "ops",
    # Deliberately never started. Present here so every other agent can
    # resolve its address and attempt delivery; absent from the resolver
    # rules below, so that attempt fails as an *unresolved destination*
    # rather than a refused connection.
    "ops_insurance": "ops",
    # Not one of the ~32 Launchpad agents -- a fixed-identity stand-in for
    # "the chat user" so scenarios/ scripts have a deterministic, resolvable
    # address `delivery` can reply to across process boundaries, the same
    # way any other cross-process agent in this system is reached.
    "user_proxy": "client",
}

PROCESS_PORTS = {
    "gateway": 8100,
    "core": 8101,
    "creative": 8102,
    "market": 8103,
    "ops": 8104,
    "client": 8105,
}

ALL_AGENT_NAMES = list(AGENT_PROCESS.keys())
NEVER_STARTED = {"ops_insurance"}

# The 33 Launchpad agents proper (32 running + ops_insurance, deliberately
# never started) -- excludes `user_proxy`, which is test harness, not part
# of the system under test.
LAUNCHPAD_AGENT_NAMES = [name for name in ALL_AGENT_NAMES if name != "user_proxy"]

AGENT_SEEDS = {name: _seed(name) for name in ALL_AGENT_NAMES}
AGENT_ADDRESSES = {name: _address(name) for name in ALL_AGENT_NAMES}
ADDRESS_TO_NAME = {addr: name for name, addr in AGENT_ADDRESSES.items()}


def _endpoint(name: str) -> str:
    port = PROCESS_PORTS[AGENT_PROCESS[name]]
    return f"http://127.0.0.1:{port}/submit"


def local_endpoint(name: str) -> str:
    """The real local HTTP route for `name`, regardless of MAILBOX_AGENTS.

    A Bureau's HTTP server answers on its port for every agent it hosts no
    matter their mailbox/endpoint setting -- mailbox mode only changes what
    a real *external* caller is told to use for resolution, not whether
    this local route works. `scenarios/_client.py` uses this (not the
    resolver every real Launchpad agent gets) so the five scripted
    scenarios keep working at full local speed without needing a live
    Agentverse mailbox connection, even for `gateway`.
    """
    return _endpoint(name)


# Which agents get a real Agentverse mailbox (visible/connectable in the
# Agentverse UI) vs. staying purely local. Default: all 32 running agents
# (everyone except `ops_insurance`, which never starts). This used to
# default to {"gateway"} only, over a latency concern: mailbox routes an
# agent's *inbound* reachability through Agentverse, and the worry was that
# would drag every internal hop through it too. Verified (not assumed)
# before widening this default: `_RESOLVER_RULES` below gives every agent
# a real local route regardless of MAILBOX_AGENTS membership, so adding an
# agent to this set only changes how *external* callers reach it --
# Launchpad's own agent-to-agent traffic never touches Agentverse either
# way. Measured on `parser` specifically (chosen as the test case) before
# rolling out further: gateway -> parser send-ack latency was 7-75ms with
# `parser` mailbox-enabled, same range as with it local-only -- see
# AGENTVERSE.md for the full before/after. Override with
# LAUNCHPAD_MAILBOX_AGENTS (comma-separated names, "" for none).
if "LAUNCHPAD_MAILBOX_AGENTS" in os.environ:
    MAILBOX_AGENTS = {n.strip() for n in os.environ["LAUNCHPAD_MAILBOX_AGENTS"].split(",") if n.strip()}
else:
    MAILBOX_AGENTS = {name for name in LAUNCHPAD_AGENT_NAMES if name not in NEVER_STARTED}

# Every known agent EXCEPT the ones that never start -- resolving to
# their address with no endpoints, which is exactly what "unreachable"
# (FAILURES) needs: a resolvable identity with nowhere to deliver to.
#
# Deliberately includes MAILBOX_AGENTS (gateway) too, via `local_endpoint`
# rather than `_endpoint` -- gateway's own Agent() construction still only
# ever sets `mailbox=True` with no `endpoint` (hard constraint #6 is about
# that single agent's own config, unchanged), but every *other* Launchpad
# agent's resolver is free to know gateway's real local route, because we
# run this whole local topology ourselves. Mailbox is about how a real,
# genuinely external ASI:One user reaches gateway (they have no way to
# know about this machine's loopback address); it says nothing about how
# our own internal agents should reach it, and there's no reason for
# payment_gate's side of the Payment Protocol conversation to depend on a
# live Agentverse mailbox connection when a fast, reliable local route is
# right there. GlobalResolver (via _FallbackResolver below) is reserved
# for addresses genuinely absent from this table -- i.e. real external
# ones, which only ever comes up for `delivery`.
_RESOLVER_RULES = {AGENT_ADDRESSES[name]: local_endpoint(name) for name in ALL_AGENT_NAMES if name not in NEVER_STARTED}

_local_resolver = RulesBasedResolver(_RESOLVER_RULES)


class _FallbackResolver(Resolver):
    """Local rules table first (fast, deterministic, what every recorded
    trace in FINDINGS.md was captured against, and includes gateway's own
    local route -- see the comment on _RESOLVER_RULES above); uAgents' own
    Almanac/mailbox-aware GlobalResolver only for addresses the local
    table doesn't know about at all -- i.e. genuinely external addresses.
    In practice this only ever matters for `delivery` (replies to
    whatever address sent the original ChatMessage -- a real ASI:One
    user isn't and can't be in the local table). Every other agent's
    destinations, `payment_gate` -> `gateway` included, are always
    Launchpad agents already in the local table, so this never falls
    through to GlobalResolver for them.
    """

    def __init__(self, primary: Resolver, secondary: Resolver):
        self._primary = primary
        self._secondary = secondary

    async def resolve(self, destination: str):
        address, endpoints = await self._primary.resolve(destination)
        if endpoints:
            return address, endpoints
        return await self._secondary.resolve(destination)


_hybrid_resolver = _FallbackResolver(_local_resolver, GlobalResolver())


# `name="gateway"` alone is not a safe way to find this agent in a real
# ASI:One/Agentverse session: Agentverse is a shared, global directory, not
# scoped to this project, so "gateway" collides with anyone else's agent of
# the same name. `handle`/`description` (both real `Agent()` fields,
# published by default -- `publish_agent_details=True` is uAgents' own
# default) give it a distinctive, searchable identity instead of requiring
# the 65-char address to be pasted in. Only set for `gateway`: it's the
# only agent meant to be found this way (see AGENTVERSE.md and the
# MAILBOX_AGENTS comment above) -- the other 31 don't need a public
# identity, chat-searchable or otherwise.
_AGENT_DETAILS = {
    "gateway": {
        "handle": "launchpad-demo-gateway",
        "description": (
            "Launchpad demo entry point. Send a business idea (e.g. \"I want to start a "
            "food truck in Austin, TX\") and get back a starter kit: brand, website copy, "
            "market scan, and a compliance checklist, assembled by a 33-agent pipeline."
        ),
    },
}


def build_agent(name: str) -> Agent:
    """Construct one of this system's agents with its fixed seed. Agents in
    MAILBOX_AGENTS get a real Agentverse mailbox and no local endpoint;
    everyone else keeps the local endpoint validated throughout
    FINDINGS.md. Every agent gets the same hybrid resolver for outbound
    sends regardless -- see `_FallbackResolver`.

    `port=` is always the agent's own real process port, not uAgents'
    default of 8000 -- for a standalone agent (gateway) this is also what
    it actually serves on; for a Bureau-hosted agent, the Bureau's own
    server is what really answers regardless of this value; either way,
    it's what `/agent_info` (and the Agentverse inspector, for gateway)
    self-reports, and a wrong self-report is the bug that sent us here.
    """
    port = PROCESS_PORTS[AGENT_PROCESS[name]]
    details = _AGENT_DETAILS.get(name, {})
    if name in MAILBOX_AGENTS:
        return Agent(name=name, seed=AGENT_SEEDS[name], port=port, mailbox=True, resolve=_hybrid_resolver, **details)
    return Agent(
        name=name,
        seed=AGENT_SEEDS[name],
        port=port,
        endpoint=[_endpoint(name)],
        resolve=_hybrid_resolver,
        **details,
    )


def process_port(process: str) -> int:
    return PROCESS_PORTS[process]


# ---------------------------------------------------------------------------
# Run-to-run variance knobs
# ---------------------------------------------------------------------------

# Which ops workers apply, keyed by intake["business_type"]. Same code path
# in ops_lead, different fan-out width per run.
OPS_TEAM_BY_BUSINESS_TYPE = {
    "food": ["ops_permits", "ops_health", "ops_food_handler", "ops_entity", "ops_tax", "ops_insurance"],
    "retail": ["ops_permits", "ops_entity", "ops_tax", "ops_insurance"],
    "saas": ["ops_entity", "ops_tax"],
    "services": ["ops_entity", "ops_tax"],
}

# Worker -> section_id it owns, and which lead owns that worker. Used by
# qa_critic to route a retry to "the originating lead" and by that lead to
# find "the same worker" (spec section 5).
SECTION_OWNER = {
    "brand.name": ("brand_lead", "brand_name"),
    "brand.palette": ("brand_lead", "brand_palette"),
    "brand.logo_brief": ("brand_lead", "brand_logo_brief"),
    "brand.voice": ("brand_lead", "brand_voice"),
    "content.hero": ("content_lead", "content_hero"),
    "content.about": ("content_lead", "content_about"),
    "content.services": ("content_lead", "content_services"),
    "content.faq": ("content_lead", "content_faq"),
    "content.email": ("content_lead", "content_email"),
    "market.competitors": ("market_lead", "market_competitor_finder"),
    "market.scout_1": ("market_lead", "market_scout_1"),
    "market.scout_2": ("market_lead", "market_scout_2"),
    "market.scout_3": ("market_lead", "market_scout_3"),
    "market.pricing": ("market_lead", "market_pricing"),
    "market.seo": ("market_lead", "market_seo"),
    "market.ad_copy": ("market_lead", "market_ad_copy"),
    "ops.entity": ("ops_lead", "ops_entity"),
    "ops.tax": ("ops_lead", "ops_tax"),
    "ops.permits": ("ops_lead", "ops_permits"),
    "ops.health": ("ops_lead", "ops_health"),
    "ops.food_handler": ("ops_lead", "ops_food_handler"),
    "ops.insurance": ("ops_lead", "ops_insurance"),
}

MAX_RETRIES_PER_RUN = 3
QA_PASS_THRESHOLD = 6

# Deterministic, configurable failure injection (spec section 7). Override
# per-process-launch with LAUNCHPAD_FAILURES='{"worker": "mode"}' so
# scenarios can turn this on/off without editing code.
_DEFAULT_FAILURES = {
    "ops_insurance": "unreachable",
    "brand_logo_brief": "slow",
    "market_scout_3": "raises",
}

if os.environ.get("LAUNCHPAD_FAILURES"):
    FAILURES = json.loads(os.environ["LAUNCHPAD_FAILURES"])
else:
    FAILURES = dict(_DEFAULT_FAILURES)

# ---------------------------------------------------------------------------
# LAUNCHPAD_MODE: demo vs live
# ---------------------------------------------------------------------------
#
# demo changes *how much real work happens*, never the shape of the system:
# same 33 agents, same 5 processes, same topology, same fan-out rules, same
# QA retry loop, same three failure modes, same Payment Protocol. What
# changes is that workers skip ASI:One entirely (straight to their
# deterministic fallback, used_fallback=True -- the same fallback path live
# mode already takes on any LLM failure, just always taken here instead of
# conditionally) and sleep a small jittered interval instead of making a
# real (or cached) API call, so a full paid run finishes in seconds instead
# of however long ~25 serial ASI:One calls take.
LAUNCHPAD_MODE = os.environ.get("LAUNCHPAD_MODE", "live")
if LAUNCHPAD_MODE not in ("live", "demo"):
    raise ValueError(f"LAUNCHPAD_MODE must be 'live' or 'demo', got {LAUNCHPAD_MODE!r}")
DEMO_MODE = LAUNCHPAD_MODE == "demo"

if DEMO_MODE:
    # Scaled down from live's 12s/10s, same ratio (sleep > send timeout) --
    # small enough that FAILURES={"brand_logo_brief": "slow"} still fits a
    # <15s full-run budget, large enough to read as a clear outlier next to
    # DEMO_JITTER_RANGE below (worst case ~250ms) in the waterfall.
    #
    # SEND_TIMEOUT_SECONDS must be a plain int: it ends up as an
    # Envelope.expires computed from it, and uAgents' Envelope model
    # validates that field as a strict int -- a float here doesn't get
    # coerced, it fails validation and every send using it gets silently
    # dropped (found by actually timing a demo run, not by inspection --
    # every worker-dispatch send failed with a pydantic "int_from_float"
    # error on expires until this was an int).
    SLOW_FAILURE_SLEEP_SECONDS = 2.0
    SEND_TIMEOUT_SECONDS = 1
else:
    SLOW_FAILURE_SLEEP_SECONDS = 12  # > traced_send's 10s default timeout
    SEND_TIMEOUT_SECONDS = 10  # traced_send's own default; passed explicitly so demo/live share one code path

# Demo-mode-only: replaces the latency a real (or cached) ASI:One call would
# have contributed, so the waterfall shows realistic spread across workers
# rather than every hop collapsing to a few milliseconds. Bounds only --
# worker_common.py picks a per-worker sub-range within this so different
# workers have visibly different typical latency, not just uniform noise.
DEMO_JITTER_RANGE = (0.08, 0.25)
