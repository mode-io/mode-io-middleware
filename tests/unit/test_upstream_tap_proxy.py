#!/usr/bin/env python3

import importlib.util
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "scripts" / "upstream_tap_proxy.py"

spec = importlib.util.spec_from_file_location("modeio_upstream_tap_proxy", MODULE_PATH)
assert spec is not None and spec.loader is not None
tap_proxy = importlib.util.module_from_spec(spec)
sys.modules.setdefault("modeio_upstream_tap_proxy", tap_proxy)
spec.loader.exec_module(tap_proxy)


class TestUpstreamTapProxy(unittest.TestCase):
    def test_has_explicit_auth_headers_detects_bearer_and_api_key_forms(self):
        self.assertTrue(
            tap_proxy._has_explicit_auth_headers({"authorization": "Bearer test-token"})
        )
        self.assertTrue(
            tap_proxy._has_explicit_auth_headers({"x-api-key": "sk-ant-test"})
        )
        self.assertTrue(
            tap_proxy._has_explicit_auth_headers({"api-key": "sk-ant-test"})
        )
        self.assertFalse(tap_proxy._has_explicit_auth_headers({}))

    def test_sanitize_headers_for_log_tracks_auth_header_presence(self):
        sanitized = tap_proxy._sanitize_headers_for_log(
            {
                "authorization": "Bearer test-token",
                "x-api-key": "sk-ant-test",
                "content-type": "application/json",
            }
        )

        self.assertTrue(sanitized["authorizationPresent"])
        self.assertEqual(sanitized["authorizationPrefix"], "Bearer")
        self.assertTrue(sanitized["xApiKeyPresent"])
        self.assertFalse(sanitized["apiKeyPresent"])


if __name__ == "__main__":
    unittest.main()
