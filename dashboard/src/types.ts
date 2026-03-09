export type Locale = "en" | "zh";

export type TraceStatus = "completed" | "blocked" | "error" | "stream_completed";
export type TraceImpact = "pass_through" | "modified" | "blocked" | "warned" | "mixed";
export type ClientName = "unknown" | "claude_code" | "codex" | "opencode" | "openclaw";
export type TraceLifecycle = "none" | "pre_request" | "post_response" | "pre_and_post" | "stream" | "pre_and_stream";

export interface EventSummary {
  isDemo?: boolean;
  sequence: number;
  requestId: string;
  startedAt: string;
  durationMs: number;
  source: string;
  clientName: ClientName;
  lifecycle: TraceLifecycle;
  sourceEvent: string;
  endpointKind: string;
  phase: string;
  profile: string;
  stream: boolean;
  status: TraceStatus;
  blocked: boolean;
  upstreamCalled: boolean;
  requestChanged: boolean;
  responseChanged: boolean;
  preActions: string[];
  postActions: string[];
  degradedCount: number;
  findingCount: number;
  hookCount: number;
  impact: TraceImpact;
  impactActions: string[];
  primaryPlugin: string | null;
  pluginNames: string[];
}

export interface ChangeSummary {
  changed: boolean;
  addCount: number;
  removeCount: number;
  replaceCount: number;
  samplePaths: string[];
}

export interface HookExecution {
  pluginName: string;
  hookName: string;
  reportedAction: string | null;
  effectiveAction: string;
  durationMs: number;
  errored: boolean;
  errorType: string | null;
}

export interface EventDetail {
  isDemo?: boolean;
  sequence: number;
  requestId: string;
  startedAt: string;
  finishedAt: string;
  durationMs: number;
  source: string;
  clientName: ClientName;
  lifecycle: TraceLifecycle;
  sourceEvent: string;
  endpointKind: string;
  phase: string;
  profile: string;
  stream: boolean;
  status: TraceStatus;
  blocked: boolean;
  blockMessage: string | null;
  errorCode: string | null;
  errorMessage: string | null;
  upstreamCalled: boolean;
  upstreamDurationMs: number | null;
  request: {
    before: Record<string, unknown> | null;
    after: Record<string, unknown> | null;
    change: ChangeSummary;
  };
  response: {
    before: Record<string, unknown> | null;
    after: Record<string, unknown> | null;
    change: ChangeSummary;
  };
  preActions: string[];
  postActions: string[];
  degraded: string[];
  findings: Array<Record<string, unknown>>;
  hookExecutions: HookExecution[];
  impact: TraceImpact;
  impactActions: string[];
  primaryPlugin: string | null;
  pluginNames: string[];
  streamSummary: {
    eventCount: number;
    blockedDuringStream: boolean;
    doneReceived: boolean;
  };
}

export interface StatsSnapshot {
  retainedRecords: number;
  completedRecords: number;
  inFlightRecords: number;
  changedRequestCount: number;
  changedResponseCount: number;
  byStatus: Record<string, number>;
  bySource: Record<string, number>;
  byClient: Record<string, number>;
  byImpact: Record<string, number>;
  byLifecycle: Record<string, number>;
  byEndpointKind: Record<string, number>;
  byAction: Record<string, number>;
  byPlugin: Record<string, { calls: number; errors: number; actions: Record<string, number> }>;
  latencyMs: {
    p50: number;
    p95: number;
    max: number;
  };
}

export interface EventsResponse {
  items: EventSummary[];
  nextCursor: number | null;
}

export type MonitorFilterKey = "status" | "clientName" | "impact" | "lifecycle";

export type MonitorFilters = Record<MonitorFilterKey, string>;
