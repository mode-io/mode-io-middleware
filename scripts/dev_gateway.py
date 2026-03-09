#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from modeio_middleware.dev_runtime import (  # noqa: E402
    DEFAULT_GATEWAY_HOST,
    DEFAULT_GATEWAY_PORT,
    apply_dev_runtime_env,
    dashboard_bundle_exists,
    dashboard_bundle_is_stale,
    health_url,
    reset_dev_runtime,
    resolve_dev_runtime_paths,
    review_url,
    should_use_dev_runtime,
    vite_dashboard_url,
)

REEXEC_ENV = "MODEIO_DEV_GATEWAY_REEXEC"


def _resolve_gateway_target(gateway_args: Sequence[str]) -> tuple[str, int]:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--host", default=DEFAULT_GATEWAY_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_GATEWAY_PORT)
    known, _ = parser.parse_known_args(list(gateway_args))
    return known.host, known.port


def _has_explicit_config_arg(gateway_args: Sequence[str]) -> bool:
    return any(arg == "--config" or arg.startswith("--config=") for arg in gateway_args)


def _health_status(url: str, timeout_seconds: int = 1) -> dict[str, object]:
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8", errors="replace")
            payload = json.loads(body)
    except urllib.error.HTTPError as error:
        return {
            "ok": False,
            "statusCode": error.code,
            "message": f"http_error_{error.code}",
        }
    except Exception as error:  # pragma: no cover - best effort path
        return {
            "ok": False,
            "statusCode": None,
            "message": f"connection_failed:{type(error).__name__}",
        }
    return {
        "ok": bool(isinstance(payload, dict) and payload.get("ok") is True),
        "statusCode": response.status,
        "message": "healthy" if isinstance(payload, dict) and payload.get("ok") is True else "unhealthy_payload",
    }


def _status_payload(
    *,
    runtime_home: Path | None,
    using_dev_runtime: bool,
    gateway_args: Sequence[str],
) -> dict[str, object]:
    host, port = _resolve_gateway_target(gateway_args)
    paths = resolve_dev_runtime_paths(REPO_ROOT, runtime_home)
    return {
        "mode": "repo-local-dev" if using_dev_runtime else "explicit-runtime-override",
        "repoRoot": str(paths.repo_root),
        "runtimeHome": str(paths.runtime_home),
        "configPath": str(paths.config_path),
        "configExists": paths.config_path.exists(),
        "pluginsDir": str(paths.plugins_dir),
        "pluginsDirExists": paths.plugins_dir.exists(),
        "tracePersistence": "ephemeral (in-memory request journal)",
        "dashboardBundleExists": dashboard_bundle_exists(paths),
        "dashboardBundleStale": dashboard_bundle_is_stale(paths),
        "reviewUrl": review_url(host, port),
        "viteUrl": vite_dashboard_url(),
        "health": _health_status(health_url(host, port)),
    }


def _print_status(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _build_dashboard() -> None:
    subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / "build_dashboard.sh")],
        cwd=REPO_ROOT,
        check=True,
    )


def _repo_venv_python() -> Path | None:
    candidates = [
        REPO_ROOT / ".venv" / "bin" / "python",
        REPO_ROOT / ".venv" / "Scripts" / "python.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _parse_start_args(argv: Sequence[str]) -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(
        prog="python scripts/dev_gateway.py",
        description=(
            "Maintainer gateway entrypoint that defaults to a repo-local MODEIO runtime "
            "under .modeio-dev instead of ~/.config/modeio."
        ),
    )
    parser.add_argument("--fresh", action="store_true", help="Delete the repo-local dev runtime before starting.")
    parser.add_argument("--runtime-home", help="Override the repo-local runtime root used for MODEIO_HOME.")
    parser.add_argument("--build-dashboard", action="store_true", help="Rebuild the bundled dashboard assets before starting.")
    parser.add_argument("--status", action="store_true", help="Print repo-local runtime and health information, then exit.")
    known, gateway_args = parser.parse_known_args(list(argv))
    return known, gateway_args


def _parse_status_or_reset_args(argv: Sequence[str], *, command: str) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog=f"python scripts/dev_gateway.py {command}",
        description=f"{command.capitalize()} the repo-local middleware dev runtime.",
    )
    parser.add_argument("--runtime-home", help="Override the repo-local runtime root used for MODEIO_HOME.")
    if command == "status":
        parser.add_argument("--host", default=DEFAULT_GATEWAY_HOST)
        parser.add_argument("--port", type=int, default=DEFAULT_GATEWAY_PORT)
    return parser.parse_args(list(argv))


