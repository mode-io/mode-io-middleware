#!/usr/bin/env python3

import json
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

try:
    from compression import zstd as zstd_codec
except Exception:  # pragma: no cover
    zstd_codec = None

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
TESTS_DIR = REPO_ROOT / "tests"

sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, str(TESTS_DIR))

from helpers.gateway_harness import (  # noqa: E402
    completion_payload,
    http_get_json as _base_http_get_json,
    models_payload,
    post_json as _base_post_json,
    post_raw as _base_post_raw,
    post_stream as _base_post_stream,
    responses_payload,
    start_gateway_pair,
)
from helpers.inspection_builder import build_inspection  # noqa: E402
from helpers.plugin_modules import register_plugin_module  # noqa: E402
from modeio_middleware.plugins.base import MiddlewarePlugin  # noqa: E402

DEFAULT_TEST_AUTH = {"Authorization": "Bearer test-upstream-auth"}


def _merge_auth_headers(headers=None):
    merged = dict(DEFAULT_TEST_AUTH)
    if headers:
        merged.update(headers)
    return merged


def http_get_json(base_url: str, path: str, *, headers=None):
    request_headers = None if path == "/healthz" else _merge_auth_headers(headers)
    return _base_http_get_json(base_url, path, headers=request_headers)


def post_json(base_url: str, path: str, payload, *, headers=None):
    return _base_post_json(base_url, path, payload, headers=_merge_auth_headers(headers))


def post_raw(base_url: str, path: str, body: bytes, *, headers=None):
    return _base_post_raw(base_url, path, body, headers=_merge_auth_headers(headers))


def post_stream(base_url: str, path: str, payload, *, headers=None):
    return _base_post_stream(base_url, path, payload, headers=_merge_auth_headers(headers))


class _BlockerPlugin(MiddlewarePlugin):
    name = "blocker"

    def pre_request(self, _hook_input):
        return {"action": "block", "message": "blocked by blocker plugin"}


def _register_blocker_plugin_module(module_name: str):
    register_plugin_module(module_name, _BlockerPlugin)


