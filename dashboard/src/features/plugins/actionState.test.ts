import { describe, expect, it } from "vitest";

import { buildPluginInspectorActionState, buildPluginRowActionState } from "./actionState";
import type { PluginRow, PluginWorkingState } from "./selectors";
import type { PluginInventoryItem } from "../../types";

function createPlugin(): PluginInventoryItem {
  return {
    name: "catalog/rewrite",
    displayName: "Rewrite Plugin",
    description: "",
    sourceKind: "discovered",
    version: "0.1.0",
    hooks: ["pre.request"],
    declaredCapabilities: {
      canPatch: true,
      canBlock: false,
      needsNetwork: false,
      needsRawBody: false,
    },
    metadata: {},
    pluginDir: null,
    manifestPath: null,
    hostPath: null,
    readmePath: null,
    profiles: {
      dev: {
        listed: true,
        enabled: true,
        position: 0,
        override: {},
      },
    },
    validation: {
      status: "ok",
      warnings: [],
      errors: [],
    },
    stats: {
      calls: 0,
      errors: 0,
      actions: {},
    },
  };
}

function createWorkingState(overrides?: Partial<PluginWorkingState>): PluginWorkingState {
  return {
    listed: true,
    enabled: true,
    position: 0,
    override: {},
    effectiveMode: "observe",
    effectiveCapabilitiesGrant: { can_patch: false, can_block: false },
    effectivePoolSize: 1,
    effectiveTimeoutMs: {},
    requiresReview: false,
    hasRememberedSettings: false,
    ...overrides,
  };
}

function createRow(overrides?: Partial<PluginWorkingState>): PluginRow {
  return {
    plugin: createPlugin(),
    working: createWorkingState(overrides),
    stateKind: overrides?.enabled ? "enabled" : "disabled",
  };
}

describe("plugin quick action state", () => {
  it("allows disable and downward movement for an enabled middle plugin", () => {
    const row = createRow({ enabled: true, position: 1 });
    const actionState = buildPluginRowActionState(row, {
      readOnly: false,
      actionsDisabled: false,
      actionPending: false,
      enabledCount: 3,
    });

    expect(actionState.canDisable).toBe(true);
    expect(actionState.canMoveUp).toBe(true);
    expect(actionState.canMoveDown).toBe(true);
  });

  it("forces review instead of enable when a disabled plugin has remembered elevated settings", () => {
    const row = createRow({
      enabled: false,
      listed: false,
      position: null,
      requiresReview: true,
      hasRememberedSettings: true,
      effectiveMode: "assist",
    });

    const actionState = buildPluginRowActionState(row, {
      readOnly: false,
      actionsDisabled: false,
      actionPending: false,
      enabledCount: 0,
    });

    expect(actionState.showReview).toBe(true);
    expect(actionState.canEnable).toBe(false);
  });

  it("shares the same enable-disable guard model with the inspector", () => {
    const plugin = createPlugin();
    const working = createWorkingState({ enabled: false, listed: false, position: null });

    const inspectorState = buildPluginInspectorActionState(plugin, working, {
      readOnly: false,
      actionsDisabled: false,
      actionPending: false,
    });

    expect(inspectorState.canEnable).toBe(true);
    expect(inspectorState.canDisable).toBe(false);
  });
});
