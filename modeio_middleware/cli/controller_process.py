#!/usr/bin/env python3

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

from modeio_middleware.cli.setup_lib.common import HealthCheckResult, derive_health_url
from modeio_middleware.runtime_home import ensure_user_runtime_home

from .controller_state import ControllerStateStore


class ControllerProcessError(RuntimeError):
    pass


@dataclass(frozen=True)
class GatewayProcessStatus:
    running: bool
    healthy: bool
    pid: int | None
    host: str | None
    port: int | None
    health: HealthCheckResult | None
    stale: bool = False
    log_path: str | None = None
    config_path: str | None = None
    allow_remote_admin: bool = False

    def to_payload(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "running": self.running,
            "healthy": self.healthy,
            "pid": self.pid,
            "stale": self.stale,
            "allowRemoteAdmin": self.allow_remote_admin,
        }
        if self.host is not None:
            payload["host"] = self.host
        if self.port is not None:
            payload["port"] = self.port
        if self.log_path is not None:
            payload["logPath"] = self.log_path
        if self.config_path is not None:
            payload["configPath"] = self.config_path
        if self.health is not None:
            payload["health"] = {
                "checked": self.health.checked,
                "ok": self.health.ok,
                "statusCode": self.health.status_code,
                "message": self.health.message,
            }
        return payload


