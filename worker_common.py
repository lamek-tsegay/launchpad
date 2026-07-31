"""Shared plumbing every leaf worker uses: call ASI:One for the fuzzy
generation part, fall back to a deterministic template on any failure
(spec section 6), and honor `config.FAILURES` injection (spec section 7).

This is real shared control flow, not a debug hook -- the same function
runs whether or not a worker is in FAILURES, and the LLM call path is
identical for every worker. Only the prompts and fallback templates differ,
and those stay in each worker module.

In `config.DEMO_MODE`, the ASI:One call is skipped entirely (never
attempted, not even against the cache) and replaced with a small jittered
sleep -- see `_demo_jitter_range`.
"""

import asyncio
import hashlib
import random
from typing import Any, Callable, Dict, Tuple

import config
import llm


def critique_line(attempt: int, critique: str) -> str:
    if attempt <= 1 or not critique:
        return ""
    return f"\n\nA reviewer rejected your previous attempt: {critique}\nAddress that feedback directly this time."


def _demo_jitter_range(worker_name: str) -> Tuple[float, float]:
    """A ~60ms sub-range of config.DEMO_JITTER_RANGE, deterministic per
    worker name -- so e.g. brand_name is consistently snappier than
    ops_permits run to run (a real system would have per-service latency
    characteristics), while still varying within that band call to call
    (matches llm_cache.py's own cache-hit jitter, so a demo run and a
    cache-hit live run "feel" the same).
    """
    lo, hi = config.DEMO_JITTER_RANGE
    span = hi - lo
    digest = int(hashlib.sha256(worker_name.encode()).hexdigest(), 16)
    center = lo + (digest % 1000) / 1000 * span
    half_width = span * 0.15
    return max(lo, center - half_width), min(hi, center + half_width)


async def run_worker(
    *,
    worker_name: str,
    section_id: str,
    response_type: type,
    system_prompt: str,
    user_prompt: str,
    fallback: Callable[[], Tuple[str, Dict[str, Any]]],
):
    """Returns an instance of `response_type`. Never raises: FAILURES=="raises"
    is the one intentional exception, since that mode exists specifically to
    produce a handler that raises before replying (spec section 7).
    """
    mode = config.FAILURES.get(worker_name)
    if mode == "raises":
        raise RuntimeError(f"{worker_name}: simulated failure (FAILURES['{worker_name}'] == 'raises')")
    if mode == "slow":
        await asyncio.sleep(config.SLOW_FAILURE_SLEEP_SECONDS)

    if config.DEMO_MODE:
        if mode != "slow":  # slow's own sleep above already stands out; don't also add jitter on top
            await asyncio.sleep(random.uniform(*_demo_jitter_range(worker_name)))
        content, details = fallback()
        return response_type(section_id=section_id, content=content, details=details, used_fallback=True)

    try:
        data = await llm.call_asi1_json(system_prompt, user_prompt)
        content = str(data.get("content") or "").strip()
        if not content:
            raise ValueError("ASI:One returned no content field")
        details = {k: v for k, v in data.items() if k != "content"}
        return response_type(section_id=section_id, content=content, details=details, used_fallback=False)
    except Exception:
        content, details = fallback()
        return response_type(section_id=section_id, content=content, details=details, used_fallback=True)
