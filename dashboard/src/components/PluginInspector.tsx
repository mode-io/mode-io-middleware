import { useEffect, useMemo, useState } from "react";

import { buildPluginInspectorActionState } from "../features/plugins/actionState";
import { fmtBoolean, fmtPluginMode, fmtPluginSource, fmtPluginValidation, getCopy } from "../i18n";
import type { PluginWorkingState } from "../pluginManagement";
import type { Locale, PluginInventoryItem, PluginProfileOverride } from "../types";
import { Select } from "./Select";

interface PluginInspectorProps {
  locale: Locale;
  plugin: PluginInventoryItem | null;
  workingState: PluginWorkingState | null;
  readOnly: boolean;
  dirty: boolean;
  saving: boolean;
  quickActionsDisabled: boolean;
  onEnable: (pluginName: string) => void;
  onDisable: (pluginName: string) => void;
  onUpdate: (update: PluginProfileOverride) => void;
  onSave: () => void;
  onDiscard: () => void;
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="plugin-field">
      <div className="plugin-field__label">{label}</div>
      <div className="plugin-field__value" title={value}>{value}</div>
    </div>
  );
}

function TimeoutFields({
  hooks,
  timeouts,
  onUpdate,
  disabled,
  locale,
}: {
  hooks: string[];
  timeouts: Record<string, number>;
  onUpdate: (nextTimeouts: Record<string, number>) => void;
  disabled: boolean;
  locale: Locale;
}) {
  const copy = getCopy(locale);
  const uniqueHooks = Array.from(new Set(hooks));

  return (
    <div className="plugin-timeout-grid">
      {uniqueHooks.map((hookName) => (
        <label key={hookName} className="filter-field">
          <span className="filter-field__label mono">{hookName}</span>
          <input
            className="input input--numeric"
            type="number"
            min={1}
            value={timeouts[hookName] ?? ""}
            placeholder={copy.plugins.timeoutUnset}
            aria-label={hookName}
            disabled={disabled}
            onChange={(event) => {
              const raw = event.target.value.trim();
              if (!raw) {
                const next = { ...timeouts };
                delete next[hookName];
                onUpdate(next);
                return;
              }
              const parsed = Number.parseInt(raw, 10);
              if (!Number.isFinite(parsed) || parsed <= 0) {
                return;
              }
              onUpdate({ ...timeouts, [hookName]: parsed });
            }}
          />
        </label>
      ))}
    </div>
  );
}

function calloutTone({ invalid, requiresReview, enabled }: { invalid: boolean; requiresReview: boolean; enabled: boolean }) {
  if (invalid) {
    return "danger";
  }
  if (requiresReview) {
    return "warn";
  }
  if (enabled) {
    return "ok";
  }
  return "neutral";
}

