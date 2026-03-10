import { buildPluginRowActionState } from "../features/plugins/actionState";
import { fmtPluginMode, fmtPluginSource, fmtPluginValidation, getCopy } from "../i18n";
import { groupPluginRows, type PluginRow } from "../pluginManagement";
import type { Locale } from "../types";

interface PluginListProps {
  locale: Locale;
  rows: PluginRow[];
  selectedProfile: string;
  selectedPluginName: string | null;
  loading: boolean;
  readOnly: boolean;
  actionsDisabled: boolean;
  pendingActionPlugin: string | null;
  onSelect: (pluginName: string) => void;
  onEnable: (pluginName: string) => void;
  onDisable: (pluginName: string) => void;
  onMove: (pluginName: string, direction: -1 | 1) => void;
}

function renderIssue(row: PluginRow): string | null {
  return row.plugin.validation.errors[0] ?? row.plugin.validation.warnings[0] ?? null;
}

function RowActionCluster({
  row,
  enabledCount,
  readOnly,
  actionsDisabled,
  pendingActionPlugin,
  locale,
  onSelect,
  onEnable,
  onDisable,
  onMove,
}: {
  row: PluginRow;
  enabledCount: number;
  readOnly: boolean;
  actionsDisabled: boolean;
  pendingActionPlugin: string | null;
  locale: Locale;
  onSelect: (pluginName: string) => void;
  onEnable: (pluginName: string) => void;
  onDisable: (pluginName: string) => void;
  onMove: (pluginName: string, direction: -1 | 1) => void;
}) {
  const copy = getCopy(locale);
  const quickActions = buildPluginRowActionState(row, {
    readOnly,
    actionsDisabled,
    actionPending: pendingActionPlugin === row.plugin.name,
    enabledCount,
  });

  if (row.working.enabled) {
    return (
      <div className="plugin-card__actions">
        <button className="btn btn--quiet" type="button" disabled={!quickActions.canDisable} onClick={(event) => { event.stopPropagation(); void onDisable(row.plugin.name); }}>
          {copy.plugins.disable}
        </button>
        <button className="btn btn--quiet" type="button" disabled={!quickActions.canMoveUp} onClick={(event) => { event.stopPropagation(); void onMove(row.plugin.name, -1); }}>
          {copy.plugins.moveUp}
        </button>
        <button className="btn btn--quiet" type="button" disabled={!quickActions.canMoveDown} onClick={(event) => { event.stopPropagation(); void onMove(row.plugin.name, 1); }}>
          {copy.plugins.moveDown}
        </button>
      </div>
    );
  }

  if (quickActions.showReview) {
    return (
      <div className="plugin-card__actions">
        <button className="btn btn--quiet" type="button" onClick={(event) => { event.stopPropagation(); onSelect(row.plugin.name); }}>
          {copy.plugins.review}
        </button>
      </div>
    );
  }

  return (
    <div className="plugin-card__actions">
      <button className="btn btn--quiet" type="button" disabled={!quickActions.canEnable} onClick={(event) => { event.stopPropagation(); void onEnable(row.plugin.name); }}>
        {copy.plugins.enable}
      </button>
    </div>
  );
}

function PluginCard({
  row,
  locale,
  selected,
  readOnly,
  actionsDisabled,
  pendingActionPlugin,
  enabledCount,
  onSelect,
  onEnable,
  onDisable,
  onMove,
}: {
  row: PluginRow;
  locale: Locale;
  selected: boolean;
  readOnly: boolean;
  actionsDisabled: boolean;
  pendingActionPlugin: string | null;
  enabledCount: number;
  onSelect: (pluginName: string) => void;
  onEnable: (pluginName: string) => void;
  onDisable: (pluginName: string) => void;
  onMove: (pluginName: string, direction: -1 | 1) => void;
}) {
  const copy = getCopy(locale);
  const issue = renderIssue(row);

  return (
    <article
      className={`plugin-card${selected ? " plugin-card--selected" : ""}`}
      onClick={() => onSelect(row.plugin.name)}
    >
      <div className="plugin-card__topline">
        <div className="plugin-card__title-group">
          <div className="plugin-card__title-row">
            <strong>{row.plugin.displayName}</strong>
            {row.working.enabled && row.working.position != null ? (
              <span className="plugin-card__order mono">#{row.working.position + 1}</span>
            ) : null}
            <span className={`plugin-health plugin-health--${row.plugin.validation.status}`}>{fmtPluginValidation(row.plugin.validation.status, locale)}</span>
          </div>
          <div className="plugin-card__identity mono">{row.plugin.name}</div>
        </div>
        <RowActionCluster
          row={row}
          enabledCount={enabledCount}
          readOnly={readOnly}
          actionsDisabled={actionsDisabled}
          pendingActionPlugin={pendingActionPlugin}
          locale={locale}
          onSelect={onSelect}
          onEnable={onEnable}
          onDisable={onDisable}
          onMove={onMove}
        />
      </div>

      <div className="plugin-card__description">{row.plugin.description || copy.plugins.none}</div>

      <div className="plugin-card__meta">
        <span className={`plugin-state plugin-state--${row.stateKind}`}>{row.stateKind === "enabled" ? copy.plugins.stateEnabled : row.stateKind === "attention" ? copy.plugins.stateAttention : copy.plugins.stateDisabled}</span>
      </div>

      {issue ? (
        <div className="plugin-card__footer">
          <span className="plugin-card__issue">{copy.plugins.issue}: {issue}</span>
        </div>
      ) : null}
    </article>
  );
}

