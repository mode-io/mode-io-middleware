#!/usr/bin/env python3

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Protocol, TYPE_CHECKING

from modeio_middleware.core.contracts import (
    ENDPOINT_ANTHROPIC_MESSAGES,
    ENDPOINT_CHAT_COMPLETIONS,
    ENDPOINT_RESPONSES,
)
from modeio_middleware.core.errors import MiddlewareError
from modeio_middleware.core.provider_auth import TRANSPORT_CODEX_NATIVE
from modeio_middleware.core.upstream_plan import ResolvedUpstreamPlan

if TYPE_CHECKING:
    from modeio_middleware.core.engine import GatewayRuntimeConfig


def _normalize_codex_native_model(model_name: Any) -> Any:
    if not isinstance(model_name, str):
        return model_name
    stripped = model_name.strip()
    if stripped == "gpt-5-nano":
        return "gpt-5.4"
    return stripped


def _normalize_codex_reasoning(reasoning: Any) -> Any:
    if not isinstance(reasoning, dict):
        return reasoning
    normalized = dict(reasoning)
    effort = normalized.get("effort")
    if effort == "minimal":
        normalized["effort"] = "none"
    return normalized


def _to_codex_input_item(role: str, content: Any) -> Dict[str, Any]:
    normalized_role = role if role in {"user", "assistant", "developer"} else "user"
    if isinstance(content, list):
        normalized = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
                normalized.append({"type": "input_text", "text": item["text"]})
            elif isinstance(item, dict) and item.get("type") == "input_text" and isinstance(item.get("text"), str):
                normalized.append({"type": "input_text", "text": item["text"]})
        if normalized:
            return {"type": "message", "role": normalized_role, "content": normalized}
    if isinstance(content, str):
        return {"type": "message", "role": normalized_role, "content": [{"type": "input_text", "text": content}]}
    return {"type": "message", "role": normalized_role, "content": []}


def _codex_native_payload(endpoint_kind: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if endpoint_kind == ENDPOINT_CHAT_COMPLETIONS:
        messages = payload.get("messages") if isinstance(payload.get("messages"), list) else []
        system_messages = [
            item.get("content")
            for item in messages
            if isinstance(item, dict) and item.get("role") == "system" and isinstance(item.get("content"), str)
        ]
        input_items = [
            _to_codex_input_item(str(item.get("role") or "user"), item.get("content"))
            for item in messages
            if isinstance(item, dict) and item.get("role") != "system"
        ]
        return {
            "model": _normalize_codex_native_model(payload.get("model")),
            "instructions": "\n\n".join(system_messages) if system_messages else "You are Codex",
            "input": input_items,
            "stream": True,
            "store": False,
        }

    transformed = dict(payload)
    transformed["model"] = _normalize_codex_native_model(transformed.get("model"))
    transformed["store"] = False
    transformed["stream"] = True
    transformed.pop("max_output_tokens", None)
    transformed["reasoning"] = _normalize_codex_reasoning(transformed.get("reasoning"))

    instructions = transformed.get("instructions")
    input_value = transformed.get("input")
    if isinstance(input_value, list):
        instructions_parts = []
        normalized_items = []
        for item in input_value:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "user")
            content = item.get("content")
            if role in {"system", "developer"}:
                if isinstance(content, str) and content.strip():
                    instructions_parts.append(content.strip())
                    continue
            normalized_items.append(_to_codex_input_item(role, content))
        transformed["input"] = normalized_items
        if not isinstance(instructions, str) or not instructions.strip():
            transformed["instructions"] = (
                "\n\n".join(instructions_parts) if instructions_parts else "You are Codex"
            )
    elif isinstance(input_value, str):
        transformed["input"] = [
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": input_value}],
            }
        ]
        if not isinstance(instructions, str) or not instructions.strip():
            transformed["instructions"] = "You are Codex"
    elif not isinstance(instructions, str) or not instructions.strip():
        transformed["instructions"] = "You are Codex"
    return transformed


def _apply_model_override(payload: Dict[str, Any], plan: ResolvedUpstreamPlan) -> Dict[str, Any]:
    if not isinstance(plan.model_override, str) or not plan.model_override.strip():
        return payload
    updated = dict(payload)
    updated["model"] = plan.model_override
    return updated


def _derive_endpoint_url(base_url: str, *, endpoint_kind: str) -> str:
    normalized_base = str(base_url).rstrip("/")
    for suffix in ("/chat/completions", "/responses", "/models", "/v1/messages"):
        if normalized_base.endswith(suffix):
            normalized_base = normalized_base[: -len(suffix)]
            break
    if endpoint_kind == ENDPOINT_CHAT_COMPLETIONS:
        return f"{normalized_base}/chat/completions"
    if endpoint_kind == ENDPOINT_RESPONSES:
        return f"{normalized_base}/responses"
    if endpoint_kind == ENDPOINT_ANTHROPIC_MESSAGES:
        if normalized_base.endswith("/v1"):
            return f"{normalized_base}/messages"
        return f"{normalized_base}/v1/messages"
    raise MiddlewareError(
        500,
        "MODEIO_INTERNAL_ERROR",
        f"unsupported endpoint kind '{endpoint_kind}'",
        retryable=False,
    )


def _derive_models_url(base_url: str, *, api_family: str | None = None) -> str:
    normalized_base = str(base_url).rstrip("/")
    for suffix in ("/chat/completions", "/responses", "/models", "/v1/messages"):
        if normalized_base.endswith(suffix):
            normalized_base = normalized_base[: -len(suffix)]
            break
    if api_family == "anthropic-messages" and not normalized_base.endswith("/v1"):
        return f"{normalized_base}/v1/models"
    return f"{normalized_base}/models"


