"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { listConsultations } from "@/lib/api";
import type { ConsultationSummary } from "@/lib/api";
import { LegalDisclaimer } from "@/components/legal-disclaimer";
import { ErrorBanner } from "@/components/ui/error-banner";

function StatusBadge({ status }: { status: string }) {
  const config: Record<string, { bg: string; text: string; label: string }> = {
    green: { bg: "bg-green-100", text: "text-green-700", label: "Verificado" },
    amber: { bg: "bg-amber-100", text: "text-amber-700", label: "Parcial" },
    red: { bg: "bg-red-100", text: "text-red-700", label: "Errores" },
    pending: { bg: "bg-gray-100", text: "text-gray-600", label: "Pendiente" },
  };
  const c = config[status] ?? {
    bg: "bg-gray-100",
    text: "text-gray-600",
    label: status,
  };
  return (
    <span
      className={`inline-flex items-center rounded px-2 py-0.5 text-xs font-medium ${c.bg} ${c.text}`}
    >
      {c.label}
    </span>
  );
}

export default function HistoricoPage() {
  const [records, setRecords] = useState<ConsultationSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const data = await listConsultations(50);
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
  }

  useEffect(() => {
    void load();
  }, []);

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
                  : `${records.length} consulta${records.length !== 1 ? "s" : ""} registrada${records.length !== 1 ? "s" : ""}`}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={load}
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

        {error && (
          <ErrorBanner message={error} onRetry={load} />
        )}

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
            No hay consultas registradas todavía.{" "}
            <Link href="/consulta" className="text-primary underline">
              Realiza tu primera consulta
            </Link>
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
                    <td
                      className="px-4 py-3 max-w-xs truncate"
                      title={r.query}
                    >
                      {r.query}
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
