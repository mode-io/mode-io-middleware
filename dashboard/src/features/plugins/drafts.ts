import type {
  PluginCapabilitiesGrant,
  PluginInventoryItem,
  PluginInventoryResponse,
  PluginMode,
  PluginProfileOverride,
} from "../../types";

export interface ProfileDraft {
  pluginOrder: string[];
  pluginOverrides: Record<string, PluginProfileOverride>;
}

function normalizeGrant(grant: Partial<PluginCapabilitiesGrant> | undefined): PluginCapabilitiesGrant {
  return {
    can_patch: Boolean(grant?.can_patch),
    can_block: Boolean(grant?.can_block),
  };
}

export function normalizeOverride(override: PluginProfileOverride | undefined): PluginProfileOverride {
  if (!override) {
    return {};
  }
  const next: PluginProfileOverride = {};
  if (typeof override.enabled === "boolean") {
    next.enabled = override.enabled;
  }
  if (typeof override.mode === "string" && override.mode.trim()) {
    next.mode = override.mode.trim() as PluginMode;
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

export function normalizeDraft(draft: ProfileDraft): ProfileDraft {
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

  return normalizeDraft({
    pluginOrder: profile?.pluginOrder ?? [],
    pluginOverrides,
  });
}

export function profileDraftEquals(a: ProfileDraft, b: ProfileDraft): boolean {
  return JSON.stringify(normalizeDraft(a)) === JSON.stringify(normalizeDraft(b));
}

export function resolveProfileDraft(
  inventory: PluginInventoryResponse,
  profileName: string,
  draft: ProfileDraft | null | undefined,
): ProfileDraft {
  return normalizeDraft(draft ?? buildBaseProfileDraft(inventory, profileName));
}

function updateOverride(
  draft: ProfileDraft,
  pluginName: string,
  nextOverride: PluginProfileOverride,
): ProfileDraft {
  return normalizeDraft({
    pluginOrder: draft.pluginOrder,
    pluginOverrides: {
      ...draft.pluginOverrides,
      [pluginName]: nextOverride,
    },
  });
}

function findPlugin(inventory: PluginInventoryResponse, pluginName: string): PluginInventoryItem | null {
  return inventory.plugins.find((item) => item.name === pluginName) ?? null;
}

export function createSafeEnableDraft(
  inventory: PluginInventoryResponse,
  draft: ProfileDraft,
  pluginName: string,
): ProfileDraft {
  const plugin = findPlugin(inventory, pluginName);
  if (!plugin) {
    return draft;
  }
  const nextOrder = draft.pluginOrder.includes(pluginName)
    ? [...draft.pluginOrder]
    : [...draft.pluginOrder, pluginName];
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
  return normalizeDraft({
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
  return normalizeDraft({
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
