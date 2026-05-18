"use client";

import { useRouter } from "next/navigation";
import { useLocale } from "next-intl";
import { LOCALE_COOKIE, localeFlags, localeLabels, locales } from "@/i18n/routing";

// Module-level helper — kept outside component to satisfy react-hooks/immutability
// (React Compiler flags direct document.cookie mutations inside component functions).
function writeLocaleCookie(locale: string): void {
  document.cookie = `${LOCALE_COOKIE}=${locale}; path=/; max-age=${
    60 * 60 * 24 * 365
  }; SameSite=Lax`;
}

export function LocaleSwitcher() {
  const router = useRouter();
  const currentLocale = useLocale();

  function switchLocale(locale: string) {
    writeLocaleCookie(locale);
    router.refresh();
  }

  return (
    <div
      className="flex items-center gap-1"
      role="group"
      aria-label="Select language"
    >
      {locales.map((locale) => {
        const active = locale === currentLocale;
        return (
          <button
            key={locale}
            onClick={() => switchLocale(locale)}
            aria-pressed={active}
            title={`${localeFlags[locale]} ${localeLabels[locale]}`}
            className={[
              "px-2 py-1 text-[11px] font-medium rounded transition-colors leading-none",
              active
                ? "bg-white/20 text-white"
                : "text-brand-200 hover:text-white hover:bg-white/10",
            ].join(" ")}
          >
            {localeLabels[locale]}
          </button>
        );
      })}
    </div>
  );
}
