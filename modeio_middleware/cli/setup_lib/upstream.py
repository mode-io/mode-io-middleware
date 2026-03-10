#!/usr/bin/env python3

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from modeio_middleware.cli.setup_lib.opencode import (
    current_opencode_provider_id,
    default_opencode_config_path,
)
from modeio_middleware.cli.setup_lib.openclaw import default_openclaw_config_path
from modeio_middleware.core.provider_auth import CredentialResolver, normalize_provider_id

OPENAI_UPSTREAM_BASE_URL = "https://api.openai.com/v1"
OPENAI_DEFAULT_MODEL = "gpt-4o-mini"
ZENMUX_UPSTREAM_BASE_URL = "https://zenmux.ai/api/v1"
ZENMUX_DEFAULT_MODEL = "openai/gpt-5.3-codex"


def _normalize_base_url(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    text = value.strip().rstrip("/")
    if not text.startswith(("http://", "https://")):
        return ""
    return text


def _non_empty_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else ""


def _is_loopback_base_url(base_url: str) -> bool:
    if not base_url:
        return False
    parsed = urlparse(base_url)
    hostname = (parsed.hostname or "").lower()
    return hostname in {"127.0.0.1", "localhost", "::1"}


def _provider_for_base_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized == OPENAI_UPSTREAM_BASE_URL:
        return "openai"
    if normalized == ZENMUX_UPSTREAM_BASE_URL:
        return "zenmux"
    return "custom"


def _default_model_for_base_url(base_url: str) -> str:
    if _provider_for_base_url(base_url) == "zenmux":
        return ZENMUX_DEFAULT_MODEL
    return OPENAI_DEFAULT_MODEL


def resolve_upstream_api_key_presence(
    preferred_env: str, env: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    resolved_env = env or os.environ
    candidates = []
    for value in (preferred_env.strip(), "OPENAI_API_KEY", "ZENMUX_API_KEY"):
        if value and value not in candidates:
            candidates.append(value)

    found_env = None
    for candidate in candidates:
        if resolved_env.get(candidate, "").strip():
            found_env = candidate
            break

    return {
        "searched": candidates,
        "present": found_env is not None,
        "env": found_env,
    }


def _load_json_object(path: Path) -> Dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _resolve_env_api_key(
    env: Dict[str, str],
    *,
    preferred_env: str,
    base_url: str,
) -> tuple[str, str | None]:
    candidates = []
    preferred = preferred_env.strip()
    if preferred:
        candidates.append(preferred)

    provider = _provider_for_base_url(base_url)
    if provider == "zenmux":
        candidates.extend(["ZENMUX_API_KEY", "OPENAI_API_KEY"])
    else:
        candidates.extend(["OPENAI_API_KEY", "ZENMUX_API_KEY"])

    seen = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        value = env.get(candidate, "").strip()
        if value:
            return value, candidate
    return "", None


def _build_selection(
    *,
    source: str,
    base_url: str,
    model: str,
    api_key: str,
    api_key_env: str | None,
    api_key_source: str | None,
    config_path: Path | None,
) -> Dict[str, Any]:
    return {
        "detected": True,
        "ready": bool(api_key),
        "source": source,
        "provider": _provider_for_base_url(base_url),
        "baseUrl": base_url,
        "model": model,
        "apiKey": api_key,
        "apiKeyEnv": api_key_env,
        "apiKeySource": api_key_source,
        "configPath": str(config_path) if config_path is not None else None,
    }


def _token_from_authorization(authorization: str | None) -> str:
    text = str(authorization or "").strip()
    if text.lower().startswith("bearer "):
        return text[7:].strip()
    return text


def _selection_from_explicit_source(
    env: Dict[str, str],
    *,
    preferred_env: str,
    explicit_base_url: str,
    explicit_model: str,
    source: str,
) -> Dict[str, Any] | None:
    raw_base_url = _normalize_base_url(explicit_base_url)
    raw_model = _non_empty_text(explicit_model)
    preferred_key = env.get(preferred_env, "").strip()
    if not (raw_base_url or raw_model or preferred_key):
        return None

    base_url = raw_base_url or OPENAI_UPSTREAM_BASE_URL
    model = raw_model or _default_model_for_base_url(base_url)
    api_key, api_key_env = _resolve_env_api_key(
        env,
        preferred_env=preferred_env,
        base_url=base_url,
    )
    api_key_source = f"env:{api_key_env}" if api_key_env else None
    return _build_selection(
        source=source,
        base_url=base_url,
        model=model,
        api_key=api_key,
        api_key_env=api_key_env,
        api_key_source=api_key_source,
        config_path=None,
    )


def _selection_from_opencode_config(
    env: Dict[str, str],
    *,
    preferred_env: str,
    config_path: Path,
) -> Dict[str, Any] | None:
    payload = _load_json_object(config_path)
    if payload is None:
        return None

    resolver = CredentialResolver()
    provider_id = normalize_provider_id(current_opencode_provider_id(payload))
    provider_obj = payload.get("provider")
    selected_provider = provider_obj.get(provider_id) if isinstance(provider_obj, dict) else None
    options_obj = selected_provider.get("options") if isinstance(selected_provider, dict) else None
    if not isinstance(options_obj, dict):
        options_obj = {}

    has_selected_provider = isinstance(selected_provider, dict)

    raw_base_url = _normalize_base_url(
        options_obj.get("baseURL") or options_obj.get("baseUrl")
    )
    if not raw_base_url and isinstance(selected_provider, dict):
        raw_base_url = _normalize_base_url(selected_provider.get("baseUrl"))
    config_model = _non_empty_text(payload.get("model"))
    config_api_key = _non_empty_text(options_obj.get("apiKey")) or _non_empty_text(
        selected_provider.get("apiKey") if isinstance(selected_provider, dict) else ""
    )
    if config_api_key == "modeio-middleware":
        config_api_key = ""
    if not (raw_base_url or config_api_key or (has_selected_provider and config_model)):
        return None

    base_url = raw_base_url or OPENAI_UPSTREAM_BASE_URL
    if raw_base_url and _is_loopback_base_url(base_url):
        return None

    model = config_model or _default_model_for_base_url(base_url)
    api_key = config_api_key
    api_key_env = None
    api_key_source = None
    if api_key:
        api_key_source = f"config:provider.{provider_id}.options.apiKey"
    else:
        inspection = resolver.inspect(
            client_name="opencode",
            provider_name=provider_id,
            env=env,
        )
        api_key = _token_from_authorization(inspection.authorization)
        api_key_env = inspection.auth_env
        api_key_source = inspection.auth_source or (
            f"env:{api_key_env}" if api_key_env else None
        )
        if not api_key:
            api_key, api_key_env = _resolve_env_api_key(
                env,
                preferred_env=preferred_env,
                base_url=base_url,
            )
            api_key_source = api_key_source or (
                f"env:{api_key_env}" if api_key_env else None
            )

    return _build_selection(
        source="opencode_config",
        base_url=base_url,
        model=model,
        api_key=api_key,
        api_key_env=api_key_env,
        api_key_source=api_key_source,
        config_path=config_path,
    )


def _selection_from_openclaw_config(
    env: Dict[str, str],
    *,
    preferred_env: str,
    config_path: Path,
) -> Dict[str, Any] | None:
    payload = _load_json_object(config_path)
    if payload is None:
        return None

    resolver = CredentialResolver()
    agents_obj = payload.get("agents")
    defaults_obj = agents_obj.get("defaults") if isinstance(agents_obj, dict) else None
    model_obj = defaults_obj.get("model") if isinstance(defaults_obj, dict) else None
    primary_ref = _non_empty_text(model_obj.get("primary")) if isinstance(model_obj, dict) else ""
    if "/" not in primary_ref:
        return None

    provider_id, model_id = primary_ref.split("/", 1)
    if provider_id == "modeio-middleware":
        return None

    models_obj = payload.get("models")
    providers_obj = models_obj.get("providers") if isinstance(models_obj, dict) else None
    provider_obj = providers_obj.get(provider_id) if isinstance(providers_obj, dict) else None
    if not isinstance(provider_obj, dict):
        return None

    base_url = _normalize_base_url(provider_obj.get("baseUrl"))
    if not base_url or _is_loopback_base_url(base_url):
        return None

    model = _non_empty_text(model_id) or _default_model_for_base_url(base_url)
    api_key = _non_empty_text(provider_obj.get("apiKey"))
    if api_key == "modeio-middleware":
        api_key = ""

    api_key_env = None
    api_key_source = None
    if api_key:
        api_key_source = f"config:models.providers.{provider_id}.apiKey"
    else:
        inspection = resolver.inspect(
            client_name="openclaw",
            provider_name=provider_id,
            env=env,
        )
        api_key = _token_from_authorization(inspection.authorization)
        api_key_env = inspection.auth_env
        api_key_source = inspection.auth_source or (
            f"env:{api_key_env}" if api_key_env else None
        )
        if not api_key:
            api_key, api_key_env = _resolve_env_api_key(
                env,
                preferred_env=preferred_env,
                base_url=base_url,
            )
            api_key_source = api_key_source or (
                f"env:{api_key_env}" if api_key_env else None
            )

    return _build_selection(
        source="openclaw_config",
        base_url=base_url,
        model=model,
        api_key=api_key,
        api_key_env=api_key_env,
        api_key_source=api_key_source,
        config_path=config_path,
    )


def _selection_from_openai_env(
    env: Dict[str, str],
    *,
    preferred_env: str,
) -> Dict[str, Any] | None:
    openai_key = env.get("OPENAI_API_KEY", "").strip()
    if not openai_key:
        return None

    base_url = _normalize_base_url(env.get("OPENAI_BASE_URL"))
    if not base_url or _is_loopback_base_url(base_url):
        base_url = OPENAI_UPSTREAM_BASE_URL
    model = _non_empty_text(env.get("OPENAI_MODEL")) or _default_model_for_base_url(base_url)
    api_key, api_key_env = _resolve_env_api_key(
        env,
        preferred_env=preferred_env,
        base_url=base_url,
    )
    api_key_source = f"env:{api_key_env}" if api_key_env else None
    return _build_selection(
        source="openai_env",
        base_url=base_url,
        model=model,
        api_key=api_key,
        api_key_env=api_key_env,
        api_key_source=api_key_source,
        config_path=None,
    )


def resolve_live_upstream_selection(
    *,
    preferred_env: str = "MODEIO_GATEWAY_UPSTREAM_API_KEY",
    env: Optional[Dict[str, str]] = None,
    opencode_config_path: Optional[Path] = None,
    openclaw_config_path: Optional[Path] = None,
    explicit_base_url: str = "",
    explicit_model: str = "",
) -> Dict[str, Any]:
    resolved_env = dict(env or os.environ)
    resolved_home = Path(resolved_env.get("HOME", str(Path.home()))).expanduser()
    resolved_opencode_path = (
        opencode_config_path
        if opencode_config_path is not None
        else default_opencode_config_path(env=resolved_env, home=resolved_home)
    )
    resolved_openclaw_path = (
        openclaw_config_path
        if openclaw_config_path is not None
        else default_openclaw_config_path(env=resolved_env, home=resolved_home)
    )

    candidates = []

    explicit_candidate = _selection_from_explicit_source(
        resolved_env,
        preferred_env=preferred_env,
        explicit_base_url=explicit_base_url,
        explicit_model=explicit_model,
        source="explicit_args",
    )
    if explicit_candidate is not None:
        candidates.append(explicit_candidate)
    else:
        env_candidate = _selection_from_explicit_source(
            resolved_env,
            preferred_env=preferred_env,
            explicit_base_url=resolved_env.get("MODEIO_GATEWAY_UPSTREAM_BASE_URL", ""),
            explicit_model=resolved_env.get("MODEIO_GATEWAY_UPSTREAM_MODEL", ""),
            source="explicit_env",
        )
        if env_candidate is not None:
            candidates.append(env_candidate)

    for candidate in (
        _selection_from_opencode_config(
            resolved_env,
            preferred_env=preferred_env,
            config_path=resolved_opencode_path,
        ),
        _selection_from_openclaw_config(
            resolved_env,
            preferred_env=preferred_env,
            config_path=resolved_openclaw_path,
        ),
        _selection_from_openai_env(
            resolved_env,
            preferred_env=preferred_env,
        ),
    ):
        if candidate is not None:
            candidates.append(candidate)

    for candidate in candidates:
        if candidate.get("ready"):
            return candidate

    if candidates:
        return candidates[0]

    return {
        "detected": False,
        "ready": False,
        "source": None,
        "provider": None,
        "baseUrl": None,
        "model": None,
        "apiKey": None,
        "apiKeyEnv": None,
        "apiKeySource": None,
        "configPath": None,
    }


def summarize_live_upstream_selection(selection: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "detected": bool(selection.get("detected")),
        "ready": bool(selection.get("ready")),
        "source": selection.get("source"),
        "provider": selection.get("provider"),
        "apiKeyReady": bool(selection.get("apiKey")),
        "baseUrl": selection.get("baseUrl"),
        "model": selection.get("model"),
        "apiKeyEnv": selection.get("apiKeyEnv"),
        "apiKeySource": selection.get("apiKeySource"),
        "configPath": selection.get("configPath"),
    }
