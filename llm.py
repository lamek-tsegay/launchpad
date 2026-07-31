"""ASI:One client (spec section 6): LLM for fuzzy extraction/generation,
never for control flow. Callers are responsible for their own deterministic
fallback -- this module only calls the model (through the cache) and raises
on any failure; it never fabricates a response.
"""

import json
import os
from typing import Any, Dict, Optional

from openai import AsyncOpenAI

import llm_cache

# asi1-mini is ASI:One's fastest/cheapest tier -- picked originally because
# this system was built without an API key configured, so call cost/latency
# never mattered in practice. With a Pro account and no budget constraint,
# `asi1-extended` (ASI:One's larger, more capable reasoning tier as of this
# writing) should produce more coherent, better-instruction-following
# section copy and fewer JSON-parse failures that fall through to the
# deterministic template -- verify the exact model ID against your
# ASI:One dashboard/docs before relying on this, model catalogs drift.
# Override with ASI1_MODEL without touching code either way.
MODEL = os.environ.get("ASI1_MODEL", "asi1-extended")

_client: Optional[AsyncOpenAI] = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        api_key = os.environ.get("ASI1_API_KEY")
        if not api_key:
            raise RuntimeError("ASI1_API_KEY not set")
        _client = AsyncOpenAI(api_key=api_key, base_url="https://api.asi1.ai/v1")
    return _client


async def call_asi1(system_prompt: str, user_prompt: str, *, temperature: float = 0.3, max_tokens: int = 1500) -> str:
    """Raises on any failure (missing key, network error, timeout). Callers
    catch broadly and fall back to their deterministic template.
    """
    cache_prompt = f"{system_prompt}\x1f{user_prompt}"
    cached = await llm_cache.get(MODEL, cache_prompt, temperature)
    if cached is not None:
        return cached

    client = _get_client()
    resp = await client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    text = resp.choices[0].message.content
    if not text:
        raise RuntimeError("ASI:One returned empty content")

    await llm_cache.put(MODEL, cache_prompt, temperature, text)
    return text


async def call_asi1_json(system_prompt: str, user_prompt: str, **kwargs: Any) -> Dict[str, Any]:
    """Same as `call_asi1`, but requires the response to parse as a JSON
    object. Raises on non-JSON output too -- an LLM inventing a shape we
    didn't ask for is exactly what the fallback path exists to absorb.
    """
    text = await call_asi1(system_prompt, user_prompt, **kwargs)
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("expected a JSON object")
    return parsed
