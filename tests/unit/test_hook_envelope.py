#!/usr/bin/env python3

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = REPO_ROOT
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from modeio_middleware.core.hook_envelope import HookEnvelope  # noqa: E402


class TestHookEnvelope(unittest.TestCase):
    def test_inprocess_payload_keeps_internal_state_and_service_fields(self):
        shared_state = {"policy": {"count": 1}}
        plugin_state = {"count": 1}
        envelope = HookEnvelope(
            request_id="req-1",
            endpoint_kind="chat_completions",
            profile="dev",
            plugin_config={"enabled": True},
            shared_state=shared_state,
            plugin_state=plugin_state,
            services={"telemetry": object()},
            context={"source": "http"},
            payload={"phase": "request", "timeline": []},
            native={"request_body": {"model": "gpt-test"}},
        )

        payload = envelope.to_inprocess_input()

        self.assertIs(payload["state"], shared_state)
        self.assertIs(payload["plugin_state"], plugin_state)
        self.assertIn("services", payload)
        self.assertEqual(payload["context"]["source"], "http")
        self.assertEqual(payload["request_context"]["source"], "http")
        self.assertEqual(payload["native"]["request_body"]["model"], "gpt-test")

    def test_protocol_payload_strips_internal_only_fields(self):
        envelope = HookEnvelope(
            request_id="req-2",
            endpoint_kind="responses",
            profile="prod",
            plugin_config={"enabled": True},
            shared_state={"policy": {"count": 2}},
            plugin_state={"count": 2},
            services={"telemetry": object()},
            request_context={"source": "claude_hooks", "source_event": "Stop"},
            payload={"phase": "response", "timeline": []},
            native={"response_body": {"assistant_response": "ok"}},
            response_headers={"x-request-id": "abc"},
            source="claude_hooks",
            source_event="Stop",
        )

        payload = envelope.to_protocol_input()

        self.assertNotIn("state", payload)
        self.assertNotIn("services", payload)
        self.assertEqual(payload["plugin_state"]["count"], 2)
        self.assertEqual(payload["request_context"]["source"], "claude_hooks")
        self.assertEqual(payload["source_event"], "Stop")
        self.assertIn("payload", payload)
        self.assertIn("native", payload)


if __name__ == "__main__":
    unittest.main()
