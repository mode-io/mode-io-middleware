import { COPY } from "./i18nCatalog";
import type { Locale } from "./types";

export function getCopy(locale: Locale) {
  return COPY[locale];
}

export {
  fmtAction,
  fmtBoolean,
  fmtClient,
  fmtFilterMatchCount,
  fmtImpact,
  fmtLifecycle,
  fmtPluginMode,
  fmtPluginSource,
  fmtPluginValidation,
  fmtStatus,
} from "./i18nFormatters";
