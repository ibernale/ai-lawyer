"use client";

import type React from "react";
import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type {
  CitationMapping,
  ConsultResponse,
  VerificationReport,
} from "@/lib/api";
import { ComparativeView } from "@/components/ComparativeView";

const API_BASE =
  typeof window === "undefined"
    ? (process.env["API_BASE_URL"] ?? "http://localhost:8000")
    : (process.env["NEXT_PUBLIC_API_URL"] ?? "http://localhost:8000");

// ---------------------------------------------------------------------------
// Citation panel
// ---------------------------------------------------------------------------

function CitationPanel({
  citation,
  onClose,
}: {
  citation: CitationMapping;
  onClose: () => void;
}) {
  const boeUrl = citation.source_id.startsWith("BOE-")
    ? `https://boe.es/buscar/doc.php?id=${citation.source_id}`
    : null;
  const eurlexUrl = /^\d{5}[A-Z]\d{4}/.test(citation.source_id)
    ? `https://eur-lex.europa.eu/legal-content/ES/TXT/?uri=CELEX:${citation.source_id}`
    : null;

  return (
    <aside className="fixed right-0 top-0 z-50 h-full w-96 border-l border-border bg-background shadow-xl flex flex-col">
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <h3 className="font-semibold text-sm">Fuente [REF:{citation.index}]</h3>
        <button
          onClick={onClose}
          className="rounded p-1 hover:bg-muted text-muted-foreground text-lg leading-none"
          aria-label="Cerrar"
        >
          ×
        </button>
      </div>
      <div className="flex-1 overflow-y-auto p-4 space-y-3 text-sm">
        <div>
          <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-1">
            Jerarquía
          </p>
          <p className="text-foreground">{citation.hierarchy_path}</p>
        </div>
        <div>
          <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-1">
            Norma
          </p>
          <p className="font-mono text-xs text-foreground">
            {citation.source_id}
          </p>
        </div>
        <div>
          <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-1">
            Fragmento
          </p>
          <blockquote className="border-l-2 border-primary pl-3 text-xs leading-relaxed text-muted-foreground italic">
            {citation.fragment_text}
          </blockquote>
        </div>
        {(boeUrl ?? eurlexUrl) && (
          <div>
            <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-1">
              Fuente externa
            </p>
            <a
              href={(boeUrl ?? eurlexUrl) as string}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs text-primary underline hover:no-underline"
            >
              Abrir en {boeUrl ? "BOE.es" : "EUR-Lex"} ↗
            </a>
          </div>
        )}
      </div>
    </aside>
  );
}

// ---------------------------------------------------------------------------
// Verification banner
// ---------------------------------------------------------------------------

