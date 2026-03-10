#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:  # Python 3.14+
    from compression import zstd as _zstd_codec
except Exception:  # pragma: no cover
    _zstd_codec = None

from modeio_middleware.cli.setup_lib.upstream import (
    OPENAI_UPSTREAM_BASE_URL,
    resolve_live_upstream_selection,
    summarize_live_upstream_selection,
)
from smoke_matrix.agents import build_agent_command as _build_agent_command
from smoke_matrix.common import (
    check_required_commands as _check_required_commands,
    default_upstream_base_url,
    default_upstream_model,
    default_artifacts_root,
    default_repo_root,
    free_port as _free_port,
    load_tap_events as _load_tap_events,
    parse_agents as _parse_agents,
    run_command_capture as _run_command_capture,
    tap_token_metrics as _tap_token_metrics,
    tap_window_metrics as _tap_window_metrics,
    utc_stamp as _utc_stamp,
    wait_for_url as _wait_for_url,
    write_json as _write_json,
    write_text as _write_text,
)
from smoke_matrix.sandbox import (
    build_sandbox_env as _build_sandbox_env,
    build_sandbox_paths as _build_sandbox_paths,
    configure_openclaw_supported_family as _configure_openclaw_supported_family,
    seed_codex_credentials as _seed_codex_credentials,
    seed_opencode_state as _seed_opencode_state,
    seed_openclaw_state as _seed_openclaw_state,
)
from smoke_matrix.runtime import prepare_runtime as _prepare_runtime

SUPPORTED_OPENCLAW_FAMILIES = ("openai-completions", "anthropic-messages")
DEFAULT_OPENCLAW_ANTHROPIC_PROVIDER = "anthropic"
DEFAULT_OPENCLAW_ANTHROPIC_MODEL = os.environ.get(
    "OPENCLAW_ANTHROPIC_MODEL",
    "anthropic/claude-sonnet-4-6",
)
DEFAULT_OPENCLAW_ANTHROPIC_BASE_URL = os.environ.get(
    "OPENCLAW_ANTHROPIC_BASE_URL",
    "https://api.anthropic.com",
)

_DEFAULT_UPSTREAM_SELECTION = resolve_live_upstream_selection(env=dict(os.environ))
DEFAULT_UPSTREAM_BASE_URL = str(
    _DEFAULT_UPSTREAM_SELECTION.get("baseUrl") or default_upstream_base_url(dict(os.environ))
)
DEFAULT_UPSTREAM_MODEL = str(
    _DEFAULT_UPSTREAM_SELECTION.get("model") or default_upstream_model(dict(os.environ))
)


def _default_repo_root() -> Path:
    return default_repo_root(Path(__file__))


def _default_artifacts_root() -> Path:
    return default_artifacts_root(Path(__file__))


def _read_json_object(path: Path) -> Dict[str, object]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _normalize_openclaw_model_ref(provider_key: str, model_ref: str) -> str:
    model_text = str(model_ref).strip()
    if "/" in model_text:
        prefix, suffix = model_text.split("/", 1)
        if prefix.strip():
            return f"{provider_key}/{suffix}"
    return f"{provider_key}/{model_text}"


def _normalize_openclaw_model_id(model_ref: str) -> str:
    return model_ref.split("/", 1)[1] if "/" in model_ref else model_ref


def _slug_token_part(text: str) -> str:
    raw = str(text).strip().lower()
    normalized = "".join(ch if ch.isalnum() else "_" for ch in raw)
    return normalized.strip("_") or "openclaw"


def _openclaw_auth_profile_providers(paths: Dict[str, Path]) -> set[str]:
    auth_path = paths["openclaw_models_cache"].parent / "auth-profiles.json"
    payload = _read_json_object(auth_path)
    profiles = payload.get("profiles")
    providers: set[str] = set()
    if isinstance(profiles, dict):
        for value in profiles.values():
            if not isinstance(value, dict):
                continue
            provider = value.get("provider")
            if isinstance(provider, str) and provider.strip():
                providers.add(provider.strip())
    return providers


def _openclaw_current_primary(config_path: Path) -> tuple[str | None, str | None]:
    payload = _read_json_object(config_path)
    agents_obj = payload.get("agents")
    defaults_obj = agents_obj.get("defaults") if isinstance(agents_obj, dict) else None
    model_obj = defaults_obj.get("model") if isinstance(defaults_obj, dict) else None
    primary = model_obj.get("primary") if isinstance(model_obj, dict) else None
    if isinstance(primary, str) and "/" in primary:
        provider, model_id = primary.split("/", 1)
        return provider, model_id
    return None, None