def _run_start(argv: Sequence[str]) -> int:
    parsed, gateway_args = _parse_start_args(argv)
    runtime_home = Path(parsed.runtime_home).expanduser() if parsed.runtime_home else None
    paths = resolve_dev_runtime_paths(REPO_ROOT, runtime_home)
    using_dev_runtime = should_use_dev_runtime(gateway_args, os.environ)
    if (
        not using_dev_runtime
        and os.environ.get(REEXEC_ENV) == "1"
        and not os.environ.get("MODEIO_MIDDLEWARE_CONFIG")
        and not _has_explicit_config_arg(gateway_args)
        and os.environ.get("MODEIO_HOME") == str(paths.runtime_home)
    ):
        using_dev_runtime = True

    if parsed.status:
        _print_status(
            _status_payload(
                runtime_home=runtime_home,
                using_dev_runtime=using_dev_runtime,
                gateway_args=gateway_args,
            )
        )
        return 0

    if using_dev_runtime and parsed.fresh:
        reset_dev_runtime(paths.runtime_home)

    if parsed.build_dashboard:
        _build_dashboard()

    if using_dev_runtime:
        env_updates = apply_dev_runtime_env(runtime_home=paths.runtime_home, env=os.environ)
        os.environ["MODEIO_HOME"] = env_updates["MODEIO_HOME"]

    try:
        from modeio_middleware.cli.gateway import main as gateway_main
    except ModuleNotFoundError as error:
        venv_python = _repo_venv_python()
        if (
            venv_python is not None
            and Path(sys.executable).absolute() != venv_python.absolute()
            and os.environ.get(REEXEC_ENV) != "1"
        ):
            reexec_env = dict(os.environ)
            reexec_env[REEXEC_ENV] = "1"
            os.execvpe(
                str(venv_python),
                [str(venv_python), str(SCRIPT_DIR / "dev_gateway.py"), *sys.argv[1:]],
                reexec_env,
            )

        print(
            (
                "[dev-gateway] missing runtime dependency "
                f"({error.name}). Install the repo environment first, for example:\n"
                "  python -m pip install -e ."
            ),
            file=sys.stderr,
        )
        return 1

    host, port = _resolve_gateway_target(gateway_args)
    status_payload = _status_payload(
        runtime_home=runtime_home,
        using_dev_runtime=using_dev_runtime,
        gateway_args=gateway_args,
    )
    print(
        (
            f"[dev-gateway] runtime={status_payload['mode']} "
            f"home={status_payload['runtimeHome']} "
            f"review={review_url(host, port)}"
        ),
        file=sys.stderr,
    )
    if status_payload["dashboardBundleStale"] and not parsed.build_dashboard:
        print(
            "[dev-gateway] dashboard bundle may be stale; run with --build-dashboard after frontend changes.",
            file=sys.stderr,
        )

    return gateway_main(gateway_args)


def _run_reset(argv: Sequence[str]) -> int:
    parsed = _parse_status_or_reset_args(argv, command="reset")
    runtime_home = Path(parsed.runtime_home).expanduser() if parsed.runtime_home else None
    paths = resolve_dev_runtime_paths(REPO_ROOT, runtime_home)
    reset_dev_runtime(paths.runtime_home)
    print(f"Removed dev runtime: {paths.runtime_home}")
    return 0


def _run_status(argv: Sequence[str]) -> int:
    parsed = _parse_status_or_reset_args(argv, command="status")
    runtime_home = Path(parsed.runtime_home).expanduser() if parsed.runtime_home else None
    gateway_args = ["--host", parsed.host, "--port", str(parsed.port)]
    using_dev_runtime = should_use_dev_runtime(gateway_args, os.environ)
    _print_status(
        _status_payload(
            runtime_home=runtime_home,
            using_dev_runtime=using_dev_runtime,
            gateway_args=gateway_args,
        )
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    if args and args[0] in {"reset", "status"}:
        command = args[0]
        remainder = args[1:]
    else:
        command = "start"
        remainder = args

    if command == "reset":
        return _run_reset(remainder)
    if command == "status":
        return _run_status(remainder)
    return _run_start(remainder)


if __name__ == "__main__":
    raise SystemExit(main())
