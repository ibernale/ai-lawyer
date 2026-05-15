"use client";

import { useEffect, useState } from "react";
import { listPipelines, type PipelineExecution } from "@/lib/api";

const STATUS_STYLES: Record<string, string> = {
  RUNNING: "bg-blue-100 text-blue-700",
  SUCCEEDED: "bg-green-100 text-green-700",
  FAILED: "bg-red-100 text-red-700",
  TIMED_OUT: "bg-orange-100 text-orange-700",
  ABORTED: "bg-gray-100 text-gray-600",
};

function duration(start: string | null, stop: string | null): string {
  if (!start) return "—";
  const s = new Date(start).getTime();
  const e = stop ? new Date(stop).getTime() : Date.now();
  const sec = Math.round((e - s) / 1000);
  if (sec < 60) return `${sec}s`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m ${sec % 60}s`;
  return `${Math.floor(sec / 3600)}h ${Math.floor((sec % 3600) / 60)}m`;
}

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("es-ES", {
    dateStyle: "short",
    timeStyle: "short",
  });
}

export default function PipelinesPage() {
  const [data, setData] = useState<{
    executions: PipelineExecution[];
    status: string;
    message?: string;
  } | null>(null);
  const [loading, setLoading] = useState(true);

  function load() {
    setLoading(true);
    listPipelines()
      .then(setData)
      .catch((e) =>
        setData({
          executions: [],
          status: "unavailable",
          message: e instanceof Error ? e.message : "Error desconocido",
        }),
      )
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    load();
  }, []);

  return (
    <div>
      <div className="mb-6 flex items-start justify-between">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">Pipelines</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            Ejecuciones recientes de AWS Step Functions.
          </p>
        </div>
        <button
          onClick={load}
          disabled={loading}
          className="px-3 py-1.5 text-sm border border-gray-300 rounded hover:bg-gray-50 disabled:opacity-50"
        >
          {loading ? "Cargando..." : "Actualizar"}
        </button>
      </div>

      {data && data.status !== "ok" && (
        <div className="mb-4 bg-amber-50 border border-amber-200 rounded-lg px-4 py-3 text-xs text-amber-800">
          <strong>
            {data.status === "not_configured"
              ? "AWS SDK no configurado"
              : "Servicio no disponible"}
            :
          </strong>{" "}
          {data.status === "not_configured"
            ? "boto3 no está instalado o no hay credenciales AWS configuradas. Las ejecuciones se mostrarán aquí cuando el entorno tenga acceso a AWS."
            : (data.message ?? "No se pudo conectar con Step Functions.")}
        </div>
      )}

      {loading && !data ? (
        <div className="space-y-2">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-12 bg-gray-100 rounded animate-pulse" />
          ))}
        </div>
      ) : data?.executions.length === 0 ? (
        <div className="text-center py-16 text-gray-400">
          <svg
            className="w-10 h-10 mx-auto mb-3 text-gray-300"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={1.5}
              d="M9 17V7m0 10a2 2 0 01-2 2H5a2 2 0 01-2-2V7a2 2 0 012-2h2a2 2 0 012 2m0 10a2 2 0 002 2h2a2 2 0 002-2M9 7a2 2 0 012-2h2a2 2 0 012 2m0 10V7m0 10a2 2 0 002 2h2a2 2 0 002-2V7a2 2 0 00-2-2h-2a2 2 0 00-2 2"
            />
          </svg>
          <p className="text-sm">No hay ejecuciones recientes.</p>
        </div>
      ) : (
        <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
          <table className="min-w-full text-sm">
            <thead className="bg-gray-50 text-gray-600 text-xs uppercase">
              <tr>
                <th className="px-4 py-3 text-left font-medium">Nombre</th>
                <th className="px-4 py-3 text-left font-medium">Estado</th>
                <th className="px-4 py-3 text-left font-medium">Inicio</th>
                <th className="px-4 py-3 text-left font-medium">Duración</th>
                <th className="px-4 py-3 text-left font-medium">ARN</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {data?.executions.map((ex) => (
                <tr key={ex.execution_arn} className="hover:bg-gray-50">
                  <td className="px-4 py-3 font-medium text-gray-900 font-mono text-xs">
                    {ex.name}
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={`inline-block text-xs font-medium px-2 py-0.5 rounded ${STATUS_STYLES[ex.status] ?? "bg-gray-100 text-gray-600"}`}
                    >
                      {ex.status}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-xs text-gray-500">
                    {fmtDate(ex.start_date)}
                  </td>
                  <td className="px-4 py-3 text-xs text-gray-500">
                    {duration(ex.start_date, ex.stop_date)}
                  </td>
                  <td className="px-4 py-3 text-xs text-gray-400 font-mono max-w-xs truncate">
                    {ex.execution_arn.split(":").slice(-1)[0]}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
