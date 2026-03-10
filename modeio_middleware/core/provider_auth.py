#!/usr/bin/env python3

from __future__ import annotations

import base64
import json
import os
import time
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request
from urllib.parse import urlparse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Protocol

from modeio_middleware.connectors.client_identity import (
    CLIENT_CODEX,
    CLIENT_OPENCODE,
    CLIENT_OPENCLAW,
    CLIENT_UNKNOWN,
)
from modeio_middleware.core.upstream_plan import (
    ResolvedAuthMaterial,
    ResolvedCredential,
    ResolvedUpstreamPlan,
)

AUTH_KIND_API_KEY = "api_key"
AUTH_KIND_MISSING = "missing"
AUTH_KIND_OAUTH = "oauth"
AUTH_KIND_TOKEN = "token"

TRANSPORT_CODEX_NATIVE = "codex_native"
TRANSPORT_OPENAI_COMPAT = "openai_compat"

PROVIDER_ANTHROPIC = "anthropic"
PROVIDER_GITHUB_COPILOT = "github-copilot"
PROVIDER_GOOGLE_GEMINI_CLI = "google-gemini-cli"
PROVIDER_MODEIO_MIDDLEWARE = "modeio-middleware"
PROVIDER_OPENAI = "openai"
PROVIDER_OPENAI_CODEX = "openai-codex"
OPENAI_COMPAT_BASE_URL = "https://api.openai.com/v1"

OPENAI_CODEX_OAUTH_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
OPENAI_CODEX_TOKEN_URL = "https://auth.openai.com/oauth/token"
OPENAI_CODEX_JWT_CLAIM_PATH = "https://api.openai.com/auth"

LOCAL_AUTH_PLACEHOLDER = PROVIDER_MODEIO_MIDDLEWARE
PROVIDER_ALIASES = {
    "codex": PROVIDER_OPENAI_CODEX,
    "openai_codex": PROVIDER_OPENAI_CODEX,
}
OPENCLAW_SUPPORTED_API_FAMILIES = frozenset(
    {
        "openai-completions",
        "anthropic-messages",
    }
)

def normalize_provider_id(raw_provider_id: str | None) -> str:
    text = str(raw_provider_id or "").strip().lower().replace("_", "-")
    if not text:
        return ""
    return PROVIDER_ALIASES.get(text, text)


def _env_mapping(env: Mapping[str, str] | None = None) -> dict[str, str]:
    return dict(env or os.environ)


def _home(env: Mapping[str, str]) -> Path:
    return Path(env.get("HOME", str(Path.home()))).expanduser()


def _header(headers: Mapping[str, str], name: str) -> str:
    target = name.lower()
    for key, value in headers.items():
        if key.lower() == target:
            return str(value)
    return ""


def _looks_like_placeholder(auth_header: str) -> bool:
    lower_value = auth_header.strip().lower()
    return lower_value in {
        f"bearer {LOCAL_AUTH_PLACEHOLDER}",
        LOCAL_AUTH_PLACEHOLDER,
    }