def _check_health_url(health_url: str, *, timeout_seconds: float = 2.0) -> HealthCheckResult:
    import json
    import urllib.error
    import urllib.request

    request = urllib.request.Request(health_url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            status_code = response.status
            body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as error:
        try:
            message = f"http_error_{error.code}"
        finally:
            error.close()
        return HealthCheckResult(
            checked=True,
            ok=False,
            status_code=error.code,
            message=message,
        )
    except Exception as error:  # pragma: no cover - best effort
        return HealthCheckResult(
            checked=True,
            ok=False,
            status_code=None,
            message=f"connection_failed:{type(error).__name__}",
        )

    if status_code != 200:
        return HealthCheckResult(
            checked=True,
            ok=False,
            status_code=status_code,
            message=f"unexpected_status:{status_code}",
        )

    try:
        payload = json.loads(body)
    except ValueError:
        return HealthCheckResult(
            checked=True,
            ok=False,
            status_code=status_code,
            message="invalid_json",
        )

    if isinstance(payload, dict) and payload.get("ok") is True:
        return HealthCheckResult(
            checked=True,
            ok=True,
            status_code=status_code,
            message="healthy",
        )

    return HealthCheckResult(
        checked=True,
        ok=False,
        status_code=status_code,
        message="unhealthy_payload",
    )


class GatewayProcessManager:
    def __init__(self, *, state_store: ControllerStateStore) -> None:
        self._state_store = state_store

    def _is_pid_alive(self, pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return False
        return True

    def _status_from_payload(self, payload: Dict[str, Any] | None) -> GatewayProcessStatus:
        if not payload:
            return GatewayProcessStatus(
                running=False,
                healthy=False,
                pid=None,
                host=None,
                port=None,
                health=None,
                log_path=str(self._state_store.log_path),
                config_path=str(self._state_store.config_path),
            )

        pid = int(payload.get("pid") or 0) or None
        host = payload.get("host")
        port = int(payload.get("port") or 0) or None
        allow_remote_admin = bool(payload.get("allowRemoteAdmin", False))
        if pid is None or host is None or port is None:
            self._state_store.clear_pid_payload()
            return GatewayProcessStatus(
                running=False,
                healthy=False,
                pid=None,
                host=None,
                port=None,
                health=None,
                stale=True,
                log_path=str(self._state_store.log_path),
                config_path=str(self._state_store.config_path),
                allow_remote_admin=allow_remote_admin,
            )

        if not self._is_pid_alive(pid):
            self._state_store.clear_pid_payload()
            return GatewayProcessStatus(
                running=False,
                healthy=False,
                pid=pid,
                host=str(host),
                port=port,
                health=None,
                stale=True,
                log_path=str(self._state_store.log_path),
                config_path=str(self._state_store.config_path),
                allow_remote_admin=allow_remote_admin,
            )

        health = _check_health_url(
            derive_health_url(f"http://{host}:{port}/v1"),
            timeout_seconds=2.0,
        )
        return GatewayProcessStatus(
            running=True,
            healthy=health.ok,
            pid=pid,
            host=str(host),
            port=port,
            health=health,
            stale=False,
            log_path=str(self._state_store.log_path),
            config_path=str(self._state_store.config_path),
            allow_remote_admin=allow_remote_admin,
        )

    def status(self) -> GatewayProcessStatus:
        return self._status_from_payload(self._state_store.load_pid_payload())

    def _build_command(self, *, host: str, port: int, allow_remote_admin: bool) -> list[str]:
        command = [
            sys.executable,
            "-m",
            "modeio_middleware.cli.gateway",
            "--host",
            host,
            "--port",
            str(port),
            "--config",
            str(self._state_store.config_path),
        ]
        if allow_remote_admin:
            command.append("--allow-remote-admin")
        return command

    def _build_env(self) -> Dict[str, str]:
        env = dict(os.environ)
        repo_root = str(Path(__file__).resolve().parents[2])
        existing_pythonpath = str(env.get("PYTHONPATH") or "").strip()
        if existing_pythonpath:
            env["PYTHONPATH"] = f"{repo_root}{os.pathsep}{existing_pythonpath}"
        else:
            env["PYTHONPATH"] = repo_root
        return env

    def start(
        self,
        *,
        host: str,
        port: int,
        allow_remote_admin: bool,
        startup_timeout_seconds: float = 15.0,
    ) -> GatewayProcessStatus:
        current = self.status()
        if (
            current.running
            and current.healthy
            and current.host == host
            and current.port == port
            and current.allow_remote_admin == allow_remote_admin
        ):
            return current
        if current.running:
            self.stop()

        ensure_user_runtime_home(self._state_store.config_path)
        self._state_store.log_path.parent.mkdir(parents=True, exist_ok=True)
        log_handle = self._state_store.log_path.open("a", encoding="utf-8")
        process = subprocess.Popen(
            self._build_command(
                host=host,
                port=port,
                allow_remote_admin=allow_remote_admin,
            ),
            cwd=str(Path(__file__).resolve().parents[2]),
            env=self._build_env(),
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=(os.name != "nt"),
        )
        log_handle.close()

        deadline = time.monotonic() + startup_timeout_seconds
        health_url = derive_health_url(f"http://{host}:{port}/v1")
        while time.monotonic() < deadline:
            if process.poll() is not None:
                break
            health = _check_health_url(health_url, timeout_seconds=1.0)
            if health.ok:
                self._state_store.save_pid_payload(
                    {
                        "pid": process.pid,
                        "host": host,
                        "port": port,
                        "allowRemoteAdmin": allow_remote_admin,
                        "configPath": str(self._state_store.config_path),
                    }
                )
                return self.status()
            time.sleep(0.2)

        try:
            process.terminate()
        except OSError:
            pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        self._state_store.clear_pid_payload()
        raise ControllerProcessError(
            f"middleware server failed to become healthy on http://{host}:{port}"
        )

    def stop(self) -> GatewayProcessStatus:
        payload = self._state_store.load_pid_payload()
        current = self._status_from_payload(payload)
        if not current.running or current.pid is None:
            self._state_store.clear_pid_payload()
            return GatewayProcessStatus(
                running=False,
                healthy=False,
                pid=None,
                host=current.host,
                port=current.port,
                health=None,
                stale=current.stale,
                log_path=current.log_path,
                config_path=current.config_path,
                allow_remote_admin=current.allow_remote_admin,
            )

        try:
            os.kill(current.pid, signal.SIGTERM)
        except OSError:
            pass

        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if not self._is_pid_alive(current.pid):
                self._state_store.clear_pid_payload()
                return GatewayProcessStatus(
                    running=False,
                    healthy=False,
                    pid=None,
                    host=current.host,
                    port=current.port,
                    health=None,
                    log_path=current.log_path,
                    config_path=current.config_path,
                    allow_remote_admin=current.allow_remote_admin,
                )
            time.sleep(0.1)

        try:
            os.kill(current.pid, signal.SIGKILL)
        except OSError:
            pass
        self._state_store.clear_pid_payload()
        return GatewayProcessStatus(
            running=False,
            healthy=False,
            pid=None,
            host=current.host,
            port=current.port,
            health=None,
            log_path=current.log_path,
            config_path=current.config_path,
            allow_remote_admin=current.allow_remote_admin,
        )
