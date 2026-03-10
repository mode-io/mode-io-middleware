import { useQuery } from "@tanstack/react-query";

import { fetchJson } from "../../api";
import { modeioMonitoringRoutes } from "../../apiRoutes";
import { directionFilterToLifecycles, resultFilterToQueryParams } from "../../monitorFilters";
import type { EventDetail, EventsResponse, MonitorFilters, StatsSnapshot } from "../../types";

const EVENTS_LIMIT = 50;

export const TRAFFIC_EVENTS_QUERY_KEY = "traffic-events";
export const TRAFFIC_STATS_QUERY_KEY = "traffic-stats";
export const TRAFFIC_DETAIL_QUERY_KEY = "traffic-detail";

export function buildEventsUrl(filters: MonitorFilters): string {
  const params = new URLSearchParams({ limit: String(EVENTS_LIMIT) });
  const resultParams = resultFilterToQueryParams(filters.result);
  if (resultParams.status) {
    params.set("status", resultParams.status);
  }
  if (resultParams.impact) {
    params.set("impact", resultParams.impact);
  }
  if (filters.clientName !== "all") {
    params.set("client", filters.clientName);
  }
  const lifecycles = directionFilterToLifecycles(filters.direction);
  if (lifecycles && lifecycles.length === 1) {
    params.set("lifecycle", lifecycles[0]);
  }
  return `${modeioMonitoringRoutes.events}?${params.toString()}`;
}

export function buildEventsQueryKey(filters: MonitorFilters) {
  return [TRAFFIC_EVENTS_QUERY_KEY, filters.result, filters.clientName, filters.direction] as const;
}

export function buildDetailQueryKey(requestId: string | null) {
  return [TRAFFIC_DETAIL_QUERY_KEY, requestId] as const;
}

export function useTrafficEventsQuery(filters: MonitorFilters) {
  return useQuery({
    queryKey: buildEventsQueryKey(filters),
    queryFn: () => fetchJson<EventsResponse>(buildEventsUrl(filters)),
  });
}

export function useTrafficStatsQuery() {
  return useQuery({
    queryKey: [TRAFFIC_STATS_QUERY_KEY],
    queryFn: () => fetchJson<StatsSnapshot>(modeioMonitoringRoutes.stats),
  });
}

export function useTrafficDetailQuery(requestId: string | null, enabled: boolean) {
  return useQuery({
    queryKey: buildDetailQueryKey(requestId),
    queryFn: () => fetchJson<EventDetail>(modeioMonitoringRoutes.eventDetail(String(requestId))),
    enabled,
  });
}

export function isEmptyStats(stats: StatsSnapshot | undefined): boolean {
  if (!stats) {
    return false;
  }
  return stats.completedRecords === 0 && stats.inFlightRecords === 0;
}
