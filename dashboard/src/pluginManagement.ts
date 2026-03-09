import type {
  PluginCapabilitiesGrant,
  PluginHealthFilter,
  PluginInventoryItem,
  PluginInventoryResponse,
  PluginListFilters,
  PluginProfileOverride,
  PluginStateFilter,
  PluginValidationStatus,
} from "./types";

export interface ProfileDraft {
  pluginOrder: string[];
  pluginOverrides: Record<string, PluginProfileOverride>;
}

export interface PluginWorkingState {
  listed: boolean;
  enabled: boolean;
  position: number | null;
  override: PluginProfileOverride;
  effectiveMode: string;
  effectiveCapabilitiesGrant: PluginCapabilitiesGrant;
  effectivePoolSize: number;
  effectiveTimeoutMs: Record<string, number>;
  requiresReview: boolean;
  hasRememberedSettings: boolean;
}

export interface PluginRow {
  plugin: PluginInventoryItem;
  working: PluginWorkingState;
  stateKind: "enabled" | "attention" | "disabled";
  usageLabel: string;
}

export const DEFAULT_PLUGIN_FILTERS: PluginListFilters = {
  search: "",
  state: "all",
  capability: "all",
  health: "all",
};

function cloneJson<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function normalizeGrant(grant: Partial<PluginCapabilitiesGrant> | undefined): PluginCapabilitiesGrant {
  return {
    can_patch: Boolean(grant?.can_patch),
    can_block: Boolean(grant?.can_block),
  };
}

function normalizeOverride(override: PluginProfileOverride | undefined): PluginProfileOverride {
  if (!override) {
    return {};
  }
  const next: PluginProfileOverride = {};
  if (typeof override.enabled === "boolean") {
    next.enabled = override.enabled;
  }
  if (typeof override.mode === "string" && override.mode.trim()) {
    next.mode = override.mode.trim();
  }
  if (override.capabilities_grant) {
    next.capabilities_grant = normalizeGrant(override.capabilities_grant);
  }
  if (override.timeout_ms) {
    const entries = Object.entries(override.timeout_ms).filter(([, value]) => Number.isInteger(value) && value > 0);
    if (entries.length > 0) {
      next.timeout_ms = Object.fromEntries(entries);
    }
  }
  if (typeof override.pool_size === "number" && Number.isInteger(override.pool_size) && override.pool_size > 0) {
    next.pool_size = override.pool_size;
  }
  return next;
}

function normalizeDraftValue(draft: ProfileDraft): ProfileDraft {
  const normalizedOverrides: Record<string, PluginProfileOverride> = {};
  for (const [pluginName, override] of Object.entries(draft.pluginOverrides)) {
    const normalized = normalizeOverride(override);
    if (Object.keys(normalized).length > 0) {
      normalizedOverrides[pluginName] = normalized;
    }
  }
  return {
    pluginOrder: Array.from(new Set(draft.pluginOrder)),
    pluginOverrides: normalizedOverrides,
  };
}

export function getProfileSummary(inventory: PluginInventoryResponse, profileName: string) {
  return inventory.profiles.find((profile) => profile.name === profileName) ?? null;
}

export function buildBaseProfileDraft(inventory: PluginInventoryResponse, profileName: string): ProfileDraft {
  const profile = getProfileSummary(inventory, profileName);
  const pluginOverrides: Record<string, PluginProfileOverride> = {};

  for (const plugin of inventory.plugins) {
    const override = plugin.profiles[profileName]?.override;
    if (override && Object.keys(normalizeOverride(override)).length > 0) {
      pluginOverrides[plugin.name] = normalizeOverride(override);
    }
  }

  return normalizeDraftValue({
    pluginOrder: profile?.pluginOrder ?? [],
    pluginOverrides,
  });
}

export function profileDraftEquals(a: ProfileDraft, b: ProfileDraft): boolean {
  return JSON.stringify(normalizeDraftValue(a)) === JSON.stringify(normalizeDraftValue(b));
}