def _collect_openclaw_provider_entries(
    *,
    config_path: Path,
    models_cache_path: Path,
) -> Dict[str, Dict[str, object]]:
    entries: Dict[str, Dict[str, object]] = {}

    def merge_provider_map(providers: Any) -> None:
        if not isinstance(providers, dict):
            return
        for provider_key, provider_value in providers.items():
            if not isinstance(provider_key, str) or not isinstance(provider_value, dict):
                continue
            normalized = provider_key.strip().lower().replace("_", "-")
            entry = entries.setdefault(
                normalized,
                {
                    "providerKey": provider_key,
                    "apiFamily": None,
                    "baseUrl": None,
                    "models": [],
                    "providerFields": {},
                },
            )
            entry["providerKey"] = entry.get("providerKey") or provider_key
            api_family = provider_value.get("api")
            if isinstance(api_family, str) and api_family.strip():
                entry["apiFamily"] = api_family.strip().lower()
            base_url = provider_value.get("baseUrl")
            if isinstance(base_url, str) and base_url.strip():
                entry["baseUrl"] = base_url.strip()
            models = provider_value.get("models")
            if isinstance(models, list) and models:
                entry["models"] = models
            for field_name in ("apiKey", "authHeader", "headers"):
                if field_name in provider_value:
                    entry_provider_fields = entry.setdefault("providerFields", {})
                    if isinstance(entry_provider_fields, dict):
                        entry_provider_fields[field_name] = provider_value.get(field_name)

    config_payload = _read_json_object(config_path)
    merge_provider_map(
        ((config_payload.get("models") or {}).get("providers"))
        if isinstance(config_payload.get("models"), dict)
        else None
    )

    cache_payload = _read_json_object(models_cache_path)
    if isinstance(cache_payload.get("models"), dict):
        merge_provider_map(cache_payload["models"].get("providers"))
    merge_provider_map(cache_payload.get("providers"))

    return entries


def _parse_openclaw_families(raw: str) -> tuple[str, ...]:
    parts = [part.strip().lower() for part in str(raw).split(",") if part.strip()]
    if not parts:
        raise ValueError("--openclaw-families must include at least one family")
    invalid = [part for part in parts if part not in SUPPORTED_OPENCLAW_FAMILIES]
    if invalid:
        raise ValueError(
            "unsupported OpenClaw families in --openclaw-families: "
            + ", ".join(invalid)
        )
    deduped: List[str] = []
    for part in parts:
        if part not in deduped:
            deduped.append(part)
    return tuple(deduped)


