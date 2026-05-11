import Link from "next/link";
import { listConsultations } from "@/lib/api";
import type { ConsultationSummary } from "@/lib/api";
import { LegalDisclaimer } from "@/components/legal-disclaimer";

function StatusBadge({ status }: { status: string }) {
  const config: Record<string, { bg: string; text: string; label: string }> = {
    green: { bg: "bg-green-100", text: "text-green-700", label: "Verificado" },
    amber: { bg: "bg-amber-100", text: "text-amber-700", label: "Parcial" },
    red: { bg: "bg-red-100", text: "text-red-700", label: "Errores" },
    pending: { bg: "bg-gray-100", text: "text-gray-600", label: "Pendiente" },
  };
  const c = config[status] ?? { bg: "bg-gray-100", text: "text-gray-600", label: status };
  return (
    <span className={`inline-flex items-center rounded px-2 py-0.5 text-xs font-medium ${c.bg} ${c.text}`}>
      {c.label}
    </span>
  );
}

export default async function HistoricoPage() {
  let records: ConsultationSummary[] = [];
  let fetchError: string | null = null;

  try {
    records = await listConsultations(20);
  } catch (e) {
    fetchError = e instanceof Error ? e.message : "Error al cargar el historial";
  }

  return (
    <div className="flex min-h-screen flex-col">
      <main className="flex-1 mx-auto w-full max-w-5xl px-4 py-8 space-y-6">
        <header className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">Histórico de consultas</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              Últimas {records.length} consultas realizadas
            </p>
          </div>
          <Link
            href="/consulta"
            className="rounded-md bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground hover:bg-primary/90 transition-colors"
          >
            Nueva consulta
          </Link>
        </header>

        {fetchError && (
          <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
            {fetchError}
          </div>
        )}

        {records.length === 0 && !fetchError && (
          <p className="text-sm text-muted-foreground text-center py-12">
            No hay consultas registradas todavía.{" "}
            <Link href="/consulta" className="text-primary underline">
              Realizar primera consulta
            </Link>
          </p>
        )}

        {records.length > 0 && (
          <div className="overflow-hidden rounded-lg border border-border">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border bg-muted/50">
                  <th className="px-4 py-3 text-left font-medium text-muted-foreground">Fecha</th>
                  <th className="px-4 py-3 text-left font-medium text-muted-foreground">Consulta</th>
                  <th className="px-4 py-3 text-left font-medium text-muted-foreground">Estado</th>
                  <th className="px-4 py-3 text-right font-medium text-muted-foreground">ms</th>
                  <th className="sr-only">Acción</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {records.map((r) => (
                  <tr key={r.trace_id} className="hover:bg-muted/30 transition-colors">
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
