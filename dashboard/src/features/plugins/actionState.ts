import type { PluginRow, PluginWorkingState } from "./selectors";
import type { PluginInventoryItem } from "../../types";

export interface PluginQuickActionState {
  canEnable: boolean;
  canDisable: boolean;
  canMoveUp: boolean;
  canMoveDown: boolean;
  showReview: boolean;
}

interface ActionContext {
  readOnly: boolean;
  actionsDisabled: boolean;
  actionPending: boolean;
  enabledCount: number;
}

function resolveQuickActions(
  working: PluginWorkingState,
  plugin: Pick<PluginInventoryItem, "validation">,
  context: ActionContext,
): PluginQuickActionState {
  const showReview = !working.enabled && working.requiresReview && working.hasRememberedSettings;
  const canEnable = !showReview
    && !context.readOnly
    && !context.actionsDisabled
    && !context.actionPending
    && !working.enabled
    && plugin.validation.status !== "error";
  const canDisable = working.enabled && !context.readOnly && !context.actionsDisabled && !context.actionPending;

  return {
    canEnable,
    canDisable,
    canMoveUp: canDisable && (working.position ?? 0) > 0,
    canMoveDown: canDisable && working.position != null && working.position < context.enabledCount - 1,
    showReview,
  };
}

export function buildPluginRowActionState(
  row: PluginRow,
  context: ActionContext,
): PluginQuickActionState {
  return resolveQuickActions(row.working, row.plugin, context);
}

export function buildPluginInspectorActionState(
  plugin: PluginInventoryItem,
  working: PluginWorkingState,
  context: Omit<ActionContext, "enabledCount">,
): Pick<PluginQuickActionState, "canEnable" | "canDisable"> {
  const quickActions = resolveQuickActions(working, plugin, {
    ...context,
    enabledCount: Number.MAX_SAFE_INTEGER,
  });
  return {
    canEnable: quickActions.canEnable,
    canDisable: quickActions.canDisable,
  };
}
