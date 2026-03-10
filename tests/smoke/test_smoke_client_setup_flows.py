#!/usr/bin/env python3

import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT
HELPERS_DIR = REPO_ROOT / "tests" / "helpers"
sys.path.insert(0, str(PACKAGE_DIR))
sys.path.insert(0, str(HELPERS_DIR))

from modeio_middleware.cli import setup as setup_gateway  # noqa: E402
from gateway_harness import completion_payload, post_json, start_gateway_pair  # noqa: E402


def _run_setup_json(args):
    out = io.StringIO()
    with redirect_stdout(out):
        code = setup_gateway.main(args)
    return code, json.loads(out.getvalue())


class TestSmokeClientSetupFlows(unittest.TestCase):
    def test_openclaw_setup_apply_and_uninstall(self):
        upstream = None
        gateway = None
        try:
            upstream, gateway = start_gateway_pair(
                lambda _path, payload: completion_payload(
                    payload.get("messages", [{}])[0].get("content", "openclaw-ok")
                )
            )

            with TemporaryDirectory() as temp_dir:
                openclaw_config = Path(temp_dir) / "openclaw.json"
                models_cache = (
                    Path(temp_dir) / "agents" / "main" / "agent" / "models.json"
                )
                gateway_base_url = f"{gateway.base_url}/v1"

                apply_code, apply_payload = _run_setup_json(
                    [
                        "--json",
                        "--apply-openclaw",
                        "--create-openclaw-config",
                        "--openclaw-config-path",
                        str(openclaw_config),
                        "--openclaw-models-cache-path",
                        str(models_cache),
                        "--gateway-base-url",
                        gateway_base_url,
                    ]
                )
                self.assertEqual(apply_code, 0)
                self.assertTrue(apply_payload["success"])

                config_payload = json.loads(openclaw_config.read_text(encoding="utf-8"))
                provider = config_payload["models"]["providers"]["modeio-middleware"]
                self.assertEqual(
                    provider["baseUrl"],
                    f"{gateway.base_url}/clients/openclaw/v1",
                )
                self.assertEqual(
                    config_payload["agents"]["defaults"]["model"]["primary"],
                    "modeio-middleware/middleware-default",
                )

                models_payload = json.loads(models_cache.read_text(encoding="utf-8"))
                self.assertIn(
                    "modeio-middleware", models_payload["models"]["providers"]
                )

                uninstall_code, uninstall_payload = _run_setup_json(
                    [
                        "--json",
                        "--apply-openclaw",
                        "--uninstall",
                        "--openclaw-config-path",
                        str(openclaw_config),
                        "--openclaw-models-cache-path",
                        str(models_cache),
                        "--gateway-base-url",
                        gateway_base_url,
                    ]
                )
                self.assertEqual(uninstall_code, 0)
                self.assertTrue(uninstall_payload["success"])

                config_after = json.loads(openclaw_config.read_text(encoding="utf-8"))
                self.assertNotIn(
                    "modeio-middleware",
                    config_after.get("models", {}).get("providers", {}),
                )
                models_after = json.loads(models_cache.read_text(encoding="utf-8"))
                self.assertNotIn(
                    "modeio-middleware",
                    models_after.get("models", {}).get("providers", {}),
                )
        finally:
            if gateway is not None:
                gateway.stop()
            if upstream is not None:
                upstream.stop()

    def test_claude_setup_apply_route_and_uninstall(self):
        upstream = None
        gateway = None
        try:
            upstream, gateway = start_gateway_pair(
                lambda _path, payload: completion_payload(
                    payload.get("messages", [{}])[0].get("content", "claude-ok")
                )
            )

            with TemporaryDirectory() as temp_dir:
                claude_settings = Path(temp_dir) / "settings.json"
                gateway_base_url = f"{gateway.base_url}/v1"

                apply_code, apply_payload = _run_setup_json(
                    [
                        "--json",
                        "--apply-claude",
                        "--create-claude-settings",
                        "--claude-settings-path",
                        str(claude_settings),
                        "--gateway-base-url",
                        gateway_base_url,
                    ]
                )
                self.assertEqual(apply_code, 0)
                self.assertTrue(apply_payload["success"])
                self.assertEqual(
                    apply_payload["claude"]["hookUrl"],
                    f"{gateway.base_url}/connectors/claude/hooks",
                )

                settings_payload = json.loads(
                    claude_settings.read_text(encoding="utf-8")
                )
                self.assertIn("UserPromptSubmit", settings_payload["hooks"])
                self.assertIn("Stop", settings_payload["hooks"])

                status, headers, payload = post_json(
                    gateway.base_url,
                    "/connectors/claude/hooks",
                    {
                        "hook_event_name": "UserPromptSubmit",
                        "prompt": "claude smoke",
                        "modeio": {"profile": "dev"},
                    },
                )
                self.assertEqual(status, 200)
                self.assertEqual(payload, {})
                self.assertIn(
                    "x-modeio-request-id", {k.lower(): v for k, v in headers.items()}
                )
                self.assertEqual(headers["x-modeio-upstream-called"], "false")

                uninstall_code, uninstall_payload = _run_setup_json(
                    [
                        "--json",
                        "--apply-claude",
                        "--uninstall",
                        "--claude-settings-path",
                        str(claude_settings),
                        "--gateway-base-url",
                        gateway_base_url,
                    ]
                )
                self.assertEqual(uninstall_code, 0)
                self.assertTrue(uninstall_payload["success"])

                settings_after = json.loads(claude_settings.read_text(encoding="utf-8"))
                self.assertNotIn("hooks", settings_after)
        finally:
            if gateway is not None:
                gateway.stop()
            if upstream is not None:
                upstream.stop()


if __name__ == "__main__":
    unittest.main()
