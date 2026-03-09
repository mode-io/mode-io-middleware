import type {
  PluginCapabilitiesGrant,
  PluginInventoryItem,
  PluginInventoryResponse,
  PluginListFilters,
  PluginMode,
  PluginProfileState,
  PluginSourceKind,
  PluginValidationStatus,
} from "../../types";
import {
  normalizeOverride,
  type ProfileDraft,
} from "./drafts";

export interface PluginWorkingState {
  listed: boolean;
  enabled: boolean;
  position: number | null;
  override: PluginProfileState["override"];
  effectiveMode: PluginMode;
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
}

export interface PluginRowGroups {
  enabled: PluginRow[];
  attention: PluginRow[];
  available: PluginRow[];
}

export const DEFAULT_PLUGIN_FILTERS: PluginListFilters = {
  search: "",
};

export function clearSelectionFilters(filters: PluginListFilters): PluginListFilters {
  if (!filters.search) {
    return filters;
  }
  return { ...DEFAULT_PLUGIN_FILTERS };
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
  const effectiveMode = (override.mode ?? profileState?.effectiveMode ?? "observe") as PluginMode;
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

function matchesSearch(row: PluginRow, search: string): boolean {
  if (!search.trim()) {
    return true;
  }
  const tags = Array.isArray(row.plugin.metadata.tags) ? row.plugin.metadata.tags.join(" ") : "";
  const haystack = [row.plugin.name, row.plugin.displayName, row.plugin.description, tags]
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

  const validationRank: Record<PluginValidationStatus, number> = {
    error: 0,
    warn: 1,
    ok: 2,
  };
  if (validationRank[a.plugin.validation.status] !== validationRank[b.plugin.validation.status]) {
    return validationRank[a.plugin.validation.status] - validationRank[b.plugin.validation.status];
  }
  return a.plugin.displayName.localeCompare(b.plugin.displayName, undefined, { sensitivity: "base" });
}

function deriveRowStateKind(working: PluginWorkingState, validationStatus: PluginValidationStatus, sourceKind: PluginSourceKind): PluginRow["stateKind"] {
  if (working.enabled) {
    return "enabled";
  }
  if (validationStatus !== "ok" || sourceKind === "missing") {
    return "attention";
  }
  return "disabled";
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
      return {
        plugin,
        working,
        stateKind: deriveRowStateKind(working, plugin.validation.status, plugin.sourceKind),
      } satisfies PluginRow;
    })
    .filter((row) => matchesSearch(row, filters.search))
    .sort(sortRows);
}

export function groupPluginRows(rows: PluginRow[]): PluginRowGroups {
  return rows.reduce<PluginRowGroups>(
    (groups, row) => {
      if (row.working.enabled) {
        groups.enabled.push(row);
      } else if (row.stateKind === "attention") {
        groups.attention.push(row);
      } else {
        groups.available.push(row);
      }
      return groups;
    },
    { enabled: [], attention: [], available: [] },
  );
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

export function selectPluginRecord(
  inventory: PluginInventoryResponse | null,
  selectedPluginName: string | null,
  visibleRows: PluginRow[],
): PluginInventoryItem | null {
  if (!inventory) {
    return null;
  }
  const explicitSelection = selectedPluginName
    ? inventory.plugins.find((plugin) => plugin.name === selectedPluginName) ?? null
    : null;
  return explicitSelection ?? visibleRows[0]?.plugin ?? inventory.plugins[0] ?? null;
}

export function isSelectionHiddenByFilter(selectedPlugin: PluginInventoryItem | null, visibleRows: PluginRow[]): boolean {
  if (!selectedPlugin) {
    return false;
  }
  return !visibleRows.some((row) => row.plugin.name === selectedPlugin.name);
}
