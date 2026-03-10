#!/usr/bin/env python3

from __future__ import annotations

import json
import sys
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT
if str(PACKAGE_DIR) not in sys.path:
    sys.path.insert(0, str(PACKAGE_DIR))

from modeio_middleware.cli import gateway
from modeio_middleware.runtime_config_store import build_gateway_runtime_config


def completion_payload(content: str) -> Dict[str, Any]:
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 0,
        "model": "test-model",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": content,
                },
                "finish_reason": "stop",
            }
        ],
    }


def responses_payload(content: str) -> Dict[str, Any]:
    return {
        "id": "resp_test",
        "object": "response",
        "model": "test-model",
        "output_text": content,
        "output": [
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": content}],
            }
        ],
    }


def models_payload(*model_ids: str) -> Dict[str, Any]:
    ids = model_ids or ("test-model",)
    return {
        "object": "list",
        "models": [{"id": model_id, "name": model_id} for model_id in ids],
    }


def http_get_json(
    base_url: str,
    path: str,
    *,
    headers: Dict[str, str] | None = None,
):
    request = urllib.request.Request(
        f"{base_url}{path}",
        headers=dict(headers or {}),
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            body = json.loads(response.read().decode("utf-8"))
            return response.status, response.headers, body
    except urllib.error.HTTPError as error:
        try:
            body = json.loads(error.read().decode("utf-8"))
            return error.code, error.headers, body
        finally:
            error.close()


def http_get_text(base_url: str, path: str):
    request = urllib.request.Request(f"{base_url}{path}", method="GET")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            body = response.read().decode("utf-8", errors="replace")
            return response.status, response.headers, body
    except urllib.error.HTTPError as error:
        try:
            body = error.read().decode("utf-8", errors="replace")
            return error.code, error.headers, body
        finally:
            error.close()


def post_json(
    base_url: str,
    path: str,
    payload: Dict[str, Any],
    *,
    headers: Dict[str, str] | None = None,
):
    request_headers = {"Content-Type": "application/json"}
    if headers:
        request_headers.update(headers)

    request = urllib.request.Request(
        f"{base_url}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers=request_headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            body = json.loads(response.read().decode("utf-8"))
            return response.status, response.headers, body
    except urllib.error.HTTPError as error:
        try:
            body = json.loads(error.read().decode("utf-8"))
            return error.code, error.headers, body
        finally:
            error.close()


def put_json(
    base_url: str,
    path: str,
    payload: Dict[str, Any],
    *,
    headers: Dict[str, str] | None = None,
):
    request_headers = {"Content-Type": "application/json"}
    if headers:
        request_headers.update(headers)

    request = urllib.request.Request(
        f"{base_url}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers=request_headers,
        method="PUT",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            body = json.loads(response.read().decode("utf-8"))
            return response.status, response.headers, body
    except urllib.error.HTTPError as error:
        try:
            body = json.loads(error.read().decode("utf-8"))
            return error.code, error.headers, body
        finally:
            error.close()


def post_raw(
    base_url: str, path: str, body: bytes, *, headers: Dict[str, str] | None = None
):
    request_headers = {"Content-Type": "application/json"}
    if headers:
        request_headers.update(headers)

    request = urllib.request.Request(
        f"{base_url}{path}",
        data=body,
        headers=request_headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return response.status, response.headers, payload
    except urllib.error.HTTPError as error:
        try:
            payload = json.loads(error.read().decode("utf-8"))
            return error.code, error.headers, payload
        finally:
            error.close()


def post_stream(
    base_url: str,
    path: str,
    payload: Dict[str, Any],
    *,
    headers: Dict[str, str] | None = None,
):
    request_headers = {"Content-Type": "application/json"}
    if headers:
        request_headers.update(headers)
    request = urllib.request.Request(
        f"{base_url}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers=request_headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            body = response.read().decode("utf-8", errors="replace")
            return response.status, response.headers, body
    except urllib.error.HTTPError as error:
        try:
            body = error.read().decode("utf-8", errors="replace")
            return error.code, error.headers, body
        finally:
            error.close()


class UpstreamStub:
    def __init__(
        self,
        response_factory,
        status: int = 200,
        stream_factory=None,
        response_headers: Dict[str, str] | None = None,
    ):
        self.response_factory = response_factory
        self.status = status
        self.stream_factory = stream_factory
        self.response_headers = dict(response_headers or {})
        self.requests = []
        self._server = None
        self._thread = None
        self.base_url = ""

    def start(self):
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self):
                owner.requests.append(
                    {
                        "path": self.path,
                        "headers": dict(self.headers.items()),
                        "body": None,
                    }
                )

                response_payload = owner.response_factory(self.path, {})
                response_body = json.dumps(response_payload).encode("utf-8")

                self.send_response(owner.status)
                self.send_header("Content-Type", "application/json")
                for header_name, header_value in owner.response_headers.items():
                    self.send_header(header_name, header_value)
                self.send_header("Content-Length", str(len(response_body)))
                self.end_headers()
                self.wfile.write(response_body)

            def do_POST(self):
                content_length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(content_length)
                payload = json.loads(body.decode("utf-8")) if body else {}
                owner.requests.append(
                    {
                        "path": self.path,
                        "headers": dict(self.headers.items()),
                        "body": payload,
                    }
                )

                if payload.get("stream") is True and owner.stream_factory is not None:
                    self.send_response(owner.status)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Cache-Control", "no-cache")
                    self.end_headers()

                    events = owner.stream_factory(self.path, payload)
                    for event in events:
                        if isinstance(event, bytes):
                            chunk = event
                        elif event == "[DONE]":
                            chunk = b"data: [DONE]\n\n"
                        elif isinstance(event, dict):
                            chunk = (
                                b"data: " + json.dumps(event).encode("utf-8") + b"\n\n"
                            )
                        else:
                            chunk = str(event).encode("utf-8")
                            if not chunk.endswith(b"\n\n"):
                                chunk += b"\n\n"

                        self.wfile.write(chunk)
                        self.wfile.flush()
                    return

                response_payload = owner.response_factory(self.path, payload)
                response_body = json.dumps(response_payload).encode("utf-8")

                self.send_response(owner.status)
                self.send_header("Content-Type", "application/json")
                for header_name, header_value in owner.response_headers.items():
                    self.send_header(header_name, header_value)
                self.send_header("Content-Length", str(len(response_body)))
                self.end_headers()
                self.wfile.write(response_body)

            def log_message(self, _format, *_args):
                return

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        host, port = self._server.server_address
        self.base_url = f"http://{host}:{port}"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self):
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2)


class GatewayStub:
    def __init__(
        self, upstream_base_url: str, *, plugins=None, profiles=None, config_path=None
    ):
        self._server = None
        self._thread = None
        self.base_url = ""
        if config_path is not None:
            self.config = build_gateway_runtime_config(
                Path(config_path),
                upstream_chat_completions_url=f"{upstream_base_url}/v1/chat/completions",
                upstream_responses_url=f"{upstream_base_url}/v1/responses",
                upstream_timeout_seconds=5,
                upstream_api_key_env="MODEIO_GATEWAY_UPSTREAM_API_KEY",
                default_profile="dev",
            )
        else:
            self.config = gateway.GatewayRuntimeConfig(
                upstream_chat_completions_url=f"{upstream_base_url}/v1/chat/completions",
                upstream_responses_url=f"{upstream_base_url}/v1/responses",
                upstream_timeout_seconds=5,
                upstream_api_key_env="MODEIO_GATEWAY_UPSTREAM_API_KEY",
                default_profile="dev",
                config_base_dir=str(REPO_ROOT),
                profiles=profiles
                or {
                    "dev": {
                        "on_plugin_error": "warn",
                        "plugins": ["redact"],
                    }
                },
                plugins=plugins
                or {
                    "redact": {
                        "enabled": False,
                        "module": "modeio_middleware.plugins.redact",
                    },
                },
            )

    def start(self):
        self._server = gateway.create_server("127.0.0.1", 0, self.config)
        host, port = self._server.server_address
        self.base_url = f"http://{host}:{port}"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self):
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2)


def start_gateway_pair(
    response_factory,
    *,
    status: int = 200,
    stream_factory=None,
    response_headers: Dict[str, str] | None = None,
    plugins=None,
    profiles=None,
    config_path=None,
):
    upstream = UpstreamStub(
        response_factory=response_factory,
        status=status,
        stream_factory=stream_factory,
        response_headers=response_headers,
    )
    upstream.start()
    gateway_stub = GatewayStub(
        upstream_base_url=upstream.base_url,
        plugins=plugins,
        profiles=profiles,
        config_path=config_path,
    )
    gateway_stub.start()
    return upstream, gateway_stub
