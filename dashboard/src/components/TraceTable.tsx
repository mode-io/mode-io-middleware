import { deriveDirection, deriveResult, fmtClient, fmtLifecycle, fmtResult, getCopy } from "../i18n";
import { summarizePluginLabel } from "../traceInsights";
import { TraceFilters } from "./TraceFilters";
import type { EventSummary, Locale, MonitorFilters } from "../types";
import { formatDuration, formatTimestamp } from "../utils";

interface TraceTableProps {
  events: EventSummary[];
  filters: MonitorFilters;
  locale: Locale;
  loading: boolean;
  selectedRequestId: string | null;
  onFiltersChange: (filters: MonitorFilters) => void;
  onSelect: (requestId: string) => void;
  usingDemo: boolean;
  onOpenPlugin?: (pluginName: string, profile: string) => void;
}

export function TraceTable({
  events,
  filters,
  locale,
  loading,
  selectedRequestId,
  onFiltersChange,
  onSelect,
  usingDemo,
  onOpenPlugin,
}: TraceTableProps) {
  const copy = getCopy(locale);
  const visibleCount = events.length;

  return (
    <div className="trace-table-panel">
      <div className="pane-header">
        <div>
          <strong className="pane-header__title">{copy.table.listTitle}</strong>
          <div className="pane-header__meta">{copy.table.listSubtitle}</div>
        </div>
        <div className="pane-header__count mono">{visibleCount}</div>
      </div>

      {usingDemo ? <div className="trace-table__demo-note">{copy.table.demoNote}</div> : null}

      <TraceFilters filters={filters} locale={locale} visibleCount={visibleCount} onFiltersChange={onFiltersChange} />

      <div className="trace-table__scroll">
        <table className="trace-table">
          <colgroup>
            <col className="trace-table__col trace-table__col--result" />
            <col className="trace-table__col trace-table__col--client" />
            <col className="trace-table__col trace-table__col--direction" />
            <col className="trace-table__col trace-table__col--plugin" />
            <col className="trace-table__col trace-table__col--duration" />
            <col className="trace-table__col trace-table__col--request-id" />
            <col className="trace-table__col trace-table__col--time" />
          </colgroup>
          <thead>
            <tr>
              <th className="col-result">{copy.table.result}</th>
              <th className="col-client">{copy.table.client}</th>
              <th className="col-direction">{copy.table.direction}</th>
              <th className="col-plugin">{copy.table.plugin}</th>
              <th className="col-duration">{copy.table.duration}</th>
              <th className="col-id">{copy.table.requestId}</th>
              <th className="col-time">{copy.table.time}</th>
            </tr>
          </thead>
          <tbody>
            {loading && events.length === 0 ? (
              <tr>
                <td colSpan={7} className="trace-table__message">
                  {copy.table.loading}
                </td>
              </tr>
            ) : null}
            {!loading && events.length === 0 ? (
              <tr>
                <td colSpan={7} className="trace-table__message">
                  {copy.table.empty}
                </td>
              </tr>
            ) : null}
            {events.map((event) => {
              const selected = event.requestId === selectedRequestId;
              const result = deriveResult(event.status, event.impact);
              return (
                <tr
                  key={event.requestId}
                  className={`trace-table__row${selected ? " trace-table__row--selected" : ""}`}
                  onClick={() => onSelect(event.requestId)}
                >
                  <td className="col-result">
                    <span className={`result-tag result-tag--${result}`}>{fmtResult(event.status, event.impact, locale)}</span>
                  </td>
                  <td className="col-client">{fmtClient(event.clientName, locale)}</td>
                  <td className="col-direction">
                    <span className={`dir-tag dir-tag--${deriveDirection(event.lifecycle)}`}>{fmtLifecycle(event.lifecycle, locale)}</span>
                  </td>
                    <td className="col-plugin mono" title={event.pluginNames.join(", ") || undefined}>
                      {event.primaryPlugin && onOpenPlugin ? (
                        <button
                          className="link-inline link-inline--mono"
                          onClick={(clickEvent) => {
                            clickEvent.stopPropagation();
                            onOpenPlugin(event.primaryPlugin as string, event.profile);
                          }}
                          type="button"
                        >
                          {summarizePluginLabel(event.primaryPlugin, event.pluginNames)}
                        </button>
                      ) : (
                        summarizePluginLabel(event.primaryPlugin, event.pluginNames)
                      )}
                    </td>
                  <td className="col-duration mono">{formatDuration(event.durationMs, locale)}</td>
                  <td className="col-id mono">{event.requestId}</td>
                  <td className="col-time mono">{formatTimestamp(event.startedAt, locale)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
