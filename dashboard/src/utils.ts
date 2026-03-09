import type { Locale } from "./types";

function intlLocale(locale: Locale): string {
  return locale === "zh" ? "zh-CN" : "en-US";
}

export function formatDuration(durationMs: number | null | undefined, locale: Locale): string {
  if (durationMs == null || Number.isNaN(durationMs)) {
    return "-";
  }
  if (durationMs < 1000) {
    return locale === "zh" ? `${durationMs.toFixed(1)} 毫秒` : `${durationMs.toFixed(1)} ms`;
  }
  return locale === "zh" ? `${(durationMs / 1000).toFixed(2)} 秒` : `${(durationMs / 1000).toFixed(2)} s`;
}

export function formatTimestamp(timestamp: string, locale: Locale): string {
  return new Intl.DateTimeFormat(intlLocale(locale), {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    month: "short",
    day: "2-digit",
  }).format(new Date(timestamp));
}

export function stableJson(value: unknown, fallback = "Not captured"): string {
  if (value == null) {
    return fallback;
  }
  return JSON.stringify(value, null, 2);
}
