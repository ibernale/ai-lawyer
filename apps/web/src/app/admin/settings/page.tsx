"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  getSystemState,
  getVersion,
  type KillSwitchRow,
  type VersionResponse,
} from "@/lib/api";

function InfoRow({
  label,
  value,
  mono,
}: {
  label: string;
  value: React.ReactNode;
  mono?: boolean;
}) {
  return (
    <div className="flex items-center justify-between py-2 border-b border-gray-100 last:border-0">
      <span className="text-sm text-gray-500">{label}</span>
      <span
        className={`text-sm text-gray-900 ${mono ? "font-mono text-xs" : "font-medium"}`}
      >
        {value}
      </span>
    </div>
  );
}

function KillSwitchBadge({ engaged }: { engaged: boolean }) {
  return (
    <span
      className={`inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full ${
        engaged ? "bg-red-100 text-red-700" : "bg-green-100 text-green-700"
      }`}
    >
      <span
        className={`w-1.5 h-1.5 rounded-full ${engaged ? "bg-red-500" : "bg-green-500"}`}
      />
      {engaged ? "Activo" : "Liberado"}
    </span>
  );
}

export default function SettingsPage() {
  const [version, setVersion] = useState<VersionResponse | null>(null);
  const [killSwitches, setKillSwitches] = useState<KillSwitchRow[] | null>(
    null,
  );
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([getVersion(), getSystemState()])
      .then(([v, state]) => {
        setVersion(v);
        setKillSwitches(state.kill_switches);
      })
      .catch(() => setError("No se pudo cargar la configuración."));
  }, []);

  const globalKill = killSwitches?.find((k) => k.target === "global");
  const agentKills = killSwitches?.filter((k) => k.target !== "global") ?? [];
  const engagedAgentKills = agentKills.filter((k) => k.engaged);

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-xl font-semibold text-gray-900">
          Platform Settings
        </h1>
        <p className="text-sm text-gray-500 mt-1">
          Estado y configuración de la plataforma. La edición de flags se
          gestiona en{" "}
          <Link href="/admin/flags" className="text-blue-600 hover:underline">
            Feature Flags
          </Link>
          .
        </p>
      </div>

      {error && (
        <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2 mb-4">
          {error}
        </p>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Build info */}
        <div className="bg-white border border-gray-200 rounded-lg p-5">
          <h2 className="text-sm font-semibold text-gray-900 mb-3">
            Información del build
          </h2>
          {!version ? (
            <div className="space-y-2">
              {[1, 2, 3, 4].map((i) => (
                <div
                  key={i}
                  className="h-8 bg-gray-100 rounded animate-pulse"
                />
              ))}
            </div>
          ) : (
            <div>
              <InfoRow label="Versión" value={version.version} mono />
              <InfoRow
                label="Commit SHA"
                value={version.commit_sha?.slice(0, 12) ?? "—"}
                mono
              />
              <InfoRow
                label="Build time"
                value={
                  version.build_time
                    ? new Date(version.build_time).toLocaleString()
                    : "—"
                }
              />
              <InfoRow
                label="Python"
                value={version.python_version.split(" ")[0] ?? "—"}
                mono
              />
            </div>
          )}
        </div>

        {/* Auth config */}
        <div className="bg-white border border-gray-200 rounded-lg p-5">
          <h2 className="text-sm font-semibold text-gray-900 mb-3">
            Autenticación
          </h2>
          <div>
            <InfoRow label="Mecanismo" value="JWT HS256" />
            <InfoRow label="Almacenamiento" value="sessionStorage" />
            <InfoRow
              label="Gestión de usuarios"
              value={
                <span className="text-xs text-gray-500">
                  AWS Secrets Manager{" "}
                  <code className="bg-gray-100 px-1 rounded">
                    AUTH_USERS_JSON
                  </code>
                </span>
              }
            />
            <InfoRow
              label="Roles disponibles"
              value={
                <span className="flex gap-1 flex-wrap justify-end">
                  {["admin", "operator", "auditor", "analyst"].map((r) => (
                    <span
                      key={r}
                      className="text-[10px] bg-gray-100 text-gray-600 px-1.5 py-0.5 rounded"
                    >
                      {r}
                    </span>
                  ))}
                </span>
              }
            />
          </div>
        </div>

        {/* Kill switches */}
        <div className="bg-white border border-gray-200 rounded-lg p-5 lg:col-span-2">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-gray-900">
              Kill Switches
            </h2>
            <Link
              href="/admin/ops"
              className="text-xs text-blue-600 hover:underline"
            >
              Gestionar en Ops Center →
            </Link>
          </div>

          {!killSwitches ? (
            <div className="space-y-2">
              {[1, 2].map((i) => (
                <div
                  key={i}
                  className="h-10 bg-gray-100 rounded animate-pulse"
                />
              ))}
            </div>
          ) : (
            <>
              <div className="mb-4 p-3 bg-gray-50 rounded-lg flex items-center justify-between">
                <div>
                  <span className="text-sm font-medium text-gray-900">
                    Kill Switch Global
                  </span>
                  {globalKill?.engaged && (
                    <p className="text-xs text-red-600 mt-0.5">
                      Activado por {globalKill.engaged_by} ·{" "}
                      {globalKill.engaged_at
                        ? new Date(globalKill.engaged_at).toLocaleString()
                        : ""}
                      {globalKill.reason ? ` — ${globalKill.reason}` : ""}
                    </p>
                  )}
                </div>
                <KillSwitchBadge engaged={globalKill?.engaged ?? false} />
              </div>

              {agentKills.length > 0 && (
                <div>
                  <p className="text-xs text-gray-500 mb-2">
                    Kill switches por agente ({engagedAgentKills.length} activos
                    de {agentKills.length})
                  </p>
                  <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-2">
                    {agentKills.map((k) => (
                      <div
                        key={k.target}
                        className="flex items-center justify-between bg-gray-50 rounded px-3 py-2"
                      >
                        <span className="text-xs font-mono text-gray-700 truncate mr-2">
                          {k.target.replace("agent:", "")}
                        </span>
                        <KillSwitchBadge engaged={k.engaged} />
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {agentKills.length === 0 && (
                <p className="text-xs text-gray-400 italic">
                  No hay kill switches por agente configurados.
                </p>
              )}
            </>
          )}
        </div>

        {/* Feature flags summary */}
        <div className="bg-white border border-gray-200 rounded-lg p-5 lg:col-span-2">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-gray-900">
              Feature Flags
            </h2>
            <Link
              href="/admin/flags"
              className="text-xs text-blue-600 hover:underline"
            >
              Ver y editar todos los flags →
            </Link>
          </div>
          <p className="text-sm text-gray-500">
            Los feature flags controlan el comportamiento de la plataforma en
            tiempo real sin necesidad de redespliegue. Se auditan
            automáticamente en el audit trail.
          </p>
        </div>
      </div>
    </div>
  );
}
