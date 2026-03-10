#!/usr/bin/env python3

import io
import json
import os
import sys
import threading
import unittest
from unittest import mock
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT
sys.path.insert(0, str(PACKAGE_DIR))

from modeio_middleware.cli import setup as setup_gateway  # noqa: E402
from modeio_middleware.cli.setup_lib.claude import (  # noqa: E402
    apply_claude_settings_file,
    derive_claude_hook_url,
    uninstall_claude_settings_file,
)
from modeio_middleware.cli.setup_lib.common import (
    SetupError,
    derive_health_url,
    normalize_gateway_base_url,
)  # noqa: E402
from modeio_middleware.cli.setup_lib.opencode import (  # noqa: E402
    apply_opencode_base_url,
    apply_opencode_config_file,
    default_opencode_config_path,
    uninstall_opencode_config_file,
)
from modeio_middleware.cli.setup_lib.openclaw import (  # noqa: E402
    OPENCLAW_AUTH_MODE_MANAGED,
    OPENCLAW_AUTH_MODE_NATIVE,
    OPENCLAW_MODEL_ID,
    OPENCLAW_MODEL_REF,
    OPENCLAW_PROVIDER_ID,
    apply_openclaw_config_file,
    apply_openclaw_models_cache_file,
    apply_openclaw_provider_route,
    default_openclaw_config_path,
    default_openclaw_models_cache_path,
    uninstall_openclaw_config_file,
    uninstall_openclaw_models_cache_file,
)
from modeio_middleware.cli.setup_lib.upstream import (  # noqa: E402
    OPENAI_DEFAULT_MODEL,
    OPENAI_UPSTREAM_BASE_URL,
    resolve_live_upstream_selection,
)


class HealthServer:
    def __init__(self):
        self._server = None
        self._thread = None
        self.health_url = ""

    def start(self):
        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self):
                if self.path == "/healthz":
                    body = b'{"ok":true}'
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                self.send_response(404)
                self.end_headers()

            def log_message(self, _format, *_args):
                return

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        host, port = self._server.server_address
        self.health_url = f"http://{host}:{port}/healthz"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self):
        if self._server:
            self._server.shutdown()
            self._server.server_close()
        if self._thread:
            self._thread.join(timeout=2)


