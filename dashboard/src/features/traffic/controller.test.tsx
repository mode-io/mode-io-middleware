import { QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor, act } from "@testing-library/react";
import type { PropsWithChildren } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { createDashboardQueryClient } from "../../queryClient";
import { useTrafficMonitorState } from "./controller";

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function wrapper() {
  const queryClient = createDashboardQueryClient();
  return ({ children }: PropsWithChildren) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

function createLiveEvents() {
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
        profile: "dev",
        stream: false,
        status: "completed",
        blocked: false,
        upstreamCalled: true,
        requestChanged: true,
        responseChanged: false,
        preActions: [],
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

function createLiveStats() {
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

function createDetail() {
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
    profile: "dev",
    stream: false,
    status: "completed",
    blocked: false,
    blockMessage: null,
    errorCode: null,
    errorMessage: null,
    upstreamCalled: true,
    upstreamDurationMs: 90,
    request: { before: {}, after: {}, change: { changed: false, addCount: 0, removeCount: 0, replaceCount: 0, samplePaths: [] } },
    response: { before: {}, after: {}, change: { changed: false, addCount: 0, removeCount: 0, replaceCount: 0, samplePaths: [] } },
    preActions: [],
    postActions: [],
    degraded: [],
    findings: [],
    hookExecutions: [],
    impact: "modified",
    impactActions: ["modify"],
    primaryPlugin: "catalog/rewrite",
    pluginNames: ["catalog/rewrite"],
    streamSummary: { eventCount: 0, blockedDuringStream: false, doneReceived: false },
  };
}

describe("useTrafficMonitorState", () => {
  beforeEach(() => {
    vi.useRealTimers();
  });

  it("falls back to demo data when traffic queries are empty", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.startsWith("/modeio/api/events?")) {
        return jsonResponse({ items: [], nextCursor: null });
      }
      if (url === "/modeio/api/stats") {
        return jsonResponse({
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
        });
      }
      return jsonResponse({}, 404);
    }));

    const { result } = renderHook(() => useTrafficMonitorState("en"), { wrapper: wrapper() });

    await waitFor(() => expect(result.current.overviewLoading).toBe(false));
    expect(result.current.usingDemo).toBe(true);
    expect(result.current.events.length).toBeGreaterThan(0);
    expect(result.current.selectedRequestId).not.toBeNull();
    expect(result.current.detail).not.toBeNull();
  });

  it("loads live traffic detail for the selected request", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.startsWith("/modeio/api/events?")) {
        return jsonResponse(createLiveEvents());
      }
      if (url === "/modeio/api/stats") {
        return jsonResponse(createLiveStats());
      }
      if (url === "/modeio/api/events/req_1") {
        return jsonResponse(createDetail());
      }
      return jsonResponse({}, 404);
    });
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useTrafficMonitorState("en"), { wrapper: wrapper() });

    await waitFor(() => expect(result.current.selectedRequestId).toBe("req_1"));
    await waitFor(() => expect(result.current.detail?.requestId).toBe("req_1"));
    expect(result.current.usingDemo).toBe(false);
    expect(fetchMock).toHaveBeenCalledWith("/modeio/api/events/req_1", expect.anything());
  });

  it("invalidates traffic queries when live events arrive", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.startsWith("/modeio/api/events?")) {
        return jsonResponse(createLiveEvents());
      }
      if (url === "/modeio/api/stats") {
        return jsonResponse(createLiveStats());
      }
      if (url === "/modeio/api/events/req_1") {
        return jsonResponse(createDetail());
      }
      return jsonResponse({}, 404);
    });
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useTrafficMonitorState("en"), { wrapper: wrapper() });

    await waitFor(() => expect(result.current.detail?.requestId).toBe("req_1"));
    const initialCalls = fetchMock.mock.calls.length;
    const EventSourceClass = (window as unknown as { __TEST_EVENT_SOURCE__: { instances: Array<{ emit: (type: string) => void }> } }).__TEST_EVENT_SOURCE__;

    act(() => {
      EventSourceClass.instances[0]?.emit("trace.completed");
    });

    await new Promise((resolve) => window.setTimeout(resolve, 220));

    await waitFor(() => expect(fetchMock.mock.calls.length).toBeGreaterThan(initialCalls));
  });
});
