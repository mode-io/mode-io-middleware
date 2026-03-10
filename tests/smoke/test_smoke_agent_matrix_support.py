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
from smoke_matrix.agents import build_agent_command  # noqa: E402
from smoke_matrix.common import (  # noqa: E402
    default_repo_root,
    default_upstream_base_url,
    default_upstream_model,
    parse_agents,
)
from smoke_matrix.sandbox import build_sandbox_paths  # noqa: E402


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
        self.assertEqual(args.install_mode, "repo")
        self.assertEqual(args.install_target, "")

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

    def test_opencode_config_defaults_drive_live_upstream_choice(self):
        with TemporaryDirectory() as temp_dir:
            config_path = (
                Path(temp_dir) / ".config" / "opencode" / "opencode.json"
            )
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
            self.assertEqual(default_upstream_base_url(env), "https://provider.example/v1")
            self.assertEqual(default_upstream_model(env), "provider-model")

    def test_parse_args_uses_environment_defaults_for_live_smoke(self):
        with mock.patch.dict(
            "os.environ",
            {
                "MODEIO_GATEWAY_UPSTREAM_BASE_URL": "https://example.test/v1",
                "MODEIO_GATEWAY_UPSTREAM_MODEL": "example-model",
            },
            clear=False,
        ):
            import smoke_agent_matrix  # noqa: E402

            with (
                mock.patch.object(
                    smoke_agent_matrix,
                    "DEFAULT_UPSTREAM_BASE_URL",
                    "https://example.test/v1",
                ),
                mock.patch.object(
                    smoke_agent_matrix,
                    "DEFAULT_UPSTREAM_MODEL",
                    "example-model",
                ),
            ):
                args = smoke_agent_matrix.parse_args([])

        self.assertEqual(args.upstream_base_url, "https://example.test/v1")
        self.assertEqual(args.model, "example-model")


if __name__ == "__main__":
    unittest.main()