class TestSetupGateway(unittest.TestCase):
    def _run_main_json(self, extra_args):
        out = io.StringIO()
        with redirect_stdout(out):
            code = setup_gateway.main(["--json", *extra_args])
        return code, json.loads(out.getvalue())

    def test_normalize_gateway_base_url(self):
        self.assertEqual(
            normalize_gateway_base_url("http://127.0.0.1:8787/v1/"),
            "http://127.0.0.1:8787/v1",
        )

    def test_normalize_gateway_base_url_requires_http(self):
        with self.assertRaises(SetupError):
            normalize_gateway_base_url("127.0.0.1:8787/v1")

    def test_derive_health_url(self):
        self.assertEqual(
            derive_health_url("http://127.0.0.1:8787/v1"),
            "http://127.0.0.1:8787/healthz",
        )

    def test_derive_claude_hook_url(self):
        self.assertEqual(
            derive_claude_hook_url("http://127.0.0.1:8787/v1"),
            "http://127.0.0.1:8787/connectors/claude/hooks",
        )

    def test_codex_env_command_variants(self):
        url = "http://127.0.0.1:8787/v1"
        self.assertEqual(
            setup_gateway._codex_env_command("bash", url),
            'export OPENAI_BASE_URL="http://127.0.0.1:8787/clients/codex/v1"',
        )
        self.assertEqual(
            setup_gateway._codex_env_command("powershell", url),
            '$env:OPENAI_BASE_URL = "http://127.0.0.1:8787/clients/codex/v1"',
        )

    def test_codex_unset_command_variants(self):
        self.assertEqual(
            setup_gateway._codex_unset_env_command("bash"), "unset OPENAI_BASE_URL"
        )
        self.assertEqual(
            setup_gateway._codex_unset_env_command("powershell"),
            "Remove-Item Env:OPENAI_BASE_URL",
        )

    def test_build_start_command_uses_installed_entrypoint(self):
        command = setup_gateway._build_start_command("http://127.0.0.1:8787/v1")
        self.assertTrue(command.startswith("modeio-middleware-gateway "))

    def test_apply_opencode_base_url_updates_nested_object(self):
        source = {
            "model": "openai/gpt-4o-mini",
            "provider": {
                "openai": {
                    "options": {
                        "apiKey": "secret",
                    }
                }
            },
        }
        updated, changed = apply_opencode_base_url(source, "http://127.0.0.1:8787/v1")
        self.assertTrue(changed)
        self.assertEqual(
            updated["provider"]["openai"]["options"]["baseURL"],
            "http://127.0.0.1:8787/clients/opencode/openai/v1",
        )
        self.assertEqual(
            updated["provider"]["openai"]["options"]["apiKey"],
            "secret",
        )

    def test_apply_opencode_base_url_preserves_missing_api_key(self):
        source = {
            "model": "openai/gpt-4o-mini",
            "provider": {
                "openai": {
                    "options": {}
                }
            },
        }
        updated, changed = apply_opencode_base_url(source, "http://127.0.0.1:8787/v1")
        self.assertTrue(changed)
        self.assertNotIn("apiKey", updated["provider"]["openai"]["options"])

    def test_apply_opencode_base_url_tracks_current_provider(self):
        source = {
            "model": "openrouter/anthropic/claude-sonnet-4",
            "provider": {
                "openrouter": {
                    "options": {
                        "apiKey": "secret",
                    }
                }
            },
        }
        updated, changed = apply_opencode_base_url(source, "http://127.0.0.1:8787/v1")
        self.assertTrue(changed)
        self.assertEqual(
            updated["provider"]["openrouter"]["options"]["baseURL"],
            "http://127.0.0.1:8787/clients/opencode/openrouter/v1",
        )

    def test_apply_and_uninstall_opencode_config_file(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "opencode.json"
            apply_result = apply_opencode_config_file(
                config_path=path,
                gateway_base_url="http://127.0.0.1:8787/v1",
                create_if_missing=True,
            )
            self.assertTrue(apply_result["changed"])
            self.assertTrue(path.exists())

            uninstall_result = uninstall_opencode_config_file(
                config_path=path,
                gateway_base_url="http://127.0.0.1:8787/v1",
                force_remove=False,
            )
            self.assertTrue(uninstall_result["changed"])
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertNotIn("baseURL", payload["provider"]["openai"]["options"])

    def test_default_opencode_config_path_windows_prefers_appdata(self):
        path = default_opencode_config_path(
            os_name="windows",
            env={"APPDATA": "C:/Users/test/AppData/Roaming"},
            home=Path("C:/Users/test"),
        )
        self.assertEqual(
            path, Path("C:/Users/test/AppData/Roaming") / "opencode" / "opencode.json"
        )

    def test_default_openclaw_config_path_honors_env_override(self):
        path = default_openclaw_config_path(
            os_name="linux",
            env={"OPENCLAW_CONFIG_PATH": "/tmp/custom-openclaw.json"},
            home=Path("/home/test"),
        )
        self.assertEqual(path, Path("/tmp/custom-openclaw.json"))

    def test_default_openclaw_models_cache_path_from_config_parent(self):
        config_path = Path("/tmp/custom/openclaw.json")
        path = default_openclaw_models_cache_path(
            config_path=config_path,
            env={},
            home=Path("/home/test"),
        )
        self.assertEqual(path, Path("/tmp/custom/agents/main/agent/models.json"))

    def test_apply_openclaw_provider_route_updates_expected_keys(self):
        updated, changed = apply_openclaw_provider_route(
            {},
            "http://127.0.0.1:8787/v1",
            auth_mode=OPENCLAW_AUTH_MODE_MANAGED,
        )
        self.assertTrue(changed)
        provider = updated["models"]["providers"][OPENCLAW_PROVIDER_ID]
        self.assertEqual(provider["baseUrl"], "http://127.0.0.1:8787/clients/openclaw/v1")
        self.assertEqual(provider["api"], "openai-completions")
        self.assertEqual(provider["apiKey"], "modeio-middleware")
        self.assertFalse(provider["authHeader"])
        self.assertEqual(provider["models"][0]["id"], OPENCLAW_MODEL_ID)
        self.assertEqual(
            updated["agents"]["defaults"]["model"]["primary"],
            OPENCLAW_MODEL_REF,
        )

    def test_apply_and_uninstall_openclaw_config_file(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "openclaw.json"
            apply_result = apply_openclaw_config_file(
                config_path=path,
                gateway_base_url="http://127.0.0.1:8787/v1",
                create_if_missing=True,
                auth_mode=OPENCLAW_AUTH_MODE_MANAGED,
            )
            self.assertTrue(apply_result["changed"])
            self.assertTrue(path.exists())

            uninstall_result = uninstall_openclaw_config_file(
                config_path=path,
                gateway_base_url="http://127.0.0.1:8787/v1",
                force_remove=False,
            )
            self.assertTrue(uninstall_result["changed"])
            payload = json.loads(path.read_text(encoding="utf-8"))
            providers = payload.get("models", {}).get("providers", {})
            self.assertNotIn(OPENCLAW_PROVIDER_ID, providers)

    def test_apply_and_uninstall_openclaw_models_cache_file(self):
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "openclaw.json"
            path = Path(temp_dir) / "agents" / "main" / "agent" / "models.json"
            apply_result = apply_openclaw_models_cache_file(
                models_cache_path=path,
                gateway_base_url="http://127.0.0.1:8787/v1",
                config_path=config_path,
                auth_mode=OPENCLAW_AUTH_MODE_MANAGED,
            )
            self.assertTrue(apply_result["changed"])
            self.assertTrue(path.exists())

            uninstall_result = uninstall_openclaw_models_cache_file(
                models_cache_path=path,
                gateway_base_url="http://127.0.0.1:8787/v1",
                config_path=config_path,
                force_remove=False,
                auth_mode=OPENCLAW_AUTH_MODE_MANAGED,
            )
            self.assertTrue(uninstall_result["changed"])
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertNotIn(
                OPENCLAW_PROVIDER_ID,
                payload.get("models", {}).get("providers", {}),
            )

    def test_apply_openclaw_provider_route_native_mode_preserves_provider_context(self):
        source = {
            "agents": {"defaults": {"model": {"primary": "openai/gpt-4.1"}}},
            "models": {
                "providers": {
                    "openai": {
                        "api": "openai-completions",
                        "baseUrl": "https://api.openai.com/v1",
                    }
                }
            },
        }
        updated, changed = apply_openclaw_provider_route(
            source,
            "http://127.0.0.1:8787/v1",
            auth_mode=OPENCLAW_AUTH_MODE_NATIVE,
        )
        self.assertTrue(changed)
        provider = updated["models"]["providers"]["openai"]
        self.assertEqual(
            provider["baseUrl"],
            "http://127.0.0.1:8787/clients/openclaw/openai/v1",
        )
        self.assertEqual(
            updated["agents"]["defaults"]["model"]["primary"],
            "openai/gpt-4.1",
        )
        self.assertNotIn(OPENCLAW_PROVIDER_ID, updated["models"]["providers"])

    def test_apply_openclaw_provider_route_native_mode_preserves_anthropic_provider_context(self):
        source = {
            "agents": {"defaults": {"model": {"primary": "anthropic/claude-sonnet-4"}}},
            "models": {
                "providers": {
                    "anthropic": {
                        "api": "anthropic-messages",
                        "baseUrl": "https://api.anthropic.com",
                    }
                }
            },
        }
        updated, changed = apply_openclaw_provider_route(
            source,
            "http://127.0.0.1:8787/v1",
            auth_mode=OPENCLAW_AUTH_MODE_NATIVE,
        )
        self.assertTrue(changed)
        provider = updated["models"]["providers"]["anthropic"]
        self.assertEqual(
            provider["baseUrl"],
            "http://127.0.0.1:8787/clients/openclaw/anthropic",
        )
        self.assertEqual(provider["api"], "anthropic-messages")
        self.assertEqual(
            updated["agents"]["defaults"]["model"]["primary"],
            "anthropic/claude-sonnet-4",
        )

    def test_apply_and_uninstall_openclaw_config_file_native_mode_restores_primary(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "openclaw.json"
            path.write_text(
                json.dumps(
                    {
                        "agents": {
                            "defaults": {
                                "model": {"primary": "openai/gpt-4.1"}
                            }
                        },
                        "models": {
                            "providers": {
                                "openai": {
                                    "api": "openai-completions",
                                    "baseUrl": "https://api.openai.com/v1",
                                }
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            apply_result = apply_openclaw_config_file(
                config_path=path,
                gateway_base_url="http://127.0.0.1:8787/v1",
                create_if_missing=False,
                auth_mode=OPENCLAW_AUTH_MODE_NATIVE,
            )
            self.assertEqual(apply_result["authMode"], "native")
            uninstall_result = uninstall_openclaw_config_file(
                config_path=path,
                gateway_base_url="http://127.0.0.1:8787/v1",
                force_remove=False,
            )
            self.assertTrue(uninstall_result["changed"])

            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(
                payload["agents"]["defaults"]["model"]["primary"],
                "openai/gpt-4.1",
            )
            self.assertEqual(
                payload["models"]["providers"]["openai"]["baseUrl"],
                "https://api.openai.com/v1",
            )

    def test_apply_openclaw_config_file_native_mode_is_idempotent(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "openclaw.json"
            path.write_text(
                json.dumps(
                    {
                        "agents": {
                            "defaults": {
                                "model": {"primary": "openai/gpt-4.1"}
                            }
                        },
                        "models": {
                            "providers": {
                                "openai": {
                                    "api": "openai-completions",
                                    "baseUrl": "https://api.openai.com/v1",
                                }
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            apply_openclaw_config_file(
                config_path=path,
                gateway_base_url="http://127.0.0.1:8787/v1",
                create_if_missing=False,
                auth_mode=OPENCLAW_AUTH_MODE_NATIVE,
            )
            second_apply = apply_openclaw_config_file(
                config_path=path,
                gateway_base_url="http://127.0.0.1:8787/v1",
                create_if_missing=False,
                auth_mode=OPENCLAW_AUTH_MODE_NATIVE,
            )
            self.assertEqual(second_apply["authMode"], "native")

            payload = json.loads(path.read_text(encoding="utf-8"))
            provider = payload["models"]["providers"]["openai"]
            self.assertEqual(
                provider["baseUrl"],
                "http://127.0.0.1:8787/clients/openclaw/openai/v1",
            )

    def test_openclaw_uninstall_mismatch_keeps_restore_sidecar(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "openclaw.json"
            path.write_text(
                json.dumps(
                    {
                        "agents": {
                            "defaults": {
                                "model": {"primary": "openai/gpt-4.1"}
                            }
                        },
                        "models": {
                            "providers": {
                                "openai": {
                                    "api": "openai-completions",
                                    "baseUrl": "https://api.openai.com/v1",
                                }
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            apply_openclaw_config_file(
                config_path=path,
                gateway_base_url="http://127.0.0.1:8787/v1",
                create_if_missing=False,
                auth_mode=OPENCLAW_AUTH_MODE_NATIVE,
            )
            uninstall_result = uninstall_openclaw_config_file(
                config_path=path,
                gateway_base_url="http://127.0.0.1:9999/v1",
                force_remove=False,
            )
            self.assertFalse(uninstall_result["changed"])
            self.assertTrue(path.with_name("openclaw.json.modeio-route.json").exists())

    def test_openclaw_native_mode_defers_openai_codex_provider(self):
        source = {
            "agents": {"defaults": {"model": {"primary": "openai-codex/gpt-5.3-codex"}}},
            "models": {
                "providers": {
                    "openai-codex": {
                        "baseUrl": "https://chatgpt.com/backend-api/codex",
                    }
                }
            },
        }
        updated, changed = apply_openclaw_provider_route(
            source,
            "http://127.0.0.1:8787/v1",
            auth_mode=OPENCLAW_AUTH_MODE_NATIVE,
        )
        self.assertFalse(changed)
        self.assertEqual(updated, source)

    def test_apply_and_uninstall_claude_settings_file(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "settings.json"
            apply_result = apply_claude_settings_file(
                config_path=path,
                gateway_base_url="http://127.0.0.1:8787/v1",
                create_if_missing=True,
            )
            self.assertTrue(apply_result["changed"])
            self.assertTrue(path.exists())

            payload = json.loads(path.read_text(encoding="utf-8"))
            hooks = payload["hooks"]
            self.assertIn("UserPromptSubmit", hooks)
            self.assertIn("Stop", hooks)

            uninstall_result = uninstall_claude_settings_file(
                config_path=path,
                gateway_base_url="http://127.0.0.1:8787/v1",
                force_remove=False,
            )
            self.assertTrue(uninstall_result["changed"])
            self.assertEqual(uninstall_result["removedHooks"], 2)

            payload_after = json.loads(path.read_text(encoding="utf-8"))
            self.assertNotIn("hooks", payload_after)

    def test_health_check_reports_healthy(self):
        server = HealthServer()
        server.start()
        try:
            health = setup_gateway._check_gateway_health(
                server.health_url, timeout_seconds=2
            )
            self.assertTrue(health.checked)
            self.assertTrue(health.ok)
            self.assertEqual(health.status_code, 200)
        finally:
            server.stop()

    def test_main_json_validation_error(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = setup_gateway.main(["--json", "--create-opencode-config"])
        self.assertEqual(code, 2)
        payload = json.loads(out.getvalue())
        self.assertFalse(payload["success"])
        self.assertEqual(payload["error"]["type"], "validation_error")

    def test_main_json_validation_error_for_claude_create(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = setup_gateway.main(["--json", "--create-claude-settings"])
        self.assertEqual(code, 2)
        payload = json.loads(out.getvalue())
        self.assertFalse(payload["success"])
        self.assertEqual(payload["error"]["type"], "validation_error")

    def test_main_json_validation_error_for_openclaw_create(self):
        code, payload = self._run_main_json(["--create-openclaw-config"])
        self.assertEqual(code, 2)
        self.assertFalse(payload["success"])
        self.assertEqual(payload["error"]["type"], "validation_error")

    def test_main_json_openclaw_apply_uses_explicit_temp_path(self):
        with TemporaryDirectory() as temp_dir:
            openclaw_path = Path(temp_dir) / "openclaw.json"
            code, payload = self._run_main_json(
                [
                    "--apply-openclaw",
                    "--create-openclaw-config",
                    "--openclaw-config-path",
                    str(openclaw_path),
                ]
            )
            self.assertEqual(code, 0)
            self.assertTrue(payload["success"])
            self.assertIsNotNone(payload["openclaw"])
            self.assertTrue(openclaw_path.exists())
            self.assertIsNotNone(payload["openclaw"].get("modelsCache"))

    def test_main_json_doctor_reports_required_checks(self):
        with TemporaryDirectory() as temp_dir:
            auth_dir = Path(temp_dir) / ".codex"
            auth_dir.mkdir(parents=True)
            (auth_dir / "auth.json").write_text(
                '{"access_token":"test"}', encoding="utf-8"
            )

            with mock.patch.dict(
                os.environ,
                {
                    "HOME": temp_dir,
                    "MODEIO_GATEWAY_UPSTREAM_API_KEY": "sk-test",
                },
                clear=False,
            ):
                code, payload = self._run_main_json(
                    [
                        "--doctor",
                        "--require-upstream-api-key",
                        "--require-codex-auth",
                    ]
                )

        self.assertEqual(code, 0)
        self.assertTrue(payload["success"])
        self.assertEqual(payload["mode"], "doctor")
        self.assertTrue(payload["upstreamApiKey"]["present"])
        self.assertTrue(payload["codex"]["authPresent"])
        self.assertIn("nativeClients", payload)
        self.assertIn("codex", payload["nativeClients"])
        self.assertNotIn("authorization", payload["nativeClients"]["codex"])
        self.assertGreaterEqual(len(payload["checks"]), 2)

    def test_main_json_doctor_fails_when_required_command_missing(self):
        code, payload = self._run_main_json(
            [
                "--doctor",
                "--require-commands",
                "definitely-not-a-real-modeio-command",
            ]
        )
        self.assertEqual(code, 1)
        self.assertFalse(payload["success"])
        self.assertEqual(payload["checks"][0]["name"], "required-commands")
        self.assertIn(
            "definitely-not-a-real-modeio-command",
            payload["checks"][0]["missing"],
        )

    def test_main_json_doctor_does_not_silently_pick_zenmux_without_config(self):
        with TemporaryDirectory() as temp_dir:
            with mock.patch.dict(
                os.environ,
                {
                    "HOME": temp_dir,
                    "ZENMUX_API_KEY": "sk-zenmux-test",
                },
                clear=True,
            ):
                code, payload = self._run_main_json(
                    [
                        "--doctor",
                        "--require-upstream-api-key",
                        "--upstream-api-key-env",
                        "MODEIO_GATEWAY_UPSTREAM_API_KEY",
                    ]
                )
        self.assertEqual(code, 1)
        self.assertFalse(payload["success"])
        self.assertEqual(payload["checks"][0]["resolvedSource"], None)

    def test_resolve_live_upstream_selection_prefers_openai_env_over_bare_zenmux_key(self):
        with TemporaryDirectory() as temp_dir:
            selection = resolve_live_upstream_selection(
                env={
                    "HOME": temp_dir,
                    "OPENAI_API_KEY": "sk-openai-test",
                    "ZENMUX_API_KEY": "sk-zenmux-test",
                }
            )
        self.assertTrue(selection["ready"])
        self.assertEqual(selection["source"], "openai_env")
        self.assertEqual(selection["baseUrl"], OPENAI_UPSTREAM_BASE_URL)
        self.assertEqual(selection["model"], OPENAI_DEFAULT_MODEL)
        self.assertEqual(selection["apiKeyEnv"], "OPENAI_API_KEY")

    def test_resolve_live_upstream_selection_reuses_opencode_config(self):
        with TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            config_path = home / ".config" / "opencode" / "opencode.json"
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

            selection = resolve_live_upstream_selection(
                env={
                    "HOME": temp_dir,
                }
            )

        self.assertTrue(selection["ready"])
        self.assertEqual(selection["source"], "opencode_config")
        self.assertEqual(selection["baseUrl"], "https://provider.example/v1")
        self.assertEqual(selection["model"], "provider-model")
        self.assertEqual(selection["apiKeySource"], "config:provider.openai.options.apiKey")

    def test_main_json_doctor_accepts_reusable_opencode_upstream(self):
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

            with mock.patch.dict(os.environ, {"HOME": temp_dir}, clear=True):
                code, payload = self._run_main_json(
                    [
                        "--doctor",
                        "--require-upstream-api-key",
                    ]
                )

        self.assertEqual(code, 0)
        self.assertTrue(payload["success"])
        self.assertEqual(payload["liveUpstream"]["source"], "opencode_config")
        self.assertEqual(payload["checks"][0]["resolvedSource"], "opencode_config")

    def test_resolve_live_upstream_selection_reuses_openclaw_config(self):
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / ".openclaw" / "openclaw.json"
            config_path.parent.mkdir(parents=True)
            config_path.write_text(
                json.dumps(
                    {
                        "models": {
                            "providers": {
                                "remote-provider": {
                                    "baseUrl": "https://provider.example/v1",
                                    "apiKey": "cfg-secret",
                                }
                            }
                        },
                        "agents": {
                            "defaults": {
                                "model": {"primary": "remote-provider/provider-model"}
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            selection = resolve_live_upstream_selection(
                env={
                    "HOME": temp_dir,
                }
            )

        self.assertTrue(selection["ready"])
        self.assertEqual(selection["source"], "openclaw_config")
        self.assertEqual(selection["baseUrl"], "https://provider.example/v1")
        self.assertEqual(selection["model"], "provider-model")

    def test_main_json_doctor_accepts_zenmux_key_fallback_from_reused_config(self):
        with mock.patch.dict(
            os.environ,
            {
                "ZENMUX_API_KEY": "sk-zenmux-test",
                "HOME": "/tmp/unused-home",
            },
            clear=True,
        ):
            with TemporaryDirectory() as temp_dir:
                config_path = Path(temp_dir) / "opencode.json"
                config_path.write_text(
                    json.dumps(
                        {
                            "model": "openai/gpt-5.3-codex",
                            "provider": {
                                "openai": {
                                    "options": {
                                        "baseURL": "https://zenmux.ai/api/v1"
                                    }
                                }
                            },
                        }
                    ),
                    encoding="utf-8",
                )
                code, payload = self._run_main_json(
                    [
                        "--doctor",
                        "--require-upstream-api-key",
                        "--opencode-config-path",
                        str(config_path),
                    ]
                )
        self.assertEqual(code, 0)
        self.assertTrue(payload["success"])
        self.assertEqual(payload["liveUpstream"]["source"], "opencode_config")
        self.assertEqual(payload["liveUpstream"]["apiKeyEnv"], "ZENMUX_API_KEY")

    def test_main_json_doctor_validation_error_for_mutating_flags(self):
        code, payload = self._run_main_json(["--doctor", "--apply-opencode"])
        self.assertEqual(code, 2)
        self.assertFalse(payload["success"])
        self.assertEqual(payload["error"]["type"], "validation_error")


if __name__ == "__main__":
    unittest.main()
