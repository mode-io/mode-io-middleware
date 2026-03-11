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
HELPERS_DIR = REPO_ROOT / "tests" / "helpers"
sys.path.insert(0, str(PACKAGE_DIR))
sys.path.insert(0, str(HELPERS_DIR))

from modeio_middleware.cli import middleware as middleware_cli  # noqa: E402
from gateway_harness import http_get_json  # noqa: E402


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as handle:
        handle.bind(("127.0.0.1", 0))
        return int(handle.getsockname()[1])


def _run_cli_json(args):
    out = io.StringIO()
    with redirect_stdout(out):
        code = middleware_cli.main([*args, "--json"])
    return code, json.loads(out.getvalue())


class TestSmokeControllerFlows(unittest.TestCase):
    def test_openclaw_enable_and_disable_all(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "modeio" / "middleware.json"
            openclaw_config = root / "openclaw-state" / "openclaw.json"
            models_cache = root / "openclaw-state" / "agents" / "main" / "agent" / "models.json"
            openclaw_config.parent.mkdir(parents=True, exist_ok=True)
            models_cache.parent.mkdir(parents=True, exist_ok=True)
            openclaw_config.write_text(
                json.dumps(
                    {
                        "agents": {"defaults": {"model": {"primary": "openai/gpt-4.1"}}},
                        "models": {
                            "providers": {
                                "openai": {
                                    "api": "openai-completions",
                                    "baseUrl": "https://api.openai.com/v1",
                                    "apiKey": "sk-openclaw-test",
                                }
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            models_cache.write_text(
                json.dumps(
                    {
                        "models": {
                            "providers": {
                                "openai": {
                                    "api": "openai-completions",
                                    "baseUrl": "https://api.openai.com/v1",
                                    "apiKey": "sk-openclaw-test",
                                }
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            port = _free_port()
            env = {
                "HOME": temp_dir,
                "OPENCLAW_CONFIG_PATH": str(openclaw_config),
                "OPENCLAW_STATE_DIR": str(root / "openclaw-state"),
                "OPENCLAW_AGENT_DIR": str(models_cache.parent),
                "PI_CODING_AGENT_DIR": str(models_cache.parent),
            }
            try:
                with mock.patch.dict("os.environ", env, clear=False):
                    enable_code, enable_payload = _run_cli_json(
                        [
                            "--config",
                            str(config_path),
                            "--openclaw-config-path",
                            str(openclaw_config),
                            "--openclaw-models-cache-path",
                            str(models_cache),
                            "enable",
                            "openclaw",
                            "--host",
                            "127.0.0.1",
                            "--port",
                            str(port),
                        ]
                    )
                    self.assertEqual(enable_code, 0)
                    self.assertTrue(enable_payload["success"])

                    config_payload = json.loads(openclaw_config.read_text(encoding="utf-8"))
                    provider = config_payload["models"]["providers"]["openai"]
                    self.assertEqual(
                        provider["baseUrl"],
                        f"http://127.0.0.1:{port}/clients/openclaw/openai/v1",
                    )

                    status_code, _, health_payload = http_get_json(
                        f"http://127.0.0.1:{port}",
                        "/healthz",
                    )
                    self.assertEqual(status_code, 200)
                    self.assertTrue(health_payload["ok"])

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

                    config_after = json.loads(openclaw_config.read_text(encoding="utf-8"))
                    self.assertEqual(
                        config_after["models"]["providers"]["openai"]["baseUrl"],
                        "https://api.openai.com/v1",
                    )
            finally:
                with mock.patch.dict("os.environ", env, clear=False):
                    _run_cli_json(["--config", str(config_path), "disable", "--all"])

    def test_claude_enable_and_disable_all(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "modeio" / "middleware.json"
            claude_settings = root / ".claude" / "settings.json"
            port = _free_port()
            env = {"HOME": temp_dir}
            try:
                with mock.patch.dict("os.environ", env, clear=False):
                    enable_code, enable_payload = _run_cli_json(
                        [
                            "--config",
                            str(config_path),
                            "--claude-settings-path",
                            str(claude_settings),
                            "enable",
                            "claude",
                            "--host",
                            "127.0.0.1",
                            "--port",
                            str(port),
                        ]
                    )
                    self.assertEqual(enable_code, 0)
                    self.assertTrue(enable_payload["success"])
                    self.assertTrue(claude_settings.exists())

                    status_code, _, health_payload = http_get_json(
                        f"http://127.0.0.1:{port}",
                        "/healthz",
                    )
                    self.assertEqual(status_code, 200)
                    self.assertTrue(health_payload["ok"])

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
            finally:
                with mock.patch.dict("os.environ", env, clear=False):
                    _run_cli_json(["--config", str(config_path), "disable", "--all"])


if __name__ == "__main__":
    unittest.main()
