"use client";

import { useState } from "react";
import type { NegotiationSummary, NegotiationIssue } from "@/lib/api";

// ─── Types ─────────────────────────────────────────────────────────────────

interface NegotiationPanelProps {
  negotiation: NegotiationSummary;
}

// ─── Constants ─────────────────────────────────────────────────────────────

const POSTURE_CONFIG: Record<
  NegotiationSummary["posture_label"],
  { bg: string; text: string; border: string; label: string }
> = {
  reject: {
    bg: "bg-red-100 dark:bg-red-900/30",
    text: "text-red-700 dark:text-red-400",
    border: "border-red-300 dark:border-red-700",
    label: "RECHAZAR",
  },
  renegotiate: {
    bg: "bg-orange-100 dark:bg-orange-900/30",
    text: "text-orange-700 dark:text-orange-400",
    border: "border-orange-300 dark:border-orange-700",
    label: "RENEGOCIAR",
  },
  conditionally_accept: {
    bg: "bg-yellow-100 dark:bg-yellow-900/30",
    text: "text-yellow-700 dark:text-yellow-600",
    border: "border-yellow-300 dark:border-yellow-700",
    label: "ACEPTAR CON CONDICIONES",
  },
  accept: {
    bg: "bg-green-100 dark:bg-green-900/30",
    text: "text-green-700 dark:text-green-400",
    border: "border-green-300 dark:border-green-700",
    label: "ACEPTAR",
  },
};

const PLAYBOOK_POSITION_BADGE: Record<
  NegotiationIssue["playbook_position"],
  { bg: string; text: string; label: string }
> = {
  preferred: {
    bg: "bg-green-100 dark:bg-green-900/30",
    text: "text-green-700 dark:text-green-400",
    label: "Preferida",
  },
  acceptable: {
    bg: "bg-blue-100 dark:bg-blue-900/30",
    text: "text-blue-700 dark:text-blue-400",
    label: "Aceptable",
  },
  fallback: {
    bg: "bg-yellow-100 dark:bg-yellow-900/30",
    text: "text-yellow-700 dark:text-yellow-600",
    label: "Fallback",
  },
  never_accept: {
    bg: "bg-red-100 dark:bg-red-900/30",
    text: "text-red-700 dark:text-red-400",
    label: "Nunca aceptar",
  },
  uncharted: {
    bg: "bg-gray-100 dark:bg-gray-800",
    text: "text-gray-600 dark:text-gray-400",
    label: "Sin playbook",
  },
};

const SCENARIO_KEYS = [
  { key: "accept_as_is", label: "Aceptar" },
  { key: "renegotiate_priority", label: "Renegociar prioritario" },
  { key: "full_renegotiation", label: "Negociación completa" },
] as const;

// ─── PostureGauge ──────────────────────────────────────────────────────────

function PostureGauge({
  score,
  label,
}: {
  score: number;
  label: NegotiationSummary["posture_label"];
}) {
  const cfg = POSTURE_CONFIG[label];
  const displayScore = Math.round(score * 100);
  const R = 40;
  const CX = 60;
  const CY = 60;
  const circumference = Math.PI * R;
  const dashOffset = circumference * (1 - score);

  const strokeClass =
    label === "reject"
      ? "stroke-red-600"
      : label === "renegotiate"
        ? "stroke-orange-500"
        : label === "conditionally_accept"
          ? "stroke-yellow-500"
          : "stroke-green-500";

  return (
    <div className="flex flex-col items-center gap-2">
      <div className="relative w-32 h-20">
        <svg viewBox="0 0 120 70" className="w-full h-full" aria-hidden="true">
          <path
            d={`M ${CX - R} ${CY} A ${R} ${R} 0 0 1 ${CX + R} ${CY}`}
            fill="none"
            className="stroke-muted"
            strokeWidth="8"
            strokeLinecap="round"
          />
          <path
            d={`M ${CX - R} ${CY} A ${R} ${R} 0 0 1 ${CX + R} ${CY}`}
            fill="none"
            className={strokeClass}
            strokeWidth="8"
            strokeLinecap="round"
            strokeDasharray={`${circumference} ${circumference}`}
            strokeDashoffset={dashOffset}
            style={{ transition: "stroke-dashoffset 0.8s ease" }}
          />
        </svg>
        <div className="absolute bottom-0 left-0 right-0 flex flex-col items-center">
          <span className={`text-2xl font-bold tabular-nums ${cfg.text}`}>
            {displayScore}
          </span>
          <span className="text-[10px] text-muted-foreground leading-none">
            /100
          </span>
        </div>
      </div>
      <span
        className={`inline-flex items-center rounded-full px-3 py-1 text-xs font-bold tracking-wider ${cfg.bg} ${cfg.text} border ${cfg.border}`}
      >
        {cfg.label}
      </span>
    </div>
  );
}

