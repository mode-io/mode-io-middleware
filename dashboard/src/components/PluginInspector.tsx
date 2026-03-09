import { useEffect, useState } from "react";

import { fmtBoolean, fmtPluginMode, fmtPluginSource, fmtPluginValidation, getCopy } from "../i18n";
import type { PluginWorkingState } from "../pluginManagement";
import type { Locale, PluginInventoryItem, PluginProfileOverride } from "../types";

interface PluginInspectorProps {
  locale: Locale;
  plugin: PluginInventoryItem | null;
  workingState: PluginWorkingState | null;
  readOnly: boolean;
  dirty: boolean;
  saving: boolean;
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

export function PluginInspector({
  locale,
  plugin,
  workingState,
  readOnly,
  dirty,
  saving,
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

  if (!plugin || !workingState) {
    return (
      <div className="inspector-panel inspector-panel--empty">
        <div className="inspector-empty-state">
          <strong>{copy.plugins.inspectorTitle}</strong>
          <p>{copy.inspector.emptyNote}</p>
        </div>
      </div>
    );
  }

  const docsUrl = typeof plugin.metadata.documentation_url === "string"
    ? plugin.metadata.documentation_url
    : typeof plugin.metadata.homepage === "string"
      ? plugin.metadata.homepage
      : "";
  const invalid = plugin.validation.status === "error";

  return (
    <div className="inspector-panel">
      <div className="pane-header pane-header--inspector">
        <div>
          <strong className="pane-header__title">{copy.plugins.inspectorTitle}</strong>
          <div className="pane-header__meta">{copy.plugins.inspectorSubtitle}</div>
        </div>
        <div className="plugin-inspector__actions">
          {workingState.enabled ? (
            <button className="btn btn--quiet" onClick={() => onDisable(plugin.name)} type="button" disabled={readOnly || saving}>
              {copy.plugins.disable}
            </button>
          ) : (
            <button className="btn btn--quiet" onClick={() => onEnable(plugin.name)} type="button" disabled={readOnly || saving || invalid}>
              {copy.plugins.enable}
            </button>
          )}
          <button className="btn" onClick={onSave} type="button" disabled={readOnly || saving || !dirty || invalid}>
            {saving ? copy.plugins.saving : copy.plugins.save}
          </button>
        </div>
      </div>

      <div className="plugin-inspector__body">
        {!readOnly && dirty ? <div className="plugin-banner plugin-banner--draft">{copy.plugins.pendingChanges}</div> : null}
        {readOnly ? <div className="plugin-banner plugin-banner--warn">{copy.plugins.readOnly}</div> : null}
        {workingState.requiresReview && !workingState.enabled ? <div className="plugin-banner plugin-banner--warn">{copy.plugins.requiresReview}</div> : null}
        {!workingState.enabled && workingState.hasRememberedSettings ? <div className="plugin-banner">{copy.plugins.remembered}</div> : null}
        {invalid ? <div className="plugin-banner plugin-banner--danger">{copy.plugins.invalidPlugin}</div> : null}

        <section className="plugin-section">
          <div className="plugin-section__title">{copy.plugins.overview}</div>
          <div className="plugin-field-grid">
            <Field label={copy.plugins.manifestName} value={plugin.name} />
            <Field label={copy.plugins.version} value={plugin.version || copy.plugins.none} />
            <Field label={copy.plugins.source} value={fmtPluginSource(plugin.sourceKind, locale)} />
            <Field label={copy.plugins.hooks} value={plugin.hooks.join(", ") || copy.plugins.none} />
            <Field label={copy.plugins.description} value={plugin.description || copy.plugins.none} />
          </div>
        </section>

        <section className="plugin-section">
          <div className="plugin-section__title">{copy.plugins.profileState}</div>
          <div className="plugin-field-grid">
            <Field label={copy.plugins.selectedProfile} value={workingState.enabled ? copy.plugins.enabledForProfile : copy.plugins.disabledForProfile} />
            <Field label={copy.plugins.chainPosition} value={workingState.position != null ? String(workingState.position + 1) : copy.plugins.none} />
            <Field label={copy.plugins.mode} value={fmtPluginMode(workingState.effectiveMode, locale)} />
            <Field label={copy.plugins.grants} value={`patch ${fmtBoolean(workingState.effectiveCapabilitiesGrant.can_patch, locale)} / block ${fmtBoolean(workingState.effectiveCapabilitiesGrant.can_block, locale)}`} />
            <Field label={copy.plugins.poolSize} value={String(workingState.effectivePoolSize)} />
            <Field label={copy.plugins.timeouts} value={Object.keys(workingState.effectiveTimeoutMs).length > 0 ? Object.entries(workingState.effectiveTimeoutMs).map(([hook, value]) => `${hook}=${value}`).join(", ") : copy.plugins.timeoutUnset} />
          </div>
        </section>

        <section className="plugin-section">
          <div className="plugin-section__title">{copy.plugins.settings}</div>
          <div className="plugin-settings-grid">
            <label className="filter-field">
              <span className="filter-field__label">{copy.plugins.mode}</span>
              <select value={workingState.effectiveMode} aria-label={copy.plugins.mode} disabled={readOnly} onChange={(event) => onUpdate({ mode: event.target.value })}>
                <option value="observe">{fmtPluginMode("observe", locale)}</option>
                <option value="assist">{fmtPluginMode("assist", locale)}</option>
                <option value="enforce">{fmtPluginMode("enforce", locale)}</option>
              </select>
              <span className="plugin-settings__hint">{copy.plugins.modeHint}</span>
            </label>

            <label className={`plugin-checkbox${!plugin.declaredCapabilities.canPatch ? " plugin-checkbox--disabled" : ""}`}>
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
              <small>{copy.plugins.patchHint}</small>
            </label>

            <label className={`plugin-checkbox${!plugin.declaredCapabilities.canBlock ? " plugin-checkbox--disabled" : ""}`}>
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
              <small>{copy.plugins.blockHint}</small>
            </label>

            <label className="filter-field">
              <span className="filter-field__label">{copy.plugins.poolSize}</span>
              <input
                className="input input--numeric"
                type="text"
                min={1}
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
          </div>

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
        </section>

        <section className="plugin-section">
          <div className="plugin-section__title">{copy.plugins.declaredCapabilities}</div>
          <div className="plugin-field-grid">
            <Field label={copy.plugins.canPatch} value={fmtBoolean(plugin.declaredCapabilities.canPatch, locale)} />
            <Field label={copy.plugins.canBlock} value={fmtBoolean(plugin.declaredCapabilities.canBlock, locale)} />
            <Field label={copy.plugins.needsNetwork} value={fmtBoolean(plugin.declaredCapabilities.needsNetwork, locale)} />
            <Field label={copy.plugins.needsRawBody} value={fmtBoolean(plugin.declaredCapabilities.needsRawBody, locale)} />
          </div>
        </section>

        <section className="plugin-section">
          <div className="plugin-section__title">{copy.plugins.validation}</div>
          <div className="plugin-validation-stack">
            <div className={`plugin-health plugin-health--${plugin.validation.status}`}>{fmtPluginValidation(plugin.validation.status, locale)}</div>
            {plugin.validation.warnings.map((warning) => (
              <div key={warning} className="plugin-banner plugin-banner--warn">{warning}</div>
            ))}
            {plugin.validation.errors.map((validationError) => (
              <div key={validationError} className="plugin-banner plugin-banner--danger">{validationError}</div>
            ))}
            {plugin.validation.warnings.length === 0 && plugin.validation.errors.length === 0 ? <div className="plugin-banner">{copy.plugins.none}</div> : null}
          </div>
        </section>

        <section className="plugin-section">
          <div className="plugin-section__title">{copy.plugins.usage}</div>
          <div className="plugin-field-grid">
            <Field label={copy.plugins.calls} value={String(plugin.stats.calls)} />
            <Field label={copy.plugins.errors} value={String(plugin.stats.errors)} />
            <Field label={copy.plugins.actions} value={Object.entries(plugin.stats.actions).map(([key, value]) => `${key}:${value}`).join(", ") || copy.plugins.none} />
          </div>
        </section>

        <section className="plugin-section">
          <div className="plugin-section__title">{copy.plugins.files}</div>
          <div className="plugin-field-grid">
            <Field label={copy.plugins.pathPlugin} value={plugin.pluginDir || copy.plugins.none} />
            <Field label={copy.plugins.pathManifest} value={plugin.manifestPath || copy.plugins.none} />
            <Field label={copy.plugins.pathHost} value={plugin.hostPath || copy.plugins.none} />
            <Field label={copy.plugins.pathReadme} value={plugin.readmePath || copy.plugins.none} />
          </div>
        </section>

        {docsUrl ? (
          <section className="plugin-section">
            <div className="plugin-section__title">{copy.plugins.docs}</div>
            <a className="plugin-link mono" href={docsUrl} target="_blank" rel="noreferrer">
              {copy.plugins.openDocs}
            </a>
          </section>
        ) : null}

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
