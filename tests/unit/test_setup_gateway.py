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

from tests.helpers.openclaw_builder import (  # noqa: E402
    build_openclaw_config,
    build_openclaw_models_cache,
    build_openclaw_provider,
)

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
    apply_openclaw_config_file,
    apply_openclaw_models_cache_file,
    apply_openclaw_provider_route,
    default_openclaw_config_path,
    default_openclaw_models_cache_path,
    uninstall_openclaw_config_file,
    uninstall_openclaw_models_cache_file,
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
            path.write_text(
                json.dumps(
                    {
                        "model": "openai/gpt-4o-mini",
                        "provider": {
                            "openai": {
                                "options": {
                                    "apiKey": "secret",
                                    "baseURL": "https://api.openai.com/v1",
                                }
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            apply_result = apply_opencode_config_file(
                config_path=path,
                gateway_base_url="http://127.0.0.1:8787/v1",
                create_if_missing=False,
                env={"HOME": temp_dir},
            )
            self.assertTrue(apply_result["changed"])
            self.assertTrue(path.exists())
            self.assertEqual(apply_result["providerId"], "openai")
            self.assertEqual(apply_result["routeMode"], "preserve_provider")
            route_metadata = json.loads(
                path.with_name("opencode.json.modeio-route.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                route_metadata["providers"]["openai"]["originalBaseUrl"],
                "https://api.openai.com/v1",
            )

            uninstall_result = uninstall_opencode_config_file(
                config_path=path,
                gateway_base_url="http://127.0.0.1:8787/v1",
                force_remove=False,
            )
            self.assertTrue(uninstall_result["changed"])
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(
                payload["provider"]["openai"]["options"]["baseURL"],
                "https://api.openai.com/v1",
            )
            self.assertFalse(path.with_name("opencode.json.modeio-route.json").exists())

    def test_apply_opencode_config_file_rejects_openai_oauth_transport(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = root / "opencode.json"
            path.write_text(
                json.dumps(
                    {
                        "model": "openai/gpt-5.4",
                        "provider": {
                            "openai": {
                                "options": {
                                    "baseURL": "https://api.openai.com/v1",
                                }
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            auth_store = root / ".local" / "share" / "opencode" / "auth.json"
            auth_store.parent.mkdir(parents=True)
            auth_store.write_text(
                json.dumps(
                    {
                        "openai": {
                            "type": "oauth",
                            "access": "oauth-access",
                            "refresh": "oauth-refresh",
                            "expires": 9999999999,
                        }
                    }
                ),
                encoding="utf-8",
            )

            result = apply_opencode_config_file(
                config_path=path,
                gateway_base_url="http://127.0.0.1:8787/v1",
                create_if_missing=False,
                env={"HOME": temp_dir},
            )

        self.assertFalse(result["changed"])
        self.assertFalse(result["supported"])
        self.assertEqual(result["providerId"], "openai")
        self.assertEqual(result["reason"], "provider_uses_internal_oauth_transport")
        self.assertEqual(result["authType"], "oauth")
        self.assertFalse(path.with_name("opencode.json.modeio-route.json").exists())

    def test_apply_opencode_config_file_requires_recoverable_upstream_base_url(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "opencode.json"
            path.write_text(
                json.dumps(
                    {
                        "model": "openrouter/claude-sonnet-4",
                        "provider": {
                            "openrouter": {
                                "options": {
                                    "apiKey": "secret",
                                    "baseURL": "http://127.0.0.1:8787/clients/opencode/openrouter/v1",
                                }
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            result = apply_opencode_config_file(
                config_path=path,
                gateway_base_url="http://127.0.0.1:8787/v1",
                create_if_missing=False,
            )

        self.assertFalse(result["changed"])
        self.assertFalse(result["supported"])
        self.assertEqual(result["reason"], "missing_upstream_base_url")

    def test_apply_opencode_config_file_accepts_preserved_loopback_via_route_metadata(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "opencode.json"
            path.write_text(
                json.dumps(
                    {
                        "model": "opencode/gpt-5.4",
                        "provider": {
                            "opencode": {
                                "options": {
                                    "baseURL": "http://127.0.0.1:9999",
                                }
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            path.with_name("opencode.json.modeio-route.json").write_text(
                json.dumps(
                    {
                        "providers": {
                            "opencode": {
                                "providerId": "opencode",
                                "originalBaseUrl": "http://127.0.0.1:9999",
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

            result = apply_opencode_config_file(
                config_path=path,
                gateway_base_url="http://127.0.0.1:8787/v1",
                create_if_missing=False,
                env={"HOME": temp_dir},
            )

        self.assertTrue(result["changed"])
        self.assertTrue(result["supported"])
        self.assertEqual(result["providerId"], "opencode")
        self.assertEqual(result["originalBaseUrl"], "http://127.0.0.1:9999")

    def test_apply_opencode_config_file_requires_active_provider(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "opencode.json"
            path.write_text(
                json.dumps({"provider": {"openai": {"options": {}}}}),
                encoding="utf-8",
            )

            result = apply_opencode_config_file(
                config_path=path,
                gateway_base_url="http://127.0.0.1:8787/v1",
                create_if_missing=False,
                env={"HOME": temp_dir},
            )

        self.assertFalse(result["changed"])
        self.assertFalse(result["supported"])
        self.assertEqual(result["reason"], "missing_active_provider")

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

    def test_apply_openclaw_provider_route_preserves_provider_context_by_default(self):
        source = build_openclaw_config(
            primary="openai/gpt-4.1",
            providers={
                "openai": build_openclaw_provider(
                    api="openai-completions",
                    base_url="https://api.openai.com/v1",
                )
            },
        )
        updated, changed = apply_openclaw_provider_route(
            source,
            "http://127.0.0.1:8787/v1",
        )
        self.assertTrue(changed)
        provider = updated["models"]["providers"]["openai"]
        self.assertEqual(
            provider["baseUrl"],
            "http://127.0.0.1:8787/clients/openclaw/openai/v1",
        )
        self.assertEqual(provider["api"], "openai-completions")
        self.assertEqual(
            updated["agents"]["defaults"]["model"]["primary"],
            "openai/gpt-4.1",
        )

    def test_apply_and_uninstall_openclaw_config_file(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "openclaw.json"
            path.write_text(
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
            apply_result = apply_openclaw_config_file(
                config_path=path,
                gateway_base_url="http://127.0.0.1:8787/v1",
                create_if_missing=False,
            )
            self.assertTrue(apply_result["changed"])
            self.assertTrue(path.exists())
            self.assertTrue(apply_result["supported"])
            self.assertEqual(apply_result["routeMode"], "preserve_provider")

            uninstall_result = uninstall_openclaw_config_file(
                config_path=path,
                gateway_base_url="http://127.0.0.1:8787/v1",
                force_remove=False,
            )
            self.assertTrue(uninstall_result["changed"])
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(
                payload["models"]["providers"]["openai"]["baseUrl"],
                "https://api.openai.com/v1",
            )

    def test_apply_and_uninstall_openclaw_models_cache_file(self):
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "openclaw.json"
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
            path = Path(temp_dir) / "agents" / "main" / "agent" / "models.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    build_openclaw_models_cache(
                        providers={
                            "openai": build_openclaw_provider(
                                api="openai-completions",
                                base_url="https://api.openai.com/v1",
                                models=[{"id": "gpt-4.1"}],
                            )
                        }
                    )
                ),
                encoding="utf-8",
            )
            apply_openclaw_config_file(
                config_path=config_path,
                gateway_base_url="http://127.0.0.1:8787/v1",
                create_if_missing=False,
            )
            apply_result = apply_openclaw_models_cache_file(
                models_cache_path=path,
                gateway_base_url="http://127.0.0.1:8787/v1",
                config_path=config_path,
            )
            self.assertTrue(apply_result["changed"])
            self.assertTrue(path.exists())

            uninstall_result = uninstall_openclaw_models_cache_file(
                models_cache_path=path,
                gateway_base_url="http://127.0.0.1:8787/v1",
                config_path=config_path,
                force_remove=False,
            )
            self.assertTrue(uninstall_result["changed"])
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["models"]["providers"], {})

    def test_apply_openclaw_provider_route_native_mode_preserves_provider_context(self):
        source = build_openclaw_config(
            primary="openai/gpt-4.1",
            providers={
                "openai": build_openclaw_provider(
                    api="openai-completions",
                    base_url="https://api.openai.com/v1",
                )
            },
        )
        updated, changed = apply_openclaw_provider_route(
            source,
            "http://127.0.0.1:8787/v1",
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
        self.assertNotIn("modeio-middleware", updated["models"]["providers"])

    def test_apply_openclaw_provider_route_native_mode_preserves_anthropic_provider_context(self):
        source = build_openclaw_config(
            primary="anthropic/claude-sonnet-4",
            providers={
                "anthropic": build_openclaw_provider(
                    api="anthropic-messages",
                    base_url="https://api.anthropic.com",
                )
            },
        )
        updated, changed = apply_openclaw_provider_route(
            source,
            "http://127.0.0.1:8787/v1",
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
            )
            second_apply = apply_openclaw_config_file(
                config_path=path,
                gateway_base_url="http://127.0.0.1:8787/v1",
                create_if_missing=False,
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
        )
        self.assertFalse(changed)
        self.assertEqual(updated, source)

    def test_apply_openclaw_config_file_does_not_create_empty_file_when_route_is_unsupported(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "openclaw.json"

            result = apply_openclaw_config_file(
                config_path=path,
                gateway_base_url="http://127.0.0.1:8787/v1",
                create_if_missing=True,
            )

        self.assertFalse(result["supported"])
        self.assertFalse(result["created"])
        self.assertFalse(path.exists())

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
        self.assertIn("no longer supported", payload["error"]["message"])

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
        self.assertIn("no longer supported", payload["error"]["message"])

    def test_main_json_openclaw_apply_uses_explicit_temp_path(self):
        with TemporaryDirectory() as temp_dir:
            openclaw_path = Path(temp_dir) / "openclaw.json"
            code, payload = self._run_main_json(
                [
                    "--apply-openclaw",
                    "--openclaw-config-path",
                    str(openclaw_path),
                ]
            )
            self.assertEqual(code, 1)
            self.assertFalse(payload["success"])
            self.assertIsNone(payload.get("openclaw"))
            self.assertFalse(openclaw_path.exists())
            self.assertIn("existing, working OpenClaw config", payload["error"]["message"])

    def test_main_json_doctor_reports_required_checks(self):
        with TemporaryDirectory() as temp_dir:
            auth_dir = Path(temp_dir) / ".codex"
            auth_dir.mkdir(parents=True)
            (auth_dir / "auth.json").write_text(
                '{"access_token":"test"}', encoding="utf-8"
            )

            with mock.patch.dict(
                os.environ,
                {"HOME": temp_dir},
                clear=False,
            ):
                code, payload = self._run_main_json(
                    [
                        "--doctor",
                        "--require-codex-auth",
                    ]
                )

        self.assertEqual(code, 0)
        self.assertTrue(payload["success"])
        self.assertEqual(payload["mode"], "doctor")
        self.assertTrue(payload["codex"]["authPresent"])
        self.assertIn("nativeClients", payload)
        self.assertIn("codex", payload["nativeClients"])
        self.assertNotIn("authorization", payload["nativeClients"]["codex"])
        self.assertNotIn("upstreamApiKey", payload)
        self.assertNotIn("liveUpstream", payload)
        self.assertGreaterEqual(len(payload["checks"]), 1)
        self.assertIn("routeSupport", payload["opencode"])
        self.assertIn("routeSupport", payload["openclaw"])

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

    def test_main_json_doctor_stays_independent_of_unrelated_provider_envs(self):
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
                    ]
                )
        self.assertEqual(code, 0)
        self.assertTrue(payload["success"])
        self.assertNotIn("upstreamApiKey", payload)
        self.assertNotIn("liveUpstream", payload)

    def test_main_json_doctor_validation_error_for_mutating_flags(self):
        code, payload = self._run_main_json(["--doctor", "--apply-opencode"])
        self.assertEqual(code, 2)
        self.assertFalse(payload["success"])
        self.assertEqual(payload["error"]["type"], "validation_error")

    def test_main_json_setup_fails_when_openclaw_route_is_unsupported(self):
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "openclaw.json"
            config_path.write_text("{}", encoding="utf-8")
            code, payload = self._run_main_json(
                [
                    "--apply-openclaw",
                    "--openclaw-config-path",
                    str(config_path),
                    "--openclaw-models-cache-path",
                    str(Path(temp_dir) / "models.json"),
                ]
            )

        self.assertEqual(code, 1)
        self.assertFalse(payload["success"])
        self.assertFalse(payload["openclaw"]["supported"])


if __name__ == "__main__":
    unittest.main()
