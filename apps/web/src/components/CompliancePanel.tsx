"use client";

import type { ComplianceFinding } from "@/lib/api";

// ─── Config ───────────────────────────────────────────────────────────────

const STATUS_CONFIG: Record<
  ComplianceFinding["status"],
  { icon: string; label: string; bg: string; text: string; sortOrder: number }
> = {
  non_compliant: {
    icon: "🔴",
    label: "No conforme",
    bg: "bg-red-100 dark:bg-red-900/30",
    text: "text-red-700 dark:text-red-400",
    sortOrder: 0,
  },
  requires_review: {
    icon: "🟡",
    label: "Requiere revisión",
    bg: "bg-yellow-100 dark:bg-yellow-900/30",
    text: "text-yellow-700 dark:text-yellow-500",
    sortOrder: 1,
  },
  compliant: {
    icon: "🟢",
    label: "Conforme",
    bg: "bg-green-100 dark:bg-green-900/30",
    text: "text-green-700 dark:text-green-500",
    sortOrder: 2,
  },
  not_applicable: {
    icon: "⚪",
    label: "No aplica",
    bg: "bg-gray-100 dark:bg-gray-800",
    text: "text-gray-600 dark:text-gray-400",
    sortOrder: 3,
  },
};

// ─── Overall status derivation ────────────────────────────────────────────

type OverallStatus = "non_compliant" | "requires_review" | "ok";

function deriveOverallStatus(findings: ComplianceFinding[]): OverallStatus {
  if (findings.some((f) => f.status === "non_compliant"))
    return "non_compliant";
  if (findings.some((f) => f.status === "requires_review"))
    return "requires_review";
  return "ok";
}

const OVERALL_CONFIG: Record<
  OverallStatus,
  { icon: string; label: string; bg: string; text: string; border: string }
> = {
  non_compliant: {
    icon: "⚠️",
    label: "Incumplimientos detectados",
    bg: "bg-red-50 dark:bg-red-950/20",
    text: "text-red-700 dark:text-red-400",
    border: "border-red-200 dark:border-red-800",
  },
  requires_review: {
    icon: "🔍",
    label: "Revisión requerida",
    bg: "bg-yellow-50 dark:bg-yellow-950/20",
    text: "text-yellow-700 dark:text-yellow-500",
    border: "border-yellow-200 dark:border-yellow-800",
  },
  ok: {
    icon: "✓",
    label: "Cumplimiento verificado",
    bg: "bg-green-50 dark:bg-green-950/20",
    text: "text-green-700 dark:text-green-500",
    border: "border-green-200 dark:border-green-800",
  },
};

// ─── Finding row ──────────────────────────────────────────────────────────

function FindingRow({ finding }: { finding: ComplianceFinding }) {
  const cfg = STATUS_CONFIG[finding.status];

  return (
    <div className="rounded-lg border border-border bg-card p-4 space-y-2">
      {/* Header */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="inline-block rounded bg-muted px-2 py-0.5 text-[11px] font-medium text-muted-foreground">
          {finding.regulation}
        </span>
        <span
          className={`inline-flex items-center gap-1.5 rounded px-2 py-0.5 text-[11px] font-semibold ${cfg.bg} ${cfg.text}`}
        >
          <span aria-hidden="true">{cfg.icon}</span>
          {cfg.label}
        </span>
      </div>

      {/* Finding text */}
      <p className="text-sm text-foreground leading-relaxed">
        {finding.finding}
      </p>

      {/* Clause refs */}
      {finding.clause_refs.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {finding.clause_refs.map((ref) => (
            <span
              key={ref}
              className="inline-block rounded bg-muted px-1.5 py-0.5 text-[10px] font-mono text-muted-foreground"
            >
              [{ref}]
            </span>
          ))}
        </div>
      )}

      {/* Recommendation */}
      {finding.recommendation && (
        <div className="rounded-md bg-amber-50 dark:bg-amber-950/20 border border-amber-200 dark:border-amber-800 px-3 py-2">
          <p className="text-xs text-amber-800 dark:text-amber-400 leading-relaxed">
            <span className="font-semibold">Recomendación: </span>
            {finding.recommendation}
          </p>
        </div>
      )}
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────

export function CompliancePanel({
  findings,
}: {
  findings: ComplianceFinding[];
}) {
  if (findings.length === 0) {
    return (
      <div className="rounded-xl border border-border bg-card p-6 text-center">
        <p className="text-sm text-muted-foreground">
          No se realizó verificación de cumplimiento
        </p>
      </div>
    );
  }

  const overallStatus = deriveOverallStatus(findings);
  const overallCfg = OVERALL_CONFIG[overallStatus];

  const sortedFindings = [...findings].sort(
    (a, b) =>
      STATUS_CONFIG[a.status].sortOrder - STATUS_CONFIG[b.status].sortOrder,
  );

  return (
    <div className="rounded-xl border border-border bg-card p-5 space-y-4">
      {/* Header */}
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-base font-semibold text-foreground">
          Verificación de cumplimiento
        </h2>
        {/* Overall status chip */}
        <span
          className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-semibold border ${overallCfg.bg} ${overallCfg.text} ${overallCfg.border}`}
        >
          <span aria-hidden="true">{overallCfg.icon}</span>
          {overallCfg.label}
        </span>
      </div>

      {/* Findings list */}
      <div className="space-y-3">
        {sortedFindings.map((finding, idx) => (
          <FindingRow key={idx} finding={finding} />
        ))}
      </div>
    </div>
  );
}
