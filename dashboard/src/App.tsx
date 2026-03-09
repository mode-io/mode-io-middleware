import { useEffect, useMemo, useState } from "react";

import { StatsBar } from "./components/StatsBar";
import { TraceInspector } from "./components/TraceInspector";
import { TraceTable } from "./components/TraceTable";
import { useDashboardState } from "./hooks/useDashboardState";
import { getCopy } from "./i18n";
import type { Locale } from "./types";

type ThemeMode = "day" | "night";

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
  } = useDashboardState(locale);

  useEffect(() => {
    document.documentElement.lang = locale === "zh" ? "zh-CN" : "en";
    document.title = locale === "zh" ? "ModeIO 监控台" : "ModeIO Monitor";
    window.localStorage.setItem("modeio-dashboard-locale", locale);
  }, [locale]);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    window.localStorage.setItem("modeio-dashboard-theme", theme);
  }, [theme]);

  return (
    <div className="shell">
      <header className="toolbar">
        <div className="toolbar__left">
          <strong className="toolbar__title">{copy.toolbar.title}</strong>
          {usingDemo ? <span className="badge badge--muted">{copy.toolbar.demoBadge}</span> : null}
        </div>
        <div className="toolbar__right">
          <button className="btn" onClick={() => void refreshOverview()} type="button">
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
        />
        <div className="master-detail__divider" aria-hidden="true" />
        <TraceInspector detail={detail} loading={detailLoading} locale={locale} />
      </main>
    </div>
  );
}
