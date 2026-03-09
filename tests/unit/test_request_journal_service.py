#!/usr/bin/env python3

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT
sys.path.insert(0, str(PACKAGE_DIR))

from modeio_middleware.core.observability.models import RequestJournalConfig  # noqa: E402
from modeio_middleware.core.observability.service import RequestJournalService  # noqa: E402


class TestRequestJournalService(unittest.TestCase):
    def _service(self) -> RequestJournalService:
        return RequestJournalService(
            config=RequestJournalConfig(
                enabled=True,
                max_records=10,
                capture_bodies=True,
                max_body_chars=200,
                sample_diff_paths=10,
                live_queue_size=10,
            )
        )

    def test_records_completed_request_with_change_summary(self):
        service = self._service()
        service.start_request(
            request_id="req-1",
            source="openai_gateway",
            client_name="codex",
            source_event="http_request",
            endpoint_kind="chat_completions",
            phase="request",
            profile="dev",
            stream=False,
            request_body={"messages": [{"content": "hello"}], "api_key": "secret"},
        )
        service.record_pre_result(
            request_id="req-1",
            effective_request_body={
                "messages": [{"content": "hello world"}],
                "api_key": "secret",
            },
            pre_actions=["inject_context:modify"],
            degraded=[],
            findings=[],
            blocked=False,
            block_message=None,
        )
        service.mark_upstream_start(request_id="req-1")
        service.record_upstream_result(
            request_id="req-1", response_body={"output_text": "ok"}
        )
        service.record_post_result(
            request_id="req-1",
            effective_response_body={"output_text": "patched"},
            post_actions=["decorate:modify"],
            degraded=[],
            findings=[{"reason": "patched"}],
            blocked=False,
            block_message=None,
        )
        service.record_hook_execution(
            request_id="req-1",
            plugin_name="inject_context",
            hook_name="pre_request",
            effective_action="modify",
            duration_ms=5.0,
            errored=False,
            reported_action="modify",
        )
        service.finish_success(request_id="req-1")

        record = service.get_record("req-1")
        self.assertIsNotNone(record)
        self.assertEqual(record.status, "completed")
        self.assertEqual(record.client_name, "codex")
        self.assertEqual(record.impact.category, "modified")
        self.assertEqual(record.impact.primary_plugin, "inject_context")
        self.assertEqual(service.stats_snapshot()["byLifecycle"]["pre_and_post"], 1)
        self.assertTrue(record.request_change.changed)
        self.assertTrue(record.response_change.changed)
        self.assertEqual(record.original_request_body["api_key"], "***")
        self.assertEqual(record.hook_executions[0].plugin_name, "inject_context")
        self.assertEqual(service.stats_snapshot()["byAction"]["modify"], 1)

    def test_records_blocked_error_as_blocked_status(self):
        service = self._service()
        service.start_request(
            request_id="req-2",
            source="openai_gateway",
            client_name="opencode",
            source_event="http_request",
            endpoint_kind="chat_completions",
            phase="request",
            profile="dev",
            stream=False,
            request_body={"messages": [{"content": "hello"}]},
        )
        service.record_pre_result(
            request_id="req-2",
            effective_request_body={"messages": [{"content": "hello"}]},
            pre_actions=["blocker:block"],
            degraded=[],
            findings=[],
            blocked=True,
            block_message="blocked by plugin",
        )
        service.record_hook_execution(
            request_id="req-2",
            plugin_name="blocker",
            hook_name="pre_request",
            effective_action="block",
            duration_ms=3.0,
            errored=False,
            reported_action="block",
        )
        service.finish_error(
            request_id="req-2",
            error_code="MODEIO_PLUGIN_BLOCKED",
            error_message="blocked by plugin",
            blocked=True,
            block_message="blocked by plugin",
        )

        record = service.get_record("req-2")
        self.assertIsNotNone(record)
        self.assertEqual(record.status, "blocked")
        self.assertTrue(record.blocked)
        self.assertEqual(record.error_code, "MODEIO_PLUGIN_BLOCKED")
        self.assertEqual(record.impact.category, "blocked")
        self.assertEqual(service.stats_snapshot()["byLifecycle"]["pre_request"], 1)

    def test_marks_stream_completion(self):
        service = self._service()
        service.start_request(
            request_id="req-3",
            source="openai_gateway",
            client_name="unknown",
            source_event="http_request",
            endpoint_kind="chat_completions",
            phase="request",
            profile="dev",
            stream=True,
            request_body={"messages": [{"content": "stream me"}]},
        )
        service.record_pre_result(
            request_id="req-3",
            effective_request_body={"messages": [{"content": "stream me"}]},
            pre_actions=[],
            degraded=[],
            findings=[],
            blocked=False,
            block_message=None,
        )
        service.mark_upstream_start(request_id="req-3")
        service.record_upstream_result(request_id="req-3", response_body=None)
        service.record_post_result(
            request_id="req-3",
            effective_response_body=None,
            post_actions=["stream"],
            degraded=[],
            findings=[],
            blocked=False,
            block_message=None,
        )
        service.record_stream_event(request_id="req-3")
        service.record_stream_event(request_id="req-3", done_received=True)
        service.finish_success(request_id="req-3")

        record = service.get_record("req-3")
        self.assertIsNotNone(record)
        self.assertEqual(record.status, "stream_completed")
        self.assertEqual(record.impact.category, "pass_through")
        self.assertEqual(service.stats_snapshot()["byLifecycle"]["none"], 1)
        self.assertEqual(record.stream_summary.event_count, 2)
        self.assertTrue(record.stream_summary.done_received)


if __name__ == "__main__":
    unittest.main()
