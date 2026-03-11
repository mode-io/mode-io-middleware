from __future__ import annotations

import json
import shutil
import tomllib
from pathlib import Path
from typing import Any, Dict, List, Tuple


def build_sandbox_paths(root: Path) -> Dict[str, Path]:
    home = root / "home"
    xdg_root = root / "xdg"
    openclaw_state = root / "openclaw-state"
    return {
        "root": root,
        "home": home,
        "codex_config": home / ".codex" / "config.toml",
        "xdg_config": xdg_root / "config",
        "xdg_state": xdg_root / "state",
        "xdg_cache": xdg_root / "cache",
        "home_local_share": home / ".local" / "share",
        "opencode_config": xdg_root / "config" / "opencode" / "opencode.json",
        "opencode_auth_store": home / ".local" / "share" / "opencode" / "auth.json",
        "claude_settings": home / ".claude" / "settings.json",
        "openclaw_state": openclaw_state,
        "openclaw_config": openclaw_state / "openclaw.json",
        "openclaw_models_cache": openclaw_state / "agents" / "main" / "agent" / "models.json",
    }


def build_sandbox_env(
    parent_env: Dict[str, str],
    paths: Dict[str, Path],
    *,
    gateway_base_url: str,
) -> Dict[str, str]:
    allowlist = (
        "PATH",
        "LANG",
        "LC_ALL",
        "TERM",
        "TMPDIR",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "NO_PROXY",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "REQUESTS_CA_BUNDLE",
    )
    env = {
        key: value
        for key, value in parent_env.items()
        if key in allowlist and isinstance(value, str) and value
    }
    gateway_root_url = (
        gateway_base_url[:-3] if gateway_base_url.endswith("/v1") else gateway_base_url
    )
    env.update(
        {
            "HOME": str(paths["home"]),
            "XDG_CONFIG_HOME": str(paths["xdg_config"]),
            "XDG_STATE_HOME": str(paths["xdg_state"]),
            "XDG_CACHE_HOME": str(paths["xdg_cache"]),
            "MODEIO_SMOKE_CODEX_BASE_URL": f"{gateway_root_url}/clients/codex/v1",
            "OPENCLAW_CONFIG_PATH": str(paths["openclaw_config"]),
            "OPENCLAW_STATE_DIR": str(paths["openclaw_state"]),
            "OPENCLAW_AGENT_DIR": str(paths["openclaw_models_cache"].parent),
            "PI_CODING_AGENT_DIR": str(paths["openclaw_models_cache"].parent),
            "PYTHONUNBUFFERED": "1",
        }
    )
    return env


def seed_codex_credentials(real_home: Path, sandbox_home: Path) -> List[str]:
    seeded: List[str] = []
    source_root = real_home / ".codex"
    target_root = sandbox_home / ".codex"
    if not source_root.exists():
        return seeded

    for relative in ("auth.json", "config.toml"):
        src = source_root / relative
        if not src.exists():
            continue
        dst = target_root / relative
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists() or dst.is_symlink():
            dst.unlink()
        dst.symlink_to(src)
        seeded.append(relative)
    return seeded


def resolve_codex_smoke_model(
    *,
    config_path: Path,
) -> str:
    if config_path.exists():
        try:
            payload = tomllib.loads(config_path.read_text(encoding="utf-8"))
        except Exception:
            payload = {}
        config_model = payload.get("model")
        if isinstance(config_model, str) and config_model.strip():
            return config_model.strip()
    raise ValueError(
        f"unable to determine Codex selected model from {config_path}"
    )


