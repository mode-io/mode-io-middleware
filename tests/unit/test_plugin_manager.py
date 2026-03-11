#!/usr/bin/env python3

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
TESTS_DIR = REPO_ROOT / "tests"

sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, str(TESTS_DIR))

from modeio_middleware.core.contracts import ENDPOINT_CHAT_COMPLETIONS  # noqa: E402
from modeio_middleware.core.decision import HookDecision  # noqa: E402
from modeio_middleware.core.payload_codec import (  # noqa: E402
    normalize_request_payload,
    normalize_response_payload,
    normalize_stream_event_payload,
)
from modeio_middleware.core.plugin_manager import PluginManager  # noqa: E402
from modeio_middleware.core.services.telemetry import PluginTelemetry  # noqa: E402
from modeio_middleware.plugins.base import MiddlewarePlugin  # noqa: E402
from helpers.plugin_modules import register_plugin_module  # noqa: E402


class _ModifyPlugin(MiddlewarePlugin):
    name = "modify"

    def pre_request(self, hook_input):
        return {
            "action": "modify",
            "operations": [
                {
                    "op": "replace_text",
                    "target": "prompt",
                    "text": "rewritten prompt",
                }
            ],
        }

    def post_response(self, hook_input):
        return {
            "action": "modify",
            "operations": [
                {
                    "op": "append_text",
                    "target": "response",
                    "text": " [done]",
                }
            ],
        }

    def post_stream_event(self, hook_input):
        return {
            "action": "modify",
            "operations": [
                {
                    "op": "append_text",
                    "target": "response",
                    "text": "!",
                }
            ],
        }


class _ErrorPlugin(MiddlewarePlugin):
    name = "error"

    def pre_request(self, _hook_input):
        raise RuntimeError("boom")


class _BlockPlugin(MiddlewarePlugin):
    name = "block"

    def pre_request(self, _hook_input):
        return {"action": "block", "message": "blocked by test plugin"}


class _DecisionPlugin(MiddlewarePlugin):
    name = "decision"

    def pre_request(self, _hook_input):
        return HookDecision(
            action="warn",
            message="decision-based warning",
            findings=[{"class": "test_decision", "severity": "low", "confidence": 1.0, "reason": "ok", "evidence": []}],
        )


class _InvalidActionPlugin(MiddlewarePlugin):
    name = "invalid_action"

    def pre_request(self, _hook_input):
        return {"action": "defer", "message": "removed action"}


class _StubLease:
    def __init__(self, runtime):
        self.runtime = runtime
        self.released = False

    def release(self):
        self.released = True


class _StubRuntime:
    def invoke(self, _hook_name, _hook_input):
        return {"action": "pass"}


class _FailingRuntimeManager:
    def __init__(self):
        self.calls = 0
        self.first_lease = None

    def acquire(self, _spec):
        self.calls += 1
        if self.calls == 1:
            self.first_lease = _StubLease(_StubRuntime())
            return self.first_lease
        raise RuntimeError("runtime pool exhausted")

    def shutdown(self):
        return


