"use client";

import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { listConsultations } from "@/lib/api";
import type { ConsultationSummary } from "@/lib/api";
import { LegalDisclaimer } from "@/components/legal-disclaimer";
import { ErrorBanner } from "@/components/ui/error-banner";

const STATUS_OPTIONS = [
  { value: "green", label: "Verificado", bg: "bg-green-100", text: "text-green-700" },
  { value: "amber", label: "Parcial", bg: "bg-amber-100", text: "text-amber-700" },
  { value: "red", label: "Errores", bg: "bg-red-100", text: "text-red-700" },
  { value: "pending", label: "Pendiente", bg: "bg-gray-100", text: "text-gray-600" },
];

const DEPTH_OPTIONS = [
  { value: "shallow", label: "Rápido" },
  { value: "standard", label: "Estándar" },
  { value: "deep", label: "Profundo" },
];

function StatusBadge({ status }: { status: string }) {
  const cfg = STATUS_OPTIONS.find((o) => o.value === status) ?? {
    bg: "bg-gray-100",
    text: "text-gray-600",
    label: status,
  };
  return (
    <span
      className={`inline-flex items-center rounded px-2 py-0.5 text-xs font-medium ${cfg.bg} ${cfg.text}`}
    >
      {"label" in cfg ? cfg.label : status}
    </span>
  );
}

function FilterChip({
  active,
  label,
  onClick,
}: {
  active: boolean;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={[
        "px-2.5 py-1 text-xs font-medium rounded-full border transition-colors",
        active
          ? "bg-primary text-primary-foreground border-primary"
          : "bg-background text-muted-foreground border-input hover:bg-accent hover:text-accent-foreground",
      ].join(" ")}
    >
      {label}
    </button>
  );
}

