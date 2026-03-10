from __future__ import annotations

import argparse
import gzip
import json
import os
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

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
from smoke_matrix.openclaw_family import _slug_token_part
from smoke_matrix.sandbox import (
    build_sandbox_env as _build_sandbox_env,
    configure_openclaw_supported_family as _configure_openclaw_supported_family,
)

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


def run_doctor(
    *,
    setup_command: Sequence[str],
    repo_root: Path,
    env: Dict[str, str],
    agents: Sequence[str],
    gateway_base_url: str,
    opencode_config_path: Path,
    openclaw_config_path: Path,
    openclaw_models_cache_path: Path,
    claude_settings_path: Path,
    timeout_seconds: int,
    require_upstream_api_key: bool,
) -> Dict[str, object]:
    command = [
        *setup_command,
        "--json",
        "--doctor",
        "--gateway-base-url",
        gateway_base_url,
        "--opencode-config-path",
        str(opencode_config_path),
        "--openclaw-config-path",
        str(openclaw_config_path),
        "--openclaw-models-cache-path",
        str(openclaw_models_cache_path),
        "--claude-settings-path",
        str(claude_settings_path),
        "--require-commands",
        ",".join(agents),
    ]
    if require_upstream_api_key:
        command.append("--require-upstream-api-key")
    if "codex" in agents:
        command.append("--require-codex-auth")

    payload, result = run_json_cli_command(
        command=command,
        cwd=repo_root,
        env=env,
        timeout_seconds=timeout_seconds,
    )
    if int(result["exitCode"]) != 0 or not payload.get("success"):
        raise RuntimeError(
            f"doctor failed: exit={result['exitCode']} payload={payload}"
        )
    return payload


def run_setup(
    *,
    setup_command: Sequence[str],
    repo_root: Path,
    env: Dict[str, str],
    gateway_base_url: str,
    claude_gateway_base_url: str,
    opencode_config_path: Path,
    openclaw_config_path: Path,
    openclaw_models_cache_path: Path,
    claude_settings_path: Path,
    timeout_seconds: int,
    configure_openai_clients: bool,
    configure_claude: bool,
    openclaw_auth_mode: str,
) -> Dict[str, object]:
    report: Dict[str, object] = {
        "success": True,
        "opencode": None,
        "openclaw": None,
        "claude": None,
        "commands": {},
    }

    if configure_openai_clients:
        routing_command = [
            *setup_command,
            "--json",
            "--apply-opencode",
            "--create-opencode-config",
            "--opencode-config-path",
            str(opencode_config_path),
            "--apply-openclaw",
            "--create-openclaw-config",
            "--openclaw-config-path",
            str(openclaw_config_path),
            "--openclaw-models-cache-path",
            str(openclaw_models_cache_path),
            "--openclaw-auth-mode",
            openclaw_auth_mode,
            "--gateway-base-url",
            gateway_base_url,
        ]
        routing_payload, routing_result = run_json_cli_command(
            command=routing_command,
            cwd=repo_root,
            env=env,
            timeout_seconds=timeout_seconds,
        )
        if int(routing_result["exitCode"]) != 0 or not routing_payload.get("success"):
            raise RuntimeError(
                f"setup command failed: exit={routing_result['exitCode']} payload={routing_payload}"
            )
        report.update(
            {
                "opencode": routing_payload.get("opencode"),
                "openclaw": routing_payload.get("openclaw"),
            }
        )
        commands = routing_payload.get("commands")
        if isinstance(commands, dict):
            report["commands"].update(commands)

    if configure_claude:
        claude_command = [
            *setup_command,
            "--json",
            "--apply-claude",
            "--create-claude-settings",
            "--claude-settings-path",
            str(claude_settings_path),
            "--gateway-base-url",
            claude_gateway_base_url,
        ]
        claude_payload, claude_result = run_json_cli_command(
            command=claude_command,
            cwd=repo_root,
            env=env,
            timeout_seconds=timeout_seconds,
        )
        if int(claude_result["exitCode"]) != 0 or not claude_payload.get("success"):
            raise RuntimeError(
                f"setup command failed: exit={claude_result['exitCode']} payload={claude_payload}"
            )
        report["claude"] = claude_payload.get("claude")
        commands = claude_payload.get("commands")
        if isinstance(commands, dict) and commands.get("claudeHookUrl"):
            report["commands"]["claudeHookUrl"] = commands.get("claudeHookUrl")

    return report


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