class TestPluginManager(unittest.TestCase):
    def setUp(self):
        register_plugin_module("modeio_middleware.tests.plugins.modify", _ModifyPlugin)
        register_plugin_module("modeio_middleware.tests.plugins.error", _ErrorPlugin)
        register_plugin_module("modeio_middleware.tests.plugins.block", _BlockPlugin)
        register_plugin_module("modeio_middleware.tests.plugins.decision", _DecisionPlugin)
        register_plugin_module("modeio_middleware.tests.plugins.invalid_action", _InvalidActionPlugin)

    def _request_payload(self):
        body = {
            "model": "gpt-test",
            "messages": [{"role": "user", "content": "hello"}],
        }
        normalized = normalize_request_payload(
            endpoint_kind=ENDPOINT_CHAT_COMPLETIONS,
            source="openai_gateway",
            request_body=body,
            connector_context={},
        ).to_public_dict()
        return body, normalized, {"request_body": body}

    def _response_payload(self):
        body = {
            "id": "resp",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "original response"},
                    "finish_reason": "stop",
                }
            ],
        }
        normalized = normalize_response_payload(
            endpoint_kind=ENDPOINT_CHAT_COMPLETIONS,
            source="openai_gateway",
            response_body=body,
            connector_context={},
        ).to_public_dict()
        return body, normalized, {"response_body": body}

    def _stream_event_payload(self):
        event = {
            "data_type": "json",
            "payload": {
                "choices": [{"delta": {"content": "stream"}}],
            },
        }
        normalized = normalize_stream_event_payload(
            endpoint_kind=ENDPOINT_CHAT_COMPLETIONS,
            source="openai_gateway",
            event=event,
            request_context={},
        ).to_public_dict()
        return event, normalized, {"event": event}

    def test_resolve_active_plugins_enabled_order(self):
        manager = PluginManager(
            {
                "modify": {
                    "enabled": True,
                    "module": "modeio_middleware.tests.plugins.modify",
                },
                "error": {
                    "enabled": False,
                    "module": "modeio_middleware.tests.plugins.error",
                },
            }
        )

        active = manager.resolve_active_plugins(["modify", "error"], {})
        self.assertEqual([plugin.name for plugin in active], ["modify"])

    def test_apply_pre_request_modify(self):
        manager = PluginManager(
            {
                "modify": {
                    "enabled": True,
                    "module": "modeio_middleware.tests.plugins.modify",
                }
            }
        )
        active = manager.resolve_active_plugins(["modify"], {})
        request_body, normalized_payload, native_payload = self._request_payload()

        result = manager.apply_pre_request(
            active,
            request_id="req1",
            endpoint_kind=ENDPOINT_CHAT_COMPLETIONS,
            profile="dev",
            request_body=request_body,
            normalized_payload=normalized_payload,
            native_payload=native_payload,
            request_headers={},
            context={},
            shared_state={},
            on_plugin_error="warn",
        )

        self.assertFalse(result.blocked)
        self.assertEqual(result.body["messages"][0]["content"], "rewritten prompt")
        self.assertIn("modify:modify", result.actions)

    def test_resolve_active_plugins_reuses_runtime_instances(self):
        manager = PluginManager(
            {
                "modify": {
                    "enabled": True,
                    "module": "modeio_middleware.tests.plugins.modify",
                }
            }
        )

        first_active = manager.resolve_active_plugins(["modify"], {})
        manager.shutdown_active_plugins(first_active)
        second_active = manager.resolve_active_plugins(["modify"], {})

        self.assertIs(first_active[0].runtime, second_active[0].runtime)

    def test_resolve_active_plugins_releases_prior_leases_when_later_acquire_fails(self):
        runtime_manager = _FailingRuntimeManager()
        manager = PluginManager(
            {
                "modify": {
                    "enabled": True,
                    "module": "modeio_middleware.tests.plugins.modify",
                },
                "block": {
                    "enabled": True,
                    "module": "modeio_middleware.tests.plugins.block",
                },
            },
            runtime_manager=runtime_manager,
        )

        with self.assertRaisesRegex(RuntimeError, "runtime pool exhausted"):
            manager.resolve_active_plugins(["modify", "block"], {})

        self.assertIsNotNone(runtime_manager.first_lease)
        self.assertTrue(runtime_manager.first_lease.released)

    def test_apply_pre_request_downgrades_modify_when_connector_disallows_patch(self):
        manager = PluginManager(
            {
                "modify": {
                    "enabled": True,
                    "module": "modeio_middleware.tests.plugins.modify",
                }
            }
        )
        active = manager.resolve_active_plugins(["modify"], {})
        request_body, normalized_payload, native_payload = self._request_payload()

        result = manager.apply_pre_request(
            active,
            request_id="req1",
            endpoint_kind=ENDPOINT_CHAT_COMPLETIONS,
            profile="dev",
            request_body=request_body,
            normalized_payload=normalized_payload,
            native_payload=native_payload,
            request_headers={},
            context={},
            shared_state={},
            on_plugin_error="warn",
            connector_capabilities={
                "can_patch": False,
                "can_block": True,
            },
        )

        self.assertFalse(result.blocked)
        self.assertEqual(result.body["messages"][0]["content"], "hello")
        self.assertIn("modify:warn", result.actions)

    def test_apply_pre_request_error_fail_safe_blocks(self):
        manager = PluginManager(
            {
                "error": {
                    "enabled": True,
                    "module": "modeio_middleware.tests.plugins.error",
                }
            }
        )
        active = manager.resolve_active_plugins(["error"], {})
        request_body, normalized_payload, native_payload = self._request_payload()

        result = manager.apply_pre_request(
            active,
            request_id="req1",
            endpoint_kind=ENDPOINT_CHAT_COMPLETIONS,
            profile="prod",
            request_body=request_body,
            normalized_payload=normalized_payload,
            native_payload=native_payload,
            request_headers={},
            context={},
            shared_state={},
            on_plugin_error="fail_safe",
        )

        self.assertTrue(result.blocked)
        self.assertIn("plugin 'error' failed", result.block_message)

    def test_apply_pre_request_block_action(self):
        manager = PluginManager(
            {
                "block": {
                    "enabled": True,
                    "module": "modeio_middleware.tests.plugins.block",
                }
            }
        )
        active = manager.resolve_active_plugins(["block"], {})
        request_body, normalized_payload, native_payload = self._request_payload()

        result = manager.apply_pre_request(
            active,
            request_id="req1",
            endpoint_kind=ENDPOINT_CHAT_COMPLETIONS,
            profile="dev",
            request_body=request_body,
            normalized_payload=normalized_payload,
            native_payload=native_payload,
            request_headers={},
            context={},
            shared_state={},
            on_plugin_error="warn",
        )
        self.assertTrue(result.blocked)
        self.assertEqual(result.block_message, "blocked by test plugin")

    def test_apply_post_response_modify(self):
        manager = PluginManager(
            {
                "modify": {
                    "enabled": True,
                    "module": "modeio_middleware.tests.plugins.modify",
                }
            }
        )
        active = manager.resolve_active_plugins(["modify"], {})
        response_body, normalized_payload, native_payload = self._response_payload()

        result = manager.apply_post_response(
            active,
            request_id="req1",
            endpoint_kind=ENDPOINT_CHAT_COMPLETIONS,
            profile="dev",
            request_context={},
            response_body=response_body,
            normalized_payload=normalized_payload,
            native_payload=native_payload,
            response_headers={},
            shared_state={},
            on_plugin_error="warn",
        )
        self.assertFalse(result.blocked)
        self.assertEqual(
            result.body["choices"][0]["message"]["content"],
            "original response [done]",
        )
        self.assertIn("modify:modify", result.actions)

    def test_apply_post_stream_event_modify(self):
        manager = PluginManager(
            {
                "modify": {
                    "enabled": True,
                    "module": "modeio_middleware.tests.plugins.modify",
                }
            }
        )
        active = manager.resolve_active_plugins(["modify"], {})
        event, normalized_payload, native_payload = self._stream_event_payload()

        result = manager.apply_post_stream_event(
            active,
            request_id="req1",
            endpoint_kind=ENDPOINT_CHAT_COMPLETIONS,
            profile="dev",
            request_context={},
            event=event,
            normalized_payload=normalized_payload,
            native_payload=native_payload,
            shared_state={},
            on_plugin_error="warn",
        )

        self.assertFalse(result.blocked)
        self.assertEqual(
            result.event["payload"]["choices"][0]["delta"]["content"], "stream!"
        )
        self.assertIn("modify:modify", result.actions)

    def test_apply_pre_request_accepts_hookdecision_payload(self):
        manager = PluginManager(
            {
                "decision": {
                    "enabled": True,
                    "module": "modeio_middleware.tests.plugins.decision",
                }
            }
        )
        active = manager.resolve_active_plugins(["decision"], {})
        request_body, normalized_payload, native_payload = self._request_payload()

        result = manager.apply_pre_request(
            active,
            request_id="req1",
            endpoint_kind=ENDPOINT_CHAT_COMPLETIONS,
            profile="dev",
            request_body=request_body,
            normalized_payload=normalized_payload,
            native_payload=native_payload,
            request_headers={},
            context={},
            shared_state={},
            on_plugin_error="warn",
        )

        self.assertFalse(result.blocked)
        self.assertIn("decision:warn", result.actions)
        self.assertEqual(result.findings[0]["class"], "test_decision")

    def test_apply_pre_request_records_telemetry(self):
        manager = PluginManager(
            {
                "modify": {
                    "enabled": True,
                    "module": "modeio_middleware.tests.plugins.modify",
                }
            }
        )
        active = manager.resolve_active_plugins(["modify"], {})
        telemetry = PluginTelemetry()
        request_body, normalized_payload, native_payload = self._request_payload()

        result = manager.apply_pre_request(
            active,
            request_id="req1",
            endpoint_kind=ENDPOINT_CHAT_COMPLETIONS,
            profile="dev",
            request_body=request_body,
            normalized_payload=normalized_payload,
            native_payload=native_payload,
            request_headers={},
            context={},
            shared_state={},
            on_plugin_error="warn",
            services={"telemetry": telemetry},
        )

        self.assertFalse(result.blocked)
        snapshot = telemetry.snapshot()
        self.assertEqual(snapshot["modify"]["calls"], 1)
        self.assertEqual(snapshot["modify"]["hooks"]["pre_request"], 1)

    def test_apply_pre_request_rejects_removed_defer_action(self):
        manager = PluginManager(
            {
                "defer": {
                    "enabled": True,
                    "module": "modeio_middleware.tests.plugins.invalid_action",
                }
            }
        )
        active = manager.resolve_active_plugins(["defer"], {})
        request_body, normalized_payload, native_payload = self._request_payload()

        result = manager.apply_pre_request(
            active,
            request_id="req1",
            endpoint_kind=ENDPOINT_CHAT_COMPLETIONS,
            profile="dev",
            request_body=request_body,
            normalized_payload=normalized_payload,
            native_payload=native_payload,
            request_headers={},
            context={},
            shared_state={},
            on_plugin_error="warn",
            services={},
        )

        self.assertFalse(result.blocked)
        self.assertIn("defer:error", result.actions)
        self.assertIn("plugin_error:defer", result.degraded)


if __name__ == "__main__":
    unittest.main()