function HistoricoInner() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const [records, setRecords] = useState<ConsultationSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Controlled filter state — initialized from URL
  const [searchText, setSearchText] = useState(searchParams.get("q") ?? "");
  const [depthFilter, setDepthFilter] = useState(searchParams.get("depth") ?? "");
  const [statusFilter, setStatusFilter] = useState(searchParams.get("status") ?? "");
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const load = useCallback(
    async (q: string, depth: string, status: string) => {
      setLoading(true);
      setError(null);
      try {
        const data = await listConsultations({
          q: q || undefined,
          depth: depth || undefined,
          status: status || undefined,
          limit: 50,
        });
        setRecords(data);
      } catch (e) {
        setError(
          e instanceof Error
            ? e.message
            : "No se pudieron cargar las consultas. Inténtalo de nuevo.",
        );
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  // Sync URL params → fetch (runs on mount and when filters change via URL)
  useEffect(() => {
    const q = searchParams.get("q") ?? "";
    const depth = searchParams.get("depth") ?? "";
    const status = searchParams.get("status") ?? "";
    setSearchText(q);
    setDepthFilter(depth);
    setStatusFilter(status);
    void load(q, depth, status);
  }, [searchParams, load]);

  function pushFilters(q: string, depth: string, status: string) {
    const params = new URLSearchParams();
    if (q) params.set("q", q);
    if (depth) params.set("depth", depth);
    if (status) params.set("status", status);
    const qs = params.toString();
    router.replace(`/historico${qs ? `?${qs}` : ""}`);
  }

  function handleSearchChange(value: string) {
    setSearchText(value);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      pushFilters(value, depthFilter, statusFilter);
    }, 300);
  }

  function toggleDepth(value: string) {
    const next = depthFilter === value ? "" : value;
    setDepthFilter(next);
    pushFilters(searchText, next, statusFilter);
  }

  function toggleStatus(value: string) {
    const next = statusFilter === value ? "" : value;
    setStatusFilter(next);
    pushFilters(searchText, depthFilter, next);
  }

  function clearFilters() {
    setSearchText("");
    setDepthFilter("");
    setStatusFilter("");
    router.replace("/historico");
  }

  const hasFilters = !!(searchText || depthFilter || statusFilter);

  return (
    <div className="flex min-h-screen flex-col">
      <main className="flex-1 mx-auto w-full max-w-5xl px-4 py-8 space-y-6">
        <header className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">
              Histórico de consultas
            </h1>
            <p className="mt-1 text-sm text-muted-foreground">
              {loading
                ? "Cargando…"
                : error
                  ? "No se pudieron cargar las consultas"
                  : `${records.length} consulta${records.length !== 1 ? "s" : ""} encontrada${records.length !== 1 ? "s" : ""}`}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => load(searchText, depthFilter, statusFilter)}
              disabled={loading}
              className="rounded-md border border-input px-3 py-1.5 text-sm hover:bg-muted disabled:opacity-50 transition-colors"
            >
              ↻ Actualizar
            </button>
            <Link
              href="/consulta"
              className="rounded-md bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground hover:bg-primary/90 transition-colors"
            >
              Nueva consulta
            </Link>
          </div>
        </header>

        {/* Search + filters */}
        <div className="space-y-3">
          <div className="relative">
            <svg
              className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground pointer-events-none"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
              />
            </svg>
            <input
              type="search"
              value={searchText}
              onChange={(e) => handleSearchChange(e.target.value)}
              placeholder="Buscar en consultas…"
              className="w-full rounded-md border border-input bg-background pl-9 pr-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
            />
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-muted-foreground font-medium">Profundidad:</span>
            {DEPTH_OPTIONS.map((opt) => (
              <FilterChip
                key={opt.value}
                label={opt.label}
                active={depthFilter === opt.value}
                onClick={() => toggleDepth(opt.value)}
              />
            ))}
            <span className="text-xs text-muted-foreground font-medium ml-3">Estado:</span>
            {STATUS_OPTIONS.map((opt) => (
              <FilterChip
                key={opt.value}
                label={opt.label}
                active={statusFilter === opt.value}
                onClick={() => toggleStatus(opt.value)}
              />
            ))}
            {hasFilters && (
              <button
                type="button"
                onClick={clearFilters}
                className="ml-1 px-2 py-1 text-xs text-muted-foreground hover:text-foreground underline"
              >
                Limpiar
              </button>
            )}
          </div>
        </div>

        {error && <ErrorBanner message={error} onRetry={() => load(searchText, depthFilter, statusFilter)} />}

        {loading && (
          <div className="flex items-center justify-center py-16">
            <span className="inline-block h-6 w-6 animate-spin rounded-full border-2 border-primary border-t-transparent" />
            <span className="ml-3 text-sm text-muted-foreground">
              Cargando historial…
            </span>
          </div>
        )}

        {!loading && !error && records.length === 0 && (
          <p className="text-sm text-muted-foreground text-center py-12">
            {hasFilters
              ? "No se encontraron consultas con estos filtros."
              : "No hay consultas registradas todavía. "}
            {!hasFilters && (
              <Link href="/consulta" className="text-primary underline">
                Realiza tu primera consulta
              </Link>
            )}
          </p>
        )}

        {!loading && records.length > 0 && (
          <div className="overflow-hidden rounded-lg border border-border">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border bg-muted/50">
                  <th className="px-4 py-3 text-left font-medium text-muted-foreground">
                    Fecha
                  </th>
                  <th className="px-4 py-3 text-left font-medium text-muted-foreground">
                    Consulta
                  </th>
                  <th className="px-4 py-3 text-left font-medium text-muted-foreground">
                    Rama
                  </th>
                  <th className="px-4 py-3 text-left font-medium text-muted-foreground">
                    Modo
                  </th>
                  <th className="px-4 py-3 text-left font-medium text-muted-foreground">
                    Estado
                  </th>
                  <th className="px-4 py-3 text-right font-medium text-muted-foreground">
                    ms
                  </th>
                  <th className="sr-only">Acción</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {records.map((r) => (
                  <tr
                    key={r.trace_id}
                    className="hover:bg-muted/30 transition-colors"
                  >
                    <td className="px-4 py-3 whitespace-nowrap text-muted-foreground text-xs">
                      {new Date(r.created_at).toLocaleString("es-ES", {
                        day: "2-digit",
                        month: "2-digit",
                        year: "2-digit",
                        hour: "2-digit",
                        minute: "2-digit",
                      })}
                    </td>
                    <td className="px-4 py-3 max-w-xs truncate" title={r.query}>
                      {r.query}
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap text-xs text-muted-foreground font-mono">
                      {r.branch ?? "—"}
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap text-xs text-muted-foreground capitalize">
                      {r.depth_used ?? "—"}
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge status={r.verification_status} />
                    </td>
                    <td className="px-4 py-3 text-right text-muted-foreground font-mono text-xs">
                      {r.latency_ms ?? "—"}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <Link
                        href={`/consulta?trace=${r.trace_id}`}
                        className="text-xs text-primary underline hover:no-underline"
                      >
                        Ver
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </main>

      <LegalDisclaimer />
    </div>
  );
}

export default function HistoricoPage() {
  return (
    <Suspense>
      <HistoricoInner />
    </Suspense>
  );
}
