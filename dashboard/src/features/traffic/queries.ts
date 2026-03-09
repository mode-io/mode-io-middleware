import { useQuery } from "@tanstack/react-query";

import { fetchJson } from "../../api";
import type { EventDetail, EventsResponse, MonitorFilters, StatsSnapshot } from "../../types";

const EVENTS_LIMIT = 50;

export const TRAFFIC_EVENTS_QUERY_KEY = "traffic-events";
export const TRAFFIC_STATS_QUERY_KEY = "traffic-stats";
export const TRAFFIC_DETAIL_QUERY_KEY = "traffic-detail";

export function buildEventsUrl(filters: MonitorFilters): string {
  const params = new URLSearchParams({ limit: String(EVENTS_LIMIT) });
  if (filters.status !== "all") {
    params.set("status", filters.status);
  }
  if (filters.clientName !== "all") {
    params.set("client", filters.clientName);
  }
  if (filters.impact !== "all") {
    params.set("impact", filters.impact);
  }
  if (filters.lifecycle !== "all") {
    params.set("lifecycle", filters.lifecycle);
  }
  return `/modeio/api/events?${params.toString()}`;
}

export function buildEventsQueryKey(filters: MonitorFilters) {
  return [TRAFFIC_EVENTS_QUERY_KEY, filters.status, filters.clientName, filters.impact, filters.lifecycle] as const;
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
    queryFn: () => fetchJson<StatsSnapshot>("/modeio/api/stats"),
  });
}

export function useTrafficDetailQuery(requestId: string | null, enabled: boolean) {
  return useQuery({
    queryKey: buildDetailQueryKey(requestId),
    queryFn: () => fetchJson<EventDetail>(`/modeio/api/events/${requestId}`),
    enabled,
  });
}

export function isEmptyStats(stats: StatsSnapshot | undefined): boolean {
  if (!stats) {
    return false;
  }
  return stats.completedRecords === 0 && stats.inFlightRecords === 0;
}