def _resolve_openclaw_family_scenarios(
    *,
    paths: Dict[str, Path],
    args: argparse.Namespace,
) -> List[Dict[str, object]]:
    scenarios: List[Dict[str, object]] = []
    requested_families = _parse_openclaw_families(args.openclaw_families)
    auth_providers = _openclaw_auth_profile_providers(paths)
    provider_entries = _collect_openclaw_provider_entries(
        config_path=paths["openclaw_config"],
        models_cache_path=paths["openclaw_models_cache"],
    )
    current_provider, current_model_id = _openclaw_current_primary(paths["openclaw_config"])

    def add_skipped(family: str, reason: str) -> None:
        scenarios.append(
            {
                "name": f"openclaw:{family}",
                "family": family,
                "skipped": True,
                "reason": reason,
            }
        )

    def model_list_contains(raw_models: object, candidate_model: str) -> bool:
        if not candidate_model or not isinstance(raw_models, list):
            return False
        normalized_full = candidate_model.strip()
        normalized_id = _normalize_openclaw_model_id(candidate_model)
        for item in raw_models:
            if not isinstance(item, dict):
                continue
            item_id = str(item.get("id") or "").strip()
            if item_id and (item_id == normalized_full or item_id == normalized_id):
                return True
        return False

    def model_list_has_specific_choice(raw_models: object) -> bool:
        if not isinstance(raw_models, list):
            return False
        for item in raw_models:
            if not isinstance(item, dict):
                continue
            item_id = str(item.get("id") or "").strip().lower()
            if item_id and item_id not in {"auto", "middleware-default"}:
                return True
        return False

    if "openai-completions" in requested_families:
        selected_entry: Dict[str, object] | None = None
        requested_model_hint = (
            args.openclaw_openai_model.strip() if args.openclaw_openai_model else ""
        )
        if args.openclaw_openai_provider:
            selected_entry = provider_entries.get(
                args.openclaw_openai_provider.strip().lower().replace("_", "-")
            )
        elif current_provider:
            candidate = provider_entries.get(current_provider.strip().lower().replace("_", "-"))
            if candidate and candidate.get("apiFamily") == "openai-completions":
                selected_entry = candidate
        if selected_entry is None:
            openai_candidates: List[Dict[str, object]] = []
            for candidate in provider_entries.values():
                if candidate.get("providerKey") == "modeio-middleware":
                    continue
                if candidate.get("apiFamily") != "openai-completions":
                    continue
                if not isinstance(candidate.get("baseUrl"), str) or not str(candidate.get("baseUrl")).strip():
                    continue
                models = candidate.get("models")
                if not isinstance(models, list) or not models:
                    continue
                openai_candidates.append(candidate)
            if requested_model_hint:
                for candidate in openai_candidates:
                    if model_list_contains(candidate.get("models"), requested_model_hint):
                        selected_entry = candidate
                        break
            if selected_entry is None and requested_model_hint:
                for candidate in openai_candidates:
                    if model_list_has_specific_choice(candidate.get("models")):
                        selected_entry = candidate
                        break
            if selected_entry is None:
                for candidate in openai_candidates:
                    if model_list_has_specific_choice(candidate.get("models")):
                        selected_entry = candidate
                        break
            if selected_entry is None and openai_candidates:
                selected_entry = openai_candidates[0]

        if selected_entry is None:
            add_skipped("openai-completions", "no_openai_provider_configured")
        else:
            provider_key = str(selected_entry["providerKey"])
            raw_models = selected_entry.get("models")
            chosen_model = args.openclaw_openai_model.strip() if args.openclaw_openai_model else ""
            if not chosen_model and current_provider == provider_key and current_model_id:
                chosen_model = current_model_id
            if not chosen_model and isinstance(raw_models, list):
                for item in raw_models:
                    if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"].strip():
                        chosen_model = item["id"].strip()
                        break
            if not chosen_model:
                chosen_model = _normalize_openclaw_model_id(args.model)
            model_ref = _normalize_openclaw_model_ref(provider_key, chosen_model)
            scenarios.append(
                {
                    "name": "openclaw:openai-completions",
                    "family": "openai-completions",
                    "providerKey": provider_key,
                    "modelRef": model_ref,
                    "realBaseUrl": str(selected_entry.get("baseUrl") or "").strip(),
                    "apiFamily": "openai-completions",
                    "providerFields": dict(selected_entry.get("providerFields") or {}),
                    "expectedTapPathFragment": "/chat/completions",
                    "source": "existing_provider",
                }
            )

    if "anthropic-messages" in requested_families:
        selected_entry = provider_entries.get(
            args.openclaw_anthropic_provider.strip().lower().replace("_", "-")
        )
        provider_key = (
            str(selected_entry.get("providerKey"))
            if isinstance(selected_entry, dict) and selected_entry.get("providerKey")
            else args.openclaw_anthropic_provider.strip()
        )
        if not provider_key:
            provider_key = DEFAULT_OPENCLAW_ANTHROPIC_PROVIDER
        if selected_entry is None and provider_key not in auth_providers and "anthropic" not in auth_providers:
            add_skipped("anthropic-messages", "anthropic_auth_profile_missing")
        else:
            chosen_model = args.openclaw_anthropic_model.strip() or DEFAULT_OPENCLAW_ANTHROPIC_MODEL
            model_ref = _normalize_openclaw_model_ref(provider_key, chosen_model)
            provider_fields = (
                dict(selected_entry.get("providerFields") or {})
                if isinstance(selected_entry, dict)
                else {}
            )
            real_base_url = (
                str(selected_entry.get("baseUrl") or "").strip()
                if isinstance(selected_entry, dict)
                else ""
            )
            if not real_base_url:
                real_base_url = args.openclaw_anthropic_base_url.strip()
            scenarios.append(
                {
                    "name": "openclaw:anthropic-messages",
                    "family": "anthropic-messages",
                    "providerKey": provider_key,
                    "modelRef": model_ref,
                    "realBaseUrl": real_base_url,
                    "apiFamily": "anthropic-messages",
                    "providerFields": provider_fields,
                    "expectedTapPathFragment": "/v1/messages",
                    "source": "existing_provider" if isinstance(selected_entry, dict) else "synthesized_from_auth_profile",
                }
            )

    return scenarios


