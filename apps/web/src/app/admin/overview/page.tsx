"use client";

import { useEffect, useState } from "react";
import {
  getSystemState,
  listSources,
  type KillSwitchRow,
  type SourceStatus,
} from "@/lib/api";

interface OverviewCard {
  label: string;
  value: string | number;
  sub?: string;
  color?: string;
}

export default function OverviewPage() {
  const [cards, setCards] = useState<OverviewCard[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([getSystemState(), listSources()])
      .then(([state, sources]) => {
        const globalKill = state.kill_switches.find(
          (k: KillSwitchRow) => k.target === "global",
        );
        const activeAgents = state.kill_switches.filter(
          (k: KillSwitchRow) => k.target !== "global" && !k.engaged,
        ).length;
        const activeSources = (sources as SourceStatus[]).filter(
          (s) => s.status === "active",
        ).length;

        setCards([
          {
            label: "Estado del sistema",
            value: globalKill?.engaged ? "KILL ACTIVO" : "Operativo",
            sub: globalKill?.engaged
              ? `Activado por ${globalKill.engaged_by}`
              : "Todos los agentes respondiendo",
            color: globalKill?.engaged ? "text-red-600" : "text-green-600",
          },
          {
            label: "Agentes activos",
            value: activeAgents,
            sub: "Sin kill switch",
            color: "text-gray-900",
          },
          {
            label: "Fuentes activas",
            value: activeSources,
            sub: `de ${(sources as SourceStatus[]).length} totales`,
            color: "text-gray-900",
          },
          {
            label: "Feature flags",
            value: state.flags?.length ?? 0,
            sub: "Flags configurados",
            color: "text-gray-900",
          },
        ]);
      })
      .catch(() => setError("No se pudo cargar el estado del sistema."));
  }, []);

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-xl font-semibold text-gray-900">Overview</h1>
        <p className="text-sm text-gray-500 mt-1">
          Estado operativo de la plataforma en tiempo real.
        </p>
      </div>

      {error && <p className="text-sm text-red-600 mb-4">{error}</p>}

      {cards.length === 0 && !error && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {[1, 2, 3, 4].map((i) => (
            <div
              key={i}
              className="bg-white border border-gray-200 rounded-lg p-4 animate-pulse"
            >
              <div className="h-3 bg-gray-200 rounded w-2/3 mb-3" />
              <div className="h-6 bg-gray-200 rounded w-1/2 mb-2" />
              <div className="h-3 bg-gray-200 rounded w-3/4" />
            </div>
          ))}
        </div>
      )}

      {cards.length > 0 && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {cards.map(({ label, value, sub, color }) => (
            <div
              key={label}
              className="bg-white border border-gray-200 rounded-lg p-4"
            >
              <p className="text-xs text-gray-500 font-medium">{label}</p>
              <p
                className={`text-2xl font-bold mt-1 ${color ?? "text-gray-900"}`}
              >
                {value}
              </p>
              {sub && <p className="text-xs text-gray-400 mt-1">{sub}</p>}
            </div>
          ))}
        </div>
      )}

      <div className="mt-8 text-sm text-gray-500 border-t border-gray-100 pt-4">
        Navega a <strong>Ops Center</strong> para controlar agentes y fuentes, o
        a <strong>Observabilidad</strong> para métricas detalladas.
      </div>
    </div>
  );
}
