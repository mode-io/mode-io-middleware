#!/usr/bin/env python3

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
TESTS_DIR = REPO_ROOT / "tests"

sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, str(TESTS_DIR))

from helpers.gateway_harness import (
    completion_payload,
    http_get_json,
    http_get_text,
    post_json,
    start_gateway_pair,
)  # noqa: E402
from helpers.plugin_modules import register_plugin_module  # noqa: E402
from modeio_middleware.plugins.base import MiddlewarePlugin  # noqa: E402

AUTH_HEADERS = {"Authorization": "Bearer smoke-key"}


class _ModifyBothPlugin(MiddlewarePlugin):
    name = "modify_both"

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
                    "op": "replace_text",
                    "target": "response",
                    "text": "rewritten response",
                }
            ],
        }


class _BlockPlugin(MiddlewarePlugin):
    name = "blocker"

    def pre_request(self, _hook_input):
        return {"action": "block", "message": "blocked for testing"}


def _register_modify_plugin(module_name: str):
    register_plugin_module(module_name, _ModifyBothPlugin)


def _register_block_plugin(module_name: str):
    register_plugin_module(module_name, _BlockPlugin)


class TestMonitoringApi(unittest.TestCase):
    def test_dashboard_page_and_assets_are_served(self):
        upstream, gateway_stub = start_gateway_pair(
            lambda _path, payload: completion_payload(payload["messages"][0]["content"])
        )
        try:
            status, headers, html = http_get_text(
                gateway_stub.base_url,
                "/modeio/dashboard",
            )
            self.assertEqual(status, 200)
            self.assertEqual(headers.get_content_type(), "text/html")
            self.assertIn("ModeIO Monitor", html)
            self.assertIn("/modeio/dashboard/assets/dashboard.js", html)
            self.assertIn("/modeio/dashboard/assets/favicon.svg", html)

            status, headers, javascript = http_get_text(
                gateway_stub.base_url,
                "/modeio/dashboard/assets/dashboard.js",
            )
            self.assertEqual(status, 200)
            self.assertIn("javascript", headers.get_content_type())
            self.assertIn("/modeio/api/v1/events", javascript)

            status, headers, favicon = http_get_text(
                gateway_stub.base_url,
                "/favicon.ico",
            )
            self.assertEqual(status, 200)
            self.assertEqual(headers.get_content_type(), "image/svg+xml")
            self.assertIn("<svg", favicon)
        finally:
            gateway_stub.stop()
            upstream.stop()

    def test_events_and_stats_capture_completed_request(self):
        upstream, gateway_stub = start_gateway_pair(
            lambda _path, payload: completion_payload(payload["messages"][0]["content"])
        )
        try:
            status, _headers, _payload = post_json(
                gateway_stub.base_url,
                "/v1/chat/completions",
                {
                    "model": "gpt-test",
                    "messages": [{"role": "user", "content": "hello monitoring"}],
                },
                headers=AUTH_HEADERS,
            )
            self.assertEqual(status, 200)

            status, _headers, events = http_get_json(
                gateway_stub.base_url, "/modeio/api/v1/events"
            )
            self.assertEqual(status, 200)
            self.assertEqual(len(events["items"]), 1)
            request_id = events["items"][0]["requestId"]
            self.assertEqual(events["items"][0]["clientName"], "unknown")
            self.assertEqual(events["items"][0]["lifecycle"], "none")
            self.assertEqual(events["items"][0]["impact"], "pass_through")

            status, _headers, detail = http_get_json(
                gateway_stub.base_url, f"/modeio/api/v1/events/{request_id}"
            )
            self.assertEqual(status, 200)
            self.assertEqual(detail["clientName"], "unknown")
            self.assertEqual(detail["lifecycle"], "none")
            self.assertEqual(
                detail["request"]["before"]["views"]["prompt"]["text"],
                "hello monitoring",
            )

            status, _headers, stats = http_get_json(
                gateway_stub.base_url, "/modeio/api/v1/stats"
            )
            self.assertEqual(status, 200)
            self.assertEqual(stats["completedRecords"], 1)
            self.assertEqual(stats["byStatus"]["completed"], 1)
            self.assertEqual(stats["byLifecycle"]["none"], 1)
        finally:
            gateway_stub.stop()
            upstream.stop()

    def test_detail_shows_request_and_response_changes(self):
        module_name = "modeio_middleware.tests.plugins.monitoring_modify_both"
        _register_modify_plugin(module_name)
        plugins = {
            "modify_both": {
                "enabled": True,
                "module": module_name,
            }
        }
        profiles = {
            "dev": {
                "on_plugin_error": "warn",
                "plugins": ["modify_both"],
            }
        }
        upstream, gateway_stub = start_gateway_pair(
            lambda _path, payload: completion_payload(
                payload["messages"][0]["content"]
            ),
            plugins=plugins,
            profiles=profiles,
        )
        try:
            status, _headers, payload = post_json(
                gateway_stub.base_url,
                "/v1/chat/completions",
                {
                    "model": "gpt-test",
                    "messages": [{"role": "user", "content": "hello monitoring"}],
                },
                headers=AUTH_HEADERS,
            )
            self.assertEqual(status, 200)
            self.assertEqual(
                payload["choices"][0]["message"]["content"], "rewritten response"
            )

            status, _headers, events = http_get_json(
                gateway_stub.base_url, "/modeio/api/v1/events"
            )
            request_id = events["items"][0]["requestId"]

            status, _headers, detail = http_get_json(
                gateway_stub.base_url, f"/modeio/api/v1/events/{request_id}"
            )
            self.assertEqual(status, 200)
            self.assertEqual(detail["lifecycle"], "pre_and_post")
            self.assertEqual(detail["impact"], "modified")
            self.assertEqual(detail["primaryPlugin"], "modify_both")
            self.assertTrue(detail["request"]["change"]["changed"])
            self.assertTrue(detail["response"]["change"]["changed"])
            self.assertEqual(
                detail["request"]["after"]["views"]["prompt"]["text"],
                "rewritten prompt",
            )
            self.assertEqual(
                detail["response"]["after"]["views"]["response"]["text"],
                "rewritten response",
            )
            self.assertEqual(len(detail["hookExecutions"]), 2)
        finally:
            gateway_stub.stop()
            upstream.stop()

    def test_blocked_request_is_listed_as_blocked(self):
        module_name = "modeio_middleware.tests.plugins.monitoring_blocker"
        _register_block_plugin(module_name)
        plugins = {
            "blocker": {
                "enabled": True,
                "module": module_name,
            }
        }
        profiles = {
            "dev": {
                "on_plugin_error": "warn",
                "plugins": ["blocker"],
            }
        }
        upstream, gateway_stub = start_gateway_pair(
            lambda _path, payload: completion_payload(
                payload["messages"][0]["content"]
            ),
            plugins=plugins,
            profiles=profiles,
        )
        try:
            status, _headers, payload = post_json(
                gateway_stub.base_url,
                "/v1/chat/completions",
                {
                    "model": "gpt-test",
                    "messages": [{"role": "user", "content": "hello monitoring"}],
                },
                headers=AUTH_HEADERS,
            )
            self.assertEqual(status, 403)
            self.assertEqual(payload["error"]["code"], "MODEIO_PLUGIN_BLOCKED")

            status, _headers, stats = http_get_json(
                gateway_stub.base_url, "/modeio/api/v1/stats"
            )
            self.assertEqual(status, 200)
            self.assertEqual(stats["byStatus"]["blocked"], 1)

            status, _headers, events = http_get_json(
                gateway_stub.base_url, "/modeio/api/v1/events?status=blocked"
            )
            self.assertEqual(status, 200)
            self.assertEqual(len(events["items"]), 1)
            self.assertEqual(events["items"][0]["status"], "blocked")
            self.assertEqual(events["items"][0]["lifecycle"], "pre_request")
            self.assertEqual(events["items"][0]["impact"], "blocked")
        finally:
            gateway_stub.stop()
            upstream.stop()

    def test_events_support_client_impact_and_lifecycle_filters(self):
        upstream, gateway_stub = start_gateway_pair(
            lambda _path, payload: completion_payload(payload["messages"][0]["content"])
        )
        try:
            status, _headers, _payload = post_json(
                gateway_stub.base_url,
                "/v1/chat/completions",
                {
                    "model": "gpt-test",
                    "messages": [{"role": "user", "content": "hello monitoring"}],
                },
                headers=AUTH_HEADERS,
            )
            self.assertEqual(status, 200)

            status, _headers, events = http_get_json(
                gateway_stub.base_url,
                "/modeio/api/v1/events?client=unknown&impact=pass_through&lifecycle=none",
            )
            self.assertEqual(status, 200)
            self.assertEqual(len(events["items"]), 1)
            self.assertEqual(events["items"][0]["clientName"], "unknown")
            self.assertEqual(events["items"][0]["impact"], "pass_through")
            self.assertEqual(events["items"][0]["lifecycle"], "none")

            status, _headers, missing_route = http_get_json(
                gateway_stub.base_url, "/modeio/unknown-monitoring-route"
            )
            self.assertEqual(status, 404)
            self.assertEqual(missing_route["error"]["code"], "MODEIO_ROUTE_NOT_FOUND")
        finally:
            gateway_stub.stop()
            upstream.stop()


if __name__ == "__main__":
    unittest.main()