def seed_opencode_state(real_home: Path, paths: Dict[str, Path]) -> Dict[str, object]:
    report: Dict[str, object] = {
        "configSeeded": False,
        "cacheLinked": False,
        "stateLinked": False,
        "authSeeded": False,
    }
    source_config = real_home / ".config" / "opencode" / "opencode.json"
    if source_config.exists():
        target_config = paths["opencode_config"]
        target_config.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_config, target_config)
        report["configSeeded"] = True
        report["configPath"] = str(source_config)

    source_cache = real_home / ".cache" / "opencode"
    target_cache = paths["xdg_cache"] / "opencode"
    if source_cache.exists() and not target_cache.exists():
        target_cache.parent.mkdir(parents=True, exist_ok=True)
        target_cache.symlink_to(source_cache, target_is_directory=True)
        report["cacheLinked"] = True
        report["cachePath"] = str(source_cache)

    source_state = real_home / ".local" / "state" / "opencode"
    target_state = paths["xdg_state"] / "opencode"
    if source_state.exists() and not target_state.exists():
        target_state.parent.mkdir(parents=True, exist_ok=True)
        target_state.symlink_to(source_state, target_is_directory=True)
        report["stateLinked"] = True
        report["statePath"] = str(source_state)

    source_auth = real_home / ".local" / "share" / "opencode" / "auth.json"
    if source_auth.exists():
        target_auth = paths["opencode_auth_store"]
        target_auth.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_auth, target_auth)
        report["authSeeded"] = True
        report["authPath"] = str(source_auth)

    return report


def seed_openclaw_state(real_home: Path, paths: Dict[str, Path]) -> Dict[str, object]:
    report: Dict[str, object] = {
        "configSeeded": False,
        "modelsSeeded": False,
        "authProfilesSeeded": False,
    }
    source_root = real_home / ".openclaw"
    source_config = source_root / "openclaw.json"
    if source_config.exists():
        target_config = paths["openclaw_config"]
        target_config.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_config, target_config)
        report["configSeeded"] = True
        report["configPath"] = str(source_config)

    source_agent_dir = source_root / "agents" / "main" / "agent"
    target_agent_dir = paths["openclaw_models_cache"].parent
    target_agent_dir.mkdir(parents=True, exist_ok=True)

    source_models = source_agent_dir / "models.json"
    if source_models.exists():
        shutil.copy2(source_models, paths["openclaw_models_cache"])
        report["modelsSeeded"] = True
        report["modelsPath"] = str(source_models)

    source_auth_profiles = source_agent_dir / "auth-profiles.json"
    if source_auth_profiles.exists():
        shutil.copy2(source_auth_profiles, target_agent_dir / "auth-profiles.json")
        report["authProfilesSeeded"] = True
        report["authProfilesPath"] = str(source_auth_profiles)

    return report


