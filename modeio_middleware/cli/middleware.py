#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

from modeio_middleware.cli.setup_lib.common import detect_os_name

from .controller_service import ControllerService, HarnessPathOverrides
from .controller_state import (
    ControllerStateStore,
    DEFAULT_CONTROLLER_HOST,
    DEFAULT_CONTROLLER_PORT,
)
from .harness_adapters import HarnessAdapterRegistry


def _detect_shell(os_name: str, env: Dict[str, str]) -> str:
    if os_name == "windows":
        return "powershell"
    shell_path = env.get("SHELL", "").lower()
    if shell_path.endswith("zsh"):
        return "zsh"
    if shell_path.endswith("fish"):
        return "fish"
    return "bash"


def _build_state_store(args: argparse.Namespace) -> ControllerStateStore:
    config_path = Path(args.config).expanduser() if getattr(args, "config", None) else None
    return ControllerStateStore(config_path=config_path)


def _build_service(args: argparse.Namespace) -> ControllerService:
    return ControllerService(
        state_store=_build_state_store(args),
        registry=HarnessAdapterRegistry(),
    )


def _build_overrides(args: argparse.Namespace, harness_name: str | None = None) -> Dict[str, HarnessPathOverrides]:
    normalized = HarnessAdapterRegistry().normalize_name(harness_name or "")
    overrides: Dict[str, HarnessPathOverrides] = {}
    opencode_overrides = HarnessPathOverrides(
        config_path=Path(args.opencode_config_path).expanduser()
        if getattr(args, "opencode_config_path", None)
        else None,
    )
    openclaw_overrides = HarnessPathOverrides(
        config_path=Path(args.openclaw_config_path).expanduser()
        if getattr(args, "openclaw_config_path", None)
        else None,
        models_cache_path=Path(args.openclaw_models_cache_path).expanduser()
        if getattr(args, "openclaw_models_cache_path", None)
        else None,
    )
    claude_overrides = HarnessPathOverrides(
        config_path=Path(args.claude_settings_path).expanduser()
        if getattr(args, "claude_settings_path", None)
        else None,
    )
    codex_overrides = HarnessPathOverrides(
        config_path=Path(args.codex_config_path).expanduser()
        if getattr(args, "codex_config_path", None)
        else None,
    )
    if not normalized or normalized == "opencode":
        overrides["opencode"] = opencode_overrides
    if not normalized or normalized == "openclaw":
        overrides["openclaw"] = openclaw_overrides
    if not normalized or normalized == "claude":
        overrides["claude"] = claude_overrides
    if not normalized or normalized == "codex":
        overrides["codex"] = codex_overrides
    return overrides


