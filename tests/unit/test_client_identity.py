#!/usr/bin/env python3

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT
sys.path.insert(0, str(PACKAGE_DIR))

from modeio_middleware.connectors.client_identity import (  # noqa: E402
    CLIENT_CLAUDE_CODE,
    CLIENT_CODEX,
    CLIENT_OPENCODE,
    CLIENT_OPENCLAW,
    CLIENT_UNKNOWN,
    detect_openai_client_name,
)


class TestClientIdentity(unittest.TestCase):
    def test_prefers_explicit_client_header(self):
        self.assertEqual(
            detect_openai_client_name({"X-ModeIO-Client": CLIENT_OPENCODE}),
            CLIENT_OPENCODE,
        )

    def test_detects_user_agent_markers(self):
        self.assertEqual(
            detect_openai_client_name({"User-Agent": "OpenCode/0.9"}),
            CLIENT_OPENCODE,
        )
        self.assertEqual(
            detect_openai_client_name({"User-Agent": "Codex CLI/1.2"}),
            CLIENT_CODEX,
        )
        self.assertEqual(
            detect_openai_client_name({"User-Agent": "OpenClaw/2.0"}),
            CLIENT_OPENCLAW,
        )

    def test_returns_unknown_when_no_signal_exists(self):
        self.assertEqual(detect_openai_client_name({}), CLIENT_UNKNOWN)
        self.assertEqual(
            detect_openai_client_name({"User-Agent": "python-urllib/3.14"}),
            CLIENT_UNKNOWN,
        )

    def test_claude_constant_is_stable(self):
        self.assertEqual(CLIENT_CLAUDE_CODE, "claude_code")


if __name__ == "__main__":
    unittest.main()
