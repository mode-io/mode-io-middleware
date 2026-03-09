import { QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import { PluginWorkspace } from "./components/PluginWorkspace";
import { TrafficWorkspace } from "./components/TrafficWorkspace";
import { ViewTabs } from "./components/ViewTabs";
import { useLocalStorageState } from "./hooks/useLocalStorageState";
import { usePluginManagementState } from "./hooks/usePluginManagementState";
import { useTrafficMonitorState } from "./hooks/useDashboardState";
import { getCopy } from "./i18n";
import { createDashboardQueryClient } from "./queryClient";
import type { DashboardView, Locale, ThemeMode } from "./types";

function resolveInitialView(): DashboardView {
  return "traffic";
}

function resolveInitialLocale(): Locale {
  return navigator.language.toLowerCase().startsWith("zh") ? "zh" : "en";
}

function resolveInitialTheme(): ThemeMode {
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "night" : "day";
}

function AppShell() {
  const [locale, setLocale] = useLocalStorageState<Locale>("modeio-dashboard-locale", resolveInitialLocale, {
    serialize: (value) => value,
    deserialize: (raw) => (raw === "en" || raw === "zh" ? raw : null),
  });
  const [theme, setTheme] = useLocalStorageState<ThemeMode>("modeio-dashboard-theme", resolveInitialTheme, {
    serialize: (value) => value,
    deserialize: (raw) => (raw === "day" || raw === "night" ? raw : null),
  });
  const [activeView, setActiveView] = useLocalStorageState<DashboardView>("modeio-dashboard-view", resolveInitialView, {
    serialize: (value) => value,
    deserialize: (raw) => (raw === "traffic" || raw === "plugins" ? raw : null),
  });
  const copy = useMemo(() => getCopy(locale), [locale]);
  const trafficMonitor = useTrafficMonitorState(locale);
  const pluginManagement = usePluginManagementState(locale);

  useEffect(() => {
    document.documentElement.lang = locale === "zh" ? "zh-CN" : "en";
    document.title = locale === "zh" ? "ModeIO 监控台" : "ModeIO Monitor";
  }, [locale]);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

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
          </div>
          <ViewTabs activeView={activeView} locale={locale} onChange={setActiveView} />
        </div>
        <div className="toolbar__right">
          <button className="btn" onClick={() => (activeView === "traffic" ? void trafficMonitor.refreshOverview() : void pluginManagement.refresh())} type="button">
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
        <TrafficWorkspace locale={locale} controller={trafficMonitor} onOpenPlugin={openPlugin} />
      ) : (
        <PluginWorkspace locale={locale} controller={pluginManagement} />
      )}
    </div>
  );
}

export function App() {
  const [queryClient] = useState(() => createDashboardQueryClient());

  return (
    <QueryClientProvider client={queryClient}>
      <AppShell />
    </QueryClientProvider>
  );
}
