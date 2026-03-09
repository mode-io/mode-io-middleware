import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { fetchJson } from "../api";
import { buildDemoState } from "../demoData";
import { DEFAULT_FILTERS, filterEvents } from "../monitorFilters";
import type { EventDetail, EventSummary, EventsResponse, Locale, MonitorFilters, StatsSnapshot } from "../types";

const EVENTS_LIMIT = 50;

function buildEventsUrl(filters: MonitorFilters): string {
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

export function useTrafficMonitorState(locale: Locale) {
  const demoState = useMemo(() => buildDemoState(locale), [locale]);
  const [filters, setFilters] = useState<MonitorFilters>(DEFAULT_FILTERS);
  const [events, setEvents] = useState<EventSummary[]>([]);
  const [stats, setStats] = useState<StatsSnapshot | null>(null);
  const [selectedRequestId, setSelectedRequestId] = useState<string | null>(null);
  const [detail, setDetail] = useState<EventDetail | null>(null);
  const [overviewLoading, setOverviewLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [usingDemo, setUsingDemo] = useState(false);
  const refreshTimer = useRef<number | null>(null);
  const selectedRequestIdRef = useRef<string | null>(null);

  useEffect(() => {
    selectedRequestIdRef.current = selectedRequestId;
  }, [selectedRequestId]);

  const refreshOverview = useCallback(async () => {
    setOverviewLoading(true);
    setError(null);
    try {
      const [eventsResponse, statsResponse] = await Promise.all([
        fetchJson<EventsResponse>(buildEventsUrl(filters)),
        fetchJson<StatsSnapshot>("/modeio/api/stats"),
      ]);
      const shouldUseDemo = eventsResponse.items.length === 0 && statsResponse.completedRecords === 0 && statsResponse.inFlightRecords === 0;
      const nextEvents = shouldUseDemo ? filterEvents(demoState.events, filters) : eventsResponse.items;
      const nextStats = shouldUseDemo ? demoState.stats : statsResponse;

      setUsingDemo(shouldUseDemo);
      setEvents(nextEvents);
      setStats(nextStats);
      setSelectedRequestId((current) => {
        if (current && nextEvents.some((item) => item.requestId === current)) {
          return current;
        }
        return nextEvents[0]?.requestId ?? null;
      });
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : locale === "zh" ? "加载监控数据失败。" : "Failed to load monitoring data.";
      setUsingDemo(false);
      setError(message);
    } finally {
      setOverviewLoading(false);
    }
  }, [demoState.events, demoState.stats, filters, locale]);

  const refreshDetail = useCallback(async (requestId: string | null) => {
    if (!requestId) {
      setDetail(null);
      return;
    }
    if (usingDemo) {
      setDetailLoading(false);
      setDetail(demoState.detailById[requestId] ?? null);
      return;
    }
    setDetailLoading(true);
    try {
      const response = await fetchJson<EventDetail>(`/modeio/api/events/${requestId}`);
      setDetail(response);
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : locale === "zh" ? "加载轨迹详情失败。" : "Failed to load trace detail.";
      setError(message);
      setDetail(null);
    } finally {
      setDetailLoading(false);
    }
  }, [demoState.detailById, locale, usingDemo]);

  useEffect(() => {
    void refreshOverview();
  }, [refreshOverview]);

  useEffect(() => {
    void refreshDetail(selectedRequestId);
  }, [refreshDetail, selectedRequestId]);

  useEffect(() => {
    const source = new EventSource("/modeio/api/events/live");

    const scheduleRefresh = () => {
      if (refreshTimer.current !== null) {
        window.clearTimeout(refreshTimer.current);
      }
      refreshTimer.current = window.setTimeout(() => {
        void refreshOverview();
        if (selectedRequestIdRef.current) {
          void refreshDetail(selectedRequestIdRef.current);
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
  }, [refreshDetail, refreshOverview]);

  return {
    detail,
    detailLoading,
    error,
    events,
    filters,
    overviewLoading,
    selectedRequestId,
    setFilters,
    setSelectedRequestId,
    stats,
    refreshOverview,
    usingDemo,
  };
}