def run_agent_check(
    *,
    agent: str,
    index: int,
    run_id: str,
    report_name: str | None,
    model: str,
    claude_model: str,
    repo_root: Path,
    run_dir: Path,
    env: Dict[str, str],
    timeout_seconds: int,
    claude_settings_path: Optional[Path],
    tap_jsonl_path: Path,
    expected_tap_path_fragment: str | None = None,
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
        repo_root=repo_root,
        codex_output_path=codex_message_path,
        claude_settings_path=claude_settings_path,
        timeout_seconds=timeout_seconds,
    )

    before_count = len(_load_tap_events(tap_jsonl_path))
    agent_env = dict(os.environ) if agent == "claude" else env
    result = _run_command_capture(
        command=command,
        cwd=repo_root,
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
    tap_kind = "claude_hook_tap" if agent == "claude" else "upstream_tap"
    transport_check_ok = (
        int(result["exitCode"]) == 0
        and int(tap_window["eventCount"]) >= 1
        and int(tap_window["successCount"]) >= 1
        and (
            expected_tap_path_fragment is None
            or bool(matched_paths)
        )
    )

    diagnostic = None
    outcome = "product_failed"
    stdout_text = str(result["stdout"])
    stderr_text = str(result["stderr"])
    if agent == "codex":
        if "Missing scopes: api.responses.write" in stdout_text or "Missing scopes: api.responses.write" in stderr_text:
            diagnostic = "Codex native OAuth reaches upstream, but the current token lacks `api.responses.write`."
            outcome = "external_blocked"
        elif "refresh token was already used" in stderr_text:
            diagnostic = "Codex auth store needs a fresh login before native middleware smoke can pass."
            outcome = "warning"
    elif agent == "opencode":
        if "OpenAI API key is missing" in stdout_text:
            diagnostic = "OpenCode is still on the `openai` provider but this sandbox has no reusable `OPENAI_API_KEY`."
            outcome = "external_blocked"
    elif agent == "openclaw":
        route_label = (
            "Anthropic Messages"
            if expected_tap_path_fragment == "/v1/messages"
            else "chat completions"
        )
        if 429 in upstream_statuses:
            diagnostic = (
                f"OpenClaw native bridge reaches upstream {route_label}, "
                "but the current token/account is rate limited."
            )
            outcome = "external_blocked"
        elif 401 in upstream_statuses:
            diagnostic = (
                f"OpenClaw native bridge reaches upstream {route_label}, "
                "but the current auth is rejected for this route."
            )
            outcome = "external_blocked"

    if transport_check_ok:
        outcome = "passed"
    elif diagnostic is None:
        diagnostic = "Agent run did not produce the expected successful upstream traffic."

    product_ok = outcome in {"passed", "warning", "external_blocked"}

    return {
        "name": agent,
        "reportName": report_name or agent,
        "token": token,
        "command": command,
        "exitCode": result["exitCode"],
        "timedOut": result["timedOut"],
        "durationMs": result["durationMs"],
        "stdoutPath": str(stdout_path),
        "stderrPath": str(stderr_path),
        "tokenInOutput": token in output_text,
        "tapKind": tap_kind,
        "tap": {
            "window": tap_window,
            "token": tap_token,
            "upstreamStatuses": upstream_statuses,
            "matchedPaths": matched_paths,
        },
        "diagnostic": diagnostic,
        "ok": transport_check_ok,
        "outcome": outcome,
        "productOk": product_ok,
    }


def run_openclaw_family_checks(
    *,
    setup_command: Sequence[str],
    repo_root: Path,
    env: Dict[str, str],
    gateway_base_url: str,
    openclaw_config_path: Path,
    openclaw_models_cache_path: Path,
    run_dir: Path,
    run_id: str,
    timeout_seconds: int,
    gateway_host: str,
    scenarios: Sequence[Dict[str, object]],
) -> List[Dict[str, object]]:
    reports: List[Dict[str, object]] = []
    for index, scenario in enumerate(scenarios, start=1):
        if bool(scenario.get("skipped")):
            reports.append(
                {
                    "name": "openclaw",
                    "reportName": str(scenario.get("name") or f"openclaw:{index}"),
                    "family": scenario.get("family"),
                    "ok": True,
                    "outcome": "skipped",
                    "productOk": True,
                    "diagnostic": str(scenario.get("reason") or "scenario skipped"),
                    "tap": {"window": {"eventCount": 0, "successCount": 0, "paths": []}},
                }
            )
            continue

        family = str(scenario.get("family") or "")
        provider_key = str(scenario.get("providerKey") or "")
        real_base_url = str(scenario.get("realBaseUrl") or "").strip()
        if not provider_key or not real_base_url:
            reports.append(
                {
                    "name": "openclaw",
                    "reportName": str(scenario.get("name") or f"openclaw:{index}"),
                    "family": family,
                    "ok": False,
                    "outcome": "product_failed",
                    "productOk": False,
                    "diagnostic": "OpenClaw family scenario is missing provider or upstream base URL.",
                    "tap": {"window": {"eventCount": 0, "successCount": 0, "paths": []}},
                }
            )
            continue

        family_slug = _slug_token_part(str(scenario.get("name") or family))
        tap_jsonl_path = run_dir / f"{family_slug}-tap-exchanges.jsonl"
        tap_stdout_path = run_dir / f"{family_slug}-tap.log"
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
                model_ref=str(scenario.get("modelRef") or ""),
                api_family=family,
                base_url=family_base_url,
                provider_fields=dict(scenario.get("providerFields") or {}),
            )
            scenario_patch_path = run_dir / f"{family_slug}-scenario.json"
            _write_json(scenario_patch_path, scenario_patch)

            setup_payload, setup_result = run_json_cli_command(
                command=[
                    *setup_command,
                    "--json",
                    "--apply-openclaw",
                    "--openclaw-config-path",
                    str(openclaw_config_path),
                    "--openclaw-models-cache-path",
                    str(openclaw_models_cache_path),
                    "--openclaw-auth-mode",
                    "native",
                    "--gateway-base-url",
                    gateway_base_url,
                ],
                cwd=repo_root,
                env=env,
                timeout_seconds=timeout_seconds,
            )
            if int(setup_result["exitCode"]) != 0 or not setup_payload.get("success"):
                raise RuntimeError(
                    f"openclaw family setup failed for {family}: exit={setup_result['exitCode']} payload={setup_payload}"
                )

            agent_report = run_agent_check(
                agent="openclaw",
                index=index,
                run_id=run_id,
                report_name=str(scenario.get("name") or f"openclaw:{family}"),
                model=str(scenario.get("modelRef") or ""),
                claude_model="",
                repo_root=repo_root,
                run_dir=run_dir,
                env=env,
                timeout_seconds=timeout_seconds,
                claude_settings_path=None,
                tap_jsonl_path=tap_jsonl_path,
                expected_tap_path_fragment=str(
                    scenario.get("expectedTapPathFragment") or ""
                )
                or None,
            )
            agent_report["family"] = family
            agent_report["providerKey"] = provider_key
            agent_report["modelRef"] = scenario.get("modelRef")
            agent_report["realBaseUrl"] = real_base_url
            agent_report["tap"]["logPath"] = str(tap_jsonl_path)
            agent_report["tap"]["stdoutPath"] = str(tap_stdout_path)
            agent_report["scenarioPatch"] = scenario_patch
            agent_report["setup"] = setup_payload.get("openclaw")
            reports.append(agent_report)
        except Exception as error:
            reports.append(
                {
                    "name": "openclaw",
                    "reportName": str(scenario.get("name") or f"openclaw:{family}"),
                    "family": family,
                    "providerKey": provider_key,
                    "modelRef": scenario.get("modelRef"),
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

