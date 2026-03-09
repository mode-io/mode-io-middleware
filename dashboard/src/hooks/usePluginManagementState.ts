import { useCallback, useEffect, useMemo, useState } from "react";

import { ApiError, fetchJson, putJson } from "../api";
import {
  buildBaseProfileDraft,
  buildPluginRows,
  clearSelectionFilters,
  copyDraft,
  countRows,
  createDisableDraft,
  createMoveDraft,
  createPluginSettingsDraft,
  createSafeEnableDraft,
  DEFAULT_PLUGIN_FILTERS,
  profileDraftEquals,
  resolveProfileDraft,
  resolveWorkingState,
  type ProfileDraft,
} from "../pluginManagement";
import type {
  Locale,
  PluginInventoryItem,
  PluginInventoryResponse,
  PluginListFilters,
  PluginProfileOverride,
  PluginUpdateResponse,
} from "../types";

function localizedErrorMessage(error: unknown, locale: Locale, fallback: string): string {
  if (error instanceof ApiError) {
    return error.message;
  }
  if (error instanceof Error && error.message) {
    return error.message;
  }
  return fallback;
}

function updateDraftMap(
  current: Record<string, ProfileDraft>,
  inventory: PluginInventoryResponse,
  profileName: string,
  nextDraft: ProfileDraft,
): Record<string, ProfileDraft> {
  const normalized = resolveProfileDraft(inventory, profileName, nextDraft);
  const base = buildBaseProfileDraft(inventory, profileName);
  if (profileDraftEquals(normalized, base)) {
    const next = { ...current };
    delete next[profileName];
    return next;
  }
  return {
    ...current,
    [profileName]: copyDraft(normalized),
  };
}

