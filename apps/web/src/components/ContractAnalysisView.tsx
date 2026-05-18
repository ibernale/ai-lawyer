"use client";

import { useState } from "react";
import type { ContractAnalysis, RiskFactor } from "@/lib/api";
import { ObligationGraphView } from "@/components/ObligationGraphView";
import { CompliancePanel } from "@/components/CompliancePanel";

// ─── helpers ──────────────────────────────────────────────────────────────

const SEVERITY_ORDER: Record<RiskFactor["severity"], number> = {
  critical: 0,
  high: 1,
  medium: 2,
  low: 3,
};

const SEVERITY_BADGE: Record<
  RiskFactor["severity"],
  { bg: string; text: string; label: string }
> = {
  critical: {
    bg: "bg-red-100 dark:bg-red-900/30",
    text: "text-red-700 dark:text-red-400",
    label: "CRÍTICO",
  },
  high: {
    bg: "bg-orange-100 dark:bg-orange-900/30",
    text: "text-orange-600 dark:text-orange-400",
    label: "ALTO",
  },
  medium: {
    bg: "bg-yellow-100 dark:bg-yellow-900/30",
    text: "text-yellow-700 dark:text-yellow-500",
    label: "MEDIO",
  },
  low: {
    bg: "bg-green-100 dark:bg-green-900/30",
    text: "text-green-700 dark:text-green-500",
    label: "BAJO",
  },
};

const CATEGORY_ICON: Record<RiskFactor["category"], string> = {
  financial: "💰",
  legal: "⚖️",
  operational: "⚙️",
  strategic: "🎯",
};

const RATING_CONFIG: Record<
  ContractAnalysis["risk_assessment"]["overall_rating"],
  { color: string; stroke: string; label: string; textColor: string }
> = {
  green: {
    color: "text-green-600 dark:text-green-400",
    stroke: "stroke-green-500",
    label: "RIESGO BAJO",
    textColor: "text-green-600 dark:text-green-400",
  },
  yellow: {
    color: "text-yellow-600 dark:text-yellow-400",
    stroke: "stroke-yellow-500",
    label: "RIESGO MODERADO",
    textColor: "text-yellow-600 dark:text-yellow-400",
  },
  red: {
    color: "text-red-600 dark:text-red-400",
    stroke: "stroke-red-600",
    label: "RIESGO ALTO",
    textColor: "text-red-600 dark:text-red-400",
  },
  critical: {
    color: "text-red-700 dark:text-red-300",
    stroke: "stroke-red-700",
    label: "RIESGO CRÍTICO",
    textColor: "text-red-700 dark:text-red-300",
  },
};

const CONTRACT_TYPE_BADGE: Record<string, string> = {
  NDA: "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300",
  LoanAgreement:
    "bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-300",
  ServiceAgreement:
    "bg-teal-100 text-teal-700 dark:bg-teal-900/30 dark:text-teal-300",
  EmploymentContract:
    "bg-indigo-100 text-indigo-700 dark:bg-indigo-900/30 dark:text-indigo-300",
  LeaseAgreement:
    "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300",
};

function contractTypeBadgeClass(docType: string): string {
  return (
    CONTRACT_TYPE_BADGE[docType] ??
    "bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300"
  );
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return "—";
  try {
    return new Date(dateStr).toLocaleDateString("es-ES", {
      day: "2-digit",
      month: "long",
      year: "numeric",
    });
  } catch {
    return dateStr;
  }
}

const JURISDICTION_FLAG: Record<string, string> = {
  ES: "🇪🇸",
  EU: "🇪🇺",
  UK: "🇬🇧",
  US: "🇺🇸",
  DE: "🇩🇪",
  FR: "🇫🇷",
  PT: "🇵🇹",
  BR: "🇧🇷",
  MX: "🇲🇽",
  AR: "🇦🇷",
};

// ─── Risk Gauge ────────────────────────────────────────────────────────────

