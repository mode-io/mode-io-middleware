import { getCopy } from "../i18n";
import type { Locale, PluginListFilters, PluginProfileSummary, PluginRuntimeSummary } from "../types";

interface PluginToolbarProps {
  locale: Locale;
  runtime: PluginRuntimeSummary | null;
  profiles: PluginProfileSummary[];
  selectedProfile: string;
  filters: PluginListFilters;
  loading: boolean;
  counts: { total: number; enabled: number; attention: number };
  onProfileChange: (profile: string) => void;
  onFiltersChange: (filters: PluginListFilters) => void;
  onRefresh: () => void;
}

function summaryLine(template: string, counts: { total: number; enabled: number; attention: number }) {
  return template
    .replace("{enabled}", String(counts.enabled))
    .replace("{attention}", String(counts.attention))
    .replace("{total}", String(counts.total));
}

export function PluginToolbar({
  locale,
  runtime,
  profiles,
  selectedProfile,
  filters,
  loading,
  counts,
  onProfileChange,
  onFiltersChange,
  onRefresh,
}: PluginToolbarProps) {
  const copy = getCopy(locale);

  return (
    <section className="plugin-toolbar">
      <div className="plugin-toolbar__top">
        <div className="plugin-toolbar__copy">
          <strong className="pane-header__title">{copy.plugins.title}</strong>
          <div className="pane-header__meta">{copy.plugins.subtitle}</div>
          <div className="plugin-toolbar__summary-line mono">{summaryLine(copy.plugins.summaryLine, counts)}</div>
        </div>

        <div className="plugin-toolbar__controls">
          <label className="filter-field">
            <span className="filter-field__label">{copy.plugins.selectedProfile}</span>
            <select value={selectedProfile} aria-label={copy.plugins.selectedProfile} onChange={(event) => onProfileChange(event.target.value)}>
              {profiles.map((profile) => (
                <option key={profile.name} value={profile.name}>
                  {profile.name}
                </option>
              ))}
            </select>
          </label>

          <label className="filter-field filter-field--search">
            <span className="filter-field__label">{copy.plugins.search}</span>
            <input
              className="input"
              type="search"
              value={filters.search}
              onChange={(event) => onFiltersChange({ search: event.target.value })}
              placeholder={copy.plugins.searchPlaceholder}
              aria-label={copy.plugins.search}
            />
          </label>

          <button className="btn" onClick={onRefresh} type="button" disabled={loading}>
            {copy.plugins.refresh}
          </button>
        </div>
      </div>

      {runtime ? (
        <div className="plugin-toolbar__meta mono">
          <span>{copy.plugins.configPath}: {runtime.configPath}</span>
          {runtime.discoveryRoots[0] ? <span>{copy.plugins.discoveryRoot}: {runtime.discoveryRoots[0]}</span> : null}
        </div>
      ) : null}
    </section>
  );
}
