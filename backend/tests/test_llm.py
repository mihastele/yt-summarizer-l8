"""Regression tests for LLM endpoint resolution, parsing, and retries.

Run from the repo root:  .venv/bin/python -m unittest discover -s backend/tests -v
"""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from backend.llm import (
    LLMError,
    anthropic_endpoint,
    auth_headers,
    complete_anthropic,
    complete_openai,
    openai_endpoint,
    parse_anthropic_content,
    parse_openai_content,
)


class OpenAIEndpointTests(unittest.TestCase):
    def test_base_url(self):
        self.assertEqual(
            openai_endpoint("https://api.openai.com/v1"),
            "https://api.openai.com/v1/chat/completions",
        )

    def test_trailing_slash(self):
        self.assertEqual(
            openai_endpoint("https://api.openai.com/v1/"),
            "https://api.openai.com/v1/chat/completions",
        )

    def test_full_url_passthrough(self):
        url = "https://proxy.example.com/v1/chat/completions"
        self.assertEqual(openai_endpoint(url), url)

    def test_ollama_from_compose(self):
        # The documented Ollama URL for docker compose must resolve correctly.
        self.assertEqual(
            openai_endpoint("http://host.docker.internal:11434/v1"),
            "http://host.docker.internal:11434/v1/chat/completions",
        )

    def test_ollama_local_dev(self):
        self.assertEqual(
            openai_endpoint("http://localhost:11434/v1"),
            "http://localhost:11434/v1/chat/completions",
        )


class AnthropicEndpointTests(unittest.TestCase):
    def test_base_url(self):
        self.assertEqual(
            anthropic_endpoint("https://api.anthropic.com"),
            "https://api.anthropic.com/v1/messages",
        )

    def test_v1_base(self):
        self.assertEqual(
            anthropic_endpoint("https://api.anthropic.com/v1"),
            "https://api.anthropic.com/v1/messages",
        )

    def test_full_url_passthrough(self):
        url = "https://proxy.example.com/v1/messages"
        self.assertEqual(anthropic_endpoint(url), url)


class AuthHeaderTests(unittest.TestCase):
    def test_key_sent_as_bearer(self):
        self.assertEqual(auth_headers("sk-test"), {"Authorization": "Bearer sk-test"})

    def test_empty_key_omits_header(self):
        # Keyless local servers (e.g. Ollama) must not receive an empty header.
        self.assertEqual(auth_headers(""), {})


def _openai_body(content, finish_reason="stop"):
    return {"choices": [{"message": {"content": content}, "finish_reason": finish_reason}]}


def _anthropic_body(text, stop_reason="end_turn"):
    return {"content": [{"type": "text", "text": text}], "stop_reason": stop_reason}


class ParseOpenAIContentTests(unittest.TestCase):
    def test_full_response(self):
        body = _openai_body("  Hello world  ")
        content, stop = parse_openai_content(body, json.dumps(body))
        self.assertEqual((content, stop), ("Hello world", "stop"))

    def test_empty_string_is_returned_for_retry(self):
        body = _openai_body("")
        content, _ = parse_openai_content(body, json.dumps(body))
        self.assertEqual(content, "")

    def test_null_content_is_empty_not_none_string(self):
        # Must not become the literal text "None" saved as a summary.
        body = _openai_body(None)
        content, _ = parse_openai_content(body, json.dumps(body))
        self.assertEqual(content, "")

    def test_missing_choices_raises(self):
        with self.assertRaises(LLMError):
            parse_openai_content({"choices": []}, "{}")

    def test_non_dict_raises(self):
        with self.assertRaises(LLMError):
            parse_openai_content([], "[]")

    def test_think_blocks_stripped_from_content(self):
        body = _openai_body("<think>internal reasoning</think>  Real summary  ")
        content, stop = parse_openai_content(body, json.dumps(body))
        self.assertEqual((content, stop), ("Real summary", "stop"))

    def test_think_only_content_is_empty_for_retry(self):
        body = _openai_body("<thinking>hmm</thinking>")
        content, _ = parse_openai_content(body, json.dumps(body))
        self.assertEqual(content, "")

    def test_reasoning_content_fallback_when_content_empty(self):
        body = {"choices": [{"message": {"content": "", "reasoning_content": "Recovered"}, "finish_reason": "stop"}]}
        content, _ = parse_openai_content(body, json.dumps(body))
        self.assertEqual(content, "Recovered")

    def test_reasoning_field_fallback_when_content_empty(self):
        body = {"choices": [{"message": {"content": None, "reasoning": "Recovered"}, "finish_reason": "stop"}]}
        content, _ = parse_openai_content(body, json.dumps(body))
        self.assertEqual(content, "Recovered")

    def test_list_content_blocks_joined(self):
        body = {"choices": [{"message": {"content": [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]}, "finish_reason": "stop"}]}
        content, _ = parse_openai_content(body, json.dumps(body))
        self.assertEqual(content, "a\nb")


class ParseAnthropicContentTests(unittest.TestCase):
    def test_full_response(self):
        body = _anthropic_body("Hi")
        text, stop = parse_anthropic_content(body, json.dumps(body))
        self.assertEqual((text, stop), ("Hi", "end_turn"))

    def test_empty_blocks_return_empty_for_retry(self):
        body = {"content": [], "stop_reason": "end_turn"}
        text, _ = parse_anthropic_content(body, json.dumps(body))
        self.assertEqual(text, "")

    def test_truncation_reason_preserved(self):
        body = _anthropic_body("partial…", "max_tokens")
        _, stop = parse_anthropic_content(body, json.dumps(body))
        self.assertEqual(stop, "max_tokens")


