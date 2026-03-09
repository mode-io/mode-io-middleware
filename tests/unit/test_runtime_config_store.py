#!/usr/bin/env python3

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = REPO_ROOT
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from modeio_middleware.runtime_config_store import (  # noqa: E402
    build_gateway_runtime_config,
    write_runtime_config_payload,
)


class TestRuntimeConfigStore(unittest.TestCase):
    def test_build_gateway_runtime_config_merges_discovered_plugins(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "middleware.json"
            plugins_dir = root / "plugins" / "sample"
            plugins_dir.mkdir(parents=True, exist_ok=True)
            (plugins_dir / "manifest.json").write_text(
                json.dumps(
                    {
                        "name": "sample/plugin",
                        "version": "0.1.0",
                        "protocol_version": "1.0",
                        "transport": "stdio-jsonrpc",
                        "hooks": ["pre.request"],
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
                        "command": ["python3", "./plugin.py"],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (plugins_dir / "plugin.py").write_text("print('ok')\n", encoding="utf-8")
            config_path.write_text(
                json.dumps(
                    {
                        "profiles": {
                            "dev": {
                                "on_plugin_error": "warn",
                                "plugins": ["sample/plugin"],
                            }
                        },
                        "plugins": {},
                        "services": {},
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            runtime_config = build_gateway_runtime_config(
                config_path,
                upstream_chat_completions_url="https://example.com/v1/chat/completions",
                upstream_responses_url="https://example.com/v1/responses",
                upstream_timeout_seconds=5,
                upstream_api_key_env="MODEIO_GATEWAY_UPSTREAM_API_KEY",
                default_profile="dev",
            )
            self.assertIn("sample/plugin", runtime_config.plugins)
            self.assertEqual(runtime_config.config_path, str(config_path))

    def test_write_runtime_config_payload_creates_backup(self):
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "middleware.json"
            config_path.write_text(
                '{"profiles":{},"plugins":{},"services":{}}\n', encoding="utf-8"
            )
            backup_path = write_runtime_config_payload(
                config_path,
                {
                    "profiles": {"dev": {"on_plugin_error": "warn", "plugins": []}},
                    "plugins": {},
                    "services": {},
                },
            )
            self.assertTrue(Path(backup_path).exists())
            payload = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertIn("dev", payload["profiles"])


if __name__ == "__main__":
    unittest.main()
