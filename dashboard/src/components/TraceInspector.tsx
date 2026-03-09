import { useState } from "react";

import { fmtAction, fmtClient, fmtImpact, fmtLifecycle, fmtStatus, getCopy } from "../i18n";
import { summarizePluginLabel } from "../traceInsights";
import type { ChangeSummary, EventDetail, Locale } from "../types";
import { formatDuration, formatTimestamp, stableJson } from "../utils";

type Tab = "request" | "response" | "hooks" | "context" | "raw";

interface TraceInspectorProps {
  detail: EventDetail | null;
  loading: boolean;
  locale: Locale;
  onOpenPlugin?: (pluginName: string, profile: string) => void;
}

function ChangeBadge({ change, locale }: { change: ChangeSummary; locale: Locale }) {
  const copy = getCopy(locale);
  if (!change.changed) {
    return <span className="change-badge change-badge--none">{copy.inspector.unchanged}</span>;
  }
  return (
    <span className="change-badge change-badge--changed">
      +{change.addCount} -{change.removeCount} ~{change.replaceCount}
      {change.samplePaths.length > 0 ? (
        <span className="change-badge__paths">
          {change.samplePaths.slice(0, 3).map((p) => (
            <code key={p}>{p}</code>
          ))}
        </span>
      ) : null}
    </span>
  );
}

function JsonSplit({
  beforeLabel,
  afterLabel,
  before,
  after,
  emptyLabel,
}: {
  beforeLabel: string;
  afterLabel: string;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  emptyLabel: string;
}) {
  return (
    <div className="json-split">
      <div className="json-split__pane">
        <div className="json-split__label">{beforeLabel}</div>
        <pre className="json-block">{stableJson(before, emptyLabel)}</pre>
      </div>
      <div className="json-split__pane">
        <div className="json-split__label">{afterLabel}</div>
        <pre className="json-block">{stableJson(after, emptyLabel)}</pre>
      </div>
    </div>
  );
}

function ChangePanel({
  change,
  before,
  after,
  locale,
}: {
  change: ChangeSummary;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  locale: Locale;
}) {
  const copy = getCopy(locale);
  return (
    <div className="inspector-tab-content">
      <div className="inspector-section-header">
        <span>{copy.inspector.change}</span>
        <ChangeBadge change={change} locale={locale} />
      </div>
      <JsonSplit beforeLabel={copy.inspector.before} afterLabel={copy.inspector.after} before={before} after={after} emptyLabel={copy.inspector.notCaptured} />
    </div>
  );
}

