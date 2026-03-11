#!/usr/bin/env python3

import io
import json
import socket
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT
sys.path.insert(0, str(PACKAGE_DIR))

from modeio_middleware.cli import middleware as middleware_cli  # noqa: E402
from tests.helpers.gateway_harness import http_get_json  # noqa: E402


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as handle:
        handle.bind(("127.0.0.1", 0))
        return int(handle.getsockname()[1])


def _run_cli_json(args):
    out = io.StringIO()
    with redirect_stdout(out):
        code = middleware_cli.main([*args, "--json"])
    return code, json.loads(out.getvalue())


class TestMiddlewareControllerCLI(unittest.TestCase):
    def test_inspect_codex_reports_controller_unsupported(self):
        code, payload = _run_cli_json(["inspect", "codex"])
        self.assertEqual(code, 0)
        self.assertFalse(payload["harnesses"]["codex"]["controllerSupported"])
        self.assertIn("Codex controller mode is not supported yet", payload["harnesses"]["codex"]["reason"])

    def test_enable_codex_returns_unsupported_exit_code(self):
        code, payload = _run_cli_json(["enable", "codex"])
        self.assertEqual(code, 2)
        self.assertFalse(payload["success"])
        self.assertTrue(payload["unsupported"])

    def test_start_requires_enabled_harnesses(self):
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "modeio" / "middleware.json"
            code, payload = _run_cli_json(["--config", str(config_path), "start"])
        self.assertEqual(code, 1)
        self.assertEqual(payload["reason"], "no_enabled_harnesses")

    def test_enable_claude_starts_server_and_disable_all_stops_it(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "modeio" / "middleware.json"
            claude_settings = root / ".claude" / "settings.json"
            port = _free_port()
            env = {
                "HOME": temp_dir,
                "XDG_CONFIG_HOME": str(root / ".config"),
                "XDG_STATE_HOME": str(root / ".state"),
                "XDG_CACHE_HOME": str(root / ".cache"),
            }
            try:
                with mock.patch.dict("os.environ", env, clear=False):
                    enable_code, enable_payload = _run_cli_json(
                        [
                            "--config",
                            str(config_path),
                            "--claude-settings-path",
                            str(claude_settings),
                            "enable",
                            "claude-code",
                            "--host",
                            "127.0.0.1",
                            "--port",
                            str(port),
                        ]
                    )
                    self.assertEqual(enable_code, 0)
                    self.assertTrue(enable_payload["success"])
                    self.assertTrue(enable_payload["server"]["running"])
                    self.assertTrue(claude_settings.exists())

                    status_code, _, health_payload = http_get_json(
                        f"http://127.0.0.1:{port}",
                        "/healthz",
                    )
                    self.assertEqual(status_code, 200)
                    self.assertTrue(health_payload["ok"])

                    status_code, status_payload = _run_cli_json(
                        [
                            "--config",
                            str(config_path),
                            "status",
                        ]
                    )
                    self.assertEqual(status_code, 0)
                    self.assertTrue(status_payload["server"]["running"])
                    self.assertIn("claude", status_payload["enabledHarnesses"])

                    disable_code, disable_payload = _run_cli_json(
                        [
                            "--config",
                            str(config_path),
                            "disable",
                            "--all",
                        ]
                    )
                    self.assertEqual(disable_code, 0)
                    self.assertTrue(disable_payload["success"])
                    self.assertFalse(disable_payload["server"]["running"])
            finally:
                with mock.patch.dict("os.environ", env, clear=False):
                    _run_cli_json(["--config", str(config_path), "disable", "--all"])


if __name__ == "__main__":
    unittest.main()
