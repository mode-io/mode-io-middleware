from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict, List

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


def parse_openclaw_families(raw: str) -> tuple[str, ...]:
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


def resolve_openclaw_family_scenarios(
    *,
    paths: Dict[str, Path],
    args: argparse.Namespace,
) -> List[Dict[str, object]]:
    scenarios: List[Dict[str, object]] = []
    requested_families = parse_openclaw_families(args.openclaw_families)
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
