"use client";

import { useEffect, useState } from "react";
import { listAgents, type AgentStatus } from "@/lib/api";

function MetricCard({
  label,
  value,
  sub,
  accent,
}: {
  label: string;
  value: string | number;
  sub?: string;
  accent?: string;
}) {
  return (
    <div className="bg-white border border-gray-200 rounded-lg p-4">
      <p className="text-xs text-gray-500 font-medium">{label}</p>
      <p className={`text-2xl font-bold mt-1 ${accent ?? "text-gray-900"}`}>
        {value}
      </p>
      {sub && <p className="text-xs text-gray-400 mt-1">{sub}</p>}
    </div>
  );
}

export default function CostsPage() {
  const [agents, setAgents] = useState<AgentStatus[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    listAgents()
      .then(setAgents)
      .catch(() => setError("No se pudo cargar los datos de agentes."));
  }, []);

  const totalInvocations =
    agents?.reduce((sum, a) => sum + a.invocations_last_24h, 0) ?? 0;
  const totalCost = agents?.reduce((sum, a) => sum + a.cost_usd_last_24h, 0) ?? 0;
  const avgLatency =
    agents && agents.length > 0
      ? agents
          .filter((a) => a.avg_latency_ms_last_24h !== null)
          .reduce((sum, a) => sum + (a.avg_latency_ms_last_24h ?? 0), 0) /
          Math.max(
            1,
            agents.filter((a) => a.avg_latency_ms_last_24h !== null).length,
          )
      : null;

  return (
    <div>
      <div className="mb-4">
        <h1 className="text-xl font-semibold text-gray-900">Costs &amp; FinOps</h1>
        <p className="text-sm text-gray-500 mt-1">
          Métricas de uso e invocaciones de los agentes en las últimas 24 horas.
        </p>
      </div>

      <div className="mb-6 bg-amber-50 border border-amber-200 rounded-lg px-4 py-3 text-xs text-amber-700">
        <strong>Nota:</strong> Los datos de coste en USD reflejan estimaciones
        internas del agente. La integración con AWS Cost Explorer y facturación
        real de Anthropic se activará en la Fase 11.
      </div>

      {error && (
        <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2 mb-4">
          {error}
        </p>
      )}

      {!agents && !error && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
          {[1, 2, 3, 4].map((i) => (
            <div
              key={i}
              className="h-24 bg-gray-100 rounded-lg animate-pulse"
            />
          ))}
        </div>
      )}

      {agents && (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
            <MetricCard
              label="Invocaciones 24h"
              value={totalInvocations.toLocaleString()}
              sub="Suma de todos los agentes"
            />
            <MetricCard
              label="Coste estimado 24h"
              value={`$${totalCost.toFixed(4)}`}
              sub="Estimación interna"
              accent={totalCost > 0 ? "text-gray-900" : "text-gray-400"}
            />
            <MetricCard
              label="Latencia media"
              value={
                avgLatency !== null ? `${avgLatency.toFixed(0)} ms` : "—"
              }
              sub="Media entre agentes activos"
            />
            <MetricCard
              label="Agentes activos"
              value={agents.filter((a) => a.status === "active").length}
              sub={`de ${agents.length} totales`}
            />
          </div>

          <h2 className="text-base font-semibold text-gray-900 mb-3">
            Desglose por agente
          </h2>
          <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
            <table className="min-w-full text-sm">
              <thead className="bg-gray-50 text-gray-600 text-xs uppercase">
                <tr>
                  <th className="px-4 py-3 text-left font-medium">Agente</th>
                  <th className="px-4 py-3 text-left font-medium">Estado</th>
                  <th className="px-4 py-3 text-left font-medium">Modelo</th>
                  <th className="px-4 py-3 text-right font-medium">
                    Invocaciones 24h
                  </th>
                  <th className="px-4 py-3 text-right font-medium">
                    Latencia media
                  </th>
                  <th className="px-4 py-3 text-right font-medium">
                    Coste estimado 24h
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {agents.map((a) => (
                  <tr key={a.name} className="hover:bg-gray-50">
                    <td className="px-4 py-3 font-mono font-medium text-gray-900">
                      {a.name}
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`text-xs font-medium px-2 py-0.5 rounded ${
                          a.status === "active"
                            ? "bg-green-100 text-green-700"
                            : a.status === "killed"
              ? "bg-red-100 text-red-700"
                              : "bg-amber-100 text-amber-700"
                        }`}
                      >
                        {a.status}
                      </span>
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-gray-500">
                      {a.model}
                    </td>
                    <td className="px-4 py-3 text-right text-gray-700">
                      {a.invocations_last_24h.toLocaleString()}
                    </td>
                    <td className="px-4 py-3 text-right text-gray-500 text-xs">
                      {a.avg_latency_ms_last_24h !== null
                        ? `${a.avg_latency_ms_last_24h.toFixed(0)} ms`
                        : "—"}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-xs text-gray-600">
                      ${a.cost_usd_last_24h.toFixed(4)}
                    </td>
                  </tr>
                ))}
              </tbody>
              <tfoot className="bg-gray-50 border-t border-gray-200">
                <tr>
                  <td
                    colSpan={3}
                    className="px-4 py-2 text-xs font-semibold text-gray-600"
                  >
                    Total
                  </td>
                  <td className="px-4 py-2 text-right text-xs font-semibold text-gray-800">
                    {totalInvocations.toLocaleString()}
                  </td>
                  <td className="px-4 py-2" />
                  <td className="px-4 py-2 text-right font-mono text-xs font-semibold text-gray-800">
                    ${totalCost.toFixed(4)}
                  </td>
                </tr>
              </tfoot>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
