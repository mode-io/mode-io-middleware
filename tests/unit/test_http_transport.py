#!/usr/bin/env python3

import json
import sys
import unittest
from pathlib import Path

from starlette.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = REPO_ROOT
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from modeio_middleware.core.engine import GatewayRuntimeConfig  # noqa: E402
from modeio_middleware.core.errors import MiddlewareError  # noqa: E402
from modeio_middleware.http_transport import create_app, create_server  # noqa: E402


class TestHttpTransport(unittest.TestCase):
    def setUp(self):
        config = GatewayRuntimeConfig(
            upstream_chat_completions_url="https://upstream.example/v1/chat/completions",
            upstream_responses_url="https://upstream.example/v1/responses",
            upstream_timeout_seconds=5,
            upstream_api_key_env="MODEIO_TEST_UPSTREAM_KEY",
            plugins={},
            profiles={"dev": {"on_plugin_error": "warn", "plugins": []}},
        )
        self.client = TestClient(create_app(config))

    def tearDown(self):
        self.client.close()

    def _assert_contract_headers(self, response):
        self.assertIn("x-modeio-contract-version", response.headers)
        self.assertIn("x-modeio-request-id", response.headers)
        self.assertEqual(response.headers["x-modeio-upstream-called"], "false")

    def test_empty_body_returns_contract_validation_error(self):
        response = self.client.post("/v1/chat/completions", content=b"")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "MODEIO_VALIDATION_ERROR")
        self._assert_contract_headers(response)

    def test_anthropic_messages_route_returns_contract_validation_error_for_empty_body(self):
        response = self.client.post("/v1/messages", content=b"")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "MODEIO_VALIDATION_ERROR")
        self._assert_contract_headers(response)

    def test_malformed_json_returns_contract_validation_error(self):
        response = self.client.post(
            "/v1/chat/completions",
            content=b"{bad",
            headers={"Content-Type": "application/json"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "MODEIO_VALIDATION_ERROR")
        self._assert_contract_headers(response)

    def test_non_object_json_returns_contract_validation_error(self):
        response = self.client.post(
            "/v1/chat/completions",
            content=json.dumps(["not", "an", "object"]).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "MODEIO_VALIDATION_ERROR")
        self._assert_contract_headers(response)

    def test_create_server_rejects_non_loopback_host_without_remote_admin_opt_in(self):
        config = GatewayRuntimeConfig(
            upstream_chat_completions_url="https://upstream.example/v1/chat/completions",
            upstream_responses_url="https://upstream.example/v1/responses",
            upstream_timeout_seconds=5,
            upstream_api_key_env="MODEIO_TEST_UPSTREAM_KEY",
            plugins={},
            profiles={"dev": {"on_plugin_error": "warn", "plugins": []}},
        )

        with self.assertRaises(MiddlewareError) as error_ctx:
            create_server("0.0.0.0", 0, config)

        self.assertEqual(error_ctx.exception.code, "MODEIO_REMOTE_ADMIN_DISABLED")

    def test_create_server_allows_non_loopback_host_when_opted_in(self):
        config = GatewayRuntimeConfig(
            upstream_chat_completions_url="https://upstream.example/v1/chat/completions",
            upstream_responses_url="https://upstream.example/v1/responses",
            upstream_timeout_seconds=5,
            upstream_api_key_env="MODEIO_TEST_UPSTREAM_KEY",
            plugins={},
            profiles={"dev": {"on_plugin_error": "warn", "plugins": []}},
        )

        server = create_server("0.0.0.0", 0, config, allow_remote_admin=True)
        try:
            self.assertIsNotNone(server.server_address)
        finally:
            server.server_close()


if __name__ == "__main__":
    unittest.main()
