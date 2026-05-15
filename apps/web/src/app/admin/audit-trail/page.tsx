"use client";

import { useEffect, useState } from "react";
import {
  listAuditTrail,
  verifyAuditChain,
  exportAuditTrail,
  type AuditEntry,
  type AuditFilter,
  type ChainVerification,
} from "@/lib/api";

function prettyJson(raw: string | null): string {
  if (!raw) return "—";
  try {
    return JSON.stringify(JSON.parse(raw), null, 2);
  } catch {
    return raw;
  }
}

export default function AuditTrailPage() {
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [actionError, setActionError] = useState("");
  const [verification, setVerification] = useState<ChainVerification | null>(
    null,
  );
  const [verifying, setVerifying] = useState(false);
  const [selected, setSelected] = useState<AuditEntry | null>(null);
  const [filters, setFilters] = useState<AuditFilter>({ limit: 100 });

  function load() {
    setLoading(true);
    listAuditTrail(filters)
      .then(setEntries)
      .catch(console.error)
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    load();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function handleVerify() {
    setVerifying(true);
    setActionError("");
    try {
      const result = await verifyAuditChain();
      setVerification(result);
    } catch (e) {
      setActionError(`Error al verificar la cadena: ${e}`);
    } finally {
      setVerifying(false);
    }
  }

  async function handleExport(format: "csv" | "json") {
    setActionError("");
    try {
      const blob = await exportAuditTrail(format);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `audit_trail.${format}`;
      a.click();
      URL.revokeObjectURL(url);
      // Reload to show the meta-audit entry
      setTimeout(load, 500);
    } catch (e) {
      setActionError(`Error al exportar: ${e}`);
    }
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-800">Audit Trail</h1>
        <div className="flex gap-2">
          <button
            onClick={handleVerify}
            disabled={verifying}
            className="px-3 py-1.5 text-sm border rounded hover:bg-gray-50 disabled:opacity-50"
          >
            {verifying ? "Verificando…" : "Verify chain"}
          </button>
          {verification && (
            <span
              className={`px-3 py-1.5 text-sm font-medium rounded ${verification.valid ? "bg-green-100 text-green-700" : "bg-red-100 text-red-700"}`}
            >
              {verification.valid
                ? `✓ ${verification.total} entradas íntegras`
                : `✗ Chain rota en id=${verification.broken_at}`}
            </span>
          )}
          <button
            onClick={() => handleExport("csv")}
            className="px-3 py-1.5 text-sm bg-gray-100 border rounded hover:bg-gray-200"
          >
            CSV
          </button>
          <button
            onClick={() => handleExport("json")}
            className="px-3 py-1.5 text-sm bg-gray-100 border rounded hover:bg-gray-200"
          >
            JSON
          </button>
        </div>
      </div>

      {actionError && (
        <p className="mb-4 text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
          {actionError}
        </p>
      )}

      {/* Filters */}
      <div className="flex gap-3 mb-4 flex-wrap">
        <input
          className="border rounded px-2 py-1 text-sm w-36"
          placeholder="Actor"
          value={filters.actor ?? ""}
          onChange={(e) =>
            setFilters((f) => ({ ...f, actor: e.target.value || undefined }))
          }
        />
        <input
          className="border rounded px-2 py-1 text-sm w-48"
          placeholder="action_type"
          value={filters.action_type ?? ""}
          onChange={(e) =>
            setFilters((f) => ({
              ...f,
              action_type: e.target.value || undefined,
            }))
          }
        />
        <input
          className="border rounded px-2 py-1 text-sm w-40"
          placeholder="Desde (YYYY-MM-DD)"
          value={filters.since ?? ""}
          onChange={(e) =>
            setFilters((f) => ({ ...f, since: e.target.value || undefined }))
          }
        />
        <input
          className="border rounded px-2 py-1 text-sm w-40"
          placeholder="Hasta (YYYY-MM-DD)"
          value={filters.until ?? ""}
          onChange={(e) =>
            setFilters((f) => ({ ...f, until: e.target.value || undefined }))
          }
        />
        <button
          onClick={load}
          className="px-3 py-1 text-sm bg-blue-600 text-white rounded hover:bg-blue-700"
        >
          Filtrar
        </button>
      </div>

      {loading ? (
        <p className="text-sm text-gray-500">Cargando…</p>
      ) : entries.length === 0 ? (
        <p className="text-sm text-gray-400 italic">Sin entradas.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm border-collapse">
            <thead>
              <tr className="border-b text-left text-gray-500">
                <th className="py-2 pr-3">ID</th>
                <th className="py-2 pr-3">Timestamp</th>
                <th className="py-2 pr-3">Actor</th>
                <th className="py-2 pr-3">Rol</th>
                <th className="py-2 pr-3">Acción</th>
                <th className="py-2 pr-3">Objetivo</th>
                <th className="py-2">Razón</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((e) => (
                <tr
                  key={e.id}
                  className="border-b hover:bg-gray-50 cursor-pointer"
                  onClick={() => setSelected(e)}
                >
                  <td className="py-1.5 pr-3 text-gray-400">{e.id}</td>
                  <td className="py-1.5 pr-3 text-xs text-gray-500">
                    {e.timestamp?.slice(0, 16)}
                  </td>
                  <td className="py-1.5 pr-3 font-medium">{e.actor_user_id}</td>
                  <td className="py-1.5 pr-3 text-xs">{e.actor_role}</td>
                  <td className="py-1.5 pr-3">
                    <span className="font-mono text-xs bg-gray-100 rounded px-1">
                      {e.action_type}
                    </span>
                  </td>
                  <td className="py-1.5 pr-3 text-xs">
                    {e.target_type}
                    {e.target_id ? ` #${e.target_id}` : ""}
                  </td>
                  <td className="py-1.5 text-gray-600 max-w-xs truncate text-xs">
                    {e.reason}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Detail modal */}
      {selected && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-lg shadow-xl p-6 w-full max-w-2xl max-h-[80vh] overflow-auto">
            <div className="flex justify-between items-start mb-4">
              <h3 className="font-semibold text-gray-800">
                Entrada #{selected.id}
              </h3>
              <button
                onClick={() => setSelected(null)}
                className="text-gray-400 hover:text-gray-600"
              >
                ✕
              </button>
            </div>
            <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
              <dt className="text-gray-500">Timestamp</dt>
              <dd>{selected.timestamp}</dd>
              <dt className="text-gray-500">Actor</dt>
              <dd>
                {selected.actor_user_id} ({selected.actor_role})
              </dd>
              <dt className="text-gray-500">Acción</dt>
              <dd className="font-mono text-xs">{selected.action_type}</dd>
              <dt className="text-gray-500">Objetivo</dt>
              <dd>
                {selected.target_type}{" "}
                {selected.target_id && `#${selected.target_id}`}
              </dd>
              <dt className="text-gray-500">Razón</dt>
              <dd className="col-span-1">{selected.reason}</dd>
              <dt className="text-gray-500">Checksum</dt>
              <dd className="font-mono text-xs break-all col-span-1">
                {selected.checksum_self ?? "—"}
              </dd>
            </dl>
            {(selected.before_state || selected.after_state) && (
              <div className="mt-4 grid grid-cols-2 gap-4">
                <div>
                  <p className="text-xs text-gray-500 font-medium mb-1">
                    Before
                  </p>
                  <pre className="text-xs bg-red-50 rounded p-2 overflow-auto max-h-48">
                    {prettyJson(selected.before_state)}
                  </pre>
                </div>
                <div>
                  <p className="text-xs text-gray-500 font-medium mb-1">
                    After
                  </p>
                  <pre className="text-xs bg-green-50 rounded p-2 overflow-auto max-h-48">
                    {prettyJson(selected.after_state)}
                  </pre>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
