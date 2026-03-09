import { useEffect, useMemo, useState } from "react";

import { PluginWorkspace } from "./components/PluginWorkspace";
import { StatsBar } from "./components/StatsBar";
import { TraceInspector } from "./components/TraceInspector";
import { TraceTable } from "./components/TraceTable";
import { ViewTabs } from "./components/ViewTabs";
import { usePluginManagementState } from "./hooks/usePluginManagementState";
import { useTrafficMonitorState } from "./hooks/useDashboardState";
import { getCopy } from "./i18n";
import type { DashboardView, Locale } from "./types";

type ThemeMode = "day" | "night";

function resolveInitialView(): DashboardView {
  const stored = window.localStorage.getItem("modeio-dashboard-view");
  return stored === "plugins" ? "plugins" : "traffic";
}

function resolveInitialLocale(): Locale {
  const stored = window.localStorage.getItem("modeio-dashboard-locale");
  if (stored === "en" || stored === "zh") {
    return stored;
  }
  return navigator.language.toLowerCase().startsWith("zh") ? "zh" : "en";
}

function resolveInitialTheme(): ThemeMode {
  const stored = window.localStorage.getItem("modeio-dashboard-theme");
  if (stored === "day" || stored === "night") {
    return stored;
  }
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "night" : "day";
}

export function App() {
  const [locale, setLocale] = useState<Locale>(resolveInitialLocale);
  const [theme, setTheme] = useState<ThemeMode>(resolveInitialTheme);
  const [activeView, setActiveView] = useState<DashboardView>(resolveInitialView);
  const copy = useMemo(() => getCopy(locale), [locale]);
  const {
    detail,
    detailLoading,
    error,
    events,
    filters,
    overviewLoading,
    refreshOverview,
    selectedRequestId,
    setFilters,
    setSelectedRequestId,
    stats,
    usingDemo,
  } = useTrafficMonitorState(locale);
  const pluginManagement = usePluginManagementState(locale);

  useEffect(() => {
    document.documentElement.lang = locale === "zh" ? "zh-CN" : "en";
    document.title = locale === "zh" ? "ModeIO 监控台" : "ModeIO Monitor";
    window.localStorage.setItem("modeio-dashboard-locale", locale);
  }, [locale]);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    window.localStorage.setItem("modeio-dashboard-theme", theme);
  }, [theme]);

  useEffect(() => {
    window.localStorage.setItem("modeio-dashboard-view", activeView);
  }, [activeView]);

  function openPlugin(pluginName: string, profile: string) {
    pluginManagement.focusPlugin(pluginName, profile);
    setActiveView("plugins");
  }

  return (
    <div className="shell">
      <header className="toolbar">
        <div className="toolbar__left">
          <div className="toolbar__brand">
            <strong className="toolbar__title">{copy.toolbar.title}</strong>
            {activeView === "traffic" && usingDemo ? <span className="badge badge--muted">{copy.toolbar.demoBadge}</span> : null}
          </div>
          <ViewTabs activeView={activeView} locale={locale} onChange={setActiveView} />
        </div>
        <div className="toolbar__right">
          <button className="btn" onClick={() => (activeView === "traffic" ? void refreshOverview() : void pluginManagement.refresh())} type="button">
            {copy.toolbar.refresh}
          </button>
          <div className="toggle-group" role="group" aria-label={copy.toolbar.language}>
            <button className={`toggle-btn${locale === "en" ? " toggle-btn--on" : ""}`} onClick={() => setLocale("en")} type="button">
              EN
            </button>
            <button className={`toggle-btn${locale === "zh" ? " toggle-btn--on" : ""}`} onClick={() => setLocale("zh")} type="button">
              中文
            </button>
          </div>
          <div className="toggle-group" role="group" aria-label={copy.toolbar.theme}>
            <button className={`toggle-btn${theme === "day" ? " toggle-btn--on" : ""}`} onClick={() => setTheme("day")} type="button">
              {copy.toolbar.day}
            </button>
            <button
              className={`toggle-btn${theme === "night" ? " toggle-btn--on" : ""}`}
              onClick={() => setTheme("night")}
              type="button"
            >
              {copy.toolbar.night}
            </button>
          </div>
        </div>
      </header>

      {activeView === "traffic" ? (
        <>
          {error ? <div className="error-strip">{error}</div> : null}
          <StatsBar locale={locale} stats={stats} filters={filters} onFiltersChange={setFilters} />
          <main className="master-detail">
            <TraceTable
              events={events}
              filters={filters}
              locale={locale}
              loading={overviewLoading}
              selectedRequestId={selectedRequestId}
              onFiltersChange={setFilters}
              onSelect={setSelectedRequestId}
              usingDemo={usingDemo}
              onOpenPlugin={openPlugin}
            />
            <div className="master-detail__divider" aria-hidden="true" />
            <TraceInspector detail={detail} loading={detailLoading} locale={locale} onOpenPlugin={openPlugin} />
          </main>
        </>
      ) : (
        <PluginWorkspace
          locale={locale}
          runtime={pluginManagement.runtime}
          profiles={pluginManagement.profiles}
          selectedProfile={pluginManagement.selectedProfile}
          selectedPluginName={pluginManagement.selectedPluginName}
          selectedPlugin={pluginManagement.selectedPlugin}
          selectedWorkingState={pluginManagement.selectedWorkingState}
          rows={pluginManagement.rows}
          filters={pluginManagement.filters}
          counts={pluginManagement.counts}
          warnings={pluginManagement.warnings}
          loading={pluginManagement.loading}
          readOnly={pluginManagement.readOnly}
          dirty={pluginManagement.dirty}
          saving={pluginManagement.saving}
          pendingActionPlugin={pluginManagement.pendingActionPlugin}
          error={pluginManagement.error}
          onProfileChange={pluginManagement.setSelectedProfile}
          onSelectPlugin={pluginManagement.setSelectedPluginName}
          onFiltersChange={pluginManagement.setFilters}
          onRefresh={() => void pluginManagement.refresh()}
          onEnable={(pluginName) => void pluginManagement.enablePluginSafely(pluginName)}
          onDisable={(pluginName) => void pluginManagement.disablePlugin(pluginName)}
          onMove={(pluginName, direction) => void pluginManagement.movePlugin(pluginName, direction)}
          onUpdateSettings={pluginManagement.updateSelectedPluginSettings}
          onSave={() => void pluginManagement.saveChanges()}
          onDiscard={pluginManagement.discardChanges}
        />
      )}
    </div>
  );
}
