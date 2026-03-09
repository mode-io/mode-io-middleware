import { useCallback, useEffect, useMemo, useReducer, type Dispatch } from "react";

import { ApiError } from "../../api";
import { formatLocalizedError } from "../../lib/errors";
import type {
  Locale,
  PluginInventoryItem,
  PluginInventoryResponse,
  PluginProfileOverride,
  PluginProfileSummary,
  PluginRuntimeSummary,
} from "../../types";
import {
  buildBaseProfileDraft,
  createDisableDraft,
  createMoveDraft,
  createPluginSettingsDraft,
  createSafeEnableDraft,
  profileDraftEquals,
  resolveProfileDraft,
  type ProfileDraft,
} from "./drafts";
import {
  usePluginInventoryQuery,
  useUpdateProfilePluginsMutation,
} from "./queries";
import {
  initialPluginWorkspaceState,
  pluginWorkspaceReducer,
  type PendingIntent,
  type PluginWorkspaceAction,
} from "./reducer";
import {
  buildPluginRows,
  clearSelectionFilters,
  countRows,
  DEFAULT_PLUGIN_FILTERS,
  isSelectionHiddenByFilter,
  resolveWorkingState,
  selectPluginRecord,
} from "./selectors";

function applyIntent(intent: PendingIntent, dispatch: Dispatch<PluginWorkspaceAction>) {
  if (intent.type === "switch-profile") {
    dispatch({ type: "select-profile", profileName: intent.profileName });
    return;
  }
  dispatch({ type: "select-profile", profileName: intent.profileName });
  dispatch({ type: "set-search", search: "" });
  dispatch({ type: "select-plugin", pluginName: intent.pluginName });
}

export interface PluginWorkspaceController {
  inventory: PluginInventoryResponse | null;
  loading: boolean;
  error: string | null;
  selectedProfile: string;
  setSelectedProfile: (profile: string) => void;
  selectedPluginName: string | null;
  setSelectedPluginName: (pluginName: string | null) => void;
  filters: { search: string };
  setFilters: (filters: { search: string }) => void;
  rows: ReturnType<typeof buildPluginRows>;
  counts: ReturnType<typeof countRows>;
  readOnly: boolean;
  warnings: string[];
  runtime: PluginRuntimeSummary | null;
  profiles: PluginProfileSummary[];
  selectedPlugin: PluginInventoryItem | null;
  selectedWorkingState: ReturnType<typeof resolveWorkingState> | null;
  dirty: boolean;
  saving: boolean;
  quickActionsDisabled: boolean;
  pendingActionPlugin: string | null;
  pendingIntent: PendingIntent | null;
  selectionHiddenByFilter: boolean;
  refresh: () => Promise<void>;
  focusPlugin: (pluginName: string, profileName: string) => void;
  enablePluginSafely: (pluginName: string) => Promise<void>;
  disablePlugin: (pluginName: string) => Promise<void>;
  movePlugin: (pluginName: string, direction: -1 | 1) => Promise<void>;
  updateSelectedPluginSettings: (update: PluginProfileOverride) => void;
  discardChanges: () => void;
  saveChanges: () => Promise<boolean>;
  confirmPendingIntent: (strategy: "save" | "discard") => Promise<void>;
  cancelPendingIntent: () => void;
}

