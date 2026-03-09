import { getCopy } from "../i18n";
import { setFilterValue } from "../monitorFilters";
import type { Locale, MonitorFilters, StatsSnapshot } from "../types";
import { formatDuration } from "../utils";

interface StatsBarProps {
  locale: Locale;
  stats: StatsSnapshot | null;
  filters: MonitorFilters;
  onFiltersChange: (filters: MonitorFilters) => void;
}

function Stat({
  label,
  value,
  accent,
  active,
  onClick,
}: {
  label: string;
  value: string | number;
  accent?: string;
  active?: boolean;
  onClick?: () => void;
}) {
  const cls = `statsbar__stat${accent ? ` statsbar__stat--${accent}` : ""}${active ? " statsbar__stat--active" : ""}`;
  if (onClick) {
    return (
      <button className={cls} onClick={onClick} type="button">
        <span className="statsbar__label">{label}</span>
        <strong className="statsbar__value">{value}</strong>
      </button>
    );
  }
  return (
    <div className={cls}>
      <span className="statsbar__label">{label}</span>
      <strong className="statsbar__value">{value}</strong>
    </div>
  );
}

export function StatsBar({ locale, stats, filters, onFiltersChange }: StatsBarProps) {
  const copy = getCopy(locale);

  if (!stats) {
    return <div className="statsbar statsbar--empty">{copy.table.loading}</div>;
  }

  const blockedCount = stats.byStatus["blocked"] ?? 0;
  const errorCount = stats.byStatus["error"] ?? 0;
  const modifiedCount = stats.byImpact["modified"] ?? 0;

  function toggleStatusFilter(status: string) {
    onFiltersChange(setFilterValue(filters, "status", filters.status === status ? "all" : status));
  }

  function toggleImpactFilter(impact: string) {
    onFiltersChange(setFilterValue(filters, "impact", filters.impact === impact ? "all" : impact));
  }

  return (
    <div className="statsbar">
      <Stat label={copy.stats.traces} value={stats.completedRecords} />
      <Stat label={copy.stats.inFlight} value={stats.inFlightRecords} />
      <Stat
        label={copy.stats.modified}
        value={modifiedCount}
        accent="warn"
        active={filters.impact === "modified"}
        onClick={() => toggleImpactFilter("modified")}
      />
      <Stat
        label={copy.stats.blocked}
        value={blockedCount}
        accent="danger"
        active={filters.status === "blocked"}
        onClick={() => toggleStatusFilter("blocked")}
      />
      <Stat
        label={copy.stats.errors}
        value={errorCount}
        accent="danger"
        active={filters.status === "error"}
        onClick={() => toggleStatusFilter("error")}
      />
      <Stat label={copy.stats.p50} value={formatDuration(stats.latencyMs.p50, locale)} />
      <Stat label={copy.stats.p95} value={formatDuration(stats.latencyMs.p95, locale)} />
    </div>
  );
}
