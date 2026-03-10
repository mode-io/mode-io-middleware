#!/usr/bin/env python3

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = REPO_ROOT
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from modeio_middleware.core.errors import MiddlewareError  # noqa: E402
from modeio_middleware.runtime_config_store import (  # noqa: E402
    build_gateway_runtime_config,
)
from modeio_middleware.runtime_control import GatewayController  # noqa: E402


class _FakeNextEngine:
    def __init__(self):
        self.config = SimpleNamespace(default_profile="dev", preset_registry={})
        self.services = SimpleNamespace(request_journal=None)
        self.shutdown_calls = 0

    def shutdown(self):
        self.shutdown_calls += 1


def _write_config(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "version": "0.2",
                "profiles": {
                    "dev": {
                        "on_plugin_error": "warn",
                        "plugins": [],
                    }
                },
                "plugins": {},
                "services": {},
            }
        )
        + "\n",
        encoding="utf-8",
    )


def _build_controller(config_path: Path) -> GatewayController:
    runtime_config = build_gateway_runtime_config(
        config_path,
        upstream_chat_completions_url="https://upstream.example/v1/chat/completions",
        upstream_responses_url="https://upstream.example/v1/responses",
        upstream_timeout_seconds=5,
        upstream_api_key_env="MODEIO_TEST_UPSTREAM_KEY",
        default_profile="dev",
    )
    return GatewayController(runtime_config)


class TestRuntimeControl(unittest.TestCase):
    def test_update_profile_plugins_engine_build_failure_keeps_generation_and_file(self):
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "middleware.json"
            _write_config(config_path)
            original_text = config_path.read_text(encoding="utf-8")
            controller = _build_controller(config_path)
            original_generation = controller.current_generation()
            try:
                with patch(
                    "modeio_middleware.runtime_control.MiddlewareEngine",
                    side_effect=RuntimeError("boom"),
                ):
                    with self.assertRaisesRegex(RuntimeError, "boom"):
                        controller.update_profile_plugins(
                            "dev",
                            plugin_order=[],
                            plugin_overrides={},
                            expected_generation=original_generation,
                        )
            finally:
                controller.shutdown()

            self.assertEqual(controller.current_generation(), original_generation)
            self.assertEqual(
                config_path.read_text(encoding="utf-8"),
                original_text,
            )

    def test_update_profile_plugins_write_failure_shuts_down_new_engine_and_keeps_state(self):
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "middleware.json"
            _write_config(config_path)
            original_text = config_path.read_text(encoding="utf-8")
            controller = _build_controller(config_path)
            original_generation = controller.current_generation()
            fake_next_engine = _FakeNextEngine()
            try:
                with patch(
                    "modeio_middleware.runtime_control.MiddlewareEngine",
                    return_value=fake_next_engine,
                ):
                    with patch(
                        "modeio_middleware.runtime_control.write_runtime_config_payload",
                        side_effect=MiddlewareError(
                            500,
                            "MODEIO_CONFIG_ERROR",
                            "disk write failed",
                            retryable=False,
                        ),
                    ):
                        with self.assertRaises(MiddlewareError) as error_ctx:
                            controller.update_profile_plugins(
                                "dev",
                                plugin_order=[],
                                plugin_overrides={},
                                expected_generation=original_generation,
                            )
            finally:
                controller.shutdown()

            self.assertEqual(error_ctx.exception.code, "MODEIO_CONFIG_ERROR")
            self.assertEqual(controller.current_generation(), original_generation)
            self.assertEqual(
                config_path.read_text(encoding="utf-8"),
                original_text,
            )
            self.assertEqual(fake_next_engine.shutdown_calls, 1)


if __name__ == "__main__":
    unittest.main()
