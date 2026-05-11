import type { Metadata } from "next";
import "./globals.css";
import { LegalDisclaimer } from "@/components/legal-disclaimer";

export const metadata: Metadata = {
  title: "lex-agents — Consulta jurídica asistida",
  description:
    "Plataforma multi-agente de consulta jurídica especializada (uso interno)",
};

const NAV_ITEMS = [
  { label: "Regulatorio bancario UE+ES", active: true, href: "/" },
  { label: "Laboral", active: false },
  { label: "Contencioso", active: false },
  { label: "Societario", active: false },
] as const;

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="es">
      <body className="flex min-h-screen flex-col antialiased">
        {/* Header */}
        <header className="border-b border-border bg-brand-800 px-6 py-4">
          <div className="flex items-center gap-3">
            <span className="text-2xl" aria-hidden>
              ⚖
            </span>
            <div>
              <h1 className="text-lg font-semibold leading-tight text-white">
                lex-agents
              </h1>
              <p className="text-xs text-brand-200">
                Consulta jurídica asistida
              </p>
            </div>
          </div>
        </header>

        <div className="flex flex-1">
          {/* Sidebar */}
          <nav
            className="w-64 border-r border-border bg-brand-50 p-4"
            aria-label="Ramas jurídicas"
          >
            <p className="mb-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Ramas jurídicas
            </p>
            <ul className="space-y-1">
              {NAV_ITEMS.map((item) =>
                item.active ? (
                  <li key={item.label}>
                    <a
                      href={item.href}
                      className="flex items-center rounded-md bg-brand-800 px-3 py-2 text-sm font-medium text-white"
                    >
                      {item.label}
                    </a>
                  </li>
                ) : (
                  <li key={item.label} title="Próximamente">
                    <span className="flex cursor-not-allowed items-center rounded-md px-3 py-2 text-sm text-muted-foreground opacity-50 select-none">
                      {item.label}
                    </span>
                  </li>
                ),
              )}
            </ul>
          </nav>

          {/* Main content */}
          <main className="flex-1 p-6">{children}</main>
        </div>

        {/* Footer — permanent legal disclaimer */}
        <LegalDisclaimer />
      </body>
    </html>
  );
}