export function resolveProfileDraft(
  inventory: PluginInventoryResponse,
  profileName: string,
  draft: ProfileDraft | null | undefined,
): ProfileDraft {
  return normalizeDraftValue(draft ?? buildBaseProfileDraft(inventory, profileName));
}

export function resolveWorkingState(
  plugin: PluginInventoryItem,
  profileName: string,
  draft: ProfileDraft,
): PluginWorkingState {
  const profileState = plugin.profiles[profileName];
  const position = draft.pluginOrder.indexOf(plugin.name);
  const listed = position >= 0;
  const override = normalizeOverride(draft.pluginOverrides[plugin.name]);
  const effectiveCapabilitiesGrant = {
    can_patch: override.capabilities_grant?.can_patch ?? profileState?.effectiveCapabilitiesGrant?.can_patch ?? false,
    can_block: override.capabilities_grant?.can_block ?? profileState?.effectiveCapabilitiesGrant?.can_block ?? false,
  };
  const effectiveMode = override.mode ?? profileState?.effectiveMode ?? "observe";
  const effectivePoolSize = override.pool_size ?? profileState?.effectivePoolSize ?? 1;
  const effectiveTimeoutMs = override.timeout_ms ?? profileState?.effectiveTimeoutMs ?? {};
  const requiresReview = effectiveMode !== "observe" || effectiveCapabilitiesGrant.can_patch || effectiveCapabilitiesGrant.can_block;
  const hasRememberedSettings = Object.keys(override).length > 0;

  return {
    listed,
    enabled: listed && (override.enabled ?? profileState?.enabled ?? true) && plugin.validation.status !== "error",
    position: listed ? position : null,
    override,
    effectiveMode,
    effectiveCapabilitiesGrant,
    effectivePoolSize,
    effectiveTimeoutMs,
    requiresReview,
    hasRememberedSettings,
  };
}

function matchesStateFilter(row: PluginRow, filter: PluginStateFilter): boolean {
  if (filter === "all") {
    return true;
  }
  if (filter === "enabled") {
    return row.working.enabled;
  }
  if (filter === "attention") {
    return row.stateKind === "attention";
  }
  return !row.working.enabled && row.stateKind === "disabled";
}

function matchesCapabilityFilter(row: PluginRow, filter: PluginListFilters["capability"]): boolean {
  if (filter === "all") {
    return true;
  }
  if (filter === "canPatch") {
    return row.plugin.declaredCapabilities.canPatch;
  }
  return row.plugin.declaredCapabilities.canBlock;
}

function matchesHealthFilter(row: PluginRow, filter: PluginHealthFilter): boolean {
  if (filter === "all") {
    return true;
  }
  return row.plugin.validation.status === filter;
}

function matchesSearch(row: PluginRow, search: string): boolean {
  if (!search.trim()) {
    return true;
  }
  const tags = Array.isArray(row.plugin.metadata.tags) ? row.plugin.metadata.tags.join(" ") : "";
  const haystack = [
    row.plugin.name,
    row.plugin.displayName,
    row.plugin.description,
    tags,
  ]
    .join(" ")
    .toLowerCase();
  return haystack.includes(search.trim().toLowerCase());
}

function sortRows(a: PluginRow, b: PluginRow): number {
  if (a.working.enabled !== b.working.enabled) {
    return a.working.enabled ? -1 : 1;
  }
  if (a.working.enabled && b.working.enabled) {
    return (a.working.position ?? Number.MAX_SAFE_INTEGER) - (b.working.position ?? Number.MAX_SAFE_INTEGER);
  }
  const priority = (status: PluginValidationStatus) => {
    if (status === "error") {
      return 0;
    }
    if (status === "warn") {
      return 1;
    }
    return 2;
  };
  if (priority(a.plugin.validation.status) !== priority(b.plugin.validation.status)) {
    return priority(a.plugin.validation.status) - priority(b.plugin.validation.status);
  }
  return a.plugin.displayName.localeCompare(b.plugin.displayName, undefined, { sensitivity: "base" });
}