function VerificationBanner({ report }: { report: VerificationReport }) {
  const [expanded, setExpanded] = useState(false);

  const config = {
    green: {
      bg: "bg-green-50 border-green-200",
      text: "text-green-800",
      icon: "✓",
      message: "Citas verificadas",
    },
    amber: {
      bg: "bg-amber-50 border-amber-200",
      text: "text-amber-800",
      icon: "⚠",
      message: "Verificación parcial — revisar lagunas",
    },
    red: {
      bg: "bg-red-50 border-red-200",
      text: "text-red-800",
      icon: "✗",
      message: "Citas con errores detectados — no publicar sin revisión",
    },
  }[report.status];

  const hasDetails =
    report.broken_refs.length > 0 || report.uncited_claims.length > 0;

  return (
    <div className={`rounded-md border px-4 py-3 ${config.bg}`}>
      <div className="flex items-center justify-between">
        <p className={`text-sm font-medium ${config.text}`}>
          {config.icon} {config.message}
        </p>
        {hasDetails && (
          <button
            onClick={() => setExpanded(!expanded)}
            className={`text-xs underline ${config.text}`}
          >
            {expanded ? "Ocultar detalles" : "Ver detalles"}
          </button>
        )}
      </div>
      {expanded && hasDetails && (
        <div className={`mt-3 space-y-2 text-xs ${config.text}`}>
          {report.broken_refs.length > 0 && (
            <div>
              <p className="font-semibold">Referencias rotas:</p>
              <ul className="mt-1 list-disc list-inside">
                {report.broken_refs.map((ref) => (
                  <li key={ref}>
                    [REF:{ref}] no resuelve a ningún fragmento indexado
                  </li>
                ))}
              </ul>
            </div>
          )}
          {report.uncited_claims.length > 0 && (
            <div>
              <p className="font-semibold">Lagunas declaradas (sin cita):</p>
              <ul className="mt-1 list-disc list-inside space-y-1">
                {report.uncited_claims.map((claim, i) => (
                  <li key={i}>{claim}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// [REF:n] inline chip renderer
// ---------------------------------------------------------------------------

function RefChip({
  idx,
  citation,
  onChipClick,
}: {
  idx: number;
  citation: CitationMapping | undefined;
  onChipClick: (c: CitationMapping) => void;
}) {
  return (
    <button
      onClick={() => citation && onChipClick(citation)}
      className="inline-flex items-center rounded bg-primary/10 px-1.5 py-0.5 text-xs font-mono font-medium text-primary hover:bg-primary/20 transition-colors mx-0.5"
      title={citation?.hierarchy_path ?? `REF:${idx}`}
    >
      [{idx}]
    </button>
  );
}

function renderAnswerWithChips(
  text: string,
  citations: CitationMapping[],
  onChipClick: (citation: CitationMapping) => void,
) {
  // Split on [REF:n] markers, keeping the delimiters
  const parts = text.split(/(\[REF:\d+\])/g);

  const nodes: React.ReactNode[] = parts.map((part, i) => {
    const match = part.match(/^\[REF:(\d+)\]$/);
    if (match) {
      const idx = parseInt(match[1]!, 10);
      return (
        <RefChip
          key={i}
          idx={idx}
          citation={citations.find((c) => c.index === idx)}
          onChipClick={onChipClick}
        />
      );
    }
    // Render each text segment as markdown so headers, bold, and lists are styled
    return (
      <ReactMarkdown
        key={i}
        remarkPlugins={[remarkGfm]}
        components={{
          // Inline rendering — no extra wrapper div between paragraphs
          p: ({ children }) => <span className="block mb-2">{children}</span>,
        }}
      >
        {part}
      </ReactMarkdown>
    );
  });

  return nodes;
}

// ---------------------------------------------------------------------------
// Feedback modal
// ---------------------------------------------------------------------------

const ISSUE_TYPES = [
  { value: "error_factual", label: "Error factual" },
  { value: "cita_incorrecta", label: "Cita incorrecta o incompleta" },
  { value: "fuera_de_alcance", label: "Fuera de alcance del sistema" },
  { value: "otro", label: "Otro" },
];

function FeedbackModal({
  traceId,
  answerExcerpt,
  onClose,
}: {
  traceId: string;
  answerExcerpt: string;
  onClose: () => void;
}) {
  const [issueType, setIssueType] = useState("error_factual");
  const [description, setDescription] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const res = await fetch(
        `${API_BASE}/api/v1/consult/${traceId}/feedback`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            issue_type: issueType,
            description,
            answer_excerpt: answerExcerpt,
          }),
        },
      );
      if (!res.ok) throw new Error(`${res.status}`);
      setDone(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-background rounded-lg shadow-xl border border-border w-full max-w-md p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="font-semibold text-sm">Reportar problema</h2>
          <button
            onClick={onClose}
            className="text-muted-foreground hover:text-foreground text-lg"
          >
            ×
          </button>
        </div>
        {done ? (
          <div className="text-sm text-green-700 bg-green-50 border border-green-200 rounded p-3">
            Gracias. Feedback guardado (Trace:{" "}
            <span className="font-mono">{traceId.slice(0, 8)}</span>).
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-3">
            <div>
              <label className="text-xs font-medium text-muted-foreground block mb-1">
                Tipo de problema
              </label>
              <select
                value={issueType}
                onChange={(e) => setIssueType(e.target.value)}
                className="w-full rounded border border-input bg-background px-2 py-1.5 text-sm"
              >
                {ISSUE_TYPES.map((t) => (
                  <option key={t.value} value={t.value}>
                    {t.label}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-xs font-medium text-muted-foreground block mb-1">
                Descripción
              </label>
              <textarea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                rows={4}
                placeholder="Describa el problema observado…"
                className="w-full rounded border border-input bg-background px-2 py-1.5 text-sm resize-none"
                required
              />
            </div>
            {error && <p className="text-xs text-red-600">{error}</p>}
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={onClose}
                className="px-3 py-1.5 text-sm rounded border border-input hover:bg-muted"
              >
                Cancelar
              </button>
              <button
                type="submit"
                disabled={submitting || !description.trim()}
                className="px-3 py-1.5 text-sm rounded bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
              >
                {submitting ? "Enviando…" : "Enviar"}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Razonamiento del sistema panel (PMJ metadata)
// ---------------------------------------------------------------------------

function BranchDetectionBanner({
  response,
  userSelectedJurisdictions,
}: {
  response: ConsultResponse;
  userSelectedJurisdictions?: string[];
}) {
  const po = response.planner_output;
  if (!po || po.branches.length === 0) return null;

  const branchNames = po.branches.map((b) => b.name);
  const isManual =
    userSelectedJurisdictions && userSelectedJurisdictions.length > 0;

  return (
    <div className="rounded-md border border-blue-100 bg-blue-50/40 px-3 py-2 text-xs text-blue-800 flex items-start gap-2">
      <span className="mt-0.5">🔍</span>
      <span>
        {isManual
          ? "Ramas seleccionadas manualmente + detección automática: "
          : "Ramas detectadas automáticamente: "}
        <strong>{branchNames.join(", ")}</strong>
        {po.jurisdictions.length > 0 && (
          <>
            {" "}
            · jurisdicciones: <strong>{po.jurisdictions.join(", ")}</strong>
          </>
        )}
      </span>
    </div>
  );
}

function RazonamientoPanel({ response }: { response: ConsultResponse }) {
  const [open, setOpen] = useState(false);
  const hasData = response.planner_output || response.judge_verdict;
  if (!hasData) return null;

  const po = response.planner_output;
  const jv = response.judge_verdict;
  const costTotal = response.cost_breakdown_by_agent
    ? Object.values(response.cost_breakdown_by_agent).reduce((a, b) => a + b, 0)
    : null;

  return (
    <div className="rounded-md border border-blue-200 bg-blue-50/50">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-4 py-3 text-xs font-medium text-blue-800 hover:bg-blue-50 transition-colors"
      >
        <span>🧠 Razonamiento del sistema</span>
        <span className="text-muted-foreground">
          {open ? "▲ Ocultar" : "▼ Ver"}
        </span>
      </button>

      {open && (
        <div className="px-4 pb-4 space-y-3 text-xs">
          {/* Overview row */}
          <div className="flex flex-wrap gap-3">
            <span className="inline-flex items-center gap-1 rounded bg-blue-100 px-2 py-0.5 font-mono text-blue-800">
              depth: {response.depth_used ?? "—"}
            </span>
            {(response.iterations ?? 0) > 0 && (
              <span className="inline-flex items-center gap-1 rounded bg-blue-100 px-2 py-0.5 font-mono text-blue-800">
                iteraciones: {response.iterations}
              </span>
            )}
            {costTotal != null && (
              <span className="inline-flex items-center gap-1 rounded bg-blue-100 px-2 py-0.5 font-mono text-blue-800">
                coste total: ${costTotal.toFixed(4)}
              </span>
            )}
          </div>

          {/* Planner output */}
          {po && (
            <div className="space-y-2">
              <p className="font-semibold text-blue-900">Planner</p>
              <div className="grid grid-cols-2 gap-x-4 gap-y-1 font-mono text-blue-800">
                <span className="text-muted-foreground">Ramas detectadas</span>
                <span>{po.branches.map((b) => b.name).join(", ")}</span>
                <span className="text-muted-foreground">Jurisdicciones</span>
                <span>{po.jurisdictions.join(", ") || "—"}</span>
                <span className="text-muted-foreground">Output type</span>
                <span>{po.output_type}</span>
              </div>
              {po.sub_tasks.length > 0 && (
                <div>
                  <p className="text-muted-foreground mb-1">Sub-tareas:</p>
                  <ul className="space-y-0.5">
                    {po.sub_tasks.map((t) => (
                      <li key={t.id} className="font-mono text-blue-800">
                        {t.id}: {t.branch} (peso {t.weight.toFixed(2)})
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}

          {/* Judge verdict */}
          {jv && (
            <div className="space-y-2">
              <p className="font-semibold text-blue-900">
                Judge{" "}
                <span
                  className={[
                    "ml-1 rounded px-1.5 py-0.5 font-mono text-xs",
                    jv.verdict === "publish"
                      ? "bg-green-100 text-green-800"
                      : jv.verdict === "reject"
                        ? "bg-red-100 text-red-800"
                        : "bg-amber-100 text-amber-800",
                  ].join(" ")}
                >
                  {jv.verdict}
                </span>
              </p>
              <div className="grid grid-cols-2 gap-x-4 gap-y-1 font-mono text-blue-800">
                {Object.entries(jv.scores).map(([k, v]) => (
                  <>
                    <span key={`k-${k}`} className="text-muted-foreground">
                      {k}
                    </span>
                    <span key={`v-${k}`}>{(v * 100).toFixed(0)}%</span>
                  </>
                ))}
              </div>
              {jv.gaps.length > 0 && (
                <div>
                  <p className="text-muted-foreground mb-1">
                    Brechas identificadas:
                  </p>
                  <ul className="list-disc list-inside space-y-0.5 text-blue-800">
                    {jv.gaps.map((g, i) => (
                      <li key={i}>{g}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}

          {/* Cost breakdown */}
          {response.cost_breakdown_by_agent &&
            Object.keys(response.cost_breakdown_by_agent).length > 0 && (
              <div>
                <p className="font-semibold text-blue-900 mb-1">
                  Coste por agente
                </p>
                <div className="grid grid-cols-2 gap-x-4 gap-y-1 font-mono text-blue-800">
                  {Object.entries(response.cost_breakdown_by_agent).map(
                    ([k, v]) => (
                      <>
                        <span
                          key={`k-${k}`}
                          className="text-muted-foreground truncate"
                        >
                          {k}
                        </span>
                        <span key={`v-${k}`}>${v.toFixed(4)}</span>
                      </>
                    ),
                  )}
                </div>
              </div>
            )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Cross-jurisdiction collapsible sections
// ---------------------------------------------------------------------------

function CrossJurisdictionView({
  branchAnswers,
  citations,
  onChipClick,
}: {
  branchAnswers: Record<string, string>;
  citations: CitationMapping[];
  onChipClick: (citation: CitationMapping) => void;
}) {
  const branches = Object.keys(branchAnswers);
  const [openBranches, setOpenBranches] = useState<Record<string, boolean>>({});

  if (branches.length === 0) return null;

  function toggleBranch(branch: string) {
    setOpenBranches((prev) => ({ ...prev, [branch]: !prev[branch] }));
  }

  return (
    <div className="space-y-2">
      <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
        Respuestas por rama especializada
      </p>
      {branches.map((branch) => (
        <div key={branch} className="rounded-md border border-border">
          <button
            type="button"
            onClick={() => toggleBranch(branch)}
            className="w-full flex items-center justify-between px-4 py-2.5 text-xs font-medium text-foreground hover:bg-muted/50 transition-colors"
          >
            <span className="font-mono">{branch}</span>
            <span className="text-muted-foreground text-[10px]">
              {openBranches[branch] ? "▲ Ocultar" : "▼ Ver análisis"}
            </span>
          </button>
          {openBranches[branch] && (
            <div className="border-t border-border px-4 py-3 text-sm leading-relaxed prose prose-sm max-w-none">
              {renderAnswerWithChips(
                branchAnswers[branch] ?? "",
                citations,
                onChipClick,
              )}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main ResponseView
// ---------------------------------------------------------------------------

export function ResponseView({
  response,
  selectedJurisdictions,
}: {
  response: ConsultResponse;
  selectedJurisdictions?: string[];
}) {
  const [activeCitation, setActiveCitation] = useState<CitationMapping | null>(
    null,
  );
  const [showFeedback, setShowFeedback] = useState(false);
  const [metaExpanded, setMetaExpanded] = useState(false);

  const uncitedClaims = response.verification?.uncited_claims ?? [];
  const meta = response.metadata;
  const hasBranchAnswers =
    response.branch_answers && Object.keys(response.branch_answers).length > 1;

  function handleExport() {
    window.open(
      `${API_BASE}/api/v1/consult/${response.trace_id}/export`,
      "_blank",
    );
  }

  const isComparative = !!response.comparative_output;

  return (
    <div className="space-y-4">
      {/* Verification banner */}
      {response.verification && (
        <VerificationBanner report={response.verification} />
      )}

      {/* Branch detection banner */}
      <BranchDetectionBanner
        response={response}
        userSelectedJurisdictions={selectedJurisdictions}
      />

      {/* PMJ reasoning panel */}
      <RazonamientoPanel response={response} />

      {/* Cross-jurisdiction per-branch collapsible sections */}
      {hasBranchAnswers && (
        <CrossJurisdictionView
          branchAnswers={response.branch_answers!}
          citations={response.citations}
          onChipClick={setActiveCitation}
        />
      )}

      {/* Comparative view (structured pivot table) */}
      {response.comparative_output && (
        <ComparativeView
          comparative={response.comparative_output}
          traceId={response.trace_id}
          onCitationClick={setActiveCitation}
        />
      )}

      {/* Answer text with clickable [REF:n] chips */}
      <article className="prose prose-sm max-w-none rounded-lg border border-border bg-background p-5 leading-relaxed text-sm">
        {renderAnswerWithChips(
          response.answer,
          response.citations,
          setActiveCitation,
        )}
      </article>

      {/* Uncited claims */}
      {uncitedClaims.length > 0 && (
        <div className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3">
          <p className="text-xs font-semibold text-amber-800 mb-2">
            Lagunas declaradas (afirmaciones sin cita verificable):
          </p>
          <ul className="list-disc list-inside space-y-1 text-xs text-amber-700">
            {uncitedClaims.map((claim, i) => (
              <li key={i}>{claim}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Action bar */}
      <div className="flex items-center justify-between gap-3 border-t border-border pt-3">
        <div className="text-xs text-muted-foreground font-mono">
          {response.trace_id.slice(0, 8)}…
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setMetaExpanded(!metaExpanded)}
            className="text-xs text-muted-foreground underline hover:text-foreground"
          >
            {metaExpanded ? "Ocultar metadatos" : "Metadatos técnicos"}
          </button>
          <button
            onClick={handleExport}
            className="inline-flex items-center gap-1 rounded border border-input px-3 py-1.5 text-xs font-medium hover:bg-muted transition-colors"
          >
            ↓ Exportar Word
          </button>
          {isComparative && (
            <a
              href={`${API_BASE}/api/v1/consult/${response.trace_id}/export/comparative`}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 rounded border border-input px-3 py-1.5 text-xs font-medium hover:bg-muted transition-colors"
            >
              ↓ Exportar XLSX
            </a>
          )}
          <button
            onClick={() => setShowFeedback(true)}
            className="inline-flex items-center gap-1 rounded border border-input px-3 py-1.5 text-xs font-medium hover:bg-muted transition-colors"
          >
            ⚑ Reportar problema
          </button>
        </div>
      </div>

      {/* Metadata panel */}
      {metaExpanded && (
        <div className="rounded-md border border-border bg-muted/30 px-4 py-3 text-xs space-y-1 font-mono">
          <div className="grid grid-cols-2 gap-x-4 gap-y-1">
            <span className="text-muted-foreground">Trace ID</span>
            <span>{response.trace_id}</span>
            <span className="text-muted-foreground">Modelo</span>
            <span>{String(meta.model ?? "—")}</span>
            <span className="text-muted-foreground">Prompt version</span>
            <span>{String(meta.prompt_version ?? "—")}</span>
            <span className="text-muted-foreground">Latencia</span>
            <span>
              {meta.latency_ms != null ? `${String(meta.latency_ms)} ms` : "—"}
            </span>
            <span className="text-muted-foreground">Coste estimado</span>
            <span>
              {meta.cost_estimate_usd != null
                ? `$${(meta.cost_estimate_usd as number).toFixed(4)}`
                : "—"}
            </span>
            <span className="text-muted-foreground">Consulta reescrita</span>
            <span className="truncate">{response.query_rewritten || "—"}</span>
          </div>
        </div>
      )}

      {/* Citation side panel */}
      {activeCitation && (
        <CitationPanel
          citation={activeCitation}
          onClose={() => setActiveCitation(null)}
        />
      )}

      {/* Feedback modal */}
      {showFeedback && (
        <FeedbackModal
          traceId={response.trace_id}
          answerExcerpt={response.answer.slice(0, 200)}
          onClose={() => setShowFeedback(false)}
        />
      )}
    </div>
  );
}
