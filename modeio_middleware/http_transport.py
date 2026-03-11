#!/usr/bin/env python3

from __future__ import annotations

import gzip
import json
import socket
import threading
import zlib
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional
from urllib.parse import unquote

import uvicorn
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import FileResponse, Response, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from modeio_middleware.core.engine import (
    GatewayRuntimeConfig,
    ProcessResult,
    StreamProcessResult,
)
from modeio_middleware.core.errors import MiddlewareError
from modeio_middleware.core.http_contract import (
    CONTRACT_VERSION,
    contract_headers,
    error_payload,
    new_request_id,
    safe_json_dumps,
)
from modeio_middleware.monitoring.api import build_monitoring_routes
from modeio_middleware.resources import (
    bundled_dashboard_dir,
    bundled_dashboard_favicon_path,
    bundled_dashboard_index_path,
)
from modeio_middleware.runtime_control import GatewayController

try:  # Python 3.14+
    from compression import zstd as _zstd_codec
except Exception:  # pragma: no cover
    _zstd_codec = None

CLAUDE_HOOK_CONNECTOR_PATH = "/connectors/claude/hooks"
LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}
CLIENT_ROUTE_PREFIX = "/clients/"


def _decode_content_encoded_body(body_bytes: bytes, content_encoding: str) -> bytes:
    decoded = body_bytes
    encodings = [
        item.strip().lower() for item in content_encoding.split(",") if item.strip()
    ]
    if not encodings:
        return decoded

    for encoding in reversed(encodings):
        if encoding == "identity":
            continue

        try:
            if encoding in {"gzip", "x-gzip"}:
                decoded = gzip.decompress(decoded)
            elif encoding == "deflate":
                try:
                    decoded = zlib.decompress(decoded)
                except zlib.error:
                    decoded = zlib.decompress(decoded, -zlib.MAX_WBITS)
            elif encoding in {"zstd", "x-zstd"}:
                if _zstd_codec is None:
                    raise MiddlewareError(
                        400,
                        "MODEIO_VALIDATION_ERROR",
                        "content encoding 'zstd' is not supported in this Python runtime",
                    )
                decoded = _zstd_codec.decompress(decoded)
            else:
                raise MiddlewareError(
                    400,
                    "MODEIO_VALIDATION_ERROR",
                    f"unsupported Content-Encoding '{encoding}'",
                )
        except MiddlewareError:
            raise
        except Exception as error:
            raise MiddlewareError(
                400,
                "MODEIO_VALIDATION_ERROR",
                f"failed to decode request body with Content-Encoding '{encoding}'",
            ) from error

    return decoded


