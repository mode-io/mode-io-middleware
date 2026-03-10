#!/usr/bin/env python3

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
TESTS_DIR = REPO_ROOT / "tests"

sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, str(TESTS_DIR))

from helpers.gateway_harness import (  # noqa: E402
    completion_payload,
    http_get_json,
    post_json,
    put_json,
    start_gateway_pair,
)


PLUGIN_SCRIPT = """#!/usr/bin/env python3
from __future__ import annotations

import json
import sys


def reply(request_id, result=None, error=None):
    payload = {"jsonrpc": "2.0", "id": request_id}
    if error is not None:
        payload["error"] = error
    else:
        payload["result"] = result or {}
    sys.stdout.write(json.dumps(payload) + "\\n")
    sys.stdout.flush()


def main():
    for line in sys.stdin:
        if not line.strip():
            continue
        request = json.loads(line)
        method = request.get("method")
        request_id = request.get("id")
        params = request.get("params") or {}

        if method == "modeio.initialize":
            reply(request_id, {"protocol_version": "1.0", "name": "catalog/rewrite"})
            continue

        if method == "modeio.invoke":
            hook = params.get("hook")
            if hook == "pre.request":
                reply(
                    request_id,
                    {
                        "decision": {
                            "action": "patch",
                            "patch_target": "request_body",
                            "patches": [
                                {
                                    "op": "replace",
                                    "path": "/messages/0/content",
                                    "value": "rewritten by discovered plugin",
                                }
                            ],
                            "findings": [],
                        }
                    },
                )
                continue
            reply(request_id, {"decision": {"action": "pass", "findings": []}})
            continue

        if method == "modeio.shutdown":
            reply(request_id, {"ok": True})
            return 0

        reply(request_id, error={"code": -32601, "message": f"unknown method: {method}"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
"""


