"use client";

import { useCallback, useEffect, useState } from "react";
import {
  listAuditSamples,
  getAuditSample,
  submitAuditReview,
  promoteAuditSample,
  type AuditSample,
  type AuditSampleDetail,
  type AuditStatus,
  type AuditVerdict,
} from "@/lib/api";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function truncate(text: string, max: number): string {
  return text.length <= max ? text : `${text.slice(0, max)}…`;
}

function parseAnswer(responseJson: string | null): string {
  if (!responseJson) return "—";
  try {
    const parsed = JSON.parse(responseJson) as { answer?: string };
    return parsed.answer ?? "—";
  } catch {
    return "—";
  }
}

// ---------------------------------------------------------------------------
// Status badge
// ---------------------------------------------------------------------------

const STATUS_STYLES: Record<AuditStatus, string> = {
  pending:
    "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/40 dark:text-yellow-300",
  reviewing: "bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300",
  reviewed:
    "bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300",
};

const STATUS_LABELS: Record<AuditStatus, string> = {
  pending: "Pendiente",
  reviewing: "En revisión",
  reviewed: "Revisado",
};

function StatusBadge({ status }: { status: AuditStatus }) {
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${STATUS_STYLES[status]}`}
    >
      {STATUS_LABELS[status]}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Tab bar
// ---------------------------------------------------------------------------

const TABS: { label: string; status: AuditStatus | undefined }[] = [
  { label: "Pendientes", status: "pending" },
  { label: "En revisión", status: "reviewing" },
  { label: "Revisados", status: "reviewed" },
];

// ---------------------------------------------------------------------------
// Side panel
// ---------------------------------------------------------------------------

type PanelProps = {
  detail: AuditSampleDetail;
  onClose: () => void;
  onReviewSubmitted: () => void;
};

function ReviewPanel({ detail, onClose, onReviewSubmitted }: PanelProps) {
  const [verdict, setVerdict] = useState<AuditVerdict | "">(
    detail.review_verdict ?? "",
  );
  const [notes, setNotes] = useState(detail.review_notes ?? "");
  const [submitting, setSubmitting] = useState(false);
  const [promoting, setPromoting] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit() {
    if (!verdict) return;
    setSubmitting(true);
    setError("");
    try {
      await submitAuditReview(detail.id, verdict, notes);
      onReviewSubmitted();
    } catch (e) {
      setError(`Error al enviar revisión: ${e}`);
    } finally {
      setSubmitting(false);
    }
  }

  async function handlePromote() {
    setPromoting(true);
    setError("");
    try {
      const result = await promoteAuditSample(detail.id);
      const blob = new Blob([result.yaml_content], { type: "text/yaml" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = result.suggested_filename;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(`Error al promover: ${e}`);
    } finally {
      setPromoting(false);
    }
  }

  const canSubmit = verdict !== "" && !submitting;

  return (
    <aside className="w-[420px] shrink-0 border-l border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 flex flex-col overflow-hidden">
      {/* Panel header */}
      <div className="flex items-center justify-between px-5 py-3 border-b border-gray-200 dark:border-gray-700">
        <h2 className="text-sm font-semibold text-gray-800 dark:text-gray-100">
          Muestra #{detail.id}
        </h2>
        <button
          onClick={onClose}
          aria-label="Cerrar panel"
          className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 text-lg leading-none"
        >
          ✕
        </button>
      </div>

      {/* Scrollable body */}
      <div className="flex-1 overflow-y-auto px-5 py-4 space-y-5 text-sm">
        {/* Query */}
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400 mb-1">
            Consulta
          </p>
          <p className="text-gray-800 dark:text-gray-200 whitespace-pre-wrap break-words">
            {detail.query}
          </p>
        </div>

        {/* Answer */}
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400 mb-1">
            Respuesta del agente
          </p>
          <p className="text-gray-700 dark:text-gray-300 whitespace-pre-wrap break-words max-h-56 overflow-y-auto rounded border border-gray-100 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 px-3 py-2">
            {parseAnswer(detail.response_json)}
          </p>
        </div>

        {/* Metadata row */}
        <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-gray-500 dark:text-gray-400">
          <dt className="font-medium">Branch</dt>
          <dd className="font-mono">{detail.branch}</dd>
          <dt className="font-medium">Depth</dt>
          <dd className="font-mono">{detail.depth}</dd>
          <dt className="font-medium">Muestreado</dt>
          <dd>{detail.sampled_at?.slice(0, 16)}</dd>
          {detail.reviewer && (
            <>
              <dt className="font-medium">Revisor</dt>
              <dd>{detail.reviewer}</dd>
            </>
          )}
        </dl>

        {/* Verdict radios */}
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400 mb-2">
            Veredicto
          </p>
          <div className="flex gap-4">
            {(["correcto", "dudoso", "incorrecto"] as AuditVerdict[]).map(
              (v) => (
                <label
                  key={v}
                  className="flex items-center gap-1.5 cursor-pointer text-sm capitalize"
                >
                  <input
                    type="radio"
                    name="verdict"
                    value={v}
                    checked={verdict === v}
                    onChange={() => setVerdict(v)}
                    className="accent-blue-600"
                  />
                  <span className="text-gray-700 dark:text-gray-200">{v}</span>
                </label>
              ),
            )}
          </div>
        </div>

        {/* Notes */}
        <div>
          <label
            htmlFor="review-notes"
            className="block text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400 mb-1"
          >
            Notas
          </label>
          <textarea
            id="review-notes"
            rows={4}
            className="w-full border border-gray-300 dark:border-gray-600 rounded px-3 py-2 text-sm resize-none bg-white dark:bg-gray-800 text-gray-800 dark:text-gray-200 focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="Observaciones opcionales..."
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
          />
        </div>

        {error && (
          <p className="text-xs text-red-600 bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-700 rounded px-3 py-2">
            {error}
          </p>
        )}
      </div>

      {/* Footer actions */}
      <div className="px-5 py-3 border-t border-gray-200 dark:border-gray-700 flex flex-col gap-2">
        <button
          onClick={handleSubmit}
          disabled={!canSubmit}
          className="w-full px-4 py-2 text-sm font-medium bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          {submitting ? "Enviando…" : "Enviar revisión"}
        </button>
        {verdict === "incorrecto" && (
          <button
            onClick={handlePromote}
            disabled={promoting}
            className="w-full px-4 py-2 text-sm font-medium border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200 rounded hover:bg-gray-50 dark:hover:bg-gray-800 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            {promoting ? "Generando YAML…" : "Promover a golden dataset"}
          </button>
        )}
      </div>
    </aside>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function ReviewQueuePage() {
  const [activeTab, setActiveTab] = useState<AuditStatus>("pending");
  const [samples, setSamples] = useState<AuditSample[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [selectedDetail, setSelectedDetail] =
    useState<AuditSampleDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const loadSamples = useCallback((status: AuditStatus) => {
    setLoading(true);
    setLoadError("");
    setSelectedDetail(null);
    listAuditSamples(status)
      .then(setSamples)
      .catch((e) => setLoadError(`Error al cargar muestras: ${e}`))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    loadSamples(activeTab);
  }, [activeTab, loadSamples]);

  async function handleRowClick(sample: AuditSample) {
    setDetailLoading(true);
    try {
      const detail = await getAuditSample(sample.id);
      setSelectedDetail(detail);
    } catch (e) {
      setLoadError(`Error al cargar detalle: ${e}`);
    } finally {
      setDetailLoading(false);
    }
  }

  function handleReviewSubmitted() {
    setSelectedDetail(null);
    loadSamples(activeTab);
  }

  return (
    <div className="flex flex-col h-full">
      {/* Page header */}
      <div className="flex items-center justify-between mb-5">
        <h1 className="text-2xl font-bold text-gray-800 dark:text-gray-100">
          Cola de revisión
        </h1>
        <button
          onClick={() => loadSamples(activeTab)}
          className="px-3 py-1.5 text-sm border border-gray-300 dark:border-gray-600 rounded hover:bg-gray-50 dark:hover:bg-gray-800 text-gray-700 dark:text-gray-200 transition-colors"
        >
          Recargar
        </button>
      </div>

      {/* Tab bar */}
      <div className="flex gap-1 mb-5 border-b border-gray-200 dark:border-gray-700">
        {TABS.map(({ label, status }) => (
          <button
            key={status}
            onClick={() => {
              if (status) setActiveTab(status);
            }}
            className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors ${
              activeTab === status
                ? "border-blue-600 text-blue-600 dark:text-blue-400"
                : "border-transparent text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
            }`}
          >
            {label}
            {status === activeTab && samples.length > 0 && (
              <span className="ml-2 text-xs bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 px-1.5 py-0.5 rounded-full">
                {samples.length}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Error banner */}
      {loadError && (
        <p className="mb-4 text-sm text-red-600 bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-700 rounded-lg px-3 py-2">
          {loadError}
        </p>
      )}

      {/* Content area: table + side panel */}
      <div className="flex flex-1 gap-0 min-h-0 overflow-hidden rounded-lg border border-gray-200 dark:border-gray-700">
        {/* Table */}
        <div className="flex-1 overflow-auto">
          {loading ? (
            <p className="p-4 text-sm text-gray-500 dark:text-gray-400">
              Cargando…
            </p>
          ) : samples.length === 0 ? (
            <p className="p-4 text-sm text-gray-400 dark:text-gray-500 italic">
              Sin muestras en esta categoría.
            </p>
          ) : (
            <table className="w-full text-sm border-collapse">
              <thead className="sticky top-0 bg-gray-50 dark:bg-gray-800 z-10">
                <tr className="border-b border-gray-200 dark:border-gray-700 text-left text-xs text-gray-500 dark:text-gray-400 font-semibold uppercase tracking-wide">
                  <th className="py-2.5 px-4">ID</th>
                  <th className="py-2.5 px-4">Consulta</th>
                  <th className="py-2.5 px-4">Branch</th>
                  <th className="py-2.5 px-4">Depth</th>
                  <th className="py-2.5 px-4">Muestreado</th>
                  <th className="py-2.5 px-4">Estado</th>
                  <th className="py-2.5 px-4">Revisor</th>
                </tr>
              </thead>
              <tbody>
                {samples.map((s) => {
                  const isActive = selectedDetail?.id === s.id;
                  return (
                    <tr
                      key={s.id}
                      onClick={() => handleRowClick(s)}
                      className={`border-b border-gray-100 dark:border-gray-800 cursor-pointer transition-colors ${
                        isActive
                          ? "bg-blue-50 dark:bg-blue-900/20"
                          : "hover:bg-gray-50 dark:hover:bg-gray-800/60"
                      }`}
                    >
                      <td className="py-2.5 px-4 text-gray-400 dark:text-gray-500 tabular-nums">
                        {s.id}
                      </td>
                      <td className="py-2.5 px-4 text-gray-800 dark:text-gray-200 max-w-xs">
                        {truncate(s.query, 80)}
                      </td>
                      <td className="py-2.5 px-4">
                        <span className="font-mono text-xs bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 rounded px-1.5 py-0.5">
                          {s.branch}
                        </span>
                      </td>
                      <td className="py-2.5 px-4">
                        <span className="font-mono text-xs text-gray-500 dark:text-gray-400">
                          {s.depth}
                        </span>
                      </td>
                      <td className="py-2.5 px-4 text-xs text-gray-500 dark:text-gray-400 tabular-nums">
                        {s.sampled_at?.slice(0, 16)}
                      </td>
                      <td className="py-2.5 px-4">
                        <StatusBadge status={s.status} />
                      </td>
                      <td className="py-2.5 px-4 text-xs text-gray-500 dark:text-gray-400">
                        {s.reviewer ?? "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}

          {/* Loading overlay when fetching detail */}
          {detailLoading && (
            <p className="p-3 text-xs text-gray-400 dark:text-gray-500 italic border-t border-gray-100 dark:border-gray-800">
              Cargando detalle…
            </p>
          )}
        </div>

        {/* Side panel */}
        {selectedDetail && (
          <ReviewPanel
            detail={selectedDetail}
            onClose={() => setSelectedDetail(null)}
            onReviewSubmitted={handleReviewSubmitted}
          />
        )}
      </div>
    </div>
  );
}