export function usePluginManagementState(locale: Locale): PluginWorkspaceController {
  const [state, dispatch] = useReducer(pluginWorkspaceReducer, initialPluginWorkspaceState);
  const inventoryQuery = usePluginInventoryQuery();
  const updateMutation = useUpdateProfilePluginsMutation();

  useEffect(() => {
    if (!inventoryQuery.data) {
      return;
    }
    dispatch({
      type: "inventory-synced",
      inventory: inventoryQuery.data,
      defaultFilters: DEFAULT_PLUGIN_FILTERS,
    });
  }, [inventoryQuery.data]);

  const inventory = inventoryQuery.data ?? null;
  const activeProfile = state.selectedProfile || inventory?.runtime.defaultProfile || inventory?.profiles[0]?.name || "";
  const baseDraft = useMemo(() => {
    if (!inventory || !activeProfile) {
      return null;
    }
    return buildBaseProfileDraft(inventory, activeProfile);
  }, [activeProfile, inventory]);

  const effectiveDraft = useMemo(() => {
    if (!inventory || !activeProfile || !baseDraft) {
      return null;
    }
    return resolveProfileDraft(
      inventory,
      activeProfile,
      state.draftProfile === activeProfile ? state.draft : null,
    );
  }, [activeProfile, baseDraft, inventory, state.draft, state.draftProfile]);

  const dirty = useMemo(() => {
    if (!baseDraft || !effectiveDraft) {
      return false;
    }
    return !profileDraftEquals(baseDraft, effectiveDraft);
  }, [baseDraft, effectiveDraft]);

  const rows = useMemo(() => {
    if (!inventory || !activeProfile || !effectiveDraft) {
      return [];
    }
    return buildPluginRows(inventory, activeProfile, effectiveDraft, state.filters);
  }, [activeProfile, effectiveDraft, inventory, state.filters]);

  const allRows = useMemo(() => {
    if (!inventory || !activeProfile || !baseDraft) {
      return [];
    }
    return buildPluginRows(inventory, activeProfile, baseDraft, DEFAULT_PLUGIN_FILTERS);
  }, [activeProfile, baseDraft, inventory]);

  const counts = useMemo(() => countRows(allRows), [allRows]);
  const selectedPluginRecord = useMemo(
    () => selectPluginRecord(inventory, state.selectedPluginName, rows),
    [inventory, rows, state.selectedPluginName],
  );
  const selectedPluginName = selectedPluginRecord?.name ?? null;
  const selectionHiddenByFilter = isSelectionHiddenByFilter(selectedPluginRecord, rows);
  const selectedWorkingState = selectedPluginRecord && activeProfile && effectiveDraft
    ? resolveWorkingState(selectedPluginRecord, activeProfile, effectiveDraft)
    : null;

  const readOnly = inventory ? !inventory.runtime.configWritable : false;
  const quickActionsDisabled = readOnly || state.mutation.status === "pending" || dirty;

  const commitDraft = useCallback(
    async (
      profileName: string,
      nextDraft: ProfileDraft,
      options: { kind: "toggle" | "reorder" | "save"; pluginName?: string | null },
    ) => {
      if (!inventory) {
        return false;
      }
      dispatch({ type: "mutation-started", kind: options.kind, pluginName: options.pluginName ?? null });
      try {
        const latestInventory = await updateMutation.mutateAsync({
          profileName,
          expectedGeneration: inventory.runtime.generation,
          pluginOrder: nextDraft.pluginOrder,
          pluginOverrides: nextDraft.pluginOverrides,
        });
        dispatch({
          type: "inventory-synced",
          inventory: latestInventory,
          defaultFilters: DEFAULT_PLUGIN_FILTERS,
        });
        dispatch({ type: "mutation-succeeded" });
        return true;
      } catch (error) {
        if (error instanceof ApiError && error.code === "MODEIO_GENERATION_CONFLICT") {
          await inventoryQuery.refetch();
          dispatch({
            type: "mutation-conflict",
            message: locale === "zh"
              ? "插件配置已变更，请检查最新状态后重试。"
              : "Plugin config changed elsewhere. Review the latest state and save again.",
          });
          return false;
        }
        dispatch({
          type: "mutation-failed",
          message: formatLocalizedError(error, locale, {
            en: "Failed to save plugin settings.",
            zh: "保存插件设置失败。",
          }),
        });
        return false;
      }
    },
    [inventory, inventoryQuery, locale, updateMutation],
  );

  const refresh = useCallback(async () => {
    await inventoryQuery.refetch();
  }, [inventoryQuery]);

  const patchDraft = useCallback((updater: (draft: ProfileDraft) => ProfileDraft) => {
    if (!inventory || !activeProfile || !effectiveDraft) {
      return;
    }
    const nextDraft = updater(effectiveDraft);
    if (baseDraft && profileDraftEquals(baseDraft, nextDraft)) {
      dispatch({ type: "clear-draft" });
      return;
    }
    dispatch({ type: "set-draft", profileName: activeProfile, draft: nextDraft });
  }, [activeProfile, baseDraft, effectiveDraft, inventory]);

  const setSelectedProfile = useCallback((profileName: string) => {
    if (!inventory || !profileName || profileName === activeProfile) {
      return;
    }
    if (dirty) {
      dispatch({ type: "set-pending-intent", pendingIntent: { type: "switch-profile", profileName } });
      return;
    }
    dispatch({ type: "select-profile", profileName });
  }, [activeProfile, dirty, inventory]);

  const setSelectedPluginName = useCallback((pluginName: string | null) => {
    dispatch({ type: "select-plugin", pluginName });
  }, []);

  const setFilters = useCallback((filters: { search: string }) => {
    dispatch({ type: "set-search", search: filters.search });
  }, []);

  const enablePluginSafely = useCallback(async (pluginName: string) => {
    if (!inventory || !baseDraft || !activeProfile || quickActionsDisabled) {
      return;
    }
    const nextDraft = createSafeEnableDraft(inventory, baseDraft, pluginName);
    await commitDraft(activeProfile, nextDraft, { kind: "toggle", pluginName });
  }, [activeProfile, baseDraft, commitDraft, inventory, quickActionsDisabled]);

  const disablePlugin = useCallback(async (pluginName: string) => {
    if (!baseDraft || !activeProfile || quickActionsDisabled) {
      return;
    }
    const nextDraft = createDisableDraft(baseDraft, pluginName);
    await commitDraft(activeProfile, nextDraft, { kind: "toggle", pluginName });
  }, [activeProfile, baseDraft, commitDraft, quickActionsDisabled]);

  const movePlugin = useCallback(async (pluginName: string, direction: -1 | 1) => {
    if (!baseDraft || !activeProfile || quickActionsDisabled) {
      return;
    }
    const nextDraft = createMoveDraft(baseDraft, pluginName, direction);
    await commitDraft(activeProfile, nextDraft, { kind: "reorder", pluginName });
  }, [activeProfile, baseDraft, commitDraft, quickActionsDisabled]);

  const updateSelectedPluginSettings = useCallback((update: PluginProfileOverride) => {
    if (!selectedPluginName) {
      return;
    }
    patchDraft((draft) => createPluginSettingsDraft(draft, selectedPluginName, update));
  }, [patchDraft, selectedPluginName]);

  const discardChanges = useCallback(() => {
    dispatch({ type: "clear-draft" });
  }, []);

  const saveChanges = useCallback(async () => {
    if (!activeProfile || !effectiveDraft || !dirty || readOnly || state.mutation.status === "pending") {
      return false;
    }
    return commitDraft(activeProfile, effectiveDraft, { kind: "save" });
  }, [activeProfile, commitDraft, dirty, effectiveDraft, readOnly, state.mutation.status]);

  const focusPlugin = useCallback((pluginName: string, profileName: string) => {
    const nextIntent: PendingIntent = { type: "focus-plugin", profileName, pluginName };
    if (dirty) {
      dispatch({ type: "set-pending-intent", pendingIntent: nextIntent });
      return;
    }
    applyIntent(nextIntent, dispatch);
    dispatch({ type: "set-search", search: clearSelectionFilters(state.filters).search });
  }, [dirty, state.filters]);

  const confirmPendingIntent = useCallback(async (strategy: "save" | "discard") => {
    if (!state.pendingIntent) {
      return;
    }
    const intent = state.pendingIntent;
    if (strategy === "save") {
      const saved = await saveChanges();
      if (!saved) {
        return;
      }
    } else {
      dispatch({ type: "clear-draft" });
    }
    dispatch({ type: "set-pending-intent", pendingIntent: null });
    applyIntent(intent, dispatch);
  }, [saveChanges, state.pendingIntent]);

  const cancelPendingIntent = useCallback(() => {
    dispatch({ type: "set-pending-intent", pendingIntent: null });
  }, []);

  const error = inventoryQuery.error
    ? formatLocalizedError(inventoryQuery.error, locale, {
        en: "Failed to load plugin catalog.",
        zh: "加载插件目录失败。",
      })
    : state.mutation.message;

  return {
    inventory,
    loading: inventoryQuery.isLoading,
    error,
    selectedProfile: activeProfile,
    setSelectedProfile,
    selectedPluginName,
    setSelectedPluginName,
    filters: state.filters,
    setFilters,
    rows,
    counts,
    readOnly,
    warnings: inventory?.warnings ?? [],
    runtime: inventory?.runtime ?? null,
    profiles: inventory?.profiles ?? [],
    selectedPlugin: selectedPluginRecord,
    selectedWorkingState,
    dirty,
    saving: state.mutation.status === "pending",
    quickActionsDisabled,
    pendingActionPlugin: state.mutation.pluginName,
    pendingIntent: state.pendingIntent,
    selectionHiddenByFilter,
    refresh,
    focusPlugin,
    enablePluginSafely,
    disablePlugin,
    movePlugin,
    updateSelectedPluginSettings,
    discardChanges,
    saveChanges,
    confirmPendingIntent,
    cancelPendingIntent,
  } satisfies PluginWorkspaceController;
}
