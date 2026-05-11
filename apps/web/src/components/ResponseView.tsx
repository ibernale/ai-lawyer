"use client";

import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { CitationMapping, ConsultResponse, VerificationReport } from "@/lib/api";

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
          <p className="font-mono text-xs text-foreground">{citation.source_id}</p>
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

  const hasDetails = report.broken_refs.length > 0 || report.uncited_claims.length > 0;

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
                  <li key={ref}>[REF:{ref}] no resuelve a ningún fragmento indexado</li>
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

function renderAnswerWithChips(
  text: string,
  citations: CitationMapping[],
  onChipClick: (citation: CitationMapping) => void,
) {
  const parts = text.split(/(\[REF:\d+\])/g);
  return parts.map((part, i) => {
    const match = part.match(/^\[REF:(\d+)\]$/);
    if (match) {
      const idx = parseInt(match[1], 10);
      const citation = citations.find((c) => c.index === idx);
      return (
        <button
          key={i}
          onClick={() => citation && onChipClick(citation)}
          className="inline-flex items-center rounded bg-primary/10 px-1.5 py-0.5 text-xs font-mono font-medium text-primary hover:bg-primary/20 transition-colors mx-0.5"
          title={citation?.hierarchy_path ?? `REF:${idx}`}
        >
          [{idx}]
        </button>
      );
    }
    return part;
  });
}

// ---------------------------------------------------------------------------
// Main ResponseView
// ---------------------------------------------------------------------------

export function ResponseView({ response }: { response: ConsultResponse }) {
  const [activeCitation, setActiveCitation] = useState<CitationMapping | null>(null);

  const uncitedClaims = response.verification?.uncited_claims ?? [];

  return (
    <div className="space-y-4">
      {/* Verification banner */}
      {response.verification && (
        <VerificationBanner report={response.verification} />
      )}

      {/* Answer text with clickable [REF:n] chips */}
      <article className="prose prose-sm max-w-none rounded-lg border border-border bg-background p-5 leading-relaxed text-sm">
        {renderAnswerWithChips(response.answer, response.citations, setActiveCitation)}
      </article>

      {/* Uncited claims section */}
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

      {/* Legal disclaimer footer */}
      <div className="text-center text-xs text-muted-foreground pt-2">
        Trace ID:{" "}
        <span className="font-mono">{response.trace_id}</span>
        {response.metadata.latency_ms != null && (
          <> · {response.metadata.latency_ms as number}ms</>
        )}
      </div>

      {/* Citation side panel */}
      {activeCitation && (
        <CitationPanel
          citation={activeCitation}
          onClose={() => setActiveCitation(null)}
        />
      )}
    </div>
  );
}
