import { fmtFilterMatchCount, getCopy } from "../i18n";
import { FILTER_OPTIONS, formatFilterChip, formatFilterValue, hasActiveFilters, resetFilters, setFilterValue } from "../monitorFilters";
import type { Locale, MonitorFilterKey, MonitorFilters } from "../types";
import { Select } from "./Select";

interface TraceFiltersProps {
  filters: MonitorFilters;
  locale: Locale;
  visibleCount: number;
  onFiltersChange: (filters: MonitorFilters) => void;
}

const FILTER_FIELDS: MonitorFilterKey[] = ["result", "clientName", "direction"];

export function TraceFilters({ filters, locale, visibleCount, onFiltersChange }: TraceFiltersProps) {
  const copy = getCopy(locale);
  const hasFilters = hasActiveFilters(filters);
  const activeFilters = FILTER_FIELDS.filter((key) => filters[key] !== "all");
  const fieldLabels: Record<MonitorFilterKey, string> = {
    result: copy.filters.result,
    clientName: copy.filters.client,
    direction: copy.filters.direction,
  };

  return (
    <div className="trace-filters">
      <div className="trace-filters__controls">
        {FILTER_FIELDS.map((key) => {
          const value = filters[key];
          return (
            <div key={key} className={`filter-field${value !== "all" ? " filter-field--active" : ""}`}>
              <span className="filter-field__label">{fieldLabels[key]}</span>
              <Select
                value={value}
                options={FILTER_OPTIONS[key].map((option) => ({
                  value: option,
                  label: formatFilterValue(key, option, locale),
                }))}
                onChange={(nextValue) => onFiltersChange(setFilterValue(filters, key, nextValue as MonitorFilters[typeof key]))}
                aria-label={fieldLabels[key]}
              />
            </div>
          );
        })}
      </div>

      <div className="trace-filters__summary">
        <span className="trace-filters__result mono">{fmtFilterMatchCount(visibleCount, locale)}</span>
        {hasFilters ? (
          <div className="trace-filters__chips" aria-label={copy.filters.activeFilters}>
            {activeFilters.map((key) => (
              <span key={key} className="trace-filter-chip">
                {formatFilterChip(key, filters[key], locale)}
              </span>
            ))}
          </div>
        ) : (
          <span className="trace-filters__inactive">{copy.filters.showingAll}</span>
        )}
        {hasFilters ? (
          <button className="btn btn--quiet" onClick={() => onFiltersChange(resetFilters())} type="button">
            {copy.filters.clear}
          </button>
        ) : null}
      </div>
    </div>
  );
}
