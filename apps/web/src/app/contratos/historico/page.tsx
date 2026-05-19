"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  FileText,
  AlertTriangle,
  CheckCircle,
  Clock,
  XCircle,
} from "lucide-react";
import { listContracts } from "@/lib/api";
import type { ContractAnalysis } from "@/lib/api";

interface ContractRow {
  contract_id: string;
  trace_id: string;
  status: string;
  analysis: ContractAnalysis | null;
}

const RISK_CONFIG: Record<
  string,
  { label: string; className: string; icon: React.ReactNode }
> = {
  green: {
    label: "Verde",
    className: "bg-green-100 text-green-800",
    icon: <CheckCircle className="w-3.5 h-3.5" />,
  },
  yellow: {
    label: "Amarillo",
    className: "bg-yellow-100 text-yellow-800",
    icon: <Clock className="w-3.5 h-3.5" />,
  },
  red: {
    label: "Rojo",
    className: "bg-red-100 text-red-800",
    icon: <AlertTriangle className="w-3.5 h-3.5" />,
  },
  critical: {
    label: "Crítico",
    className: "bg-red-200 text-red-900 font-semibold",
    icon: <XCircle className="w-3.5 h-3.5" />,
  },
};

function RiskBadge({ rating }: { rating: string }) {
  const cfg = RISK_CONFIG[rating] ?? {
    label: rating,
    className: "bg-gray-100 text-gray-700",
    icon: null,
  };
  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs ${cfg.className}`}
    >
      {cfg.icon}
      {cfg.label}
    </span>
  );
}

function SkeletonRow() {
  return (
    <tr className="animate-pulse">
      {[1, 2, 3, 4, 5].map((i) => (
        <td key={i} className="px-4 py-3">
          <div className="h-4 bg-gray-200 rounded w-3/4" />
        </td>
      ))}
    </tr>
  );
}

export default function ContractosHistoricoPage() {
  const [rows, setRows] = useState<ContractRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [compareToast, setCompareToast] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await listContracts(50);
      setRows(data);
    } catch (e) {
      setError(`Error al cargar contratos: ${e}`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  function toggleSelect(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function handleCompare() {
    setCompareToast(true);
    setTimeout(() => setCompareToast(false), 3000);
  }

  return (
    <div className="p-6 max-w-6xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">
            Historial de contratos
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            Contratos analizados por tu organización
          </p>
        </div>
        <div className="flex items-center gap-3">
          <Link
            href="/contratos"
            className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg text-sm hover:bg-blue-700 transition-colors"
          >
            <FileText className="w-4 h-4" />
            Nuevo análisis
          </Link>
          <button
            disabled={selected.size < 2}
            onClick={handleCompare}
            className="inline-flex items-center gap-2 px-4 py-2 border border-gray-300 rounded-lg text-sm text-gray-700 hover:bg-gray-50 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          >
            Comparar seleccionados ({selected.size})
          </button>
        </div>
      </div>

      {/* Compare toast */}
      {compareToast && (
        <div className="mb-4 p-3 bg-blue-50 border border-blue-200 rounded-lg text-sm text-blue-800">
          Comparación de contratos próximamente — el endpoint ya está disponible
          en{" "}
          <code className="font-mono text-xs">
            GET /api/v1/contracts/compare
          </code>
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
          {error}
        </div>
      )}

      {/* Table */}
      <div className="bg-white border border-gray-200 rounded-xl overflow-hidden shadow-sm">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-200">
            <tr>
              <th className="w-8 px-4 py-3" />
              <th className="px-4 py-3 text-left font-medium text-gray-600">
                Archivo
              </th>
              <th className="px-4 py-3 text-left font-medium text-gray-600">
                Tipo
              </th>
              <th className="px-4 py-3 text-left font-medium text-gray-600">
                Riesgo
              </th>
              <th className="px-4 py-3 text-left font-medium text-gray-600">
                Partes
              </th>
              <th className="px-4 py-3 text-left font-medium text-gray-600">
                Acciones
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {loading &&
              Array.from({ length: 5 }).map((_, i) => <SkeletonRow key={i} />)}

            {!loading && rows.length === 0 && (
              <tr>
                <td
                  colSpan={6}
                  className="px-4 py-12 text-center text-gray-400"
                >
                  <FileText className="w-8 h-8 mx-auto mb-2 opacity-40" />
                  <p>No hay contratos analizados todavía</p>
                  <Link
                    href="/contratos"
                    className="text-blue-600 hover:underline text-sm mt-1 inline-block"
                  >
                    Analiza tu primer contrato
                  </Link>
                </td>
              </tr>
            )}

            {!loading &&
              rows.map((row) => {
                const a = row.analysis;
                if (!a) return null;
                const parties =
                  a.metadata?.parties
                    ?.slice(0, 2)
                    .map((p) => p.name)
                    .join(" · ") ?? "—";
                const rating = a.risk_assessment?.overall_rating ?? "yellow";
                const docType = a.metadata?.document_type ?? "—";

                return (
                  <tr
                    key={row.contract_id}
                    className={`hover:bg-gray-50 transition-colors ${selected.has(row.contract_id) ? "bg-blue-50" : ""}`}
                  >
                    <td className="px-4 py-3">
                      <input
                        type="checkbox"
                        checked={selected.has(row.contract_id)}
                        onChange={() => toggleSelect(row.contract_id)}
                        className="rounded border-gray-300 text-blue-600"
                        aria-label={`Seleccionar ${a.filename}`}
                      />
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <FileText className="w-4 h-4 text-gray-400 shrink-0" />
                        <span className="font-medium text-gray-900 truncate max-w-[200px]">
                          {a.filename}
                        </span>
                      </div>
                    </td>
                    <td className="px-4 py-3 text-gray-600">{docType}</td>
                    <td className="px-4 py-3">
                      <RiskBadge rating={rating} />
                    </td>
                    <td className="px-4 py-3 text-gray-500 truncate max-w-[220px]">
                      {parties}
                    </td>
                    <td className="px-4 py-3">
                      <Link
                        href={`/contratos?id=${row.contract_id}`}
                        className="text-blue-600 hover:underline text-xs"
                      >
                        Ver análisis
                      </Link>
                    </td>
                  </tr>
                );
              })}
          </tbody>
        </table>
      </div>

      <p className="text-xs text-gray-400 mt-3">
        Mostrando hasta 50 contratos más recientes
      </p>
    </div>
  );
}
