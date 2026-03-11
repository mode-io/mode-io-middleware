#!/usr/bin/env python3

import json
import sys
import unittest
from tempfile import TemporaryDirectory
from unittest import mock
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"

sys.path.insert(0, str(SCRIPTS_DIR))

from smoke_agent_matrix import parse_args  # noqa: E402
from smoke_agent_matrix import (  # noqa: E402
    _parse_openclaw_families,
    _resolve_codex_smoke_model,
    _resolve_openclaw_family_scenarios,
)
from smoke_matrix.agents import build_agent_command  # noqa: E402
from smoke_matrix.common import (  # noqa: E402
    default_repo_root,
    default_upstream_base_url,
    default_upstream_model,
    parse_agents,
)
from smoke_matrix.sandbox import (  # noqa: E402
    build_sandbox_env,
    build_sandbox_paths,
    configure_openclaw_supported_family,
    resolve_codex_smoke_model,
    resolve_opencode_smoke_model,
)


class TestSmokeAgentMatrixSupport(unittest.TestCase):
    def test_parse_agents_accepts_claude_and_dedupes(self):
        self.assertEqual(
            parse_agents("codex,claude,opencode,claude"),
            ("codex", "claude", "opencode"),
        )

    def test_build_sandbox_paths_includes_claude_settings(self):
        paths = build_sandbox_paths(Path("/tmp/modeio-smoke"))
        self.assertEqual(
            paths["claude_settings"],
            Path("/tmp/modeio-smoke/home/.claude/settings.json"),
        )
        self.assertEqual(
            paths["codex_config"],
            Path("/tmp/modeio-smoke/home/.codex/config.toml"),
        )

    def test_build_sandbox_env_uses_codex_only_base_url_marker(self):
        paths = build_sandbox_paths(Path("/tmp/modeio-smoke"))
        env = build_sandbox_env(
            {"PATH": "/usr/bin", "OPENAI_API_KEY": "sk-test"},
            paths,
            gateway_base_url="http://127.0.0.1:8787/v1",
        )
        self.assertEqual(
            env["MODEIO_SMOKE_CODEX_BASE_URL"],
            "http://127.0.0.1:8787/clients/codex/v1",
        )
        self.assertNotIn("OPENAI_BASE_URL", env)
        self.assertNotIn("OPENAI_API_KEY", env)

    def test_build_agent_command_for_claude_uses_print_mode_and_settings(self):
        command = build_agent_command(
            agent="claude",
            token="CLAUDE_TOKEN",
            model="openai/gpt-5.3-codex",
            claude_model="sonnet",
            repo_root=Path("/tmp/repo"),
            codex_output_path=Path("/tmp/codex-last-message.txt"),
            claude_settings_path=Path("/tmp/claude-settings.json"),
            timeout_seconds=30,
        )
        self.assertEqual(command[0], "claude")
        self.assertIn("--print", command)
        self.assertIn("--no-session-persistence", command)
        self.assertIn("--settings", command)
        self.assertEqual(
            command[command.index("--settings") + 1], "/tmp/claude-settings.json"
        )
        self.assertIn("--model", command)
        self.assertEqual(command[command.index("--model") + 1], "sonnet")

    def test_parse_args_defaults_include_claude(self):
        import smoke_agent_matrix  # noqa: E402

        with (
            mock.patch.object(
                smoke_agent_matrix,
                "DEFAULT_UPSTREAM_BASE_URL",
                "https://api.openai.com/v1",
            ),
            mock.patch.object(
                smoke_agent_matrix,
                "DEFAULT_UPSTREAM_MODEL",
                "gpt-4o-mini",
            ),
        ):
            args = smoke_agent_matrix.parse_args([])
        self.assertEqual(args.agents, "codex,opencode,openclaw,claude")
        self.assertEqual(args.claude_model, "sonnet")
        self.assertEqual(args.upstream_base_url, "https://api.openai.com/v1")
        self.assertEqual(args.model, "gpt-4o-mini")
        self.assertEqual(args.opencode_model, "")
        self.assertEqual(args.install_mode, "repo")
        self.assertEqual(args.install_target, "")
        self.assertEqual(args.openclaw_families, "current")
        self.assertEqual(args.openclaw_anthropic_provider, "")
        self.assertEqual(args.openclaw_anthropic_model, "")
        self.assertEqual(args.openclaw_anthropic_base_url, "")

    def test_parse_args_accepts_wheel_install_mode(self):
        args = parse_args(
            ["--install-mode", "wheel", "--install-target", "/tmp/pkg.whl"]
        )
        self.assertEqual(args.install_mode, "wheel")
        self.assertEqual(args.install_target, "/tmp/pkg.whl")

    def test_default_repo_root_resolves_repo_checkout(self):
        script_path = REPO_ROOT / "scripts" / "smoke_agent_matrix.py"
        self.assertEqual(default_repo_root(script_path), REPO_ROOT)

    def test_bare_zenmux_env_does_not_silently_change_defaults(self):
        with TemporaryDirectory() as temp_dir:
            env = {"HOME": temp_dir, "ZENMUX_API_KEY": "sk-test"}
            self.assertEqual(default_upstream_base_url(env), "https://api.openai.com/v1")
            self.assertEqual(default_upstream_model(env), "gpt-4o-mini")

    def test_defaults_ignore_host_config_and_stay_static(self):
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / ".config" / "opencode" / "opencode.json"
            config_path.parent.mkdir(parents=True)
            config_path.write_text(
                json.dumps(
                    {
                        "model": "provider-model",
                        "provider": {
                            "openai": {
                                "options": {
                                    "baseURL": "https://provider.example/v1",
                                    "apiKey": "cfg-secret",
                                }
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            env = {"HOME": temp_dir}
            self.assertEqual(default_upstream_base_url(env), "https://api.openai.com/v1")
            self.assertEqual(default_upstream_model(env), "gpt-4o-mini")

    def test_parse_args_ignores_managed_upstream_environment_defaults(self):
        with mock.patch.dict(
            "os.environ",
            {
                "MODEIO_GATEWAY_UPSTREAM_BASE_URL": "https://example.test/v1",
                "MODEIO_GATEWAY_UPSTREAM_MODEL": "example-model",
            },
            clear=False,
        ):
            args = parse_args([])

        self.assertEqual(args.upstream_base_url, "https://api.openai.com/v1")
        self.assertEqual(args.model, "gpt-4o-mini")
        self.assertEqual(args.opencode_model, "")

    def test_resolve_codex_smoke_model_returns_none_for_generic_default(self):
        import smoke_agent_matrix  # noqa: E402

        with mock.patch.object(smoke_agent_matrix, "DEFAULT_UPSTREAM_MODEL", "gpt-4o-mini"):
            self.assertIsNone(_resolve_codex_smoke_model("gpt-4o-mini"))
            self.assertIsNone(_resolve_codex_smoke_model(""))

    def test_resolve_codex_smoke_model_keeps_explicit_override(self):
        import smoke_agent_matrix  # noqa: E402

        with mock.patch.object(smoke_agent_matrix, "DEFAULT_UPSTREAM_MODEL", "gpt-4o-mini"):
            self.assertEqual(_resolve_codex_smoke_model("gpt-5.4"), "gpt-5.4")
            self.assertEqual(
                _resolve_codex_smoke_model("openai/gpt-5.3-codex"),
                "gpt-5.3-codex",
            )

    def test_resolve_codex_smoke_model_prefers_seeded_codex_config(self):
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.toml"
            config_path.write_text('model = "gpt-5.4"\n', encoding="utf-8")

            resolved = resolve_codex_smoke_model(
                config_path=config_path,
            )

            self.assertEqual(resolved, "gpt-5.4")

    def test_resolve_codex_smoke_model_raises_when_config_missing(self):
        with TemporaryDirectory() as temp_dir:
            with self.assertRaises(ValueError):
                resolve_codex_smoke_model(
                    config_path=Path(temp_dir) / "missing.toml",
                )

    def test_resolve_opencode_smoke_model_prefers_config_model(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "opencode.json"
            state_path = root / "model.json"
            config_path.write_text(
                json.dumps({"model": "openai/gpt-5.4"}),
                encoding="utf-8",
            )

            resolved = resolve_opencode_smoke_model(
                config_path=config_path,
                state_path=state_path,
            )

            self.assertEqual(resolved, "openai/gpt-5.4")

    def test_resolve_opencode_smoke_model_falls_back_to_recent_state(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "opencode.json"
            state_path = root / "model.json"
            config_path.write_text("{}", encoding="utf-8")
            state_path.write_text(
                json.dumps(
                    {
                        "recent": [
                            {
                                "providerID": "openai",
                                "modelID": "gpt-5.4",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            resolved = resolve_opencode_smoke_model(
                config_path=config_path,
                state_path=state_path,
            )

            self.assertEqual(resolved, "openai/gpt-5.4")

    def test_resolve_opencode_smoke_model_raises_when_state_missing(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "opencode.json"
            state_path = root / "model.json"
            config_path.write_text("{}", encoding="utf-8")

            with self.assertRaises(ValueError):
                resolve_opencode_smoke_model(
                    config_path=config_path,
                    state_path=state_path,
                )

    def test_parse_openclaw_families_rejects_invalid_values(self):
        with self.assertRaises(ValueError):
            _parse_openclaw_families("openai-completions,unsupported-family")

    def test_parse_openclaw_families_accepts_current_mode(self):
        self.assertEqual(_parse_openclaw_families("current"), ("current",))

    def test_resolve_openclaw_family_scenarios_follows_current_primary_only(self):
        with TemporaryDirectory() as temp_dir:
            paths = build_sandbox_paths(Path(temp_dir))
            paths["openclaw_config"].parent.mkdir(parents=True, exist_ok=True)
            paths["openclaw_models_cache"].parent.mkdir(parents=True, exist_ok=True)
            paths["openclaw_config"].write_text(
                json.dumps(
                    {
                        "agents": {
                            "defaults": {
                                "model": {"primary": "zenmux/gpt-5.3-codex"}
                            }
                        },
                        "models": {
                            "providers": {
                                "anthropic": {
                                    "api": "anthropic-messages",
                                    "baseUrl": "https://api.anthropic.com",
                                    "models": [
                                        {
                                            "id": "anthropic/claude-sonnet-4-6",
                                            "name": "Claude Sonnet 4.6",
                                        }
                                    ],
                                }
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            paths["openclaw_models_cache"].write_text(
                json.dumps(
                    {
                        "models": {
                            "providers": {
                                "zenmux": {
                                    "api": "openai-completions",
                                    "baseUrl": "https://zenmux.ai/api/v1",
                                    "models": [
                                        {
                                            "id": "openai/gpt-5.3-codex",
                                            "name": "GPT 5.3 Codex",
                                        }
                                    ],
                                },
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            paths["openclaw_config"].with_name("openclaw.json.modeio-route.json").write_text(
                json.dumps(
                    {
                        "providers": {
                            "zenmux": {
                                "providerId": "zenmux",
                                "providerKey": "zenmux",
                                "apiFamily": "openai-completions",
                                "originalBaseUrl": "https://zenmux.ai/api/v1",
                            },
                            "anthropic": {
                                "providerId": "anthropic",
                                "providerKey": "anthropic",
                                "apiFamily": "anthropic-messages",
                                "originalBaseUrl": "https://api.anthropic.com",
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            args = parse_args([])
            scenarios = _resolve_openclaw_family_scenarios(paths=paths, args=args)

            self.assertEqual(len(scenarios), 1)
            scenario = scenarios[0]
            self.assertEqual(scenario["family"], "openai-completions")
            self.assertEqual(scenario["providerKey"], "zenmux")
            self.assertEqual(scenario["modelRef"], "zenmux/gpt-5.3-codex")
            self.assertEqual(
                scenario["realBaseUrl"],
                "https://zenmux.ai/api/v1",
            )
            self.assertEqual(scenario["source"], "current_primary")

    def test_resolve_openclaw_family_scenarios_skips_when_current_family_unsupported(self):
        with TemporaryDirectory() as temp_dir:
            paths = build_sandbox_paths(Path(temp_dir))
            paths["openclaw_config"].parent.mkdir(parents=True, exist_ok=True)
            paths["openclaw_models_cache"].parent.mkdir(parents=True, exist_ok=True)
            paths["openclaw_config"].write_text(
                json.dumps(
                    {
                        "agents": {
                            "defaults": {
                                "model": {"primary": "openai-codex/gpt-5.3-codex"}
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            paths["openclaw_models_cache"].write_text(
                json.dumps(
                    {
                        "models": {
                            "providers": {
                                "openrouter": {
                                    "api": "openai-completions",
                                    "baseUrl": "https://openrouter.ai/api/v1",
                                    "models": [{"id": "gpt-5.4", "name": "GPT 5.4"}],
                                },
                                "zenmux": {
                                    "api": "openai-completions",
                                    "baseUrl": "https://zenmux.ai/api/v1",
                                    "models": [
                                        {
                                            "id": "openai/gpt-5.3-codex",
                                            "name": "GPT 5.3 Codex",
                                        }
                                    ],
                                },
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            scenarios = _resolve_openclaw_family_scenarios(
                paths=paths,
                args=parse_args([]),
            )

            self.assertEqual(len(scenarios), 1)
            scenario = scenarios[0]
            self.assertTrue(scenario["skipped"])
            self.assertEqual(scenario["reason"], "unsupported_current_family")

    def test_resolve_openclaw_family_scenarios_requires_current_primary_to_match_explicit_family(self):
        with TemporaryDirectory() as temp_dir:
            paths = build_sandbox_paths(Path(temp_dir))
            paths["openclaw_config"].parent.mkdir(parents=True, exist_ok=True)
            paths["openclaw_models_cache"].parent.mkdir(parents=True, exist_ok=True)
            paths["openclaw_config"].write_text(
                json.dumps(
                    {
                        "agents": {
                            "defaults": {
                                "model": {"primary": "openai-codex/gpt-5.3-codex"}
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            paths["openclaw_models_cache"].write_text(
                json.dumps(
                    {
                        "models": {
                            "providers": {
                                "zenmux": {
                                    "api": "openai-completions",
                                    "baseUrl": "https://zenmux.ai/api/v1",
                                    "models": [
                                        {
                                            "id": "openai/gpt-5.3-codex",
                                            "name": "GPT 5.3 Codex",
                                        }
                                    ],
                                },
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            scenarios = _resolve_openclaw_family_scenarios(
                paths=paths,
                args=parse_args(["--openclaw-families", "openai-completions"]),
            )

            self.assertEqual(len(scenarios), 1)
            scenario = scenarios[0]
            self.assertTrue(scenario["error"])
            self.assertEqual(scenario["reason"], "current_primary_family_mismatch")

    def test_configure_openclaw_supported_family_updates_config_and_cache(self):
        with TemporaryDirectory() as temp_dir:
            paths = build_sandbox_paths(Path(temp_dir))
            result = configure_openclaw_supported_family(
                config_path=paths["openclaw_config"],
                models_cache_path=paths["openclaw_models_cache"],
                provider_key="anthropic",
                model_ref="anthropic/claude-sonnet-4-6",
                api_family="anthropic-messages",
                base_url="http://127.0.0.1:8787",
                provider_fields={"authHeader": False},
            )

            self.assertTrue(result["configChanged"])
            self.assertTrue(result["modelsCacheChanged"])

            config_payload = json.loads(paths["openclaw_config"].read_text(encoding="utf-8"))
            self.assertEqual(
                config_payload["agents"]["defaults"]["model"]["primary"],
                "anthropic/claude-sonnet-4-6",
            )
            provider = config_payload["models"]["providers"]["anthropic"]
            self.assertEqual(provider["baseUrl"], "http://127.0.0.1:8787")
            self.assertEqual(provider["api"], "anthropic-messages")
            self.assertEqual(provider["authHeader"], False)
            self.assertEqual(provider["models"][0]["id"], "claude-sonnet-4-6")

            cache_payload = json.loads(
                paths["openclaw_models_cache"].read_text(encoding="utf-8")
            )
            cache_provider = cache_payload["models"]["providers"]["anthropic"]
            self.assertEqual(cache_provider["baseUrl"], "http://127.0.0.1:8787")
            self.assertEqual(cache_provider["api"], "anthropic-messages")
            self.assertEqual(cache_provider["authHeader"], False)
            self.assertEqual(cache_provider["models"][0]["id"], "claude-sonnet-4-6")


if __name__ == "__main__":
    unittest.main()
