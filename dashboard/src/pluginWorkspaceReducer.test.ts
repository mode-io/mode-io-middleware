import { describe, expect, it } from "vitest";

import { pluginWorkspaceReducer, initialPluginWorkspaceState } from "./pluginWorkspaceReducer";
import type { PluginInventoryResponse } from "./types";

function createInventory(): PluginInventoryResponse {
  return {
    runtime: {
      configPath: "/tmp/middleware.json",
      configWritable: true,
      generation: 4,
      defaultProfile: "dev",
      discoveryRoots: ["/tmp/plugins"],
    },
    profiles: [
      { name: "dev", onPluginError: "warn", pluginOrder: [] },
      { name: "prod", onPluginError: "fail_safe", pluginOrder: [] },
    ],
    warnings: [],
    plugins: [
      {
        name: "catalog/rewrite",
        displayName: "Rewrite Plugin",
        description: "",
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
        stats: { calls: 0, errors: 0, actions: {} },
        profiles: {
          dev: { listed: false, enabled: false, position: null, override: {} },
          prod: { listed: false, enabled: false, position: null, override: {} },
        },
      },
    ],
  };
}

describe("pluginWorkspaceReducer", () => {
  it("selects default profile and first plugin when inventory syncs", () => {
    const next = pluginWorkspaceReducer(initialPluginWorkspaceState, {
      type: "inventory-synced",
      inventory: createInventory(),
      defaultFilters: { search: "" },
    });

    expect(next.selectedProfile).toBe("dev");
    expect(next.selectedPluginName).toBe("catalog/rewrite");
  });

  it("preserves a same-profile draft but clears it when switching profiles", () => {
    const withDraft = {
      ...initialPluginWorkspaceState,
      selectedProfile: "dev",
      draft: { pluginOrder: ["catalog/rewrite"], pluginOverrides: {} },
      draftProfile: "dev",
    };

    const sameProfile = pluginWorkspaceReducer(withDraft, {
      type: "select-profile",
      profileName: "dev",
    });
    expect(sameProfile.draft).not.toBeNull();

    const switched = pluginWorkspaceReducer(withDraft, {
      type: "select-profile",
      profileName: "prod",
    });
    expect(switched.draft).toBeNull();
    expect(switched.draftProfile).toBeNull();
  });

  it("tracks mutation lifecycle and clears draft on success", () => {
    const started = pluginWorkspaceReducer(initialPluginWorkspaceState, {
      type: "mutation-started",
      kind: "toggle",
      pluginName: "catalog/rewrite",
    });
    expect(started.mutation.status).toBe("pending");
    expect(started.mutation.pluginName).toBe("catalog/rewrite");

    const failed = pluginWorkspaceReducer(started, {
      type: "mutation-failed",
      message: "failed",
    });
    expect(failed.mutation.status).toBe("error");
    expect(failed.mutation.message).toBe("failed");

    const succeeded = pluginWorkspaceReducer(
      {
        ...failed,
        draft: { pluginOrder: ["catalog/rewrite"], pluginOverrides: {} },
        draftProfile: "dev",
      },
      { type: "mutation-succeeded" },
    );
    expect(succeeded.mutation.status).toBe("idle");
    expect(succeeded.draft).toBeNull();
  });
});
