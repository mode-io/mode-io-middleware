from __future__ import annotations

from typing import Any, Dict, Iterable


def build_openclaw_provider(
    *,
    api: str,
    base_url: str,
    models: Iterable[Dict[str, Any]] | None = None,
    extra: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "api": api,
        "baseUrl": base_url,
    }
    if models is not None:
        payload["models"] = list(models)
    if extra:
        payload.update(extra)
    return payload


def build_openclaw_config(
    *,
    primary: str,
    providers: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    return {
        "agents": {"defaults": {"model": {"primary": primary}}},
        "models": {"providers": providers},
    }


def build_openclaw_models_cache(
    *,
    providers: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    return {
        "models": {"providers": providers},
    }


def build_openclaw_route_metadata(
    providers: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    return {
        "providers": providers,
    }
