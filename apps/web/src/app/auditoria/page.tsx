"use client";

import { useEffect, useState } from "react";
import { getAuditSample, listAuditSamples, submitAuditReview } from "@/lib/api";
import type { AuditSample, AuditStatus, AuditVerdict } from "@/lib/api";
import { ErrorBanner } from "@/components/ui/error-banner";

const STATUS_LABELS: Record<AuditStatus, string> = {
  pending: "Pendiente",
  reviewing: "En revisión",
  reviewed: "Revisado",
};

const STATUS_COLORS: Record<AuditStatus, string> = {
  pending: "bg-amber-100 text-amber-800 border-amber-200",
  reviewing: "bg-blue-100 text-blue-800 border-blue-200",
  reviewed: "bg-green-100 text-green-800 border-green-200",
};

const VERDICT_OPTIONS: { value: AuditVerdict; label: string; cls: string }[] = [
  {
    value: "correcto",
    label: "✅ Correcto",
    cls: "border-green-200 text-green-800 hover:bg-green-50 data-[active=true]:bg-green-100",
  },
  {
    value: "dudoso",
    label: "❓ Dudoso",
    cls: "border-amber-200 text-amber-800 hover:bg-amber-50 data-[active=true]:bg-amber-100",
  },
  {
    value: "incorrecto",
    label: "❌ Incorrecto",
    cls: "border-red-200 text-red-800 hover:bg-red-50 data-[active=true]:bg-red-100",
  },
];

