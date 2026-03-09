#!/usr/bin/env python3

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = REPO_ROOT
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from modeio_middleware.dev_runtime import (  # noqa: E402
    apply_dev_runtime_env,
    dashboard_bundle_exists,
    dashboard_bundle_is_stale,
    reset_dev_runtime,
    resolve_dev_runtime_paths,
    should_use_dev_runtime,
)


class TestDevRuntime(unittest.TestCase):
    def test_resolve_dev_runtime_paths_defaults_to_repo_local_root(self):
        paths = resolve_dev_runtime_paths(REPO_ROOT)
        self.assertEqual(paths.runtime_home, REPO_ROOT / ".modeio-dev")
        self.assertEqual(paths.config_path, REPO_ROOT / ".modeio-dev" / "middleware.json")
        self.assertEqual(paths.plugins_dir, REPO_ROOT / ".modeio-dev" / "plugins")

    def test_should_use_dev_runtime_skips_when_explicit_runtime_is_present(self):
        self.assertFalse(should_use_dev_runtime(["--config", "/tmp/custom.json"], {}))
        self.assertFalse(should_use_dev_runtime([], {"MODEIO_HOME": "/tmp/runtime-home"}))
        self.assertFalse(
            should_use_dev_runtime([], {"MODEIO_MIDDLEWARE_CONFIG": "/tmp/custom.json"})
        )
        self.assertTrue(should_use_dev_runtime([], {}))

    def test_apply_dev_runtime_env_sets_modeio_home_only_when_needed(self):
        runtime_home = Path("/tmp/modeio-dev")
        env = apply_dev_runtime_env(runtime_home=runtime_home, env={"PATH": "/usr/bin"})
        self.assertEqual(env["MODEIO_HOME"], str(runtime_home))

        unchanged = apply_dev_runtime_env(
            runtime_home=runtime_home,
            env={"MODEIO_MIDDLEWARE_CONFIG": "/tmp/custom.json"},
        )
        self.assertNotIn("MODEIO_HOME", unchanged)

    def test_reset_dev_runtime_deletes_tree(self):
        with TemporaryDirectory() as temp_dir:
            runtime_home = Path(temp_dir) / ".modeio-dev"
            (runtime_home / "plugins").mkdir(parents=True)
            (runtime_home / "plugins" / "example.txt").write_text("x", encoding="utf-8")
            reset_dev_runtime(runtime_home)
            self.assertFalse(runtime_home.exists())

    def test_dashboard_bundle_status_helpers(self):
        with TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            source_dir = repo_root / "dashboard" / "src"
            source_dir.mkdir(parents=True)
            (source_dir / "App.tsx").write_text("export const app = 1;\n", encoding="utf-8")

            bundle_assets = repo_root / "modeio_middleware" / "resources" / "dashboard" / "assets"
            bundle_assets.mkdir(parents=True)
            (bundle_assets.parent / "index.html").write_text("<html></html>\n", encoding="utf-8")
            (bundle_assets / "dashboard.js").write_text("console.log('x');\n", encoding="utf-8")
            (bundle_assets / "dashboard.css").write_text("body{}\n", encoding="utf-8")

            paths = resolve_dev_runtime_paths(repo_root)
            self.assertTrue(dashboard_bundle_exists(paths))
            self.assertFalse(dashboard_bundle_is_stale(paths))

            os.utime(source_dir / "App.tsx", None)
            self.assertTrue(dashboard_bundle_is_stale(paths))

    def test_dev_gateway_status_uses_repo_local_runtime(self):
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "dev_gateway.py"), "status"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        payload = json.loads(result.stdout)
        self.assertEqual(payload["mode"], "repo-local-dev")
        self.assertEqual(payload["runtimeHome"], str(REPO_ROOT / ".modeio-dev"))
        self.assertEqual(payload["tracePersistence"], "ephemeral (in-memory request journal)")

    def test_dev_gateway_reset_deletes_custom_runtime_home(self):
        with TemporaryDirectory() as temp_dir:
            runtime_home = Path(temp_dir) / ".modeio-dev"
            runtime_home.mkdir(parents=True)
            (runtime_home / "middleware.json").write_text("{}", encoding="utf-8")

            subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "dev_gateway.py"),
                    "reset",
                    "--runtime-home",
                    str(runtime_home),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertFalse(runtime_home.exists())


if __name__ == "__main__":
    unittest.main()
