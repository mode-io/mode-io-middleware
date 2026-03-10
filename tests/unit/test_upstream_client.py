#!/usr/bin/env python3

import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = REPO_ROOT
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from modeio_middleware.core.engine import GatewayRuntimeConfig  # noqa: E402
from modeio_middleware.core.errors import MiddlewareError  # noqa: E402
from modeio_middleware.core.upstream_client import forward_upstream_json  # noqa: E402


class _FakeResponse:
    def __init__(self, *, status_code: int, payload=None, headers=None, json_error: Exception | None = None):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}
        self._json_error = json_error

    def json(self):
        if self._json_error is not None:
            raise self._json_error
        return self._payload


class _FakeClient:
    def __init__(self, behavior):
        self._behavior = behavior
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def post(self, url, *, headers, json):
        self.calls.append({"url": url, "headers": headers, "json": json})
        if isinstance(self._behavior, Exception):
            raise self._behavior
        return self._behavior


class _ClientFactory:
    def __init__(self, *behaviors):
        self._behaviors = list(behaviors)
        self.instances = []

    def __call__(self, *args, **kwargs):
        del args, kwargs
        behavior = self._behaviors.pop(0)
        client = _FakeClient(behavior)
        self.instances.append(client)
        return client


class TestUpstreamClient(unittest.TestCase):
    def setUp(self):
        self.config = GatewayRuntimeConfig(
            upstream_chat_completions_url="https://upstream.example/v1/chat/completions",
            upstream_responses_url="https://upstream.example/v1/responses",
            upstream_timeout_seconds=5,
            upstream_api_key_env="MODEIO_TEST_UPSTREAM_KEY",
        )

    def test_forward_upstream_json_prefers_incoming_authorization_header(self):
        factory = _ClientFactory(_FakeResponse(status_code=200, payload={"ok": True}))
        with patch("modeio_middleware.core.upstream_client.httpx.Client", side_effect=factory):
            with patch.dict(os.environ, {"MODEIO_TEST_UPSTREAM_KEY": "fallback-secret"}, clear=False):
                response = forward_upstream_json(
                    config=self.config,
                    endpoint_kind="chat_completions",
                    payload={"model": "gpt-test"},
                    incoming_headers={
                        "Authorization": "Bearer incoming-secret",
                        "OpenAI-Organization": "org_test",
                        "x-modeio-debug": "drop-me",
                    },
                )

        self.assertEqual(response.payload, {"ok": True})
        sent_headers = factory.instances[0].calls[0]["headers"]
        self.assertEqual(sent_headers["Authorization"], "Bearer incoming-secret")
        self.assertEqual(sent_headers["OpenAI-Organization"], "org_test")
        self.assertNotIn("x-modeio-debug", sent_headers)

    def test_forward_upstream_json_retries_retryable_status_then_succeeds(self):
        factory = _ClientFactory(
            _FakeResponse(status_code=503, payload={"error": "busy"}),
            _FakeResponse(status_code=200, payload={"ok": True}),
        )
        with patch("modeio_middleware.core.upstream_client.httpx.Client", side_effect=factory):
            with patch("modeio_middleware.core.upstream_client.time.sleep") as sleep_mock:
                response = forward_upstream_json(
                    config=self.config,
                    endpoint_kind="chat_completions",
                    payload={"model": "gpt-test"},
                    incoming_headers={},
                )

        self.assertEqual(response.payload, {"ok": True})
        self.assertEqual(len(factory.instances), 2)
        sleep_mock.assert_called_once()

    def test_forward_upstream_json_returns_sanitized_response_headers(self):
        factory = _ClientFactory(
            _FakeResponse(
                status_code=200,
                payload={"ok": True},
                headers={
                    "openai-request-id": "req_123",
                    "x-ratelimit-limit-requests": "1000",
                    "Content-Length": "999",
                    "Transfer-Encoding": "chunked",
                    "x-modeio-upstream": "drop-me",
                },
            )
        )
        with patch("modeio_middleware.core.upstream_client.httpx.Client", side_effect=factory):
            response = forward_upstream_json(
                config=self.config,
                endpoint_kind="chat_completions",
                payload={"model": "gpt-test"},
                incoming_headers={},
            )

        self.assertEqual(response.headers["openai-request-id"], "req_123")
        self.assertEqual(response.headers["x-ratelimit-limit-requests"], "1000")
        self.assertNotIn("Content-Length", response.headers)
        self.assertNotIn("Transfer-Encoding", response.headers)
        self.assertNotIn("x-modeio-upstream", response.headers)

    def test_forward_upstream_json_rejects_non_object_json(self):
        factory = _ClientFactory(_FakeResponse(status_code=200, payload=["not", "an", "object"]))
        with patch("modeio_middleware.core.upstream_client.httpx.Client", side_effect=factory):
            with self.assertRaises(MiddlewareError) as error_ctx:
                forward_upstream_json(
                    config=self.config,
                    endpoint_kind="chat_completions",
                    payload={"model": "gpt-test"},
                    incoming_headers={},
                )

        self.assertEqual(error_ctx.exception.code, "MODEIO_UPSTREAM_INVALID_JSON")

    def test_forward_upstream_json_preserves_response_headers_on_upstream_error(self):
        factory = _ClientFactory(
            _FakeResponse(
                status_code=429,
                payload={"error": "rate limited"},
                headers={"retry-after": "3", "openai-request-id": "req_429"},
            )
        )
        with patch("modeio_middleware.core.upstream_client.httpx.Client", side_effect=factory):
            with self.assertRaises(MiddlewareError) as error_ctx:
                forward_upstream_json(
                    config=self.config,
                    endpoint_kind="chat_completions",
                    payload={"model": "gpt-test"},
                    incoming_headers={},
                )

        self.assertEqual(error_ctx.exception.status, 429)
        self.assertEqual(error_ctx.exception.headers["retry-after"], "3")
        self.assertEqual(error_ctx.exception.headers["openai-request-id"], "req_429")

    def test_forward_upstream_json_retries_timeout_exception_then_raises(self):
        timeout_error = httpx.ReadTimeout("timed out")
        factory = _ClientFactory(timeout_error, timeout_error, timeout_error)
        with patch("modeio_middleware.core.upstream_client.httpx.Client", side_effect=factory):
            with patch("modeio_middleware.core.upstream_client.time.sleep") as sleep_mock:
                with self.assertRaises(MiddlewareError) as error_ctx:
                    forward_upstream_json(
                        config=self.config,
                        endpoint_kind="chat_completions",
                        payload={"model": "gpt-test"},
                        incoming_headers={},
                    )

        self.assertEqual(error_ctx.exception.code, "MODEIO_UPSTREAM_TIMEOUT")
        self.assertEqual(sleep_mock.call_count, 2)

    def test_forward_upstream_json_routes_anthropic_messages_with_x_api_key(self):
        factory = _ClientFactory(_FakeResponse(status_code=200, payload={"type": "message"}))
        inspection = SimpleNamespace(
            ready=True,
            authorization=None,
            resolved_headers={"x-api-key": "sk-anthropic-test"},
            metadata={
                "apiFamily": "anthropic-messages",
                "upstreamBaseUrl": "https://api.anthropic.com",
            },
            transport="openai_compat",
        )
        with patch("modeio_middleware.core.upstream_client.inspect_client_native_auth", return_value=inspection):
            with patch("modeio_middleware.core.upstream_client.httpx.Client", side_effect=factory):
                response = forward_upstream_json(
                    config=self.config,
                    endpoint_kind="anthropic_messages",
                    payload={
                        "model": "claude-sonnet-4",
                        "messages": [{"role": "user", "content": "hello"}],
                    },
                    incoming_headers={"Authorization": "Bearer modeio-middleware"},
                    client_name="openclaw",
                    client_provider_name="anthropic",
                )

        self.assertEqual(response.payload, {"type": "message"})
        sent = factory.instances[0].calls[0]
        self.assertEqual(sent["url"], "https://api.anthropic.com/v1/messages")
        self.assertEqual(sent["headers"]["x-api-key"], "sk-anthropic-test")
        self.assertEqual(sent["headers"]["anthropic-version"], "2023-06-01")
        self.assertNotIn("Authorization", sent["headers"])

    def test_forward_upstream_json_preserves_explicit_x_api_key_header(self):
        factory = _ClientFactory(_FakeResponse(status_code=200, payload={"type": "message"}))
        inspection = SimpleNamespace(
            ready=False,
            authorization=None,
            resolved_headers={},
            metadata={},
            transport="openai_compat",
        )
        with patch("modeio_middleware.core.upstream_client.inspect_client_native_auth", return_value=inspection):
            with patch("modeio_middleware.core.upstream_client.httpx.Client", side_effect=factory):
                response = forward_upstream_json(
                    config=self.config,
                    endpoint_kind="anthropic_messages",
                    payload={
                        "model": "claude-sonnet-4",
                        "messages": [{"role": "user", "content": "hello"}],
                    },
                    incoming_headers={"x-api-key": "incoming-anthropic-key"},
                    client_name="openclaw",
                    client_provider_name="anthropic",
                )

        self.assertEqual(response.payload, {"type": "message"})
        sent_headers = factory.instances[0].calls[0]["headers"]
        self.assertEqual(sent_headers["x-api-key"], "incoming-anthropic-key")
        self.assertEqual(sent_headers["anthropic-version"], "2023-06-01")

    def test_forward_upstream_json_preserves_explicit_bearer_auth_for_anthropic_messages(self):
        factory = _ClientFactory(_FakeResponse(status_code=200, payload={"type": "message"}))
        inspection = SimpleNamespace(
            ready=True,
            authorization=None,
            resolved_headers={"x-api-key": "fallback-should-not-win"},
            metadata={
                "apiFamily": "anthropic-messages",
                "upstreamBaseUrl": "https://api.anthropic.com",
            },
            transport="openai_compat",
        )
        with patch("modeio_middleware.core.upstream_client.inspect_client_native_auth", return_value=inspection):
            with patch("modeio_middleware.core.upstream_client.httpx.Client", side_effect=factory):
                response = forward_upstream_json(
                    config=self.config,
                    endpoint_kind="anthropic_messages",
                    payload={
                        "model": "claude-sonnet-4",
                        "messages": [{"role": "user", "content": "hello"}],
                    },
                    incoming_headers={"Authorization": "Bearer sk-ant-oat-subscription-token"},
                    client_name="openclaw",
                    client_provider_name="anthropic",
                )

        self.assertEqual(response.payload, {"type": "message"})
        sent_headers = factory.instances[0].calls[0]["headers"]
        self.assertEqual(
            sent_headers["Authorization"],
            "Bearer sk-ant-oat-subscription-token",
        )
        self.assertNotIn("x-api-key", sent_headers)
        self.assertEqual(sent_headers["anthropic-version"], "2023-06-01")

    def test_forward_upstream_json_rejects_deferred_openclaw_family(self):
        inspection = SimpleNamespace(
            ready=False,
            authorization=None,
            resolved_headers={},
            metadata={
                "providerId": "openai-codex",
                "apiFamily": "openai-codex-responses",
                "unsupportedFamily": True,
                "supportedFamilies": [
                    "anthropic-messages",
                    "openai-completions",
                ],
            },
            transport="openai_compat",
        )
        with patch(
            "modeio_middleware.core.upstream_client.inspect_client_native_auth",
            return_value=inspection,
        ):
            with self.assertRaises(MiddlewareError) as error_ctx:
                forward_upstream_json(
                    config=self.config,
                    endpoint_kind="chat_completions",
                    payload={"model": "gpt-test"},
                    incoming_headers={"Authorization": "Bearer modeio-middleware"},
                    client_name="openclaw",
                    client_provider_name="openai-codex",
                )

        self.assertEqual(error_ctx.exception.status, 400)
        self.assertEqual(error_ctx.exception.code, "MODEIO_VALIDATION_ERROR")
        self.assertEqual(
            error_ctx.exception.details["apiFamily"],
            "openai-codex-responses",
        )


if __name__ == "__main__":
    unittest.main()
