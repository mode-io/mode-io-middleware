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

from modeio_middleware.runtime_home import (  # noqa: E402
    build_user_runtime_config_payload,
    default_modeio_config_path,
    default_modeio_home_path,
    ensure_user_runtime_home,
)


class TestRuntimeHome(unittest.TestCase):
    def test_default_modeio_home_path_uses_xdg_or_dot_config(self):
        path = default_modeio_home_path(
            os_name="linux",
            env={"XDG_CONFIG_HOME": "/tmp/xdg-config"},
            home=Path("/home/test"),
        )
        self.assertEqual(path, Path("/tmp/xdg-config") / "modeio")

        fallback = default_modeio_home_path(
            os_name="darwin",
            env={},
            home=Path("/Users/test"),
        )
        self.assertEqual(fallback, Path("/Users/test/.config/modeio"))

    def test_default_modeio_config_path_honors_explicit_env_override(self):
        path = default_modeio_config_path(
            os_name="linux",
            env={"MODEIO_MIDDLEWARE_CONFIG": "/tmp/custom-modeio.json"},
            home=Path("/home/test"),
        )
        self.assertEqual(path, Path("/tmp/custom-modeio.json"))

    def test_build_user_runtime_config_payload_enables_discovery(self):
        payload = build_user_runtime_config_payload()
        self.assertEqual(payload["plugins"], {})
        self.assertEqual(payload["plugin_discovery"]["roots"], ["./plugins"])
        self.assertTrue(payload["plugin_discovery"]["enabled"])
        self.assertIn("request_journal", payload["services"])

    def test_ensure_user_runtime_home_creates_config_and_example_plugin(self):
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "modeio" / "middleware.json"
            created = ensure_user_runtime_home(config_path)
            self.assertTrue(created)
            self.assertTrue(config_path.exists())

            payload = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["plugin_discovery"]["roots"], ["./plugins"])
            self.assertEqual(payload["profiles"]["dev"]["plugins"], [])
            self.assertTrue(
                (config_path.parent / "plugins" / "example" / "manifest.json").exists()
            )
            self.assertTrue(
                (
                    config_path.parent / "plugins" / "example" / "modeio.host.json"
                ).exists()
            )

            created_again = ensure_user_runtime_home(config_path)
            self.assertFalse(created_again)


if __name__ == "__main__":
    unittest.main()
