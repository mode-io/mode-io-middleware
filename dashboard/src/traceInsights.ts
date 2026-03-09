import type { ChangeSummary, HookExecution, TraceImpact, TraceLifecycle } from "./types";

const PRE_REQUEST_HOOKS = new Set(["pre_request"]);
const POST_RESPONSE_HOOKS = new Set(["post_response"]);
const STREAM_HOOKS = new Set(["post_stream_start", "post_stream_event", "post_stream_end"]);

interface TraceInsightInput {
  blocked: boolean;
  requestChange: ChangeSummary;
  responseChange: ChangeSummary;
  hookExecutions: HookExecution[];
}

export interface TraceImpactMetadata {
  impact: TraceImpact;
  impactActions: string[];
  primaryPlugin: string | null;
  pluginNames: string[];
}

export function deriveTraceLifecycle({
  requestChange,
  responseChange,
  hookExecutions,
}: {
  requestChange: ChangeSummary;
  responseChange: ChangeSummary;
  hookExecutions: HookExecution[];
}): TraceLifecycle {
  let touchesPreRequest = requestChange.changed;
  let touchesPostResponse = responseChange.changed;
  let touchesStream = false;

  for (const hook of hookExecutions) {
    const hookName = hook.hookName?.trim().toLowerCase();
    if (!hookName) {
      continue;
    }
    if (PRE_REQUEST_HOOKS.has(hookName)) {
      touchesPreRequest = true;
    } else if (POST_RESPONSE_HOOKS.has(hookName)) {
      touchesPostResponse = true;
    } else if (STREAM_HOOKS.has(hookName)) {
      touchesStream = true;
    }
  }

  if (touchesStream && touchesPreRequest) {
    return "pre_and_stream";
  }
  if (touchesPreRequest && touchesPostResponse) {
    return "pre_and_post";
  }
  if (touchesStream) {
    return "stream";
  }
  if (touchesPostResponse) {
    return "post_response";
  }
  if (touchesPreRequest) {
    return "pre_request";
  }
  return "none";
}

export function deriveTraceImpactMetadata({ blocked, requestChange, responseChange, hookExecutions }: TraceInsightInput): TraceImpactMetadata {
  const pluginNames: string[] = [];
  const seenPlugins = new Set<string>();
  const impactActions: string[] = [];
  const seenActions = new Set<string>();

  for (const hook of hookExecutions) {
    if (hook.pluginName && !seenPlugins.has(hook.pluginName)) {
      pluginNames.push(hook.pluginName);
      seenPlugins.add(hook.pluginName);
    }
    const action = hook.effectiveAction?.trim().toLowerCase();
    if (!action || action === "allow" || seenActions.has(action)) {
      continue;
    }
    impactActions.push(action);
    seenActions.add(action);
  }

  const hasModify = requestChange.changed || responseChange.changed || seenActions.has("modify");
  const hasBlock = blocked || seenActions.has("block");
  const hasWarn = seenActions.has("warn") || seenActions.has("error");
  const dimensionCount = Number(hasModify) + Number(hasBlock) + Number(hasWarn);

  let impact: TraceImpact = "pass_through";
  if (dimensionCount > 1) {
    impact = "mixed";
  } else if (hasBlock) {
    impact = "blocked";
  } else if (hasModify) {
    impact = "modified";
  } else if (hasWarn) {
    impact = "warned";
  }

  let primaryPlugin: string | null = null;
  for (const preferredAction of ["block", "modify", "warn", "error"]) {
    const match = hookExecutions.find((hook) => hook.effectiveAction === preferredAction);
    if (match) {
      primaryPlugin = match.pluginName;
      break;
    }
  }

  return {
    impact,
    impactActions,
    primaryPlugin,
    pluginNames: impact === "pass_through" ? [] : pluginNames,
  };
}

export function summarizePluginLabel(primaryPlugin: string | null, pluginNames: string[]): string {
  if (!primaryPlugin && pluginNames.length === 0) {
    return "-";
  }
  const anchor = primaryPlugin ?? pluginNames[0];
  const overflow = Math.max(pluginNames.length - 1, 0);
  return overflow > 0 ? `${anchor} +${overflow}` : anchor;
}
