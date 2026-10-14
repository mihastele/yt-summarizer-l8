"""Regression tests for LLM endpoint resolution and auth headers.

Run from the repo root:  .venv/bin/python -m unittest discover -s backend/tests -v
"""
import unittest

from backend.llm import anthropic_endpoint, auth_headers, openai_endpoint


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


if __name__ == "__main__":
    unittest.main()
