"use client";

import { useState } from "react";
import type {
  CitationMapping,
  ComparativeDimension,
  ComparativeResponse,
  Divergence,
  JurisdictionEntry,
  RiskLevel,
} from "@/lib/api";
import { getComparativeExportUrl } from "@/lib/api";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function riskBadgeClass(level: RiskLevel): string {
  return {
    low: "bg-green-100 text-green-800 border-green-200",
    medium: "bg-amber-100 text-amber-800 border-amber-200",
    high: "bg-red-100 text-red-800 border-red-200",
  }[level];
}

function coverageCellClass(coverage: JurisdictionEntry["coverage"]): string {
  return {
    full: "bg-background",
    partial: "bg-yellow-50",
    insufficient: "bg-amber-50 border-amber-200",
  }[coverage];
}

function severityLabel(s: RiskLevel): string {
  return { low: "Baja", medium: "Media", high: "Alta" }[s];
}

// ---------------------------------------------------------------------------
// Cell expand panel
// ---------------------------------------------------------------------------

function CellPanel({
  entry,
  jurisdiction,
  dimensionName,
  citations,
  onClose,
  onCitationClick,
}: {
  entry: JurisdictionEntry;
  jurisdiction: string;
  dimensionName: string;
  citations: CitationMapping[];
  onClose: () => void;
  onCitationClick: (c: CitationMapping) => void;
}) {
  const refCitations = entry.refs
    .map((r) => citations.find((c) => c.index === r))
    .filter(Boolean) as CitationMapping[];

  return (
    <aside className="fixed right-0 top-0 z-50 h-full w-96 border-l border-border bg-background shadow-xl flex flex-col">
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <div>
          <p className="text-xs text-muted-foreground">{dimensionName}</p>
          <h3 className="font-semibold text-sm">{jurisdiction}</h3>
        </div>
        <button
          onClick={onClose}
          className="rounded p-1 hover:bg-muted text-muted-foreground text-lg leading-none"
          aria-label="Cerrar"
        >
          ×
        </button>
      </div>
      <div className="flex-1 overflow-y-auto p-4 space-y-4 text-sm">
        {entry.coverage !== "full" && (
          <div
            className={`rounded border px-3 py-2 text-xs ${
              entry.coverage === "insufficient"
                ? "bg-amber-50 border-amber-200 text-amber-800"
                : "bg-yellow-50 border-yellow-200 text-yellow-800"
            }`}
          >
            {entry.coverage === "insufficient"
              ? "Cobertura insuficiente"
              : "Cobertura parcial"}
            {entry.note && ` — ${entry.note}`}
          </div>
        )}

        {entry.text ? (
          <p className="leading-relaxed">{entry.text}</p>
        ) : (
          <p className="text-muted-foreground italic">
            Sin análisis disponible para esta jurisdicción en esta dimensión.
          </p>
        )}

        {entry.note && entry.coverage === "full" && (
          <p className="text-xs text-muted-foreground italic">{entry.note}</p>
        )}

        {refCitations.length > 0 && (
          <div className="space-y-2">
            <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
              Referencias
            </p>
            {refCitations.map((cit) => (
              <button
                key={cit.chunk_id}
                onClick={() => onCitationClick(cit)}
                className="w-full text-left rounded border border-border px-3 py-2 hover:bg-muted/50 transition-colors space-y-1"
              >
                <p className="text-xs font-mono text-primary">
                  [REF:{cit.index}] {cit.source_id}
                </p>
                <p className="text-xs text-muted-foreground line-clamp-2">
                  {cit.fragment_text}
                </p>
              </button>
            ))}
          </div>
        )}
      </div>
    </aside>
  );
}

// ---------------------------------------------------------------------------
// Pivot table
// ---------------------------------------------------------------------------

