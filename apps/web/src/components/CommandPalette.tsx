"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

type PaletteItem = {
  href: string;
  label: string;
  section: string;
  keywords?: string;
};

const ITEMS: PaletteItem[] = [
  { href: "/", label: "Inicio / Dashboard", section: "Navegación", keywords: "home dashboard inicio" },
  { href: "/consulta", label: "Nueva consulta", section: "Asesoría", keywords: "consultar normativa regulatorio" },
  { href: "/documentos", label: "Análisis de documentos", section: "Asesoría", keywords: "subir analizar contrato" },
  { href: "/historico", label: "Histórico de consultas", section: "Historial", keywords: "historial buscar anteriores" },
  { href: "/auditoria", label: "Auditoría", section: "Historial", keywords: "revisar calidad feedback" },
  { href: "/admin", label: "Panel de administración", section: "Admin", keywords: "admin ops governance" },
  { href: "/legal", label: "Aviso legal", section: "Legal", keywords: "disclaimer aviso" },
];

function highlight(text: string, query: string): React.ReactNode {
  if (!query) return text;
  const idx = text.toLowerCase().indexOf(query.toLowerCase());
  if (idx === -1) return text;
  return (
    <>
      {text.slice(0, idx)}
      <mark className="bg-brand-100 text-brand-800 rounded-sm">{text.slice(idx, idx + query.length)}</mark>
      {text.slice(idx + query.length)}
    </>
  );
}

export function CommandPalette({ onClose }: { onClose: () => void }) {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [activeIdx, setActiveIdx] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLUListElement>(null);

  const filtered = query.trim()
    ? ITEMS.filter((item) => {
        const q = query.toLowerCase();
        return (
          item.label.toLowerCase().includes(q) ||
          item.section.toLowerCase().includes(q) ||
          (item.keywords ?? "").toLowerCase().includes(q)
        );
      })
    : ITEMS;

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  useEffect(() => {
    setActiveIdx(0);
  }, [query]);

  // Scroll active item into view
  useEffect(() => {
    const list = listRef.current;
    if (!list) return;
    const active = list.children[activeIdx] as HTMLElement | undefined;
    active?.scrollIntoView({ block: "nearest" });
  }, [activeIdx]);

  function navigate(href: string) {
    router.push(href);
    onClose();
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIdx((i) => Math.min(i + 1, filtered.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIdx((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter") {
      const item = filtered[activeIdx];
      if (item) navigate(item.href);
    } else if (e.key === "Escape") {
      onClose();
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 bg-black/60 flex items-start justify-center pt-20 px-4"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label="Paleta de comandos"
    >
      <div
        className="w-full max-w-lg bg-white rounded-xl shadow-2xl overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Search input */}
        <div className="flex items-center gap-3 px-4 border-b border-border">
          <svg className="w-4 h-4 text-muted-foreground shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Buscar páginas y acciones…"
            className="flex-1 py-4 text-sm bg-transparent focus:outline-none"
            autoComplete="off"
            spellCheck={false}
          />
          <kbd
            onClick={onClose}
            className="text-[11px] text-muted-foreground border border-border rounded px-1.5 py-0.5 font-mono cursor-pointer hover:bg-muted"
            title="Cerrar"
          >
            Esc
          </kbd>
        </div>

        {/* Results */}
        <ul ref={listRef} className="max-h-72 overflow-y-auto py-1.5" role="listbox">
          {filtered.length === 0 ? (
            <li className="px-4 py-8 text-sm text-muted-foreground text-center">
              Sin resultados para &ldquo;{query}&rdquo;
            </li>
          ) : (
            filtered.map((item, i) => (
              <li key={item.href} role="option" aria-selected={i === activeIdx}>
                <button
                  onMouseEnter={() => setActiveIdx(i)}
                  onClick={() => navigate(item.href)}
                  className={[
                    "w-full flex items-center justify-between px-4 py-2.5 text-sm transition-colors text-left",
                    i === activeIdx
                      ? "bg-brand-50 text-brand-700"
                      : "text-foreground hover:bg-muted",
                  ].join(" ")}
                >
                  <span>{highlight(item.label, query)}</span>
                  <span className="text-xs text-muted-foreground ml-4 shrink-0">
                    {item.section}
                  </span>
                </button>
              </li>
            ))
          )}
        </ul>

        {/* Footer hint */}
        <div className="border-t border-border px-4 py-2 flex items-center gap-4 text-[11px] text-muted-foreground">
          <span><kbd className="font-mono">↑↓</kbd> navegar</span>
          <span><kbd className="font-mono">↵</kbd> abrir</span>
          <span><kbd className="font-mono">Esc</kbd> cerrar</span>
        </div>
      </div>
    </div>
  );
}