function PluginSection({
  title,
  emptyText,
  rows,
  locale,
  selectedPluginName,
  readOnly,
  actionsDisabled,
  pendingActionPlugin,
  enabledCount,
  onSelect,
  onEnable,
  onDisable,
  onMove,
}: {
  title: string;
  emptyText: string;
  rows: PluginRow[];
  locale: Locale;
  selectedPluginName: string | null;
  readOnly: boolean;
  actionsDisabled: boolean;
  pendingActionPlugin: string | null;
  enabledCount: number;
  onSelect: (pluginName: string) => void;
  onEnable: (pluginName: string) => void;
  onDisable: (pluginName: string) => void;
  onMove: (pluginName: string, direction: -1 | 1) => void;
}) {
  if (rows.length === 0) return null;

  return (
    <section className="plugin-group">
      <div className="plugin-group__header">
        <strong className="plugin-group__title">{title}</strong>
        <span className="plugin-group__count mono">{rows.length}</span>
      </div>
      <div className="plugin-group__list">
        {rows.map((row) => (
          <PluginCard
            key={row.plugin.name}
            row={row}
            locale={locale}
            selected={row.plugin.name === selectedPluginName}
            readOnly={readOnly}
            actionsDisabled={actionsDisabled}
            pendingActionPlugin={pendingActionPlugin}
            enabledCount={enabledCount}
            onSelect={onSelect}
            onEnable={onEnable}
            onDisable={onDisable}
            onMove={onMove}
          />
        ))}
      </div>
    </section>
  );
}

export function PluginList({
  locale,
  rows,
  selectedProfile,
  selectedPluginName,
  loading,
  readOnly,
  actionsDisabled,
  pendingActionPlugin,
  onSelect,
  onEnable,
  onDisable,
  onMove,
}: PluginListProps) {
  const copy = getCopy(locale);
  const groups = groupPluginRows(rows);

  return (
    <div className="plugin-list-panel">
      <div className="pane-header">
        <div>
          <strong className="pane-header__title">{copy.plugins.listTitle}</strong>
          <div className="pane-header__meta">{selectedProfile}</div>
        </div>
        <div className="pane-header__count mono">{rows.length}</div>
      </div>

      <div className="plugin-list__scroll">
        {loading && rows.length === 0 ? <div className="plugin-group__empty plugin-group__empty--standalone">{copy.table.loading}</div> : null}
        {!loading && rows.length === 0 ? (
          <div className="plugin-group__empty plugin-group__empty--standalone">
            <strong>{copy.plugins.emptyTitle}</strong>
            <div>{copy.plugins.emptyNote}</div>
          </div>
        ) : null}

        {loading && rows.length > 0 ? null : (
          <div className="plugin-list__sections">
            <PluginSection
              title={copy.plugins.enabledSection}
              emptyText={copy.plugins.enabledSectionEmpty}
              rows={groups.enabled}
              locale={locale}
              selectedPluginName={selectedPluginName}
              readOnly={readOnly}
              actionsDisabled={actionsDisabled}
              pendingActionPlugin={pendingActionPlugin}
              enabledCount={groups.enabled.length}
              onSelect={onSelect}
              onEnable={onEnable}
              onDisable={onDisable}
              onMove={onMove}
            />
            <PluginSection
              title={copy.plugins.attentionSection}
              emptyText={copy.plugins.attentionSectionEmpty}
              rows={groups.attention}
              locale={locale}
              selectedPluginName={selectedPluginName}
              readOnly={readOnly}
              actionsDisabled={actionsDisabled}
              pendingActionPlugin={pendingActionPlugin}
              enabledCount={groups.enabled.length}
              onSelect={onSelect}
              onEnable={onEnable}
              onDisable={onDisable}
              onMove={onMove}
            />
            <PluginSection
              title={copy.plugins.availableSection}
              emptyText={copy.plugins.availableSectionEmpty}
              rows={groups.available}
              locale={locale}
              selectedPluginName={selectedPluginName}
              readOnly={readOnly}
              actionsDisabled={actionsDisabled}
              pendingActionPlugin={pendingActionPlugin}
              enabledCount={groups.enabled.length}
              onSelect={onSelect}
              onEnable={onEnable}
              onDisable={onDisable}
              onMove={onMove}
            />
          </div>
        )}
      </div>
    </div>
  );
}
