import { describe, expect, it } from "vitest";

import {
  buildBaseProfileDraft,
  buildPluginRows,
  createDisableDraft,
  createMoveDraft,
  createPluginSettingsDraft,
  createSafeEnableDraft,
  DEFAULT_PLUGIN_FILTERS,
  resolveWorkingState,
} from "./pluginManagement";
import type { PluginInventoryResponse } from "./types";

function createInventory(): PluginInventoryResponse {
  return {
    runtime: {
      configPath: "/tmp/middleware.json",
      configWritable: true,
      generation: 1,
      defaultProfile: "dev",
      discoveryRoots: ["/tmp/plugins"],
    },
    profiles: [
      { name: "dev", onPluginError: "warn", pluginOrder: ["alpha/plugin"] },
      { name: "prod", onPluginError: "fail_safe", pluginOrder: [] },
    ],
    warnings: [],
    plugins: [
      {
        name: "alpha/plugin",
        displayName: "Alpha Plugin",
        description: "First plugin",
        sourceKind: "discovered",
        version: "0.1.0",
        hooks: ["pre.request"],
        declaredCapabilities: { canPatch: true, canBlock: false, needsNetwork: false, needsRawBody: false },
        metadata: {},
        pluginDir: null,
        manifestPath: null,
        hostPath: null,
        readmePath: null,
        validation: { status: "ok", warnings: [], errors: [] },
        stats: { calls: 2, errors: 0, actions: { modify: 1 } },
        profiles: {
          dev: {
            listed: true,
            enabled: true,
            position: 0,
            override: { mode: "assist", capabilities_grant: { can_patch: true, can_block: false }, pool_size: 2 },
            effectiveMode: "assist",
            effectiveCapabilitiesGrant: { can_patch: true, can_block: false },
            effectivePoolSize: 2,
            effectiveTimeoutMs: { "pre.request": 240 },
          },
          prod: {
            listed: false,
            enabled: false,
            position: null,
            override: {},
            effectiveMode: "observe",
            effectiveCapabilitiesGrant: { can_patch: false, can_block: false },
            effectivePoolSize: 1,
            effectiveTimeoutMs: {},
          },
        },
      },
      {
        name: "beta/plugin",
        displayName: "Beta Plugin",
        description: "Needs attention",
        sourceKind: "discovered",
        version: "0.1.0",
        hooks: ["post.response"],
        declaredCapabilities: { canPatch: false, canBlock: true, needsNetwork: false, needsRawBody: false },
        metadata: {},
        pluginDir: null,
        manifestPath: null,
        hostPath: null,
        readmePath: null,
        validation: { status: "warn", warnings: ["review config"], errors: [] },
        stats: { calls: 0, errors: 0, actions: {} },
        profiles: {
          dev: {
            listed: false,
            enabled: false,
            position: null,
            override: { mode: "observe", capabilities_grant: { can_patch: false, can_block: false } },
            effectiveMode: "observe",
            effectiveCapabilitiesGrant: { can_patch: false, can_block: false },
            effectivePoolSize: 1,
            effectiveTimeoutMs: {},
          },
          prod: {
            listed: false,
            enabled: false,
            position: null,
            override: {},
            effectiveMode: "observe",
            effectiveCapabilitiesGrant: { can_patch: false, can_block: false },
            effectivePoolSize: 1,
            effectiveTimeoutMs: {},
          },
        },
      },
    ],
  };
}

describe("pluginManagement helpers", () => {
  it("builds rows with enabled plugins before attention items", () => {
    const inventory = createInventory();
    const draft = buildBaseProfileDraft(inventory, "dev");
    const rows = buildPluginRows(inventory, "dev", draft, DEFAULT_PLUGIN_FILTERS);
    expect(rows.map((row) => row.plugin.name)).toEqual(["alpha/plugin", "beta/plugin"]);
    expect(rows[0]?.working.enabled).toBe(true);
    expect(rows[1]?.stateKind).toBe("attention");
  });

  it("resolves working state from draft overrides and preserves explicit false grants", () => {
    const inventory = createInventory();
    const draft = createPluginSettingsDraft(buildBaseProfileDraft(inventory, "dev"), "alpha/plugin", {
      capabilities_grant: { can_patch: false, can_block: false },
      mode: "observe",
    });
    const working = resolveWorkingState(inventory.plugins[0], "dev", draft);
    expect(working.effectiveMode).toBe("observe");
    expect(working.effectiveCapabilitiesGrant.can_patch).toBe(false);
    expect(working.requiresReview).toBe(false);
  });

  it("creates safe enable, disable, and move drafts deterministically", () => {
    const inventory = createInventory();
    const base = buildBaseProfileDraft(inventory, "dev");
    const enabled = createSafeEnableDraft(inventory, "dev", base, "beta/plugin");
    expect(enabled.pluginOrder).toEqual(["alpha/plugin", "beta/plugin"]);
    expect(enabled.pluginOverrides["beta/plugin"]?.mode).toBe("observe");
    expect(enabled.pluginOverrides["beta/plugin"]?.capabilities_grant).toEqual({ can_patch: false, can_block: false });

    const moved = createMoveDraft(enabled, "beta/plugin", -1);
    expect(moved.pluginOrder).toEqual(["beta/plugin", "alpha/plugin"]);

    const disabled = createDisableDraft(moved, "beta/plugin");
    expect(disabled.pluginOrder).toEqual(["alpha/plugin"]);
  });
});