def _run_json_cli_command(
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


def _run_doctor(
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

    payload, result = _run_json_cli_command(
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


def _run_setup(
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
        routing_payload, routing_result = _run_json_cli_command(
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
        claude_payload, claude_result = _run_json_cli_command(
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


def _start_logged_process(
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


def _stop_process(process: Optional[subprocess.Popen]) -> None:
    if process is None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _close_handle(handle: Optional[object]) -> None:
    if handle is not None:
        handle.close()


def _run_agent_check(
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


def _run_openclaw_family_checks(
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
            tap_process, tap_log_handle = _start_logged_process(
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

            setup_payload, setup_result = _run_json_cli_command(
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

            agent_report = _run_agent_check(
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
            _stop_process(tap_process)
            _close_handle(tap_log_handle)
    return reports


def _request_with_bytes(
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


def _run_gateway_smoke_checks(
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

    health_result = _request_with_bytes(
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
    route_result = _request_with_bytes(
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
    unsupported_result = _request_with_bytes(
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
    gzip_result = _request_with_bytes(
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
    zstd_result = _request_with_bytes(
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


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run isolated live smoke tests via codex/opencode/openclaw/claude through modeio-middleware."
    )
    parser.add_argument(
        "--agents",
        default="codex,opencode,openclaw,claude",
        help="Comma-separated agent list (codex,opencode,openclaw,claude)",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_UPSTREAM_MODEL,
        help="OpenAI-compatible model name used for codex/opencode/openclaw smoke prompts",
    )
    parser.add_argument(
        "--openclaw-families",
        default="openai-completions,anthropic-messages",
        help=(
            "Comma-separated OpenClaw families to exercise when openclaw is requested "
            f"({', '.join(SUPPORTED_OPENCLAW_FAMILIES)})"
        ),
    )
    parser.add_argument(
        "--openclaw-openai-provider",
        default="",
        help="Optional OpenClaw provider id to force for the openai-completions family",
    )
    parser.add_argument(
        "--openclaw-openai-model",
        default="",
        help="Optional OpenClaw model id/ref to force for the openai-completions family",
    )
    parser.add_argument(
        "--openclaw-anthropic-provider",
        default=DEFAULT_OPENCLAW_ANTHROPIC_PROVIDER,
        help="OpenClaw provider id used for the anthropic-messages family",
    )
    parser.add_argument(
        "--openclaw-anthropic-model",
        default=DEFAULT_OPENCLAW_ANTHROPIC_MODEL,
        help="OpenClaw model id/ref used for the anthropic-messages family",
    )
    parser.add_argument(
        "--openclaw-anthropic-base-url",
        default=DEFAULT_OPENCLAW_ANTHROPIC_BASE_URL,
        help="Upstream base URL used when synthesizing the OpenClaw anthropic family provider",
    )
    parser.add_argument(
        "--claude-model",
        default="sonnet",
        help="Claude model alias/name used for claude smoke prompts",
    )
    parser.add_argument(
        "--upstream-base-url",
        default=DEFAULT_UPSTREAM_BASE_URL,
        help="Real upstream OpenAI-compatible base URL",
    )
    parser.add_argument(
        "--upstream-api-key-env",
        default="MODEIO_GATEWAY_UPSTREAM_API_KEY",
        help="Primary env var to read upstream API key from",
    )
    parser.add_argument(
        "--artifacts-dir",
        default=str(_default_artifacts_root()),
        help="Artifact root directory (run-specific child dir is created)",
    )
    parser.add_argument(
        "--repo-root",
        default=str(_default_repo_root()),
        help="Repository root containing the smoke harness checkout",
    )
    parser.add_argument(
        "--install-mode",
        choices=("repo", "wheel", "path", "git"),
        default="repo",
        help=(
            "How the middleware runtime under test is launched: repo uses the current checkout, "
            "wheel installs a built wheel into a fresh temp venv, path installs from a local path, "
            "and git installs from a git URL"
        ),
    )
    parser.add_argument(
        "--install-target",
        default="",
        help="Optional path, wheel, or git URL used when --install-mode is wheel/path/git",
    )
    parser.add_argument(
        "--gateway-host", default="127.0.0.1", help="Gateway listen host"
    )
    parser.add_argument(
        "--gateway-port", type=int, default=0, help="Gateway listen port (0 = auto)"
    )
    parser.add_argument(
        "--tap-port", type=int, default=0, help="Tap proxy listen port (0 = auto)"
    )
    parser.add_argument(
        "--claude-tap-port",
        type=int,
        default=0,
        help="Claude hook tap proxy listen port (0 = auto)",
    )
    parser.add_argument(
        "--command-timeout-seconds",
        type=int,
        default=300,
        help="Per-command timeout for setup and each agent command",
    )
    parser.add_argument(
        "--startup-timeout-seconds",
        type=int,
        default=40,
        help="Startup timeout for tap proxy and middleware health checks",
    )
    parser.add_argument(
        "--keep-sandbox",
        action="store_true",
        help="Do not delete temporary sandbox directory after run (runtime install artifacts stay under the run artifacts dir)",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    started_at = _utc_stamp()
    run_id = f"{started_at.lower()}-{os.getpid()}"

    repo_root = Path(args.repo_root).expanduser().resolve()
    artifacts_root = Path(args.artifacts_dir).expanduser().resolve()
    run_dir = artifacts_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    summary_path = run_dir / "summary.json"
    tap_jsonl_path = run_dir / "tap-exchanges.jsonl"
    tap_stdout_path = run_dir / "tap-proxy.log"
    codex_tap_jsonl_path = run_dir / "codex-tap-exchanges.jsonl"
    codex_tap_stdout_path = run_dir / "codex-tap.log"
    claude_tap_jsonl_path = run_dir / "claude-hook-exchanges.jsonl"
    claude_tap_stdout_path = run_dir / "claude-hook-tap.log"
    gateway_log_path = run_dir / "gateway.log"
    setup_payload_path = run_dir / "setup-report.json"

    report: Dict[str, object] = {
        "success": False,
        "mode": "live-agents",
        "runId": run_id,
        "startedAt": started_at,
        "finishedAt": None,
        "upstream": {
            "baseUrl": args.upstream_base_url,
            "apiKeyEnv": None,
            "model": args.model,
        },
        "agentModels": {
            "openaiCompatible": args.model,
            "claude": args.claude_model,
        },
        "runtime": {
            "mode": args.install_mode,
            "installTarget": args.install_target or None,
        },
        "sandbox": {},
        "gateway": {},
        "tap": {
            "logPath": str(tap_jsonl_path),
            "stdoutPath": str(tap_stdout_path),
        },
        "codexNativeTap": None,
        "claudeHookTap": None,
        "doctor": None,
        "setup": None,
        "openclawFamilyScenarios": [],
        "gatewayChecks": [],
        "agents": [],
        "error": None,
    }

    sandbox_root = Path(tempfile.mkdtemp(prefix="modeio-middleware-smoke-"))
    paths = _build_sandbox_paths(sandbox_root)
    report["sandbox"] = {
        "root": str(paths["root"]),
        "home": str(paths["home"]),
        "claudeSettings": str(paths["claude_settings"]),
        "opencodeConfig": str(paths["opencode_config"]),
        "openclawConfig": str(paths["openclaw_config"]),
        "openclawModelsCache": str(paths["openclaw_models_cache"]),
        "kept": bool(args.keep_sandbox),
    }

    tap_process: Optional[subprocess.Popen] = None
    tap_log_handle = None
    codex_tap_process: Optional[subprocess.Popen] = None
    codex_tap_log_handle = None
    claude_tap_process: Optional[subprocess.Popen] = None
    claude_tap_log_handle = None
    gateway_process: Optional[subprocess.Popen] = None
    gateway_log_handle = None

    try:
        agents = _parse_agents(args.agents)
        needs_claude = "claude" in agents
        needs_openai_agents = any(agent != "claude" for agent in agents)
        needs_managed_gateway_checks = any(agent in {"codex", "opencode"} for agent in agents)
        report["mode"] = (
            "live-agents"
            if needs_claude and needs_openai_agents
            else "live-claude"
            if needs_claude
            else "live-openai-agents"
        )
        missing_commands = _check_required_commands(agents)
        if missing_commands:
            raise RuntimeError(
                "missing required commands: " + ", ".join(missing_commands)
            )

        explicit_base_url = (
            args.upstream_base_url
            if args.upstream_base_url != DEFAULT_UPSTREAM_BASE_URL
            else ""
        )
        explicit_model = args.model if args.model != DEFAULT_UPSTREAM_MODEL else ""
        upstream_selection = resolve_live_upstream_selection(
            preferred_env=args.upstream_api_key_env,
            env=dict(os.environ),
            explicit_base_url=explicit_base_url,
            explicit_model=explicit_model,
        )
        report["upstream"] = {
            **report["upstream"],
            **summarize_live_upstream_selection(upstream_selection),
            "required": False,
            "requestedBaseUrl": args.upstream_base_url,
            "requestedModel": args.model,
        }

        upstream_api_key = str(upstream_selection.get("apiKey") or "")

        runtime = _prepare_runtime(
            repo_root=repo_root,
            run_dir=run_dir,
            timeout_seconds=args.command_timeout_seconds,
            install_mode=args.install_mode,
            install_target=args.install_target,
        )
        report["runtime"] = runtime.report

        for key in ("home", "xdg_config", "xdg_state", "xdg_cache", "openclaw_state"):
            paths[key].mkdir(parents=True, exist_ok=True)
        paths["claude_settings"].parent.mkdir(parents=True, exist_ok=True)
        paths["opencode_config"].parent.mkdir(parents=True, exist_ok=True)
        paths["openclaw_models_cache"].parent.mkdir(parents=True, exist_ok=True)

        seeded_codex = _seed_codex_credentials(Path.home(), paths["home"])
        seeded_opencode = _seed_opencode_state(Path.home(), paths)
        seeded_openclaw = _seed_openclaw_state(Path.home(), paths)
        report["sandbox"]["seededCodexFiles"] = seeded_codex
        report["sandbox"]["seededOpenCode"] = seeded_opencode
        report["sandbox"]["seededOpenClaw"] = seeded_openclaw
        report["sandbox"]["claudeUsesHostAuthContext"] = needs_claude

        openclaw_family_scenarios: List[Dict[str, object]] = []
        if "openclaw" in agents:
            openclaw_family_scenarios = _resolve_openclaw_family_scenarios(
                paths=paths,
                args=args,
            )
            report["openclawFamilyScenarios"] = [
                {
                    key: scenario.get(key)
                    for key in (
                        "name",
                        "family",
                        "providerKey",
                        "modelRef",
                        "realBaseUrl",
                        "apiFamily",
                        "expectedTapPathFragment",
                        "source",
                        "skipped",
                        "reason",
                    )
                    if key in scenario
                }
                for scenario in openclaw_family_scenarios
            ]

        gateway_port = args.gateway_port if args.gateway_port > 0 else _free_port()
        tap_port = args.tap_port if args.tap_port > 0 else _free_port()
        gateway_base_url = f"http://{args.gateway_host}:{gateway_port}/v1"
        gateway_health_url = f"http://{args.gateway_host}:{gateway_port}/healthz"
        tap_base_url = f"http://{args.gateway_host}:{tap_port}"
        gateway_root_url = gateway_base_url.rsplit("/v1", 1)[0]

        env = _build_sandbox_env(
            runtime.env,
            paths,
            gateway_base_url=gateway_base_url,
            upstream_api_key=upstream_api_key,
        )

        report["doctor"] = _run_doctor(
            setup_command=runtime.setup_command,
            repo_root=repo_root,
            env=env,
            agents=agents,
            gateway_base_url=gateway_base_url,
            opencode_config_path=paths["opencode_config"],
            openclaw_config_path=paths["openclaw_config"],
            openclaw_models_cache_path=paths["openclaw_models_cache"],
            claude_settings_path=paths["claude_settings"],
            timeout_seconds=args.command_timeout_seconds,
            require_upstream_api_key=False,
        )
        native_clients_report = report.get("doctor", {}).get("nativeClients", {})
        opencode_transport = (
            native_clients_report.get("opencode", {}).get("transport")
            if isinstance(native_clients_report, dict)
            else None
        )

        gateway_upstream_chat_url = f"{OPENAI_UPSTREAM_BASE_URL}/chat/completions"
        gateway_upstream_responses_url = f"{OPENAI_UPSTREAM_BASE_URL}/responses"
        if needs_openai_agents:
            tap_command = [
                sys.executable,
                str(repo_root / "scripts" / "upstream_tap_proxy.py"),
                "--host",
                args.gateway_host,
                "--port",
                str(tap_port),
                "--target-base-url",
                args.upstream_base_url,
                "--log-jsonl",
                str(tap_jsonl_path),
                "--api-key-env",
                "MODEIO_TAP_UPSTREAM_API_KEY",
            ]
            tap_process, tap_log_handle = _start_logged_process(
                command=tap_command,
                cwd=repo_root,
                env=env,
                log_path=tap_stdout_path,
            )
            if not _wait_for_url(
                f"{tap_base_url}/healthz", timeout_seconds=args.startup_timeout_seconds
            ):
                raise RuntimeError("tap proxy failed to become healthy")
            gateway_upstream_chat_url = f"{tap_base_url}/v1/chat/completions"
            gateway_upstream_responses_url = f"{tap_base_url}/v1/responses"
            report["tap"]["baseUrl"] = tap_base_url
            report["tap"]["port"] = tap_port
            if "codex" in agents:
                codex_tap_port = _free_port()
                codex_tap_base_url = f"http://{args.gateway_host}:{codex_tap_port}"
                codex_tap_command = [
                    sys.executable,
                    str(repo_root / "scripts" / "upstream_tap_proxy.py"),
                    "--host",
                    args.gateway_host,
                    "--port",
                    str(codex_tap_port),
                    "--target-base-url",
                    "https://chatgpt.com/backend-api/codex",
                    "--log-jsonl",
                    str(codex_tap_jsonl_path),
                    "--api-key-env",
                    "MODEIO_TAP_UPSTREAM_API_KEY",
                ]
                codex_tap_process, codex_tap_log_handle = _start_logged_process(
                    command=codex_tap_command,
                    cwd=repo_root,
                    env=env,
                    log_path=codex_tap_stdout_path,
                )
                if not _wait_for_url(
                    f"{codex_tap_base_url}/healthz",
                    timeout_seconds=args.startup_timeout_seconds,
                ):
                    raise RuntimeError("codex native tap proxy failed to become healthy")
                env["MODEIO_CODEX_NATIVE_BASE_URL"] = codex_tap_base_url
                report["codexNativeTap"] = {
                    "baseUrl": codex_tap_base_url,
                    "port": codex_tap_port,
                    "logPath": str(codex_tap_jsonl_path),
                    "stdoutPath": str(codex_tap_stdout_path),
                    "targetBaseUrl": "https://chatgpt.com/backend-api/codex",
                }
        else:
            report["tap"]["skipped"] = True
            report["tap"]["reason"] = "openai-compatible-agents-not-requested"

        gateway_command = [
            *runtime.gateway_command,
            "--host",
            args.gateway_host,
            "--port",
            str(gateway_port),
            "--upstream-chat-url",
            gateway_upstream_chat_url,
            "--upstream-responses-url",
            gateway_upstream_responses_url,
        ]
        gateway_process, gateway_log_handle = _start_logged_process(
            command=gateway_command,
            cwd=repo_root,
            env=env,
            log_path=gateway_log_path,
        )
        if not _wait_for_url(
            gateway_health_url, timeout_seconds=args.startup_timeout_seconds
        ):
            raise RuntimeError("middleware gateway failed to become healthy")

        report["gateway"] = {
            "baseUrl": gateway_base_url,
            "healthUrl": gateway_health_url,
            "logPath": str(gateway_log_path),
            "host": args.gateway_host,
            "port": gateway_port,
        }

        claude_gateway_base_url = gateway_base_url
        if needs_claude:
            claude_tap_port = (
                args.claude_tap_port if args.claude_tap_port > 0 else _free_port()
            )
            claude_tap_base_url = f"http://{args.gateway_host}:{claude_tap_port}"
            claude_tap_command = [
                sys.executable,
                str(repo_root / "scripts" / "upstream_tap_proxy.py"),
                "--host",
                args.gateway_host,
                "--port",
                str(claude_tap_port),
                "--target-base-url",
                gateway_root_url,
                "--log-jsonl",
                str(claude_tap_jsonl_path),
                "--api-key-env",
                "MODEIO_TAP_UPSTREAM_API_KEY",
            ]
            claude_tap_process, claude_tap_log_handle = _start_logged_process(
                command=claude_tap_command,
                cwd=repo_root,
                env=env,
                log_path=claude_tap_stdout_path,
            )
            if not _wait_for_url(
                f"{claude_tap_base_url}/healthz",
                timeout_seconds=args.startup_timeout_seconds,
            ):
                raise RuntimeError("claude hook tap proxy failed to become healthy")
            claude_gateway_base_url = f"{claude_tap_base_url}/v1"
            report["claudeHookTap"] = {
                "baseUrl": claude_tap_base_url,
                "port": claude_tap_port,
                "logPath": str(claude_tap_jsonl_path),
                "stdoutPath": str(claude_tap_stdout_path),
                "targetBaseUrl": gateway_root_url,
            }

        setup_payload = _run_setup(
            setup_command=runtime.setup_command,
            repo_root=repo_root,
            env=env,
            gateway_base_url=gateway_base_url,
            claude_gateway_base_url=claude_gateway_base_url,
            opencode_config_path=paths["opencode_config"],
            openclaw_config_path=paths["openclaw_config"],
            openclaw_models_cache_path=paths["openclaw_models_cache"],
            claude_settings_path=paths["claude_settings"],
            timeout_seconds=args.command_timeout_seconds,
            configure_openai_clients=needs_openai_agents,
            configure_claude=needs_claude,
            openclaw_auth_mode="native",
        )
        report["setup"] = setup_payload
        _write_json(setup_payload_path, setup_payload)

        if needs_managed_gateway_checks and bool(upstream_selection.get("ready")):
            gateway_check_base_url = f"{gateway_root_url}/clients/codex/v1"
            report["gatewayChecks"] = list(
                _run_gateway_smoke_checks(
                    gateway_root_url=gateway_root_url,
                    request_base_url=gateway_check_base_url,
                    model=args.model,
                    run_id=run_id,
                    timeout_seconds=args.command_timeout_seconds,
                    tap_jsonl_path=(
                        codex_tap_jsonl_path if codex_tap_process is not None else tap_jsonl_path
                    ),
                )
            )
        elif needs_managed_gateway_checks:
            report["gatewayChecks"] = [
                {
                    "name": "managed-upstream-gateway-checks",
                    "ok": True,
                    "skipped": True,
                    "reason": "native-auth-only run; generic /responses gateway probes require an explicit reusable managed upstream",
                }
            ]
        else:
            report["gatewayChecks"] = [
                {
                    "name": "managed-upstream-gateway-checks",
                    "ok": True,
                    "skipped": True,
                    "reason": "agent subset does not use the generic managed OpenAI-compatible gateway probes",
                }
            ]

        for index, agent in enumerate(agents, start=1):
            if agent == "openclaw":
                report["agents"].extend(
                    _run_openclaw_family_checks(
                        setup_command=runtime.setup_command,
                        repo_root=repo_root,
                        env=env,
                        gateway_base_url=gateway_base_url,
                        openclaw_config_path=paths["openclaw_config"],
                        openclaw_models_cache_path=paths["openclaw_models_cache"],
                        run_dir=run_dir,
                        run_id=run_id,
                        timeout_seconds=args.command_timeout_seconds,
                        gateway_host=args.gateway_host,
                        scenarios=openclaw_family_scenarios,
                    )
                )
                continue

            report["agents"].append(
                _run_agent_check(
                    agent=agent,
                    index=index,
                    run_id=run_id,
                    report_name=None,
                    model=args.model,
                    claude_model=args.claude_model,
                    repo_root=repo_root,
                    run_dir=run_dir,
                    env=env,
                    timeout_seconds=args.command_timeout_seconds,
                    claude_settings_path=paths["claude_settings"]
                    if agent == "claude"
                    else None,
                    tap_jsonl_path=(
                        claude_tap_jsonl_path
                        if agent == "claude"
                        else codex_tap_jsonl_path
                        if (
                            codex_tap_process is not None
                            and (
                                agent == "codex"
                                or (agent == "opencode" and opencode_transport == "codex_native")
                            )
                        )
                        else tap_jsonl_path
                    ),
                )
            )

        gateway_checks_ok = True
        if needs_managed_gateway_checks and bool(upstream_selection.get("ready")):
            gateway_checks_ok = all(
                bool(item.get("productOk", item.get("ok")))
                for item in report.get("gatewayChecks", [])
            )
        report["success"] = gateway_checks_ok and all(
            bool(agent.get("productOk", agent.get("ok"))) for agent in report["agents"]
        )
    except Exception as error:
        report["success"] = False
        report["error"] = str(error)
    finally:
        _stop_process(claude_tap_process)
        _stop_process(codex_tap_process)
        _stop_process(gateway_process)
        _stop_process(tap_process)
        _close_handle(claude_tap_log_handle)
        _close_handle(codex_tap_log_handle)
        _close_handle(gateway_log_handle)
        _close_handle(tap_log_handle)

    report["finishedAt"] = _utc_stamp()
    _write_json(summary_path, report)

    if not args.keep_sandbox:
        shutil.rmtree(paths["root"], ignore_errors=True)

    print(f"[smoke-agent-matrix] summary: {summary_path}")
    for agent_report in report.get("agents", []):
        if not isinstance(agent_report, dict):
            continue
        tap = agent_report.get("tap")
        window = tap.get("window") if isinstance(tap, dict) else {}
        event_count = window.get("eventCount") if isinstance(window, dict) else None
        success_count = window.get("successCount") if isinstance(window, dict) else None
        print(
            "[smoke-agent-matrix] "
            f"{agent_report.get('reportName') or agent_report.get('name')}: "
            f"ok={agent_report.get('ok')} outcome={agent_report.get('outcome')} "
            f"exit={agent_report.get('exitCode')} tapEvents={event_count} tap2xx={success_count}"
        )

    for check in report.get("gatewayChecks", []):
        if not isinstance(check, dict):
            continue
        print(
            "[smoke-agent-matrix] "
            f"check {check.get('name')}: ok={check.get('ok')} outcome={check.get('outcome')} "
            f"status={check.get('status')}"
        )

    if report.get("error"):
        print(f"[smoke-agent-matrix] error: {report['error']}")

    return 0 if report.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
