import json
import os
from collections.abc import AsyncIterator

import httpx

MODEL = "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free"
BASE_URL = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")


def require_api_key() -> str:
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY is not set")
    return key


async def stream_answer(system_prompt: str, user_prompt: str) -> AsyncIterator[str]:
    """Stream the model's answer from OpenRouter, yielding content deltas.

    OpenRouter sends Server-Sent Events: one `data: {...}` line per delta and a
    final `data: [DONE]` sentinel. We decode just the text content of each
    chunk so callers can consume a plain stream of string deltas.
    """
    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream(
            "POST",
            f"{BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {require_api_key()}"},
            json={
                "model": MODEL,
                "stream": True,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            },
        ) as response:
            if response.is_error:
                # Keep OpenRouter's explanation (rate limits, bad key, model
                # issues) instead of a bare status code.
                body = (await response.aread()).decode(errors="replace")
                try:
                    error = json.loads(body).get("error", {})
                    # metadata.raw carries the actionable upstream message
                    # (e.g. "rate-limited upstream, retry shortly").
                    detail = (
                        error.get("metadata", {}).get("raw")
                        or error.get("message")
                        or body[:200]
                    )
                except ValueError:
                    detail = body[:200]
                raise httpx.HTTPStatusError(
                    f"{response.status_code} {response.reason_phrase}: "
                    f"{detail or response.reason_phrase}",
                    request=response.request,
                    response=response,
                )
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = line[len("data: ") :]
                if data == "[DONE]":
                    break
                event = json.loads(data)
                # OpenRouter appends annotation events (usage stats) with an
                # empty choices list — skip them instead of indexing [0].
                choices = event.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta", {}).get("content")
                if delta:
                    yield delta
