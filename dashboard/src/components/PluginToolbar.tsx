import { getCopy } from "../i18n";
import type { Locale, PluginInventoryResponse, PluginListFilters, PluginProfileSummary, PluginRuntimeSummary } from "../types";

interface PluginToolbarProps {
  locale: Locale;
  runtime: PluginRuntimeSummary | null;
  profiles: PluginProfileSummary[];
  selectedProfile: string;
  filters: PluginListFilters;
  loading: boolean;
  counts: { total: number; enabled: number; attention: number };
  visibleCount: number;
  onProfileChange: (profile: string) => void;
  onFiltersChange: (filters: PluginListFilters) => void;
  onRefresh: () => void;
}

export function PluginToolbar({
  locale,
  runtime,
  profiles,
  selectedProfile,
  filters,
  loading,
  counts,
  visibleCount,
  onProfileChange,
  onFiltersChange,
  onRefresh,
}: PluginToolbarProps) {
  const copy = getCopy(locale);

  return (
    <section className="plugin-toolbar">
      <div className="plugin-toolbar__summary">
        <div>
          <strong className="pane-header__title">{copy.plugins.title}</strong>
          <div className="pane-header__meta">{copy.plugins.subtitle}</div>
        </div>
        <label className="plugin-toolbar__profile-picker">
          <span className="plugin-toolbar__profile-picker-label">{copy.plugins.selectedProfile}</span>
          <select value={selectedProfile} onChange={(event) => onProfileChange(event.target.value)}>
            {profiles.map((profile) => (
              <option key={profile.name} value={profile.name}>
                {profile.name}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="plugin-toolbar__controls">
        <label className="filter-field filter-field--search">
          <span className="filter-field__label">{copy.plugins.search}</span>
          <input
            className="input"
            type="search"
            value={filters.search}
            onChange={(event) => onFiltersChange({ ...filters, search: event.target.value })}
            placeholder={copy.plugins.searchPlaceholder}
            aria-label={copy.plugins.search}
          />
        </label>

        <label className="filter-field">
          <span className="filter-field__label">{copy.plugins.state}</span>
          <select value={filters.state} onChange={(event) => onFiltersChange({ ...filters, state: event.target.value as PluginListFilters["state"] })}>
            <option value="all">{copy.plugins.stateAll}</option>
            <option value="enabled">{copy.plugins.stateEnabledOnly}</option>
            <option value="disabled">{copy.plugins.stateDisabledOnly}</option>
            <option value="attention">{copy.plugins.stateAttentionOnly}</option>
          </select>
        </label>

        <label className="filter-field">
          <span className="filter-field__label">{copy.plugins.capability}</span>
          <select value={filters.capability} onChange={(event) => onFiltersChange({ ...filters, capability: event.target.value as PluginListFilters["capability"] })}>
            <option value="all">{copy.plugins.capabilityAll}</option>
            <option value="canPatch">{copy.plugins.capabilityPatch}</option>
            <option value="canBlock">{copy.plugins.capabilityBlock}</option>
          </select>
        </label>

        <label className="filter-field">
          <span className="filter-field__label">{copy.plugins.health}</span>
          <select value={filters.health} onChange={(event) => onFiltersChange({ ...filters, health: event.target.value as PluginListFilters["health"] })}>
            <option value="all">{copy.filters.all}</option>
            <option value="ok">{copy.plugins.healthOk}</option>
            <option value="warn">{copy.plugins.healthWarn}</option>
            <option value="error">{copy.plugins.healthError}</option>
          </select>
        </label>

        <div className="plugin-toolbar__actions">
          <button className="btn" onClick={onRefresh} type="button" disabled={loading}>
            {copy.plugins.refresh}
          </button>
          <button
            className="btn btn--quiet"
            onClick={() => onFiltersChange({ search: "", state: "all", capability: "all", health: "all" })}
            type="button"
          >
            {copy.plugins.clear}
          </button>
        </div>
      </div>

      <div className="plugin-toolbar__footer">
        <div className="plugin-toolbar__metrics" aria-label={copy.plugins.title}>
          <div className="plugin-toolbar__metric">
            <span className="plugin-toolbar__metric-label">{copy.plugins.totalCount}</span>
            <strong className="plugin-toolbar__metric-value mono">{counts.total}</strong>
          </div>
          <div className="plugin-toolbar__metric">
            <span className="plugin-toolbar__metric-label">{copy.plugins.enabledCount}</span>
            <strong className="plugin-toolbar__metric-value mono">{counts.enabled}</strong>
          </div>
          <div className="plugin-toolbar__metric plugin-toolbar__metric--attention">
            <span className="plugin-toolbar__metric-label">{copy.plugins.attentionCount}</span>
            <strong className="plugin-toolbar__metric-value mono">{counts.attention}</strong>
          </div>
          <div className="plugin-toolbar__metric">
            <span className="plugin-toolbar__metric-label">{copy.plugins.visibleCount}</span>
            <strong className="plugin-toolbar__metric-value mono">{visibleCount}</strong>
          </div>
        </div>
        {runtime ? (
          <div className="plugin-toolbar__meta mono">
            <span>{copy.plugins.configPath}: {runtime.configPath}</span>
            {runtime.discoveryRoots[0] ? <span>{copy.plugins.discoveryRoot}: {runtime.discoveryRoots[0]}</span> : null}
          </div>
        ) : null}
      </div>
    </section>
  );
}
