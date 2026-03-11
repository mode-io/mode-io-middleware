#!/usr/bin/env python3

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from modeio_middleware.core.provider_policy import (  # noqa: E402
    default_provider_family,
    build_client_gateway_base_url,
    openclaw_provider_gateway_base_url,
    resolve_provider_family_spec,
    resolve_openclaw_route_policy,
    resolve_opencode_route_policy,
    supported_provider_families_for_client,
)


class TestProviderPolicy(unittest.TestCase):
    def test_build_client_gateway_base_url_normalizes_v1_suffix(self):
        self.assertEqual(
            build_client_gateway_base_url(
                "http://127.0.0.1:8787/v1",
                "opencode",
                provider_name="openai",
            ),
            "http://127.0.0.1:8787/clients/opencode/openai/v1",
        )

    def test_openclaw_anthropic_gateway_base_url_omits_trailing_v1(self):
        self.assertEqual(
            openclaw_provider_gateway_base_url(
                "http://127.0.0.1:8787/v1",
                provider_key="anthropic",
                api_family="anthropic-messages",
            ),
            "http://127.0.0.1:8787/clients/openclaw/anthropic",
        )

    def test_provider_family_registry_exposes_client_support_matrix(self):
        family = resolve_provider_family_spec("openai-codex-responses")
        self.assertIsNotNone(family)
        self.assertEqual(family.transport_kind, "codex_native")
        self.assertFalse(family.openclaw_supported)
        self.assertEqual(
            supported_provider_families_for_client("openclaw"),
            ("anthropic-messages", "openai-completions"),
        )

    def test_resolve_opencode_route_policy_rejects_builtin_openai_oauth(self):
        policy = resolve_opencode_route_policy(
            config={"model": "openai/gpt-5.4", "provider": {"openai": {}}},
            auth_store={"openai": {"type": "oauth"}},
            default_upstream_base_url="https://api.openai.com/v1",
        )
        self.assertFalse(policy.supported)
        self.assertEqual(policy.reason, "provider_uses_internal_oauth_transport")
        self.assertEqual(policy.api_family, "openai-completions")
        self.assertEqual(policy.transport_kind, "openai_compat")
        self.assertEqual(policy.upstream_base_url, "https://api.openai.com/v1")

    def test_resolve_opencode_route_policy_accepts_redirectable_provider(self):
        policy = resolve_opencode_route_policy(
            config={
                "model": "zenmux/gpt-5.4",
                "provider": {
                    "zenmux": {
                        "options": {
                            "baseURL": "https://api.zenmux.example/v1",
                        }
                    }
                },
            },
            auth_store={"zenmux": {"type": "api-key"}},
            default_upstream_base_url=None,
        )
        self.assertTrue(policy.supported)
        self.assertIsNone(policy.reason)
        self.assertEqual(policy.api_family, "openai-completions")
        self.assertEqual(policy.transport_kind, "openai_compat")
        self.assertEqual(policy.upstream_base_url, "https://api.zenmux.example/v1")

    def test_default_provider_family_handles_known_native_provider_ids(self):
        self.assertEqual(default_provider_family("anthropic"), "anthropic-messages")
        self.assertEqual(default_provider_family("openai-codex"), "openai-codex-responses")
        self.assertEqual(default_provider_family("zenmux"), "openai-completions")

    def test_resolve_openclaw_route_policy_requires_exact_api_family(self):
        policy = resolve_openclaw_route_policy(
            config={
                "agents": {"defaults": {"model": {"primary": "openai/gpt-4.1"}}},
                "models": {
                    "providers": {
                        "openai": {
                            "baseUrl": "https://api.openai.com/v1",
                        }
                    }
                },
            },
            gateway_base_url="http://127.0.0.1:8787/v1",
            models_cache_data=None,
            route_metadata=None,
        )
        self.assertFalse(policy.supported)
        self.assertEqual(policy.reason, "missing_api_family")

    def test_resolve_openclaw_route_policy_preserves_exact_family(self):
        policy = resolve_openclaw_route_policy(
            config={
                "agents": {"defaults": {"model": {"primary": "anthropic/claude-sonnet-4-6"}}},
                "models": {
                    "providers": {
                        "anthropic": {
                            "api": "anthropic-messages",
                            "baseUrl": "https://api.anthropic.com",
                        }
                    }
                },
            },
            gateway_base_url="http://127.0.0.1:8787/v1",
            models_cache_data=None,
            route_metadata=None,
        )
        self.assertTrue(policy.supported)
        self.assertEqual(policy.api_family, "anthropic-messages")
        self.assertEqual(
            policy.route_base_url,
            "http://127.0.0.1:8787/clients/openclaw/anthropic",
        )
        self.assertEqual(policy.upstream_base_url, "https://api.anthropic.com")

    def test_resolve_openclaw_route_policy_rejects_deferred_family_from_registry(self):
        policy = resolve_openclaw_route_policy(
            config={
                "agents": {"defaults": {"model": {"primary": "openai-codex/gpt-5.3-codex"}}},
                "models": {
                    "providers": {
                        "openai-codex": {
                            "api": "openai-codex-responses",
                            "baseUrl": "https://chatgpt.com/backend-api/codex",
                        }
                    }
                },
            },
            gateway_base_url="http://127.0.0.1:8787/v1",
            models_cache_data=None,
            route_metadata=None,
        )
        self.assertFalse(policy.supported)
        self.assertEqual(policy.reason, "unsupported_api_family:openai-codex-responses")


if __name__ == "__main__":
    unittest.main()
