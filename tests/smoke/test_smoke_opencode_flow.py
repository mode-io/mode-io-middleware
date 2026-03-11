#!/usr/bin/env python3

import io
import json
import socket
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT
HELPERS_DIR = REPO_ROOT / "tests" / "helpers"
sys.path.insert(0, str(PACKAGE_DIR))
sys.path.insert(0, str(HELPERS_DIR))

from modeio_middleware.cli import middleware as middleware_cli  # noqa: E402
from gateway_harness import (  # noqa: E402
    completion_payload,
    post_json,
    post_stream,
    responses_payload,
    start_gateway_pair,
)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as handle:
        handle.bind(("127.0.0.1", 0))
        return int(handle.getsockname()[1])


def _run_cli_json(args):
    out = io.StringIO()
    with redirect_stdout(out):
        code = middleware_cli.main([*args, "--json"])
    return code, json.loads(out.getvalue())


class TestSmokeOpenCodeFlow(unittest.TestCase):
    def test_opencode_enable_route_and_disable_all(self):
        def response_factory(path, payload):
            if path.endswith("/v1/chat/completions"):
                content = ""
                if isinstance(payload.get("messages"), list) and payload["messages"]:
                    first = payload["messages"][0]
                    if isinstance(first, dict):
                        content = str(first.get("content", ""))
                return completion_payload(content)

            if path.endswith("/v1/responses"):
                content = payload.get("input")
                if not isinstance(content, str):
                    content = "responses-ok"
                return responses_payload(content)

            return {"ok": True}

        def stream_factory(path, payload):
            if not path.endswith("/v1/chat/completions"):
                return ["[DONE]"]

            content = "stream"
            if isinstance(payload.get("messages"), list) and payload["messages"]:
                first = payload["messages"][0]
                if isinstance(first, dict) and isinstance(first.get("content"), str):
                    content = first["content"]

            return [
                {
                    "id": "evt1",
                    "object": "chat.completion.chunk",
                    "choices": [{"delta": {"content": content[:4]}}],
                },
                "[DONE]",
            ]

        upstream = None
        gateway = None
        try:
            upstream, gateway = start_gateway_pair(response_factory, stream_factory=stream_factory)
            with TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                modeio_config = root / "modeio" / "middleware.json"
                opencode_config = root / ".config" / "opencode" / "opencode.json"
                opencode_config.parent.mkdir(parents=True, exist_ok=True)
                opencode_config.write_text(
                    json.dumps(
                        {
                            "model": "openai/gpt-test",
                            "provider": {
                                "openai": {
                                    "options": {
                                        "baseURL": f"{upstream.base_url}/v1",
                                        "apiKey": "sk-opencode-test",
                                    }
                                }
                            },
                        }
                    ),
                    encoding="utf-8",
                )
                opencode_config.with_name("opencode.json.modeio-route.json").write_text(
                    json.dumps(
                        {
                            "providers": {
                                "openai": {
                                    "providerId": "openai",
                                    "originalBaseUrl": f"{upstream.base_url}/v1",
                                    "hadExplicitBaseUrl": True,
                                    "routeMode": "preserve_provider",
                                }
                            }
                        }
                    ),
                    encoding="utf-8",
                )
                port = _free_port()
                env = {
                    "HOME": temp_dir,
                    "XDG_CONFIG_HOME": str(root / ".config"),
                    "XDG_STATE_HOME": str(root / ".state"),
                    "XDG_CACHE_HOME": str(root / ".cache"),
                }
                try:
                    with mock.patch.dict("os.environ", env, clear=False):
                        enable_code, enable_payload = _run_cli_json(
                            [
                                "--config",
                                str(modeio_config),
                                "--opencode-config-path",
                                str(opencode_config),
                                "enable",
                                "opencode",
                                "--host",
                                "127.0.0.1",
                                "--port",
                                str(port),
                            ]
                        )
                        self.assertEqual(enable_code, 0)
                        self.assertTrue(enable_payload["success"])

                        routed_headers = {"Authorization": "Bearer harness-secret"}
                        chat_status, chat_headers, chat_payload = post_json(
                            f"http://127.0.0.1:{port}",
                            "/clients/opencode/openai/v1/chat/completions",
                            {
                                "model": "gpt-test",
                                "messages": [{"role": "user", "content": "smoke-chat"}],
                                "modeio": {"profile": "dev"},
                            },
                            headers=routed_headers,
                        )
                        self.assertEqual(chat_status, 200)
                        self.assertEqual(chat_payload["choices"][0]["message"]["content"], "smoke-chat")
                        self.assertIn("x-modeio-request-id", {k.lower(): v for k, v in chat_headers.items()})

                        responses_status, _, responses_payload_data = post_json(
                            f"http://127.0.0.1:{port}",
                            "/clients/opencode/openai/v1/responses",
                            {
                                "model": "gpt-test",
                                "input": "smoke-responses",
                                "modeio": {"profile": "dev"},
                            },
                            headers=routed_headers,
                        )
                        self.assertEqual(responses_status, 200)
                        self.assertEqual(responses_payload_data["output_text"], "smoke-responses")

                        stream_status, stream_headers, stream_text = post_stream(
                            f"http://127.0.0.1:{port}",
                            "/clients/opencode/openai/v1/chat/completions",
                            {
                                "model": "gpt-test",
                                "stream": True,
                                "messages": [{"role": "user", "content": "stream-smoke"}],
                                "modeio": {"profile": "dev"},
                            },
                            headers=routed_headers,
                        )
                        self.assertEqual(stream_status, 200)
                        self.assertEqual(
                            {k.lower(): v for k, v in stream_headers.items()}.get("x-modeio-streaming"),
                            "true",
                        )
                        self.assertIn("[DONE]", stream_text)

                        disable_code, disable_payload = _run_cli_json(
                            [
                                "--config",
                                str(modeio_config),
                                "disable",
                                "--all",
                            ]
                        )
                        self.assertEqual(disable_code, 0)
                        self.assertTrue(disable_payload["success"])
                finally:
                    with mock.patch.dict("os.environ", env, clear=False):
                        _run_cli_json(["--config", str(modeio_config), "disable", "--all"])
        finally:
            if gateway is not None:
                gateway.stop()
            if upstream is not None:
                upstream.stop()


if __name__ == "__main__":
    unittest.main()
