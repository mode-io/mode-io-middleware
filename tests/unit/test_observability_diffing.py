#!/usr/bin/env python3

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT
sys.path.insert(0, str(PACKAGE_DIR))

from modeio_middleware.core.observability.diffing import summarize_change  # noqa: E402


class TestObservabilityDiffing(unittest.TestCase):
    def test_summarize_change_counts_add_remove_replace(self):
        before = {
            "messages": [{"content": "hello"}],
            "temperature": 0,
            "remove_me": True,
        }
        after = {
            "messages": [{"content": "hello world"}],
            "temperature": 0,
            "context": "extra",
        }

        summary = summarize_change(before, after, sample_limit=10)

        self.assertTrue(summary.changed)
        self.assertEqual(summary.add_count, 1)
        self.assertEqual(summary.remove_count, 1)
        self.assertEqual(summary.replace_count, 1)
        self.assertIn("/messages/0/content", summary.sample_paths)

    def test_summarize_change_handles_missing_payloads(self):
        summary = summarize_change(None, {"output": "hello"}, sample_limit=5)

        self.assertTrue(summary.changed)
        self.assertEqual(summary.add_count, 1)


if __name__ == "__main__":
    unittest.main()
