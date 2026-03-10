import { useEffect, useRef } from "react";

import { useQueryClient } from "@tanstack/react-query";

import { modeioMonitoringRoutes } from "../../apiRoutes";
import {
  buildDetailQueryKey,
  TRAFFIC_EVENTS_QUERY_KEY,
  TRAFFIC_STATS_QUERY_KEY,
} from "./queries";

export function useTrafficLiveInvalidation(selectedRequestId: string | null) {
  const queryClient = useQueryClient();
  const refreshTimer = useRef<number | null>(null);
  const selectedRequestIdRef = useRef<string | null>(selectedRequestId);

  useEffect(() => {
    selectedRequestIdRef.current = selectedRequestId;
  }, [selectedRequestId]);

  useEffect(() => {
    const source = new EventSource(modeioMonitoringRoutes.liveEvents);

    const scheduleRefresh = () => {
      if (refreshTimer.current !== null) {
        window.clearTimeout(refreshTimer.current);
      }
      refreshTimer.current = window.setTimeout(() => {
        void queryClient.invalidateQueries({ queryKey: [TRAFFIC_STATS_QUERY_KEY] });
        void queryClient.invalidateQueries({ queryKey: [TRAFFIC_EVENTS_QUERY_KEY] });
        if (selectedRequestIdRef.current) {
          void queryClient.invalidateQueries({
            queryKey: buildDetailQueryKey(selectedRequestIdRef.current),
          });
        }
      }, 150);
    };

    source.addEventListener("trace.completed", scheduleRefresh);
    source.addEventListener("stats.updated", scheduleRefresh);
    source.onerror = () => {
      source.close();
    };

    return () => {
      if (refreshTimer.current !== null) {
        window.clearTimeout(refreshTimer.current);
      }
      source.close();
    };
  }, [queryClient]);
}