def _print_payload(payload: Dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    if payload.get("success") is False:
        reason = str(payload.get("reason") or "operation failed")
        print(reason, file=sys.stderr)
        return
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _host_port_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--host", default=None, help=f"Gateway host (default stored or {DEFAULT_CONTROLLER_HOST})")
    parser.add_argument("--port", type=int, default=None, help=f"Gateway port (default stored or {DEFAULT_CONTROLLER_PORT})")
    parser.add_argument(
        "--allow-remote-admin",
        action="store_true",
        help="Allow admin routes when binding on a non-loopback host",
    )


def _common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    parser.add_argument(
        "--config",
        default=None,
        help="Middleware config JSON path; controller state is stored beside it",
    )
    parser.add_argument("--os-name", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--shell", default="auto", help=argparse.SUPPRESS)
    parser.add_argument("--codex-config-path", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--opencode-config-path", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--openclaw-config-path", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--openclaw-models-cache-path", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--claude-settings-path", default=None, help=argparse.SUPPRESS)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="middleware",
        description="Unified controller for enabling, disabling, and running supported middleware harness integrations.",
    )
    _common_args(parser)
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser("inspect", help="Inspect current harness-selected state")
    _common_args(inspect_parser)
    _host_port_args(inspect_parser)
    inspect_parser.add_argument("harness", nargs="?", help="Harness to inspect")

    enable_parser = subparsers.add_parser("enable", help="Enable one supported harness and start middleware")
    _common_args(enable_parser)
    _host_port_args(enable_parser)
    enable_parser.add_argument("harness", help="Harness to enable")

    disable_parser = subparsers.add_parser("disable", help="Disable one harness or all enabled harnesses")
    _common_args(disable_parser)
    disable_parser.add_argument("harness", nargs="?", help="Harness to disable")
    disable_parser.add_argument("--all", action="store_true", help="Disable all enabled harnesses")

    status_parser = subparsers.add_parser("status", help="Show current server and enabled harness state")
    _common_args(status_parser)

    start_parser = subparsers.add_parser("start", help="Start middleware for already-enabled harnesses")
    _common_args(start_parser)
    _host_port_args(start_parser)

    stop_parser = subparsers.add_parser("stop", help="Stop the middleware server without detaching harnesses")
    _common_args(stop_parser)

    restart_parser = subparsers.add_parser("restart", help="Restart middleware for already-enabled harnesses")
    _common_args(restart_parser)
    _host_port_args(restart_parser)

    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    if args.command == "disable" and not args.all and not args.harness:
        raise SystemExit("disable requires a harness name or --all")
    if args.command == "disable" and args.all and args.harness:
        raise SystemExit("disable accepts either a harness name or --all, not both")
    env = dict(os.environ)
    os_name = detect_os_name(args.os_name)
    shell = args.shell if args.shell != "auto" else _detect_shell(os_name, env)
    service = _build_service(args)

    if args.command == "inspect":
        payload = service.inspect(
            harness_name=args.harness,
            env=env,
            os_name=os_name,
            shell=shell,
            host=args.host,
            port=args.port,
            allow_remote_admin=args.allow_remote_admin,
            overrides=_build_overrides(args, args.harness),
        )
        _print_payload(payload, as_json=args.json)
        return 0

    if args.command == "enable":
        payload = service.enable(
            harness_name=args.harness,
            env=env,
            os_name=os_name,
            shell=shell,
            host=args.host,
            port=args.port,
            allow_remote_admin=args.allow_remote_admin,
            overrides=_build_overrides(args, args.harness).get(
                HarnessAdapterRegistry().normalize_name(args.harness),
                HarnessPathOverrides(),
            ),
        )
        _print_payload(payload, as_json=args.json)
        if payload.get("success"):
            return 0
        return 2 if payload.get("unsupported") else 1

    if args.command == "disable":
        if args.all:
            payload = service.disable_all(
                env=env,
                os_name=os_name,
                shell=shell,
            )
            _print_payload(payload, as_json=args.json)
            return 0 if payload.get("success") else 1
        payload = service.disable(
            harness_name=args.harness,
            env=env,
            os_name=os_name,
            shell=shell,
        )
        _print_payload(payload, as_json=args.json)
        if payload.get("success"):
            return 0
        return 2 if payload.get("unsupported") else 1

    if args.command == "status":
        payload = service.status(
            env=env,
            os_name=os_name,
            shell=shell,
        )
        _print_payload(payload, as_json=args.json)
        return 0

    if args.command == "start":
        payload = service.start(
            env=env,
            os_name=os_name,
            shell=shell,
            host=args.host,
            port=args.port,
            allow_remote_admin=args.allow_remote_admin,
        )
        _print_payload(payload, as_json=args.json)
        if payload.get("success"):
            return 0
        return 2 if payload.get("unsupported") else 1

    if args.command == "stop":
        payload = service.stop()
        _print_payload(payload, as_json=args.json)
        return 0 if payload.get("success") else 1

    if args.command == "restart":
        payload = service.restart(
            env=env,
            os_name=os_name,
            shell=shell,
            host=args.host,
            port=args.port,
            allow_remote_admin=args.allow_remote_admin,
        )
        _print_payload(payload, as_json=args.json)
        if payload.get("success"):
            return 0
        return 2 if payload.get("unsupported") else 1

    raise SystemExit(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
