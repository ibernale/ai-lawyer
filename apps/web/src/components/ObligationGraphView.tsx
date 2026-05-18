"use client";

import { useState } from "react";
import type { Obligation, ObligationEdge } from "@/lib/api";

// ─── Types ────────────────────────────────────────────────────────────────

type ObligationGraph = {
  nodes: Obligation[];
  edges: ObligationEdge[];
};

type DeonticFilter = "all" | Obligation["deontic_type"];

// ─── Config ───────────────────────────────────────────────────────────────

const DEONTIC_CONFIG: Record<
  Obligation["deontic_type"],
  { label: string; icon: string; bg: string; text: string; border: string }
> = {
  obligation: {
    label: "DEBE",
    icon: "⚠",
    bg: "bg-red-100 dark:bg-red-900/30",
    text: "text-red-700 dark:text-red-400",
    border: "border-red-200 dark:border-red-800",
  },
  permission: {
    label: "PUEDE",
    icon: "✓",
    bg: "bg-blue-100 dark:bg-blue-900/30",
    text: "text-blue-600 dark:text-blue-400",
    border: "border-blue-200 dark:border-blue-800",
  },
  prohibition: {
    label: "PROHIBIDO",
    icon: "✗",
    bg: "bg-orange-100 dark:bg-orange-900/30",
    text: "text-orange-700 dark:text-orange-400",
    border: "border-orange-200 dark:border-orange-800",
  },
  right: {
    label: "DERECHO",
    icon: "→",
    bg: "bg-green-100 dark:bg-green-900/30",
    text: "text-green-600 dark:text-green-500",
    border: "border-green-200 dark:border-green-800",
  },
};

const RELATIONSHIP_LABEL: Record<ObligationEdge["relationship"], string> = {
  depends_on: "depende de",
  conflicts_with: "conflicta con",
  reinforces: "refuerza",
};

const FILTER_TABS: { value: DeonticFilter; label: string }[] = [
  { value: "all", label: "Todas" },
  { value: "obligation", label: "Obligaciones" },
  { value: "permission", label: "Permisos" },
  { value: "prohibition", label: "Prohibiciones" },
  { value: "right", label: "Derechos" },
];

// ─── Obligation card ──────────────────────────────────────────────────────

function ObligationCard({ node }: { node: Obligation }) {
  const cfg = DEONTIC_CONFIG[node.deontic_type];

  return (
    <div className={`rounded-lg border p-3 space-y-2 ${cfg.border} bg-card`}>
      {/* Header row */}
      <div className="flex flex-wrap items-center gap-2">
        <span
          className={`inline-flex items-center gap-1 rounded px-2 py-0.5 text-[10px] font-bold tracking-wider shrink-0 ${cfg.bg} ${cfg.text}`}
        >
          <span aria-hidden="true">{cfg.icon}</span>
          {cfg.label}
        </span>
        <span className="text-sm font-semibold text-foreground">
          {node.party}
        </span>
        <span className="ml-auto inline-block rounded bg-muted px-1.5 py-0.5 text-[10px] font-mono text-muted-foreground shrink-0">
          [{node.clause_ref}]
        </span>
      </div>

      {/* Description */}
      <p className="text-sm text-foreground leading-relaxed">
        {node.description}
      </p>

      {/* Conditions */}
      {node.conditions && (
        <p className="text-xs italic text-muted-foreground">
          Condición: {node.conditions}
        </p>
      )}

      {/* Deadline */}
      {node.deadline && (
        <span className="inline-block rounded-full bg-amber-100 dark:bg-amber-900/30 px-2 py-0.5 text-[11px] font-medium text-amber-700 dark:text-amber-400 border border-amber-200 dark:border-amber-800">
          Plazo: {node.deadline}
        </span>
      )}

      {/* Exceptions */}
      {node.exceptions.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {node.exceptions.map((exc, idx) => (
            <span
              key={idx}
              className="inline-block rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground"
            >
              {exc}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────

export function ObligationGraphView({
  obligations,
}: {
  obligations: ObligationGraph;
}) {
  const { nodes, edges } = obligations;
  const [activeFilter, setActiveFilter] = useState<DeonticFilter>("all");

  const filteredNodes =
    activeFilter === "all"
      ? nodes
      : nodes.filter((n) => n.deontic_type === activeFilter);

  // Group by party
  const byParty = filteredNodes.reduce<Record<string, Obligation[]>>(
    (acc, node) => {
      const party = node.party || "Sin parte";
      if (!acc[party]) acc[party] = [];
      acc[party]!.push(node);
      return acc;
    },
    {},
  );

  if (nodes.length === 0) {
    return (
      <div className="rounded-xl border border-border bg-card p-6 text-center">
        <p className="text-sm text-muted-foreground">
          No se identificaron obligaciones en este contrato
        </p>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-border bg-card p-5 space-y-4">
      {/* Header */}
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-base font-semibold text-foreground">
          Obligaciones y derechos
        </h2>
        <span className="inline-flex items-center rounded-full bg-muted px-2.5 py-0.5 text-xs font-medium text-muted-foreground">
          {nodes.length}
        </span>
      </div>

      {/* Filter tabs */}
      <div className="flex flex-wrap gap-1.5 border-b border-border pb-3">
        {FILTER_TABS.map((tab) => (
          <button
            key={tab.value}
            type="button"
            onClick={() => setActiveFilter(tab.value)}
            className={[
              "px-3 py-1 text-xs font-medium rounded-md border transition-colors",
              activeFilter === tab.value
                ? "bg-primary text-primary-foreground border-primary"
                : "bg-background text-muted-foreground border-input hover:bg-accent hover:text-accent-foreground",
            ].join(" ")}
          >
            {tab.label}
            {tab.value !== "all" && (
              <span className="ml-1 text-[10px] opacity-70">
                ({nodes.filter((n) => n.deontic_type === tab.value).length})
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Nodes grouped by party */}
      {filteredNodes.length === 0 ? (
        <p className="text-sm text-muted-foreground py-2">
          No hay elementos en esta categoría
        </p>
      ) : (
        <div className="space-y-5">
          {Object.entries(byParty).map(([party, partyNodes]) => (
            <div key={party} className="space-y-2">
              <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                {party}
              </p>
              <div className="space-y-2 pl-1">
                {partyNodes.map((node) => (
                  <ObligationCard key={node.id} node={node} />
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Edge relations table */}
      {edges.length > 0 && (
        <div className="space-y-2 border-t border-border pt-4">
          <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Relaciones ({edges.length})
          </p>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-border">
                  <th className="text-left py-1.5 pr-3 font-medium text-muted-foreground">
                    Origen
                  </th>
                  <th className="text-left py-1.5 pr-3 font-medium text-muted-foreground">
                    Relación
                  </th>
                  <th className="text-left py-1.5 font-medium text-muted-foreground">
                    Destino
                  </th>
                </tr>
              </thead>
              <tbody>
                {edges.map((edge, idx) => (
                  <tr
                    key={idx}
                    className="border-b border-border/50 last:border-0"
                  >
                    <td className="py-1.5 pr-3 font-mono text-muted-foreground">
                      {edge.from_id}
                    </td>
                    <td className="py-1.5 pr-3 text-foreground">
                      {RELATIONSHIP_LABEL[edge.relationship]}
                    </td>
                    <td className="py-1.5 font-mono text-muted-foreground">
                      {edge.to_id}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
