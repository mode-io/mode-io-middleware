import { getCopy } from "../i18n";
import type { Locale, PluginListFilters, PluginProfileOverride } from "../types";
import type { PluginInventoryItem, PluginProfileSummary, PluginRuntimeSummary } from "../types";
import type { PluginWorkingState, PluginRow } from "../pluginManagement";
import { PluginInspector } from "./PluginInspector";
import { PluginList } from "./PluginList";
import { PluginToolbar } from "./PluginToolbar";

interface PluginWorkspaceProps {
  locale: Locale;
  runtime: PluginRuntimeSummary | null;
  profiles: PluginProfileSummary[];
  selectedProfile: string;
  selectedPluginName: string | null;
  selectedPlugin: PluginInventoryItem | null;
  selectedWorkingState: PluginWorkingState | null;
  rows: PluginRow[];
  filters: PluginListFilters;
  counts: { total: number; enabled: number; attention: number };
  warnings: string[];
  loading: boolean;
  readOnly: boolean;
  dirty: boolean;
  saving: boolean;
  pendingActionPlugin: string | null;
  error: string | null;
  onProfileChange: (profile: string) => void;
  onSelectPlugin: (pluginName: string) => void;
  onFiltersChange: (filters: PluginListFilters) => void;
  onRefresh: () => void;
  onEnable: (pluginName: string) => void;
  onDisable: (pluginName: string) => void;
  onMove: (pluginName: string, direction: -1 | 1) => void;
  onUpdateSettings: (update: PluginProfileOverride) => void;
  onSave: () => void;
  onDiscard: () => void;
}

export function PluginWorkspace({
  locale,
  runtime,
  profiles,
  selectedProfile,
  selectedPluginName,
  selectedPlugin,
  selectedWorkingState,
  rows,
  filters,
  counts,
  warnings,
  loading,
  readOnly,
  dirty,
  saving,
  pendingActionPlugin,
  error,
  onProfileChange,
  onSelectPlugin,
  onFiltersChange,
  onRefresh,
  onEnable,
  onDisable,
  onMove,
  onUpdateSettings,
  onSave,
  onDiscard,
}: PluginWorkspaceProps) {
  const copy = getCopy(locale);

  return (
    <>
      <PluginToolbar
        locale={locale}
        runtime={runtime}
        profiles={profiles}
        selectedProfile={selectedProfile}
        filters={filters}
        loading={loading}
        counts={counts}
        visibleCount={rows.length}
        onProfileChange={onProfileChange}
        onFiltersChange={onFiltersChange}
        onRefresh={onRefresh}
      />

      {readOnly ? <div className="error-strip">{copy.plugins.readOnly}</div> : null}
      {warnings.map((warning) => (
        <div key={warning} className="warning-strip">
          {warning}
        </div>
      ))}
      {error ? <div className="error-strip">{error}</div> : null}

      <main className="master-detail master-detail--plugins">
        <PluginList
          locale={locale}
          rows={rows}
          enabledCount={counts.enabled}
          selectedPluginName={selectedPluginName}
          loading={loading}
          readOnly={readOnly}
          pendingActionPlugin={pendingActionPlugin}
          onSelect={onSelectPlugin}
          onEnable={onEnable}
          onDisable={onDisable}
          onMove={onMove}
        />
        <div className="master-detail__divider" aria-hidden="true" />
        <PluginInspector
          locale={locale}
          plugin={selectedPlugin}
          workingState={selectedWorkingState}
          readOnly={readOnly}
          dirty={dirty}
          saving={saving}
          onEnable={onEnable}
          onDisable={onDisable}
          onUpdate={onUpdateSettings}
          onSave={onSave}
          onDiscard={onDiscard}
        />
      </main>
    </>
  );
}