class TestGatewayContract(unittest.TestCase):
    def _start_pair(self, response_factory, *, status=200, stream_factory=None, plugins=None, profiles=None):
        return start_gateway_pair(
            response_factory,
            status=status,
            stream_factory=stream_factory,
            plugins=plugins,
            profiles=profiles,
        )

    def test_healthz_reports_ready(self):
        upstream, gateway_stub = self._start_pair(lambda _path, _payload: completion_payload("ok"))
        try:
            status, _headers, payload = http_get_json(gateway_stub.base_url, "/healthz")
            self.assertEqual(status, 200)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["service"], "modeio-middleware")
        finally:
            gateway_stub.stop()
            upstream.stop()

    def test_healthz_includes_dev_instance_id_when_present(self):
        with mock.patch.dict(os.environ, {"MODEIO_DEV_INSTANCE_ID": "dev-instance-123"}):
            upstream, gateway_stub = self._start_pair(
                lambda _path, _payload: completion_payload("ok")
            )
            try:
                status, _headers, payload = http_get_json(gateway_stub.base_url, "/healthz")
                self.assertEqual(status, 200)
                self.assertEqual(payload["devInstanceId"], "dev-instance-123")
            finally:
                gateway_stub.stop()
                upstream.stop()

    def test_chat_modeio_metadata_not_forwarded_to_upstream(self):
        upstream, gateway_stub = self._start_pair(
            lambda _path, payload: completion_payload(payload["messages"][0]["content"])
        )
        try:
            status, _headers, _payload = post_json(
                gateway_stub.base_url,
                "/v1/chat/completions",
                {
                    "model": "gpt-test",
                    "messages": [{"role": "user", "content": "hello"}],
                    "modeio": {"profile": "dev"},
                },
            )
            self.assertEqual(status, 200)
            upstream_payload = upstream.requests[-1]["body"]
            self.assertNotIn("modeio", upstream_payload)
        finally:
            gateway_stub.stop()
            upstream.stop()

    def test_gateway_preserves_safe_upstream_metadata_headers(self):
        upstream, gateway_stub = start_gateway_pair(
            lambda _path, payload: completion_payload(payload["messages"][0]["content"]),
            response_headers={
                "openai-request-id": "req_upstream_123",
                "x-ratelimit-limit-requests": "1000",
                "x-modeio-upstream": "drop-me",
            },
        )
        try:
            status, headers, payload = post_json(
                gateway_stub.base_url,
                "/v1/chat/completions",
                {
                    "model": "gpt-test",
                    "messages": [{"role": "user", "content": "hello passthrough"}],
                },
                headers={
                    "Authorization": "Bearer incoming-secret",
                    "OpenAI-Organization": "org_test",
                    "x-modeio-request-id": "drop-me",
                },
            )
            self.assertEqual(status, 200)
            self.assertEqual(
                payload["choices"][0]["message"]["content"],
                "hello passthrough",
            )
            upstream_request_headers = {
                key.lower(): value for key, value in upstream.requests[-1]["headers"].items()
            }
            self.assertEqual(
                upstream_request_headers["authorization"],
                "Bearer incoming-secret",
            )
            self.assertEqual(
                upstream_request_headers["openai-organization"],
                "org_test",
            )
            self.assertNotIn("x-modeio-request-id", upstream_request_headers)
            self.assertEqual(headers["openai-request-id"], "req_upstream_123")
            self.assertEqual(headers["x-ratelimit-limit-requests"], "1000")
            self.assertNotIn("x-modeio-upstream", headers)
        finally:
            gateway_stub.stop()
            upstream.stop()

    def test_models_route_proxies_upstream_models_payload(self):
        upstream, gateway_stub = self._start_pair(
            lambda path, _payload: models_payload("openai/gpt-5.3-codex")
            if path.startswith("/v1/models")
            else completion_payload("ok")
        )
        try:
            status, headers, payload = http_get_json(gateway_stub.base_url, "/v1/models")
            self.assertEqual(status, 200)
            self.assertEqual(payload["models"][0]["id"], "openai/gpt-5.3-codex")
            self.assertEqual(upstream.requests[-1]["path"], "/v1/models")
            self.assertIn("x-modeio-request-id", {k.lower(): v for k, v in headers.items()})
        finally:
            gateway_stub.stop()
            upstream.stop()

    def test_codex_native_transport_uses_backend_api_paths(self):
        def response_factory(path, payload):
            if path.startswith("/codex/models"):
                return models_payload("gpt-5.4")
            input_items = payload.get("input") or []
            text = "ok"
            if isinstance(input_items, list) and input_items:
                first = input_items[0]
                if isinstance(first, dict):
                    content = first.get("content")
                    if isinstance(content, list) and content:
                        entry = content[0]
                        if isinstance(entry, dict) and isinstance(entry.get("text"), str):
                            text = entry["text"]
            return responses_payload(text)

        upstream, gateway_stub = self._start_pair(
            response_factory
        )
        inspection = build_inspection(
            guaranteed=False,
            authorization="Bearer codex-token",
            transport="codex_native",
            metadata={"nativeBaseUrl": f"{upstream.base_url}/codex", "accountId": "acct-1"},
        )

        try:
            with mock.patch(
                "modeio_middleware.core.upstream_client.inspect_client_native_auth",
                return_value=inspection,
            ):
                status, _headers, models = http_get_json(
                    gateway_stub.base_url,
                    "/clients/codex/v1/models?client_version=0.112.0",
                    headers={"Authorization": "Bearer modeio-middleware"},
                )
                self.assertEqual(status, 200)
                self.assertEqual(models["models"][0]["id"], "gpt-5.4")
                self.assertFalse(models["models"][0].get("supports_websockets", True))
                self.assertFalse(models["models"][0].get("prefer_websockets", True))

                status, _headers, payload = post_json(
                    gateway_stub.base_url,
                    "/clients/codex/v1/responses",
                    {
                        "model": "openai/gpt-5.4",
                        "instructions": "You are Codex",
                        "input": "hello codex transport",
                    },
                    headers={"Authorization": "Bearer modeio-middleware"},
                )
                self.assertEqual(status, 200)
                self.assertEqual(payload["output_text"], "hello codex transport")

            self.assertEqual(upstream.requests[0]["path"], "/codex/models?client_version=0.112.0")
            self.assertEqual(upstream.requests[1]["path"], "/codex/responses")
            self.assertEqual(upstream.requests[1]["headers"]["ChatGPT-Account-Id"], "acct-1")
            self.assertFalse(upstream.requests[1]["body"]["store"])
            self.assertTrue(upstream.requests[1]["body"]["stream"])
        finally:
            gateway_stub.stop()
            upstream.stop()

    def test_client_scoped_codex_route_bridges_auth_from_codex_store(self):
        with TemporaryDirectory() as temp_dir:
            auth_path = Path(temp_dir) / ".codex" / "auth.json"
            auth_path.parent.mkdir(parents=True)
            auth_path.write_text(
                json.dumps(
                    {
                        "tokens": {"access_token": "eyJhbGciOi-test-codex"},
                        "OPENAI_API_KEY": "",
                    }
                ),
                encoding="utf-8",
            )

            def response_factory(_path, payload):
                input_items = payload.get("input") or []
                text = "ok"
                if isinstance(input_items, list) and input_items:
                    first = input_items[0]
                    if isinstance(first, dict):
                        content = first.get("content")
                        if isinstance(content, list) and content:
                            entry = content[0]
                            if isinstance(entry, dict) and isinstance(entry.get("text"), str):
                                text = entry["text"]
                return responses_payload(text)

            upstream, gateway_stub = self._start_pair(response_factory)
            try:
                with mock.patch.dict(
                    os.environ,
                    {
                        "HOME": temp_dir,
                        "MODEIO_CODEX_NATIVE_BASE_URL": f"{upstream.base_url}/codex",
                    },
                    clear=False,
                ):
                    status, _headers, payload = post_json(
                        gateway_stub.base_url,
                        "/clients/codex/v1/chat/completions",
                        {
                            "model": "gpt-test",
                            "messages": [{"role": "user", "content": "hello codex"}],
                        },
                        headers={"Authorization": "Bearer modeio-middleware"},
                    )
                self.assertEqual(status, 200)
                self.assertEqual(payload["output_text"], "hello codex")
                self.assertEqual(
                    upstream.requests[-1]["headers"]["Authorization"],
                    "Bearer eyJhbGciOi-test-codex",
                )
                self.assertEqual(
                    upstream.requests[-1]["path"],
                    "/codex/chat/completions",
                )
            finally:
                gateway_stub.stop()
                upstream.stop()

    def test_client_scoped_openclaw_route_rejects_deferred_openai_codex_family(self):
        upstream, gateway_stub = self._start_pair(
            lambda _path, payload: completion_payload(payload["messages"][0]["content"])
        )
        try:
            status, _headers, payload = post_json(
                gateway_stub.base_url,
                "/clients/openclaw/openai-codex/v1/chat/completions",
                {
                    "model": "gpt-test",
                    "messages": [{"role": "user", "content": "hello openclaw"}],
                },
                headers={"Authorization": "Bearer modeio-middleware"},
            )
            self.assertEqual(status, 400)
            self.assertEqual(payload["error"]["code"], "MODEIO_VALIDATION_ERROR")
            self.assertIn("unsupported API family", payload["error"]["message"])
            self.assertEqual(
                payload["error"]["details"]["apiFamily"],
                "openai-codex-responses",
            )
            self.assertEqual(
                payload["error"]["details"]["providerId"],
                "openai-codex",
            )
            self.assertEqual(upstream.requests, [])
        finally:
            gateway_stub.stop()
            upstream.stop()

    def test_client_scoped_route_normalizes_provider_prefixed_model(self):
        upstream, gateway_stub = self._start_pair(
            lambda _path, payload: completion_payload(payload["model"])
        )
        inspection = build_inspection(
            provider_id="openai-codex",
            authorization="Bearer test-token",
            transport="codex_native",
            metadata={"nativeBaseUrl": f"{upstream.base_url}/codex"},
        )
        try:
            with mock.patch(
                "modeio_middleware.core.upstream_client.inspect_client_native_auth",
                return_value=inspection,
            ):
                status, _headers, payload = post_json(
                    gateway_stub.base_url,
                    "/clients/codex/v1/chat/completions",
                    {
                        "model": "openai/gpt-test",
                        "messages": [{"role": "user", "content": "hello model"}],
                    },
                    headers={"Authorization": "Bearer modeio-middleware"},
                )
            self.assertEqual(status, 200)
            self.assertEqual(payload["choices"][0]["message"]["content"], "gpt-test")
            self.assertEqual(upstream.requests[-1]["body"]["model"], "gpt-test")
        finally:
            gateway_stub.stop()
            upstream.stop()

    def test_responses_modeio_metadata_not_forwarded_to_upstream(self):
        upstream, gateway_stub = self._start_pair(
            lambda _path, payload: responses_payload(str(payload.get("input", "")))
        )
        try:
            status, _headers, payload = post_json(
                gateway_stub.base_url,
                "/v1/responses",
                {
                    "model": "gpt-test",
                    "input": "hello from responses",
                    "modeio": {"profile": "dev"},
                },
            )
            self.assertEqual(status, 200)
            self.assertIn("output_text", payload)
            upstream_payload = upstream.requests[-1]["body"]
            self.assertNotIn("modeio", upstream_payload)
        finally:
            gateway_stub.stop()
            upstream.stop()

    def test_invalid_modeio_plugin_preset_returns_validation_error(self):
        upstream, gateway_stub = self._start_pair(
            lambda _path, payload: completion_payload(payload["messages"][0]["content"])
        )
        try:
            status, _headers, payload = post_json(
                gateway_stub.base_url,
                "/v1/chat/completions",
                {
                    "model": "gpt-test",
                    "messages": [{"role": "user", "content": "hello"}],
                    "modeio": {
                        "plugins": {
                            "custom_policy": {
                                "preset": True,
                            }
                        }
                    },
                },
            )
            self.assertEqual(status, 400)
            self.assertEqual(payload["error"]["code"], "MODEIO_VALIDATION_ERROR")
        finally:
            gateway_stub.stop()
            upstream.stop()

    def test_invalid_modeio_plugin_mode_returns_validation_error(self):
        upstream, gateway_stub = self._start_pair(
            lambda _path, payload: completion_payload(payload["messages"][0]["content"])
        )
        try:
            status, _headers, payload = post_json(
                gateway_stub.base_url,
                "/v1/chat/completions",
                {
                    "model": "gpt-test",
                    "messages": [{"role": "user", "content": "hello"}],
                    "modeio": {
                        "plugins": {
                            "custom_policy": {
                                "mode": True,
                            }
                        }
                    },
                },
            )
            self.assertEqual(status, 400)
            self.assertEqual(payload["error"]["code"], "MODEIO_VALIDATION_ERROR")
        finally:
            gateway_stub.stop()
            upstream.stop()

    @unittest.skipIf(zstd_codec is None, "compression.zstd unavailable")
    def test_responses_accepts_zstd_encoded_request_body(self):
        upstream, gateway_stub = self._start_pair(
            lambda _path, payload: responses_payload(str(payload.get("input", "")))
        )
        try:
            raw_payload = json.dumps(
                {
                    "model": "gpt-test",
                    "input": "hello zstd",
                    "modeio": {"profile": "dev"},
                }
            ).encode("utf-8")
            encoded = zstd_codec.compress(raw_payload)

            status, _headers, payload = post_raw(
                gateway_stub.base_url,
                "/v1/responses",
                encoded,
                headers={"Content-Encoding": "zstd"},
            )
            self.assertEqual(status, 200)
            self.assertIn("output_text", payload)
            self.assertEqual(upstream.requests[-1]["body"]["input"], "hello zstd")
        finally:
            gateway_stub.stop()
            upstream.stop()

    def test_rejects_unknown_content_encoding(self):
        upstream, gateway_stub = self._start_pair(
            lambda _path, payload: responses_payload(str(payload.get("input", "")))
        )
        try:
            raw_payload = json.dumps(
                {
                    "model": "gpt-test",
                    "input": "hello",
                }
            ).encode("utf-8")
            status, _headers, payload = post_raw(
                gateway_stub.base_url,
                "/v1/responses",
                raw_payload,
                headers={"Content-Encoding": "snappy"},
            )
            self.assertEqual(status, 400)
            self.assertEqual(payload["error"]["code"], "MODEIO_VALIDATION_ERROR")
            self.assertIn("unsupported Content-Encoding", payload["error"]["message"])
        finally:
            gateway_stub.stop()
            upstream.stop()

    def test_chat_stream_is_passed_through(self):
        def stream_factory(_path, payload):
            content = payload["messages"][0]["content"]
            return [
                {"choices": [{"delta": {"content": f"Echo: {content}"}}]},
                "[DONE]",
            ]

        upstream, gateway_stub = self._start_pair(
            lambda _path, _payload: completion_payload("unused"),
            stream_factory=stream_factory,
        )
        try:
            status, headers, body = post_stream(
                gateway_stub.base_url,
                "/v1/chat/completions",
                {
                    "model": "gpt-test",
                    "messages": [{"role": "user", "content": "hello stream"}],
                    "stream": True,
                },
            )
            self.assertEqual(status, 200)
            self.assertEqual(headers["x-modeio-upstream-called"], "true")
            self.assertEqual(headers["x-modeio-streaming"], "true")
            self.assertIn("Echo: hello stream", body)
            self.assertIn("[DONE]", body)
        finally:
            gateway_stub.stop()
            upstream.stop()

    def test_responses_stream_is_passed_through(self):
        def stream_factory(_path, _payload):
            return [
                {"type": "response.output_text.delta", "delta": "hello"},
                {"type": "response.completed"},
                "[DONE]",
            ]

        upstream, gateway_stub = self._start_pair(
            lambda _path, _payload: responses_payload("unused"),
            stream_factory=stream_factory,
        )
        try:
            status, headers, body = post_stream(
                gateway_stub.base_url,
                "/v1/responses",
                {
                    "model": "gpt-test",
                    "input": "hello response stream",
                    "stream": True,
                },
            )
            self.assertEqual(status, 200)
            self.assertEqual(headers["x-modeio-streaming"], "true")
            self.assertIn("response.output_text.delta", body)
            self.assertIn("[DONE]", body)
        finally:
            gateway_stub.stop()
            upstream.stop()

    def test_redact_plugin_shields_and_restores_non_stream_chat(self):
        plugins = {
            "redact": {
                "enabled": True,
                "module": "modeio_middleware.plugins.redact",
            },
        }
        profiles = {
            "dev": {
                "on_plugin_error": "warn",
                "plugins": ["redact"],
            }
        }

        def echo_user_content(_path, payload):
            content = payload["messages"][0]["content"]
            return completion_payload(f"Echo: {content}")

        upstream, gateway_stub = self._start_pair(echo_user_content, plugins=plugins, profiles=profiles)
        try:
            status, headers, payload = post_json(
                gateway_stub.base_url,
                "/v1/chat/completions",
                {
                    "model": "gpt-test",
                    "messages": [
                        {
                            "role": "user",
                            "content": "Please email alice@example.com about account reset.",
                        }
                    ],
                },
            )
            self.assertEqual(status, 200)

            upstream_payload = upstream.requests[-1]["body"]
            self.assertNotIn("alice@example.com", json.dumps(upstream_payload))
            self.assertIn("__MIO_EMAIL_", json.dumps(upstream_payload))

            content = payload["choices"][0]["message"]["content"]
            self.assertIn("alice@example.com", content)
            self.assertIn("redact:modify", headers["x-modeio-pre-actions"])
        finally:
            gateway_stub.stop()
            upstream.stop()

    def test_redact_plugin_restores_streamed_chat_content(self):
        plugins = {
            "redact": {
                "enabled": True,
                "module": "modeio_middleware.plugins.redact",
            },
        }
        profiles = {
            "dev": {
                "on_plugin_error": "warn",
                "plugins": ["redact"],
            }
        }

        def stream_factory(_path, payload):
            content = payload["messages"][0]["content"]
            return [
                {"choices": [{"delta": {"content": f"Echo: {content}"}}]},
                "[DONE]",
            ]

        upstream, gateway_stub = self._start_pair(
            lambda _path, _payload: completion_payload("unused"),
            stream_factory=stream_factory,
            plugins=plugins,
            profiles=profiles,
        )
        try:
            status, _headers, body = post_stream(
                gateway_stub.base_url,
                "/v1/chat/completions",
                {
                    "model": "gpt-test",
                    "messages": [{"role": "user", "content": "email alice@example.com"}],
                    "stream": True,
                },
            )
            self.assertEqual(status, 200)
            self.assertNotIn("__MIO_EMAIL_", body)
            self.assertIn("alice@example.com", body)
            self.assertNotIn("alice@example.com", json.dumps(upstream.requests[-1]["body"]))
        finally:
            gateway_stub.stop()
            upstream.stop()

    def test_blocking_plugin_blocks_before_upstream_call(self):
        module_name = "modeio_middleware.tests.plugins.blocker"
        _register_blocker_plugin_module(module_name)

        plugins = {
            "blocker": {
                "enabled": True,
                "module": module_name,
            }
        }
        profiles = {
            "dev": {
                "on_plugin_error": "warn",
                "plugins": ["blocker"],
            }
        }

        upstream, gateway_stub = self._start_pair(
            lambda _path, payload: completion_payload(payload["messages"][0]["content"]),
            plugins=plugins,
            profiles=profiles,
        )
        try:
            status, headers, payload = post_json(
                gateway_stub.base_url,
                "/v1/chat/completions",
                {
                    "model": "gpt-test",
                    "messages": [{"role": "user", "content": "hello"}],
                },
            )
            self.assertEqual(status, 403)
            self.assertEqual(payload["error"]["code"], "MODEIO_PLUGIN_BLOCKED")
            self.assertEqual(headers["x-modeio-upstream-called"], "false")
            self.assertEqual(len(upstream.requests), 0)
        finally:
            gateway_stub.stop()
            upstream.stop()

    def test_profile_plugin_override_can_enable_plugin(self):
        module_name = "modeio_middleware.tests.plugins.blocker_profile_enabled"
        _register_blocker_plugin_module(module_name)

        plugins = {
            "blocker": {
                "enabled": False,
                "module": module_name,
            }
        }
        profiles = {
            "profile_with_override": {
                "on_plugin_error": "warn",
                "plugins": ["blocker"],
                "plugin_overrides": {
                    "blocker": {
                        "enabled": True,
                    }
                },
            }
        }

        upstream, gateway_stub = self._start_pair(
            lambda _path, payload: completion_payload(payload["messages"][0]["content"]),
            plugins=plugins,
            profiles=profiles,
        )
        try:
            status, _headers, payload = post_json(
                gateway_stub.base_url,
                "/v1/chat/completions",
                {
                    "model": "gpt-test",
                    "messages": [{"role": "user", "content": "hello"}],
                    "modeio": {
                        "profile": "profile_with_override",
                    },
                },
            )
            self.assertEqual(status, 403)
            self.assertEqual(payload["error"]["code"], "MODEIO_PLUGIN_BLOCKED")
            self.assertEqual(len(upstream.requests), 0)
        finally:
            gateway_stub.stop()
            upstream.stop()

    def test_request_plugin_override_wins_over_profile_plugin_override(self):
        module_name = "modeio_middleware.tests.plugins.blocker_profile_override"
        _register_blocker_plugin_module(module_name)

        plugins = {
            "blocker": {
                "enabled": False,
                "module": module_name,
            }
        }
        profiles = {
            "profile_with_override": {
                "on_plugin_error": "warn",
                "plugins": ["blocker"],
                "plugin_overrides": {
                    "blocker": {
                        "enabled": True,
                    }
                },
            }
        }

        upstream, gateway_stub = self._start_pair(
            lambda _path, payload: completion_payload(payload["messages"][0]["content"]),
            plugins=plugins,
            profiles=profiles,
        )
        try:
            status, _headers, _payload = post_json(
                gateway_stub.base_url,
                "/v1/chat/completions",
                {
                    "model": "gpt-test",
                    "messages": [{"role": "user", "content": "hello"}],
                    "modeio": {
                        "profile": "profile_with_override",
                        "plugins": {
                            "blocker": {
                                "enabled": False,
                            }
                        },
                    },
                },
            )
            self.assertEqual(status, 200)
            self.assertEqual(len(upstream.requests), 1)
        finally:
            gateway_stub.stop()
            upstream.stop()


if __name__ == "__main__":
    unittest.main()