export default function AuditoriaPage() {
  const [statusFilter, setStatusFilter] = useState<AuditStatus | "all">(
    "pending",
  );
  const [samples, setSamples] = useState<AuditSample[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selected, setSelected] = useState<AuditSample | null>(null);
  const [fullRecord, setFullRecord] = useState<
    (AuditSample & { response_json?: string }) | null
  >(null);
  const [reviewVerdict, setReviewVerdict] = useState<AuditVerdict | null>(null);
  const [reviewNotes, setReviewNotes] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setLoadError(null);
    try {
      const data = await listAuditSamples(
        statusFilter === "all" ? undefined : statusFilter,
      );
      setSamples(data);
    } catch (e) {
      setLoadError(
        e instanceof Error
          ? e.message
          : "No se pudieron cargar las muestras de auditoría. Inténtalo de nuevo.",
      );
      setSamples([]);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [statusFilter]);

  async function openSample(sample: AuditSample) {
    setSelected(sample);
    setFullRecord(null);
    setReviewVerdict(null);
    setReviewNotes("");
    setSubmitError(null);
    const full = await getAuditSample(sample.id);
    setFullRecord(full as AuditSample & { response_json?: string });
  }

  async function handleReview() {
    if (!selected || !reviewVerdict) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      await submitAuditReview(selected.id, reviewVerdict, reviewNotes);
      setSelected(null);
      await load();
    } catch (e) {
      setSubmitError(e instanceof Error ? e.message : "Error");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">Auditoría diaria</h1>
        <div className="flex items-center gap-2">
          {(["pending", "reviewing", "reviewed", "all"] as const).map((s) => (
            <button
              key={s}
              onClick={() => setStatusFilter(s)}
              className={`rounded border px-3 py-1 text-xs font-medium transition-colors ${
                statusFilter === s
                  ? "bg-primary text-primary-foreground border-primary"
                  : "border-input hover:bg-muted"
              }`}
            >
              {s === "all" ? "Todos" : (STATUS_LABELS[s as AuditStatus] ?? s)}
            </button>
          ))}
          <button
            onClick={load}
            className="rounded border border-input px-3 py-1 text-xs hover:bg-muted"
          >
            ↻ Actualizar
          </button>
        </div>
      </div>

      {loadError && <ErrorBanner message={loadError} onRetry={load} />}

      {loading ? (
        <div className="flex items-center gap-3 py-6">
          <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-primary border-t-transparent" />
          <span className="text-sm text-muted-foreground">
            Cargando muestras…
          </span>
        </div>
      ) : !loadError && samples.length === 0 ? (
        <p className="text-sm text-muted-foreground italic">
          No hay muestras con este estado.
        </p>
      ) : !loadError ? (
        <div className="rounded-lg border border-border overflow-hidden">
          <table className="w-full text-xs">
            <thead className="bg-muted/50">
              <tr>
                <th className="px-3 py-2 text-left font-semibold">ID</th>
                <th className="px-3 py-2 text-left font-semibold">Consulta</th>
                <th className="px-3 py-2 text-left font-semibold">Rama</th>
                <th className="px-3 py-2 text-left font-semibold">Depth</th>
                <th className="px-3 py-2 text-left font-semibold">
                  Muestreado
                </th>
                <th className="px-3 py-2 text-left font-semibold">Estado</th>
                <th className="px-3 py-2 text-left font-semibold">Veredicto</th>
                <th className="px-3 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {samples.map((s, i) => (
                <tr
                  key={s.id}
                  className={i % 2 === 0 ? "bg-background" : "bg-muted/20"}
                >
                  <td className="px-3 py-2 font-mono">{s.id}</td>
                  <td
                    className="px-3 py-2 max-w-[260px] truncate"
                    title={s.query}
                  >
                    {s.query}
                  </td>
                  <td className="px-3 py-2 font-mono text-[10px]">
                    {s.branch}
                  </td>
                  <td className="px-3 py-2">{s.depth}</td>
                  <td className="px-3 py-2">
                    {new Date(s.sampled_at).toLocaleDateString("es-ES")}
                  </td>
                  <td className="px-3 py-2">
                    <span
                      className={`rounded border px-1.5 py-0.5 text-[10px] font-semibold ${STATUS_COLORS[s.status]}`}
                    >
                      {STATUS_LABELS[s.status]}
                    </span>
                  </td>
                  <td className="px-3 py-2">
                    {s.review_verdict ? (
                      <span className="font-medium">{s.review_verdict}</span>
                    ) : (
                      <span className="text-muted-foreground">—</span>
                    )}
                  </td>
                  <td className="px-3 py-2">
                    {s.status !== "reviewed" && (
                      <button
                        onClick={() => openSample(s)}
                        className="rounded border border-primary px-2 py-0.5 text-[10px] text-primary hover:bg-primary/10"
                      >
                        Revisar
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      {/* Review panel */}
      {selected && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="bg-background rounded-lg shadow-xl border border-border w-full max-w-2xl max-h-[85vh] flex flex-col">
            <div className="flex items-center justify-between border-b border-border px-4 py-3 shrink-0">
              <h2 className="font-semibold text-sm">
                Revisar muestra #{selected.id}
              </h2>
              <button
                onClick={() => setSelected(null)}
                className="text-muted-foreground hover:text-foreground text-lg"
              >
                ×
              </button>
            </div>

            <div className="flex-1 overflow-y-auto p-4 space-y-4 text-sm">
              <div className="space-y-1">
                <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
                  Consulta
                </p>
                <p className="text-foreground">{selected.query}</p>
              </div>

              <div className="flex gap-3 text-xs text-muted-foreground font-mono">
                <span>rama: {selected.branch}</span>
                <span>·</span>
                <span>depth: {selected.depth}</span>
                <span>·</span>
                <span>trace: {selected.trace_id.slice(0, 8)}</span>
              </div>

              {fullRecord?.response_json ? (
                <div className="space-y-1">
                  <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
                    Respuesta
                  </p>
                  <div className="rounded border border-border bg-muted/20 p-3 text-xs leading-relaxed max-h-48 overflow-y-auto">
                    {(() => {
                      try {
                        const d = JSON.parse(fullRecord.response_json) as {
                          answer?: string;
                        };
                        return d.answer ?? fullRecord.response_json;
                      } catch {
                        return fullRecord.response_json;
                      }
                    })()}
                  </div>
                </div>
              ) : (
                <p className="text-xs text-muted-foreground italic">
                  Cargando respuesta…
                </p>
              )}

              <div className="space-y-2">
                <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
                  Veredicto
                </p>
                <div className="flex gap-2">
                  {VERDICT_OPTIONS.map((v) => (
                    <button
                      key={v.value}
                      data-active={reviewVerdict === v.value}
                      onClick={() => setReviewVerdict(v.value)}
                      className={`rounded border px-3 py-1.5 text-xs font-medium transition-colors ${v.cls}`}
                    >
                      {v.label}
                    </button>
                  ))}
                </div>
              </div>

              <div className="space-y-1">
                <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
                  Notas de revisión
                </p>
                <textarea
                  value={reviewNotes}
                  onChange={(e) => setReviewNotes(e.target.value)}
                  rows={3}
                  placeholder="Observaciones sobre la corrección jurídica, citas erróneas, lagunas…"
                  className="w-full rounded border border-input bg-background px-2 py-1.5 text-xs resize-none"
                />
              </div>

              {submitError && (
                <p className="text-xs text-red-600">{submitError}</p>
              )}
            </div>

            <div className="flex justify-end gap-2 border-t border-border px-4 py-3 shrink-0">
              <button
                onClick={() => setSelected(null)}
                className="px-3 py-1.5 text-xs rounded border border-input hover:bg-muted"
              >
                Cancelar
              </button>
              <button
                onClick={handleReview}
                disabled={!reviewVerdict || submitting}
                className="px-3 py-1.5 text-xs rounded bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
              >
                {submitting ? "Guardando…" : "Guardar revisión"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
