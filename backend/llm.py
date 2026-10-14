"""Minimal OpenAI- and Anthropic-compatible chat clients over httpx."""
from __future__ import annotations

import httpx

from .prompts import MAX_TOKENS, SYSTEM


class LLMError(RuntimeError):
    pass


def _join(base: str, path: str) -> str:
    base = base.rstrip("/")
    if base.endswith(path) or base.endswith(path.split("/")[-1]):
        # Caller already passed a full endpoint URL; use as-is.
        if base.endswith(path):
            return base
    return f"{base}{path}"


async def complete_openai(*, api_url: str, api_key: str, model: str, prompt: str, length: str) -> str:
    if not api_key:
        raise LLMError("OPENAI_API_KEY is not set. Add it to .env (see .env.example).")
    endpoint = api_url if api_url.rstrip("/").endswith("/chat/completions") else _join(api_url, "/chat/completions")
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.4,
        "max_tokens": MAX_TOKENS.get(length, 1200),
    }
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                endpoint,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
            )
    except httpx.HTTPError as exc:
        raise LLMError(f"OpenAI-compatible request failed: {exc}") from exc
    if response.status_code >= 400:
        raise LLMError(f"OpenAI-compatible API error {response.status_code}: {response.text[:500]}")
    try:
        return str(response.json()["choices"][0]["message"]["content"]).strip()
    except Exception as exc:
        raise LLMError(f"Unexpected OpenAI-compatible response shape: {response.text[:500]}") from exc


async def complete_anthropic(*, api_url: str, api_key: str, model: str, prompt: str, length: str) -> str:
    if not api_key:
        raise LLMError("ANTHROPIC_API_KEY is not set. Add it to .env (see .env.example).")
    base = api_url.rstrip("/")
    if base.endswith("/v1/messages") or base.endswith("/messages"):
        endpoint = base
    elif base.endswith("/v1"):
        endpoint = f"{base}/messages"
    else:
        endpoint = f"{base}/v1/messages"
    payload = {
        "model": model,
        "max_tokens": MAX_TOKENS.get(length, 1200),
        "system": SYSTEM,
        "messages": [{"role": "user", "content": prompt}],
    }
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                endpoint,
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
    except httpx.HTTPError as exc:
        raise LLMError(f"Anthropic-compatible request failed: {exc}") from exc
    if response.status_code >= 400:
        raise LLMError(f"Anthropic-compatible API error {response.status_code}: {response.text[:500]}")
    try:
        blocks = response.json().get("content", [])
        texts = [b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "text"]
        combined = "\n".join(t for t in texts if t).strip()
        if not combined and blocks and isinstance(blocks[0], dict):
            combined = str(blocks[0].get("text", "")).strip()
        if not combined:
            raise ValueError("empty content")
        return combined
    except Exception as exc:
        raise LLMError(f"Unexpected Anthropic-compatible response shape: {response.text[:500]}") from exc
