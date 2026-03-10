#!/usr/bin/env python3

import json
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from modeio_middleware.connectors.client_identity import (  # noqa: E402
    CLIENT_CODEX,
    CLIENT_OPENCODE,
    CLIENT_OPENCLAW,
)
from modeio_middleware.core.client_auth import (  # noqa: E402
    inspect_codex_native_auth,
    inspect_opencode_native_auth,
    inspect_openclaw_native_auth,
    resolve_client_upstream_authorization,
)
from modeio_middleware.core.provider_auth import (  # noqa: E402
    CredentialResolver,
    CredentialHealthStore,
    OpenClawSelectionResolver,
    PROVIDER_OPENAI_CODEX,
)


class TestClientAuth(unittest.TestCase):
    def test_resolver_defaults_codex_to_openai_codex_provider(self):
        resolver = CredentialResolver()
        provider_id = resolver.resolve_provider_id(client_name=CLIENT_CODEX)
        self.assertEqual(provider_id, PROVIDER_OPENAI_CODEX)

    def test_codex_bridge_uses_access_token_from_auth_store(self):
        with TemporaryDirectory() as temp_dir:
            auth_path = Path(temp_dir) / ".codex" / "auth.json"
            auth_path.parent.mkdir(parents=True)
            auth_path.write_text(
                json.dumps({"tokens": {"access_token": "eyJhbGciOi-codex"}}),
                encoding="utf-8",
            )

            with mock.patch.dict(os.environ, {"HOME": temp_dir}, clear=False):
                authorization = resolve_client_upstream_authorization(
                    {},
                    client_name=CLIENT_CODEX,
                )

        self.assertEqual(authorization, "Bearer eyJhbGciOi-codex")

    def test_codex_bridge_falls_back_to_openclaw_profile_when_codex_store_missing(self):
        with TemporaryDirectory() as temp_dir:
            agent_dir = Path(temp_dir) / ".openclaw" / "agents" / "main" / "agent"
            agent_dir.mkdir(parents=True)
            (agent_dir / "auth-profiles.json").write_text(
                json.dumps(
                    {
                        "profiles": {
                            "openai-codex:default": {
                                "provider": "openai-codex",
                                "access": "eyJhbGciOi-openclaw",
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch.dict(os.environ, {"HOME": temp_dir}, clear=False):
                authorization = resolve_client_upstream_authorization(
                    {},
                    client_name=CLIENT_CODEX,
                )

        self.assertEqual(authorization, "Bearer eyJhbGciOi-openclaw")

    def test_codex_inspection_strips_authorization_from_public_payload(self):
        with TemporaryDirectory() as temp_dir:
            auth_path = Path(temp_dir) / ".codex" / "auth.json"
            auth_path.parent.mkdir(parents=True)
            auth_path.write_text(
                json.dumps({"tokens": {"access_token": "eyJhbGciOi-codex"}}),
                encoding="utf-8",
            )

            with mock.patch.dict(os.environ, {"HOME": temp_dir}, clear=False):
                inspection = inspect_codex_native_auth()

        self.assertTrue(inspection["ready"])
        self.assertEqual(inspection["providerId"], "openai-codex")
        self.assertEqual(inspection["transport"], "codex_native")
        self.assertEqual(inspection["fallbackMode"], "managed_upstream")
        self.assertNotIn("authorization", inspection)

    def test_openclaw_bridge_overrides_placeholder_auth(self):
        with TemporaryDirectory() as temp_dir:
            agent_dir = Path(temp_dir) / ".openclaw" / "agents" / "main" / "agent"
            agent_dir.mkdir(parents=True)
            (agent_dir / "auth-profiles.json").write_text(
                json.dumps(
                    {
                        "profiles": {
                            "openai-codex:default": {
                                "provider": "openai-codex",
                                "access": "eyJhbGciOi-openclaw",
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            with mock.patch.dict(os.environ, {"HOME": temp_dir}, clear=False):
                authorization = resolve_client_upstream_authorization(
                    {"Authorization": "Bearer modeio-middleware"},
                    client_name=CLIENT_OPENCLAW,
                    client_provider_name="openai-codex",
                )

        self.assertEqual(authorization, "Bearer eyJhbGciOi-openclaw")

    def test_opencode_bridge_uses_configured_openai_api_key(self):
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / ".config" / "opencode" / "opencode.json"
            config_path.parent.mkdir(parents=True)
            config_path.write_text(
                json.dumps(
                    {
                        "model": "openai/gpt-4o-mini",
                        "provider": {
                            "openai": {
                                "options": {
                                    "apiKey": "sk-opencode-test",
                                }
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            with mock.patch.dict(os.environ, {"HOME": temp_dir}, clear=False):
                authorization = resolve_client_upstream_authorization(
                    {},
                    client_name=CLIENT_OPENCODE,
                )

        self.assertEqual(authorization, "Bearer sk-opencode-test")

    def test_opencode_bridge_uses_provider_env_candidate(self):
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / ".config" / "opencode" / "opencode.json"
            config_path.parent.mkdir(parents=True)
            config_path.write_text(
                json.dumps(
                    {
                        "model": "opencode/gpt-5.4",
                        "provider": {
                            "opencode": {
                                "options": {}
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            cache_path = Path(temp_dir) / ".cache" / "opencode" / "models.json"
            cache_path.parent.mkdir(parents=True)
            cache_path.write_text(
                json.dumps(
                    {
                        "opencode": {
                            "env": ["OPENCODE_API_KEY"],
                        }
                    }
                ),
                encoding="utf-8",
            )

            with mock.patch.dict(
                os.environ,
                {
                    "HOME": temp_dir,
                    "OPENCODE_API_KEY": "sk-opencode-provider",
                },
                clear=False,
            ):
                authorization = resolve_client_upstream_authorization(
                    {},
                    client_name=CLIENT_OPENCODE,
                    client_provider_name="opencode",
                )

        self.assertEqual(authorization, "Bearer sk-opencode-provider")

    def test_opencode_inspection_uses_provider_env_candidate(self):
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / ".config" / "opencode" / "opencode.json"
            config_path.parent.mkdir(parents=True)
            config_path.write_text(
                json.dumps(
                    {
                        "model": "opencode/gpt-5.4",
                        "provider": {
                            "opencode": {
                                "options": {}
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            cache_path = Path(temp_dir) / ".cache" / "opencode" / "models.json"
            cache_path.parent.mkdir(parents=True)
            cache_path.write_text(
                json.dumps({"opencode": {"env": ["OPENCODE_API_KEY"]}}),
                encoding="utf-8",
            )

            with mock.patch.dict(
                os.environ,
                {"HOME": temp_dir, "OPENCODE_API_KEY": "sk-opencode-provider"},
                clear=False,
            ):
                inspection = inspect_opencode_native_auth("opencode")

        self.assertTrue(inspection["ready"])
        self.assertEqual(inspection["providerId"], "opencode")
        self.assertEqual(inspection["authEnv"], "OPENCODE_API_KEY")
        self.assertEqual(inspection["transport"], "openai_compat")
        self.assertNotIn("authorization", inspection)

    def test_opencode_openai_inspection_can_reuse_codex_auth(self):
        with TemporaryDirectory() as temp_dir:
            auth_path = Path(temp_dir) / ".codex" / "auth.json"
            auth_path.parent.mkdir(parents=True)
            auth_path.write_text(
                json.dumps({"tokens": {"access_token": "eyJhbGciOi-codex"}}),
                encoding="utf-8",
            )
            config_path = Path(temp_dir) / ".config" / "opencode" / "opencode.json"
            config_path.parent.mkdir(parents=True)
            config_path.write_text(
                json.dumps(
                    {
                        "model": "openai/gpt-5.4",
                        "provider": {
                            "openai": {
                                "options": {
                                    "baseURL": "http://127.0.0.1:1234/v1",
                                    "apiKey": "modeio-middleware",
                                }
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            with mock.patch.dict(os.environ, {"HOME": temp_dir}, clear=False):
                inspection = inspect_opencode_native_auth("openai")

        self.assertTrue(inspection["ready"])
        self.assertFalse(inspection["guaranteed"])
        self.assertEqual(inspection["strategy"], "shared-codex-oauth")
        self.assertEqual(inspection["transport"], "codex_native")

    def test_openclaw_inspection_uses_profile_store(self):
        with TemporaryDirectory() as temp_dir:
            agent_dir = Path(temp_dir) / ".openclaw" / "agents" / "main" / "agent"
            agent_dir.mkdir(parents=True)
            (agent_dir / "auth-profiles.json").write_text(
                json.dumps(
                    {
                        "profiles": {
                            "openai-codex:default": {
                                "provider": "openai-codex",
                                "access": "eyJhbGciOi-openclaw",
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            with mock.patch.dict(os.environ, {"HOME": temp_dir}, clear=False):
                inspection = inspect_openclaw_native_auth("openai-codex")

        self.assertTrue(inspection["ready"])
        self.assertEqual(inspection["providerId"], "openai-codex")
        self.assertEqual(inspection["strategy"], "auth-profile")
        self.assertEqual(inspection["transport"], "openai_compat")
        self.assertNotIn("authorization", inspection)

    def test_openclaw_selection_resolver_skips_profile_in_cooldown(self):
        health = CredentialHealthStore()
        resolver = OpenClawSelectionResolver(health)
        with TemporaryDirectory() as temp_dir:
            agent_dir = Path(temp_dir) / ".openclaw" / "agents" / "main" / "agent"
            agent_dir.mkdir(parents=True)
            (agent_dir / "auth-profiles.json").write_text(
                json.dumps(
                    {
                        "profiles": {
                            "openai-codex:default": {
                                "provider": "openai-codex",
                                "access": "token-a",
                            },
                            "openai-codex:backup": {
                                "provider": "openai-codex",
                                "access": "token-b",
                            },
                        }
                    }
                ),
                encoding="utf-8",
            )
            health.mark_cooldown(
                provider_id="openai-codex",
                profile_id="openai-codex:default",
                reason="rate_limited",
                cooldown_seconds=60,
            )
            selection = resolver.resolve(
                env={"HOME": temp_dir},
                provider_id="openai-codex",
            )

        self.assertEqual(selection.profile_id, "openai-codex:backup")

    def test_openclaw_selection_resolver_falls_back_to_configured_provider(self):
        health = CredentialHealthStore()
        resolver = OpenClawSelectionResolver(health)
        with TemporaryDirectory() as temp_dir:
            agent_dir = Path(temp_dir) / ".openclaw" / "agents" / "main" / "agent"
            agent_dir.mkdir(parents=True)
            (agent_dir / "auth-profiles.json").write_text(
                json.dumps(
                    {
                        "profiles": {
                            "openai-codex:default": {
                                "provider": "openai-codex",
                                "access": "token-a",
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            (agent_dir / "models.json").write_text(
                json.dumps(
                    {
                        "providers": {
                            "zenmux": {
                                "baseUrl": "https://zenmux.ai/api/v1",
                                "apiKey": "sk-zenmux",
                                "models": [{"id": "openai/gpt-5.3-codex"}],
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            health.mark_cooldown(
                provider_id="openai-codex",
                profile_id="openai-codex:default",
                reason="rate_limited",
                cooldown_seconds=60,
            )
            selection = resolver.resolve(
                env={"HOME": temp_dir},
                provider_id="openai-codex",
            )

        self.assertEqual(selection.provider_id, "zenmux")
        self.assertTrue(selection.reason.startswith("fallback_provider:"))

    def test_openclaw_inspection_refreshes_expired_openai_codex_profile(self):
        with TemporaryDirectory() as temp_dir:
            agent_dir = Path(temp_dir) / ".openclaw" / "agents" / "main" / "agent"
            agent_dir.mkdir(parents=True)
            auth_path = agent_dir / "auth-profiles.json"
            auth_path.write_text(
                json.dumps(
                    {
                        "profiles": {
                            "openai-codex:default": {
                                "provider": "openai-codex",
                                "access": "old-token",
                                "refresh": "refresh-token",
                                "expires": 1,
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch(
                "modeio_middleware.core.provider_auth._refresh_openai_codex_oauth",
                return_value={
                    "access": "new-token",
                    "refresh": "new-refresh",
                    "expires": 9999999999999,
                    "accountId": "acct-123",
                },
            ):
                with mock.patch.dict(os.environ, {"HOME": temp_dir}, clear=False):
                    inspection = inspect_openclaw_native_auth("openai-codex")

            stored = json.loads(auth_path.read_text(encoding="utf-8"))

        self.assertTrue(inspection["ready"])
        self.assertEqual(inspection["selectedProfileId"], "openai-codex:default")
        self.assertEqual(stored["profiles"]["openai-codex:default"]["access"], "new-token")
        self.assertEqual(stored["profiles"]["openai-codex:default"]["refresh"], "new-refresh")


if __name__ == "__main__":
    unittest.main()
