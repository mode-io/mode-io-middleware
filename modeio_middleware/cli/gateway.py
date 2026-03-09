#!/usr/bin/env python3
"""ModeIO middleware gateway entrypoint."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Optional, Sequence

from modeio_middleware.core.engine import GatewayRuntimeConfig
from modeio_middleware.core.errors import MiddlewareError
from modeio_middleware.core.profiles import DEFAULT_PROFILE, normalize_profile_name
from modeio_middleware.http_transport import create_server
from modeio_middleware.runtime_config_store import build_gateway_runtime_config
from modeio_middleware.runtime_home import (
    default_modeio_config_path,
    ensure_user_runtime_home,
)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787
DEFAULT_UPSTREAM_CHAT_URL = "https://api.openai.com/v1/chat/completions"
DEFAULT_UPSTREAM_RESPONSES_URL = "https://api.openai.com/v1/responses"
DEFAULT_UPSTREAM_TIMEOUT_SECONDS = 60
DEFAULT_UPSTREAM_API_KEY_ENV = "MODEIO_GATEWAY_UPSTREAM_API_KEY"


def _default_config_path() -> Path:
    return default_modeio_config_path()


def load_runtime_config(args: argparse.Namespace) -> GatewayRuntimeConfig:
    config_path = Path(args.config).expanduser()
    if config_path == _default_config_path() and not config_path.exists():
        ensure_user_runtime_home(config_path)

    return build_gateway_runtime_config(
        config_path,
        upstream_chat_completions_url=args.upstream_chat_url,
        upstream_responses_url=args.upstream_responses_url,
        upstream_timeout_seconds=args.upstream_timeout,
        upstream_api_key_env=args.upstream_api_key_env,
        default_profile=normalize_profile_name(
            args.default_profile,
            default_profile=DEFAULT_PROFILE,
        ),
    )


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run local modeio-middleware gateway for Codex/OpenCode provider routing. "
            "Contract: POST /v1/chat/completions, /v1/responses, /connectors/claude/hooks, GET /healthz"
        )
    )
    parser.add_argument(
        "--host", default=DEFAULT_HOST, help=f"Listen host (default: {DEFAULT_HOST})"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Listen port (default: {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--upstream-chat-url",
        default=os.environ.get(
            "MODEIO_MIDDLEWARE_UPSTREAM_CHAT_URL", DEFAULT_UPSTREAM_CHAT_URL
        ),
        help=(
            "Upstream OpenAI-compatible chat completions endpoint "
            f"(default env MODEIO_MIDDLEWARE_UPSTREAM_CHAT_URL or {DEFAULT_UPSTREAM_CHAT_URL})"
        ),
    )
    parser.add_argument(
        "--upstream-responses-url",
        default=os.environ.get(
            "MODEIO_MIDDLEWARE_UPSTREAM_RESPONSES_URL", DEFAULT_UPSTREAM_RESPONSES_URL
        ),
        help=(
            "Upstream OpenAI-compatible responses endpoint "
            f"(default env MODEIO_MIDDLEWARE_UPSTREAM_RESPONSES_URL or {DEFAULT_UPSTREAM_RESPONSES_URL})"
        ),
    )
    parser.add_argument(
        "--upstream-timeout",
        type=int,
        default=DEFAULT_UPSTREAM_TIMEOUT_SECONDS,
        help=f"Upstream timeout seconds (default: {DEFAULT_UPSTREAM_TIMEOUT_SECONDS})",
    )
    parser.add_argument(
        "--upstream-api-key-env",
        default=DEFAULT_UPSTREAM_API_KEY_ENV,
        help=(
            "Environment variable name containing upstream API key when incoming request "
            "has no Authorization header"
        ),
    )
    parser.add_argument(
        "--config",
        default=str(_default_config_path()),
        help="Middleware config JSON path",
    )
    parser.add_argument(
        "--default-profile",
        default=DEFAULT_PROFILE,
        help=f"Default middleware profile when request has no modeio.profile (default: {DEFAULT_PROFILE})",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    try:
        config = load_runtime_config(args)
    except MiddlewareError as error:
        print(f"Failed to load middleware config: {error.message}", file=sys.stderr)
        return 1

    server = create_server(args.host, args.port, config)
    listen_host, listen_port = server.server_address
    print(
        (
            f"modeio-middleware listening on http://{listen_host}:{listen_port} "
            f"-> chat upstream {config.upstream_chat_completions_url} "
            f"-> responses upstream {config.upstream_responses_url}"
        ),
        file=sys.stderr,
    )

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Shutting down middleware...", file=sys.stderr)
    finally:
        server.shutdown()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
