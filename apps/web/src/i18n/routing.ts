/**
 * Locale routing configuration for next-intl.
 *
 * Strategy: cookie-based locale without URL prefixes.
 *   - URLs remain unchanged (/consulta, /calendario, etc.)
 *   - Locale stored in NEXT_LOCALE cookie (set by LocaleSwitcher)
 *   - Default locale: 'es' (Spanish, the primary language)
 */

export const locales = ["es", "en", "pt"] as const;
export type Locale = (typeof locales)[number];

export const defaultLocale: Locale = "es";

export const localeLabels: Record<Locale, string> = {
  es: "ES",
  en: "EN",
  pt: "PT",
};

export const localeFlags: Record<Locale, string> = {
  es: "🇪🇸",
  en: "🇬🇧",
  pt: "🇧🇷",
};

/** Cookie name used by next-intl and LocaleSwitcher. */
export const LOCALE_COOKIE = "NEXT_LOCALE";
