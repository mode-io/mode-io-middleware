#!/usr/bin/env python3

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT
sys.path.insert(0, str(PACKAGE_DIR))

from modeio_middleware.core.observability.sanitize import sanitize_payload  # noqa: E402


class TestObservabilitySanitize(unittest.TestCase):
    def test_sanitize_payload_masks_sensitive_keys(self):
        payload = {
            "authorization": "Bearer secret",
            "nested": {
                "api_key": "abc123",
            },
        }

        sanitized = sanitize_payload(payload, capture_bodies=True, max_chars=100)

        self.assertEqual(sanitized["authorization"], "***")
        self.assertEqual(sanitized["nested"]["api_key"], "***")

    def test_sanitize_payload_truncates_long_strings(self):
        payload = {"prompt": "abcdefghij"}

        sanitized = sanitize_payload(payload, capture_bodies=True, max_chars=5)

        self.assertEqual(sanitized["prompt"], "abcde...<truncated 5 chars>")

    def test_sanitize_payload_returns_none_when_capture_disabled(self):
        payload = {"prompt": "hello"}

        self.assertIsNone(
            sanitize_payload(payload, capture_bodies=False, max_chars=100)
        )


if __name__ == "__main__":
    unittest.main()
