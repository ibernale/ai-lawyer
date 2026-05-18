"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { Route } from "next";
import { useTranslations } from "next-intl";
import { CommandPalette } from "./CommandPalette";

type NavItem =
  | { href: Route; label: string; disabled?: false }
  | { label: string; disabled: true };

type NavSection = {
  label: string;
  items: NavItem[];
};

function IconConsulta() {
  return (
    <svg
      className="w-4 h-4 shrink-0"
      fill="none"
      stroke="currentColor"
      viewBox="0 0 24 24"
      aria-hidden="true"
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={1.8}
        d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-3 3-3-3z"
      />
    </svg>
  );
}

function IconDocumentos() {
  return (
    <svg
      className="w-4 h-4 shrink-0"
      fill="none"
      stroke="currentColor"
      viewBox="0 0 24 24"
      aria-hidden="true"
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={1.8}
        d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
      />
    </svg>
  );
}

function IconHistorico() {
  return (
    <svg
      className="w-4 h-4 shrink-0"
      fill="none"
      stroke="currentColor"
      viewBox="0 0 24 24"
      aria-hidden="true"
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={1.8}
        d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"
      />
    </svg>
  );
}

function IconAuditoria() {
  return (
    <svg
      className="w-4 h-4 shrink-0"
      fill="none"
      stroke="currentColor"
      viewBox="0 0 24 24"
      aria-hidden="true"
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={1.8}
        d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4"
      />
    </svg>
  );
}

function IconCalendario() {
  return (
    <svg
      className="w-4 h-4 shrink-0"
      fill="none"
      stroke="currentColor"
      viewBox="0 0 24 24"
      aria-hidden="true"
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={1.8}
        d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"
      />
    </svg>
  );
}

function IconContratos() {
  return (
    <svg
      className="w-4 h-4 shrink-0"
      fill="none"
      stroke="currentColor"
      viewBox="0 0 24 24"
      aria-hidden="true"
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={1.8}
        d="M9 12h6m-6 4h6M7 3H5a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2V5a2 2 0 00-2-2h-2M9 3h6a1 1 0 010 2H9a1 1 0 010-2z"
      />
    </svg>
  );
}

export function AppSidebar() {
  const pathname = usePathname();
  const [paletteOpen, setPaletteOpen] = useState(false);
  const t = useTranslations("nav");

  const ITEM_ICONS: Record<string, React.ReactNode> = {
    [t("consulta")]: <IconConsulta />,
    [t("documentos")]: <IconDocumentos />,
    [t("contratos")]: <IconContratos />,
    [t("calendario")]: <IconCalendario />,
    [t("historico")]: <IconHistorico />,
    [t("auditoria")]: <IconAuditoria />,
  };

  const NAV_SECTIONS: NavSection[] = [
    {
      label: t("asesoria"),
      items: [
        { href: "/consulta" as Route, label: t("consulta") },
        { href: "/documentos" as Route, label: t("documentos") },
        { href: "/contratos" as Route, label: t("contratos") },
        { href: "/calendario" as Route, label: t("calendario") },
      ],
    },
    {
      label: t("historial"),
      items: [
        { href: "/historico" as Route, label: t("historico") },
        { href: "/auditoria" as Route, label: t("auditoria") },
      ],
    },
    {
      label: t("proximamente"),
      items: [
        { label: t("laboral"), disabled: true },
        { label: t("contencioso"), disabled: true },
      ],
    },
  ];

  useEffect(() => {
    function handler(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setPaletteOpen((v) => !v);
      }
    }
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, []);

  return (
    <>
      <aside
        className="w-56 bg-white border-r border-border flex flex-col shrink-0"
        aria-label="Navegación principal"
      >
        <nav className="flex-1 px-2 py-4 overflow-y-auto space-y-5">
          {NAV_SECTIONS.map((section) => (
            <div key={section.label}>
              <p className="px-3 mb-1 text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">
                {section.label}
              </p>
              <div className="space-y-0.5">
                {section.items.map((item) => {
                  if (item.disabled) {
                    return (
                      <span
                        key={item.label}
                        title={t("proximamente")}
                        className="flex items-center gap-2 px-3 py-2 text-sm rounded-md text-muted-foreground opacity-40 cursor-not-allowed select-none"
                      >
                        <span className="w-4 h-4 shrink-0" />
                        {item.label}
                        <span className="ml-auto text-[9px] bg-muted px-1.5 py-0.5 rounded font-medium">
                          {t("soon")}
                        </span>
                      </span>
                    );
                  }
                  const active =
                    pathname === item.href ||
                    (item.href !== "/" && pathname.startsWith(item.href));
                  return (
                    <Link
                      key={item.href}
                      href={item.href}
                      aria-current={active ? "page" : undefined}
                      className={[
                        "flex items-center gap-2 px-3 py-2 text-sm rounded-md transition-colors",
                        active
                          ? "bg-brand-50 text-brand-700 font-semibold"
                          : "text-foreground hover:bg-muted",
                      ].join(" ")}
                    >
                      {ITEM_ICONS[item.label]}
                      {item.label}
                    </Link>
                  );
                })}
              </div>
            </div>
          ))}
        </nav>

        {/* ⌘K trigger */}
        <div className="border-t border-border p-3">
          <button
            onClick={() => setPaletteOpen(true)}
            className="w-full flex items-center gap-2 px-3 py-2 text-sm rounded-md border border-border text-muted-foreground hover:bg-muted transition-colors"
            aria-label="Abrir paleta de comandos"
          >
            <svg
              className="w-3.5 h-3.5 shrink-0"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
              aria-hidden="true"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
              />
            </svg>
            <span className="flex-1 text-left text-xs">{t("search")}</span>
            <kbd className="text-[10px] font-mono bg-muted border border-border px-1.5 py-0.5 rounded leading-none">
              ⌘K
            </kbd>
          </button>
        </div>
      </aside>

      {paletteOpen && <CommandPalette onClose={() => setPaletteOpen(false)} />}
    </>
  );
}
