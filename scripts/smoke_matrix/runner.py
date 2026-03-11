from __future__ import annotations

import gzip
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

try:  # Python 3.14+
    from compression import zstd as _zstd_codec
except Exception:  # pragma: no cover
    _zstd_codec = None

from smoke_matrix.agents import build_agent_command as _build_agent_command
from smoke_matrix.common import (
    free_port as _free_port,
    load_tap_events as _load_tap_events,
    run_command_capture as _run_command_capture,
    tap_token_metrics as _tap_token_metrics,
    tap_window_metrics as _tap_window_metrics,
    wait_for_url as _wait_for_url,
    write_json as _write_json,
    write_text as _write_text,
)
from smoke_matrix.models import OpenClawFamilyScenario, SmokeAgentReport
from smoke_matrix.openclaw_family import _slug_token_part
from smoke_matrix.outcome import classify_agent_outcome
from smoke_matrix.sandbox import configure_openclaw_supported_family as _configure_openclaw_supported_family

def run_json_cli_command(
    *,
    command: Sequence[str],
    cwd: Path,
    env: Dict[str, str],
    timeout_seconds: int,
) -> Tuple[Dict[str, object], Dict[str, object]]:
    result = _run_command_capture(
        command=command,
        cwd=cwd,
        env=env,
        timeout_seconds=timeout_seconds,
    )
    stdout = str(result["stdout"])
    try:
        payload = json.loads(stdout)
    except ValueError as error:
        raise RuntimeError(
            f"command returned non-JSON output: {stdout[:400]}"
        ) from error
    if not isinstance(payload, dict):
        raise RuntimeError("JSON command did not return an object payload")
    return payload, result


def _controller_common_args(
    *,
    controller_config_path: Path,
    opencode_config_path: Path,
    openclaw_config_path: Path,
    openclaw_models_cache_path: Path,
    claude_settings_path: Path,
    codex_config_path: Path | None = None,
) -> list[str]:
    command = [
        "--config",
        str(controller_config_path),
        "--opencode-config-path",
        str(opencode_config_path),
        "--openclaw-config-path",
        str(openclaw_config_path),
        "--openclaw-models-cache-path",
        str(openclaw_models_cache_path),
        "--claude-settings-path",
        str(claude_settings_path),
    ]
    if codex_config_path is not None:
        command.extend(["--codex-config-path", str(codex_config_path)])
    return command


def run_controller_inspect(
    *,
    controller_command: Sequence[str],
    repo_root: Path,
    env: Dict[str, str],
    controller_config_path: Path,
    opencode_config_path: Path,
    openclaw_config_path: Path,
    openclaw_models_cache_path: Path,
    claude_settings_path: Path,
    codex_config_path: Path | None,
    timeout_seconds: int,
    harness_name: str | None = None,
    host: str | None = None,
    port: int | None = None,
) -> Dict[str, object]:
    command = [
        *controller_command,
        "inspect",
        *( [harness_name] if harness_name else [] ),
        "--json",
        *_controller_common_args(
            controller_config_path=controller_config_path,
            opencode_config_path=opencode_config_path,
            openclaw_config_path=openclaw_config_path,
            openclaw_models_cache_path=openclaw_models_cache_path,
            claude_settings_path=claude_settings_path,
            codex_config_path=codex_config_path,
        ),
    ]
    if host is not None:
        command.extend(["--host", host])
    if port is not None:
        command.extend(["--port", str(port)])
    payload, result = run_json_cli_command(
        command=command,
        cwd=repo_root,
        env=env,
        timeout_seconds=timeout_seconds,
    )
    if int(result["exitCode"]) != 0 or not payload.get("success"):
        raise RuntimeError(
            f"inspect failed: exit={result['exitCode']} payload={payload}"
        )
    return payload