export function usePluginManagementState(locale: Locale) {
  const [inventory, setInventory] = useState<PluginInventoryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedProfile, setSelectedProfile] = useState<string>("");
  const [selectedPluginName, setSelectedPluginName] = useState<string | null>(null);
  const [filters, setFilters] = useState<PluginListFilters>(DEFAULT_PLUGIN_FILTERS);
  const [drafts, setDrafts] = useState<Record<string, ProfileDraft>>({});
  const [saving, setSaving] = useState(false);
  const [pendingActionPlugin, setPendingActionPlugin] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const response = await fetchJson<PluginInventoryResponse>("/modeio/api/plugins");
      setInventory(response);
      setError(null);
    } catch (caught) {
      setError(
        localizedErrorMessage(
          caught,
          locale,
          locale === "zh" ? "加载插件目录失败。" : "Failed to load plugin catalog.",
        ),
      );
    } finally {
      setLoading(false);
    }
  }, [locale]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (!inventory) {
      return;
    }
    const availableProfiles = inventory.profiles.map((profile) => profile.name);
    if (availableProfiles.length === 0) {
      setSelectedProfile("");
      return;
    }
    setSelectedProfile((current) => {
      if (current && availableProfiles.includes(current)) {
        return current;
      }
      return inventory.runtime.defaultProfile || availableProfiles[0];
    });
  }, [inventory]);

  const activeDraft = useMemo(() => {
    if (!inventory || !selectedProfile) {
      return null;
    }
    return resolveProfileDraft(inventory, selectedProfile, drafts[selectedProfile]);
  }, [drafts, inventory, selectedProfile]);

  const allRows = useMemo(() => {
    if (!inventory || !selectedProfile || !activeDraft) {
      return [];
    }
    return buildPluginRows(inventory, selectedProfile, activeDraft, filters);
  }, [activeDraft, filters, inventory, selectedProfile]);

  const unfilteredRows = useMemo(() => {
    if (!inventory || !selectedProfile || !activeDraft) {
      return [];
    }
    return buildPluginRows(inventory, selectedProfile, activeDraft, { ...DEFAULT_PLUGIN_FILTERS });
  }, [activeDraft, inventory, selectedProfile]);

  useEffect(() => {
    if (allRows.length === 0) {
      setSelectedPluginName(null);
      return;
    }
    setSelectedPluginName((current) => {
      if (current && allRows.some((row) => row.plugin.name === current)) {
        return current;
      }
      return allRows[0]?.plugin.name ?? null;
    });
  }, [allRows]);

  const selectedPlugin = useMemo(() => {
    const selectedRow = allRows.find((row) => row.plugin.name === selectedPluginName);
    return selectedRow ?? null;
  }, [allRows, selectedPluginName]);

  const counts = useMemo(() => countRows(unfilteredRows), [unfilteredRows]);
  const currentDraftDirty = useMemo(() => {
    if (!inventory || !selectedProfile || !activeDraft) {
      return false;
    }
    return !profileDraftEquals(activeDraft, buildBaseProfileDraft(inventory, selectedProfile));
  }, [activeDraft, inventory, selectedProfile]);

  const commitDraft = useCallback(
    async (profileName: string, nextDraft: ProfileDraft, actionPluginName?: string) => {
      if (!inventory) {
        return;
      }
      setSaving(true);
      setPendingActionPlugin(actionPluginName ?? null);
      setDrafts((current) => updateDraftMap(current, inventory, profileName, nextDraft));
      try {
        await putJson<PluginUpdateResponse>(`/modeio/api/profiles/${profileName}/plugins`, {
          expectedGeneration: inventory.runtime.generation,
          pluginOrder: nextDraft.pluginOrder,
          pluginOverrides: nextDraft.pluginOverrides,
        });
        setDrafts((current) => {
          const next = { ...current };
          delete next[profileName];
          return next;
        });
        await refresh();
      } catch (caught) {
        if (caught instanceof ApiError && caught.code === "MODEIO_GENERATION_CONFLICT") {
          await refresh();
          setError(locale === "zh" ? "插件配置已变更，请检查最新状态后重试。" : "Plugin config changed elsewhere. Review the latest state and save again.");
        } else {
          setError(
            localizedErrorMessage(
              caught,
              locale,
              locale === "zh" ? "保存插件设置失败。" : "Failed to save plugin settings.",
            ),
          );
        }
      } finally {
        setSaving(false);
        setPendingActionPlugin(null);
      }
    },
    [inventory, locale, refresh],
  );

  const patchDraft = useCallback(
    (updater: (draft: ProfileDraft) => ProfileDraft) => {
      if (!inventory || !selectedProfile || !activeDraft) {
        return;
      }
      const nextDraft = updater(activeDraft);
      setDrafts((current) => updateDraftMap(current, inventory, selectedProfile, nextDraft));
      setError(null);
    },
    [activeDraft, inventory, selectedProfile],
  );

  const enablePluginSafely = useCallback(
    async (pluginName: string) => {
      if (!inventory || !selectedProfile || !activeDraft) {
        return;
      }
      const nextDraft = createSafeEnableDraft(inventory, selectedProfile, activeDraft, pluginName);
      await commitDraft(selectedProfile, nextDraft, pluginName);
    },
    [activeDraft, commitDraft, inventory, selectedProfile],
  );

  const disablePlugin = useCallback(
    async (pluginName: string) => {
      if (!selectedProfile || !activeDraft) {
        return;
      }
      const nextDraft = createDisableDraft(activeDraft, pluginName);
      await commitDraft(selectedProfile, nextDraft, pluginName);
    },
    [activeDraft, commitDraft, selectedProfile],
  );

  const movePlugin = useCallback(
    async (pluginName: string, direction: -1 | 1) => {
      if (!selectedProfile || !activeDraft) {
        return;
      }
      const nextDraft = createMoveDraft(activeDraft, pluginName, direction);
      await commitDraft(selectedProfile, nextDraft, pluginName);
    },
    [activeDraft, commitDraft, selectedProfile],
  );

  const updateSelectedPluginSettings = useCallback(
    (update: PluginProfileOverride) => {
      if (!selectedPluginName) {
        return;
      }
      patchDraft((draft) => createPluginSettingsDraft(draft, selectedPluginName, update));
    },
    [patchDraft, selectedPluginName],
  );

  const discardChanges = useCallback(() => {
    if (!selectedProfile) {
      return;
    }
    setDrafts((current) => {
      const next = { ...current };
      delete next[selectedProfile];
      return next;
    });
  }, [selectedProfile]);

  const saveChanges = useCallback(async () => {
    if (!selectedProfile || !activeDraft || !currentDraftDirty) {
      return;
    }
    await commitDraft(selectedProfile, activeDraft);
  }, [activeDraft, commitDraft, currentDraftDirty, selectedProfile]);

  const focusPlugin = useCallback((pluginName: string, profileName: string) => {
    setSelectedProfile(profileName);
    setSelectedPluginName(pluginName);
    setFilters((current) => clearSelectionFilters(current));
  }, []);

  const profileOptions = inventory?.profiles ?? [];
  const readOnly = inventory ? !inventory.runtime.configWritable : false;
  const selectedPluginRecord: PluginInventoryItem | null = selectedPlugin?.plugin ?? null;
  const selectedWorkingState = selectedPluginRecord && selectedProfile && activeDraft
    ? resolveWorkingState(selectedPluginRecord, selectedProfile, activeDraft)
    : null;

  return {
    inventory,
    loading,
    error,
    selectedProfile,
    setSelectedProfile,
    selectedPluginName,
    setSelectedPluginName,
    filters,
    setFilters,
    rows: allRows,
    counts,
    readOnly,
    warnings: inventory?.warnings ?? [],
    runtime: inventory?.runtime ?? null,
    profiles: profileOptions,
    selectedPlugin: selectedPluginRecord,
    selectedWorkingState,
    dirty: currentDraftDirty,
    saving,
    pendingActionPlugin,
    refresh,
    focusPlugin,
    enablePluginSafely,
    disablePlugin,
    movePlugin,
    updateSelectedPluginSettings,
    discardChanges,
    saveChanges,
  };
}
