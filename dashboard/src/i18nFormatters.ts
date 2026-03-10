import { COPY } from "./i18nCatalog";
import type { Locale } from "./types";

function getCopy(locale: Locale) {
  return COPY[locale];
}

export function fmtStatus(status: string, locale: Locale): string {
  const c = getCopy(locale).common;
  const map: Record<string, string> = { completed: c.completed, blocked: c.blocked, error: c.error, stream_completed: c.streamCompleted };
  return map[status] ?? status;
}

export function fmtClient(clientName: string, locale: Locale): string {
  const c = getCopy(locale).common;
  const map: Record<string, string> = {
    claude_code: c.claudeCode,
    codex: c.codex,
    opencode: c.opencode,
    openclaw: c.openclaw,
  };
  return map[clientName] ?? c.unknown;
}

export function deriveDirection(lifecycle: string): string {
  if (lifecycle === "pre_request") return "inbound";
  if (lifecycle === "post_response" || lifecycle === "stream") return "outbound";
  if (lifecycle === "pre_and_post" || lifecycle === "pre_and_stream") return "both";
  return "idle";
}

export function fmtLifecycle(lifecycle: string, locale: Locale): string {
  const c = getCopy(locale).common;
  const map: Record<string, string> = {
    idle: c.dirIdle,
    inbound: c.dirInbound,
    outbound: c.dirOutbound,
    both: c.dirBoth,
  };
  return map[deriveDirection(lifecycle)] ?? (lifecycle || c.unknown);
}

export function deriveResult(status: string, impact: string): string {
  if (status === "blocked") return "denied";
  if (status === "error") return "error";
  if (impact === "modified" || impact === "mixed") return "edited";
  if (impact === "warned") return "flagged";
  return "clean";
}

export function fmtResult(status: string, impact: string, locale: Locale): string {
  const c = getCopy(locale).common;
  const map: Record<string, string> = {
    clean: c.impactClean,
    edited: c.impactEdited,
    denied: c.impactDenied,
    flagged: c.impactFlagged,
    error: c.impactError,
  };
  return map[deriveResult(status, impact)] ?? status;
}

export function fmtAction(action: string, locale: Locale): string {
  const c = getCopy(locale).common;
  const map: Record<string, string> = { allow: c.allow, modify: c.modify, warn: c.warn, block: c.block };
  return map[action] ?? action;
}

export function fmtFilterMatchCount(count: number, locale: Locale): string {
  if (locale === "zh") {
    return `匹配 ${count} 条`;
  }
  return `${count} ${count === 1 ? "match" : "matches"}`;
}

export function fmtPluginMode(mode: string, locale: Locale): string {
  const c = getCopy(locale).common;
  const map: Record<string, string> = { observe: c.observe, assist: c.assist, enforce: c.enforce };
  return map[mode] ?? mode;
}

export function fmtBoolean(value: boolean, locale: Locale): string {
  return value ? getCopy(locale).common.yes : getCopy(locale).common.no;
}

export function fmtPluginValidation(status: string, locale: Locale): string {
  const c = getCopy(locale).plugins;
  const map: Record<string, string> = { ok: c.healthOk, warn: c.healthWarn, error: c.healthError };
  return map[status] ?? status;
}

export function fmtPluginSource(sourceKind: string, locale: Locale): string {
  const c = getCopy(locale).plugins;
  const map: Record<string, string> = {
    discovered: c.sourceDiscovered,
    config: c.sourceConfig,
    missing: c.sourceMissing,
  };
  return map[sourceKind] ?? c.sourceOther;
}
