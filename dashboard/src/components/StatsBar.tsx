import { getCopy } from "../i18n";
import { setFilterValue } from "../monitorFilters";
import type { DisplayResult, Locale, MonitorFilters, StatsSnapshot } from "../types";
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
  const inner = (
    <>
      <span className="statsbar__label">{label}</span>
      <strong className="statsbar__value">{value}</strong>
    </>
  );
  if (onClick) {
    return <button className={cls} onClick={onClick} type="button">{inner}</button>;
  }
  return <div className={cls}>{inner}</div>;
}

export function StatsBar({ locale, stats, filters, onFiltersChange }: StatsBarProps) {
  const copy = getCopy(locale);

  if (!stats) {
    return <div className="statsbar statsbar--empty">{copy.table.loading}</div>;
  }

  const blockedCount = stats.byStatus["blocked"] ?? 0;
  const errorCount = stats.byStatus["error"] ?? 0;
  const modifiedCount = stats.byImpact["modified"] ?? 0;

  function toggleResultFilter(result: DisplayResult) {
    onFiltersChange(setFilterValue(filters, "result", filters.result === result ? "all" : result));
  }

  return (
    <div className="statsbar">
      <Stat label={copy.stats.traces} value={stats.completedRecords} />
      <Stat label={copy.stats.inFlight} value={stats.inFlightRecords} />
      <Stat
        label={copy.stats.modified}
        value={modifiedCount}
        accent="warn"
        active={filters.result === "edited"}
        onClick={() => toggleResultFilter("edited")}
      />
      <Stat
        label={copy.stats.blocked}
        value={blockedCount}
        accent="danger"
        active={filters.result === "denied"}
        onClick={() => toggleResultFilter("denied")}
      />
      <Stat
        label={copy.stats.errors}
        value={errorCount}
        accent="danger"
        active={filters.result === "error"}
        onClick={() => toggleResultFilter("error")}
      />
      <Stat label={copy.stats.p50} value={formatDuration(stats.latencyMs.p50, locale)} />
      <Stat label={copy.stats.p95} value={formatDuration(stats.latencyMs.p95, locale)} />
    </div>
  );
}
