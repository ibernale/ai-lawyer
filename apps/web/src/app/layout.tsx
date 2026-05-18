import type { Metadata } from "next";
import Link from "next/link";
import { NextIntlClientProvider } from "next-intl";
import { getLocale, getMessages, getTranslations } from "next-intl/server";
import "./globals.css";
import { AppSidebar } from "@/components/AppSidebar";
import { LocaleSwitcher } from "@/components/LocaleSwitcher";
import { LegalDisclaimer } from "@/components/legal-disclaimer";
import { CaveatFooterNote } from "@/components/CaveatBanner";

// Force dynamic rendering so the CSP middleware injects a fresh nonce per
// request — cached HTML would have stale nonces causing browsers to block scripts.
export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "lex-agents — Consulta jurídica asistida",
  description:
    "Plataforma multi-agente de consulta jurídica especializada (uso interno)",
};

export default async function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const locale = await getLocale();
  const messages = await getMessages();
  const t = await getTranslations("layout");

  return (
    <html lang={locale}>
      <body className="antialiased">
        <NextIntlClientProvider locale={locale} messages={messages}>
          <div className="flex min-h-screen flex-col">
            {/* Top header */}
            <header className="border-b border-border bg-brand-800 px-6 py-3 flex items-center gap-3 shrink-0">
              <Link
                href="/"
                className="flex items-center gap-3 hover:opacity-90 transition-opacity"
              >
                <span className="text-xl" aria-hidden>
                  ⚖
                </span>
                <div>
                  <span className="text-base font-semibold leading-tight text-white block">
                    {t("appName")}
                  </span>
                  <span className="text-[11px] text-brand-200 leading-none">
                    {t("appSubtitle")}
                  </span>
                </div>
              </Link>

              {/* Locale switcher — right-aligned */}
              <div className="ml-auto">
                <LocaleSwitcher />
              </div>
            </header>

            <div className="flex flex-1 min-h-0">
              <AppSidebar />
              <main className="flex-1 overflow-auto">{children}</main>
            </div>

            <CaveatFooterNote />
            <LegalDisclaimer />
          </div>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
