import { deriveDirection, deriveResult, fmtClient, getCopy } from "./i18n";
import type {
  DisplayDirection,
  DisplayResult,
  EventSummary,
  Locale,
  MonitorClientFilter,
  MonitorDirectionFilter,
  MonitorFilterKey,
  MonitorFilters,
  MonitorResultFilter,
} from "./types";

export const DEFAULT_FILTERS: MonitorFilters = {
  result: "all",
  clientName: "all",
  direction: "all",
};

export const FILTER_OPTIONS: {
  result: MonitorResultFilter[];
  clientName: MonitorClientFilter[];
  direction: MonitorDirectionFilter[];
} = {
  result: ["all", "clean", "edited", "flagged", "denied", "error"],
  clientName: ["all", "codex", "opencode", "openclaw", "claude_code", "unknown"],
  direction: ["all", "idle", "inbound", "outbound", "both"],
};

const RESULT_TO_PARAMS: Record<DisplayResult, { status?: string; impact?: string }> = {
  clean: { impact: "pass_through" },
  edited: { impact: "modified" },
  flagged: { impact: "warned" },
  denied: { status: "blocked" },
  error: { status: "error" },
};

const DIRECTION_TO_LIFECYCLES: Record<DisplayDirection, string[]> = {
  idle: ["none"],
  inbound: ["pre_request"],
  outbound: ["post_response", "stream"],
  both: ["pre_and_post", "pre_and_stream"],
};

export function resultFilterToQueryParams(result: MonitorResultFilter): { status?: string; impact?: string } {
  if (result === "all") return {};
  return RESULT_TO_PARAMS[result] ?? {};
}

export function directionFilterToLifecycles(direction: MonitorDirectionFilter): string[] | null {
  if (direction === "all") return null;
  return DIRECTION_TO_LIFECYCLES[direction] ?? null;
}

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
    (filters.result === "all" || deriveResult(event.status, event.impact) === filters.result) &&
    (filters.clientName === "all" || event.clientName === filters.clientName) &&
    (filters.direction === "all" || deriveDirection(event.lifecycle) === filters.direction)
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

  if (key === "result") {
    const c = copy.common;
    const map: Record<string, string> = {
      clean: c.impactClean,
      edited: c.impactEdited,
      flagged: c.impactFlagged,
      denied: c.impactDenied,
      error: c.impactError,
    };
    return map[value] ?? value;
  }
  if (key === "clientName") {
    return fmtClient(value, locale);
  }
  if (key === "direction") {
    const c = copy.common;
    const map: Record<string, string> = {
      idle: c.dirIdle,
      inbound: c.dirInbound,
      outbound: c.dirOutbound,
      both: c.dirBoth,
    };
    return map[value] ?? value;
  }
  return value;
}

export function formatFilterChip(key: MonitorFilterKey, value: MonitorFilters[MonitorFilterKey], locale: Locale): string {
  const copy = getCopy(locale);
  const labelByKey: Record<MonitorFilterKey, string> = {
    result: copy.filters.result,
    clientName: copy.filters.client,
    direction: copy.filters.direction,
  };

  return `${labelByKey[key]}: ${formatFilterValue(key, value, locale)}`;
}
