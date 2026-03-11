from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

SUPPORTED_OPENCLAW_FAMILIES = ("openai-completions", "anthropic-messages")
CURRENT_OPENCLAW_FAMILY_TOKEN = "current"


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


def _normalize_provider_key(provider_key: str) -> str:
    return str(provider_key).strip().lower().replace("_", "-")


def _slug_token_part(text: str) -> str:
    raw = str(text).strip().lower()
    normalized = "".join(ch if ch.isalnum() else "_" for ch in raw)
    return normalized.strip("_") or "openclaw"


def _string_value(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text if text else None


def _is_loopback_base_url(value: str | None) -> bool:
    text = str(value or "").strip().lower()
    return text.startswith("http://127.0.0.1") or text.startswith("http://localhost")


def _openclaw_current_primary(config_path: Path) -> tuple[str | None, str | None]:
    payload = _read_json_object(config_path)
    agents_obj = payload.get("agents")
    defaults_obj = agents_obj.get("defaults") if isinstance(agents_obj, dict) else None
    model_obj = defaults_obj.get("model") if isinstance(defaults_obj, dict) else None
    primary = model_obj.get("primary") if isinstance(model_obj, dict) else None
    if isinstance(primary, str) and "/" in primary:
        provider, model_id = primary.split("/", 1)
        provider = provider.strip()
        model_id = model_id.strip()
        if provider and model_id:
            return provider, model_id
    return None, None


def _merge_provider_map(entries: Dict[str, Dict[str, object]], providers: object) -> None:
    if not isinstance(providers, dict):
        return
    for provider_key, provider_value in providers.items():
        if not isinstance(provider_key, str) or not isinstance(provider_value, dict):
            continue
        normalized = _normalize_provider_key(provider_key)
        entry = entries.setdefault(
            normalized,
            {
                "providerKey": provider_key.strip(),
                "apiFamily": None,
                "realBaseUrl": None,
                "models": [],
                "providerFields": {},
            },
        )
        entry["providerKey"] = entry.get("providerKey") or provider_key.strip()
        api_family = _string_value(provider_value.get("api"))
        if api_family:
            entry["apiFamily"] = api_family.lower()
        direct_base_url = None
        options_obj = provider_value.get("options")
        if isinstance(options_obj, dict):
            direct_base_url = _string_value(options_obj.get("baseURL")) or _string_value(
                options_obj.get("baseUrl")
            )
        if direct_base_url is None:
            direct_base_url = _string_value(provider_value.get("baseUrl")) or _string_value(
                provider_value.get("baseURL")
            )
        if direct_base_url and not _is_loopback_base_url(direct_base_url):
            entry["realBaseUrl"] = direct_base_url.rstrip("/")
        models = provider_value.get("models")
        if isinstance(models, list) and models:
            entry["models"] = models
        provider_fields = entry.setdefault("providerFields", {})
        if isinstance(provider_fields, dict):
            for field_name in ("apiKey", "authHeader", "headers"):
                if field_name in provider_value:
                    provider_fields[field_name] = provider_value.get(field_name)


def _merge_route_metadata(entries: Dict[str, Dict[str, object]], config_path: Path) -> None:
    metadata_path = config_path.with_name(f"{config_path.name}.modeio-route.json")
    metadata = _read_json_object(metadata_path)
    providers = metadata.get("providers")
    if not isinstance(providers, dict):
        return
    for provider_id, provider_value in providers.items():
        if not isinstance(provider_id, str) or not isinstance(provider_value, dict):
            continue
        normalized = _normalize_provider_key(provider_id)
        entry = entries.setdefault(
            normalized,
            {
                "providerKey": _string_value(provider_value.get("providerKey")) or provider_id.strip(),
                "apiFamily": None,
                "realBaseUrl": None,
                "models": [],
                "providerFields": {},
            },
        )
        provider_key = _string_value(provider_value.get("providerKey"))
        if provider_key:
            entry["providerKey"] = provider_key
        api_family = _string_value(provider_value.get("apiFamily"))
        if api_family:
            entry["apiFamily"] = api_family.lower()
        for field_name in ("originalBaseUrl", "originalModelsCacheBaseUrl"):
            value = _string_value(provider_value.get(field_name))
            if value:
                entry["realBaseUrl"] = value.rstrip("/")
                break


def _collect_openclaw_provider_entries(
    *,
    config_path: Path,
    models_cache_path: Path,
) -> Dict[str, Dict[str, object]]:
    entries: Dict[str, Dict[str, object]] = {}

    config_payload = _read_json_object(config_path)
    models_obj = config_payload.get("models")
    _merge_provider_map(
        entries,
        models_obj.get("providers") if isinstance(models_obj, dict) else None,
    )

    cache_payload = _read_json_object(models_cache_path)
    cache_models_obj = cache_payload.get("models")
    _merge_provider_map(
        entries,
        cache_models_obj.get("providers") if isinstance(cache_models_obj, dict) else None,
    )
    _merge_provider_map(entries, cache_payload.get("providers"))
    _merge_route_metadata(entries, config_path)
    return entries


def parse_openclaw_families(raw: str) -> tuple[str, ...]:
    parts = [part.strip().lower() for part in str(raw).split(",") if part.strip()]
    if not parts:
        raise ValueError("--openclaw-families must include at least one family")
    if len(parts) == 1 and parts[0] == CURRENT_OPENCLAW_FAMILY_TOKEN:
        return (CURRENT_OPENCLAW_FAMILY_TOKEN,)
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


def _error_scenario(family: str, reason: str) -> Dict[str, object]:
    return {
        "name": f"openclaw:{family}",
        "family": family,
        "error": True,
        "reason": reason,
    }


def _skipped_scenario(name: str, reason: str) -> Dict[str, object]:
    return {
        "name": name,
        "family": None,
        "skipped": True,
        "reason": reason,
    }


def _resolve_family_provider(
    *,
    family: str,
    requested_provider: str,
    current_provider: str | None,
    provider_entries: Dict[str, Dict[str, object]],
) -> Dict[str, object] | None:
    if requested_provider:
        return provider_entries.get(_normalize_provider_key(requested_provider))

    if current_provider:
        current_entry = provider_entries.get(_normalize_provider_key(current_provider))
        if isinstance(current_entry, dict) and current_entry.get("apiFamily") == family:
            return current_entry
    return None


def _resolve_family_model(
    *,
    provider_key: str,
    requested_model: str,
    current_provider: str | None,
    current_model_id: str | None,
    entry: Dict[str, object],
) -> str | None:
    if requested_model:
        requested_model_id = _normalize_openclaw_model_id(requested_model)
        return requested_model_id if requested_model_id else None

    if current_provider and _normalize_provider_key(current_provider) == _normalize_provider_key(provider_key):
        current_model = _normalize_openclaw_model_id(current_model_id or "")
        if current_model and current_model.lower() not in {"auto", "middleware-default"}:
            return current_model
    return None


def _resolve_current_primary_scenario(
    *,
    current_provider: str | None,
    current_model_id: str | None,
    provider_entries: Dict[str, Dict[str, object]],
) -> Dict[str, object]:
    if not current_provider:
        return _skipped_scenario("openclaw:current", "missing_current_primary")
    if _normalize_provider_key(current_provider) == "openai-codex":
        return _skipped_scenario("openclaw:current", "unsupported_current_family")

    entry = provider_entries.get(_normalize_provider_key(current_provider))
    if not isinstance(entry, dict):
        return _skipped_scenario("openclaw:current", "missing_current_provider_entry")

    provider_key = _string_value(entry.get("providerKey"))
    if not provider_key:
        return _skipped_scenario("openclaw:current", "missing_current_provider_key")

    family = _string_value(entry.get("apiFamily"))
    if not family:
        return _skipped_scenario("openclaw:current", "missing_current_api_family")
    if family not in SUPPORTED_OPENCLAW_FAMILIES:
        return _skipped_scenario("openclaw:current", "unsupported_current_family")

    chosen_model = _resolve_family_model(
        provider_key=provider_key,
        requested_model="",
        current_provider=current_provider,
        current_model_id=current_model_id,
        entry=entry,
    )
    if not chosen_model:
        return _skipped_scenario("openclaw:current", "current_primary_model_unresolved")

    real_base_url = _string_value(entry.get("realBaseUrl"))
    if not real_base_url:
        return _skipped_scenario("openclaw:current", "missing_current_upstream_base_url")

    model_ref = _normalize_openclaw_model_ref(provider_key, chosen_model)
    return {
        "name": f"openclaw:{family}",
        "family": family,
        "providerKey": provider_key,
        "modelRef": model_ref,
        "realBaseUrl": real_base_url.rstrip("/"),
        "apiFamily": family,
        "providerFields": dict(entry.get("providerFields") or {}),
        "expectedTapPathFragment": (
            "/v1/messages" if family == "anthropic-messages" else "/chat/completions"
        ),
        "source": "current_primary",
    }


def resolve_openclaw_family_scenarios(
    *,
    paths: Dict[str, Path],
    args: argparse.Namespace,
) -> List[Dict[str, object]]:
    scenarios: List[Dict[str, object]] = []
    requested_families = parse_openclaw_families(args.openclaw_families)
    provider_entries = _collect_openclaw_provider_entries(
        config_path=paths["openclaw_config"],
        models_cache_path=paths["openclaw_models_cache"],
    )
    current_provider, current_model_id = _openclaw_current_primary(paths["openclaw_config"])

    if requested_families == (CURRENT_OPENCLAW_FAMILY_TOKEN,):
        return [
            _resolve_current_primary_scenario(
                current_provider=current_provider,
                current_model_id=current_model_id,
                provider_entries=provider_entries,
            )
        ]

    for family in requested_families:
        if family == "openai-completions":
            requested_provider = str(args.openclaw_openai_provider or "").strip()
            requested_model = str(args.openclaw_openai_model or "").strip()
            requested_base_url = ""
        else:
            requested_provider = str(args.openclaw_anthropic_provider or "").strip()
            requested_model = str(args.openclaw_anthropic_model or "").strip()
            requested_base_url = str(args.openclaw_anthropic_base_url or "").strip()

        entry = _resolve_family_provider(
            family=family,
            requested_provider=requested_provider,
            current_provider=current_provider,
            provider_entries=provider_entries,
        )
        if entry is None:
            reason = (
                "requested_provider_not_found"
                if requested_provider
                else "current_primary_family_mismatch"
            )
            scenarios.append(_error_scenario(family, reason))
            continue

        provider_key = _string_value(entry.get("providerKey"))
        if not provider_key:
            scenarios.append(_error_scenario(family, "missing_provider_key"))
            continue
        if entry.get("apiFamily") != family:
            scenarios.append(_error_scenario(family, "provider_family_mismatch"))
            continue

        chosen_model = _resolve_family_model(
            provider_key=provider_key,
            requested_model=requested_model,
            current_provider=current_provider,
            current_model_id=current_model_id,
            entry=entry,
        )
        if not chosen_model:
            reason = (
                "requested_model_missing"
                if requested_model
                else "current_primary_model_unresolved"
            )
            scenarios.append(_error_scenario(family, reason))
            continue

        real_base_url = _string_value(entry.get("realBaseUrl")) or _string_value(
            requested_base_url
        )
        if not real_base_url:
            scenarios.append(_error_scenario(family, "missing_upstream_base_url"))
            continue

        model_ref = _normalize_openclaw_model_ref(provider_key, chosen_model)
        scenarios.append(
            {
                "name": f"openclaw:{family}",
                "family": family,
                "providerKey": provider_key,
                "modelRef": model_ref,
                "realBaseUrl": real_base_url.rstrip("/"),
                "apiFamily": family,
                "providerFields": dict(entry.get("providerFields") or {}),
                "expectedTapPathFragment": (
                    "/v1/messages" if family == "anthropic-messages" else "/chat/completions"
                ),
                "source": "existing_provider",
            }
        )

    return scenarios
