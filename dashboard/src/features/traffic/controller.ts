import { useCallback, useEffect, useMemo, useState } from "react";

import { useQueryClient } from "@tanstack/react-query";

import { buildDemoState } from "../../demoData";
import { formatLocalizedError } from "../../lib/errors";
import { DEFAULT_FILTERS, filterEvents } from "../../monitorFilters";
import type { EventDetail, EventSummary, Locale, MonitorFilters, StatsSnapshot } from "../../types";
import {
  buildDetailQueryKey,
  buildEventsQueryKey,
  isEmptyStats,
  TRAFFIC_STATS_QUERY_KEY,
  useTrafficDetailQuery,
  useTrafficEventsQuery,
  useTrafficStatsQuery,
} from "./queries";
import { useTrafficLiveInvalidation } from "./useTrafficLiveInvalidation";

export interface TrafficMonitorController {
  detail: EventDetail | null;
  detailLoading: boolean;
  error: string | null;
  events: EventSummary[];
  filters: MonitorFilters;
  overviewLoading: boolean;
  refreshOverview: () => Promise<void>;
  selectedRequestId: string | null;
  setFilters: (filters: MonitorFilters) => void;
  setSelectedRequestId: (requestId: string | null) => void;
  stats: StatsSnapshot | null;
  usingDemo: boolean;
}

export function useTrafficMonitorState(locale: Locale): TrafficMonitorController {
  const demoState = useMemo(() => buildDemoState(locale), [locale]);
  const queryClient = useQueryClient();
  const [filters, setFilters] = useState<MonitorFilters>(DEFAULT_FILTERS);
  const [selectedRequestId, setSelectedRequestId] = useState<string | null>(null);

  const eventsQuery = useTrafficEventsQuery(filters);
  const statsQuery = useTrafficStatsQuery();

  const usingDemo = useMemo(() => {
    return (eventsQuery.data?.items.length ?? 0) === 0 && isEmptyStats(statsQuery.data);
  }, [eventsQuery.data?.items.length, statsQuery.data]);

  const events = useMemo<EventSummary[]>(() => {
    if (usingDemo) {
      return filterEvents(demoState.events, filters);
    }
    return eventsQuery.data?.items ?? [];
  }, [demoState.events, eventsQuery.data?.items, filters, usingDemo]);

  const stats = useMemo<StatsSnapshot | null>(() => {
    if (usingDemo) {
      return demoState.stats;
    }
    return statsQuery.data ?? null;
  }, [demoState.stats, statsQuery.data, usingDemo]);

  useEffect(() => {
    const availableRequestIds = new Set(events.map((event) => event.requestId));
    setSelectedRequestId((current) => {
      if (current && availableRequestIds.has(current)) {
        return current;
      }
      return events[0]?.requestId ?? null;
    });
  }, [events]);

  const detailQuery = useTrafficDetailQuery(selectedRequestId, Boolean(selectedRequestId) && !usingDemo);

  const detail = useMemo<EventDetail | null>(() => {
    if (!selectedRequestId) {
      return null;
    }
    if (usingDemo) {
      return demoState.detailById[selectedRequestId] ?? null;
    }
    return detailQuery.data ?? null;
  }, [demoState.detailById, detailQuery.data, selectedRequestId, usingDemo]);

  const refreshOverview = useCallback(async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: [TRAFFIC_STATS_QUERY_KEY] }),
      queryClient.invalidateQueries({ queryKey: buildEventsQueryKey(filters) }),
      selectedRequestId
        ? queryClient.invalidateQueries({ queryKey: buildDetailQueryKey(selectedRequestId) })
        : Promise.resolve(),
    ]);
  }, [filters, queryClient, selectedRequestId]);

  useTrafficLiveInvalidation(selectedRequestId);

  const error = useMemo(() => {
    const overviewError = eventsQuery.error ?? statsQuery.error;
    if (overviewError) {
      return formatLocalizedError(overviewError, locale, {
        en: "Failed to load monitoring data.",
        zh: "加载监控数据失败。",
      });
    }
    if (!usingDemo && detailQuery.error) {
      return formatLocalizedError(detailQuery.error, locale, {
        en: "Failed to load trace detail.",
        zh: "加载轨迹详情失败。",
      });
    }
    return null;
  }, [detailQuery.error, eventsQuery.error, locale, statsQuery.error, usingDemo]);

  return {
    detail,
    detailLoading: Boolean(selectedRequestId) && !usingDemo && detailQuery.isFetching,
    error,
    events,
    filters,
    overviewLoading: eventsQuery.isLoading || statsQuery.isLoading,
    refreshOverview,
    selectedRequestId,
    setFilters,
    setSelectedRequestId,
    stats,
    usingDemo,
  };
}