def _fake_response(status=200, body=None):
    text = json.dumps(body) if body is not None else ""
    resp = SimpleNamespace(status_code=status, text=text)
    resp.json = MagicMock(return_value=body)
    return resp


def _patched_client(*responses):
    """Patch httpx.AsyncClient used inside backend.llm; returns (patcher, post_mock)."""
    post = AsyncMock(side_effect=list(responses))
    client = MagicMock()
    client.post = post
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=client)
    context.__aexit__ = AsyncMock(return_value=False)
    return patch("backend.llm.httpx.AsyncClient", MagicMock(return_value=context)), post


class RetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_then_good_returns_summary(self):
        patcher, post = _patched_client(
            _fake_response(200, _openai_body("")),
            _fake_response(200, _openai_body("Recovered")),
        )
        with patcher:
            result = await complete_openai(
                api_url="https://x/v1", api_key="k", model="m", prompt="p", length="quick"
            )
        self.assertEqual(result, "Recovered")
        self.assertEqual(post.call_count, 2)

    async def test_persistent_empty_fails_after_three_attempts(self):
        patcher, post = _patched_client(*[_fake_response(200, _openai_body(""))] * 3)
        with patcher:
            with self.assertRaises(LLMError) as ctx:
                await complete_openai(
                    api_url="https://x/v1", api_key="k", model="m", prompt="p", length="quick"
                )
        self.assertIn("3 attempts", str(ctx.exception))
        self.assertIn("empty", str(ctx.exception))
        self.assertEqual(post.call_count, 3)

    async def test_cut_off_output_retries_then_succeeds(self):
        patcher, post = _patched_client(
            _fake_response(200, _openai_body("stub…", "length")),
            _fake_response(200, _openai_body("Full summary")),
        )
        with patcher:
            result = await complete_openai(
                api_url="https://x/v1", api_key="k", model="m", prompt="p", length="long"
            )
        self.assertEqual(result, "Full summary")
        self.assertEqual(post.call_count, 2)

    async def test_content_filter_refusal_fails_fast(self):
        patcher, post = _patched_client(_fake_response(200, _openai_body("", "content_filter")))
        with patcher:
            with self.assertRaises(LLMError) as ctx:
                await complete_openai(
                    api_url="https://x/v1", api_key="k", model="m", prompt="p", length="quick"
                )
        self.assertIn("refused", str(ctx.exception))
        self.assertIn("content_filter", str(ctx.exception))
        self.assertEqual(post.call_count, 1)

    async def test_empty_error_names_finish_reason_and_raw_body(self):
        patcher, _ = _patched_client(*[_fake_response(200, _openai_body(""))] * 3)
        with patcher:
            with self.assertRaises(LLMError) as ctx:
                await complete_openai(
                    api_url="https://x/v1", api_key="k", model="m", prompt="p", length="quick"
                )
        message = str(ctx.exception)
        self.assertIn("finish_reason=stop", message)
        self.assertIn("Last raw response", message)
        self.assertIn("OPENAI_MODEL", message)

    async def test_http_error_does_not_retry(self):
        patcher, post = _patched_client(_fake_response(404, {"error": "nope"}))
        with patcher:
            with self.assertRaises(LLMError):
                await complete_openai(
                    api_url="https://x/v1", api_key="k", model="m", prompt="p", length="quick"
                )
        self.assertEqual(post.call_count, 1)

    async def test_transport_error_does_not_retry(self):
        patcher, post = _patched_client(httpx.ConnectError("boom"))
        with patcher:
            with self.assertRaises(LLMError):
                await complete_openai(
                    api_url="https://x/v1", api_key="k", model="m", prompt="p", length="quick"
                )
        self.assertEqual(post.call_count, 1)

    async def test_reasoning_effort_sent_when_configured(self):
        patcher, post = _patched_client(_fake_response(200, _openai_body("Hi")))
        with patcher:
            result = await complete_openai(
                api_url="https://x/v1", api_key="k", model="m", prompt="p",
                length="quick", reasoning_effort="none",
            )
        self.assertEqual(result, "Hi")
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["reasoning_effort"], "none")
        self.assertEqual(payload["temperature"], 0.4)

    async def test_reasoning_effort_omitted_by_default(self):
        patcher, post = _patched_client(_fake_response(200, _openai_body("Hi")))
        with patcher:
            await complete_openai(
                api_url="https://x/v1", api_key="k", model="m", prompt="p", length="quick"
            )
        payload = post.call_args.kwargs["json"]
        self.assertNotIn("reasoning_effort", payload)
        self.assertEqual(payload["temperature"], 0.4)

    async def test_custom_temperature_sent(self):
        patcher, post = _patched_client(_fake_response(200, _openai_body("Hi")))
        with patcher:
            await complete_openai(
                api_url="https://x/v1", api_key="k", model="m", prompt="p",
                length="quick", temperature=0.7,
            )
        self.assertEqual(post.call_args.kwargs["json"]["temperature"], 0.7)

    async def test_anthropic_empty_retries(self):
        patcher, post = _patched_client(
            _fake_response(200, {"content": [], "stop_reason": "end_turn"}),
            _fake_response(200, _anthropic_body("Recovered")),
        )
        with patcher:
            result = await complete_anthropic(
                api_url="https://x", api_key="k", model="m", prompt="p", length="quick"
            )
        self.assertEqual(result, "Recovered")
        self.assertEqual(post.call_count, 2)


if __name__ == "__main__":
    unittest.main()