def _read_json_object(path: Path) -> Dict[str, object]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _write_json_object(path: Path, payload: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _ensure_object(value: Any) -> Dict[str, object]:
    return value if isinstance(value, dict) else {}


def resolve_opencode_smoke_model(
    *,
    config_path: Path,
    state_path: Path,
) -> str:
    config_payload = _read_json_object(config_path)
    config_model = config_payload.get("model")
    if isinstance(config_model, str) and config_model.strip():
        return config_model.strip()

    state_payload = _read_json_object(state_path)
    recent = state_payload.get("recent")
    if isinstance(recent, list):
        for entry in recent:
            if not isinstance(entry, dict):
                continue
            provider_id = entry.get("providerID")
            model_id = entry.get("modelID")
            if not isinstance(provider_id, str) or not provider_id.strip():
                continue
            if not isinstance(model_id, str) or not model_id.strip():
                continue
            normalized_provider = provider_id.strip()
            normalized_model = model_id.strip()
            if "/" in normalized_model:
                return normalized_model
            return f"{normalized_provider}/{normalized_model}"

    raise ValueError(
        f"unable to determine OpenCode selected model from {config_path} or {state_path}"
    )


def _resolve_openclaw_cache_providers(
    payload: Dict[str, object],
    *,
    create: bool,
) -> Tuple[Dict[str, object], Dict[str, object], str]:
    models_obj = payload.get("models")
    root_providers = payload.get("providers")
    if isinstance(models_obj, dict):
        providers = models_obj.get("providers")
        if isinstance(providers, dict):
            return models_obj, providers, "models"
    if isinstance(root_providers, dict):
        return payload, root_providers, "root"
    if not create:
        return payload, {}, "root"
    models_obj = _ensure_object(models_obj)
    providers = _ensure_object(models_obj.get("providers"))
    models_obj["providers"] = providers
    payload["models"] = models_obj
    return models_obj, providers, "models"


def _normalized_openclaw_model_id(model_ref: str) -> str:
    return model_ref.split("/", 1)[1] if "/" in model_ref else model_ref


def configure_openclaw_supported_family(
    *,
    config_path: Path,
    models_cache_path: Path,
    provider_key: str,
    model_ref: str,
    api_family: str,
    base_url: str,
    provider_fields: Dict[str, object] | None = None,
) -> Dict[str, object]:
    report = {
        "providerKey": provider_key,
        "modelRef": model_ref,
        "apiFamily": api_family,
        "baseUrl": base_url,
        "configPath": str(config_path),
        "modelsCachePath": str(models_cache_path),
        "configChanged": False,
        "modelsCacheChanged": False,
    }
    normalized_model_id = _normalized_openclaw_model_id(model_ref)
    extra_fields = dict(provider_fields or {})

    config_payload = _read_json_object(config_path)
    models_obj = _ensure_object(config_payload.get("models"))
    providers_obj = _ensure_object(models_obj.get("providers"))
    provider_obj = _ensure_object(providers_obj.get(provider_key))
    changed = False

    if provider_obj.get("baseUrl") != base_url:
        provider_obj["baseUrl"] = base_url
        changed = True
    if provider_obj.get("api") != api_family:
        provider_obj["api"] = api_family
        changed = True
    if upsert_openclaw_provider_model(provider_obj, normalized_model_id):
        changed = True
    for field_name, field_value in extra_fields.items():
        if provider_obj.get(field_name) != field_value:
            provider_obj[field_name] = field_value
            changed = True
    providers_obj[provider_key] = provider_obj
    models_obj["providers"] = providers_obj
    if models_obj.get("mode") != "merge":
        models_obj["mode"] = "merge"
        changed = True
    config_payload["models"] = models_obj

    agents_obj = _ensure_object(config_payload.get("agents"))
    defaults_obj = _ensure_object(agents_obj.get("defaults"))
    model_obj = _ensure_object(defaults_obj.get("model"))
    if model_obj.get("primary") != model_ref:
        model_obj["primary"] = model_ref
        changed = True
    defaults_obj["model"] = model_obj
    agents_obj["defaults"] = defaults_obj
    config_payload["agents"] = agents_obj

    if changed or not config_path.exists():
        _write_json_object(config_path, config_payload)
        report["configChanged"] = True

    cache_payload = _read_json_object(models_cache_path)
    container_obj, cache_providers, provider_parent = _resolve_openclaw_cache_providers(
        cache_payload,
        create=True,
    )
    cache_provider = _ensure_object(cache_providers.get(provider_key))
    cache_changed = False
    if cache_provider.get("baseUrl") != base_url:
        cache_provider["baseUrl"] = base_url
        cache_changed = True
    if cache_provider.get("api") != api_family:
        cache_provider["api"] = api_family
        cache_changed = True
    if upsert_openclaw_provider_model(cache_provider, normalized_model_id):
        cache_changed = True
    for field_name, field_value in extra_fields.items():
        if cache_provider.get(field_name) != field_value:
            cache_provider[field_name] = field_value
            cache_changed = True
    cache_providers[provider_key] = cache_provider
    if provider_parent == "models":
        container_obj["providers"] = cache_providers
        cache_payload["models"] = container_obj
    else:
        cache_payload["providers"] = cache_providers
    if cache_changed or not models_cache_path.exists():
        _write_json_object(models_cache_path, cache_payload)
        report["modelsCacheChanged"] = True

    return report


def upsert_openclaw_provider_model(provider_obj: Dict[str, object], model_id: str) -> bool:
    changed = False
    normalized_model_id = model_id.split("/", 1)[1] if "/" in model_id else model_id
    desired_model = {
        "id": normalized_model_id,
        "name": f"Live Smoke {normalized_model_id}",
    }

    raw_models = provider_obj.get("models")
    if not isinstance(raw_models, list):
        provider_obj["models"] = [desired_model]
        return True

    found = False
    new_models: List[object] = []
    for item in raw_models:
        if not isinstance(item, dict):
            new_models.append(item)
            continue

        item_id = item.get("id")
        if item_id == normalized_model_id:
            found = True
            if item.get("name") != desired_model["name"]:
                item = dict(item)
                item["name"] = desired_model["name"]
                changed = True
            new_models.append(item)
            continue

        if item_id == "middleware-default":
            changed = True
            continue

        new_models.append(item)

    if not found:
        new_models.append(desired_model)
        changed = True

    provider_obj["models"] = new_models
    return changed
