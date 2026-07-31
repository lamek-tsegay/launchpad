"""Disk cache for ASI:One calls (spec section 6).

Kept on by default for reproducibility, not cost: with an unmetered ASI:One
Pro account, call volume isn't a concern, but re-running the same scenario
and getting a *different* LLM completion each time would make traces
non-comparable run to run -- the same failure mode `config.FAILURES` being
deterministic-not-random exists to avoid, just for LLM content instead of
injected failures. Set `LLM_CACHE=0` to force fresh calls (e.g. deliberately
sampling different content for a scenario), or delete `.llm_cache/` to
start over.

Keyed on sha256(model + prompt + temperature); JSON blobs under
`.llm_cache/`. Cache hits still sleep a small jittered interval so traces
keep a realistic latency spread instead of collapsing to near-zero once a
scenario has been run once.
"""

import asyncio
import hashlib
import json
import os
import random
from pathlib import Path
from typing import Optional

CACHE_DIR = Path(os.environ.get("LLM_CACHE_DIR", ".llm_cache"))


def _enabled() -> bool:
    return os.environ.get("LLM_CACHE", "1") != "0"


def _key(model: str, prompt: str, temperature: float) -> str:
    raw = f"{model}\x1e{prompt}\x1e{temperature}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _path(key: str) -> Path:
    return CACHE_DIR / f"{key}.json"


async def get(model: str, prompt: str, temperature: float) -> Optional[str]:
    if not _enabled():
        return None
    path = _path(_key(model, prompt, temperature))
    if not path.exists():
        return None
    await asyncio.sleep(random.uniform(0.15, 0.4))
    try:
        return json.loads(path.read_text())["response"]
    except Exception:
        return None


async def put(model: str, prompt: str, temperature: float, response: str) -> None:
    if not _enabled():
        return
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _path(_key(model, prompt, temperature))
    path.write_text(json.dumps({"model": model, "prompt": prompt, "temperature": temperature, "response": response}))
