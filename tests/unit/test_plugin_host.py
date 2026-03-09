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

from modeio_middleware.core.errors import MiddlewareError  # noqa: E402
from modeio_middleware.plugin_host import (  # noqa: E402
    load_plugin_host_config,
    resolve_plugin_host_command,
)


class TestPluginHost(unittest.TestCase):
    def test_load_plugin_host_config_parses_defaults(self):
        with TemporaryDirectory() as temp_dir:
            host_path = Path(temp_dir) / "modeio.host.json"
            host_path.write_text(
                json.dumps(
                    {
                        "version": "1",
                        "runtime": "stdio_jsonrpc",
                        "command": ["python3", "./plugin.py"],
                        "defaults": {
                            "mode": "assist",
                            "capabilities_grant": {
                                "can_patch": True,
                                "can_block": False,
                            },
                            "pool_size": 2,
                            "timeout_ms": {"pre.request": 250},
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            host = load_plugin_host_config(host_path)
            self.assertEqual(host.runtime, "stdio_jsonrpc")
            self.assertEqual(host.defaults.mode, "assist")
            self.assertEqual(host.defaults.pool_size, 2)
            self.assertTrue(host.defaults.capabilities_grant["can_patch"])

    def test_load_plugin_host_config_rejects_invalid_pool_size(self):
        with TemporaryDirectory() as temp_dir:
            host_path = Path(temp_dir) / "modeio.host.json"
            host_path.write_text(
                json.dumps(
                    {
                        "version": "1",
                        "runtime": "stdio_jsonrpc",
                        "command": ["python3", "./plugin.py"],
                        "defaults": {"pool_size": 0},
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(MiddlewareError):
                load_plugin_host_config(host_path)

    def test_resolve_plugin_host_command_expands_relative_files(self):
        with TemporaryDirectory() as temp_dir:
            plugin_dir = Path(temp_dir)
            (plugin_dir / "plugin.py").write_text("print('ok')\n", encoding="utf-8")
            host_path = plugin_dir / "modeio.host.json"
            host_path.write_text(
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
            host = load_plugin_host_config(host_path)
            command = resolve_plugin_host_command(host, plugin_dir=plugin_dir)
            self.assertEqual(command[0], "python3")
            self.assertTrue(Path(command[1]).is_absolute())
            self.assertTrue(Path(command[1]).exists())


if __name__ == "__main__":
    unittest.main()
