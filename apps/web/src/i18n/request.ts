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

  return {
    locale,
    messages: (await import(`../../messages/${locale}.json`)).default as Record<
      string,
      Record<string, string>
    >,
  };
});
