"use client";

import { useEffect, useState } from "react";
import {
  listAgents,
  getRagStatus,
  getMemoryStatus,
  listProceduralPatterns,
  listSources,
  pauseSource,
  resumeSource,
  forceResync,
  setKillSwitch,
  type AgentStatus,
  type RagStatus,
  type MemoryStatus,
  type ProceduralPatternRow,
  type SourceStatus,
} from "@/lib/api";

const GRAFANA_URL = process.env.NEXT_PUBLIC_GRAFANA_URL ?? "";
const DAGSTER_URL = process.env.NEXT_PUBLIC_DAGSTER_URL ?? "";

// ---------------------------------------------------------------------------
// Shared
// ---------------------------------------------------------------------------

function Badge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    active: "bg-green-100 text-green-800",
    killed: "bg-red-100 text-red-800",
    degraded: "bg-amber-100 text-amber-800",
    paused: "bg-yellow-100 text-yellow-800",
    healthy: "bg-green-100 text-green-800",
    unavailable: "bg-red-100 text-red-800",
  };
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${colors[status] ?? "bg-gray-100 text-gray-700"}`}
    >
      {status}
    </span>
  );
}

function ReasonDialog({
  title,
  onConfirm,
  onCancel,
}: {
  title: string;
  onConfirm: (reason: string) => void;
  onCancel: () => void;
}) {
  const [reason, setReason] = useState("");
  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg shadow-xl p-6 w-full max-w-md">
        <h2 className="text-lg font-semibold mb-4">{title}</h2>
        <textarea
          className="w-full border border-gray-300 rounded p-2 text-sm resize-none h-24 focus:outline-none focus:ring-2 focus:ring-blue-500"
          placeholder="Motivo obligatorio..."
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          autoFocus
        />
        <div className="flex gap-3 justify-end mt-4">
          <button
            onClick={onCancel}
            className="px-4 py-2 text-sm border border-gray-300 rounded text-gray-600 hover:text-gray-900"
          >
            Cancelar
          </button>
          <button
            onClick={() => onConfirm(reason)}
            disabled={!reason.trim()}
            className="px-4 py-2 text-sm font-medium bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            Confirmar
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tab: Agents
// ---------------------------------------------------------------------------

function AgentsTab() {
  const [agents, setAgents] = useState<AgentStatus[] | null>(null);
  const [error, setError] = useState("");
  const [dialog, setDialog] = useState<{
    agent: AgentStatus;
    action: "kill" | "release";
  } | null>(null);

  useEffect(() => {
    listAgents()
      .then(setAgents)
      .catch(() => setError("Error loading agents"));
  }, []);

  async function handleKillToggle(agent: AgentStatus, reason: string) {
    setDialog(null);
    try {
      await setKillSwitch(
        `agent:${agent.name}`,
        !agent.kill_switch_engaged,
        reason,
      );
      setAgents((prev) =>
        prev
          ? prev.map((a) =>
              a.name === agent.name
                ? {
                    ...a,
                    kill_switch_engaged: !a.kill_switch_engaged,
                    status: !a.kill_switch_engaged ? "killed" : "active",
                  }
                : a,
            )
          : prev,
      );
    } catch {
      setError("Error toggling kill switch");
    }
  }

  if (error) return <p className="text-red-600 text-sm">{error}</p>;
  if (!agents) return <p className="text-gray-500 text-sm">Cargando...</p>;

  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-sm">
        <thead className="bg-gray-50 text-gray-600 uppercase text-xs">
          <tr>
            <th className="px-4 py-3 text-left">Agente</th>
            <th className="px-4 py-3 text-left">Estado</th>
            <th className="px-4 py-3 text-left">Modelo</th>
            <th className="px-4 py-3 text-left">Prompt</th>
            <th className="px-4 py-3 text-left">Invocaciones 24h</th>
            <th className="px-4 py-3 text-left">Kill switch</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-200 bg-white">
          {agents.map((agent) => (
            <tr key={agent.name} className="hover:bg-gray-50">
              <td className="px-4 py-3 font-mono font-medium">{agent.name}</td>
              <td className="px-4 py-3">
                <Badge status={agent.status} />
              </td>
              <td className="px-4 py-3 text-gray-600 font-mono text-xs">
                {agent.model}
              </td>
              <td className="px-4 py-3 text-gray-600 text-xs">
                {agent.current_prompt_version ?? "—"}
              </td>
              <td className="px-4 py-3 text-gray-600">
                {agent.invocations_last_24h}
              </td>
              <td className="px-4 py-3">
                <button
                  onClick={() =>
                    setDialog({
                      agent,
                      action: agent.kill_switch_engaged ? "release" : "kill",
                    })
                  }
                  className={`px-3 py-1 text-xs font-medium rounded transition-colors ${
                    agent.kill_switch_engaged
                      ? "bg-green-100 text-green-800 hover:bg-green-200"
                      : "bg-red-100 text-red-800 hover:bg-red-200"
                  }`}
                >
                  {agent.kill_switch_engaged ? "Reanudar" : "Pausar"}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {dialog && (
        <ReasonDialog
          title={`${dialog.action === "kill" ? "Pausar" : "Reanudar"} agente ${dialog.agent.name}`}
          onConfirm={(reason) => handleKillToggle(dialog.agent, reason)}
          onCancel={() => setDialog(null)}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tab: Sources & Pipelines
// ---------------------------------------------------------------------------

function SourcesTab() {
  const [sources, setSources] = useState<SourceStatus[] | null>(null);
  const [error, setError] = useState("");
  const [dialog, setDialog] = useState<{
    source: SourceStatus;
    action: "pause" | "resume" | "resync";
  } | null>(null);

  useEffect(() => {
    listSources()
      .then(setSources)
      .catch(() => setError("Error loading sources"));
  }, []);

  async function handleAction(reason: string) {
    if (!dialog) return;
    setDialog(null);
    try {
      if (dialog.action === "pause") {
        await pauseSource(dialog.source.source_id, reason);
        setSources((prev) =>
          prev
            ? prev.map((s) =>
                s.source_id === dialog.source.source_id
                  ? { ...s, status: "paused" as const }
                  : s,
              )
            : prev,
        );
      } else if (dialog.action === "resume") {
        await resumeSource(dialog.source.source_id, reason);
        setSources((prev) =>
          prev
            ? prev.map((s) =>
                s.source_id === dialog.source.source_id
                  ? { ...s, status: "active" as const }
                  : s,
              )
            : prev,
        );
      } else {
        await forceResync(dialog.source.source_id, reason);
      }
    } catch {
      setError("Error performing action");
    }
  }

  if (error) return <p className="text-red-600 text-sm">{error}</p>;
  if (!sources) return <p className="text-gray-500 text-sm">Cargando...</p>;

  return (
    <div>
      <table className="min-w-full text-sm">
        <thead className="bg-gray-50 text-gray-600 uppercase text-xs">
          <tr>
            <th className="px-4 py-3 text-left">Fuente</th>
            <th className="px-4 py-3 text-left">Estado</th>
            <th className="px-4 py-3 text-left">Último sync</th>
            <th className="px-4 py-3 text-left">Acciones</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-200 bg-white">
          {sources.map((s) => (
            <tr key={s.source_id} className="hover:bg-gray-50">
              <td className="px-4 py-3 font-medium">
                {s.display_name ?? s.source_id}
              </td>
              <td className="px-4 py-3">
                <Badge status={s.status} />
              </td>
              <td className="px-4 py-3 text-gray-500 text-xs">
                {s.last_synced_at
                  ? new Date(s.last_synced_at).toLocaleString()
                  : "—"}
              </td>
              <td className="px-4 py-3 flex gap-2">
                {s.status === "active" ? (
                  <button
                    onClick={() => setDialog({ source: s, action: "pause" })}
                    className="px-2 py-1 text-xs bg-yellow-100 text-yellow-800 rounded hover:bg-yellow-200"
                  >
                    Pausar
                  </button>
                ) : (
                  <button
                    onClick={() => setDialog({ source: s, action: "resume" })}
                    className="px-2 py-1 text-xs bg-green-100 text-green-800 rounded hover:bg-green-200"
                  >
                    Reanudar
                  </button>
                )}
                <button
                  onClick={() => setDialog({ source: s, action: "resync" })}
                  className="px-2 py-1 text-xs bg-blue-100 text-blue-800 rounded hover:bg-blue-200"
                >
                  Force Resync
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {DAGSTER_URL && (
        <div className="mt-8 border rounded overflow-hidden">
          <div className="bg-gray-100 px-4 py-2 text-sm font-medium text-gray-700 flex items-center justify-between">
            <span>Dagster UI</span>
            <a
              href={DAGSTER_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs text-blue-600 hover:underline"
            >
              Abrir en nueva pestaña
            </a>
          </div>
          <iframe
            src={DAGSTER_URL}
            className="w-full h-96 border-0"
            title="Dagster UI"
            sandbox="allow-scripts allow-same-origin allow-forms"
          />
        </div>
      )}

      {dialog && (
        <ReasonDialog
          title={`${dialog.action === "pause" ? "Pausar" : dialog.action === "resume" ? "Reanudar" : "Force Resync"}: ${dialog.source.display_name ?? dialog.source.source_id}`}
          onConfirm={handleAction}
          onCancel={() => setDialog(null)}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tab: RAG & Memory
// ---------------------------------------------------------------------------

function RagMemoryTab() {
  const [rag, setRag] = useState<RagStatus | null>(null);
  const [memory, setMemory] = useState<MemoryStatus | null>(null);
  const [patterns, setPatterns] = useState<ProceduralPatternRow[] | null>(null);
  const [expandedPattern, setExpandedPattern] = useState<string | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    getRagStatus()
      .then(setRag)
      .catch(() => setError("Error loading RAG status"));
    getMemoryStatus()
      .then(setMemory)
      .catch(() => {});
    listProceduralPatterns()
      .then(setPatterns)
      .catch(() => {});
  }, []);

  if (error) return <p className="text-red-600 text-sm">{error}</p>;

  return (
    <div className="space-y-8">
      {/* RAG */}
      <section>
        <h3 className="text-base font-semibold mb-3">Colecciones Qdrant</h3>
        {!rag ? (
          <p className="text-gray-500 text-sm">Cargando...</p>
        ) : (
          <>
            <p className="text-sm text-gray-600 mb-3">
              Total vectores:{" "}
              <span className="font-semibold">
                {rag.total_vectors.toLocaleString()}
              </span>
            </p>
            <table className="min-w-full text-sm">
              <thead className="bg-gray-50 text-gray-600 uppercase text-xs">
                <tr>
                  <th className="px-4 py-3 text-left">Colección</th>
                  <th className="px-4 py-3 text-left">Vectores</th>
                  <th className="px-4 py-3 text-left">Schema keys</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 bg-white">
                {rag.collections.map((col) => (
                  <tr key={col.name}>
                    <td className="px-4 py-3 font-mono font-medium">
                      {col.name}
                    </td>
                    <td className="px-4 py-3">
                      {col.vectors_count.toLocaleString()}
                    </td>
                    <td className="px-4 py-3 text-gray-500 text-xs">
                      {col.payload_schema_keys.join(", ") || "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </section>

      {/* Memory */}
      <section>
        <h3 className="text-base font-semibold mb-3">Memoria</h3>
        {memory && (
          <div className="flex gap-4 mb-4">
            <div className="bg-white border rounded p-3 text-center min-w-[120px]">
              <div className="text-2xl font-bold text-gray-800">
                {memory.procedural_patterns_count}
              </div>
              <div className="text-xs text-gray-500 mt-1">
                Patrones procedurales
              </div>
            </div>
            <div className="bg-white border rounded p-3 text-center min-w-[120px]">
              <div className="text-2xl font-bold text-gray-800">
                {memory.semantic_files_count}
              </div>
              <div className="text-xs text-gray-500 mt-1">
                Ficheros semánticos
              </div>
            </div>
          </div>
        )}

        {patterns && patterns.length > 0 && (
          <div className="border rounded overflow-hidden">
            <div className="bg-gray-50 px-4 py-2 text-xs font-semibold text-gray-600 uppercase">
              Patrones procedurales
            </div>
            {patterns.map((p) => (
              <div key={p.filename} className="border-t">
                <button
                  className="w-full text-left px-4 py-2 text-sm font-medium hover:bg-gray-50 flex items-center justify-between"
                  onClick={() =>
                    setExpandedPattern(
                      expandedPattern === p.filename ? null : p.filename,
                    )
                  }
                >
                  <span className="font-mono">{p.filename}</span>
                  <span className="text-gray-400 text-xs">
                    {expandedPattern === p.filename ? "▲" : "▼"}
                  </span>
                </button>
                {expandedPattern === p.filename && (
                  <pre className="px-4 py-3 bg-gray-900 text-gray-100 text-xs overflow-x-auto whitespace-pre-wrap">
                    {p.content}
                  </pre>
                )}
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tab: Health & Performance
// ---------------------------------------------------------------------------

type ServiceState = "healthy" | "degraded" | "unavailable" | "checking";

function HealthTab() {
  const [apiStatus, setApiStatus] = useState<ServiceState>("checking");
  const [qdrantStatus, setQdrantStatus] = useState<ServiceState>("checking");

  useEffect(() => {
    fetch("/health")
      .then((r) => r.json())
      .then((data: { status: string; deps_status: { qdrant: string } }) => {
        setApiStatus(
          data.status === "healthy"
            ? "healthy"
            : data.status === "degraded"
              ? "degraded"
              : "unavailable",
        );
        setQdrantStatus(
          data.deps_status?.qdrant === "healthy" ? "healthy" : "unavailable",
        );
      })
      .catch(() => {
        setApiStatus("unavailable");
        setQdrantStatus("unavailable");
      });
  }, []);

  const services: { name: string; status: ServiceState; url?: string }[] = [
    { name: "API", status: apiStatus },
    { name: "Qdrant", status: qdrantStatus },
    {
      name: "Dagster",
      status: "unavailable",
      url: DAGSTER_URL || undefined,
    },
    {
      name: "Grafana",
      status: "unavailable",
      url: GRAFANA_URL || undefined,
    },
  ];

  return (
    <div className="space-y-8">
      <section>
        <h3 className="text-base font-semibold mb-3">Estado de servicios</h3>
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
          {services.map((svc) => (
            <div
              key={svc.name}
              className="bg-white border rounded-lg p-4 text-center"
            >
              <div className="text-sm font-medium text-gray-700 mb-2">
                {svc.name}
              </div>
              <Badge
                status={svc.status === "checking" ? "degraded" : svc.status}
              />
              {svc.url && (
                <a
                  href={svc.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="block mt-2 text-xs text-blue-500 hover:underline"
                >
                  Abrir
                </a>
              )}
            </div>
          ))}
        </div>
      </section>

      {GRAFANA_URL && (
        <section>
          <h3 className="text-base font-semibold mb-3">Grafana</h3>
          <div className="border rounded overflow-hidden">
            <iframe
              src={GRAFANA_URL}
              className="w-full h-96 border-0"
              title="Grafana"
              sandbox="allow-scripts allow-same-origin allow-forms"
            />
          </div>
        </section>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

const TABS = [
  { id: "agents", label: "Agents" },
  { id: "sources", label: "Sources & Pipelines" },
  { id: "rag", label: "RAG & Memory" },
  { id: "health", label: "Health & Performance" },
] as const;

type TabId = (typeof TABS)[number]["id"];

export default function OpsPage() {
  const [tab, setTab] = useState<TabId>("agents");

  return (
    <div>
      <h1 className="text-xl font-semibold text-gray-900 mb-6">Ops Center</h1>
      <div className="border-b border-gray-200 mb-6">
        <nav className="-mb-px flex gap-6">
          {TABS.map(({ id, label }) => (
            <button
              key={id}
              onClick={() => setTab(id)}
              className={`pb-3 text-sm font-medium border-b-2 transition-colors ${
                tab === id
                  ? "border-blue-600 text-blue-600"
                  : "border-transparent text-gray-500 hover:text-gray-700"
              }`}
            >
              {label}
            </button>
          ))}
        </nav>
      </div>

      {tab === "agents" && <AgentsTab />}
      {tab === "sources" && <SourcesTab />}
      {tab === "rag" && <RagMemoryTab />}
      {tab === "health" && <HealthTab />}
    </div>
  );
}
