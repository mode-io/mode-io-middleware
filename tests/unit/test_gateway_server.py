#!/usr/bin/env python3

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = REPO_ROOT
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from modeio_middleware.core.engine import GatewayRuntimeConfig  # noqa: E402
from modeio_middleware.core.errors import MiddlewareError  # noqa: E402
from modeio_middleware.http_transport import create_server  # noqa: E402


class TestGatewayServer(unittest.TestCase):
    def setUp(self):
        self.config = GatewayRuntimeConfig(
            upstream_chat_completions_url="https://upstream.example/v1/chat/completions",
            upstream_responses_url="https://upstream.example/v1/responses",
            upstream_timeout_seconds=5,
            upstream_api_key_env="MODEIO_TEST_UPSTREAM_KEY",
            plugins={},
            profiles={"dev": {"on_plugin_error": "warn", "plugins": []}},
        )

    def test_create_server_rejects_non_loopback_without_remote_admin_opt_in(self):
        with self.assertRaises(MiddlewareError) as error_ctx:
            create_server("0.0.0.0", 0, self.config)

        self.assertEqual(error_ctx.exception.code, "MODEIO_REMOTE_ADMIN_DISABLED")

    def test_create_server_allows_non_loopback_with_remote_admin_opt_in(self):
        with patch("modeio_middleware.http_transport.GatewayServer") as server_cls:
            server = create_server(
                "0.0.0.0",
                0,
                self.config,
                allow_remote_admin=True,
            )

        self.assertIs(server, server_cls.return_value)
        server_cls.assert_called_once()


if __name__ == "__main__":
    unittest.main()
