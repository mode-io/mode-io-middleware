#!/usr/bin/env python3

import gzip
import importlib.util
import json
import sys
import tempfile
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

    def test_write_body_artifacts_stores_raw_and_decoded_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            body_dir = Path(tmp)
            payload = {"ok": True, "items": [1, 2, 3]}
            raw = gzip.compress(json.dumps(payload).encode("utf-8"))

            result = tap_proxy._write_body_artifacts(
                body_dir=body_dir,
                request_id="req123",
                direction="response",
                body=raw,
                content_type="application/json",
                content_encoding="gzip",
            )

            self.assertIsNotNone(result)
            assert result is not None
            raw_path = Path(result["rawBodyPath"])
            decoded_path = Path(result["decodedJsonPath"])
            self.assertTrue(raw_path.exists())
            self.assertTrue(decoded_path.exists())
            self.assertEqual(raw_path.read_bytes(), raw)
            self.assertEqual(json.loads(decoded_path.read_text()), payload)
            self.assertEqual(result["decodedFormat"], "json")
            self.assertEqual(result["decodedFromEncoding"], "gzip")


if __name__ == "__main__":
    unittest.main()
