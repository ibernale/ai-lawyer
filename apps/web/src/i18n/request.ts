import { getRequestConfig } from "next-intl/server";
import { cookies } from "next/headers";
import { defaultLocale, LOCALE_COOKIE, locales, type Locale } from "./routing";

export default getRequestConfig(async () => {
  // Read locale from the NEXT_LOCALE cookie (set by LocaleSwitcher).
  // Falls back to the default locale if cookie is absent or invalid.
  const cookieStore = await cookies();
  const raw = cookieStore.get(LOCALE_COOKIE)?.value ?? defaultLocale;
  const locale: Locale = (locales as readonly string[]).includes(raw)
    ? (raw as Locale)
    : defaultLocale;

  // Static import map — webpack can analyse these at build time and includes
  // them in the standalone bundle. A template-literal dynamic import would NOT
  // be analysed and the JSON files would be missing from the production image.
  const messageMap: Record<
    Locale,
    () => Promise<{ default: Record<string, Record<string, string>> }>
  > = {
    es: () => import("../../messages/es.json"),
    en: () => import("../../messages/en.json"),
    pt: () => import("../../messages/pt.json"),
  };

  return {
    locale,
    messages: (await messageMap[locale]()).default,
  };
});