function RiskGauge({
  score,
  rating,
}: {
  score: number;
  rating: ContractAnalysis["risk_assessment"]["overall_rating"];
}) {
  const cfg = RATING_CONFIG[rating];
  const displayScore = Math.round(score * 100);

  // SVG semicircle gauge — radius 40, centered at 60,60
  const R = 40;
  const CX = 60;
  const CY = 60;
  const circumference = Math.PI * R; // half circle
  const dashOffset = circumference * (1 - score);

  return (
    <div className="flex flex-col items-center gap-2">
      <div className="relative w-32 h-20">
        <svg viewBox="0 0 120 70" className="w-full h-full" aria-hidden="true">
          {/* Background arc */}
          <path
            d={`M ${CX - R} ${CY} A ${R} ${R} 0 0 1 ${CX + R} ${CY}`}
            fill="none"
            className="stroke-muted"
            strokeWidth="8"
            strokeLinecap="round"
          />
          {/* Filled arc */}
          <path
            d={`M ${CX - R} ${CY} A ${R} ${R} 0 0 1 ${CX + R} ${CY}`}
            fill="none"
            className={cfg.stroke}
            strokeWidth="8"
            strokeLinecap="round"
            strokeDasharray={`${circumference} ${circumference}`}
            strokeDashoffset={dashOffset}
            style={{ transition: "stroke-dashoffset 0.8s ease" }}
          />
        </svg>
        {/* Score centered below arc */}
        <div className="absolute bottom-0 left-0 right-0 flex flex-col items-center">
          <span className={`text-2xl font-bold tabular-nums ${cfg.color}`}>
            {displayScore}
          </span>
          <span className="text-[10px] text-muted-foreground leading-none">
            /100
          </span>
        </div>
      </div>
      <span className={`text-xs font-bold tracking-wider ${cfg.textColor}`}>
        {cfg.label}
      </span>
    </div>
  );
}

// ─── Stats mini-card ───────────────────────────────────────────────────────

function StatCard({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-lg border border-border bg-card p-3 text-center">
      <p className="text-lg font-bold text-foreground">{value}</p>
      <p className="text-[11px] text-muted-foreground leading-tight mt-0.5">
        {label}
      </p>
    </div>
  );
}

// ─── Coming-soon placeholder card ─────────────────────────────────────────

function ComingSoonCard({
  title,
  availableIn,
}: {
  title: string;
  availableIn: string;
}) {
  return (
    <div className="rounded-lg border border-dashed border-border bg-muted/30 p-4 opacity-60 select-none">
      <p className="text-sm font-medium text-foreground">{title}</p>
      <p className="text-xs text-muted-foreground mt-1">
        Disponible en {availableIn}
      </p>
    </div>
  );
}

// ─── Risk Factor row ───────────────────────────────────────────────────────

function RiskFactorRow({ factor }: { factor: RiskFactor }) {
  const sev = SEVERITY_BADGE[factor.severity];
  const confidencePct = Math.round(factor.confidence * 100);

  return (
    <div className="rounded-lg border border-border bg-card p-4 space-y-2">
      <div className="flex items-start gap-3 flex-wrap">
        <span
          className={`inline-flex items-center rounded px-2 py-0.5 text-[10px] font-bold tracking-wider shrink-0 ${sev.bg} ${sev.text}`}
        >
          {sev.label}
        </span>
        <span className="text-sm shrink-0" aria-hidden="true">
          {CATEGORY_ICON[factor.category]}
        </span>
        <p className="text-sm font-semibold text-foreground flex-1 min-w-0">
          {factor.issue}
        </p>
      </div>

      {factor.clause_refs.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {factor.clause_refs.map((ref) => (
            <span
              key={ref}
              className="inline-block rounded bg-muted px-1.5 py-0.5 text-[10px] font-mono text-muted-foreground"
            >
              [{ref}]
            </span>
          ))}
        </div>
      )}

      {factor.remediation && (
        <p className="text-xs italic text-muted-foreground">
          {factor.remediation}
        </p>
      )}

      {/* Confidence bar */}
      <div className="flex items-center gap-2">
        <span className="text-[10px] text-muted-foreground whitespace-nowrap">
          Confianza {confidencePct}%
        </span>
        <div className="flex-1 h-1 rounded-full bg-muted overflow-hidden">
          <div
            className="h-full rounded-full bg-brand-500"
            style={{ width: `${confidencePct}%` }}
          />
        </div>
      </div>
    </div>
  );
}