def _read_json_object(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _bearer(value: str) -> str | None:
    token = str(value).strip()
    if not token:
        return None
    return f"Bearer {token}"


def _anthropic_uses_bearer_auth(value: str, *, auth_kind: str) -> bool:
    token = str(value).strip()
    if not token:
        return False
    if auth_kind == AUTH_KIND_OAUTH:
        return True
    return token.startswith("sk-ant-oat")


def _decode_jwt_claims(token: str) -> dict[str, Any] | None:
    parts = token.split(".")
    if len(parts) < 2:
        return None
    payload = parts[1]
    padding = "=" * (-len(payload) % 4)
    try:
        raw = base64.urlsafe_b64decode(payload + padding)
        decoded = json.loads(raw.decode("utf-8"))
    except Exception:
        return None
    return decoded if isinstance(decoded, dict) else None


def _write_json_object(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _extract_openai_account_id(access_token: str) -> str | None:
    claims = _decode_jwt_claims(access_token) or {}
    auth_claim = claims.get(OPENAI_CODEX_JWT_CLAIM_PATH)
    if isinstance(auth_claim, dict):
        account_id = auth_claim.get("chatgpt_account_id")
        if isinstance(account_id, str) and account_id.strip():
            return account_id.strip()
    return None


def _codex_native_base_url(env: Mapping[str, str]) -> str:
    override = str(env.get("MODEIO_CODEX_NATIVE_BASE_URL") or "").strip()
    if override:
        return override.rstrip("/")
    return "https://chatgpt.com/backend-api/codex"


def _refresh_openai_codex_oauth(refresh_token: str) -> dict[str, Any] | None:
    token = str(refresh_token).strip()
    if not token:
        return None
    body = urllib_parse.urlencode(
        {
            "grant_type": "refresh_token",
            "refresh_token": token,
            "client_id": OPENAI_CODEX_OAUTH_CLIENT_ID,
        }
    ).encode()
    request = urllib_request.Request(
        OPENAI_CODEX_TOKEN_URL,
        data=body,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib_request.urlopen(request, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib_error.URLError, urllib_error.HTTPError, ValueError):
        return None

    access = str(payload.get("access_token") or "").strip()
    refresh = str(payload.get("refresh_token") or token).strip()
    expires_in = payload.get("expires_in")
    if not access:
        return None
    expires_ms = None
    if isinstance(expires_in, (int, float)):
        expires_ms = int(time.time() * 1000) + int(expires_in * 1000)
    return {
        "access": access,
        "refresh": refresh,
        "expires": expires_ms,
        "accountId": _extract_openai_account_id(access),
    }


@dataclass(frozen=True)
class AuthContext:
    client_name: str
    provider_id: str
    env: Mapping[str, str] = field(default_factory=dict)
    health_store: "CredentialHealthStore | None" = None


@dataclass(frozen=True)
class CredentialInspection:
    provider_id: str
    auth_kind: str
    ready: bool
    guaranteed: bool
    strategy: str
    transport: str = TRANSPORT_OPENAI_COMPAT
    reason: str | None = None
    auth_source: str | None = None
    path: str | None = None
    auth_env: str | None = None
    authorization: str | None = None
    resolved_headers: dict[str, str] = field(default_factory=dict)
    audience: Any = None
    scopes: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def auth_material(self) -> ResolvedAuthMaterial:
        return resolve_inspection_auth_material(self)

    @property
    def upstream_plan(self) -> ResolvedUpstreamPlan:
        return resolve_inspection_upstream_plan(self)

    def to_public_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "providerId": self.provider_id,
            "ready": self.ready,
            "guaranteed": self.guaranteed,
            "strategy": self.strategy,
            "transport": self.transport,
        }
        if self.reason is not None:
            payload["reason"] = self.reason
        if self.auth_source is not None:
            payload["authSource"] = self.auth_source
        if self.path is not None:
            payload["path"] = self.path
        if self.auth_env is not None:
            payload["authEnv"] = self.auth_env
        if self.audience is not None:
            payload["audience"] = self.audience
        if self.scopes:
            payload["scopes"] = list(self.scopes)
        payload.update(self.metadata)
        return payload


def _default_api_family(provider_id: str) -> str:
    normalized = normalize_provider_id(provider_id)
    if normalized == PROVIDER_ANTHROPIC:
        return "anthropic-messages"
    if normalized == PROVIDER_OPENAI_CODEX:
        return "openai-codex-responses"
    return "openai-completions"


def _default_transport_kind(provider_id: str) -> str:
    if normalize_provider_id(provider_id) == PROVIDER_OPENAI_CODEX:
        return TRANSPORT_CODEX_NATIVE
    return TRANSPORT_OPENAI_COMPAT


def resolve_inspection_credential(inspection: CredentialInspection) -> ResolvedCredential:
    source = getattr(inspection, "auth_source", None) or getattr(inspection, "auth_env", None)
    auth_kind = str(getattr(inspection, "auth_kind", AUTH_KIND_MISSING) or AUTH_KIND_MISSING)
    guaranteed = bool(getattr(inspection, "guaranteed", False))
    reason = getattr(inspection, "reason", None)
    refresh_state = None
    if auth_kind == AUTH_KIND_OAUTH and bool(getattr(inspection, "ready", False)):
        refresh_state = "reusable"
    return ResolvedCredential(
        provider_id=str(getattr(inspection, "provider_id", "")),
        auth_kind=auth_kind,
        source=source,
        guaranteed=guaranteed,
        best_effort_reason=reason if not guaranteed else None,
        refresh_state=refresh_state,
    )


def resolve_inspection_auth_material(
    inspection: CredentialInspection,
) -> ResolvedAuthMaterial:
    metadata = getattr(inspection, "metadata", None)
    metadata = metadata if isinstance(metadata, dict) else {}
    account_id = metadata.get("accountId")
    return ResolvedAuthMaterial(
        authorization=getattr(inspection, "authorization", None),
        resolved_headers=dict(getattr(inspection, "resolved_headers", {}) or {}),
        account_id=account_id.strip() if isinstance(account_id, str) and account_id.strip() else None,
    )


def resolve_inspection_upstream_plan(
    inspection: CredentialInspection,
) -> ResolvedUpstreamPlan:
    metadata = getattr(inspection, "metadata", None)
    metadata = metadata if isinstance(metadata, dict) else {}
    provider_id = str(getattr(inspection, "provider_id", "") or metadata.get("providerId") or "")
    unsupported_family = None
    if metadata.get("unsupportedFamily"):
        unsupported_family = str(metadata.get("apiFamily") or _default_api_family(provider_id))
    supported_families = ()
    raw_supported = metadata.get("supportedFamilies")
    if isinstance(raw_supported, list):
        supported_families = tuple(str(item) for item in raw_supported if str(item).strip())
    base_url = metadata.get("upstreamBaseUrl")
    if not isinstance(base_url, str) or not base_url.strip():
        native_base = metadata.get("nativeBaseUrl")
        if isinstance(native_base, str) and native_base.strip():
            base_url = native_base.strip()
        else:
            base_url = None
    model_override = metadata.get("modelOverride")
    if not isinstance(model_override, str) or not model_override.strip():
        model_override = None
    transport_kind = str(
        getattr(inspection, "transport", "") or _default_transport_kind(provider_id)
    )
    native_base_url = (
        str(metadata.get("nativeBaseUrl")).strip().rstrip("/")
        if isinstance(metadata.get("nativeBaseUrl"), str)
        and str(metadata.get("nativeBaseUrl")).strip()
        else None
    )
    if transport_kind == TRANSPORT_CODEX_NATIVE and native_base_url is None:
        transport_kind = TRANSPORT_OPENAI_COMPAT
    return ResolvedUpstreamPlan(
        provider_id=str(metadata.get("providerId") or provider_id),
        transport_kind=transport_kind,
        api_family=str(metadata.get("apiFamily") or _default_api_family(provider_id)),
        upstream_base_url=(
            base_url.strip().rstrip("/")
            if isinstance(base_url, str) and base_url.strip()
            else None
        ),
        native_base_url=native_base_url,
        model_override=model_override,
        unsupported_family=unsupported_family,
        supported_families=supported_families,
        metadata=dict(metadata),
    )


def _context_upstream_plan(
    *,
    client_name: str,
    provider_id: str,
    env: Mapping[str, str],
) -> ResolvedUpstreamPlan:
    normalized_provider = normalize_provider_id(provider_id)
    metadata: dict[str, Any] = {"providerId": normalized_provider}
    if client_name == CLIENT_OPENCLAW:
        api_family = _openclaw_current_api_family(normalized_provider, env)
        upstream_base_url = _openclaw_preserved_upstream_base_url(normalized_provider, env)
        if upstream_base_url:
            metadata["upstreamBaseUrl"] = upstream_base_url
        if api_family not in OPENCLAW_SUPPORTED_API_FAMILIES:
            return ResolvedUpstreamPlan(
                provider_id=normalized_provider,
                transport_kind=_default_transport_kind(normalized_provider),
                api_family=api_family,
                upstream_base_url=upstream_base_url,
                unsupported_family=api_family,
                supported_families=tuple(sorted(OPENCLAW_SUPPORTED_API_FAMILIES)),
                metadata=metadata,
            )
        return ResolvedUpstreamPlan(
            provider_id=normalized_provider,
            transport_kind=_default_transport_kind(normalized_provider),
            api_family=api_family,
            upstream_base_url=upstream_base_url,
            metadata=metadata,
        )

    if normalized_provider == PROVIDER_OPENAI_CODEX:
        native_base_url = _codex_native_base_url(env)
        metadata["nativeBaseUrl"] = native_base_url
        return ResolvedUpstreamPlan(
            provider_id=normalized_provider,
            transport_kind=TRANSPORT_CODEX_NATIVE,
            api_family="openai-codex-responses",
            native_base_url=native_base_url,
            metadata=metadata,
        )

    if client_name == CLIENT_OPENCODE:
        upstream_base_url = _opencode_preserved_upstream_base_url(normalized_provider, env)
        if upstream_base_url:
            metadata["upstreamBaseUrl"] = upstream_base_url
        return ResolvedUpstreamPlan(
            provider_id=normalized_provider,
            transport_kind=TRANSPORT_OPENAI_COMPAT,
            api_family=_default_api_family(normalized_provider),
            upstream_base_url=upstream_base_url,
            metadata=metadata,
        )

    if normalized_provider == PROVIDER_OPENAI:
        metadata["upstreamBaseUrl"] = OPENAI_COMPAT_BASE_URL

    return ResolvedUpstreamPlan(
        provider_id=normalized_provider,
        transport_kind=_default_transport_kind(normalized_provider),
        api_family=_default_api_family(normalized_provider),
        upstream_base_url=metadata.get("upstreamBaseUrl"),
        metadata=metadata,
    )


@dataclass(frozen=True)
class CredentialHealth:
    provider_id: str
    status: str
    guaranteed: bool
    reason: str | None = None
    profile_id: str | None = None
    cooldown_until_ms: int | None = None
    last_good_at_ms: int | None = None


@dataclass
class CredentialHealthStore:
    entries: dict[str, CredentialHealth] = field(default_factory=dict)

    def _key(self, provider_id: str, profile_id: str | None = None) -> str:
        return f"{provider_id}:{profile_id}" if profile_id else provider_id

    def snapshot(
        self,
        inspection: CredentialInspection,
        *,
        profile_id: str | None = None,
    ) -> CredentialHealth:
        status = "ok" if inspection.ready else AUTH_KIND_MISSING
        now_ms = int(time.time() * 1000)
        entry = CredentialHealth(
            provider_id=inspection.provider_id,
            status=status,
            guaranteed=inspection.guaranteed,
            reason=inspection.reason,
            profile_id=profile_id,
            last_good_at_ms=now_ms if inspection.ready else None,
        )
        self.entries[self._key(inspection.provider_id, profile_id)] = entry
        return entry

    def mark_cooldown(
        self,
        *,
        provider_id: str,
        profile_id: str | None,
        reason: str,
        cooldown_seconds: int,
    ) -> None:
        self.entries[self._key(provider_id, profile_id)] = CredentialHealth(
            provider_id=provider_id,
            status="cooldown",
            guaranteed=False,
            reason=reason,
            profile_id=profile_id,
            cooldown_until_ms=int(time.time() * 1000) + max(cooldown_seconds, 0) * 1000,
        )

    def get(self, provider_id: str, profile_id: str | None = None) -> CredentialHealth | None:
        return self.entries.get(self._key(provider_id, profile_id))


@dataclass(frozen=True)
class OpenClawSelection:
    provider_id: str
    profile_id: str | None
    reason: str
    credential: dict[str, Any] | None


def _missing(
    provider_id: str,
    *,
    strategy: str,
    reason: str,
    path: str | None = None,
    auth_env: str | None = None,
    metadata: dict[str, Any] | None = None,
    transport: str = TRANSPORT_OPENAI_COMPAT,
) -> CredentialInspection:
    return CredentialInspection(
        provider_id=provider_id,
        auth_kind=AUTH_KIND_MISSING,
        ready=False,
        guaranteed=False,
        strategy=strategy,
        transport=transport,
        reason=reason,
        path=path,
        auth_env=auth_env,
        metadata=dict(metadata or {}),
    )


def _ready(
    provider_id: str,
    *,
    auth_kind: str,
    guaranteed: bool,
    strategy: str,
    authorization: str,
    resolved_headers: dict[str, str] | None = None,
    auth_source: str | None = None,
    path: str | None = None,
    auth_env: str | None = None,
    reason: str | None = None,
    metadata: dict[str, Any] | None = None,
    audience: Any = None,
    scopes: list[str] | None = None,
    transport: str = TRANSPORT_OPENAI_COMPAT,
) -> CredentialInspection:
    return CredentialInspection(
        provider_id=provider_id,
        auth_kind=auth_kind,
        ready=True,
        guaranteed=guaranteed,
        strategy=strategy,
        transport=transport,
        reason=reason,
        auth_source=auth_source,
        path=path,
        auth_env=auth_env,
        authorization=authorization,
        resolved_headers=dict(resolved_headers or {}),
        audience=audience,
        scopes=list(scopes or []),
        metadata=dict(metadata or {}),
    )


def _codex_auth_path(env: Mapping[str, str]) -> Path:
    return _home(env) / ".codex" / "auth.json"


def _inspect_codex_store(env: Mapping[str, str]) -> CredentialInspection:
    provider_id = PROVIDER_OPENAI_CODEX
    auth_path = _codex_auth_path(env)
    payload = _read_json_object(auth_path)
    if payload is None:
        env_api_key = str(env.get("OPENAI_API_KEY") or "").strip()
        if env_api_key:
            return _ready(
                PROVIDER_OPENAI,
                auth_kind=AUTH_KIND_API_KEY,
                guaranteed=True,
                strategy="provider-env",
                auth_env="OPENAI_API_KEY",
                authorization=_bearer(env_api_key) or "",
                transport=TRANSPORT_OPENAI_COMPAT,
                metadata={
                    "providerId": PROVIDER_OPENAI,
                    "upstreamBaseUrl": OPENAI_COMPAT_BASE_URL,
                },
            )
        return _missing(
            provider_id,
            strategy="missing",
            reason="codex auth store not found",
            path=str(auth_path),
            transport=TRANSPORT_CODEX_NATIVE,
        )

    tokens = payload.get("tokens")
    if isinstance(tokens, dict):
        access_token = tokens.get("access_token")
        refresh_token = tokens.get("refresh_token")
        if isinstance(access_token, str) and access_token.strip():
            claims = _decode_jwt_claims(access_token.strip()) or {}
            scopes = claims.get("scp")
            expiry_ms = claims.get("exp")
            if isinstance(expiry_ms, (int, float)):
                expiry_ms = int(expiry_ms * 1000)
            if isinstance(expiry_ms, int) and expiry_ms <= int(time.time() * 1000):
                refreshed = None
                if isinstance(refresh_token, str) and refresh_token.strip():
                    refreshed = _refresh_openai_codex_oauth(refresh_token)
                if refreshed:
                    tokens["access_token"] = refreshed["access"]
                    tokens["refresh_token"] = refreshed["refresh"]
                    tokens["account_id"] = refreshed.get("accountId") or tokens.get("account_id")
                    payload["tokens"] = tokens
                    payload["last_refresh"] = int(time.time() * 1000)
                    _write_json_object(auth_path, payload)
                    access_token = refreshed["access"]
                    claims = _decode_jwt_claims(access_token.strip()) or {}
                    scopes = claims.get("scp")
            account_id = tokens.get("account_id") or _extract_openai_account_id(
                access_token.strip()
            )
            metadata = {
                "providerId": provider_id,
                "accountId": account_id,
                "nativeBaseUrl": _codex_native_base_url(env),
            }
            return _ready(
                provider_id,
                auth_kind=AUTH_KIND_OAUTH,
                guaranteed=False,
                strategy="oauth-bridge",
                auth_source="codex.tokens.access_token",
                path=str(auth_path),
                authorization=_bearer(access_token) or "",
                audience=claims.get("aud"),
                scopes=scopes if isinstance(scopes, list) else [],
                transport=TRANSPORT_CODEX_NATIVE,
                reason=(
                    "Codex provides OAuth access tokens, but public OpenAI-compatible `/v1/models` and `/v1/responses` may reject them or require different scopes."
                ),
                metadata=metadata,
            )

    api_key = payload.get("OPENAI_API_KEY")
    if isinstance(api_key, str) and api_key.strip():
        return _ready(
            provider_id,
            auth_kind=AUTH_KIND_API_KEY,
            guaranteed=True,
            strategy="api-key",
            auth_source="codex.OPENAI_API_KEY",
            path=str(auth_path),
            authorization=_bearer(api_key) or "",
            transport=TRANSPORT_OPENAI_COMPAT,
            metadata={
                "providerId": PROVIDER_OPENAI,
                "upstreamBaseUrl": OPENAI_COMPAT_BASE_URL,
            },
        )

    return _missing(
        provider_id,
        strategy="missing",
        reason="codex auth store has no reusable API key or access token",
        path=str(auth_path),
        transport=TRANSPORT_CODEX_NATIVE,
    )


def _opencode_config_path(env: Mapping[str, str]) -> Path:
    xdg_config = env.get("XDG_CONFIG_HOME", "").strip()
    if xdg_config:
        return Path(xdg_config).expanduser() / "opencode" / "opencode.json"
    return _home(env) / ".config" / "opencode" / "opencode.json"


def _opencode_state_path(env: Mapping[str, str]) -> Path:
    xdg_state = env.get("XDG_STATE_HOME", "").strip()
    if xdg_state:
        return Path(xdg_state).expanduser() / "opencode" / "model.json"
    return _home(env) / ".local" / "state" / "opencode" / "model.json"


def _opencode_models_cache_path(env: Mapping[str, str]) -> Path:
    xdg_cache = env.get("XDG_CACHE_HOME", "").strip()
    if xdg_cache:
        return Path(xdg_cache).expanduser() / "opencode" / "models.json"
    return _home(env) / ".cache" / "opencode" / "models.json"


def _opencode_auth_store_path(env: Mapping[str, str]) -> Path:
    xdg_data = env.get("XDG_DATA_HOME", "").strip()
    if xdg_data:
        return Path(xdg_data).expanduser() / "opencode" / "auth.json"
    return _home(env) / ".local" / "share" / "opencode" / "auth.json"


def _opencode_auth_store(env: Mapping[str, str]) -> dict[str, Any]:
    payload = _read_json_object(_opencode_auth_store_path(env))
    return payload if isinstance(payload, dict) else {}


def _opencode_route_metadata_path(env: Mapping[str, str]) -> Path:
    config_path = _opencode_config_path(env)
    return config_path.with_name(f"{config_path.name}.modeio-route.json")


def _opencode_route_metadata(env: Mapping[str, str]) -> dict[str, Any]:
    payload = _read_json_object(_opencode_route_metadata_path(env))
    return payload if isinstance(payload, dict) else {}


def _is_loopback_base_url(value: str | None) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    try:
        hostname = (urlparse(text).hostname or "").lower()
    except Exception:
        return False
    return hostname in {"127.0.0.1", "localhost", "::1"}


def _opencode_provider_object(
    payload: dict[str, Any] | None,
    provider_id: str,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    providers = payload.get("provider")
    if not isinstance(providers, dict):
        return {}
    provider_obj = providers.get(provider_id)
    return provider_obj if isinstance(provider_obj, dict) else {}


def _opencode_provider_base_url(
    provider_obj: Mapping[str, Any],
) -> str | None:
    options_obj = provider_obj.get("options")
    if isinstance(options_obj, Mapping):
        for field_name in ("baseURL", "baseUrl"):
            value = options_obj.get(field_name)
            if isinstance(value, str) and value.strip():
                return value.strip().rstrip("/")
    for field_name in ("baseURL", "baseUrl"):
        value = provider_obj.get(field_name)
        if isinstance(value, str) and value.strip():
            return value.strip().rstrip("/")
    return None


def _opencode_default_upstream_base_url(provider_id: str) -> str | None:
    if normalize_provider_id(provider_id) == PROVIDER_OPENAI:
        return OPENAI_COMPAT_BASE_URL
    return None


def _opencode_preserved_upstream_base_url(
    provider_id: str,
    env: Mapping[str, str],
    *,
    payload: dict[str, Any] | None = None,
    provider_obj: Mapping[str, Any] | None = None,
) -> str | None:
    metadata = _opencode_route_metadata(env)
    providers = metadata.get("providers")
    normalized_provider = normalize_provider_id(provider_id)
    if isinstance(providers, dict):
        entry = providers.get(normalized_provider)
        if isinstance(entry, dict):
            value = entry.get("originalBaseUrl")
            if isinstance(value, str) and value.strip():
                return value.strip().rstrip("/")

    resolved_provider_obj = (
        provider_obj
        if isinstance(provider_obj, Mapping)
        else _opencode_provider_object(payload, normalized_provider)
    )
    config_base_url = _opencode_provider_base_url(resolved_provider_obj)
    if config_base_url and not _is_loopback_base_url(config_base_url):
        return config_base_url
    return _opencode_default_upstream_base_url(normalized_provider)


def _opencode_current_provider(
    payload: dict[str, Any] | None,
    env: Mapping[str, str],
    explicit_provider_id: str | None = None,
) -> str | None:
    if explicit_provider_id:
        return normalize_provider_id(explicit_provider_id)
    if isinstance(payload, dict):
        model_name = payload.get("model")
        if isinstance(model_name, str) and "/" in model_name:
            provider_id, _ = model_name.split("/", 1)
            if provider_id.strip():
                return normalize_provider_id(provider_id)

    state_payload = _read_json_object(_opencode_state_path(env))
    if isinstance(state_payload, dict):
        recent = state_payload.get("recent")
        if isinstance(recent, list) and recent:
            first = recent[0]
            if isinstance(first, dict):
                provider_id = first.get("providerID")
                if isinstance(provider_id, str) and provider_id.strip():
                    return normalize_provider_id(provider_id)
    return None


def _opencode_provider_envs(provider_id: str, env: Mapping[str, str]) -> list[str]:
    payload = _read_json_object(_opencode_models_cache_path(env))
    if not isinstance(payload, dict):
        return []
    provider = payload.get(provider_id)
    if not isinstance(provider, dict):
        return []
    envs = provider.get("env")
    if not isinstance(envs, list):
        return []
    result: list[str] = []
    for value in envs:
        if isinstance(value, str) and value.strip() and value.strip() not in result:
            result.append(value.strip())
    return result


def _inspect_opencode_provider(
    provider_id: str,
    env: Mapping[str, str],
) -> CredentialInspection:
    payload = _read_json_object(_opencode_config_path(env))
    selected_provider = _opencode_current_provider(payload, env, provider_id)
    if selected_provider is None:
        return _missing(
            provider_id,
            strategy="missing",
            reason="unable to determine current OpenCode provider",
            path=str(_opencode_config_path(env)),
        )

    provider_obj = _opencode_provider_object(payload, selected_provider)
    upstream_base_url = _opencode_preserved_upstream_base_url(
        selected_provider,
        env,
        payload=payload,
        provider_obj=provider_obj,
    )
    base_metadata = {
        "providerId": selected_provider,
        "configPath": str(_opencode_config_path(env)),
    }
    if upstream_base_url:
        base_metadata["upstreamBaseUrl"] = upstream_base_url
    else:
        return _missing(
            selected_provider,
            strategy="missing",
            reason=(
                f"OpenCode provider '{selected_provider}' has no recoverable upstream base URL"
            ),
            path=str(_opencode_config_path(env)),
            metadata=base_metadata,
        )

    auth_store_path = _opencode_auth_store_path(env)
    auth_store = _opencode_auth_store(env)
    auth_entry = auth_store.get(selected_provider)
    if (
        normalize_provider_id(selected_provider) == PROVIDER_OPENAI
        and isinstance(auth_entry, dict)
        and str(auth_entry.get("type") or "").strip() == AUTH_KIND_OAUTH
    ):
        metadata = dict(base_metadata)
        metadata.update(
            {
                "authStorePath": str(auth_store_path),
                "supported": False,
                "unsupportedTransport": True,
            }
        )
        return _missing(
            selected_provider,
            strategy="unsupported_transport",
            reason=(
                "OpenCode provider 'openai' is using OpenCode's native OAuth transport and cannot be rerouted through middleware preserve-provider mode."
            ),
            path=str(auth_store_path),
            metadata=metadata,
        )

    for candidate in (
        provider_obj.get("apiKey"),
        provider_obj.get("options", {}).get("apiKey")
        if isinstance(provider_obj.get("options"), dict)
        else None,
    ):
        if (
            isinstance(candidate, str)
            and candidate.strip()
            and candidate.strip() != LOCAL_AUTH_PLACEHOLDER
        ):
            return _ready(
                selected_provider,
                auth_kind=AUTH_KIND_API_KEY,
                guaranteed=True,
                strategy="config-api-key",
                auth_source=f"provider.{selected_provider}.options.apiKey",
                path=str(_opencode_config_path(env)),
                authorization=_bearer(candidate) or "",
                metadata=base_metadata,
            )

    if isinstance(auth_entry, dict):
        access_token = auth_entry.get("access")
        if isinstance(access_token, str) and access_token.strip():
            metadata = dict(base_metadata)
            metadata["authStorePath"] = str(auth_store_path)
            account_id = auth_entry.get("accountId")
            if isinstance(account_id, str) and account_id.strip():
                metadata["accountId"] = account_id.strip()
            return _ready(
                selected_provider,
                auth_kind=AUTH_KIND_OAUTH,
                guaranteed=False,
                strategy="auth-store-oauth",
                auth_source=f"auth_store.{selected_provider}.access",
                path=str(_opencode_auth_store_path(env)),
                authorization=_bearer(access_token) or "",
                metadata=metadata,
            )

        api_key = auth_entry.get("key")
        if isinstance(api_key, str) and api_key.strip():
            metadata = dict(base_metadata)
            metadata["authStorePath"] = str(auth_store_path)
            return _ready(
                selected_provider,
                auth_kind=AUTH_KIND_API_KEY,
                guaranteed=True,
                strategy="auth-store-api-key",
                auth_source=f"auth_store.{selected_provider}.key",
                path=str(_opencode_auth_store_path(env)),
                authorization=_bearer(api_key) or "",
                metadata=metadata,
            )

    env_candidates = _opencode_provider_envs(selected_provider, env)
    for env_name in env_candidates:
        env_value = env.get(env_name, "").strip()
        if env_value:
            return _ready(
                selected_provider,
                auth_kind=AUTH_KIND_API_KEY,
                guaranteed=True,
                strategy="provider-env",
                auth_env=env_name,
                authorization=_bearer(env_value) or "",
                metadata=base_metadata,
            )

    return _missing(
        selected_provider,
        strategy="missing",
        reason=(
            f"OpenCode provider '{selected_provider}' has no reusable auth in config or the provider env vars are unset"
        ),
        metadata={
            **base_metadata,
            "envCandidates": env_candidates,
        },
    )


def _openclaw_state_dir(env: Mapping[str, str]) -> Path:
    raw_state = env.get("OPENCLAW_STATE_DIR", "").strip() or env.get(
        "CLAWDBOT_STATE_DIR", ""
    ).strip()
    if raw_state:
        return Path(raw_state).expanduser()

    raw_agent = env.get("OPENCLAW_AGENT_DIR", "").strip() or env.get(
        "PI_CODING_AGENT_DIR", ""
    ).strip()
    if raw_agent:
        return Path(raw_agent).expanduser().parent.parent.parent

    return _home(env) / ".openclaw"


def _openclaw_agent_dir(env: Mapping[str, str]) -> Path:
    raw_agent = env.get("OPENCLAW_AGENT_DIR", "").strip() or env.get(
        "PI_CODING_AGENT_DIR", ""
    ).strip()
    if raw_agent:
        return Path(raw_agent).expanduser()
    return _openclaw_state_dir(env) / "agents" / "main" / "agent"


def _openclaw_auth_profiles_path(env: Mapping[str, str]) -> Path:
    return _openclaw_agent_dir(env) / "auth-profiles.json"


def _openclaw_models_cache_path(env: Mapping[str, str]) -> Path:
    return _openclaw_agent_dir(env) / "models.json"


def _openclaw_route_metadata_path(env: Mapping[str, str]) -> Path:
    config_path = _openclaw_state_dir(env) / "openclaw.json"
    return config_path.with_name(f"{config_path.name}.modeio-route.json")


def _openclaw_route_metadata(env: Mapping[str, str]) -> dict[str, Any]:
    payload = _read_json_object(_openclaw_route_metadata_path(env))
    return payload if isinstance(payload, dict) else {}


def _openclaw_route_provider_metadata(
    env: Mapping[str, str],
    provider_id: str,
) -> dict[str, Any]:
    payload = _openclaw_route_metadata(env)
    providers = payload.get("providers")
    normalized_provider = normalize_provider_id(provider_id)
    if isinstance(providers, dict):
        entry = providers.get(normalized_provider)
        if isinstance(entry, dict):
            return entry
        for candidate in providers.values():
            if not isinstance(candidate, dict):
                continue
            candidate_provider = normalize_provider_id(candidate.get("providerId"))
            if candidate_provider == normalized_provider:
                return candidate
    return {}


def _openclaw_models_cache_providers(env: Mapping[str, str]) -> dict[str, Any]:
    payload = _read_json_object(_openclaw_models_cache_path(env))
    if not isinstance(payload, dict):
        return {}
    providers = payload.get("providers")
    if isinstance(providers, dict):
        return providers
    models_obj = payload.get("models")
    providers = models_obj.get("providers") if isinstance(models_obj, dict) else None
    return providers if isinstance(providers, dict) else {}


def _openclaw_profiles_store(env: Mapping[str, str]) -> dict[str, Any]:
    payload = _read_json_object(_openclaw_auth_profiles_path(env))
    return payload if isinstance(payload, dict) else {"profiles": {}}


def _save_openclaw_profiles_store(env: Mapping[str, str], store: dict[str, Any]) -> None:
    _write_json_object(_openclaw_auth_profiles_path(env), store)


def _openclaw_current_provider(
    env: Mapping[str, str], provider_id: str | None = None
) -> str | None:
    if provider_id:
        return normalize_provider_id(provider_id)
    config_payload = _read_json_object(_openclaw_state_dir(env) / "openclaw.json")
    if isinstance(config_payload, dict):
        agents_obj = config_payload.get("agents")
        defaults_obj = agents_obj.get("defaults") if isinstance(agents_obj, dict) else None
        model_obj = defaults_obj.get("model") if isinstance(defaults_obj, dict) else None
        primary = model_obj.get("primary") if isinstance(model_obj, dict) else None
        if isinstance(primary, str) and "/" in primary:
            current_provider, _ = primary.split("/", 1)
            if current_provider and current_provider != PROVIDER_MODEIO_MIDDLEWARE:
                return normalize_provider_id(current_provider)
    return None


def _openclaw_current_api_family(
    provider_id: str,
    env: Mapping[str, str],
) -> str:
    metadata = _openclaw_route_provider_metadata(env, provider_id)
    api_family = metadata.get("apiFamily")
    if isinstance(api_family, str) and api_family.strip():
        return api_family.strip().lower()
    config_payload = _read_json_object(_openclaw_state_dir(env) / "openclaw.json")
    providers = None
    if isinstance(config_payload, dict):
        models_obj = config_payload.get("models")
        providers = models_obj.get("providers") if isinstance(models_obj, dict) else None
    if isinstance(providers, dict):
        for candidate_key, candidate_value in providers.items():
            if normalize_provider_id(candidate_key) != normalize_provider_id(provider_id):
                continue
            if isinstance(candidate_value, dict):
                api_family = candidate_value.get("api")
                if isinstance(api_family, str) and api_family.strip():
                    return api_family.strip().lower()
    models_cache_providers = _openclaw_models_cache_providers(env)
    if isinstance(models_cache_providers, dict):
        for candidate_key, candidate_value in models_cache_providers.items():
            if normalize_provider_id(candidate_key) != normalize_provider_id(provider_id):
                continue
            if isinstance(candidate_value, dict):
                api_family = candidate_value.get("api")
                if isinstance(api_family, str) and api_family.strip():
                    return api_family.strip().lower()
    normalized_provider = normalize_provider_id(provider_id)
    if normalized_provider == PROVIDER_ANTHROPIC:
        return "anthropic-messages"
    if normalized_provider == PROVIDER_OPENAI_CODEX:
        return "openai-codex-responses"
    return "openai-completions"


def _openclaw_preserved_upstream_base_url(
    provider_id: str,
    env: Mapping[str, str],
) -> str | None:
    metadata = _openclaw_route_provider_metadata(env, provider_id)
    for field_name in ("originalBaseUrl", "originalModelsCacheBaseUrl"):
        value = metadata.get(field_name)
        if isinstance(value, str) and value.strip():
            return value.strip().rstrip("/")
    return None


class OpenClawSelectionResolver:
    def __init__(self, health_store: CredentialHealthStore):
        del health_store

    def resolve(
        self,
        *,
        env: Mapping[str, str],
        provider_id: str | None = None,
    ) -> OpenClawSelection:
        selected_provider = _openclaw_current_provider(env, provider_id)
        if selected_provider is None:
            return OpenClawSelection(
                provider_id=normalize_provider_id(provider_id),
                profile_id=None,
                reason="missing_provider",
                credential=None,
            )

        store = _openclaw_profiles_store(env)
        profiles = store.get("profiles")
        if not isinstance(profiles, dict):
            profiles = {}

        matching: list[tuple[str, dict[str, Any]]] = []
        for profile_id, credential in profiles.items():
            if not isinstance(profile_id, str) or not isinstance(credential, dict):
                continue
            if normalize_provider_id(credential.get("provider")) != selected_provider:
                continue
            matching.append((profile_id, credential))

        if not matching:
            return OpenClawSelection(
                provider_id=selected_provider,
                profile_id=None,
                reason="no_profiles",
                credential=None,
            )

        default_profile = next(
            (
                (profile_id, credential)
                for profile_id, credential in matching
                if profile_id.endswith(":default")
            ),
            None,
        )
        chosen = default_profile or matching[0]
        reason = "default" if default_profile else "first_available"
        return OpenClawSelection(
            provider_id=selected_provider,
            profile_id=chosen[0],
            reason=reason,
            credential=chosen[1],
        )


def _openclaw_profile_inspection(
    provider_id: str,
    env: Mapping[str, str],
    *,
    api_family: str,
    profile_id: str,
    credential: dict[str, Any],
) -> CredentialInspection | None:
    for field_name in (("access", AUTH_KIND_OAUTH), ("apiKey", AUTH_KIND_API_KEY), ("token", AUTH_KIND_TOKEN)):
        value = credential.get(field_name[0])
        if isinstance(value, str) and value.strip():
            expires_ms = credential.get("expires")
            if field_name[1] == AUTH_KIND_OAUTH and isinstance(expires_ms, (int, float)) and int(expires_ms) <= int(time.time() * 1000):
                refreshed = None
                if provider_id == PROVIDER_OPENAI_CODEX:
                    refreshed = _refresh_openai_codex_oauth(str(credential.get("refresh") or ""))
                if refreshed:
                    store = _openclaw_profiles_store(env)
                    profiles = store.get("profiles")
                    if isinstance(profiles, dict) and isinstance(profiles.get(profile_id), dict):
                        profiles[profile_id].update(
                            {
                                "access": refreshed["access"],
                                "refresh": refreshed["refresh"],
                                "expires": refreshed.get("expires") or expires_ms,
                                "accountId": refreshed.get("accountId") or profiles[profile_id].get("accountId"),
                            }
                        )
                        _save_openclaw_profiles_store(env, store)
                        credential = profiles[profile_id]
                        value = credential.get(field_name[0])
            metadata = {
                "providerId": provider_id,
                "selectedProfileId": profile_id,
                "accountId": credential.get("accountId"),
                "apiFamily": api_family,
            }
            upstream_base_url = _openclaw_preserved_upstream_base_url(provider_id, env)
            if upstream_base_url:
                metadata["upstreamBaseUrl"] = upstream_base_url
            if provider_id == PROVIDER_OPENAI_CODEX:
                metadata["nativeBaseUrl"] = _codex_native_base_url(env)
            resolved_headers: dict[str, str] | None = None
            authorization = _bearer(value) or ""
            if api_family == "anthropic-messages" and not _anthropic_uses_bearer_auth(
                str(value),
                auth_kind=field_name[1],
            ):
                resolved_headers = {"x-api-key": str(value).strip()}
                authorization = ""
            return _ready(
                provider_id,
                auth_kind=field_name[1],
                guaranteed=True,
                strategy="auth-profile",
                transport=(
                    TRANSPORT_CODEX_NATIVE
                    if provider_id == PROVIDER_OPENAI_CODEX
                    else TRANSPORT_OPENAI_COMPAT
                ),
                auth_source=f"auth-profiles:{profile_id}",
                path=str(_openclaw_auth_profiles_path(env)),
                authorization=authorization,
                resolved_headers=resolved_headers,
                metadata=metadata,
            )
    return None


def _openclaw_models_cache_inspection(
    provider_id: str, env: Mapping[str, str], *, api_family: str
) -> CredentialInspection | None:
    payload = _read_json_object(_openclaw_models_cache_path(env))
    if payload is None:
        return None

    providers = payload.get("providers")
    if not isinstance(providers, dict):
        models_obj = payload.get("models")
        providers = models_obj.get("providers") if isinstance(models_obj, dict) else None
    if not isinstance(providers, dict):
        return None

    provider = providers.get(provider_id)
    if not isinstance(provider, dict):
        normalized_provider = normalize_provider_id(provider_id)
        for candidate_key, candidate_value in providers.items():
            if normalize_provider_id(candidate_key) != normalized_provider:
                continue
            if isinstance(candidate_value, dict):
                provider = candidate_value
                break
    if not isinstance(provider, dict):
        return None

    api_key = provider.get("apiKey")
    if not isinstance(api_key, str) or not api_key.strip():
        return None
    if api_key.strip() == LOCAL_AUTH_PLACEHOLDER:
        return None

    metadata = {
        "providerId": provider_id,
        "apiFamily": api_family,
    }
    upstream_base_url = _openclaw_preserved_upstream_base_url(provider_id, env)
    if upstream_base_url:
        metadata["upstreamBaseUrl"] = upstream_base_url
    if provider_id == PROVIDER_OPENAI_CODEX:
        metadata["nativeBaseUrl"] = _codex_native_base_url(env)
    resolved_headers: dict[str, str] | None = None
    authorization = _bearer(api_key) or ""
    if api_family == "anthropic-messages" and not _anthropic_uses_bearer_auth(
        api_key,
        auth_kind=AUTH_KIND_API_KEY,
    ):
        resolved_headers = {"x-api-key": api_key.strip()}
        authorization = ""
    return _ready(
        provider_id,
        auth_kind=AUTH_KIND_API_KEY,
        guaranteed=True,
        strategy="models-cache",
        transport=(
            TRANSPORT_CODEX_NATIVE
            if provider_id == PROVIDER_OPENAI_CODEX
            else TRANSPORT_OPENAI_COMPAT
        ),
        auth_source=f"models-cache:{provider_id}",
        path=str(_openclaw_models_cache_path(env)),
        authorization=authorization,
        resolved_headers=resolved_headers,
        metadata=metadata,
    )


def _openclaw_provider_env_inspection(
    provider_id: str,
    env: Mapping[str, str],
    *,
    api_family: str,
) -> CredentialInspection | None:
    normalized_provider = normalize_provider_id(provider_id)
    env_candidates: tuple[str, ...] = ()
    if normalized_provider == PROVIDER_ANTHROPIC:
        env_candidates = ("ANTHROPIC_API_KEY",)
    elif normalized_provider == PROVIDER_OPENAI:
        env_candidates = ("OPENAI_API_KEY",)
    for env_name in env_candidates:
        env_value = env.get(env_name, "").strip()
        if not env_value:
            continue
        resolved_headers: dict[str, str] | None = None
        authorization = _bearer(env_value) or ""
        if api_family == "anthropic-messages" and not _anthropic_uses_bearer_auth(
            env_value,
            auth_kind=AUTH_KIND_API_KEY,
        ):
            resolved_headers = {"x-api-key": env_value}
            authorization = ""
        metadata = {
            "providerId": provider_id,
            "apiFamily": api_family,
        }
        upstream_base_url = _openclaw_preserved_upstream_base_url(provider_id, env)
        if upstream_base_url:
            metadata["upstreamBaseUrl"] = upstream_base_url
        return _ready(
            provider_id,
            auth_kind=AUTH_KIND_API_KEY,
            guaranteed=True,
            strategy="provider-env",
            auth_env=env_name,
            authorization=authorization,
            resolved_headers=resolved_headers,
            metadata=metadata,
            transport=(
                TRANSPORT_CODEX_NATIVE
                if provider_id == PROVIDER_OPENAI_CODEX
                else TRANSPORT_OPENAI_COMPAT
            ),
        )
    return None


def _inspect_openclaw_provider(
    provider_id: str,
    env: Mapping[str, str],
    health_store: CredentialHealthStore | None = None,
) -> CredentialInspection:
    requested_provider = _openclaw_current_provider(env, provider_id)
    if requested_provider is None:
        return _missing(
            provider_id,
            strategy="missing",
            reason="unable to determine current OpenClaw provider",
            metadata={"providerId": normalize_provider_id(provider_id)},
        )

    requested_api_family = _openclaw_current_api_family(requested_provider, env)
    requested_upstream_base_url = _openclaw_preserved_upstream_base_url(
        requested_provider,
        env,
    )

    resolver = OpenClawSelectionResolver(health_store or CredentialHealthStore())
    selection = resolver.resolve(env=env, provider_id=provider_id)
    current_provider = selection.provider_id or requested_provider
    api_family = _openclaw_current_api_family(current_provider, env)
    upstream_base_url = _openclaw_preserved_upstream_base_url(current_provider, env)

    if selection.profile_id is not None and isinstance(selection.credential, dict):
        inspection = _openclaw_profile_inspection(
            current_provider,
            env,
            api_family=api_family,
            profile_id=selection.profile_id,
            credential=selection.credential,
        )
        if inspection is not None:
            return inspection

    inspection = _openclaw_models_cache_inspection(
        requested_provider,
        env,
        api_family=requested_api_family,
    )
    if inspection is not None:
        return inspection

    inspection = _openclaw_provider_env_inspection(
        requested_provider,
        env,
        api_family=requested_api_family,
    )
    if inspection is not None:
        return inspection

    if selection.profile_id is None or not isinstance(selection.credential, dict):
        return _missing(
            requested_provider,
            strategy="missing",
            reason="unable to determine current OpenClaw provider"
            if selection.reason == "missing_provider"
            else (
                "no reusable OpenClaw auth profile, cache API key, or provider env "
                f"found for provider '{requested_provider}'"
            ),
            metadata={
                "providerId": requested_provider,
                "selectionReason": selection.reason,
                "apiFamily": requested_api_family,
                **(
                    {"upstreamBaseUrl": requested_upstream_base_url}
                    if requested_upstream_base_url
                    else {}
                ),
            },
        )

    inspection = _openclaw_profile_inspection(
        current_provider,
        env,
        api_family=api_family,
        profile_id=selection.profile_id,
        credential=selection.credential,
    )
    if inspection is not None:
        return inspection

    return _missing(
        current_provider,
        strategy="missing",
        reason=(
            f"OpenClaw provider '{current_provider}' has no reusable auth profile, cache API key, or provider env"
        ),
        metadata={
            "providerId": current_provider,
            "apiFamily": api_family,
            **({"upstreamBaseUrl": upstream_base_url} if upstream_base_url else {}),
        },
    )


class ProviderAdapter(Protocol):
    provider_ids: tuple[str, ...]

    def inspect(self, context: AuthContext) -> CredentialInspection:
        ...

    def normalize_model_name(self, model_name: Any, context: AuthContext) -> Any:
        ...


class GenericProviderAdapter:
    provider_ids: tuple[str, ...] = ()

    def inspect(self, context: AuthContext) -> CredentialInspection:
        if context.client_name == CLIENT_OPENCLAW:
            api_family = _openclaw_current_api_family(context.provider_id, context.env)
            if api_family not in OPENCLAW_SUPPORTED_API_FAMILIES:
                metadata = {
                    "providerId": normalize_provider_id(context.provider_id),
                    "apiFamily": api_family,
                    "unsupportedFamily": True,
                    "supportedFamilies": sorted(OPENCLAW_SUPPORTED_API_FAMILIES),
                }
                upstream_base_url = _openclaw_preserved_upstream_base_url(
                    context.provider_id,
                    context.env,
                )
                if upstream_base_url:
                    metadata["upstreamBaseUrl"] = upstream_base_url
                return _missing(
                    context.provider_id,
                    strategy="unsupported_family",
                    reason=(
                        f"OpenClaw provider family '{api_family}' is not supported by middleware yet."
                    ),
                    metadata=metadata,
                )
            return _inspect_openclaw_provider(
                context.provider_id,
                context.env,
                context.health_store,
            )
        if context.client_name == CLIENT_OPENCODE:
            return _inspect_opencode_provider(context.provider_id, context.env)
        return _missing(
            context.provider_id,
            strategy="missing",
            reason=(
                f"no native auth adapter is defined for client '{context.client_name or CLIENT_UNKNOWN}' and provider '{context.provider_id}'"
            ),
        )

    def normalize_model_name(self, model_name: Any, context: AuthContext) -> Any:
        if not isinstance(model_name, str) or "/" not in model_name:
            return model_name
        prefix, suffix = model_name.split("/", 1)
        normalized_prefix = normalize_provider_id(prefix)
        removable_prefixes = {
            context.provider_id,
            PROVIDER_MODEIO_MIDDLEWARE,
        }
        if context.provider_id in {PROVIDER_OPENAI, PROVIDER_OPENAI_CODEX}:
            removable_prefixes.update({PROVIDER_OPENAI, PROVIDER_OPENAI_CODEX})
        if normalized_prefix in removable_prefixes:
            return suffix
        return model_name


class OpenAIProviderAdapter(GenericProviderAdapter):
    provider_ids = (PROVIDER_OPENAI,)

    def inspect(self, context: AuthContext) -> CredentialInspection:
        if context.client_name == CLIENT_CODEX:
            codex = _inspect_codex_store(context.env)
            if codex.ready and codex.auth_kind == AUTH_KIND_API_KEY:
                return _ready(
                    PROVIDER_OPENAI,
                    auth_kind=AUTH_KIND_API_KEY,
                    guaranteed=True,
                    strategy=codex.strategy,
                    auth_source=codex.auth_source,
                    path=codex.path,
                    authorization=codex.authorization or "",
                    transport=TRANSPORT_OPENAI_COMPAT,
                    metadata={
                        "providerId": PROVIDER_OPENAI,
                        "upstreamBaseUrl": OPENAI_COMPAT_BASE_URL,
                    },
                )
        if context.client_name == CLIENT_OPENCODE:
            return _inspect_opencode_provider(PROVIDER_OPENAI, context.env)
        return super().inspect(context)


class CodexNativeAdapter(GenericProviderAdapter):
    provider_ids = (PROVIDER_OPENAI_CODEX,)

    def inspect(self, context: AuthContext) -> CredentialInspection:
        if context.client_name == CLIENT_CODEX:
            return _inspect_codex_store(context.env)
        return super().inspect(context)

    def normalize_model_name(self, model_name: Any, context: AuthContext) -> Any:
        normalized = super().normalize_model_name(model_name, context)
        if not isinstance(normalized, str):
            return normalized
        if normalized.startswith("codex/"):
            return normalized.split("/", 1)[1]
        return normalized


DEFAULT_PROVIDER_ADAPTERS: tuple[ProviderAdapter, ...] = (
    CodexNativeAdapter(),
    OpenAIProviderAdapter(),
)


class ProviderAdapterRegistry:
    def __init__(self, adapters: tuple[ProviderAdapter, ...] = DEFAULT_PROVIDER_ADAPTERS):
        self._adapters = list(adapters)
        self._default_adapter = GenericProviderAdapter()

    def adapter_for(self, provider_id: str) -> ProviderAdapter:
        normalized = normalize_provider_id(provider_id)
        for adapter in self._adapters:
            if normalized in adapter.provider_ids:
                return adapter
        return self._default_adapter

    def normalize_model_name(self, model_name: Any, context: AuthContext) -> Any:
        return self.adapter_for(context.provider_id).normalize_model_name(model_name, context)


class CredentialResolver:
    def __init__(
        self,
        *,
        registry: ProviderAdapterRegistry | None = None,
        health_store: CredentialHealthStore | None = None,
    ):
        self._registry = registry or ProviderAdapterRegistry()
        self._health_store = health_store or CredentialHealthStore()

    def resolve_provider_id(
        self,
        *,
        client_name: str,
        provider_name: str | None = None,
        env: Mapping[str, str] | None = None,
    ) -> str:
        resolved_env = _env_mapping(env)
        if provider_name:
            return normalize_provider_id(provider_name)
        if client_name == CLIENT_CODEX:
            return PROVIDER_OPENAI_CODEX
        if client_name == CLIENT_OPENCODE:
            payload = _read_json_object(_opencode_config_path(resolved_env))
            provider_id = _opencode_current_provider(payload, resolved_env)
            return normalize_provider_id(provider_id) or ""
        if client_name == CLIENT_OPENCLAW:
            provider_id = _openclaw_current_provider(resolved_env)
            return normalize_provider_id(provider_id) or ""
        return ""

    def inspect(
        self,
        *,
        client_name: str,
        provider_name: str | None = None,
        env: Mapping[str, str] | None = None,
    ) -> CredentialInspection:
        resolved_env = _env_mapping(env)
        provider_id = self.resolve_provider_id(
            client_name=client_name,
            provider_name=provider_name,
            env=resolved_env,
        )
        context = AuthContext(
            client_name=client_name,
            provider_id=provider_id,
            env=resolved_env,
            health_store=self._health_store,
        )
        inspection = self._registry.adapter_for(provider_id).inspect(context)
        self._health_store.snapshot(
            inspection,
            profile_id=(
                str(inspection.metadata.get("selectedProfileId"))
                if isinstance(inspection.metadata.get("selectedProfileId"), str)
                else None
            ),
        )
        return inspection

    def normalize_model_name(
        self,
        model_name: Any,
        *,
        client_name: str,
        provider_name: str | None = None,
        env: Mapping[str, str] | None = None,
    ) -> Any:
        resolved_env = _env_mapping(env)
        provider_id = self.resolve_provider_id(
            client_name=client_name,
            provider_name=provider_name,
            env=resolved_env,
        )
        context = AuthContext(
            client_name=client_name,
            provider_id=provider_id,
            env=resolved_env,
            health_store=self._health_store,
        )
        return self._registry.normalize_model_name(model_name, context)

    def resolve_upstream_plan(
        self,
        *,
        client_name: str,
        provider_name: str | None = None,
        env: Mapping[str, str] | None = None,
    ) -> ResolvedUpstreamPlan:
        resolved_env = _env_mapping(env)
        provider_id = self.resolve_provider_id(
            client_name=client_name,
            provider_name=provider_name,
            env=resolved_env,
        )
        return _context_upstream_plan(
            client_name=client_name,
            provider_id=provider_id,
            env=resolved_env,
        )

    def resolve_authorization(
        self,
        incoming_headers: Mapping[str, str],
        *,
        client_name: str,
        provider_name: str | None = None,
        env: Mapping[str, str] | None = None,
    ) -> str | None:
        incoming_auth = _header(incoming_headers, "authorization")
        if incoming_auth and not _looks_like_placeholder(incoming_auth):
            return incoming_auth

        inspection = self.inspect(
            client_name=client_name,
            provider_name=provider_name,
            env=env,
        )
        if inspection.ready and inspection.authorization:
            return inspection.authorization
        if incoming_auth and _looks_like_placeholder(incoming_auth):
            return None
        return incoming_auth or None

    def record_failure(self, inspection: CredentialInspection, *, status_code: int) -> None:
        del inspection
        del status_code
