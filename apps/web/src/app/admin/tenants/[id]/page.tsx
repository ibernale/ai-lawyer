"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { Users, Mail, Activity, Building2, AlertCircle } from "lucide-react";
import {
  listUsers,
  listInvitations,
  revokeInvitation,
  sendInvitation,
} from "@/lib/api";
import type { UserRow, Invitation } from "@/lib/api";
import InviteUserModal from "@/components/InviteUserModal";

type Tab = "users" | "invitations";

export default function TenantDetailPage() {
  const params = useParams();
  const tenantId = typeof params.id === "string" ? params.id : "";

  const [tab, setTab] = useState<Tab>("users");
  const [users, setUsers] = useState<UserRow[]>([]);
  const [invitations, setInvitations] = useState<Invitation[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [showInvite, setShowInvite] = useState(false);

  const loadUsers = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await listUsers(tenantId);
      setUsers(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error cargando usuarios.");
    } finally {
      setLoading(false);
    }
  }, [tenantId]);

  const loadInvitations = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await listInvitations();
      setInvitations(data.filter((i) => i.tenant_id === tenantId));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error cargando invitaciones.");
    } finally {
      setLoading(false);
    }
  }, [tenantId]);

  useEffect(() => {
    if (tab === "users") void loadUsers();
    else void loadInvitations();
  }, [tab, loadUsers, loadInvitations]);

  async function handleRevoke(invId: string) {
    try {
      await revokeInvitation(invId);
      setInvitations((prev) => prev.filter((i) => i.id !== invId));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al revocar invitación.");
    }
  }

  const TABS: { id: Tab; label: string; icon: React.ReactNode }[] = [
    { id: "users", label: "Usuarios", icon: <Users className="w-4 h-4" /> },
    {
      id: "invitations",
      label: "Invitaciones pendientes",
      icon: <Mail className="w-4 h-4" />,
    },
  ];

  return (
    <div className="p-6 max-w-5xl mx-auto">
      <div className="flex items-center gap-3 mb-6">
        <Building2 className="w-5 h-5 text-gray-400" />
        <h1 className="text-xl font-semibold text-gray-900">
          Tenant: <span className="font-mono text-blue-700">{tenantId}</span>
        </h1>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 mb-6 bg-gray-100 rounded-lg p-1 w-fit">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`flex items-center gap-2 px-4 py-2 rounded-md text-sm font-medium transition-colors ${
              tab === t.id
                ? "bg-white text-gray-900 shadow-sm"
                : "text-gray-600 hover:text-gray-900"
            }`}
          >
            {t.icon}
            {t.label}
          </button>
        ))}
        <button
          onClick={() => setShowInvite(true)}
          className="flex items-center gap-2 px-4 py-2 rounded-md text-sm font-medium bg-blue-600 text-white hover:bg-blue-700 transition-colors ml-2"
        >
          <Mail className="w-4 h-4" />
          Invitar
        </button>
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg flex items-center gap-2 text-sm text-red-700">
          <AlertCircle className="w-4 h-4 shrink-0" />
          {error}
        </div>
      )}

      {/* Users tab */}
      {tab === "users" && (
        <div className="bg-white border border-gray-200 rounded-xl overflow-hidden shadow-sm">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                <th className="px-4 py-3 text-left font-medium text-gray-600">
                  Usuario
                </th>
                <th className="px-4 py-3 text-left font-medium text-gray-600">
                  Rol
                </th>
                <th className="px-4 py-3 text-left font-medium text-gray-600">
                  Estado
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {loading && (
                <tr>
                  <td
                    colSpan={3}
                    className="px-4 py-8 text-center text-gray-400 text-sm"
                  >
                    Cargando…
                  </td>
                </tr>
              )}
              {!loading && users.length === 0 && (
                <tr>
                  <td
                    colSpan={3}
                    className="px-4 py-8 text-center text-gray-400 text-sm"
                  >
                    No hay usuarios en este tenant
                  </td>
                </tr>
              )}
              {!loading &&
                users.map((u) => (
                  <tr
                    key={u.username}
                    className="hover:bg-gray-50 transition-colors"
                  >
                    <td className="px-4 py-3 font-medium text-gray-900">
                      {u.username}
                    </td>
                    <td className="px-4 py-3 text-gray-600">{u.role}</td>
                    <td className="px-4 py-3">
                      <span
                        className={`inline-flex px-2 py-0.5 rounded text-xs ${
                          u.disabled
                            ? "bg-red-100 text-red-700"
                            : "bg-green-100 text-green-700"
                        }`}
                      >
                        {u.disabled ? "Deshabilitado" : "Activo"}
                      </span>
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Invitations tab */}
      {tab === "invitations" && (
        <div className="bg-white border border-gray-200 rounded-xl overflow-hidden shadow-sm">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                <th className="px-4 py-3 text-left font-medium text-gray-600">
                  Email
                </th>
                <th className="px-4 py-3 text-left font-medium text-gray-600">
                  Rol
                </th>
                <th className="px-4 py-3 text-left font-medium text-gray-600">
                  Invitado por
                </th>
                <th className="px-4 py-3 text-left font-medium text-gray-600">
                  Expira
                </th>
                <th className="px-4 py-3 text-left font-medium text-gray-600">
                  Acciones
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {loading && (
                <tr>
                  <td
                    colSpan={5}
                    className="px-4 py-8 text-center text-gray-400 text-sm"
                  >
                    Cargando…
                  </td>
                </tr>
              )}
              {!loading && invitations.length === 0 && (
                <tr>
                  <td
                    colSpan={5}
                    className="px-4 py-8 text-center text-gray-400 text-sm"
                  >
                    No hay invitaciones pendientes
                  </td>
                </tr>
              )}
              {!loading &&
                invitations.map((inv) => (
                  <tr
                    key={inv.id}
                    className="hover:bg-gray-50 transition-colors"
                  >
                    <td className="px-4 py-3 text-gray-900">{inv.email}</td>
                    <td className="px-4 py-3 text-gray-600">{inv.role}</td>
                    <td className="px-4 py-3 text-gray-600">
                      {inv.invited_by}
                    </td>
                    <td className="px-4 py-3 text-gray-500 text-xs">
                      {inv.expires_at.slice(0, 16).replace("T", " ")}
                    </td>
                    <td className="px-4 py-3">
                      <button
                        onClick={() => void handleRevoke(inv.id)}
                        className="text-xs px-3 py-1 rounded border border-red-300 text-red-700 hover:bg-red-50 transition-colors"
                      >
                        Revocar
                      </button>
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      )}

      {showInvite && (
        <InviteUserModal
          onClose={() => setShowInvite(false)}
          onSuccess={() => {
            if (tab === "invitations") void loadInvitations();
          }}
        />
      )}
    </div>
  );
}