// ─── Severity group section ────────────────────────────────────────────────

function RiskSeverityGroup({
  severity,
  factors,
  defaultExpanded,
}: {
  severity: RiskFactor["severity"];
  factors: RiskFactor[];
  defaultExpanded: boolean;
}) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const sev = SEVERITY_BADGE[severity];

  if (factors.length === 0) return null;

  return (
    <div className="space-y-2">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex items-center gap-2 text-left w-full group"
      >
        <span
          className={`inline-flex items-center rounded px-2 py-0.5 text-[10px] font-bold tracking-wider ${sev.bg} ${sev.text}`}
        >
          {sev.label}
        </span>
        <span className="text-xs text-muted-foreground">
          {factors.length} factor{factors.length !== 1 ? "es" : ""}
        </span>
        <span className="ml-auto text-muted-foreground group-hover:text-foreground transition-colors">
          {expanded ? "▲" : "▼"}
        </span>
      </button>

      {expanded && (
        <div className="space-y-2 pl-1">
          {factors.map((f, idx) => (
            <RiskFactorRow key={idx} factor={f} />
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Main component ────────────────────────────────────────────────────────

export function ContractAnalysisView({
  analysis,
}: {
  analysis: ContractAnalysis;
}) {
  const { metadata, risk_assessment, summary, recommendations } = analysis;

  const sortedFactors = [...risk_assessment.factors].sort(
    (a, b) => SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity],
  );

  const bySeverity: Record<RiskFactor["severity"], RiskFactor[]> = {
    critical: sortedFactors.filter((f) => f.severity === "critical"),
    high: sortedFactors.filter((f) => f.severity === "high"),
    medium: sortedFactors.filter((f) => f.severity === "medium"),
    low: sortedFactors.filter((f) => f.severity === "low"),
  };

  const criticalHighCount = bySeverity.critical.length + bySeverity.high.length;

  const latencySeconds =
    analysis.latency_ms != null
      ? (analysis.latency_ms / 1000).toFixed(1)
      : null;

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
      {/* ── Left column (2/3) ─────────────────────────────────────── */}
      <div className="lg:col-span-2 space-y-6">
        {/* Contract header card */}
        <div className="rounded-xl border border-border bg-card p-5 space-y-4">
          <div className="flex flex-wrap items-start gap-3">
            <span
              className={`inline-flex items-center rounded-full px-3 py-1 text-xs font-semibold ${contractTypeBadgeClass(metadata.document_type)}`}
            >
              {metadata.document_type}
            </span>
            <p className="text-sm text-muted-foreground truncate">
              {analysis.filename}
            </p>
          </div>

          {/* Parties */}
          {metadata.parties.length > 0 && (
            <div className="space-y-1.5">
              <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Partes
              </p>
              <div className="flex flex-wrap gap-2">
                {metadata.parties.map((party, idx) => (
                  <div
                    key={idx}
                    className="flex items-center gap-1.5 rounded-md border border-border bg-muted/40 px-2.5 py-1"
                  >
                    <span className="text-sm font-medium text-foreground">
                      {party.name}
                    </span>
                    <span className="text-[10px] text-muted-foreground">
                      {party.role}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Jurisdiction + governing law */}
          <div className="flex flex-wrap gap-4 text-sm">
            {metadata.jurisdiction.length > 0 && (
              <div className="space-y-1">
                <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                  Jurisdicción
                </p>
                <div className="flex flex-wrap gap-1.5">
                  {metadata.jurisdiction.map((j) => (
                    <span
                      key={j}
                      className="inline-flex items-center gap-1 rounded-full bg-muted px-2.5 py-0.5 text-xs text-foreground"
                    >
                      {JURISDICTION_FLAG[j] ?? ""} {j}
                    </span>
                  ))}
                </div>
              </div>
            )}
            {metadata.governing_law && (
              <div className="space-y-1">
                <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                  Ley aplicable
                </p>
                <p className="text-xs text-foreground">
                  {metadata.governing_law}
                </p>
              </div>
            )}
          </div>

          {/* Applicable framework */}
          {metadata.applicable_framework.length > 0 && (
            <div className="space-y-1.5">
              <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Marco regulatorio
              </p>
              <div className="flex flex-wrap gap-1.5">
                {metadata.applicable_framework.map((reg) => (
                  <span
                    key={reg}
                    className="inline-block rounded bg-brand-50 px-2 py-0.5 text-[11px] font-medium text-brand-700 border border-brand-200 dark:bg-brand-950/30 dark:text-brand-300 dark:border-brand-800"
                  >
                    {reg}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Dates */}
          {(metadata.effective_date ?? metadata.termination_date) && (
            <div className="flex flex-wrap gap-6 text-sm">
              {metadata.effective_date && (
                <div className="space-y-0.5">
                  <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                    Entrada en vigor
                  </p>
                  <p className="text-xs text-foreground">
                    {formatDate(metadata.effective_date)}
                  </p>
                </div>
              )}
              {metadata.termination_date && (
                <div className="space-y-0.5">
                  <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                    Vencimiento
                  </p>
                  <p className="text-xs text-foreground">
                    {formatDate(metadata.termination_date)}
                  </p>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Executive summary */}
        {summary && (
          <div className="rounded-xl border border-border bg-muted/30 p-5 dark:bg-muted/10">
            <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-2">
              Resumen ejecutivo
            </p>
            <p className="text-sm text-foreground leading-relaxed">{summary}</p>
          </div>
        )}

        {/* Risk factors */}
        <div className="space-y-4">
          <h2 className="text-base font-semibold text-foreground">
            Factores de riesgo
          </h2>
          {sortedFactors.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No se identificaron factores de riesgo.
            </p>
          ) : (
            <div className="space-y-4">
              {(["critical", "high", "medium", "low"] as const).map((sev) => (
                <RiskSeverityGroup
                  key={sev}
                  severity={sev}
                  factors={bySeverity[sev]}
                  defaultExpanded={sev === "critical" || sev === "high"}
                />
              ))}
            </div>
          )}
        </div>

        {/* Recommendations */}
        {recommendations.length > 0 && (
          <div className="space-y-3">
            <h2 className="text-base font-semibold text-foreground">
              Recomendaciones
            </h2>
            <ol className="space-y-2">
              {recommendations.slice(0, 10).map((rec, idx) => (
                <li key={idx} className="flex items-start gap-3">
                  {/* Cosmetic checkbox */}
                  <span className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded border border-border bg-background">
                    <span className="sr-only">No marcado</span>
                  </span>
                  <span className="text-sm text-foreground leading-relaxed">
                    <span className="font-semibold text-muted-foreground mr-1.5">
                      {idx + 1}.
                    </span>
                    {rec}
                  </span>
                </li>
              ))}
            </ol>
          </div>
        )}

        {/* 13B: Obligation graph */}
        {analysis.obligations.nodes.length > 0 && (
          <ObligationGraphView obligations={analysis.obligations} />
        )}

        {/* 13B: Compliance findings */}
        {analysis.compliance_findings.length > 0 && (
          <CompliancePanel findings={analysis.compliance_findings} />
        )}
      </div>

      {/* ── Right column (1/3) ───────────────────────────────────── */}
      <div className="space-y-5">
        {/* Risk gauge */}
        <div className="rounded-xl border border-border bg-card p-5 flex flex-col items-center gap-4">
          <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground self-start">
            Valoración de riesgo
          </p>
          <RiskGauge
            score={risk_assessment.overall_score}
            rating={risk_assessment.overall_rating}
          />
        </div>

        {/* Stats mini-cards */}
        <div className="grid grid-cols-2 gap-3">
          <StatCard label="Factores de riesgo" value={sortedFactors.length} />
          <StatCard label="Crítico + Alto" value={criticalHighCount} />
          <StatCard
            label="Regulaciones"
            value={metadata.applicable_framework.length}
          />
          {latencySeconds !== null && (
            <StatCard label="Tiempo análisis" value={`${latencySeconds}s`} />
          )}
        </div>

        {/* Coming soon — only 13C remains */}
        <div className="space-y-3">
          <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Próximamente
          </p>
          <ComingSoonCard title="Suite de negociación" availableIn="13C" />
        </div>
      </div>
    </div>
  );
}
