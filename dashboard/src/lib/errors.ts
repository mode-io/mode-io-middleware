import { ApiError } from "../api";
import type { Locale } from "../types";

interface LocalizedMessage {
  en: string;
  zh: string;
}

export function formatLocalizedError(
  error: unknown,
  locale: Locale,
  fallback: LocalizedMessage,
): string {
  if (error instanceof ApiError) {
    return error.message;
  }
  if (error instanceof Error && error.message) {
    return error.message;
  }
  return locale === "zh" ? fallback.zh : fallback.en;
}
