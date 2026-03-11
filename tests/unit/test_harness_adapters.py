#!/usr/bin/env python3

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from tests.helpers.openclaw_builder import (  # noqa: E402
    build_openclaw_config,
    build_openclaw_models_cache,
    build_openclaw_provider,
)

from modeio_middleware.cli.harness_adapters import (  # noqa: E402
    HarnessAdapterRegistry,
    codex_gateway_base_url,
)


class TestHarnessAdapters(unittest.TestCase):
    def test_registry_exposes_expected_attachment_kinds(self):
        registry = HarnessAdapterRegistry()
        self.assertEqual(registry.adapter_for("codex").attachment_kind, "env_session")
        self.assertEqual(registry.adapter_for("opencode").attachment_kind, "config_patch")
        self.assertEqual(registry.adapter_for("openclaw").attachment_kind, "config_patch")
        self.assertEqual(registry.adapter_for("claude").attachment_kind, "hook_patch")

    def test_codex_attachment_detects_current_env_target(self):
        adapter = HarnessAdapterRegistry().adapter_for("codex")
        target = codex_gateway_base_url("http://127.0.0.1:8787/v1")
        attachment = adapter.inspect_attachment(
            gateway_base_url="http://127.0.0.1:8787/v1",
            env={"OPENAI_BASE_URL": target},
            shell="bash",
        )
        self.assertTrue(attachment.attached)
        self.assertEqual(attachment.attachment_kind, "env_session")
        self.assertEqual(attachment.target, target)
        self.assertIn("setCommand", attachment.details)
        self.assertIn("unsetCommand", attachment.details)

    def test_opencode_attachment_reports_preserve_provider_target(self):
        adapter = HarnessAdapterRegistry().adapter_for("opencode")
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "opencode.json"
            config_path.write_text(
                json.dumps(
                    {
                        "model": "opencode/gpt-5.4",
                        "provider": {
                            "opencode": {
                                "options": {
                                    "baseURL": "http://127.0.0.1:8787/clients/opencode/opencode/v1",
                                }
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            route_metadata_path = config_path.with_name("opencode.json.modeio-route.json")
            route_metadata_path.write_text(
                json.dumps(
                    {
                        "providers": {
                            "opencode": {
                                "providerId": "opencode",
                                "originalBaseUrl": "https://opencode.ai/zen/v1",
                                "hadExplicitBaseUrl": True,
                                "routeMode": "preserve_provider",
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            auth_store = Path(temp_dir) / ".local" / "share" / "opencode" / "auth.json"
            auth_store.parent.mkdir(parents=True, exist_ok=True)
            auth_store.write_text(
                json.dumps({"opencode": {"type": "api", "key": "sk-opencode-test"}}),
                encoding="utf-8",
            )

            attachment = adapter.inspect_attachment(
                gateway_base_url="http://127.0.0.1:8787/v1",
                env={"HOME": temp_dir},
                config_path=config_path,
            )

        self.assertTrue(attachment.attached)
        self.assertTrue(attachment.managed)
        self.assertEqual(
            attachment.target,
            "http://127.0.0.1:8787/clients/opencode/opencode/v1",
        )
        self.assertTrue(attachment.details["routeSupport"]["supported"])

    def test_openclaw_attachment_reports_preserve_provider_target(self):
        adapter = HarnessAdapterRegistry().adapter_for("openclaw")
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "openclaw.json"
            config_path.write_text(
                json.dumps(
                    build_openclaw_config(
                        primary="openai/gpt-4.1",
                        providers={
                            "openai": build_openclaw_provider(
                                api="openai-completions",
                                base_url="http://127.0.0.1:8787/clients/openclaw/openai/v1",
                            )
                        },
                    )
                ),
                encoding="utf-8",
            )
            models_cache_path = Path(temp_dir) / "agents" / "main" / "agent" / "models.json"
            models_cache_path.parent.mkdir(parents=True, exist_ok=True)
            models_cache_path.write_text(
                json.dumps(
                    build_openclaw_models_cache(
                        providers={
                            "openai": build_openclaw_provider(
                                api="openai-completions",
                                base_url="http://127.0.0.1:8787/clients/openclaw/openai/v1",
                            )
                        }
                    )
                ),
                encoding="utf-8",
            )
            config_path.with_name("openclaw.json.modeio-route.json").write_text(
                json.dumps(
                    {
                        "providers": {
                            "openai": {
                                "providerId": "openai",
                                "providerKey": "openai",
                                "originalBaseUrl": "https://api.openai.com/v1",
                                "routeBaseUrl": "http://127.0.0.1:8787/clients/openclaw/openai/v1",
                                "apiFamily": "openai-completions",
                                "routeMode": "preserve_provider",
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            attachment = adapter.inspect_attachment(
                gateway_base_url="http://127.0.0.1:8787/v1",
                config_path=config_path,
                models_cache_path=models_cache_path,
            )

        self.assertTrue(attachment.attached)
        self.assertTrue(attachment.managed)
        self.assertEqual(
            attachment.target,
            "http://127.0.0.1:8787/clients/openclaw/openai/v1",
        )
        self.assertTrue(attachment.details["routeSupport"]["supported"])

    def test_openclaw_inspect_current_state_honors_override_paths(self):
        adapter = HarnessAdapterRegistry().adapter_for("openclaw")
        with TemporaryDirectory() as temp_dir:
            state_dir = Path(temp_dir) / "custom-state"
            config_path = state_dir / "openclaw.json"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(
                json.dumps(
                    build_openclaw_config(
                        primary="openai/gpt-4.1",
                        providers={
                            "openai": build_openclaw_provider(
                                api="openai-completions",
                                base_url="https://api.openai.com/v1",
                            )
                        },
                    )
                ),
                encoding="utf-8",
            )
            models_cache_path = state_dir / "agents" / "main" / "agent" / "models.json"
            models_cache_path.parent.mkdir(parents=True, exist_ok=True)
            models_cache_path.write_text(
                json.dumps(
                    build_openclaw_models_cache(
                        providers={
                            "openai": build_openclaw_provider(
                                api="openai-completions",
                                base_url="https://api.openai.com/v1",
                            )
                        }
                    )
                ),
                encoding="utf-8",
            )
            auth_profiles_path = models_cache_path.parent / "auth-profiles.json"
            auth_profiles_path.write_text(
                json.dumps(
                    {
                        "profiles": {
                            "openai:default": {
                                "provider": "openai",
                                "type": "bearer",
                                "token": "sk-test-openclaw",
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            inspection = adapter.inspect_current_state(
                env={"HOME": temp_dir},
                config_path=config_path,
                models_cache_path=models_cache_path,
            )

        self.assertTrue(inspection.ready)
        self.assertEqual(inspection.selection.provider_id, "openai")
        self.assertEqual(inspection.selection.model_id, "gpt-4.1")
        self.assertEqual(inspection.selection.api_family, "openai-completions")


if __name__ == "__main__":
    unittest.main()
