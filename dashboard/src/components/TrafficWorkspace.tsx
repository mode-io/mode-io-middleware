import type { TrafficMonitorController } from "../hooks/useDashboardState";
import type { Locale } from "../types";
import { StatsBar } from "./StatsBar";
import { TraceInspector } from "./TraceInspector";
import { TraceTable } from "./TraceTable";

interface TrafficWorkspaceProps {
  locale: Locale;
  controller: TrafficMonitorController;
  onOpenPlugin: (pluginName: string, profile: string) => void;
}

export function TrafficWorkspace({ locale, controller, onOpenPlugin }: TrafficWorkspaceProps) {
  return (
    <>
      {controller.error ? <div className="error-strip">{controller.error}</div> : null}
      <StatsBar locale={locale} stats={controller.stats} filters={controller.filters} onFiltersChange={controller.setFilters} />
      <main className="master-detail">
        <TraceTable
          events={controller.events}
          filters={controller.filters}
          locale={locale}
          loading={controller.overviewLoading}
          selectedRequestId={controller.selectedRequestId}
          onFiltersChange={controller.setFilters}
          onSelect={controller.setSelectedRequestId}
          usingDemo={controller.usingDemo}
          onOpenPlugin={onOpenPlugin}
        />
        <div className="master-detail__divider" aria-hidden="true" />
        <TraceInspector detail={controller.detail} loading={controller.detailLoading} locale={locale} onOpenPlugin={onOpenPlugin} />
      </main>
    </>
  );
}
