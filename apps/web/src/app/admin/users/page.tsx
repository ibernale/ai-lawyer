"use client";

import { useEffect, useState } from "react";
import { listUsers, type UserRow } from "@/lib/api";

const ROLE_STYLES: Record<string, string> = {
  admin: "bg-red-100 text-red-700",
  operator: "bg-blue-100 text-blue-700",
  auditor: "bg-purple-100 text-purple-700",
  analyst: "bg-green-100 text-green-700",
};

const ROLE_ORDER: Record<string, number> = {
  admin: 0,
  operator: 1,
  auditor: 2,
  analyst: 3,
};

export default function UsersPage() {
  const [users, setUsers] = useState<UserRow[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    listUsers()
      .then((rows) =>
        setUsers(
          [...rows].sort((a, b) => {
            const ra = ROLE_ORDER[a.role] ?? 99;
            const rb = ROLE_ORDER[b.role] ?? 99;
            return ra !== rb ? ra - rb : a.username.localeCompare(b.username);
          }),
        ),
      )
      .catch(() => setError("No se pudo cargar la lista de usuarios."));
  }, []);

  const byRole = users
    ? (["admin", "operator", "auditor", "analyst"] as const).map((role) => ({
        role,
        count: users.filter((u) => u.role === role).length,
      }))
    : [];

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-xl font-semibold text-gray-900">Users</h1>
        <p className="text-sm text-gray-500 mt-1">
          Usuarios con acceso al panel de administración. Para crear o modificar
          usuarios, actualiza el secreto{" "}
          <code className="bg-gray-100 text-gray-700 px-1 rounded text-xs">
            AUTH_USERS_JSON
          </code>{" "}
          en AWS Secrets Manager.
        </p>
      </div>

      {error && (
        <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2 mb-4">
          {error}
        </p>
      )}

      {users && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
          {byRole.map(({ role, count }) => (
            <div
              key={role}
              className="bg-white border border-gray-200 rounded-lg p-3 text-center"
            >
              <div className="text-2xl font-bold text-gray-800">{count}</div>
              <span
                className={`inline-block mt-1 text-xs font-medium px-2 py-0.5 rounded capitalize ${ROLE_STYLES[role] ?? "bg-gray-100 text-gray-700"}`}
              >
                {role}
              </span>
            </div>
          ))}
        </div>
      )}

      {!users && !error ? (
        <div className="space-y-2">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-12 bg-gray-100 rounded animate-pulse" />
          ))}
        </div>
      ) : users && users.length === 0 ? (
        <p className="text-sm text-gray-400 italic">
          Sin usuarios configurados.
        </p>
      ) : users ? (
        <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
          <table className="min-w-full text-sm">
            <thead className="bg-gray-50 text-gray-600 text-xs uppercase">
              <tr>
                <th className="px-4 py-3 text-left font-medium">Usuario</th>
                <th className="px-4 py-3 text-left font-medium">Rol</th>
                <th className="px-4 py-3 text-left font-medium">Permisos</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {users.map((u) => (
                <tr key={u.username} className="hover:bg-gray-50">
                  <td className="px-4 py-3 font-medium text-gray-900">
                    {u.username}
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={`inline-block text-xs font-medium px-2 py-0.5 rounded capitalize ${ROLE_STYLES[u.role] ?? "bg-gray-100 text-gray-700"}`}
                    >
                      {u.role}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-xs text-gray-500">
                    {u.role === "admin" &&
                      "Kill switch · Feature flags · Todos los recursos"}
                    {u.role === "operator" &&
                      "Ops Center · Governance · Audit Trail · Notificaciones"}
                    {u.role === "auditor" && "Audit Trail (solo lectura)"}
                    {u.role === "analyst" && "Consultas (solo lectura)"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      <div className="mt-6 bg-blue-50 border border-blue-200 rounded-lg px-4 py-3 text-xs text-blue-700">
        <strong>Gestión de usuarios:</strong> Añade o modifica entradas en el
        secreto{" "}
        <code className="bg-blue-100 px-1 rounded">AUTH_USERS_JSON</code> de AWS
        Secrets Manager. Cada entrada requiere{" "}
        <code className="bg-blue-100 px-1 rounded">username</code>,{" "}
        <code className="bg-blue-100 px-1 rounded">password_hash</code> (bcrypt)
        y <code className="bg-blue-100 px-1 rounded">role</code>. Los cambios
        surten efecto en el siguiente despliegue.
      </div>
    </div>
  );
}
