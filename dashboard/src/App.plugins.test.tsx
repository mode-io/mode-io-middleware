import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";
import type { PluginInventoryResponse } from "./types";

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function createPluginInventory(options?: { configWritable?: boolean; generation?: number }): PluginInventoryResponse {
  const configWritable = options?.configWritable ?? true;
  const generation = options?.generation ?? 1;
  return {
    runtime: {
      configPath: "/tmp/middleware.json",
      configWritable,
      generation,
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
        description: "Rewrites the first user message before upstream dispatch.",
        sourceKind: "discovered",
        version: "0.1.0",
        hooks: ["pre.request"],
        declaredCapabilities: { canPatch: true, canBlock: false, needsNetwork: false, needsRawBody: false },
        metadata: { documentation_url: "https://example.com/docs/rewrite" },
        pluginDir: "/tmp/plugins/rewrite",
        manifestPath: "/tmp/plugins/rewrite/manifest.json",
        hostPath: "/tmp/plugins/rewrite/modeio.host.json",
        readmePath: "/tmp/plugins/rewrite/README.md",
        validation: { status: "ok", warnings: [], errors: [] },
        stats: { calls: 4, errors: 0, actions: { modify: 4 } },
        profiles: {
          dev: {
            listed: false,
            enabled: false,
            position: null,
            override: {},
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
      {
        name: "audit/logger",
        displayName: "Audit Logger",
        description: "Records request outcomes.",
        sourceKind: "config",
        version: "0.2.0",
        hooks: ["post.response"],
        declaredCapabilities: { canPatch: false, canBlock: false, needsNetwork: false, needsRawBody: false },
        metadata: {},
        pluginDir: "/tmp/plugins/audit",
        manifestPath: "/tmp/plugins/audit/manifest.json",
        hostPath: "/tmp/plugins/audit/modeio.host.json",
        readmePath: null,
        validation: { status: "warn", warnings: ["review config"], errors: [] },
        stats: { calls: 1, errors: 0, actions: { warn: 1 } },
        profiles: {
          dev: {
            listed: false,
            enabled: false,
            position: null,
            override: { mode: "assist", capabilities_grant: { can_patch: false, can_block: false } },
            effectiveMode: "assist",
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

function createTrafficEvent(profile = "dev") {
  return {
    items: [
      {
        sequence: 1,
        requestId: "req_1",
        startedAt: "2026-03-09T06:00:00Z",
        durationMs: 120,
        source: "openai_gateway",
        clientName: "opencode",
        lifecycle: "pre_request",
        sourceEvent: "http_request",
        endpointKind: "chat_completions",
        phase: "request",
        profile,
        stream: false,
        status: "completed",
        blocked: false,
        upstreamCalled: true,
        requestChanged: true,
        responseChanged: false,
        preActions: ["rewrite:modify"],
        postActions: [],
        degradedCount: 0,
        findingCount: 0,
        hookCount: 1,
        impact: "modified",
        impactActions: ["modify"],
        primaryPlugin: "catalog/rewrite",
        pluginNames: ["catalog/rewrite"],
      },
    ],
    nextCursor: null,
  };
}

function createEmptyTraffic() {
  return {
    items: [],
    nextCursor: null,
  };
}

function createStats() {
  return {
    retainedRecords: 1,
    completedRecords: 1,
    inFlightRecords: 0,
    changedRequestCount: 1,
    changedResponseCount: 0,
    byStatus: { completed: 1 },
    bySource: { openai_gateway: 1 },
    byClient: { opencode: 1 },
    byImpact: { modified: 1 },
    byLifecycle: { pre_request: 1 },
    byEndpointKind: { chat_completions: 1 },
    byAction: { modify: 1 },
    byPlugin: { "catalog/rewrite": { calls: 1, errors: 0, actions: { modify: 1 } } },
    latencyMs: { p50: 120, p95: 120, max: 120 },
  };
}

function createEmptyStats() {
  return {
    retainedRecords: 0,
    completedRecords: 0,
    inFlightRecords: 0,
    changedRequestCount: 0,
    changedResponseCount: 0,
    byStatus: {},
    bySource: {},
    byClient: {},
    byImpact: {},
    byLifecycle: {},
    byEndpointKind: {},
    byAction: {},
    byPlugin: {},
    latencyMs: { p50: 0, p95: 0, max: 0 },
  };
}

function createDetail(profile = "dev") {
  return {
    sequence: 1,
    requestId: "req_1",
    startedAt: "2026-03-09T06:00:00Z",
    finishedAt: "2026-03-09T06:00:01Z",
    durationMs: 120,
    source: "openai_gateway",
    clientName: "opencode",
    lifecycle: "pre_request",
    sourceEvent: "http_request",
    endpointKind: "chat_completions",
    phase: "request",
    profile,
    stream: false,
    status: "completed",
    blocked: false,
    blockMessage: null,
    errorCode: null,
    errorMessage: null,
    upstreamCalled: true,
    upstreamDurationMs: 90,
    request: {
      before: { messages: [{ role: "user", content: "hello" }] },
      after: { messages: [{ role: "user", content: "rewritten" }] },
      change: { changed: true, addCount: 0, removeCount: 0, replaceCount: 1, samplePaths: ["/messages/0/content"] },
    },
    response: {
      before: { output_text: "ok" },
      after: { output_text: "ok" },
      change: { changed: false, addCount: 0, removeCount: 0, replaceCount: 0, samplePaths: [] },
    },
    preActions: ["rewrite:modify"],
    postActions: [],
    degraded: [],
    findings: [],
    hookExecutions: [
      {
        pluginName: "catalog/rewrite",
        hookName: "pre_request",
        reportedAction: "modify",
        effectiveAction: "modify",
        durationMs: 2.1,
        errored: false,
        errorType: null,
      },
    ],
    impact: "modified",
    impactActions: ["modify"],
    primaryPlugin: "catalog/rewrite",
    pluginNames: ["catalog/rewrite"],
    streamSummary: { eventCount: 0, blockedDuringStream: false, doneReceived: false },
  };
}

function applyProfileUpdate(inventory: PluginInventoryResponse, body: { pluginOrder: string[]; pluginOverrides: Record<string, any> }) {
  const next = structuredClone(inventory);
  next.runtime.generation += 1;
  const devProfile = next.profiles.find((profile) => profile.name === "dev");
  if (devProfile) {
    devProfile.pluginOrder = [...body.pluginOrder];
  }
  next.plugins = next.plugins.map((plugin) => {
    const override = body.pluginOverrides[plugin.name] || {};
    const position = body.pluginOrder.indexOf(plugin.name);
    const listed = position >= 0;
    return {
      ...plugin,
      profiles: {
        ...plugin.profiles,
        dev: {
          ...plugin.profiles.dev,
          listed,
          enabled: listed && (override.enabled ?? true) && plugin.validation.status !== "error",
          position: listed ? position : null,
          override,
          effectiveMode: override.mode ?? plugin.profiles.dev.effectiveMode ?? "observe",
          effectiveCapabilitiesGrant: {
            can_patch: override.capabilities_grant?.can_patch ?? plugin.profiles.dev.effectiveCapabilitiesGrant?.can_patch ?? false,
            can_block: override.capabilities_grant?.can_block ?? plugin.profiles.dev.effectiveCapabilitiesGrant?.can_block ?? false,
          },
          effectivePoolSize: override.pool_size ?? plugin.profiles.dev.effectivePoolSize ?? 1,
          effectiveTimeoutMs: override.timeout_ms ?? plugin.profiles.dev.effectiveTimeoutMs ?? {},
        },
      },
    };
  });
  return next;
}

function installFetchMock(options?: { inventory?: PluginInventoryResponse; conflictOnce?: boolean; emptyTraffic?: boolean }) {
  let inventory = structuredClone(options?.inventory ?? createPluginInventory());
  const updates: any[] = [];
  let conflictOnce = options?.conflictOnce ?? false;
  const emptyTraffic = options?.emptyTraffic ?? false;

  const mock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    const method = init?.method ?? "GET";

    if (url.startsWith("/modeio/api/events?")) {
      return jsonResponse(emptyTraffic ? createEmptyTraffic() : createTrafficEvent());
    }
    if (url === "/modeio/api/stats") {
      return jsonResponse(emptyTraffic ? createEmptyStats() : createStats());
    }
    if (url === "/modeio/api/events/req_1") {
      return jsonResponse(createDetail());
    }
    if (url === "/modeio/api/plugins" && method === "GET") {
      return jsonResponse(inventory);
    }
    if (url === "/modeio/api/profiles/dev/plugins" && method === "PUT") {
      const body = JSON.parse(String(init?.body || "{}"));
      updates.push(body);
      if (conflictOnce) {
        conflictOnce = false;
        inventory = { ...inventory, runtime: { ...inventory.runtime, generation: inventory.runtime.generation + 1 } };
        return jsonResponse({ error: { code: "MODEIO_GENERATION_CONFLICT", message: "stale" } }, 409);
      }
      inventory = applyProfileUpdate(inventory, body);
      return jsonResponse({ ok: true, generation: inventory.runtime.generation, configPath: inventory.runtime.configPath, backupPath: "/tmp/backups/middleware.json", reloaded: true });
    }
    return jsonResponse({ error: { code: "NOT_FOUND", message: `${method} ${url}` } }, 404);
  });

  vi.stubGlobal("fetch", mock);
  return {
    mock,
    updates,
    getInventory: () => inventory,
  };
}

describe("App plugin workspace", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("enables a discovered plugin safely from the list", async () => {
    const fetchState = installFetchMock();
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole("tab", { name: "Plugins" }));
    expect((await screen.findAllByText("Rewrite Plugin")).length).toBeGreaterThan(0);

    await user.click(screen.getAllByRole("button", { name: "Enable safely" })[0]);

    await waitFor(() => expect(fetchState.updates).toHaveLength(1));
    expect(fetchState.updates[0]).toMatchObject({
      pluginOrder: ["catalog/rewrite"],
      pluginOverrides: {
        "catalog/rewrite": {
          enabled: true,
          mode: "observe",
          capabilities_grant: { can_patch: false, can_block: false },
        },
      },
    });

    await waitFor(() => expect(screen.getAllByRole("button", { name: "Disable" }).length).toBeGreaterThan(0));
    expect(fetchState.getInventory().profiles[0]?.pluginOrder).toEqual(["catalog/rewrite"]);

    await user.click(screen.getAllByRole("button", { name: "Disable" })[0]);

    await waitFor(() => expect(fetchState.updates).toHaveLength(2));
    expect(fetchState.updates[1]).toMatchObject({
      pluginOrder: [],
    });
  });

  it("keeps the top tabs stable and shows demo messaging inside the traffic view", async () => {
    installFetchMock({ emptyTraffic: true });
    render(<App />);

    expect(await screen.findByText("Showing example traces. Live data will replace these automatically.")).toBeInTheDocument();
    expect(screen.queryByText("example data")).not.toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Traffic", selected: true })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Plugins", selected: false })).toBeInTheDocument();
  });

  it("edits plugin settings and saves an explicit profile draft", async () => {
    const fetchState = installFetchMock();
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole("tab", { name: "Plugins" }));
    await user.click((await screen.findAllByText("Rewrite Plugin"))[0]);

    await user.selectOptions(screen.getByLabelText("Mode"), "assist");
    await user.click(screen.getByLabelText("Can patch"));
    await user.clear(screen.getByLabelText("Pool size"));
    await user.type(screen.getByLabelText("Pool size"), "3");
    await user.type(screen.getByLabelText("pre.request"), "220");
    expect(screen.getAllByText("Unsaved changes are ready for review.").length).toBeGreaterThan(0);

    await user.click(screen.getAllByRole("button", { name: "Save settings" })[0]);

    await waitFor(() => expect(fetchState.updates).toHaveLength(1));
    expect(fetchState.updates[0]).toMatchObject({
      pluginOverrides: {
        "catalog/rewrite": {
          mode: "assist",
          capabilities_grant: { can_patch: true, can_block: false },
          pool_size: 3,
          timeout_ms: { "pre.request": 220 },
        },
      },
    });
  });

  it("shows a stale-config banner when the backend returns a generation conflict", async () => {
    installFetchMock({ conflictOnce: true });
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole("tab", { name: "Plugins" }));
    await user.click((await screen.findAllByText("Rewrite Plugin"))[0]);

    await user.selectOptions(screen.getByLabelText("Mode"), "assist");
    await user.click(screen.getAllByRole("button", { name: "Save settings" })[0]);

    expect(await screen.findByText("Plugin config changed elsewhere. Review the latest state and save again.")).toBeInTheDocument();
  });

  it("navigates from the traffic table into the matching plugin inspector", async () => {
    installFetchMock();
    const user = userEvent.setup();
    render(<App />);

    const pluginLink = (await screen.findAllByRole("button", { name: "catalog/rewrite" }))[0];
    await user.click(pluginLink);

    expect(await screen.findByRole("tab", { name: "Plugins", selected: true })).toBeInTheDocument();
    expect((await screen.findAllByText("Rewrite Plugin")).length).toBeGreaterThan(0);
    expect((screen.getByLabelText("Selected profile") as HTMLSelectElement).value).toBe("dev");
  });

  it("blocks quick row actions while the current profile has unsaved draft changes", async () => {
    installFetchMock();
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole("tab", { name: "Plugins" }));
    await user.click((await screen.findAllByText("Rewrite Plugin"))[0]);
    await user.selectOptions(screen.getByLabelText("Mode"), "assist");

    expect(await screen.findByText("Save or discard draft changes before enabling, disabling, or reordering plugins.")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Enable safely" })[0]).toBeDisabled();
  });

  it("requires resolving a dirty draft before switching profiles", async () => {
    installFetchMock();
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole("tab", { name: "Plugins" }));
    await user.click((await screen.findAllByText("Rewrite Plugin"))[0]);
    await user.selectOptions(screen.getByLabelText("Mode"), "assist");
    await user.selectOptions(screen.getByLabelText("Selected profile"), "prod");

    expect(await screen.findByText("Unsaved changes are blocking a profile switch to prod.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Discard and continue" }));

    expect((screen.getByLabelText("Selected profile") as HTMLSelectElement).value).toBe("prod");
  });

  it("disables mutating controls when the plugin config is read-only", async () => {
    installFetchMock({ inventory: createPluginInventory({ configWritable: false }) });
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole("tab", { name: "Plugins" }));
    expect((await screen.findAllByText("Plugin config is read-only. Inventory is visible, but changes are disabled.")).length).toBeGreaterThan(0);
    expect(screen.getAllByRole("button", { name: "Enable safely" })[0]).toBeDisabled();
    expect(screen.getByRole("button", { name: "Save settings" })).toBeDisabled();
  });
});
