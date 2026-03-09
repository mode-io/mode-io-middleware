#!/usr/bin/env python3

from __future__ import annotations

from modeio_middleware.core.observability.models import (
    ChangeSummary,
    HookExecutionRecord,
    ImpactSummary,
    TraceLifecycle,
)

PRE_REQUEST_HOOKS = frozenset({"pre_request"})
POST_RESPONSE_HOOKS = frozenset({"post_response"})
STREAM_HOOKS = frozenset({"post_stream_start", "post_stream_event", "post_stream_end"})


def summarize_lifecycle(
    *,
    request_change: ChangeSummary,
    response_change: ChangeSummary,
    hook_executions: tuple[HookExecutionRecord, ...],
) -> TraceLifecycle:
    touches_pre_request = request_change.changed
    touches_post_response = response_change.changed
    touches_stream = False

    for hook in hook_executions:
        hook_name = str(hook.hook_name).strip().lower()
        if hook_name in PRE_REQUEST_HOOKS:
            touches_pre_request = True
        elif hook_name in POST_RESPONSE_HOOKS:
            touches_post_response = True
        elif hook_name in STREAM_HOOKS:
            touches_stream = True

    if touches_stream and touches_pre_request:
        return "pre_and_stream"
    if touches_pre_request and touches_post_response:
        return "pre_and_post"
    if touches_stream:
        return "stream"
    if touches_post_response:
        return "post_response"
    if touches_pre_request:
        return "pre_request"
    return "none"


def summarize_impact(
    *,
    blocked: bool,
    request_change: ChangeSummary,
    response_change: ChangeSummary,
    hook_executions: tuple[HookExecutionRecord, ...],
) -> ImpactSummary:
    plugin_names: list[str] = []
    seen_plugins: set[str] = set()
    seen_actions: set[str] = set()
    impactful_actions: list[str] = []

    for hook in hook_executions:
        if hook.plugin_name and hook.plugin_name not in seen_plugins:
            plugin_names.append(hook.plugin_name)
            seen_plugins.add(hook.plugin_name)
        action = str(hook.effective_action).strip().lower()
        if action in {"", "allow"} or action in seen_actions:
            continue
        impactful_actions.append(action)
        seen_actions.add(action)

    has_modify = (
        request_change.changed or response_change.changed or "modify" in seen_actions
    )
    has_block = blocked or "block" in seen_actions
    has_warn = bool(seen_actions.intersection({"warn", "error"}))

    category_count = sum((has_block, has_modify, has_warn))
    if category_count > 1:
        category = "mixed"
    elif has_block:
        category = "blocked"
    elif has_modify:
        category = "modified"
    elif has_warn:
        category = "warned"
    else:
        category = "pass_through"

    primary_plugin = None
    for preferred_action in ("block", "modify", "warn", "error"):
        for hook in hook_executions:
            if hook.effective_action == preferred_action:
                primary_plugin = hook.plugin_name
                break
        if primary_plugin is not None:
            break

    if primary_plugin is None and category == "pass_through":
        plugin_names = []

    return ImpactSummary(
        category=category,
        actions=tuple(impactful_actions),
        primary_plugin=primary_plugin,
        plugin_names=tuple(plugin_names),
    )