async def _read_json_body(request: Request) -> Dict[str, Any]:
    body_bytes = await request.body()
    if not body_bytes:
        raise MiddlewareError(
            400, "MODEIO_VALIDATION_ERROR", "request body must not be empty"
        )

    content_encoding = str(request.headers.get("Content-Encoding", "")).strip()
    if content_encoding:
        body_bytes = _decode_content_encoded_body(body_bytes, content_encoding)

    try:
        payload = json.loads(body_bytes.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise MiddlewareError(
            400, "MODEIO_VALIDATION_ERROR", "request body must be valid JSON"
        ) from error

    if not isinstance(payload, dict):
        raise MiddlewareError(
            400, "MODEIO_VALIDATION_ERROR", "request body must be a JSON object"
        )
    return payload


def _json_response(
    status: int,
    payload: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
) -> Response:
    response = Response(
        content=safe_json_dumps(payload),
        status_code=status,
        media_type="application/json; charset=utf-8",
    )
    if headers:
        for key, value in headers.items():
            response.headers[key] = str(value)
    return response


def _default_contract_headers(
    controller: GatewayController, request_id: str
) -> Dict[str, str]:
    engine = controller.current_engine()
    return contract_headers(
        request_id,
        profile=engine.config.default_profile,
        pre_actions=[],
        post_actions=[],
        degraded=[],
        upstream_called=False,
    )


def _contract_error_response(
    controller: GatewayController,
    request_id: str,
    *,
    status: int,
    code: str,
    message: str,
    retryable: bool,
    details: Optional[Dict[str, Any]] = None,
) -> Response:
    return _json_response(
        status,
        error_payload(
            request_id,
            code,
            message,
            retryable=retryable,
            details=details,
        ),
        _default_contract_headers(controller, request_id),
    )


def _render_engine_result(
    controller: GatewayController,
    request_id: str,
    result: ProcessResult | StreamProcessResult,
) -> Response:
    if isinstance(result, StreamProcessResult):
        if result.stream is not None:
            return StreamingResponse(
                result.stream,
                status_code=result.status,
                headers=result.headers,
            )

        payload = result.payload or error_payload(
            request_id,
            "MODEIO_INTERNAL_ERROR",
            "stream result missing payload",
            retryable=False,
        )
        return _json_response(result.status, payload, result.headers)

    if isinstance(result, ProcessResult):
        return _json_response(result.status, result.payload, result.headers)

    return _json_response(
        500,
        error_payload(
            request_id,
            "MODEIO_INTERNAL_ERROR",
            "unexpected result type from middleware engine",
            retryable=False,
        ),
        _default_contract_headers(controller, request_id),
    )


def _dashboard_index_response() -> Response:
    index_path = bundled_dashboard_index_path()
    if not index_path.exists():
        return Response(
            content=(
                "ModeIO dashboard assets are missing. "
                "Run 'bash ./scripts/build_dashboard.sh' from the repository root."
            ),
            status_code=503,
            media_type="text/plain; charset=utf-8",
        )
    return FileResponse(index_path, media_type="text/html; charset=utf-8")


def _dashboard_favicon_response() -> Response:
    favicon_path = bundled_dashboard_favicon_path()
    if not favicon_path.exists():
        return Response(status_code=204)
    return FileResponse(favicon_path, media_type="image/svg+xml")


def _is_loopback_host(host: str) -> bool:
    return str(host).strip().lower() in LOOPBACK_HOSTS


def _normalized_openai_request(
    path: str,
    incoming_headers: Dict[str, str],
) -> tuple[str, Dict[str, str]]:
    normalized_headers = dict(incoming_headers)
    if not path.startswith(CLIENT_ROUTE_PREFIX):
        return path, normalized_headers

    segments = [segment for segment in path.split("/") if segment]
    if len(segments) >= 4 and segments[0] == "clients":
        client_name = unquote(segments[1]).strip()
        if segments[2] == "v1":
            remainder = "/".join(segments[3:])
            if remainder:
                normalized_headers["x-modeio-client"] = client_name
                return f"/v1/{remainder}", normalized_headers

        if len(segments) >= 5 and segments[3] == "v1":
            provider_name = unquote(segments[2]).strip()
            remainder = "/".join(segments[4:])
            if remainder:
                normalized_headers["x-modeio-client"] = client_name
                normalized_headers["x-modeio-client-provider"] = provider_name
                return f"/v1/{remainder}", normalized_headers

    return path, normalized_headers


def create_app(config: GatewayRuntimeConfig) -> Starlette:
    controller = GatewayController(config)

    @asynccontextmanager
    async def lifespan(_app: Starlette):
        try:
            yield
        finally:
            controller.shutdown()

    async def healthz(_request: Request) -> Response:
        engine = controller.current_engine()
        payload = {
            "ok": True,
            "service": "modeio-middleware",
            "version": CONTRACT_VERSION,
            "profiles": sorted(list((engine.config.profiles or {}).keys())),
        }
        return _json_response(200, payload)

    async def dashboard_index(_request: Request) -> Response:
        return _dashboard_index_response()

    async def dashboard_favicon(_request: Request) -> Response:
        return _dashboard_favicon_response()

    async def _process_post_request(request: Request) -> Response:
        request_id = new_request_id()
        normalized_path, normalized_headers = _normalized_openai_request(
            str(request.url.path), dict(request.headers.items())
        )
        try:
            body = await _read_json_body(request)
        except MiddlewareError as error:
            return _contract_error_response(
                controller,
                request_id,
                status=error.status,
                code=error.code,
                message=error.message,
                retryable=error.retryable,
                details=error.details,
            )

        try:
            result = await run_in_threadpool(
                controller.process_http_request,
                path=normalized_path,
                request_id=request_id,
                payload=body,
                incoming_headers=normalized_headers,
            )
        except MiddlewareError as error:
            return _contract_error_response(
                controller,
                request_id,
                status=error.status,
                code=error.code,
                message=error.message,
                retryable=error.retryable,
                details=error.details,
            )
        return _render_engine_result(controller, request_id, result)

    async def _process_models_request(request: Request) -> Response:
        request_id = new_request_id()
        normalized_path, normalized_headers = _normalized_openai_request(
            str(request.url.path), dict(request.headers.items())
        )
        if normalized_path != "/v1/models":
            return _contract_error_response(
                controller,
                request_id,
                status=404,
                code="MODEIO_ROUTE_NOT_FOUND",
                message="route not found",
                retryable=False,
            )

        try:
            result = await run_in_threadpool(
                controller.process_models_request,
                request_id=request_id,
                incoming_headers=normalized_headers,
                query_params={key: str(value) for key, value in request.query_params.items()},
            )
        except MiddlewareError as error:
            return _contract_error_response(
                controller,
                request_id,
                status=error.status,
                code=error.code,
                message=error.message,
                retryable=error.retryable,
                details=error.details,
            )
        response = _render_engine_result(controller, request_id, result)
        for key, value in _default_contract_headers(controller, request_id).items():
            response.headers[key] = value
        return response

    async def unknown_route(_request: Request) -> Response:
        request_id = new_request_id()
        return _contract_error_response(
            controller,
            request_id,
            status=404,
            code="MODEIO_ROUTE_NOT_FOUND",
            message="route not found",
            retryable=False,
        )

    app = Starlette(
        routes=[
            Route("/healthz", healthz, methods=["GET"]),
            Route("/favicon.ico", dashboard_favicon, methods=["GET"]),
            Route("/modeio/dashboard", dashboard_index, methods=["GET"]),
            Route("/modeio/dashboard/", dashboard_index, methods=["GET"]),
            Mount(
                "/modeio/dashboard/assets",
                app=StaticFiles(
                    directory=bundled_dashboard_dir() / "assets", check_dir=False
                ),
                name="modeio-dashboard-assets",
            ),
            *build_monitoring_routes(controller),
            Route(CLAUDE_HOOK_CONNECTOR_PATH, _process_post_request, methods=["POST"]),
            Route("/v1/models", _process_models_request, methods=["GET"]),
            Route("/v1/messages", _process_post_request, methods=["POST"]),
            Route("/v1/chat/completions", _process_post_request, methods=["POST"]),
            Route("/v1/responses", _process_post_request, methods=["POST"]),
            Route("/clients/{client}/v1/models", _process_models_request, methods=["GET"]),
            Route(
                "/clients/{client}/v1/messages",
                _process_post_request,
                methods=["POST"],
            ),
            Route(
                "/clients/{client}/v1/chat/completions",
                _process_post_request,
                methods=["POST"],
            ),
            Route(
                "/clients/{client}/v1/responses",
                _process_post_request,
                methods=["POST"],
            ),
            Route(
                "/clients/{client}/{provider}/v1/models",
                _process_models_request,
                methods=["GET"],
            ),
            Route(
                "/clients/{client}/{provider}/v1/messages",
                _process_post_request,
                methods=["POST"],
            ),
            Route(
                "/clients/{client}/{provider}/v1/chat/completions",
                _process_post_request,
                methods=["POST"],
            ),
            Route(
                "/clients/{client}/{provider}/v1/responses",
                _process_post_request,
                methods=["POST"],
            ),
            Route("/{rest:path}", unknown_route, methods=["GET", "POST"]),
        ],
        lifespan=lifespan,
    )
    app.state.controller = controller
    app.state.engine = controller.current_engine()
    return app


class GatewayServer:
    def __init__(self, host: str, port: int, app: Starlette):
        self._app = app
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.bind((host, port))
        self._socket.listen(128)
        self._socket.setblocking(False)
        self.server_address = self._socket.getsockname()
        self._server: uvicorn.Server | None = None
        self._closed = False
        self._serve_done = threading.Event()

    def _finalize(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._socket.close()
        except Exception:
            pass

    def serve_forever(self) -> None:
        config = uvicorn.Config(
            self._app,
            host=str(self.server_address[0]),
            port=int(self.server_address[1]),
            log_config=None,
            access_log=False,
        )
        server = uvicorn.Server(config)
        server.install_signal_handlers = lambda: None
        self._server = server
        try:
            server.run(sockets=[self._socket])
        finally:
            self._finalize()
            self._serve_done.set()

    def shutdown(self) -> None:
        if self._server is not None:
            self._server.should_exit = True

    def server_close(self) -> None:
        self.shutdown()
        self._serve_done.wait(timeout=5)
        self._finalize()


def create_server(
    host: str,
    port: int,
    config: GatewayRuntimeConfig,
    *,
    allow_remote_admin: bool = False,
) -> GatewayServer:
    if not allow_remote_admin and not _is_loopback_host(host):
        raise MiddlewareError(
            400,
            "MODEIO_REMOTE_ADMIN_DISABLED",
            "admin routes require loopback host binding unless --allow-remote-admin is set",
            retryable=False,
            details={"host": host},
        )
    return GatewayServer(host, port, create_app(config))
