import { COPY } from "./i18nCatalog";
import type { Locale } from "./types";

export function getCopy(locale: Locale) {
  return COPY[locale];
}

export {
  deriveDirection,
  deriveResult,
  fmtAction,
  fmtBoolean,
  fmtClient,
  fmtFilterMatchCount,
  fmtLifecycle,
  fmtPluginMode,
  fmtPluginSource,
  fmtPluginValidation,
  fmtResult,
  fmtStatus,
} from "./i18nFormatters";