def run_controller_enable(
    *,
    controller_command: Sequence[str],
    repo_root: Path,
    env: Dict[str, str],
    harness_name: str,
    controller_config_path: Path,
    opencode_config_path: Path,
    openclaw_config_path: Path,
    openclaw_models_cache_path: Path,
    claude_settings_path: Path,
    codex_config_path: Path | None,
    timeout_seconds: int,
    host: str,
    port: int,
    allow_remote_admin: bool = False,
) -> Dict[str, object]:
    command = [
        *controller_command,
        "enable",
        harness_name,
        "--json",
        "--host",
        host,
        "--port",
        str(port),
        *_controller_common_args(
            controller_config_path=controller_config_path,
            opencode_config_path=opencode_config_path,
            openclaw_config_path=openclaw_config_path,
            openclaw_models_cache_path=openclaw_models_cache_path,
            claude_settings_path=claude_settings_path,
            codex_config_path=codex_config_path,
        ),
    ]
    if allow_remote_admin:
        command.append("--allow-remote-admin")
    payload, result = run_json_cli_command(
        command=command,
        cwd=repo_root,
        env=env,
        timeout_seconds=timeout_seconds,
    )
    if int(result["exitCode"]) != 0 or not payload.get("success"):
        raise RuntimeError(
            f"enable failed for {harness_name}: exit={result['exitCode']} payload={payload}"
        )
    return payload


def run_controller_disable(
    *,
    controller_command: Sequence[str],
    repo_root: Path,
    env: Dict[str, str],
    harness_name: str,
    controller_config_path: Path,
    timeout_seconds: int,
) -> Dict[str, object]:
    payload, result = run_json_cli_command(
        command=[
            *controller_command,
            "disable",
            harness_name,
            "--json",
            "--config",
            str(controller_config_path),
        ],
        cwd=repo_root,
        env=env,
        timeout_seconds=timeout_seconds,
    )
    if int(result["exitCode"]) != 0 or not payload.get("success"):
        raise RuntimeError(
            f"disable failed for {harness_name}: exit={result['exitCode']} payload={payload}"
        )
    return payload


def run_controller_disable_all(
    *,
    controller_command: Sequence[str],
    repo_root: Path,
    env: Dict[str, str],
    controller_config_path: Path,
    timeout_seconds: int,
) -> Dict[str, object]:
    payload, result = run_json_cli_command(
        command=[
            *controller_command,
            "disable",
            "--all",
            "--json",
            "--config",
            str(controller_config_path),
        ],
        cwd=repo_root,
        env=env,
        timeout_seconds=timeout_seconds,
    )
    if int(result["exitCode"]) != 0 or not payload.get("success"):
        raise RuntimeError(
            f"disable --all failed: exit={result['exitCode']} payload={payload}"
        )
    return payload


def run_controller_status(
    *,
    controller_command: Sequence[str],
    repo_root: Path,
    env: Dict[str, str],
    controller_config_path: Path,
    timeout_seconds: int,
) -> Dict[str, object]:
    payload, result = run_json_cli_command(
        command=[
            *controller_command,
            "status",
            "--json",
            "--config",
            str(controller_config_path),
        ],
        cwd=repo_root,
        env=env,
        timeout_seconds=timeout_seconds,
    )
    if int(result["exitCode"]) != 0 or not payload.get("success"):
        raise RuntimeError(
            f"status failed: exit={result['exitCode']} payload={payload}"
        )
    return payload


