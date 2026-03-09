import { getCopy } from "../i18n";
import type { PluginWorkspaceController } from "../hooks/usePluginManagementState";
import type { Locale } from "../types";
import { PluginInspector } from "./PluginInspector";
import { PluginList } from "./PluginList";
import { PluginToolbar } from "./PluginToolbar";

interface PluginWorkspaceProps {
  locale: Locale;
  controller: PluginWorkspaceController;
}

export function PluginWorkspace({ locale, controller }: PluginWorkspaceProps) {
  const copy = getCopy(locale);
  const {
    runtime,
    profiles,
    selectedProfile,
    selectedPluginName,
    selectedPlugin,
    selectedWorkingState,
    rows,
    filters,
    counts,
    warnings,
    loading,
    readOnly,
    dirty,
    saving,
    quickActionsDisabled,
    pendingActionPlugin,
    pendingIntent,
    selectionHiddenByFilter,
    error,
  } = controller;
  const pendingIntentLabel = pendingIntent
    ? pendingIntent.type === "switch-profile"
      ? copy.plugins.pendingSwitchProfile.replace("{target}", pendingIntent.profileName)
      : copy.plugins.pendingFocusPlugin.replace("{target}", pendingIntent.pluginName)
    : null;

  return (
    <>
      <PluginToolbar
        locale={locale}
        runtime={runtime}
        profiles={profiles}
        selectedProfile={selectedProfile}
        filters={filters}
        loading={loading}
        counts={counts}
        onProfileChange={controller.setSelectedProfile}
        onFiltersChange={controller.setFilters}
        onRefresh={controller.refresh}
      />

      {readOnly ? <div className="error-strip">{copy.plugins.readOnly}</div> : null}
      {pendingIntent ? (
        <div className="warning-strip plugin-pending-intent">
          <span>{pendingIntentLabel}</span>
          <div className="plugin-pending-intent__actions">
            <button className="btn btn--quiet" type="button" onClick={() => void controller.confirmPendingIntent("discard")}>
              {copy.plugins.discardAndContinue}
            </button>
            <button className="btn btn--quiet" type="button" onClick={() => void controller.confirmPendingIntent("save")} disabled={saving}>
              {copy.plugins.saveAndContinue}
            </button>
            <button className="btn btn--quiet" type="button" onClick={controller.cancelPendingIntent}>
              {copy.plugins.stayHere}
            </button>
          </div>
        </div>
      ) : null}
      {warnings.map((warning) => (
        <div key={warning} className="warning-strip">
          {warning}
        </div>
      ))}
      {error ? <div className="error-strip">{error}</div> : null}
      {quickActionsDisabled && !readOnly && dirty ? <div className="warning-strip">{copy.plugins.quickActionsLocked}</div> : null}
      {selectionHiddenByFilter ? <div className="warning-strip">{copy.plugins.currentSelectionMissing}</div> : null}

      <main className="master-detail master-detail--plugins">
        <PluginList
          locale={locale}
          rows={rows}
          selectedProfile={selectedProfile}
          selectedPluginName={selectedPluginName}
          loading={loading}
          readOnly={readOnly}
          actionsDisabled={quickActionsDisabled}
          pendingActionPlugin={pendingActionPlugin}
          onSelect={controller.setSelectedPluginName}
          onEnable={controller.enablePluginSafely}
          onDisable={controller.disablePlugin}
          onMove={controller.movePlugin}
        />
        <div className="master-detail__divider" aria-hidden="true" />
        <PluginInspector
          locale={locale}
          plugin={selectedPlugin}
          workingState={selectedWorkingState}
          readOnly={readOnly}
          dirty={dirty}
          saving={saving}
          quickActionsDisabled={quickActionsDisabled}
          onEnable={controller.enablePluginSafely}
          onDisable={controller.disablePlugin}
          onUpdate={controller.updateSelectedPluginSettings}
          onSave={() => void controller.saveChanges()}
          onDiscard={controller.discardChanges}
        />
      </main>
    </>
  );
}
