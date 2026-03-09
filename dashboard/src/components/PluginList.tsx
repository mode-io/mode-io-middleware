import { fmtPluginMode, fmtPluginSource, fmtPluginValidation, getCopy } from "../i18n";
import type { Locale } from "../types";
import type { PluginRow } from "../pluginManagement";

interface PluginListProps {
  locale: Locale;
  rows: PluginRow[];
  enabledCount: number;
  selectedPluginName: string | null;
  loading: boolean;
  readOnly: boolean;
  pendingActionPlugin: string | null;
  onSelect: (pluginName: string) => void;
  onEnable: (pluginName: string) => void;
  onDisable: (pluginName: string) => void;
  onMove: (pluginName: string, direction: -1 | 1) => void;
}

function PluginStateLabel({ kind, locale }: { kind: PluginRow["stateKind"]; locale: Locale }) {
  const copy = getCopy(locale);
  const label = kind === "enabled" ? copy.plugins.stateEnabled : kind === "attention" ? copy.plugins.stateAttention : copy.plugins.stateDisabled;
  return <span className={`plugin-state plugin-state--${kind}`}>{label}</span>;
}

export function PluginList({
  locale,
  rows,
  enabledCount,
  selectedPluginName,
  loading,
  readOnly,
  pendingActionPlugin,
  onSelect,
  onEnable,
  onDisable,
  onMove,
}: PluginListProps) {
  const copy = getCopy(locale);

  return (
    <div className="plugin-list-panel">
      <div className="pane-header">
        <div>
          <strong className="pane-header__title">{copy.plugins.listTitle}</strong>
          <div className="pane-header__meta">{copy.plugins.listSubtitle}</div>
        </div>
        <div className="pane-header__count mono">{rows.length}</div>
      </div>

      <div className="plugin-list__scroll">
        <table className="plugin-list">
          <colgroup>
            <col className="plugin-list__col plugin-list__col--state" />
            <col className="plugin-list__col plugin-list__col--plugin" />
            <col className="plugin-list__col plugin-list__col--mode" />
            <col className="plugin-list__col plugin-list__col--hooks" />
            <col className="plugin-list__col plugin-list__col--health" />
            <col className="plugin-list__col plugin-list__col--usage" />
            <col className="plugin-list__col plugin-list__col--actions" />
          </colgroup>
          <thead>
            <tr>
              <th>{copy.plugins.stateCol}</th>
              <th>{copy.plugins.pluginCol}</th>
              <th>{copy.plugins.modeCol}</th>
              <th>{copy.plugins.hooksCol}</th>
              <th>{copy.plugins.healthCol}</th>
              <th>{copy.plugins.usageCol}</th>
              <th>{copy.plugins.actionsCol}</th>
            </tr>
          </thead>
          <tbody>
            {loading && rows.length === 0 ? (
              <tr>
                <td colSpan={7} className="trace-table__message">{copy.table.loading}</td>
              </tr>
            ) : null}
            {!loading && rows.length === 0 && enabledCount === 0 ? (
              <tr>
                <td colSpan={7} className="trace-table__message">
                  <strong>{copy.plugins.noPluginsTitle}</strong>
                  <div style={{ marginTop: 4 }}>{copy.plugins.noPluginsNote}</div>
                </td>
              </tr>
            ) : null}
            {!loading && rows.length === 0 && enabledCount > 0 ? (
              <tr>
                <td colSpan={7} className="trace-table__message">
                  <strong>{copy.plugins.emptyTitle}</strong>
                  <div style={{ marginTop: 4 }}>{copy.plugins.emptyNote}</div>
                </td>
              </tr>
            ) : null}
            {rows.map((row) => {
              const selected = row.plugin.name === selectedPluginName;
              const canEnable = row.plugin.validation.status !== "error" && !readOnly;
              const showReview = !row.working.enabled && row.working.requiresReview && row.working.hasRememberedSettings;
              const moveDisabled = pendingActionPlugin === row.plugin.name || readOnly;

              return (
                <tr
                  key={row.plugin.name}
                  className={`plugin-list__row${selected ? " plugin-list__row--selected" : ""}`}
                  onClick={() => onSelect(row.plugin.name)}
                >
                  <td>
                    <PluginStateLabel kind={row.stateKind} locale={locale} />
                  </td>
                  <td className="plugin-list__plugin-col">
                    <div className="plugin-list__plugin-name-row">
                      <strong>{row.plugin.displayName}</strong>
                      <span className="plugin-list__plugin-source mono">{fmtPluginSource(row.plugin.sourceKind, locale)}</span>
                    </div>
                    <div className="plugin-list__plugin-id mono">{row.plugin.name}</div>
                    <div className="plugin-list__plugin-desc">{row.plugin.description || copy.plugins.none}</div>
                  </td>
                  <td className="mono">{fmtPluginMode(row.working.effectiveMode, locale)}</td>
                  <td className="mono" title={row.plugin.hooks.join(", ")}>{row.plugin.hooks.join(", ") || copy.plugins.none}</td>
                  <td>
                    <span className={`plugin-health plugin-health--${row.plugin.validation.status}`}>{fmtPluginValidation(row.plugin.validation.status, locale)}</span>
                  </td>
                  <td className="mono">{row.plugin.stats.calls} / {row.plugin.stats.errors}</td>
                  <td>
                    <div className="plugin-list__actions">
                      {row.working.enabled ? (
                        <>
                          <button className="btn btn--quiet" onClick={(event) => { event.stopPropagation(); void onDisable(row.plugin.name); }} type="button" disabled={moveDisabled}>
                            {copy.plugins.disable}
                          </button>
                          <button className="btn btn--quiet" onClick={(event) => { event.stopPropagation(); void onMove(row.plugin.name, -1); }} type="button" disabled={moveDisabled || row.working.position === 0}>
                            {copy.plugins.moveUp}
                          </button>
                          <button className="btn btn--quiet" onClick={(event) => { event.stopPropagation(); void onMove(row.plugin.name, 1); }} type="button" disabled={moveDisabled || row.working.position === enabledCount - 1}>
                            {copy.plugins.moveDown}
                          </button>
                        </>
                      ) : showReview ? (
                        <button className="btn btn--quiet" onClick={(event) => { event.stopPropagation(); onSelect(row.plugin.name); }} type="button">
                          {copy.plugins.review}
                        </button>
                      ) : (
                        <button className="btn btn--quiet" onClick={(event) => { event.stopPropagation(); void onEnable(row.plugin.name); }} type="button" disabled={!canEnable || pendingActionPlugin === row.plugin.name}>
                          {copy.plugins.enable}
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
