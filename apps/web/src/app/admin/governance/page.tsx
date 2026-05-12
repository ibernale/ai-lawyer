"use client";

import { useEffect, useState } from "react";
import {
  listProposals,
  approveProposal,
  rejectProposal,
  requestChangesProposal,
  listSources,
  pauseSource,
  resumeSource,
  listRecentDecisions,
  listAuditSamples,
  type PromptEvolutionProposal,
  type SourceStatus,
  type RecentDecision,
  type AuditSample,
} from "@/lib/api";

// ─── Shared UI ────────────────────────────────────────────────────────────────

function Badge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    pending: "bg-yellow-100 text-yellow-800",
    approved: "bg-green-100 text-green-800",
    rejected: "bg-red-100 text-red-800",
    changes_requested: "bg-orange-100 text-orange-800",
    active: "bg-green-100 text-green-800",
    paused: "bg-gray-200 text-gray-700",
    reviewing: "bg-blue-100 text-blue-800",
    reviewed: "bg-green-100 text-green-800",
    correcto: "bg-green-100 text-green-800",
    dudoso: "bg-yellow-100 text-yellow-800",
    incorrecto: "bg-red-100 text-red-800",
  };
  return (
    <span className={`text-xs font-medium px-2 py-0.5 rounded ${colors[status] ?? "bg-gray-100 text-gray-600"}`}>
      {status}
    </span>
  );
}