class UpstreamStrategy(Protocol):
    def endpoint_url(
        self,
        *,
        config: "GatewayRuntimeConfig",
        endpoint_kind: str,
        plan: ResolvedUpstreamPlan,
    ) -> str: ...

    def models_url(
        self,
        *,
        config: "GatewayRuntimeConfig",
        plan: ResolvedUpstreamPlan,
    ) -> str: ...

    def request_payload(
        self,
        *,
        endpoint_kind: str,
        payload: Dict[str, Any],
        plan: ResolvedUpstreamPlan,
    ) -> Dict[str, Any]: ...

    def postprocess_models_payload(
        self,
        response_payload: Dict[str, Any],
        *,
        plan: ResolvedUpstreamPlan,
    ) -> Dict[str, Any]: ...


@dataclass(frozen=True)
class OpenAICompatStrategy:
    def endpoint_url(
        self,
        *,
        config: "GatewayRuntimeConfig",
        endpoint_kind: str,
        plan: ResolvedUpstreamPlan,
    ) -> str:
        if isinstance(plan.base_url, str) and plan.base_url.strip():
            return _derive_endpoint_url(plan.base_url, endpoint_kind=endpoint_kind)
        if endpoint_kind == ENDPOINT_CHAT_COMPLETIONS:
            return config.upstream_chat_completions_url
        if endpoint_kind == ENDPOINT_RESPONSES:
            return config.upstream_responses_url
        if endpoint_kind == ENDPOINT_ANTHROPIC_MESSAGES:
            return _derive_endpoint_url(
                config.upstream_responses_url,
                endpoint_kind=endpoint_kind,
            )
        raise MiddlewareError(
            500,
            "MODEIO_INTERNAL_ERROR",
            f"unsupported endpoint kind '{endpoint_kind}'",
            retryable=False,
        )

    def models_url(
        self,
        *,
        config: "GatewayRuntimeConfig",
        plan: ResolvedUpstreamPlan,
    ) -> str:
        if isinstance(plan.base_url, str) and plan.base_url.strip():
            return _derive_models_url(plan.base_url, api_family=plan.api_family)
        for candidate in (
            config.upstream_chat_completions_url,
            config.upstream_responses_url,
        ):
            text = str(candidate).rstrip("/")
            for suffix in ("/chat/completions", "/responses"):
                if text.endswith(suffix):
                    return text[: -len(suffix)] + "/models"
        raise MiddlewareError(
            500,
            "MODEIO_INTERNAL_ERROR",
            "unable to derive upstream models URL",
            retryable=False,
        )

    def request_payload(
        self,
        *,
        endpoint_kind: str,
        payload: Dict[str, Any],
        plan: ResolvedUpstreamPlan,
    ) -> Dict[str, Any]:
        del endpoint_kind
        return _apply_model_override(payload, plan)

    def postprocess_models_payload(
        self,
        response_payload: Dict[str, Any],
        *,
        plan: ResolvedUpstreamPlan,
    ) -> Dict[str, Any]:
        del plan
        return response_payload


@dataclass(frozen=True)
class AnthropicMessagesStrategy(OpenAICompatStrategy):
    pass


@dataclass(frozen=True)
class CodexNativeStrategy(OpenAICompatStrategy):
    def request_payload(
        self,
        *,
        endpoint_kind: str,
        payload: Dict[str, Any],
        plan: ResolvedUpstreamPlan,
    ) -> Dict[str, Any]:
        transformed = payload
        if endpoint_kind in {ENDPOINT_RESPONSES, ENDPOINT_CHAT_COMPLETIONS}:
            transformed = _codex_native_payload(endpoint_kind, payload)
        return _apply_model_override(transformed, plan)

    def postprocess_models_payload(
        self,
        response_payload: Dict[str, Any],
        *,
        plan: ResolvedUpstreamPlan,
    ) -> Dict[str, Any]:
        if plan.transport_kind != TRANSPORT_CODEX_NATIVE:
            return response_payload
        models = response_payload.get("models")
        if not isinstance(models, list):
            return response_payload
        updated = dict(response_payload)
        rewritten = []
        changed = False
        for item in models:
            if not isinstance(item, dict):
                rewritten.append(item)
                continue
            current = dict(item)
            if current.get("supports_websockets") is not False:
                current["supports_websockets"] = False
                changed = True
            if current.get("prefer_websockets") is not False:
                current["prefer_websockets"] = False
                changed = True
            rewritten.append(current)
        if not changed:
            return response_payload
        updated["models"] = rewritten
        return updated


OPENAI_COMPAT_STRATEGY = OpenAICompatStrategy()
ANTHROPIC_MESSAGES_STRATEGY = AnthropicMessagesStrategy()
CODEX_NATIVE_STRATEGY = CodexNativeStrategy()


def strategy_for_plan(plan: ResolvedUpstreamPlan) -> UpstreamStrategy:
    if plan.transport_kind == TRANSPORT_CODEX_NATIVE and isinstance(plan.base_url, str) and plan.base_url.strip():
        return CODEX_NATIVE_STRATEGY
    if plan.api_family == "anthropic-messages":
        return ANTHROPIC_MESSAGES_STRATEGY
    return OPENAI_COMPAT_STRATEGY
