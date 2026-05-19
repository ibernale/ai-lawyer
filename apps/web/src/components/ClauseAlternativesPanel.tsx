"use client";

import { useState } from "react";
import type { ClauseAlternatives, ClauseAlternative } from "@/lib/api";

// ─── Types ─────────────────────────────────────────────────────────────────

interface ClauseAlternativesPanelProps {
  alternatives: ClauseAlternatives[];
}

// ─── Constants ─────────────────────────────────────────────────────────────

const ALTERNATIVE_LABEL_CONFIG: Record<
  ClauseAlternative["label"],
  { bg: string; text: string; border: string; humanLabel: string }
> = {
  favourable_to_us: {
    bg: "bg-green-50 dark:bg-green-900/20",
    text: "text-green-700 dark:text-green-400",
    border: "border-green-300 dark:border-green-700",
    humanLabel: "Favorable para nosotros",
  },
  balanced: {
    bg: "bg-blue-50 dark:bg-blue-900/20",
    text: "text-blue-700 dark:text-blue-400",
    border: "border-blue-300 dark:border-blue-700",
    humanLabel: "Equilibrada",
  },
  compromise: {
    bg: "bg-gray-50 dark:bg-gray-800/40",
    text: "text-gray-600 dark:text-gray-400",
    border: "border-gray-300 dark:border-gray-600",
    humanLabel: "Compromiso",
  },
};

// ─── CopyButton ────────────────────────────────────────────────────────────

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard API not available
    }
  };

  return (
    <button
      type="button"
      onClick={handleCopy}
      className="shrink-0 rounded border border-border bg-background px-2 py-1 text-[10px] text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
      title="Copiar al portapapeles"
      aria-label={copied ? "Copiado" : "Copiar texto"}
    >
      {copied ? "✓ Copiado" : "Copiar"}
    </button>
  );
}

// ─── AlternativeCard ───────────────────────────────────────────────────────

function AlternativeCard({ alternative }: { alternative: ClauseAlternative }) {
  const [showRationale, setShowRationale] = useState(false);
  const cfg = ALTERNATIVE_LABEL_CONFIG[alternative.label];

  return (
    <div className={`rounded-lg border ${cfg.border} ${cfg.bg} p-3 space-y-2`}>
      {/* Header */}
      <div className="flex items-center gap-2 flex-wrap">
        <span
          className={`inline-flex items-center rounded px-2 py-0.5 text-[10px] font-bold tracking-wider ${cfg.text} border ${cfg.border}`}
        >
          {cfg.humanLabel}
        </span>
        {alternative.market_prevalence != null && (
          <span className="text-[10px] text-muted-foreground">
            Mercado: {Math.round(alternative.market_prevalence * 100)}%
          </span>
        )}
        <div className="ml-auto">
          <CopyButton text={alternative.text} />
        </div>
      </div>

      {/* Clause text */}
      <pre className="text-[11px] font-mono bg-background/60 rounded p-2 whitespace-pre-wrap leading-relaxed text-foreground/90 border border-border/50">
        {alternative.text}
      </pre>

      {/* Rationale (expandable) */}
      {alternative.rationale && (
        <div>
          <button
            type="button"
            onClick={() => setShowRationale((v) => !v)}
            className="text-[11px] text-muted-foreground hover:text-foreground transition-colors"
          >
            {showRationale ? "▲ Ocultar justificación" : "▼ Justificación"}
          </button>
          {showRationale && (
            <p className="mt-1 text-xs text-muted-foreground leading-relaxed">
              {alternative.rationale}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

// ─── ClauseAlternativeSection ──────────────────────────────────────────────

function ClauseAlternativeSection({ item }: { item: ClauseAlternatives }) {
  const [showOriginal, setShowOriginal] = useState(false);

  return (
    <div className="rounded-xl border border-border bg-card p-4 space-y-4">
      {/* Clause header */}
      <div className="flex items-start gap-2 flex-wrap">
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold text-foreground">
            {item.clause_title}
          </p>
          <span className="inline-block rounded bg-muted px-1.5 py-0.5 text-[10px] font-mono text-muted-foreground mt-0.5">
            {item.clause_ref}
          </span>
        </div>
      </div>

      {/* Mandatory law issues — red warning banner */}
      {item.mandatory_law_issues.length > 0 && (
        <div className="rounded-lg border border-red-300 dark:border-red-700 bg-red-50 dark:bg-red-900/20 p-3 space-y-2">
          <p className="text-xs font-bold text-red-700 dark:text-red-400 uppercase tracking-wider">
            Problemas de cumplimiento normativo obligatorio
          </p>
          {item.mandatory_law_issues.map((issue, idx) => (
            <div key={idx} className="space-y-1">
              <p className="text-xs font-semibold text-red-700 dark:text-red-400">
                {issue.provision}
              </p>
              <p className="text-xs text-red-600 dark:text-red-300">
                {issue.issue}
              </p>
              {issue.compliant_formulation && (
                <p className="text-xs text-foreground/80 italic">
                  Formulación conforme: {issue.compliant_formulation}
                </p>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Original text (collapsible) */}
      {item.original_text && (
        <div>
          <button
            type="button"
            onClick={() => setShowOriginal((v) => !v)}
            className="text-[11px] text-muted-foreground hover:text-foreground transition-colors"
          >
            {showOriginal ? "▲ Ocultar texto original" : "▼ Texto original"}
          </button>
          {showOriginal && (
            <pre className="mt-2 text-[11px] font-mono bg-muted rounded p-2 whitespace-pre-wrap leading-relaxed text-foreground/70 border border-border">
              {item.original_text}
            </pre>
          )}
        </div>
      )}

      {/* Alternatives */}
      {item.alternatives.length > 0 && (
        <div className="space-y-3">
          <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Alternativas ({item.alternatives.length})
          </p>
          <div className="space-y-3">
            {item.alternatives.map((alt, idx) => (
              <AlternativeCard key={idx} alternative={alt} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Main component ────────────────────────────────────────────────────────

export function ClauseAlternativesPanel({
  alternatives,
}: ClauseAlternativesPanelProps) {
  if (alternatives.length === 0) return null;

  const lawIssueCount = alternatives.reduce(
    (acc, item) => acc + item.mandatory_law_issues.length,
    0,
  );

  return (
    <div className="space-y-4">
      {/* Section header */}
      <div className="flex items-center gap-3 flex-wrap">
        <h3 className="text-sm font-semibold text-foreground">
          Alternativas de cláusulas ({alternatives.length})
        </h3>
        {lawIssueCount > 0 && (
          <span className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-bold bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400 border border-red-300 dark:border-red-700">
            ⚠ {lawIssueCount} problema{lawIssueCount !== 1 ? "s" : ""}{" "}
            normativos
          </span>
        )}
      </div>

      {/* Clause sections */}
      <div className="space-y-4">
        {alternatives.map((item, idx) => (
          <ClauseAlternativeSection key={idx} item={item} />
        ))}
      </div>
    </div>
  );
}