function HooksTab({ detail, locale }: { detail: EventDetail; locale: Locale }) {
  const copy = getCopy(locale);
  if (detail.hookExecutions.length === 0) {
    return <div className="inspector-tab-content inspector-empty">{copy.inspector.noHooks}</div>;
  }
  return (
    <div className="inspector-tab-content">
      <table className="hooks-table">
        <thead>
          <tr>
            <th>{copy.inspector.plugin}</th>
            <th>{copy.inspector.hook}</th>
            <th>{copy.inspector.reported}</th>
            <th>{copy.inspector.effective}</th>
            <th>{copy.inspector.time}</th>
          </tr>
        </thead>
        <tbody>
          {detail.hookExecutions.map((h, i) => (
            <tr key={`${h.pluginName}-${h.hookName}-${i}`} className={h.errored ? "hooks-table__row--error" : ""}>
              <td className="mono">{h.pluginName}</td>
              <td className="mono">{h.hookName}</td>
              <td>{h.reportedAction ? fmtAction(h.reportedAction, locale) : "-"}</td>
              <td>
                <span className={`action-tag action-tag--${h.effectiveAction}`}>{fmtAction(h.effectiveAction, locale)}</span>
              </td>
              <td className="mono">{formatDuration(h.durationMs, locale)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ContextTab({ detail, locale }: { detail: EventDetail; locale: Locale }) {
  const copy = getCopy(locale);
  return (
    <div className="inspector-tab-content context-grid">
      <div>
        <div className="context-label">{copy.inspector.preActions}</div>
        <div className="context-value">
          {detail.preActions.length === 0
            ? copy.inspector.none
            : detail.preActions.map((a) => (
                <code key={a} className="action-chip">
                  {a}
                </code>
              ))}
        </div>
      </div>
      <div>
        <div className="context-label">{copy.inspector.postActions}</div>
        <div className="context-value">
          {detail.postActions.length === 0
            ? copy.inspector.none
            : detail.postActions.map((a) => (
                <code key={a} className="action-chip">
                  {a}
                </code>
              ))}
        </div>
      </div>
      <div>
        <div className="context-label">{copy.inspector.degraded}</div>
        <div className="context-value">
          {detail.degraded.length === 0 ? copy.inspector.none : detail.degraded.join(", ")}
        </div>
      </div>
      {detail.stream ? (
        <div>
          <div className="context-label">{copy.inspector.stream}</div>
          <div className="context-value mono">
            {detail.streamSummary.eventCount} {copy.inspector.events}
            {detail.streamSummary.blockedDuringStream ? ` / ${copy.inspector.streamBlocked}` : ""}
            {detail.streamSummary.doneReceived ? ` / ${copy.inspector.streamDone}` : ""}
          </div>
        </div>
      ) : null}
      {detail.blockMessage ? (
        <div className="context-alert context-alert--block">
          <strong>{copy.inspector.blockReason}:</strong> {detail.blockMessage}
        </div>
      ) : null}
      {detail.errorMessage ? (
        <div className="context-alert context-alert--error">
          <strong>{copy.inspector.errorMessage}:</strong> {detail.errorMessage}
        </div>
      ) : null}
      {detail.findings.length > 0 ? (
        <div>
          <div className="context-label">{copy.inspector.findings}</div>
          <pre className="json-block json-block--compact">{stableJson(detail.findings)}</pre>
        </div>
      ) : null}
    </div>
  );
}

function RawTab({ detail }: { detail: EventDetail }) {
  return (
    <div className="inspector-tab-content">
      <pre className="json-block json-block--full">{stableJson(detail)}</pre>
    </div>
  );
}

export function TraceInspector({ detail, loading, locale, onOpenPlugin }: TraceInspectorProps) {
  const [activeTab, setActiveTab] = useState<Tab>("request");
  const copy = getCopy(locale);

  if (loading) {
    return <div className="inspector-panel inspector-panel--empty">{copy.inspector.loading}</div>;
  }

  if (!detail) {
    return (
      <div className="inspector-panel inspector-panel--empty">
        <div className="inspector-empty-state">
          <strong>{copy.inspector.emptyTitle}</strong>
          <p>{copy.inspector.emptyNote}</p>
        </div>
      </div>
    );
  }

  const tabs: { key: Tab; label: string }[] = [
    { key: "request", label: copy.inspector.tabRequest },
    { key: "response", label: copy.inspector.tabResponse },
    { key: "hooks", label: copy.inspector.tabHooks },
    { key: "context", label: copy.inspector.tabContext },
    { key: "raw", label: copy.inspector.tabRaw },
  ];
  const pluginSummary = summarizePluginLabel(detail.primaryPlugin, detail.pluginNames);
  const metadataColumns = [
    { key: "status", label: copy.table.status, value: fmtStatus(detail.status, locale) },
    { key: "client", label: copy.inspector.client, value: fmtClient(detail.clientName, locale) },
    { key: "lifecycle", label: copy.inspector.lifecycle, value: fmtLifecycle(detail.lifecycle, locale) },
    { key: "impact", label: copy.inspector.impact, value: fmtImpact(detail.impact, locale) },
    { key: "pluginSummary", label: copy.inspector.pluginSummary, value: pluginSummary },
    { key: "duration", label: copy.table.duration, value: formatDuration(detail.durationMs, locale) },
    { key: "upstream", label: copy.inspector.upstream, value: detail.upstreamDurationMs != null ? formatDuration(detail.upstreamDurationMs, locale) : "-" },
    { key: "profile", label: copy.inspector.profile, value: detail.profile },
    { key: "time", label: copy.table.time, value: formatTimestamp(detail.startedAt, locale) },
  ] as const;

  return (
    <div className="inspector-panel">
      <div className="pane-header pane-header--inspector">
        <div>
          <strong className="pane-header__title">{copy.inspector.title}</strong>
          <div className="pane-header__meta">{copy.inspector.subtitle}</div>
        </div>
      </div>

      <div className="inspector-header">
        <div className="inspector-summary">
          <div className="inspector-summary__primary">
            <span className={`status-dot status-dot--${detail.status}`} />
            <strong className="mono">{detail.requestId}</strong>
          </div>
          <div className="inspector-meta-table-wrap">
            <table className="inspector-meta-table">
              <colgroup>
                <col className="inspector-meta-table__col inspector-meta-table__col--status" />
                <col className="inspector-meta-table__col inspector-meta-table__col--client" />
                <col className="inspector-meta-table__col inspector-meta-table__col--lifecycle" />
                <col className="inspector-meta-table__col inspector-meta-table__col--impact" />
                <col className="inspector-meta-table__col inspector-meta-table__col--plugin" />
                <col className="inspector-meta-table__col inspector-meta-table__col--duration" />
                <col className="inspector-meta-table__col inspector-meta-table__col--upstream" />
                <col className="inspector-meta-table__col inspector-meta-table__col--profile" />
                <col className="inspector-meta-table__col inspector-meta-table__col--time" />
              </colgroup>
              <thead>
                <tr>
                  {metadataColumns.map((column) => (
                    <th key={column.key} scope="col">
                      {column.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                <tr>
                  {metadataColumns.map((column) => (
                    <td key={column.key} title={column.value}>
                      {column.key === "pluginSummary" && detail.primaryPlugin && onOpenPlugin ? (
                        <button
                          className="link-inline"
                          onClick={() => onOpenPlugin(detail.primaryPlugin as string, detail.profile)}
                          type="button"
                        >
                          {column.value}
                        </button>
                      ) : (
                        column.value
                      )}
                    </td>
                  ))}
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <div className="inspector-tabs" role="tablist">
        {tabs.map((tab) => (
          <button
            key={tab.key}
            className={`inspector-tab${activeTab === tab.key ? " inspector-tab--active" : ""}`}
            onClick={() => setActiveTab(tab.key)}
            role="tab"
            aria-selected={activeTab === tab.key}
            type="button"
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div className="inspector-body">
        {activeTab === "request" ? <ChangePanel change={detail.request.change} before={detail.request.before} after={detail.request.after} locale={locale} /> : null}
        {activeTab === "response" ? <ChangePanel change={detail.response.change} before={detail.response.before} after={detail.response.after} locale={locale} /> : null}
        {activeTab === "hooks" ? <HooksTab detail={detail} locale={locale} /> : null}
        {activeTab === "context" ? <ContextTab detail={detail} locale={locale} /> : null}
        {activeTab === "raw" ? <RawTab detail={detail} /> : null}
      </div>
    </div>
  );
}