function PivotTable({
  dimensions,
  jurisdictions,
  citations,
  onCitationClick,
}: {
  dimensions: ComparativeDimension[];
  jurisdictions: string[];
  citations: CitationMapping[];
  onCitationClick: (c: CitationMapping) => void;
}) {
  const [activeCell, setActiveCell] = useState<{
    entry: JurisdictionEntry;
    jurisdiction: string;
    dimensionName: string;
  } | null>(null);

  return (
    <>
      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full text-xs border-collapse">
          <thead>
            <tr className="bg-primary text-primary-foreground">
              <th className="px-3 py-2.5 text-left font-semibold w-40 min-w-[10rem]">
                Dimensión
              </th>
              {jurisdictions.map((j) => (
                <th
                  key={j}
                  className="px-3 py-2.5 text-center font-semibold min-w-[160px]"
                >
                  {j}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {dimensions.map((dim, dimIdx) => (
              <tr
                key={dim.name}
                className={dimIdx % 2 === 0 ? "bg-muted/20" : "bg-background"}
              >
                <td className="px-3 py-2 font-medium align-top border-b border-border/50 text-foreground">
                  {dim.name}
                </td>
                {jurisdictions.map((j) => {
                  const entry = dim.by_jurisdiction[j] ?? {
                    text: null,
                    refs: [],
                    coverage: "insufficient" as const,
                    note: null,
                  };
                  const isInsufficient = entry.coverage === "insufficient";
                  return (
                    <td
                      key={j}
                      className={`px-3 py-2 align-top border-b border-l border-border/50 cursor-pointer hover:brightness-95 transition-all ${coverageCellClass(entry.coverage)}`}
                      onClick={() =>
                        setActiveCell({ entry, jurisdiction: j, dimensionName: dim.name })
                      }
                    >
                      {isInsufficient ? (
                        <span className="text-amber-700 italic">
                          Cobertura insuficiente ↗
                        </span>
                      ) : (
                        <>
                          <p className="line-clamp-3 text-foreground leading-relaxed">
                            {entry.text ?? "—"}
                          </p>
                          {entry.refs.length > 0 && (
                            <div className="mt-1 flex flex-wrap gap-1">
                              {entry.refs.map((r) => (
                                <span
                                  key={r}
                                  className="inline-flex items-center rounded bg-primary/10 px-1 py-0.5 font-mono text-[10px] text-primary"
                                >
                                  [{r}]
                                </span>
                              ))}
                            </div>
                          )}
                          {entry.coverage === "partial" && (
                            <span className="mt-1 block text-[10px] text-yellow-700 italic">
                              Cobertura parcial
                            </span>
                          )}
                        </>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {activeCell && (
        <CellPanel
          entry={activeCell.entry}
          jurisdiction={activeCell.jurisdiction}
          dimensionName={activeCell.dimensionName}
          citations={citations}
          onClose={() => setActiveCell(null)}
          onCitationClick={onCitationClick}
        />
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// Divergences section
// ---------------------------------------------------------------------------

function DivergenceCard({ div }: { div: Divergence }) {
  return (
    <div className="rounded-md border border-border bg-background px-4 py-3 space-y-1.5">
      <div className="flex items-start justify-between gap-3">
        <p className="text-sm font-medium text-foreground leading-snug">
          {div.description}
        </p>
        <span
          className={`shrink-0 rounded border px-2 py-0.5 text-xs font-semibold ${riskBadgeClass(div.severity)}`}
        >
          {severityLabel(div.severity)}
        </span>
      </div>
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <span className="italic">{div.dimension}</span>
        <span>·</span>
        <span>{div.jurisdictions_involved.join(" vs ")}</span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Risk differential cards
// ---------------------------------------------------------------------------

function RiskDifferentialSection({
  riskDifferential,
  riskRationale,
  jurisdictions,
}: {
  riskDifferential: Record<string, RiskLevel>;
  riskRationale: string;
  jurisdictions: string[];
}) {
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-3">
        {jurisdictions.map((j) => {
          const level = riskDifferential[j] ?? "medium";
          return (
            <div
              key={j}
              className="rounded-lg border px-4 py-3 min-w-[100px] text-center space-y-1"
            >
              <p className="text-sm font-bold text-foreground">{j}</p>
              <span
                className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold ${riskBadgeClass(level)}`}
              >
                {level.toUpperCase()}
              </span>
            </div>
          );
        })}
      </div>
      <p className="text-xs text-muted-foreground leading-relaxed italic">
        {riskRationale}
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Coverage gaps
// ---------------------------------------------------------------------------

function CoverageGapsSection({
  gaps,
}: {
  gaps: ComparativeResponse["coverage_gaps"];
}) {
  if (gaps.length === 0) return null;
  return (
    <div className="space-y-2">
      {gaps.map((gap) => (
        <div
          key={gap.jurisdiction}
          className="rounded border border-amber-200 bg-amber-50 px-3 py-2 text-xs space-y-0.5"
        >
          <p className="font-semibold text-amber-900">
            {gap.jurisdiction} — cobertura limitada
          </p>
          <p className="text-amber-800">{gap.reason}</p>
          <p className="text-amber-700">→ {gap.recommendation}</p>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main ComparativeView
// ---------------------------------------------------------------------------

export function ComparativeView({
  comparative,
  traceId,
  onCitationClick,
}: {
  comparative: ComparativeResponse;
  traceId: string;
  onCitationClick: (citation: CitationMapping) => void;
}) {
  const [activeSection, setActiveSection] = useState<
    "table" | "divergences" | "common" | "risk" | "gaps"
  >("table");

  const tabs = [
    { id: "table" as const, label: "Tabla comparativa" },
    {
      id: "divergences" as const,
      label: `Divergencias (${comparative.divergences.length})`,
    },
    {
      id: "common" as const,
      label: `Terreno común (${comparative.common_ground.length})`,
    },
    { id: "risk" as const, label: "Riesgo diferencial" },
    ...(comparative.coverage_gaps.length > 0
      ? [{ id: "gaps" as const, label: `Lagunas (${comparative.coverage_gaps.length})` }]
      : []),
  ];

  const verificationColors = {
    green: "bg-green-50 border-green-200 text-green-800",
    amber: "bg-amber-50 border-amber-200 text-amber-800",
    red: "bg-red-50 border-red-200 text-red-800",
  };

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="rounded-lg border border-primary/20 bg-primary/5 px-4 py-3 space-y-2">
        <div className="flex items-start justify-between gap-3">
          <div className="space-y-1">
            <p className="text-xs font-semibold text-primary uppercase tracking-wide">
              Análisis comparativo
            </p>
            <p className="text-sm font-medium text-foreground leading-snug">
              {comparative.issue}
            </p>
          </div>
          <span
            className={`shrink-0 rounded border px-2 py-0.5 text-xs font-semibold ${verificationColors[comparative.verification_status]}`}
          >
            {comparative.verification_status.toUpperCase()}
          </span>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {comparative.jurisdictions_compared.map((j) => (
            <span
              key={j}
              className="inline-flex items-center rounded-full bg-primary/10 px-2.5 py-0.5 text-xs font-medium text-primary"
            >
              {j}
            </span>
          ))}
          <span className="text-xs text-muted-foreground self-center">
            · {comparative.dimensions.length} dimensiones · {comparative.divergences.length} divergencias
          </span>
        </div>
      </div>

      {/* Tab bar */}
      <div className="flex flex-wrap gap-1 border-b border-border">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveSection(tab.id)}
            className={`px-3 py-2 text-xs font-medium transition-colors border-b-2 -mb-px ${
              activeSection === tab.id
                ? "border-primary text-primary"
                : "border-transparent text-muted-foreground hover:text-foreground"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {activeSection === "table" && (
        <PivotTable
          dimensions={comparative.dimensions}
          jurisdictions={comparative.jurisdictions_compared}
          citations={comparative.citations}
          onCitationClick={onCitationClick}
        />
      )}

      {activeSection === "divergences" && (
        <div className="space-y-2">
          {comparative.divergences.length === 0 ? (
            <p className="text-sm text-muted-foreground italic">
              No se identificaron divergencias relevantes.
            </p>
          ) : (
            comparative.divergences.map((div, i) => (
              <DivergenceCard key={i} div={div} />
            ))
          )}
        </div>
      )}

      {activeSection === "common" && (
        <div className="space-y-2">
          {comparative.common_ground.length === 0 ? (
            <p className="text-sm text-muted-foreground italic">
              No se identificaron principios comunes.
            </p>
          ) : (
            <ul className="space-y-1.5">
              {comparative.common_ground.map((item, i) => (
                <li key={i} className="flex items-start gap-2 text-sm">
                  <span className="mt-1 text-green-600 shrink-0">✓</span>
                  <span>{item}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {activeSection === "risk" && (
        <RiskDifferentialSection
          riskDifferential={comparative.risk_differential}
          riskRationale={comparative.risk_rationale}
          jurisdictions={comparative.jurisdictions_compared}
        />
      )}

      {activeSection === "gaps" && (
        <CoverageGapsSection gaps={comparative.coverage_gaps} />
      )}

      {/* Export action */}
      <div className="flex justify-end pt-2">
        <a
          href={getComparativeExportUrl(traceId)}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1.5 rounded border border-input px-3 py-1.5 text-xs font-medium hover:bg-muted transition-colors"
        >
          ↓ Exportar XLSX
        </a>
      </div>
    </div>
  );
}
