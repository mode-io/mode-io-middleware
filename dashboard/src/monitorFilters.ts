import { fmtClient, fmtImpact, fmtLifecycle, fmtStatus, getCopy } from "./i18n";
import type {
  EventSummary,
  Locale,
  MonitorClientFilter,
  MonitorFilterKey,
  MonitorFilters,
  MonitorImpactFilter,
  MonitorLifecycleFilter,
  MonitorStatusFilter,
} from "./types";

export const DEFAULT_FILTERS: MonitorFilters = {
  status: "all",
  clientName: "all",
  impact: "all",
  lifecycle: "all",
};

export const FILTER_OPTIONS: {
  status: MonitorStatusFilter[];
  clientName: MonitorClientFilter[];
  impact: MonitorImpactFilter[];
  lifecycle: MonitorLifecycleFilter[];
} = {
  status: ["all", "completed", "blocked", "error", "stream_completed"],
  clientName: ["all", "codex", "opencode", "openclaw", "claude_code", "unknown"],
  impact: ["all", "pass_through", "modified", "blocked", "warned", "mixed"],
  lifecycle: ["all", "none", "pre_request", "post_response", "pre_and_post", "stream", "pre_and_stream"],
};

export function setFilterValue<K extends MonitorFilterKey>(
  filters: MonitorFilters,
  key: K,
  value: MonitorFilters[K],
): MonitorFilters {
  return {
    ...filters,
    [key]: value,
  };
}

export function resetFilters(): MonitorFilters {
  return { ...DEFAULT_FILTERS };
}

export function hasActiveFilters(filters: MonitorFilters): boolean {
  return Object.values(filters).some((value) => value !== "all");
}

export function matchesMonitorFilters(
  event: Pick<EventSummary, "status" | "clientName" | "impact" | "lifecycle">,
  filters: MonitorFilters,
): boolean {
  return (
    (filters.status === "all" || event.status === filters.status) &&
    (filters.clientName === "all" || event.clientName === filters.clientName) &&
    (filters.impact === "all" || event.impact === filters.impact) &&
    (filters.lifecycle === "all" || event.lifecycle === filters.lifecycle)
  );
}

export function filterEvents(events: EventSummary[], filters: MonitorFilters): EventSummary[] {
  return events.filter((event) => matchesMonitorFilters(event, filters));
}

export function formatFilterValue(key: MonitorFilterKey, value: MonitorFilters[MonitorFilterKey], locale: Locale): string {
  const copy = getCopy(locale);

  if (value === "all") {
    return copy.filters.all;
  }

  if (key === "status") {
    return fmtStatus(value, locale);
  }
  if (key === "clientName") {
    return fmtClient(value, locale);
  }
  if (key === "lifecycle") {
    return fmtLifecycle(value, locale);
  }
  if (key === "impact") {
    return fmtImpact(value, locale);
  }
  return value;
}

export function formatFilterChip(key: MonitorFilterKey, value: MonitorFilters[MonitorFilterKey], locale: Locale): string {
  const copy = getCopy(locale);
  const labelByKey: Record<MonitorFilterKey, string> = {
    status: copy.filters.status,
    clientName: copy.filters.client,
    lifecycle: copy.filters.lifecycle,
    impact: copy.filters.impact,
  };

  return `${labelByKey[key]}: ${formatFilterValue(key, value, locale)}`;
}
