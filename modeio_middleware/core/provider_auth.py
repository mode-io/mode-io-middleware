#!/usr/bin/env python3

from __future__ import annotations

import base64
import json
import os
import time
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Protocol

from modeio_middleware.connectors.client_identity import (
    CLIENT_CODEX,
    CLIENT_OPENCODE,
    CLIENT_OPENCLAW,
    CLIENT_UNKNOWN,
)

AUTH_KIND_API_KEY = "api_key"
AUTH_KIND_MISSING = "missing"
AUTH_KIND_OAUTH = "oauth"
AUTH_KIND_TOKEN = "token"

FALLBACK_MODE_MANAGED_UPSTREAM = "managed_upstream"
FALLBACK_MODE_NONE = "none"

TRANSPORT_CODEX_NATIVE = "codex_native"
TRANSPORT_OPENAI_COMPAT = "openai_compat"

PROVIDER_ANTHROPIC = "anthropic"
PROVIDER_GITHUB_COPILOT = "github-copilot"
PROVIDER_GOOGLE_GEMINI_CLI = "google-gemini-cli"
PROVIDER_MODEIO_MIDDLEWARE = "modeio-middleware"
PROVIDER_OPENAI = "openai"
PROVIDER_OPENAI_CODEX = "openai-codex"

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
        return PROVIDER_OPENAI
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
    fallback_mode: str = FALLBACK_MODE_NONE
    reason: str | None = None
    auth_source: str | None = None
    path: str | None = None
    auth_env: str | None = None
    authorization: str | None = None
    resolved_headers: dict[str, str] = field(default_factory=dict)
    audience: Any = None
    scopes: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_public_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "providerId": self.provider_id,
            "ready": self.ready,
            "guaranteed": self.guaranteed,
            "strategy": self.strategy,
            "transport": self.transport,
        }
        if self.fallback_mode != FALLBACK_MODE_NONE:
            payload["fallbackMode"] = self.fallback_mode
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
    fallback_mode: str = FALLBACK_MODE_NONE,
) -> CredentialInspection:
    return CredentialInspection(
        provider_id=provider_id,
        auth_kind=AUTH_KIND_MISSING,
        ready=False,
        guaranteed=False,
        strategy=strategy,
        transport=transport,
        fallback_mode=fallback_mode,
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
    fallback_mode: str = FALLBACK_MODE_NONE,
) -> CredentialInspection:
    return CredentialInspection(
        provider_id=provider_id,
        auth_kind=auth_kind,
        ready=True,
        guaranteed=guaranteed,
        strategy=strategy,
        transport=transport,
        fallback_mode=fallback_mode,
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
        return _missing(
            provider_id,
            strategy="missing",
            reason="codex auth store not found",
            path=str(auth_path),
            transport=TRANSPORT_CODEX_NATIVE,
            fallback_mode=FALLBACK_MODE_MANAGED_UPSTREAM,
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
            }
            if isinstance(account_id, str) and account_id.strip():
                metadata["nativeBaseUrl"] = _codex_native_base_url(env)
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
                fallback_mode=FALLBACK_MODE_MANAGED_UPSTREAM,
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
            metadata={"providerId": PROVIDER_OPENAI},
        )

    return _missing(
        provider_id,
        strategy="missing",
        reason="codex auth store has no reusable API key or access token",
        path=str(auth_path),
        transport=TRANSPORT_CODEX_NATIVE,
        fallback_mode=FALLBACK_MODE_MANAGED_UPSTREAM,
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
            fallback_mode=FALLBACK_MODE_MANAGED_UPSTREAM,
        )

    provider_obj = None
    if isinstance(payload, dict):
        providers = payload.get("provider")
        provider_obj = (
            providers.get(selected_provider) if isinstance(providers, dict) else None
        )
    if not isinstance(provider_obj, dict):
        provider_obj = {}

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
                metadata={"providerId": selected_provider, "configPath": str(_opencode_config_path(env))},
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
                metadata={"providerId": selected_provider, "configPath": str(_opencode_config_path(env))},
            )

    return _missing(
        selected_provider,
        strategy="missing",
        reason=(
            f"OpenCode provider '{selected_provider}' has no reusable auth in config or the provider env vars are unset"
        ),
        fallback_mode=FALLBACK_MODE_MANAGED_UPSTREAM,
        metadata={
            "providerId": selected_provider,
            "configPath": str(_opencode_config_path(env)),
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
        self._health_store = health_store

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
            return self._fallback_provider_selection(env, selected_provider, "no_profiles")

        default_profile = next(
            (
                (profile_id, credential)
                for profile_id, credential in matching
                if profile_id.endswith(":default")
            ),
            None,
        )
        now_ms = int(time.time() * 1000)
        last_good: tuple[str, dict[str, Any]] | None = None
        last_good_ts = -1
        for profile_id, credential in matching:
            health = self._health_store.get(selected_provider, profile_id)
            if health and health.cooldown_until_ms and health.cooldown_until_ms > now_ms:
                continue
            if health and health.last_good_at_ms and health.last_good_at_ms > last_good_ts:
                last_good = (profile_id, credential)
                last_good_ts = health.last_good_at_ms

        available = [
            (profile_id, credential)
            for profile_id, credential in matching
            if not (
                (health := self._health_store.get(selected_provider, profile_id))
                and health.cooldown_until_ms
                and health.cooldown_until_ms > now_ms
            )
        ]
        default_available = next(
            (
                (profile_id, credential)
                for profile_id, credential in available
                if profile_id.endswith(":default")
            ),
            None,
        )

        chosen = last_good or default_available or (available[0] if available else default_profile or matching[0])
        if not available and chosen == default_profile:
            return self._fallback_provider_selection(env, selected_provider, "primary_in_cooldown")
        reason = (
            "last_good"
            if last_good
            else "default"
            if default_available or (not available and default_profile)
            else "first_available"
        )
        return OpenClawSelection(
            provider_id=selected_provider,
            profile_id=chosen[0],
            reason=reason,
            credential=chosen[1],
        )

    def _fallback_provider_selection(
        self,
        env: Mapping[str, str],
        current_provider: str,
        reason: str,
    ) -> OpenClawSelection:
        providers = _openclaw_models_cache_providers(env)
        for provider_id, provider in providers.items():
            normalized = normalize_provider_id(provider_id)
            if normalized in {current_provider, PROVIDER_MODEIO_MIDDLEWARE}:
                continue
            if not isinstance(provider, dict):
                continue
            api_key = provider.get("apiKey")
            base_url = provider.get("baseUrl")
            models = provider.get("models")
            if not isinstance(api_key, str) or not api_key.strip():
                continue
            if not isinstance(base_url, str) or not base_url.strip():
                continue
            if not isinstance(models, list) or not models:
                continue
            return OpenClawSelection(
                provider_id=normalized,
                profile_id=None,
                reason=f"fallback_provider:{reason}",
                credential={
                    "provider": normalized,
                    "apiKey": api_key.strip(),
                    "baseUrl": base_url.strip(),
                    "models": models,
                },
            )
        return OpenClawSelection(
            provider_id=current_provider,
            profile_id=None,
            reason=reason,
            credential=None,
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


def _openclaw_env_fallback_inspection(
    provider_id: str,
    env: Mapping[str, str],
    *,
    api_family: str,
) -> CredentialInspection | None:
    env_candidates = (
        ("ANTHROPIC_API_KEY",)
        if api_family == "anthropic-messages"
        else ("OPENAI_API_KEY",)
    )
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
            fallback_mode=FALLBACK_MODE_MANAGED_UPSTREAM,
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

    if (
        current_provider == requested_provider
        and selection.profile_id is not None
        and isinstance(selection.credential, dict)
    ):
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

    inspection = _openclaw_env_fallback_inspection(
        requested_provider,
        env,
        api_family=requested_api_family,
    )
    if inspection is not None:
        return inspection

    if selection.reason.startswith("fallback_provider:") and isinstance(selection.credential, dict):
        models = selection.credential.get("models")
        fallback_model_id = None
        if isinstance(models, list):
            for item in models:
                if isinstance(item, dict) and isinstance(item.get("id"), str):
                    fallback_model_id = item["id"]
                    break
        api_key = str(selection.credential.get("apiKey") or "").strip()
        authorization = _bearer(api_key) or ""
        resolved_headers: dict[str, str] | None = None
        if api_family == "anthropic-messages" and not _anthropic_uses_bearer_auth(
            api_key,
            auth_kind=AUTH_KIND_API_KEY,
        ):
            resolved_headers = {"x-api-key": api_key} if api_key else None
            authorization = ""
        metadata = {
            "providerId": current_provider,
            "selectionReason": selection.reason,
            "overrideBaseUrl": selection.credential.get("baseUrl"),
            "fallbackModelId": fallback_model_id,
            "apiFamily": api_family,
        }
        if upstream_base_url:
            metadata["upstreamBaseUrl"] = upstream_base_url
        return _ready(
            current_provider,
            auth_kind=AUTH_KIND_API_KEY,
            guaranteed=False,
            strategy="provider-fallback",
            auth_source=f"models-cache:{current_provider}",
            path=str(_openclaw_models_cache_path(env)),
            authorization=authorization,
            resolved_headers=resolved_headers,
            reason=(
                f"Primary OpenClaw provider is cooling down; reusing configured provider '{current_provider}' as a best-effort fallback."
            ),
            metadata=metadata,
        )
    if selection.profile_id is None or not isinstance(selection.credential, dict):
        return _missing(
            requested_provider,
            strategy="missing",
            reason="unable to determine current OpenClaw provider"
            if selection.reason == "missing_provider"
            else (
                "no reusable OpenClaw auth profile, cache API key, or supported env fallback "
                f"found for provider '{requested_provider}'"
            ),
            fallback_mode=FALLBACK_MODE_MANAGED_UPSTREAM,
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
            f"OpenClaw provider '{current_provider}' has no reusable auth profile, cache API key, or supported env fallback"
        ),
        fallback_mode=FALLBACK_MODE_MANAGED_UPSTREAM,
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
                    fallback_mode=FALLBACK_MODE_MANAGED_UPSTREAM,
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
            fallback_mode=FALLBACK_MODE_MANAGED_UPSTREAM,
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
                )
        if context.client_name == CLIENT_OPENCODE:
            direct = _inspect_opencode_provider(PROVIDER_OPENAI, context.env)
            if direct.ready:
                return direct

            codex = _inspect_codex_store(context.env)
            if codex.ready:
                return CredentialInspection(
                    provider_id=PROVIDER_OPENAI,
                    auth_kind=codex.auth_kind,
                    ready=True,
                    guaranteed=False,
                    strategy="shared-codex-oauth",
                    transport=TRANSPORT_CODEX_NATIVE,
                    fallback_mode=FALLBACK_MODE_MANAGED_UPSTREAM,
                    reason=(
                        "OpenCode has no reusable OpenAI API key for the current provider; reusing Codex OAuth as a best-effort native fallback."
                    ),
                    auth_source=codex.auth_source,
                    path=codex.path,
                    auth_env=codex.auth_env,
                    authorization=codex.authorization,
                    audience=codex.audience,
                    scopes=codex.scopes,
                    metadata={
                        **codex.metadata,
                        "providerId": PROVIDER_OPENAI,
                        "sharedFrom": CLIENT_CODEX,
                        "nativeBaseUrl": _codex_native_base_url(context.env),
                    },
                )

            shared = _inspect_openclaw_provider(
                PROVIDER_OPENAI_CODEX,
                context.env,
                context.health_store,
            )
            if shared.ready:
                return CredentialInspection(
                    provider_id=PROVIDER_OPENAI,
                    auth_kind=shared.auth_kind,
                    ready=True,
                    guaranteed=False,
                    strategy="shared-openclaw-profile",
                    transport=TRANSPORT_CODEX_NATIVE,
                    fallback_mode=FALLBACK_MODE_MANAGED_UPSTREAM,
                    reason=(
                        "OpenCode has no reusable OpenAI API key for the current provider; reusing the OpenClaw `openai-codex` profile as a best-effort native fallback."
                    ),
                    auth_source=shared.auth_source,
                    path=shared.path,
                    auth_env=shared.auth_env,
                    authorization=shared.authorization,
                    audience=shared.audience,
                    scopes=shared.scopes,
                    metadata={
                        **shared.metadata,
                        "providerId": PROVIDER_OPENAI,
                        "sharedFrom": CLIENT_OPENCLAW,
                        "nativeBaseUrl": _codex_native_base_url(context.env),
                    },
                )

            return direct
        return super().inspect(context)


class CodexNativeAdapter(GenericProviderAdapter):
    provider_ids = (PROVIDER_OPENAI_CODEX,)

    def inspect(self, context: AuthContext) -> CredentialInspection:
        if context.client_name == CLIENT_CODEX:
            codex = _inspect_codex_store(context.env)
            if codex.ready:
                return codex
            shared = _inspect_openclaw_provider(
                PROVIDER_OPENAI_CODEX,
                context.env,
                context.health_store,
            )
            if shared.ready:
                metadata = {
                    **shared.metadata,
                    "sharedFrom": CLIENT_OPENCLAW,
                }
                account_id = metadata.get("accountId") if isinstance(metadata, dict) else None
                if isinstance(account_id, str) and account_id.strip():
                    metadata["nativeBaseUrl"] = _codex_native_base_url(context.env)
                return CredentialInspection(
                    provider_id=PROVIDER_OPENAI_CODEX,
                    auth_kind=shared.auth_kind,
                    ready=True,
                    guaranteed=False,
                    strategy="shared-openclaw-profile",
                    transport=TRANSPORT_CODEX_NATIVE,
                    fallback_mode=FALLBACK_MODE_MANAGED_UPSTREAM,
                    reason=(
                        "Codex auth store is unavailable or stale; reusing the OpenClaw `openai-codex` profile as a best-effort native fallback."
                    ),
                    auth_source=shared.auth_source,
                    path=shared.path,
                    auth_env=shared.auth_env,
                    authorization=shared.authorization,
                    audience=shared.audience,
                    scopes=shared.scopes,
                    metadata=metadata,
                )
            return codex
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
            return normalize_provider_id(provider_id)
        if client_name == CLIENT_OPENCLAW:
            provider_id = _openclaw_current_provider(resolved_env)
            return normalize_provider_id(provider_id)
        return PROVIDER_OPENAI

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
        profile_id = (
            str(inspection.metadata.get("selectedProfileId"))
            if isinstance(inspection.metadata.get("selectedProfileId"), str)
            else None
        )
        if not profile_id:
            return
        if status_code == 429:
            self._health_store.mark_cooldown(
                provider_id=inspection.provider_id,
                profile_id=profile_id,
                reason="rate_limited",
                cooldown_seconds=300,
            )
        elif status_code in {401, 403}:
            self._health_store.mark_cooldown(
                provider_id=inspection.provider_id,
                profile_id=profile_id,
                reason="auth_rejected",
                cooldown_seconds=120,
            )
