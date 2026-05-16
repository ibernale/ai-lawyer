"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  getSessions,
  revokeSession,
  revokeAllSessions,
  type SessionRow,
} from "@/lib/api";
import { PageLayout } from "@/components/admin/PageLayout";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Alert } from "@/components/ui/alert";

function formatDate(iso: string): string {
  if (!iso) return "—";
  try {
    return new Date(iso + "Z").toLocaleString("es-ES", {
      dateStyle: "short",
      timeStyle: "short",
    });
  } catch {
    return iso;
  }
}

function parseDevice(ua: string): string {
  if (!ua) return "Dispositivo desconocido";
  if (/mobile/i.test(ua)) return "Mobile";
  if (/tablet/i.test(ua)) return "Tablet";
  return "Desktop";
}

function parseBrowser(ua: string): string {
  if (!ua) return "—";
  if (/edg/i.test(ua)) return "Edge";
  if (/chrome/i.test(ua)) return "Chrome";
  if (/firefox/i.test(ua)) return "Firefox";
  if (/safari/i.test(ua)) return "Safari";
  return "Otro";
}

export default function UserSessionsPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const username = params.id;

  const [sessions, setSessions] = useState<SessionRow[] | null>(null);
  const [error, setError] = useState("");
  const [revoking, setRevoking] = useState<string | null>(null);
  const [revokingAll, setRevokingAll] = useState(false);

  const load = useCallback(async () => {
    try {
      const data = await getSessions(username);
      setSessions(data);
      setError("");
    } catch {
      setError("No se pudieron cargar las sesiones.");
    }
  }, [username]);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleRevoke(sessionId: string) {
    setRevoking(sessionId);
    try {
      await revokeSession(sessionId);
      await load();
    } catch {
      setError("No se pudo terminar la sesión.");
    } finally {
      setRevoking(null);
    }
  }

  async function handleRevokeAll() {
    setRevokingAll(true);
    try {
      await revokeAllSessions(username);
      await load();
    } catch {
      setError("No se pudieron terminar todas las sesiones.");
    } finally {
      setRevokingAll(false);
    }
  }

  const activeSessions = sessions ?? [];

  return (
    <PageLayout
      title={`Sesiones activas — ${username}`}
      description="Sesiones abiertas para este usuario. Terminar una sesión invalida el JWT inmediatamente."
      actions={
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => router.back()}>
            Volver
          </Button>
          {activeSessions.length > 0 && (
            <Button
              variant="destructive"
              size="sm"
              loading={revokingAll}
              onClick={handleRevokeAll}
            >
              Terminar todas
            </Button>
          )}
        </div>
      }
    >
      {error && (
        <Alert variant="error" className="mb-4">
          {error}
        </Alert>
      )}

      {sessions === null && !error && (
        <p className="text-sm text-gray-500">Cargando sesiones…</p>
      )}

      {sessions !== null && activeSessions.length === 0 && (
        <p className="text-sm text-gray-500">
          No hay sesiones activas para este usuario.
        </p>
      )}

      {activeSessions.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-gray-200">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                <th className="px-4 py-3 text-left font-semibold text-gray-700">
                  Dispositivo
                </th>
                <th className="px-4 py-3 text-left font-semibold text-gray-700">
                  IP
                </th>
                <th className="px-4 py-3 text-left font-semibold text-gray-700">
                  Último uso
                </th>
                <th className="px-4 py-3 text-left font-semibold text-gray-700">
                  Creada
                </th>
                <th className="px-4 py-3 text-left font-semibold text-gray-700">
                  Expira
                </th>
                <th className="px-4 py-3 text-left font-semibold text-gray-700">
                  Estado
                </th>
                <th className="px-4 py-3 text-right font-semibold text-gray-700">
                  Acción
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {activeSessions.map((s) => (
                <tr key={s.id} className="hover:bg-gray-50 transition-colors">
                  <td className="px-4 py-3">
                    <div className="font-medium text-gray-900">
                      {parseDevice(s.user_agent)}
                    </div>
                    <div className="text-xs text-gray-500 font-mono">
                      {parseBrowser(s.user_agent)}
                    </div>
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-gray-700">
                    {s.ip_address || "—"}
                  </td>
                  <td className="px-4 py-3 text-gray-700">
                    {formatDate(s.last_used_at)}
                  </td>
                  <td className="px-4 py-3 text-gray-500">
                    {formatDate(s.created_at)}
                  </td>
                  <td className="px-4 py-3 text-gray-500">
                    {formatDate(s.expires_at)}
                  </td>
                  <td className="px-4 py-3">
                    {s.suspicious ? (
                      <Badge variant="warning">Sospechosa</Badge>
                    ) : (
                      <Badge variant="success">OK</Badge>
                    )}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <Button
                      variant="outline"
                      size="sm"
                      loading={revoking === s.id}
                      onClick={() => handleRevoke(s.id)}
                    >
                      Terminar
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </PageLayout>
  );
}
