import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { fetchJson, putJson } from "../../api";
import { modeioAdminRoutes } from "../../apiRoutes";
import type { PluginInventoryResponse, PluginProfileOverride, PluginUpdateResponse } from "../../types";

export const PLUGIN_INVENTORY_QUERY_KEY = ["plugins", "inventory"] as const;

export async function fetchPluginInventory() {
  return fetchJson<PluginInventoryResponse>(modeioAdminRoutes.plugins);
}

export interface UpdateProfilePluginsInput {
  profileName: string;
  expectedGeneration: number;
  pluginOrder: string[];
  pluginOverrides: Record<string, PluginProfileOverride>;
}

export async function updateProfilePlugins(payload: UpdateProfilePluginsInput) {
  return putJson<PluginUpdateResponse>(modeioAdminRoutes.profilePlugins(payload.profileName), {
    expectedGeneration: payload.expectedGeneration,
    pluginOrder: payload.pluginOrder,
    pluginOverrides: payload.pluginOverrides,
  });
}

export function usePluginInventoryQuery() {
  return useQuery({
    queryKey: PLUGIN_INVENTORY_QUERY_KEY,
    queryFn: fetchPluginInventory,
  });
}

export function useUpdateProfilePluginsMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (payload: UpdateProfilePluginsInput) => {
      await updateProfilePlugins(payload);
      await queryClient.invalidateQueries({ queryKey: PLUGIN_INVENTORY_QUERY_KEY });
      return queryClient.fetchQuery({
        queryKey: PLUGIN_INVENTORY_QUERY_KEY,
        queryFn: fetchPluginInventory,
      });
    },
  });
}
