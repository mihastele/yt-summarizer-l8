"""Minimal OpenAI- and Anthropic-compatible chat clients over httpx."""
from __future__ import annotations

import httpx

from .prompts import MAX_TOKENS, SYSTEM


class LLMError(RuntimeError):
    pass


def openai_endpoint(api_url: str) -> str:
    """Resolve a base URL (or full endpoint URL) to the chat-completions endpoint."""
    base = api_url.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def anthropic_endpoint(api_url: str) -> str:
    """Resolve a base URL (or full endpoint URL) to the messages endpoint."""
    base = api_url.rstrip("/")
    if base.endswith("/v1/messages") or base.endswith("/messages"):
        return base
    if base.endswith("/v1"):
        return f"{base}/messages"
    return f"{base}/v1/messages"


def auth_headers(api_key: str) -> dict[str, str]:
    """Bearer header, omitted when no key is set (keyless local servers like Ollama)."""
    if not api_key:
        return {}
    return {"Authorization": f"Bearer {api_key}"}


async def complete_openai(*, api_url: str, api_key: str, model: str, prompt: str, length: str) -> str:
    endpoint = openai_endpoint(api_url)
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
                headers={"Content-Type": "application/json", **auth_headers(api_key)},
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
    endpoint = anthropic_endpoint(api_url)
    payload = {
        "model": model,
        "max_tokens": MAX_TOKENS.get(length, 1200),
        "system": SYSTEM,
        "messages": [{"role": "user", "content": prompt}],
    }
    headers = {"anthropic-version": "2023-06-01", "Content-Type": "application/json"}
    if api_key:
        headers["x-api-key"] = api_key
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(endpoint, headers=headers, json=payload)
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