function ReasonDialog({
  title,
  placeholder,
  onConfirm,
  onCancel,
}: {
  title: string;
  placeholder: string;
  onConfirm: (reason: string) => void;
  onCancel: () => void;
}) {
  const [value, setValue] = useState("");
  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg shadow-xl p-6 w-full max-w-md">
        <h3 className="font-semibold text-gray-800 mb-3">{title}</h3>
        <textarea
          className="w-full border rounded p-2 text-sm h-24 resize-none focus:outline-blue-400"
          placeholder={placeholder}
          value={value}
          onChange={(e) => setValue(e.target.value)}
        />
        <div className="flex justify-end gap-2 mt-4">
          <button onClick={onCancel} className="px-3 py-1.5 text-sm border rounded hover:bg-gray-50">
            Cancelar
          </button>
          <button
            disabled={!value.trim()}
            onClick={() => onConfirm(value.trim())}
            className="px-3 py-1.5 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
          >
            Confirmar
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Tab 1: Prompt Evolution PRs ─────────────────────────────────────────────

function PromptEvolutionTab() {
  const [proposals, setProposals] = useState<PromptEvolutionProposal[]>([]);
  const [filter, setFilter] = useState<string>("pending");
  const [selected, setSelected] = useState<PromptEvolutionProposal | null>(null);
  const [dialog, setDialog] = useState<{ action: string; pr: number } | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setLoading(true);
    listProposals(filter || undefined)
      .then(setProposals)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [filter]);

  async function handleAction(prNumber: number, action: string, reason: string) {
    try {
      if (action === "approve") await approveProposal(prNumber, reason);
      else if (action === "reject") await rejectProposal(prNumber, reason);
      else await requestChangesProposal(prNumber, reason);
      setDialog(null);
      setSelected(null);
      listProposals(filter || undefined).then(setProposals);
    } catch (e) {
      alert(`Error: ${e}`);
    }
  }

  return (
    <div>
      <div className="flex gap-2 mb-4 flex-wrap">
        {["pending", "approved", "rejected", "changes_requested", ""].map((s) => (
          <button
            key={s}
            onClick={() => setFilter(s)}
            className={`px-3 py-1 text-sm rounded border ${filter === s ? "bg-blue-600 text-white border-blue-600" : "border-gray-300 hover:bg-gray-50"}`}
          >
            {s || "Todos"}
          </button>
        ))}
      </div>

      {loading ? (
        <p className="text-sm text-gray-500">Cargando…</p>
      ) : proposals.length === 0 ? (
        <p className="text-sm text-gray-400 italic">No hay propuestas.</p>
      ) : (
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="border-b text-left text-gray-500">
              <th className="py-2 pr-4">PR</th>
              <th className="py-2 pr-4">Especialista</th>
              <th className="py-2 pr-4">Estado</th>
              <th className="py-2 pr-4">Creado</th>
              <th className="py-2">Acciones</th>
            </tr>
          </thead>
          <tbody>
            {proposals.map((p) => (
              <tr key={p.id} className="border-b hover:bg-gray-50">
                <td className="py-2 pr-4">
                  {p.pr_number ? (
                    <a href={p.pr_url} target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline">
                      #{p.pr_number}
                    </a>
                  ) : (
                    <span className="text-gray-400">—</span>
                  )}
                </td>
                <td className="py-2 pr-4 font-mono text-xs">{p.specialist}</td>
                <td className="py-2 pr-4"><Badge status={p.status} /></td>
                <td className="py-2 pr-4 text-gray-400 text-xs">{p.created_at?.slice(0, 16)}</td>
                <td className="py-2 flex gap-1 flex-wrap">
                  <button onClick={() => setSelected(p)} className="px-2 py-0.5 text-xs border rounded hover:bg-gray-50">Ver diff</button>
                  {p.status === "pending" && (
                    <>
                      <button onClick={() => setDialog({ action: "approve", pr: p.pr_number ?? 0 })} className="px-2 py-0.5 text-xs bg-green-100 text-green-700 border border-green-300 rounded hover:bg-green-200">Aprobar</button>
                      <button onClick={() => setDialog({ action: "request_changes", pr: p.pr_number ?? 0 })} className="px-2 py-0.5 text-xs bg-yellow-100 text-yellow-700 border border-yellow-300 rounded hover:bg-yellow-200">Cambios</button>
                      <button onClick={() => setDialog({ action: "reject", pr: p.pr_number ?? 0 })} className="px-2 py-0.5 text-xs bg-red-100 text-red-700 border border-red-300 rounded hover:bg-red-200">Rechazar</button>
                    </>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {selected && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-lg shadow-xl p-6 w-full max-w-3xl max-h-[80vh] overflow-auto">
            <div className="flex justify-between items-start mb-4">
              <h3 className="font-semibold text-gray-800">Diff — {selected.specialist} #{selected.pr_number}</h3>
              <button onClick={() => setSelected(null)} className="text-gray-400 hover:text-gray-600 text-lg">✕</button>
            </div>
            {selected.motivating_cases && (
              <div className="mb-3 text-sm text-gray-600 bg-gray-50 rounded p-3">
                <strong>Motivación:</strong> {selected.motivating_cases}
              </div>
            )}
            <pre className="text-xs bg-gray-900 text-green-300 rounded p-4 overflow-auto whitespace-pre-wrap">
              {selected.diff}
            </pre>
          </div>
        </div>
      )}

      {dialog && (
        <ReasonDialog
          title={dialog.action === "approve" ? "Razón para aprobar" : dialog.action === "reject" ? "Razón para rechazar" : "Cambios solicitados"}
          placeholder="Explica la decisión…"
          onConfirm={(r) => handleAction(dialog.pr, dialog.action, r)}
          onCancel={() => setDialog(null)}
        />
      )}
    </div>
  );
}

// ─── Tab 2: Audit Samples ─────────────────────────────────────────────────────

function AuditSamplesTab() {
  const [samples, setSamples] = useState<AuditSample[]>([]);
  const [statusFilter, setStatusFilter] = useState<string>("pending");
  const [loading, setLoading] = useState(false);

  const isUrgent = (s: AuditSample) => {
    if (s.status === "reviewed") return false;
    const days = (Date.now() - new Date(s.sampled_at).getTime()) / 86400000;
    return days > 7;
  };

  useEffect(() => {
    setLoading(true);
    listAuditSamples(statusFilter as "pending" | "reviewing" | "reviewed" | undefined)
      .then(setSamples)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [statusFilter]);

  return (
    <div>
      <div className="flex gap-2 mb-4">
        {["pending", "reviewing", "reviewed"].map((s) => (
          <button key={s} onClick={() => setStatusFilter(s)} className={`px-3 py-1 text-sm rounded border ${statusFilter === s ? "bg-blue-600 text-white border-blue-600" : "border-gray-300 hover:bg-gray-50"}`}>
            {s}
          </button>
        ))}
      </div>
      {loading ? (
        <p className="text-sm text-gray-500">Cargando…</p>
      ) : (
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="border-b text-left text-gray-500">
              <th className="py-2 pr-4">ID</th>
              <th className="py-2 pr-4">Consulta</th>
              <th className="py-2 pr-4">Rama</th>
              <th className="py-2 pr-4">Estado</th>
              <th className="py-2 pr-4">Veredicto</th>
              <th className="py-2">Muestreado</th>
            </tr>
          </thead>
          <tbody>
            {samples.map((s) => (
              <tr key={s.id} className="border-b hover:bg-gray-50">
                <td className="py-2 pr-4 text-gray-500">{s.id}</td>
                <td className="py-2 pr-4 max-w-xs truncate">{s.query}</td>
                <td className="py-2 pr-4 text-xs font-mono">{s.branch}</td>
                <td className="py-2 pr-4">
                  <Badge status={s.status} />
                  {isUrgent(s) && <span className="ml-1 text-xs text-red-600 font-bold">⚠ Urgente</span>}
                </td>
                <td className="py-2 pr-4">{s.review_verdict ? <Badge status={s.review_verdict} /> : "—"}</td>
                <td className="py-2 text-xs text-gray-400">{s.sampled_at?.slice(0, 16)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

// ─── Tab 3: Memory Edits (placeholder) ───────────────────────────────────────

function MemoryEditsTab() {
  return (
    <div className="text-sm text-gray-500 italic">
      Las ediciones de memoria se gestionan vía PR con label <code>memory-edit</code>.
      La revisión de PRs de memoria seguirá el mismo flujo que Prompt Evolution.
      <br /><br />
      Próximamente: lista de PRs pendientes con label memory-edit.
    </div>
  );
}

// ─── Tab 4: Source Status ─────────────────────────────────────────────────────

function SourceStatusTab() {
  const [sources, setSources] = useState<SourceStatus[]>([]);
  const [dialog, setDialog] = useState<{ action: "pause" | "resume"; id: string } | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setLoading(true);
    listSources().then(setSources).catch(console.error).finally(() => setLoading(false));
  }, []);

  async function handleSourceAction(sourceId: string, action: "pause" | "resume", reason: string) {
    try {
      if (action === "pause") await pauseSource(sourceId, reason);
      else await resumeSource(sourceId, reason);
      setDialog(null);
      listSources().then(setSources);
    } catch (e) {
      alert(`Error: ${e}`);
    }
  }

  return (
    <div>
      {loading ? (
        <p className="text-sm text-gray-500">Cargando…</p>
      ) : (
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="border-b text-left text-gray-500">
              <th className="py-2 pr-4">Fuente</th>
              <th className="py-2 pr-4">Estado</th>
              <th className="py-2 pr-4">Pausado por</th>
              <th className="py-2 pr-4">Razón</th>
              <th className="py-2">Acciones</th>
            </tr>
          </thead>
          <tbody>
            {sources.map((s) => (
              <tr key={s.source_id} className="border-b hover:bg-gray-50">
                <td className="py-2 pr-4 font-medium">{s.display_name ?? s.source_id}</td>
                <td className="py-2 pr-4"><Badge status={s.status} /></td>
                <td className="py-2 pr-4 text-gray-400 text-xs">{s.paused_by ?? "—"}</td>
                <td className="py-2 pr-4 text-gray-500 text-xs max-w-xs truncate">{s.paused_reason ?? "—"}</td>
                <td className="py-2">
                  {s.status === "active" ? (
                    <button onClick={() => setDialog({ action: "pause", id: s.source_id })} className="px-2 py-0.5 text-xs bg-gray-100 text-gray-700 border rounded hover:bg-gray-200">Pausar</button>
                  ) : (
                    <button onClick={() => setDialog({ action: "resume", id: s.source_id })} className="px-2 py-0.5 text-xs bg-green-100 text-green-700 border border-green-300 rounded hover:bg-green-200">Reanudar</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {dialog && (
        <ReasonDialog
          title={dialog.action === "pause" ? `Pausar ${dialog.id}` : `Reanudar ${dialog.id}`}
          placeholder="Razón de la acción…"
          onConfirm={(r) => handleSourceAction(dialog.id, dialog.action, r)}
          onCancel={() => setDialog(null)}
        />
      )}
    </div>
  );
}

// ─── Tab 5: Recent Decisions ──────────────────────────────────────────────────

function RecentDecisionsTab() {
  const [decisions, setDecisions] = useState<RecentDecision[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setLoading(true);
    listRecentDecisions(50).then(setDecisions).catch(console.error).finally(() => setLoading(false));
  }, []);

  return (
    <div>
      {loading ? (
        <p className="text-sm text-gray-500">Cargando…</p>
      ) : decisions.length === 0 ? (
        <p className="text-sm text-gray-400 italic">Sin decisiones registradas.</p>
      ) : (
        <ol className="space-y-2">
          {decisions.map((d) => (
            <li key={d.id} className="flex gap-3 items-start text-sm border-b pb-2">
              <span className="text-gray-300 text-xs mt-0.5 w-16 shrink-0">{d.timestamp?.slice(0, 16)}</span>
              <div>
                <span className="font-mono text-xs bg-gray-100 rounded px-1">{d.action_type}</span>
                {" "}
                <span className="text-gray-700">{d.target_type}{d.target_id ? ` #${d.target_id}` : ""}</span>
                {" — "}
                <span className="text-gray-500 italic">{d.reason}</span>
                <span className="ml-2 text-gray-400 text-xs">por {d.actor}</span>
              </div>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────

const TABS = [
  { id: "proposals", label: "Prompt Evolution PRs", Component: PromptEvolutionTab },
  { id: "samples", label: "Audit Samples", Component: AuditSamplesTab },
  { id: "memory", label: "Memory Edits", Component: MemoryEditsTab },
  { id: "sources", label: "Source Status", Component: SourceStatusTab },
  { id: "decisions", label: "Recent Decisions", Component: RecentDecisionsTab },
];

export default function GovernancePage() {
  const [activeTab, setActiveTab] = useState("proposals");
  const active = TABS.find((t) => t.id === activeTab)!;

  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-800 mb-6">Governance</h1>

      <div className="flex border-b mb-6 gap-0">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setActiveTab(t.id)}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              activeTab === t.id
                ? "border-blue-600 text-blue-600"
                : "border-transparent text-gray-500 hover:text-gray-700"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      <active.Component />
    </div>
  );
}
