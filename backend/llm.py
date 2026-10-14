"""Minimal OpenAI- and Anthropic-compatible chat clients over httpx."""
from __future__ import annotations

import logging
import re
from typing import Any, Callable

import httpx

from .prompts import MAX_TOKENS, SYSTEM

logger = logging.getLogger("yt-summarizer")

# Total attempts per request. Only empty or cut-off 200 responses are retried —
# transport failures, HTTP errors, and content-filter refusals fail fast.
MAX_ATTEMPTS = 3

# Finish/stop reasons that mean "the provider refused" — retrying is futile.
REFUSAL_REASONS = {"content_filter"}


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


_THINK_BLOCK = re.compile(r"<think(?:ing)?>.*?</think(?:ing)?>", re.DOTALL | re.IGNORECASE)


def _strip_thinking(text: str) -> str:
    """Drop inline <think>...</think> traces some providers leave in content."""
    return _THINK_BLOCK.sub("", text).strip()


def parse_openai_content(data: dict[str, Any], raw: str) -> tuple[str, str | None]:
    """Extract (content, finish_reason) from a chat-completions body.

    Thinking/reasoning models are handled two ways: inline <think> traces are
    stripped from content, and when content itself is empty the separate
    reasoning fields some gateways use (reasoning_content, reasoning) are
    used as a fallback. Still-empty content is returned as "" so the caller
    can retry; malformed bodies raise.
    """
    try:
        choices = data.get("choices") or []
        if not choices:
            raise ValueError("no choices")
        choice = choices[0]
        message = choice.get("message") or {}
        content = message.get("content") or ""
        if isinstance(content, list):
            content = "\n".join(
                str(part.get("text", "")) for part in content if isinstance(part, dict)
            )
        text = _strip_thinking(str(content))
        if not text:
            for key in ("reasoning_content", "reasoning"):
                fallback = message.get(key) or ""
                text = _strip_thinking(str(fallback))
                if text:
                    break
        return text, choice.get("finish_reason")
    except (AttributeError, ValueError) as exc:
        raise LLMError(f"Unexpected OpenAI-compatible response shape: {raw[:500]}") from exc


def parse_anthropic_content(data: dict[str, Any], raw: str) -> tuple[str, str | None]:
    """Extract (text, stop_reason) from a messages body. See parse_openai_content."""
    try:
        blocks = data.get("content", [])
        texts = [b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "text"]
        combined = "\n".join(t for t in texts if t).strip()
        if not combined and blocks and isinstance(blocks[0], dict):
            combined = str(blocks[0].get("text", "") or "").strip()
        return combined, data.get("stop_reason")
    except AttributeError as exc:
        raise LLMError(f"Unexpected Anthropic-compatible response shape: {raw[:500]}") from exc


async def _post_with_retry(
    *,
    label: str,
    model: str,
    endpoint: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    parse: Callable[[dict[str, Any], str], tuple[str, str | None]],
    truncated_reasons: set[str],
) -> str:
    """POST once, retrying empty or cut-off completions up to MAX_ATTEMPTS."""
    last_problem = "unknown"
    last_raw = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(endpoint, headers=headers, json=payload)
        except httpx.HTTPError as exc:
            raise LLMError(f"{label} request failed: {exc}") from exc
        if response.status_code >= 400:
            raise LLMError(f"{label} API error {response.status_code}: {response.text[:500]}")
        try:
            data = response.json()
        except Exception as exc:
            raise LLMError(f"{label} returned invalid JSON: {response.text[:500]}") from exc
        content, stop_reason = parse(data, response.text)
        if content and stop_reason not in truncated_reasons:
            return content
        if not content and stop_reason in REFUSAL_REASONS:
            raise LLMError(
                f"{label} request was refused (model '{model}', finish_reason '{stop_reason}'). "
                "The provider declined to generate this summary."
            )
        last_raw = response.text
        if not content:
            last_problem = f"came back empty (finish_reason={stop_reason})"
        else:
            last_problem = f"was cut off early ({stop_reason})"
        logger.warning(
            "%s attempt %d/%d (model '%s'): response %s; retrying",
            label, attempt, MAX_ATTEMPTS, model, last_problem,
        )
    raise LLMError(
        f"{label} failed after {MAX_ATTEMPTS} attempts (model '{model}'): "
        f"last response {last_problem}. "
        "If this keeps happening, the model id or endpoint is likely wrong for this provider — "
        "check OPENAI_MODEL / OPENAI_API_URL (or the Anthropic equivalents). "
        f"Last raw response: {last_raw[:300]}"
    )


async def complete_openai(
    *,
    api_url: str,
    api_key: str,
    model: str,
    prompt: str,
    length: str,
    temperature: float = 0.4,
    reasoning_effort: str | None = None,
) -> str:
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
        "max_tokens": MAX_TOKENS.get(length, 1200),
    }
    if reasoning_effort:
        # Top-level param understood by Ollama Cloud and DeepSeek-style
        # endpoints ("none" disables thinking); omitted entirely otherwise
        # since strict providers reject unknown parameters.
        payload["reasoning_effort"] = reasoning_effort
    return await _post_with_retry(
        label="OpenAI-compatible",
        model=model,
        endpoint=openai_endpoint(api_url),
        headers={"Content-Type": "application/json", **auth_headers(api_key)},
        payload=payload,
        parse=parse_openai_content,
        truncated_reasons={"length"},
    )


async def complete_anthropic(
    *,
    api_url: str,
    api_key: str,
    model: str,
    prompt: str,
    length: str,
    temperature: float = 0.4,
) -> str:
    headers = {"anthropic-version": "2023-06-01", "Content-Type": "application/json"}
    if api_key:
        headers["x-api-key"] = api_key
    return await _post_with_retry(
        label="Anthropic-compatible",
        model=model,
        endpoint=anthropic_endpoint(api_url),
        headers=headers,
        payload={
            "model": model,
            "max_tokens": MAX_TOKENS.get(length, 1200),
            "temperature": temperature,
            "system": SYSTEM,
            "messages": [{"role": "user", "content": prompt}],
        },
        parse=parse_anthropic_content,
        truncated_reasons={"max_tokens"},
    )