export function buildPluginRows(
  inventory: PluginInventoryResponse,
  profileName: string,
  draft: ProfileDraft,
  filters: PluginListFilters,
): PluginRow[] {
  return inventory.plugins
    .map((plugin) => {
      const working = resolveWorkingState(plugin, profileName, draft);
      const stateKind = working.enabled
        ? "enabled"
        : plugin.validation.status !== "ok" || plugin.sourceKind === "missing"
          ? "attention"
          : "disabled";
      return {
        plugin,
        working,
        stateKind,
        usageLabel: `${plugin.stats.calls}/${plugin.stats.errors}`,
      } satisfies PluginRow;
    })
    .filter((row) => matchesSearch(row, filters.search))
    .filter((row) => matchesStateFilter(row, filters.state))
    .filter((row) => matchesCapabilityFilter(row, filters.capability))
    .filter((row) => matchesHealthFilter(row, filters.health))
    .sort(sortRows);
}

function updateOverride(draft: ProfileDraft, pluginName: string, nextOverride: PluginProfileOverride): ProfileDraft {
  return normalizeDraftValue({
    pluginOrder: draft.pluginOrder,
    pluginOverrides: {
      ...draft.pluginOverrides,
      [pluginName]: nextOverride,
    },
  });
}

export function createSafeEnableDraft(
  inventory: PluginInventoryResponse,
  profileName: string,
  draft: ProfileDraft,
  pluginName: string,
): ProfileDraft {
  const plugin = inventory.plugins.find((item) => item.name === pluginName);
  if (!plugin) {
    return draft;
  }
  const nextOrder = draft.pluginOrder.includes(pluginName) ? [...draft.pluginOrder] : [...draft.pluginOrder, pluginName];
  const currentOverride = normalizeOverride(draft.pluginOverrides[pluginName]);
  return updateOverride(
    {
      ...draft,
      pluginOrder: nextOrder,
    },
    pluginName,
    {
      ...currentOverride,
      enabled: true,
      mode: "observe",
      capabilities_grant: {
        can_patch: false,
        can_block: false,
      },
    },
  );
}

export function createDisableDraft(draft: ProfileDraft, pluginName: string): ProfileDraft {
  return normalizeDraftValue({
    pluginOrder: draft.pluginOrder.filter((item) => item !== pluginName),
    pluginOverrides: draft.pluginOverrides,
  });
}

export function createMoveDraft(draft: ProfileDraft, pluginName: string, delta: -1 | 1): ProfileDraft {
  const index = draft.pluginOrder.indexOf(pluginName);
  if (index < 0) {
    return draft;
  }
  const targetIndex = index + delta;
  if (targetIndex < 0 || targetIndex >= draft.pluginOrder.length) {
    return draft;
  }
  const nextOrder = [...draft.pluginOrder];
  [nextOrder[index], nextOrder[targetIndex]] = [nextOrder[targetIndex], nextOrder[index]];
  return normalizeDraftValue({
    pluginOrder: nextOrder,
    pluginOverrides: draft.pluginOverrides,
  });
}

export function createPluginSettingsDraft(
  draft: ProfileDraft,
  pluginName: string,
  update: PluginProfileOverride,
): ProfileDraft {
  const current = normalizeOverride(draft.pluginOverrides[pluginName]);
  return updateOverride(draft, pluginName, {
    ...current,
    ...update,
  });
}

export function resetPluginFilters(): PluginListFilters {
  return { ...DEFAULT_PLUGIN_FILTERS };
}

export function countRows(rows: PluginRow[]) {
  return rows.reduce(
    (summary, row) => {
      summary.total += 1;
      if (row.working.enabled) {
        summary.enabled += 1;
      }
      if (row.stateKind === "attention") {
        summary.attention += 1;
      }
      return summary;
    },
    { total: 0, enabled: 0, attention: 0 },
  );
}

export function clearSelectionFilters(filters: PluginListFilters): PluginListFilters {
  if (
    !filters.search
    && filters.state === "all"
    && filters.capability === "all"
    && filters.health === "all"
  ) {
    return filters;
  }
  return resetPluginFilters();
}

export function copyDraft(draft: ProfileDraft): ProfileDraft {
  return cloneJson(normalizeDraftValue(draft));
}
