import { getCopy } from "../i18n";
import type { DashboardView, Locale } from "../types";

interface ViewTabsProps {
  activeView: DashboardView;
  locale: Locale;
  onChange: (view: DashboardView) => void;
}

export function ViewTabs({ activeView, locale, onChange }: ViewTabsProps) {
  const copy = getCopy(locale);
  return (
    <div className="view-tabs" role="tablist" aria-label={copy.toolbar.title}>
      {(["traffic", "plugins"] as const).map((view) => (
        <button
          key={view}
          className={`view-tabs__tab${activeView === view ? " view-tabs__tab--active" : ""}`}
          onClick={() => onChange(view)}
          role="tab"
          aria-selected={activeView === view}
          type="button"
        >
          {view === "traffic" ? copy.toolbar.traffic : copy.toolbar.plugins}
        </button>
      ))}
    </div>
  );
}
