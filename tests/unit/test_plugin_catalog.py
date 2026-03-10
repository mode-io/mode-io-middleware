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

from modeio_middleware.plugin_catalog import PluginCatalogEntry  # noqa: E402
from modeio_middleware.plugin_catalog_discovery import build_plugin_catalog  # noqa: E402
from modeio_middleware.plugin_inventory import build_plugin_inventory_response  # noqa: E402


def _write_manifest(path: Path, *, name: str, description: str = "Discovered plugin"):
    path.write_text(
        json.dumps(
            {
                "name": name,
                "version": "0.1.0",
                "protocol_version": "1.0",
                "transport": "stdio-jsonrpc",
                "hooks": ["pre.request", "post.response"],
                "capabilities": {
                    "can_patch": True,
                    "can_block": False,
                    "needs_network": False,
                    "needs_raw_body": False,
                },
                "metadata": {
                    "display_name": "Policy Plugin",
                    "description": description,
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )


def _write_host(path: Path):
    path.write_text(
        json.dumps(
            {
                "version": "1",
                "runtime": "stdio_jsonrpc",
                "command": ["python3", "./plugin.py"],
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


class TestPluginCatalog(unittest.TestCase):
    def test_catalog_compat_exports_still_resolve(self):
        self.assertIsNotNone(PluginCatalogEntry)

    def test_build_plugin_catalog_discovers_default_sibling_plugins_dir(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "middleware.json"
            plugin_dir = root / "plugins" / "policy"
            plugin_dir.mkdir(parents=True, exist_ok=True)
            _write_manifest(plugin_dir / "manifest.json", name="acme/policy")
            _write_host(plugin_dir / "modeio.host.json")
            (plugin_dir / "plugin.py").write_text("print('ok')\n", encoding="utf-8")

            payload = {
                "profiles": {
                    "dev": {"on_plugin_error": "warn", "plugins": ["acme/policy"]}
                },
                "plugins": {},
                "services": {},
            }
            catalog = build_plugin_catalog(payload, config_file_path=config_path)

            self.assertIn("acme/policy", catalog.entries)
            self.assertIn("acme/policy", catalog.runtime_plugins)
            self.assertEqual(catalog.entries["acme/policy"].source_kind, "discovered")

    def test_explicit_plugin_entry_shadows_discovered_plugin(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "middleware.json"
            plugin_dir = root / "plugins" / "policy"
            plugin_dir.mkdir(parents=True, exist_ok=True)
            _write_manifest(plugin_dir / "manifest.json", name="acme/policy")
            _write_host(plugin_dir / "modeio.host.json")
            (plugin_dir / "plugin.py").write_text("print('ok')\n", encoding="utf-8")

            payload = {
                "profiles": {"dev": {"on_plugin_error": "warn", "plugins": []}},
                "plugins": {
                    "acme/policy": {
                        "enabled": True,
                        "module": "modeio_middleware.plugins.redact",
                    }
                },
                "services": {},
            }
            catalog = build_plugin_catalog(payload, config_file_path=config_path)

            self.assertEqual(catalog.entries["acme/policy"].source_kind, "config")
            self.assertIn("shadowed", catalog.warnings[0])

    def test_inventory_reports_profile_state_stats_and_missing_plugins(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "middleware.json"
            plugin_dir = root / "plugins" / "policy"
            plugin_dir.mkdir(parents=True, exist_ok=True)
            _write_manifest(
                plugin_dir / "manifest.json",
                name="acme/policy",
                description="Applies a safe observe-only rewrite policy.",
            )
            _write_host(plugin_dir / "modeio.host.json")
            (plugin_dir / "plugin.py").write_text("print('ok')\n", encoding="utf-8")
            (plugin_dir / "README.md").write_text(
                "# Acme Policy\n\nFallback text.\n", encoding="utf-8"
            )

            payload = {
                "profiles": {
                    "dev": {
                        "on_plugin_error": "warn",
                        "plugins": ["acme/policy", "missing/plugin"],
                        "plugin_overrides": {
                            "acme/policy": {
                                "mode": "assist",
                                "capabilities_grant": {
                                    "can_patch": True,
                                    "can_block": False,
                                },
                            }
                        },
                    }
                },
                "plugins": {},
                "services": {},
            }

            inventory = build_plugin_inventory_response(
                payload,
                config_file_path=config_path,
                preset_registry={},
                generation=3,
                default_profile="dev",
                config_writable=True,
                stats_snapshot={
                    "byPlugin": {
                        "acme/policy": {
                            "calls": 4,
                            "errors": 1,
                            "actions": {"warn": 3, "modify": 1},
                        }
                    }
                },
            )

            self.assertEqual(inventory["runtime"]["generation"], 3)
            self.assertEqual(
                inventory["profiles"][0]["pluginOrder"],
                ["acme/policy", "missing/plugin"],
            )

            discovered = next(
                item for item in inventory["plugins"] if item["name"] == "acme/policy"
            )
            self.assertEqual(
                discovered["description"], "Applies a safe observe-only rewrite policy."
            )
            self.assertEqual(discovered["profiles"]["dev"]["position"], 0)
            self.assertTrue(discovered["profiles"]["dev"]["enabled"])
            self.assertEqual(discovered["profiles"]["dev"]["effectiveMode"], "assist")
            self.assertEqual(discovered["stats"]["calls"], 4)

            missing = next(
                item
                for item in inventory["plugins"]
                if item["name"] == "missing/plugin"
            )
            self.assertEqual(missing["sourceKind"], "missing")
            self.assertEqual(missing["validation"]["status"], "error")

    def test_invalid_discovered_plugin_is_reported_as_warning(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "middleware.json"
            broken_dir = root / "plugins" / "broken"
            broken_dir.mkdir(parents=True, exist_ok=True)
            _write_manifest(broken_dir / "manifest.json", name="broken/plugin")

            payload = {
                "profiles": {"dev": {"on_plugin_error": "warn", "plugins": []}},
                "plugins": {},
                "services": {},
            }
            catalog = build_plugin_catalog(payload, config_file_path=config_path)
            self.assertNotIn("broken/plugin", catalog.runtime_plugins)
            self.assertTrue(
                any("modeio.host.json" in warning for warning in catalog.warnings)
            )


if __name__ == "__main__":
    unittest.main()