def start_logged_process(
    *,
    command: Sequence[str],
    cwd: Path,
    env: Dict[str, str],
    log_path: Path,
) -> Tuple[subprocess.Popen, object]:
    handle = log_path.open("w", encoding="utf-8")
    process = subprocess.Popen(
        list(command),
        cwd=str(cwd),
        env=env,
        stdout=handle,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return process, handle


def stop_process(process: Optional[subprocess.Popen]) -> None:
    if process is None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def close_handle(handle: Optional[object]) -> None:
    if handle is not None:
        handle.close()


def skipped_agent_report(
    *,
    agent: str,
    report_name: str,
    diagnostic: str,
    product_ok: bool = False,
) -> Dict[str, object]:
    return {
        "name": agent,
        "reportName": report_name,
        "exitCode": 0,
        "timedOut": False,
        "durationMs": 0,
        "stdoutPath": "",
        "stderrPath": "",
        "tokenInOutput": False,
        "tapKind": "upstream_tap",
        "tap": {
            "window": {"eventCount": 0, "successCount": 0, "paths": []},
            "token": {"eventCount": 0, "tokenFound": False},
            "upstreamStatuses": [],
            "matchedPaths": [],
        },
        "diagnostic": diagnostic,
        "ok": False,
        "outcome": "skipped",
        "productOk": product_ok,
    }


def run_agent_check(
    *,
    agent: str,
    index: int,
    run_id: str,
    report_name: str | None,
    model: str,
    claude_model: str,
    repo_root: Path,
    work_dir: Path,
    run_dir: Path,
    env: Dict[str, str],
    timeout_seconds: int,
    claude_settings_path: Optional[Path],
    tap_jsonl_path: Path,
    expected_tap_path_fragment: str | None = None,
    prompt_text: str | None = None,
) -> Dict[str, object]:
    token_label = _slug_token_part(report_name or agent)
    token = f"SMOKE_{token_label.upper()}_{index}_{run_id.upper()}"
    file_slug = _slug_token_part(report_name or agent)
    codex_message_path = run_dir / f"{file_slug}-last-message.txt"
    command = _build_agent_command(
        agent=agent,
        token=token,
        model=model,
        claude_model=claude_model,
        work_dir=work_dir,
        codex_output_path=codex_message_path,
        claude_settings_path=claude_settings_path,
        timeout_seconds=timeout_seconds,
        prompt_text=prompt_text,
    )

    before_count = len(_load_tap_events(tap_jsonl_path))
    agent_env = dict(os.environ) if agent == "claude" else env
    if agent == "codex":
        codex_base_url = str(env.get("MODEIO_SMOKE_CODEX_BASE_URL") or "").strip()
        if codex_base_url:
            agent_env["OPENAI_BASE_URL"] = codex_base_url
    else:
        agent_env.pop("OPENAI_BASE_URL", None)
    result = _run_command_capture(
        command=command,
        cwd=work_dir,
        env=agent_env,
        timeout_seconds=timeout_seconds,
    )

    stdout_path = run_dir / f"{file_slug}.stdout.log"
    stderr_path = run_dir / f"{file_slug}.stderr.log"
    _write_text(stdout_path, str(result["stdout"]))
    _write_text(stderr_path, str(result["stderr"]))

    output_text = stdout_path.read_text(encoding="utf-8")
    if agent == "codex" and codex_message_path.exists():
        output_text = codex_message_path.read_text(encoding="utf-8")

    after_events = _load_tap_events(tap_jsonl_path)
    new_events = after_events[before_count:]
    tap_window = _tap_window_metrics(new_events)
    tap_token = _tap_token_metrics(new_events, token)
    matched_paths = [
        path
        for path in tap_window.get("paths", [])
        if isinstance(path, str)
        and (
            expected_tap_path_fragment is None
            or expected_tap_path_fragment in path
        )
    ]
    upstream_statuses = []
    for event in new_events:
        if not isinstance(event, dict):
            continue
        response_obj = event.get("response")
        status = response_obj.get("status") if isinstance(response_obj, dict) else None
        if isinstance(status, int):
            upstream_statuses.append(status)
    transport_check_ok = (
        int(result["exitCode"]) == 0
        and int(tap_window["eventCount"]) >= 1
        and int(tap_window["successCount"]) >= 1
        and (
            expected_tap_path_fragment is None
            or bool(matched_paths)
        )
    )
    stdout_text = str(result["stdout"])
    stderr_text = str(result["stderr"])
    classified = classify_agent_outcome(
        agent=agent,
        exit_code=int(result["exitCode"]),
        transport_check_ok=transport_check_ok,
        stdout_text=stdout_text,
        stderr_text=stderr_text,
        upstream_statuses=upstream_statuses,
        expected_tap_path_fragment=expected_tap_path_fragment,
    )

    return SmokeAgentReport(
        name=agent,
        report_name=report_name or agent,
        exit_code=int(result["exitCode"]),
        timed_out=bool(result["timedOut"]),
        duration_ms=int(result["durationMs"]),
        stdout_path=str(stdout_path),
        stderr_path=str(stderr_path),
        token_in_output=token in output_text,
        tap_kind=classified.tap_kind,
        tap={
            "window": tap_window,
            "token": tap_token,
            "upstreamStatuses": upstream_statuses,
            "matchedPaths": matched_paths,
        },
        diagnostic=classified.diagnostic,
        ok=transport_check_ok,
        outcome=classified.outcome,
        product_ok=classified.product_ok,
        extras={
            "token": token,
            "command": command,
        },
    ).to_dict()


def run_openclaw_family_checks(
    *,
    controller_command: Sequence[str],
    repo_root: Path,
    work_dir: Path,
    env: Dict[str, str],
    controller_config_path: Path,
    openclaw_config_path: Path,
    openclaw_models_cache_path: Path,
    opencode_config_path: Path,
    claude_settings_path: Path,
    codex_config_path: Path | None,
    run_dir: Path,
    run_id: str,
    timeout_seconds: int,
    gateway_host: str,
    gateway_port: int,
    scenarios: Sequence[OpenClawFamilyScenario],
    prompt_text: str | None = None,
) -> List[Dict[str, object]]:
    reports: List[Dict[str, object]] = []
    for index, scenario in enumerate(scenarios, start=1):
        if scenario.skipped:
            reports.append(
                {
                    "name": "openclaw",
                    "reportName": scenario.name or f"openclaw:{index}",
                    "family": scenario.family,
                    "ok": False,
                    "outcome": "product_failed",
                    "productOk": False,
                    "diagnostic": str(
                        scenario.reason or "OpenClaw current state is unsupported for middleware smoke"
                    ),
                    "tap": {"window": {"eventCount": 0, "successCount": 0, "paths": []}},
                }
            )
            continue
        if scenario.error:
            reports.append(
                {
                    "name": "openclaw",
                    "reportName": scenario.name or f"openclaw:{index}",
                    "family": scenario.family,
                    "ok": False,
                    "outcome": "product_failed",
                    "productOk": False,
                    "diagnostic": str(
                        scenario.reason or "OpenClaw family scenario is unresolved"
                    ),
                    "tap": {"window": {"eventCount": 0, "successCount": 0, "paths": []}},
                }
            )
            continue

        family = str(scenario.family or "")
        provider_key = str(scenario.provider_key or "")
        real_base_url = str(scenario.real_base_url or "").strip()
        if not provider_key or not real_base_url:
            reports.append(
                {
                    "name": "openclaw",
                    "reportName": scenario.name or f"openclaw:{index}",
                    "family": family,
                    "ok": False,
                    "outcome": "product_failed",
                    "productOk": False,
                    "diagnostic": "OpenClaw family scenario is missing provider or upstream base URL.",
                    "tap": {"window": {"eventCount": 0, "successCount": 0, "paths": []}},
                }
            )
            continue

        family_slug = _slug_token_part(str(scenario.name or family))
        tap_jsonl_path = run_dir / f"{family_slug}-tap-exchanges.jsonl"
        tap_stdout_path = run_dir / f"{family_slug}-tap.log"
        tap_body_dir = run_dir / f"{family_slug}-tap-bodies"
        tap_port = _free_port()
        family_tap_base_url = f"http://{gateway_host}:{tap_port}"
        tap_command = [
            sys.executable,
            str(repo_root / "scripts" / "upstream_tap_proxy.py"),
            "--host",
            gateway_host,
            "--port",
            str(tap_port),
            "--target-base-url",
            real_base_url,
            "--log-jsonl",
            str(tap_jsonl_path),
            "--body-dir",
            str(tap_body_dir),
        ]
        tap_process: Optional[subprocess.Popen] = None
        tap_log_handle = None
        try:
            tap_process, tap_log_handle = start_logged_process(
                command=tap_command,
                cwd=repo_root,
                env=env,
                log_path=tap_stdout_path,
            )
            if not _wait_for_url(
                f"{family_tap_base_url}/healthz",
                timeout_seconds=max(10, min(timeout_seconds, 40)),
            ):
                raise RuntimeError(
                    f"OpenClaw family tap proxy failed to become healthy for {family}"
                )

            family_base_url = (
                family_tap_base_url
                if family == "anthropic-messages"
                else f"{family_tap_base_url}/v1"
            )
            scenario_patch = _configure_openclaw_supported_family(
                config_path=openclaw_config_path,
                models_cache_path=openclaw_models_cache_path,
                provider_key=provider_key,
                model_ref=str(scenario.model_ref or ""),
                api_family=family,
                base_url=family_base_url,
                real_base_url=family_base_url,
                provider_fields=dict(scenario.provider_fields or {}),
            )
            scenario_patch_path = run_dir / f"{family_slug}-scenario.json"
            _write_json(scenario_patch_path, scenario_patch)

            enable_payload = run_controller_enable(
                controller_command=controller_command,
                repo_root=repo_root,
                env=env,
                harness_name="openclaw",
                controller_config_path=controller_config_path,
                opencode_config_path=opencode_config_path,
                openclaw_config_path=openclaw_config_path,
                openclaw_models_cache_path=openclaw_models_cache_path,
                claude_settings_path=claude_settings_path,
                codex_config_path=codex_config_path,
                timeout_seconds=timeout_seconds,
                host=gateway_host,
                port=gateway_port,
            )

            agent_report = run_agent_check(
                agent="openclaw",
                index=index,
                run_id=run_id,
                report_name=str(scenario.name or f"openclaw:{family}"),
                model=str(scenario.model_ref or ""),
                claude_model="",
                repo_root=repo_root,
                work_dir=work_dir,
                run_dir=run_dir,
                env=env,
                timeout_seconds=timeout_seconds,
                claude_settings_path=None,
                tap_jsonl_path=tap_jsonl_path,
                expected_tap_path_fragment=str(
                    scenario.expected_tap_path_fragment or ""
                )
                or None,
                prompt_text=prompt_text,
            )
            agent_report["family"] = family
            agent_report["providerKey"] = provider_key
            agent_report["modelRef"] = scenario.model_ref
            agent_report["realBaseUrl"] = real_base_url
            agent_report["tap"]["logPath"] = str(tap_jsonl_path)
            agent_report["tap"]["stdoutPath"] = str(tap_stdout_path)
            agent_report["scenarioPatch"] = scenario_patch
            agent_report["controller"] = enable_payload
            reports.append(agent_report)
        except Exception as error:
            reports.append(
                {
                    "name": "openclaw",
                    "reportName": str(scenario.name or f"openclaw:{family}"),
                    "family": family,
                    "providerKey": provider_key,
                    "modelRef": scenario.model_ref,
                    "realBaseUrl": real_base_url,
                    "ok": False,
                    "outcome": "product_failed",
                    "productOk": False,
                    "diagnostic": str(error),
                    "tap": {
                        "window": {"eventCount": 0, "successCount": 0, "paths": []},
                        "logPath": str(tap_jsonl_path),
                        "stdoutPath": str(tap_stdout_path),
                    },
                }
            )
        finally:
            try:
                run_controller_disable(
                    controller_command=controller_command,
                    repo_root=repo_root,
                    env=env,
                    harness_name="openclaw",
                    controller_config_path=controller_config_path,
                    timeout_seconds=timeout_seconds,
                )
            except Exception:
                pass
            stop_process(tap_process)
            close_handle(tap_log_handle)
    return reports


def request_with_bytes(
    *,
    method: str,
    url: str,
    body: Optional[bytes],
    headers: Dict[str, str],
    timeout_seconds: int,
) -> Dict[str, object]:
    request = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers=headers,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read()
            status = int(response.status)
            response_headers = dict(response.headers.items())
    except urllib.error.HTTPError as error:
        raw = error.read()
        status = int(error.code)
        response_headers = dict(error.headers.items()) if error.headers else {}

    body_text = raw.decode("utf-8", errors="replace")
    payload = None
    try:
        parsed = json.loads(body_text)
        if isinstance(parsed, dict):
            payload = parsed
    except ValueError:
        payload = None

    return {
        "status": status,
        "headers": response_headers,
        "bodyText": body_text,
        "payload": payload,
    }


def run_gateway_smoke_checks(
    *,
    gateway_root_url: str,
    request_base_url: str,
    model: str,
    run_id: str,
    timeout_seconds: int,
    tap_jsonl_path: Path,
) -> Sequence[Dict[str, object]]:
    checks = []
    codex_native_mode = "/clients/codex/v1" in request_base_url

    def _append(
        name: str,
        ok: bool,
        details: Dict[str, object],
        *,
        outcome: str = "product_failed",
    ) -> None:
        checks.append(
            {
                "name": name,
                "ok": ok,
                "outcome": outcome if not ok else "passed",
                "productOk": ok or outcome in {"external_blocked", "warning", "not_applicable_transport"},
                **details,
            }
        )

    health_result = request_with_bytes(
        method="GET",
        url=f"{gateway_root_url}/healthz",
        body=None,
        headers={},
        timeout_seconds=timeout_seconds,
    )
    health_payload = health_result.get("payload")
    health_ok = bool(
        health_result.get("status") == 200
        and isinstance(health_payload, dict)
        and health_payload.get("ok") is True
    )
    _append(
        "gateway-healthz",
        health_ok,
        {
            "status": health_result.get("status"),
        },
    )

    before_count = len(_load_tap_events(tap_jsonl_path))
    route_result = request_with_bytes(
        method="POST",
        url=f"{request_base_url}/not-a-real-route",
        body=json.dumps({"probe": run_id}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        timeout_seconds=timeout_seconds,
    )
    after_count = len(_load_tap_events(tap_jsonl_path))
    route_payload = route_result.get("payload")
    route_ok = bool(
        route_result.get("status") == 404
        and isinstance(route_payload, dict)
        and isinstance(route_payload.get("error"), dict)
        and route_payload["error"].get("code") == "MODEIO_ROUTE_NOT_FOUND"
        and after_count == before_count
    )
    _append(
        "route-not-found-no-upstream",
        route_ok,
        {
            "status": route_result.get("status"),
            "tapEventDelta": after_count - before_count,
        },
    )

    unsupported_raw = json.dumps(
        {
            "model": model,
            "input": f"SMOKE_UNSUPPORTED_ENCODING_{run_id}",
            "modeio": {"profile": "dev"},
        }
    ).encode("utf-8")
    before_count = len(_load_tap_events(tap_jsonl_path))
    unsupported_result = request_with_bytes(
        method="POST",
        url=f"{request_base_url}/responses",
        body=unsupported_raw,
        headers={
            "Content-Type": "application/json",
            "Content-Encoding": "snappy",
        },
        timeout_seconds=timeout_seconds,
    )
    after_count = len(_load_tap_events(tap_jsonl_path))
    unsupported_payload = unsupported_result.get("payload")
    unsupported_ok = bool(
        unsupported_result.get("status") == 400
        and isinstance(unsupported_payload, dict)
        and isinstance(unsupported_payload.get("error"), dict)
        and unsupported_payload["error"].get("code") == "MODEIO_VALIDATION_ERROR"
        and after_count == before_count
    )
    _append(
        "unsupported-encoding-no-upstream",
        unsupported_ok,
        {
            "status": unsupported_result.get("status"),
            "tapEventDelta": after_count - before_count,
        },
    )

    gzip_raw = json.dumps(
        {
            "model": model,
            "input": f"SMOKE_GZIP_{run_id}",
            "modeio": {"profile": "dev"},
        }
    ).encode("utf-8")
    before_count = len(_load_tap_events(tap_jsonl_path))
    gzip_result = request_with_bytes(
        method="POST",
        url=f"{request_base_url}/responses",
        body=gzip.compress(gzip_raw),
        headers={
            "Content-Type": "application/json",
            "Content-Encoding": "gzip",
        },
        timeout_seconds=timeout_seconds,
    )
    new_events = _load_tap_events(tap_jsonl_path)[before_count:]
    gzip_window = _tap_window_metrics(new_events)
    gzip_headers = {
        str(key).lower(): str(value)
        for key, value in dict(gzip_result.get("headers") or {}).items()
    }
    gzip_ok = bool(
        (gzip_result.get("status") == 200 or (codex_native_mode and gzip_result.get("status") == 502))
        and gzip_headers.get("x-modeio-contract-version")
        and gzip_headers.get("x-modeio-request-id")
        and gzip_headers.get("x-modeio-upstream-called") == "true"
        and int(gzip_window.get("eventCount", 0)) >= 1
        and int(gzip_window.get("successCount", 0)) >= 1
    )
    _append(
        "gzip-encoded-responses-request",
        gzip_ok,
        {
            "status": gzip_result.get("status"),
            "tapEvents": gzip_window.get("eventCount"),
            "tap2xx": gzip_window.get("successCount"),
            "paths": gzip_window.get("paths"),
        },
        outcome="not_applicable_transport" if codex_native_mode and gzip_result.get("status") == 502 else "product_failed",
    )

    if _zstd_codec is None:
        _append(
            "zstd-encoded-responses-request",
            True,
            {
                "skipped": True,
                "reason": "compression.zstd unavailable",
            },
        )
        return checks

    zstd_raw = json.dumps(
        {
            "model": model,
            "input": f"SMOKE_ZSTD_{run_id}",
            "modeio": {"profile": "dev"},
        }
    ).encode("utf-8")
    before_count = len(_load_tap_events(tap_jsonl_path))
    zstd_result = request_with_bytes(
        method="POST",
        url=f"{request_base_url}/responses",
        body=_zstd_codec.compress(zstd_raw),
        headers={
            "Content-Type": "application/json",
            "Content-Encoding": "zstd",
        },
        timeout_seconds=timeout_seconds,
    )
    zstd_events = _load_tap_events(tap_jsonl_path)[before_count:]
    zstd_window = _tap_window_metrics(zstd_events)
    zstd_headers = {
        str(key).lower(): str(value)
        for key, value in dict(zstd_result.get("headers") or {}).items()
    }
    zstd_ok = bool(
        (zstd_result.get("status") == 200 or (codex_native_mode and zstd_result.get("status") == 502))
        and zstd_headers.get("x-modeio-contract-version")
        and zstd_headers.get("x-modeio-request-id")
        and zstd_headers.get("x-modeio-upstream-called") == "true"
        and int(zstd_window.get("eventCount", 0)) >= 1
        and int(zstd_window.get("successCount", 0)) >= 1
    )
    _append(
        "zstd-encoded-responses-request",
        zstd_ok,
        {
            "status": zstd_result.get("status"),
            "tapEvents": zstd_window.get("eventCount"),
            "tap2xx": zstd_window.get("successCount"),
            "paths": zstd_window.get("paths"),
        },
        outcome="not_applicable_transport" if codex_native_mode and zstd_result.get("status") == 502 else "product_failed",
    )
    return checks