// ─── MarketPercentileBar ───────────────────────────────────────────────────

function MarketPercentileBar({ percentile }: { percentile: number }) {
  const pct = Math.round(percentile * 100);
  const colorClass =
    percentile < 0.3
      ? "bg-green-500"
      : percentile < 0.6
        ? "bg-yellow-500"
        : "bg-red-500";

  return (
    <div className="flex items-center gap-2">
      <span className="text-[10px] text-muted-foreground whitespace-nowrap w-12">
        Mercado {pct}%
      </span>
      <div className="flex-1 h-1.5 rounded-full bg-muted overflow-hidden">
        <div
          className={`h-full rounded-full ${colorClass}`}
          style={{ width: `${pct}%`, transition: "width 0.5s ease" }}
        />
      </div>
    </div>
  );
}

// ─── NegotiationIssueCard ──────────────────────────────────────────────────

function NegotiationIssueCard({ issue }: { issue: NegotiationIssue }) {
  const [expanded, setExpanded] = useState(false);
  const badge = PLAYBOOK_POSITION_BADGE[issue.playbook_position];

  return (
    <div
      className={`rounded-lg border bg-card p-4 space-y-2 ${
        issue.escalation_required
          ? "border-orange-400 dark:border-orange-600"
          : "border-border"
      }`}
    >
      <div className="flex items-start gap-2 flex-wrap">
        {issue.escalation_required && (
          <span
            className="shrink-0 text-orange-500 dark:text-orange-400"
            title="Escalación requerida"
            aria-label="Escalación requerida"
          >
            ⚠
          </span>
        )}
        <p className="text-sm font-semibold text-foreground flex-1 min-w-0">
          {issue.clause_title}
        </p>
        <span
          className={`inline-flex items-center rounded px-2 py-0.5 text-[10px] font-bold tracking-wider shrink-0 ${badge.bg} ${badge.text}`}
        >
          {badge.label}
        </span>
        <span className="inline-block rounded bg-muted px-1.5 py-0.5 text-[10px] font-mono text-muted-foreground shrink-0">
          {issue.clause_ref}
        </span>
      </div>

      <MarketPercentileBar percentile={issue.market_percentile} />

      <p className="text-xs text-muted-foreground leading-relaxed">
        <span className="font-semibold text-foreground">Posición actual: </span>
        {issue.current_position}
      </p>

      {issue.recommended_action && (
        <p className="text-xs italic text-foreground/80 leading-relaxed">
          {issue.recommended_action}
        </p>
      )}

      {issue.alternative_language && (
        <div className="space-y-1">
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="text-[11px] text-brand-600 dark:text-brand-400 hover:underline"
          >
            {expanded
              ? "▲ Ocultar texto alternativo"
              : "▼ Ver texto alternativo"}
          </button>
          {expanded && (
            <pre className="text-[11px] font-mono bg-muted rounded p-2 whitespace-pre-wrap leading-relaxed text-foreground/80">
              {issue.alternative_language}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}

// ─── ScenarioTab ──────────────────────────────────────────────────────────

function ScenarioContent({
  scenarioKey,
  negotiation,
}: {
  scenarioKey: string;
  negotiation: NegotiationSummary;
}) {
  const scenario = negotiation.scenarios[scenarioKey];
  if (!scenario) {
    return (
      <p className="text-sm text-muted-foreground">Escenario no disponible.</p>
    );
  }

  return (
    <div className="space-y-3">
      <p className="text-sm text-foreground leading-relaxed">
        {scenario.risk_summary}
      </p>

      {scenario.residual_risks.length > 0 && (
        <div className="space-y-1.5">
          <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Riesgos residuales
          </p>
          <ul className="space-y-1">
            {scenario.residual_risks.map((risk, idx) => (
              <li key={idx} className="flex items-start gap-2">
                <span className="mt-0.5 text-yellow-500 shrink-0">•</span>
                <span className="text-xs text-foreground/80">{risk}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {scenario.target_clauses.length > 0 && (
        <div className="space-y-1.5">
          <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Cláusulas objetivo
          </p>
          <div className="flex flex-wrap gap-1.5">
            {scenario.target_clauses.map((ref) => (
              <span
                key={ref}
                className="inline-block rounded bg-muted px-1.5 py-0.5 text-[10px] font-mono text-muted-foreground"
              >
                {ref}
              </span>
            ))}
          </div>
        </div>
      )}

      {scenario.expected_outcome && (
        <div className="space-y-1">
          <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Resultado esperado
          </p>
          <p className="text-xs text-foreground/80">
            {scenario.expected_outcome}
          </p>
        </div>
      )}

      {scenario.walk_away_conditions.length > 0 && (
        <div className="space-y-1.5">
          <p className="text-xs font-semibold uppercase tracking-wider text-red-600 dark:text-red-400">
            Condiciones de ruptura
          </p>
          <ul className="space-y-1">
            {scenario.walk_away_conditions.map((cond, idx) => (
              <li key={idx} className="flex items-start gap-2">
                <span className="mt-0.5 text-red-500 shrink-0">✕</span>
                <span className="text-xs text-foreground/80">{cond}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

// ─── Main component ────────────────────────────────────────────────────────

export function NegotiationPanel({ negotiation }: NegotiationPanelProps) {
  const [activeScenario, setActiveScenario] = useState<string>(
    "renegotiate_priority",
  );

  const escalationCount = negotiation.priority_issues.filter(
    (i) => i.escalation_required,
  ).length;

  const neverAcceptCount = negotiation.priority_issues.filter(
    (i) => i.playbook_position === "never_accept",
  ).length;

  return (
    <div className="space-y-6">
      {/* Header with posture gauge */}
      <div className="rounded-xl border border-border bg-card p-5">
        <div className="flex flex-wrap items-start gap-6">
          <div className="flex flex-col items-center gap-3">
            <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Postura negociadora
            </p>
            <PostureGauge
              score={negotiation.posture_score}
              label={negotiation.posture_label}
            />
          </div>

          <div className="flex-1 min-w-0 space-y-3">
            {/* Quick stats */}
            <div className="flex flex-wrap gap-3">
              <div className="rounded-lg border border-border bg-muted/30 px-3 py-2 text-center">
                <p className="text-lg font-bold text-foreground">
                  {negotiation.priority_issues.length}
                </p>
                <p className="text-[10px] text-muted-foreground">
                  Cláusulas analizadas
                </p>
              </div>
              {neverAcceptCount > 0 && (
                <div className="rounded-lg border border-red-300 dark:border-red-700 bg-red-50 dark:bg-red-900/20 px-3 py-2 text-center">
                  <p className="text-lg font-bold text-red-600 dark:text-red-400">
                    {neverAcceptCount}
                  </p>
                  <p className="text-[10px] text-red-600/80 dark:text-red-400/80">
                    Nunca aceptar
                  </p>
                </div>
              )}
              {escalationCount > 0 && (
                <div className="rounded-lg border border-orange-300 dark:border-orange-700 bg-orange-50 dark:bg-orange-900/20 px-3 py-2 text-center">
                  <p className="text-lg font-bold text-orange-600 dark:text-orange-400">
                    {escalationCount}
                  </p>
                  <p className="text-[10px] text-orange-600/80 dark:text-orange-400/80">
                    Requieren escalada
                  </p>
                </div>
              )}
            </div>

            {/* Benchmark sources */}
            {negotiation.benchmark_sources.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {negotiation.benchmark_sources.map((src) => (
                  <span
                    key={src}
                    className="inline-block rounded bg-muted px-2 py-0.5 text-[10px] text-muted-foreground"
                  >
                    {src}
                  </span>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Priority issues list */}
      {negotiation.priority_issues.length > 0 && (
        <div className="space-y-3">
          <h3 className="text-sm font-semibold text-foreground">
            Cláusulas con posición subóptima
          </h3>
          <div className="space-y-3">
            {negotiation.priority_issues.map((issue, idx) => (
              <NegotiationIssueCard key={idx} issue={issue} />
            ))}
          </div>
        </div>
      )}

      {/* Three-scenario tabs */}
      <div className="space-y-3">
        <h3 className="text-sm font-semibold text-foreground">
          Escenarios de negociación
        </h3>

        {/* Tab buttons */}
        <div className="flex gap-1 rounded-lg border border-border bg-muted/30 p-1">
          {SCENARIO_KEYS.map(({ key, label }) => (
            <button
              key={key}
              type="button"
              onClick={() => setActiveScenario(key)}
              className={`flex-1 rounded-md px-2 py-1.5 text-xs font-medium transition-colors ${
                activeScenario === key
                  ? "bg-card text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        {/* Tab content */}
        <div className="rounded-xl border border-border bg-card p-4">
          <ScenarioContent
            scenarioKey={activeScenario}
            negotiation={negotiation}
          />
        </div>
      </div>
    </div>
  );
}
