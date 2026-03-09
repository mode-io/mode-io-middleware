#!/usr/bin/env python3

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT
sys.path.insert(0, str(PACKAGE_DIR))

from modeio_middleware.core.observability.derived import summarize_lifecycle  # noqa: E402
from modeio_middleware.core.observability.models import (  # noqa: E402
    ChangeSummary,
    HookExecutionRecord,
)


def _change(changed: bool) -> ChangeSummary:
    return ChangeSummary(changed=changed)


def _hook(hook_name: str, action: str = "allow") -> HookExecutionRecord:
    return HookExecutionRecord(
        plugin_name="demo_plugin",
        hook_name=hook_name,
        effective_action=action,
        duration_ms=1.0,
        errored=False,
    )


class TestObservabilityDerived(unittest.TestCase):
    def test_summarize_lifecycle_returns_none_without_hook_activity(self):
        lifecycle = summarize_lifecycle(
            request_change=_change(False),
            response_change=_change(False),
            hook_executions=(),
        )

        self.assertEqual(lifecycle, "none")

    def test_summarize_lifecycle_detects_pre_and_post_activity(self):
        lifecycle = summarize_lifecycle(
            request_change=_change(False),
            response_change=_change(False),
            hook_executions=(
                _hook("pre_request"),
                _hook("post_response"),
            ),
        )

        self.assertEqual(lifecycle, "pre_and_post")

    def test_summarize_lifecycle_detects_pre_and_stream_activity(self):
        lifecycle = summarize_lifecycle(
            request_change=_change(True),
            response_change=_change(False),
            hook_executions=(_hook("post_stream_event", action="warn"),),
        )

        self.assertEqual(lifecycle, "pre_and_stream")


if __name__ == "__main__":
    unittest.main()