def _write_runtime_home(root: Path) -> Path:
    config_path = root / "middleware.json"
    plugins_dir = root / "plugins" / "rewrite"
    plugins_dir.mkdir(parents=True, exist_ok=True)
    (plugins_dir / "plugin.py").write_text(PLUGIN_SCRIPT, encoding="utf-8")
    (plugins_dir / "README.md").write_text(
        "# Rewrite Plugin\n\nRewrites the first user message before upstream dispatch.\n",
        encoding="utf-8",
    )
    (plugins_dir / "manifest.json").write_text(
        json.dumps(
            {
                "name": "catalog/rewrite",
                "version": "0.1.0",
                "protocol_version": "1.0",
                "transport": "stdio-jsonrpc",
                "hooks": ["pre.request"],
                "capabilities": {
                    "can_patch": True,
                    "can_block": False,
                    "needs_network": False,
                    "needs_raw_body": False,
                },
                "metadata": {
                    "display_name": "Rewrite Plugin",
                    "description": "Rewrites the first user message before upstream dispatch.",
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (plugins_dir / "modeio.host.json").write_text(
        json.dumps(
            {
                "version": "1",
                "runtime": "stdio_jsonrpc",
                "command": [sys.executable, "./plugin.py"],
                "defaults": {
                    "mode": "observe",
                    "capabilities_grant": {"can_patch": False, "can_block": False},
                    "pool_size": 1,
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    config_path.write_text(
        json.dumps(
            {
                "version": "0.2",
                "profiles": {
                    "dev": {"on_plugin_error": "warn", "plugins": []},
                    "prod": {"on_plugin_error": "fail_safe", "plugins": []},
                },
                "plugins": {},
                "services": {
                    "request_journal": {
                        "enabled": True,
                        "max_records": 200,
                        "capture_bodies": True,
                        "max_body_chars": 4000,
                        "sample_diff_paths": 20,
                        "live_queue_size": 20,
                    }
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return config_path


class TestPluginManagementApi(unittest.TestCase):
    def test_plugins_endpoint_lists_discovered_plugins_and_enabling_persists_and_reloads(
        self,
    ):
        with TemporaryDirectory() as temp_dir:
            config_path = _write_runtime_home(Path(temp_dir))
            upstream, gateway_stub = start_gateway_pair(
                lambda _path, payload: completion_payload(
                    payload["messages"][0]["content"]
                ),
                config_path=config_path,
            )
            try:
                status, _headers, inventory = http_get_json(
                    gateway_stub.base_url,
                    "/modeio/admin/v1/plugins",
                )
                self.assertEqual(status, 200)
                self.assertTrue(inventory["runtime"]["configWritable"])
                rewrite = next(
                    item
                    for item in inventory["plugins"]
                    if item["name"] == "catalog/rewrite"
                )
                self.assertEqual(
                    rewrite["description"],
                    "Rewrites the first user message before upstream dispatch.",
                )
                self.assertFalse(rewrite["profiles"]["dev"]["enabled"])

                status, _headers, update = put_json(
                    gateway_stub.base_url,
                    "/modeio/admin/v1/profiles/dev/plugins",
                    {
                        "expectedGeneration": inventory["runtime"]["generation"],
                        "pluginOrder": ["catalog/rewrite"],
                        "pluginOverrides": {
                            "catalog/rewrite": {
                                "mode": "assist",
                                "capabilities_grant": {
                                    "can_patch": True,
                                    "can_block": False,
                                },
                            }
                        },
                    },
                )
                self.assertEqual(status, 200)
                self.assertTrue(update["reloaded"])
                self.assertTrue(Path(update["backupPath"]).exists())

                status, _headers, payload = post_json(
                    gateway_stub.base_url,
                    "/v1/chat/completions",
                    {
                        "model": "gpt-test",
                        "messages": [{"role": "user", "content": "hello plugin"}],
                    },
                )
                self.assertEqual(status, 200)
                self.assertEqual(
                    payload["choices"][0]["message"]["content"],
                    "rewritten by discovered plugin",
                )
                self.assertEqual(
                    upstream.requests[0]["body"]["messages"][0]["content"],
                    "rewritten by discovered plugin",
                )

                config_payload = json.loads(config_path.read_text(encoding="utf-8"))
                self.assertEqual(
                    config_payload["profiles"]["dev"]["plugins"], ["catalog/rewrite"]
                )
                self.assertEqual(
                    config_payload["profiles"]["dev"]["plugin_overrides"][
                        "catalog/rewrite"
                    ]["mode"],
                    "assist",
                )

                status, _headers, refreshed = http_get_json(
                    gateway_stub.base_url,
                    "/modeio/admin/v1/plugins",
                )
                self.assertEqual(status, 200)
                rewrite = next(
                    item
                    for item in refreshed["plugins"]
                    if item["name"] == "catalog/rewrite"
                )
                self.assertTrue(rewrite["profiles"]["dev"]["enabled"])
                self.assertGreaterEqual(rewrite["stats"]["calls"], 1)
                self.assertEqual(
                    refreshed["runtime"]["generation"], update["generation"]
                )
            finally:
                gateway_stub.stop()
                upstream.stop()

    def test_profile_update_rejects_unknown_plugin_and_stale_generation(self):
        with TemporaryDirectory() as temp_dir:
            config_path = _write_runtime_home(Path(temp_dir))
            upstream, gateway_stub = start_gateway_pair(
                lambda _path, payload: completion_payload(
                    payload["messages"][0]["content"]
                ),
                config_path=config_path,
            )
            try:
                status, _headers, inventory = http_get_json(
                    gateway_stub.base_url, "/modeio/admin/v1/plugins"
                )
                self.assertEqual(status, 200)
                generation = inventory["runtime"]["generation"]

                status, _headers, bad = put_json(
                    gateway_stub.base_url,
                    "/modeio/admin/v1/profiles/dev/plugins",
                    {
                        "expectedGeneration": generation,
                        "pluginOrder": ["missing/plugin"],
                        "pluginOverrides": {},
                    },
                )
                self.assertEqual(status, 400)
                self.assertEqual(bad["error"]["code"], "MODEIO_VALIDATION_ERROR")

                status, _headers, update = put_json(
                    gateway_stub.base_url,
                    "/modeio/admin/v1/profiles/dev/plugins",
                    {
                        "expectedGeneration": generation,
                        "pluginOrder": ["catalog/rewrite"],
                        "pluginOverrides": {},
                    },
                )
                self.assertEqual(status, 200)

                status, _headers, stale = put_json(
                    gateway_stub.base_url,
                    "/modeio/admin/v1/profiles/dev/plugins",
                    {
                        "expectedGeneration": generation,
                        "pluginOrder": [],
                        "pluginOverrides": {},
                    },
                )
                self.assertEqual(status, 409)
                self.assertEqual(stale["error"]["code"], "MODEIO_GENERATION_CONFLICT")

                status, _headers, missing = http_get_json(
                    gateway_stub.base_url, "/modeio/unknown-admin-route"
                )
                self.assertEqual(status, 404)
                self.assertEqual(missing["error"]["code"], "MODEIO_ROUTE_NOT_FOUND")
                self.assertEqual(update["generation"], generation + 1)
            finally:
                gateway_stub.stop()
                upstream.stop()

    def test_monitoring_history_survives_profile_reload(self):
        with TemporaryDirectory() as temp_dir:
            config_path = _write_runtime_home(Path(temp_dir))
            upstream, gateway_stub = start_gateway_pair(
                lambda _path, payload: completion_payload(
                    payload["messages"][0]["content"]
                ),
                config_path=config_path,
            )
            try:
                status, _headers, inventory = http_get_json(
                    gateway_stub.base_url,
                    "/modeio/admin/v1/plugins",
                )
                self.assertEqual(status, 200)

                status, _headers, first = post_json(
                    gateway_stub.base_url,
                    "/v1/chat/completions",
                    {
                        "model": "gpt-test",
                        "messages": [{"role": "user", "content": "before reload"}],
                    },
                )
                self.assertEqual(status, 200)

                status, _headers, events_before = http_get_json(
                    gateway_stub.base_url,
                    "/modeio/api/v1/events",
                )
                self.assertEqual(status, 200)
                self.assertEqual(len(events_before["items"]), 1)
                first_request_id = events_before["items"][0]["requestId"]

                status, _headers, update = put_json(
                    gateway_stub.base_url,
                    "/modeio/admin/v1/profiles/dev/plugins",
                    {
                        "expectedGeneration": inventory["runtime"]["generation"],
                        "pluginOrder": ["catalog/rewrite"],
                        "pluginOverrides": {},
                    },
                )
                self.assertEqual(status, 200)
                self.assertTrue(update["reloaded"])

                status, _headers, second = post_json(
                    gateway_stub.base_url,
                    "/v1/chat/completions",
                    {
                        "model": "gpt-test",
                        "messages": [{"role": "user", "content": "after reload"}],
                    },
                )
                self.assertEqual(status, 200)

                status, _headers, events_after = http_get_json(
                    gateway_stub.base_url,
                    "/modeio/api/v1/events",
                )
                self.assertEqual(status, 200)
                self.assertEqual(len(events_after["items"]), 2)
                self.assertEqual(events_after["items"][-1]["requestId"], first_request_id)

                status, _headers, stats = http_get_json(
                    gateway_stub.base_url,
                    "/modeio/api/v1/stats",
                )
                self.assertEqual(status, 200)
                self.assertEqual(stats["completedRecords"], 2)
            finally:
                gateway_stub.stop()
                upstream.stop()


if __name__ == "__main__":
    unittest.main()
