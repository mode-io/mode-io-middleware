export type Locale = "en" | "zh";
export type DashboardView = "traffic" | "plugins";

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

export type PluginValidationStatus = "ok" | "warn" | "error";
export type PluginMode = "observe" | "assist" | "enforce";
export type PluginStateFilter = "all" | "enabled" | "disabled" | "attention";
export type PluginCapabilityFilter = "all" | "canPatch" | "canBlock";
export type PluginHealthFilter = "all" | PluginValidationStatus;

export interface PluginCapabilitiesGrant {
  can_patch: boolean;
  can_block: boolean;
}

export interface PluginProfileOverride {
  enabled?: boolean;
  mode?: string;
  capabilities_grant?: Partial<PluginCapabilitiesGrant>;
  timeout_ms?: Record<string, number>;
  pool_size?: number;
}

export interface PluginProfileState {
  listed: boolean;
  enabled: boolean;
  position: number | null;
  override: PluginProfileOverride;
  effectiveMode?: string;
  effectiveCapabilitiesGrant?: PluginCapabilitiesGrant;
  effectivePoolSize?: number;
  effectiveTimeoutMs?: Record<string, number>;
}

export interface PluginValidation {
  status: PluginValidationStatus;
  warnings: string[];
  errors: string[];
}

export interface PluginStats {
  calls: number;
  errors: number;
  actions: Record<string, number>;
}

export interface PluginInventoryItem {
  name: string;
  displayName: string;
  description: string;
  sourceKind: string;
  version: string;
  hooks: string[];
  declaredCapabilities: {
    canPatch: boolean;
    canBlock: boolean;
    needsNetwork: boolean;
    needsRawBody: boolean;
  };
  metadata: Record<string, unknown>;
  pluginDir: string | null;
  manifestPath: string | null;
  hostPath: string | null;
  readmePath: string | null;
  profiles: Record<string, PluginProfileState>;
  validation: PluginValidation;
  stats: PluginStats;
}

export interface PluginProfileSummary {
  name: string;
  onPluginError: string;
  pluginOrder: string[];
}

export interface PluginRuntimeSummary {
  configPath: string;
  configWritable: boolean;
  generation: number;
  defaultProfile: string;
  discoveryRoots: string[];
}

export interface PluginInventoryResponse {
  runtime: PluginRuntimeSummary;
  profiles: PluginProfileSummary[];
  plugins: PluginInventoryItem[];
  warnings: string[];
}

export interface PluginUpdateResponse {
  ok: boolean;
  generation: number;
  configPath: string;
  backupPath: string;
  reloaded: boolean;
}

export interface PluginListFilters {
  search: string;
  state: PluginStateFilter;
  capability: PluginCapabilityFilter;
  health: PluginHealthFilter;
}