export function PluginInspector({
  locale,
  plugin,
  workingState,
  readOnly,
  dirty,
  saving,
  quickActionsDisabled,
  onEnable,
  onDisable,
  onUpdate,
  onSave,
  onDiscard,
}: PluginInspectorProps) {
  const copy = getCopy(locale);
  const [poolSizeInput, setPoolSizeInput] = useState("");

  useEffect(() => {
    setPoolSizeInput(workingState ? String(workingState.effectivePoolSize) : "");
  }, [workingState?.effectivePoolSize, plugin?.name]);

  const docsUrl = typeof plugin?.metadata.documentation_url === "string"
    ? plugin.metadata.documentation_url
    : typeof plugin?.metadata.homepage === "string"
      ? plugin.metadata.homepage
      : "";

  const invalid = plugin?.validation.status === "error";
  const quickActions = plugin && workingState
    ? buildPluginInspectorActionState(plugin, workingState, {
        readOnly,
        actionsDisabled: quickActionsDisabled,
        actionPending: saving,
      })
    : { canEnable: false, canDisable: false };

  const callout = useMemo(() => {
    if (!plugin || !workingState) {
      return null;
    }

    if (invalid) {
      return {
        title: copy.plugins.statusInvalid,
        detail: plugin.validation.errors[0] ?? copy.plugins.invalidPlugin,
      };
    }

    if (workingState.requiresReview) {
      return {
        title: copy.plugins.statusReview,
        detail: workingState.enabled ? copy.plugins.statusEnabledDetail : copy.plugins.requiresReview,
      };
    }

    if (workingState.enabled) {
      return {
        title: copy.plugins.statusSafe,
        detail: copy.plugins.statusEnabledDetail,
      };
    }

    return {
      title: copy.plugins.statusIdle,
      detail: copy.plugins.statusDisabledDetail,
    };
  }, [copy.plugins, invalid, plugin, workingState]);

  if (!plugin || !workingState) {
    return (
      <div className="inspector-panel inspector-panel--empty">
        <div className="inspector-empty-state">
          <strong>{copy.plugins.inspectorTitle}</strong>
          <p>{copy.plugins.selectedHint}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="inspector-panel">
      <div className="pane-header pane-header--inspector">
        <div>
          <strong className="pane-header__title">{copy.plugins.inspectorTitle}</strong>
          <div className="pane-header__meta">{copy.plugins.inspectorSubtitle}</div>
        </div>
        <div className="plugin-inspector__actions">
          {workingState.enabled ? (
            <button className="btn btn--quiet" onClick={() => onDisable(plugin.name)} type="button" disabled={!quickActions.canDisable}>
              {copy.plugins.disable}
            </button>
          ) : (
            <button className="btn btn--quiet" onClick={() => onEnable(plugin.name)} type="button" disabled={!quickActions.canEnable || invalid}>
              {copy.plugins.enable}
            </button>
          )}
        </div>
      </div>

      <div className="plugin-inspector__body">
        <section className="plugin-section plugin-section--hero">
          <div className="plugin-hero">
            <div className="plugin-hero__identity">
              <strong className="plugin-hero__title">{plugin.displayName}</strong>
              <div className="plugin-hero__subtitle mono">{plugin.name}</div>
            </div>
            <div className="plugin-hero__chips">
              <span className={`plugin-state plugin-state--${workingState.enabled ? "enabled" : workingState.requiresReview ? "attention" : "disabled"}`}>
                {workingState.enabled ? copy.plugins.stateEnabled : workingState.requiresReview ? copy.plugins.stateAttention : copy.plugins.stateDisabled}
              </span>
              <span className={`plugin-health plugin-health--${plugin.validation.status}`}>{fmtPluginValidation(plugin.validation.status, locale)}</span>
            </div>
          </div>
          {(invalid || workingState.requiresReview) ? (
            <div className={`plugin-callout plugin-callout--${calloutTone({ invalid, requiresReview: workingState.requiresReview, enabled: workingState.enabled })}`}>
              <div className="plugin-callout__title">{callout?.title}</div>
              <div className="plugin-callout__detail">{callout?.detail}</div>
            </div>
          ) : null}
          {dirty ? <div className="plugin-draft-note mono">{copy.plugins.pendingChanges}</div> : null}
        </section>

        <section className="plugin-section">
          <div className="plugin-section__title">{copy.plugins.details}</div>
          <div className="plugin-field-grid">
            <Field label={copy.plugins.description} value={plugin.description || copy.plugins.none} />
            <Field label={copy.plugins.version} value={plugin.version || copy.plugins.none} />
            <Field label={copy.plugins.hooks} value={plugin.hooks.join(", ") || copy.plugins.none} />
            <Field label={copy.plugins.source} value={fmtPluginSource(plugin.sourceKind, locale)} />
            <Field label={copy.plugins.selectedProfile} value={workingState.enabled ? copy.plugins.enabledForProfile : copy.plugins.disabledForProfile} />
            <Field label={copy.plugins.chainPosition} value={workingState.position != null ? String(workingState.position + 1) : copy.plugins.none} />
            <Field label={copy.plugins.mode} value={fmtPluginMode(workingState.effectiveMode, locale)} />
            <Field label={copy.plugins.grants} value={`patch ${fmtBoolean(workingState.effectiveCapabilitiesGrant.can_patch, locale)} / block ${fmtBoolean(workingState.effectiveCapabilitiesGrant.can_block, locale)}`} />
          </div>
        </section>

        <section className="plugin-section">
          <div className="plugin-section__title">{copy.plugins.quickSettings}</div>
          <div className="plugin-settings-list">
            <div className="filter-field">
              <span className="filter-field__label">{copy.plugins.mode}</span>
              <Select
                value={workingState.effectiveMode}
                options={[
                  { value: "observe", label: fmtPluginMode("observe", locale) },
                  { value: "assist", label: fmtPluginMode("assist", locale) },
                  { value: "enforce", label: fmtPluginMode("enforce", locale) },
                ]}
                onChange={(val) => onUpdate({ mode: val as PluginProfileOverride["mode"] })}
                aria-label={copy.plugins.mode}
                disabled={readOnly}
              />
              <span className="plugin-settings__hint">{copy.plugins.modeHint}</span>
            </div>

            <div className="plugin-caps-row">
              <label className={`plugin-cap-toggle${!plugin.declaredCapabilities.canPatch ? " plugin-cap-toggle--disabled" : ""}`}>
                <input
                  type="checkbox"
                  aria-label={copy.plugins.canPatch}
                  checked={workingState.effectiveCapabilitiesGrant.can_patch}
                  disabled={readOnly || !plugin.declaredCapabilities.canPatch}
                  onChange={(event) => onUpdate({
                    capabilities_grant: {
                      ...workingState.effectiveCapabilitiesGrant,
                      can_patch: event.target.checked,
                    },
                  })}
                />
                <span>{copy.plugins.canPatch}</span>
              </label>
              <label className={`plugin-cap-toggle${!plugin.declaredCapabilities.canBlock ? " plugin-cap-toggle--disabled" : ""}`}>
                <input
                  type="checkbox"
                  aria-label={copy.plugins.canBlock}
                  checked={workingState.effectiveCapabilitiesGrant.can_block}
                  disabled={readOnly || !plugin.declaredCapabilities.canBlock}
                  onChange={(event) => onUpdate({
                    capabilities_grant: {
                      ...workingState.effectiveCapabilitiesGrant,
                      can_block: event.target.checked,
                    },
                  })}
                />
                <span>{copy.plugins.canBlock}</span>
              </label>
            </div>
          </div>
        </section>

        <details className="plugin-details" open={dirty || invalid}>
          <summary className="plugin-details__summary">{copy.plugins.advanced}</summary>
          <div className="plugin-details__body">
            <label className="filter-field filter-field--padded">
              <span className="filter-field__label">{copy.plugins.poolSize}</span>
              <input
                className="input input--numeric"
                type="text"
                inputMode="numeric"
                value={poolSizeInput}
                aria-label={copy.plugins.poolSize}
                disabled={readOnly}
                onChange={(event) => {
                  const nextValue = event.target.value;
                  setPoolSizeInput(nextValue);
                  const parsed = Number.parseInt(nextValue, 10);
                  if (!Number.isFinite(parsed) || parsed <= 0) {
                    return;
                  }
                  onUpdate({ pool_size: parsed });
                }}
                onBlur={() => {
                  if (!poolSizeInput.trim()) {
                    setPoolSizeInput(String(workingState.effectivePoolSize));
                  }
                }}
              />
            </label>
            <div className="plugin-timeout-panel">
              <div className="plugin-timeout-panel__title">{copy.plugins.timeoutOverride}</div>
              <TimeoutFields
                hooks={plugin.hooks}
                timeouts={workingState.effectiveTimeoutMs}
                onUpdate={(nextTimeouts) => onUpdate({ timeout_ms: nextTimeouts })}
                disabled={readOnly}
                locale={locale}
              />
            </div>
            <div className="plugin-field-grid">
              <Field label={copy.plugins.pathPlugin} value={plugin.pluginDir || copy.plugins.none} />
              <Field label={copy.plugins.pathManifest} value={plugin.manifestPath || copy.plugins.none} />
              <Field label={copy.plugins.pathHost} value={plugin.hostPath || copy.plugins.none} />
              <Field label={copy.plugins.pathReadme} value={plugin.readmePath || copy.plugins.none} />
            </div>
            {docsUrl ? (
              <a className="plugin-link mono" href={docsUrl} target="_blank" rel="noreferrer">
                {copy.plugins.openDocs}
              </a>
            ) : null}
          </div>
        </details>

        <details className="plugin-details" open={invalid || plugin.validation.warnings.length > 0}>
          <summary className="plugin-details__summary">{copy.plugins.diagnostics}</summary>
          <div className="plugin-details__body">
            <section className="plugin-section plugin-section--nested">
              <div className="plugin-section__title">{copy.plugins.validation}</div>
              <div className="plugin-validation-stack">
                <div className={`plugin-health plugin-health--${plugin.validation.status}`}>{fmtPluginValidation(plugin.validation.status, locale)}</div>
                {plugin.validation.warnings.map((warning) => (
                  <div key={warning} className="plugin-callout plugin-callout--warn">
                    <div className="plugin-callout__title">{copy.plugins.issue}</div>
                    <div className="plugin-callout__detail">{warning}</div>
                  </div>
                ))}
                {plugin.validation.errors.map((validationError) => (
                  <div key={validationError} className="plugin-callout plugin-callout--danger">
                    <div className="plugin-callout__title">{copy.plugins.issue}</div>
                    <div className="plugin-callout__detail">{validationError}</div>
                  </div>
                ))}
                {plugin.validation.warnings.length === 0 && plugin.validation.errors.length === 0 ? <div className="plugin-field__value">{copy.plugins.none}</div> : null}
              </div>
            </section>

            <section className="plugin-section plugin-section--nested">
              <div className="plugin-section__title">{copy.plugins.usage}</div>
              <div className="plugin-field-grid">
                <Field label={copy.plugins.calls} value={String(plugin.stats.calls)} />
                <Field label={copy.plugins.errors} value={String(plugin.stats.errors)} />
                <Field label={copy.plugins.actionsShort} value={Object.entries(plugin.stats.actions).map(([key, value]) => `${key}:${value}`).join(", ") || copy.plugins.none} />
                <Field label={copy.plugins.declaredCapabilities} value={`patch ${fmtBoolean(plugin.declaredCapabilities.canPatch, locale)} / block ${fmtBoolean(plugin.declaredCapabilities.canBlock, locale)}`} />
              </div>
            </section>
          </div>
        </details>

        {!readOnly && dirty ? (
          <div className="plugin-inspector__footer">
            <span className="mono">{copy.plugins.activeDraft}</span>
            <div className="plugin-inspector__footer-actions">
              <button className="btn btn--quiet" onClick={onDiscard} type="button" disabled={saving}>
                {copy.plugins.discard}
              </button>
              <button className="btn" onClick={onSave} type="button" disabled={saving || invalid}>
                {saving ? copy.plugins.saving : copy.plugins.save}
              </button>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}
