import type { PluginInventoryResponse, PluginListFilters } from "../../types";
import type { ProfileDraft } from "./drafts";

export type PendingIntent =
  | { type: "switch-profile"; profileName: string }
  | { type: "focus-plugin"; profileName: string; pluginName: string };

export interface PluginMutationState {
  status: "idle" | "pending" | "error" | "conflict";
  kind: "toggle" | "reorder" | "save" | null;
  pluginName: string | null;
  message: string | null;
}

export interface PluginWorkspaceState {
  selectedProfile: string;
  selectedPluginName: string | null;
  filters: PluginListFilters;
  draft: ProfileDraft | null;
  draftProfile: string | null;
  pendingIntent: PendingIntent | null;
  mutation: PluginMutationState;
}

export type PluginWorkspaceAction =
  | {
      type: "inventory-synced";
      inventory: PluginInventoryResponse;
      defaultFilters: PluginListFilters;
    }
  | { type: "set-search"; search: string }
  | { type: "select-plugin"; pluginName: string | null }
  | { type: "select-profile"; profileName: string }
  | { type: "set-pending-intent"; pendingIntent: PendingIntent | null }
  | {
      type: "set-draft";
      profileName: string;
      draft: ProfileDraft | null;
    }
  | { type: "clear-draft" }
  | { type: "mutation-started"; kind: "toggle" | "reorder" | "save"; pluginName?: string | null }
  | { type: "mutation-succeeded" }
  | { type: "mutation-failed"; message: string }
  | { type: "mutation-conflict"; message: string };

export const initialPluginWorkspaceState: PluginWorkspaceState = {
  selectedProfile: "",
  selectedPluginName: null,
  filters: { search: "" },
  draft: null,
  draftProfile: null,
  pendingIntent: null,
  mutation: {
    status: "idle",
    kind: null,
    pluginName: null,
    message: null,
  },
};

function syncSelectedProfile(currentProfile: string, inventory: PluginInventoryResponse): string {
  const availableProfiles = inventory.profiles.map((profile) => profile.name);
  if (currentProfile && availableProfiles.includes(currentProfile)) {
    return currentProfile;
  }
  return inventory.runtime.defaultProfile || availableProfiles[0] || "";
}

function syncSelectedPlugin(currentPluginName: string | null, inventory: PluginInventoryResponse): string | null {
  if (currentPluginName && inventory.plugins.some((plugin) => plugin.name === currentPluginName)) {
    return currentPluginName;
  }
  return inventory.plugins[0]?.name ?? null;
}

export function pluginWorkspaceReducer(
  state: PluginWorkspaceState,
  action: PluginWorkspaceAction,
): PluginWorkspaceState {
  switch (action.type) {
    case "inventory-synced": {
      const selectedProfile = syncSelectedProfile(state.selectedProfile, action.inventory);
      const selectedPluginName = syncSelectedPlugin(state.selectedPluginName, action.inventory);
      const draftStillValid = state.draftProfile === selectedProfile;

      return {
        ...state,
        selectedProfile,
        selectedPluginName,
        filters: state.filters.search ? state.filters : action.defaultFilters,
        draft: draftStillValid ? state.draft : null,
        draftProfile: draftStillValid ? state.draftProfile : null,
      };
    }
    case "set-search":
      return {
        ...state,
        filters: { search: action.search },
      };
    case "select-plugin":
      return {
        ...state,
        selectedPluginName: action.pluginName,
      };
    case "select-profile":
      return {
        ...state,
        selectedProfile: action.profileName,
        pendingIntent: null,
        draft: state.draftProfile === action.profileName ? state.draft : null,
        draftProfile: state.draftProfile === action.profileName ? state.draftProfile : null,
      };
    case "set-pending-intent":
      return {
        ...state,
        pendingIntent: action.pendingIntent,
      };
    case "set-draft":
      return {
        ...state,
        draft: action.draft,
        draftProfile: action.draft ? action.profileName : null,
      };
    case "clear-draft":
      return {
        ...state,
        draft: null,
        draftProfile: null,
      };
    case "mutation-started":
      return {
        ...state,
        mutation: {
          status: "pending",
          kind: action.kind,
          pluginName: action.pluginName ?? null,
          message: null,
        },
      };
    case "mutation-succeeded":
      return {
        ...state,
        draft: null,
        draftProfile: null,
        pendingIntent: null,
        mutation: {
          status: "idle",
          kind: null,
          pluginName: null,
          message: null,
        },
      };
    case "mutation-failed":
      return {
        ...state,
        mutation: {
          ...state.mutation,
          status: "error",
          message: action.message,
        },
      };
    case "mutation-conflict":
      return {
        ...state,
        mutation: {
          ...state.mutation,
          status: "conflict",
          message: action.message,
        },
      };
    default:
      return state;
  }
}
