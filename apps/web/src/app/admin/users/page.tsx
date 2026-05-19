"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import {
  listUsers,
  createUser,
  updateUser,
  deleteUser,
  forceRelogin,
  type UserRow,
} from "@/lib/api";
import InviteUserModal from "@/components/InviteUserModal";

const ROLES = ["analyst", "auditor", "operator", "admin"] as const;
type Role = (typeof ROLES)[number];

const ROLE_STYLES: Record<string, string> = {
  admin: "bg-red-100 text-red-700",
  operator: "bg-blue-100 text-blue-700",
  auditor: "bg-purple-100 text-purple-700",
  analyst: "bg-green-100 text-green-700",
};

const ROLE_PERMS: Record<string, string> = {
  admin: "Kill switch · Feature flags · Todos los recursos",
  operator: "Ops Center · Governance · Audit Trail · Notificaciones",
  auditor: "Audit Trail (solo lectura)",
  analyst: "Consultas (solo lectura)",
};

const ROLE_ORDER: Record<string, number> = {
  admin: 0,
  operator: 1,
  auditor: 2,
  analyst: 3,
};

// ---------------------------------------------------------------------------
// Modals
// ---------------------------------------------------------------------------

function CreateModal({
  onClose,
  onDone,
}: {
  onClose: () => void;
  onDone: () => void;
}) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<Role>("analyst");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (password.length < 8) {
      setError("La contraseña debe tener al menos 8 caracteres.");
      return;
    }
    setLoading(true);
    setError("");
    try {
      await createUser({ username: username.trim(), password, role });
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al crear usuario");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg shadow-xl p-6 w-full max-w-md">
        <h2 className="text-base font-semibold mb-4">Crear usuario</h2>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">
              Nombre de usuario
            </label>
            <input
              type="text"
              required
              minLength={2}
              maxLength={64}
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="border border-gray-300 rounded p-2 text-sm w-full focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="nombre.apellido"
              autoFocus
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">
              Contraseña (mín. 8 caracteres)
            </label>
            <input
              type="password"
              required
              minLength={8}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="border border-gray-300 rounded p-2 text-sm w-full focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">
              Rol
            </label>
            <select
              value={role}
              onChange={(e) => setRole(e.target.value as Role)}
              className="border border-gray-300 rounded p-2 text-sm w-full focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              {ROLES.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
            <p className="text-xs text-gray-400 mt-1">{ROLE_PERMS[role]}</p>
          </div>
          {error && <p className="text-xs text-red-600">{error}</p>}
          <div className="flex gap-3 justify-end pt-2">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900 border border-gray-300 rounded"
            >
              Cancelar
            </button>
            <button
              type="submit"
              disabled={loading}
              className="px-4 py-2 text-sm font-medium bg-[#b30000] text-white rounded hover:bg-[#8b0000] disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {loading ? "Creando..." : "Crear usuario"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function EditModal({
  user,
  currentUsername,
  onClose,
  onDone,
}: {
  user: UserRow;
  currentUsername: string;
  onClose: () => void;
  onDone: () => void;
}) {
  const [role, setRole] = useState<Role>(user.role as Role);
  const [password, setPassword] = useState("");
  const [disabled, setDisabled] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const isSelf = user.username === currentUsername;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (password && password.length < 8) {
      setError("La nueva contraseña debe tener al menos 8 caracteres.");
      return;
    }
    setLoading(true);
    setError("");
    try {
      await updateUser(user.username, {
        role: role !== user.role ? role : undefined,
        password: password || undefined,
        disabled: isSelf ? undefined : disabled,
      });
      onDone();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Error al actualizar usuario",
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg shadow-xl p-6 w-full max-w-md">
        <h2 className="text-base font-semibold mb-1">Editar usuario</h2>
        <p className="text-xs text-gray-500 mb-4 font-mono">{user.username}</p>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">
              Rol
            </label>
            <select
              value={role}
              onChange={(e) => setRole(e.target.value as Role)}
              className="border border-gray-300 rounded p-2 text-sm w-full focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              {ROLES.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">
              Nueva contraseña (dejar en blanco para no cambiar)
            </label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="border border-gray-300 rounded p-2 text-sm w-full focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="••••••••"
            />
          </div>
          {!isSelf && (
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={disabled}
                onChange={(e) => setDisabled(e.target.checked)}
                className="rounded"
              />
              <span className="text-sm text-gray-700">
                Deshabilitar cuenta (bloquea el acceso)
              </span>
            </label>
          )}
          {error && <p className="text-xs text-red-600">{error}</p>}
          <div className="flex gap-3 justify-end pt-2">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900 border border-gray-300 rounded"
            >
              Cancelar
            </button>
            <button
              type="submit"
              disabled={loading}
              className="px-4 py-2 text-sm font-medium bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {loading ? "Guardando..." : "Guardar cambios"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function DeleteDialog({
  user,
  onClose,
  onDone,
}: {
  user: UserRow;
  onClose: () => void;
  onDone: () => void;
}) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleDelete() {
    setLoading(true);
    setError("");
    try {
      await deleteUser(user.username);
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al eliminar");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg shadow-xl p-6 w-full max-w-sm">
        <h2 className="text-base font-semibold mb-2">Eliminar usuario</h2>
        <p className="text-sm text-gray-600 mb-4">
          ¿Eliminar permanentemente a{" "}
          <span className="font-mono font-semibold">{user.username}</span>? Esta
          acción no se puede deshacer.
        </p>
        {error && <p className="text-xs text-red-600 mb-3">{error}</p>}
        <div className="flex gap-3 justify-end">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900 border border-gray-300 rounded"
          >
            Cancelar
          </button>
          <button
            onClick={handleDelete}
            disabled={loading}
            className="px-4 py-2 text-sm font-medium bg-red-600 text-white rounded hover:bg-red-700 disabled:opacity-50"
          >
            {loading ? "Eliminando..." : "Eliminar"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function UsersPage() {
  const [users, setUsers] = useState<UserRow[] | null>(null);
  const [error, setError] = useState("");
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<UserRow | null>(null);
  const [deleting, setDeleting] = useState<UserRow | null>(null);
  const [showInvite, setShowInvite] = useState(false);
  const [forceReloginUser, setForceReloginUser] = useState<string | null>(null);
  const currentUsername =
    typeof window !== "undefined"
      ? (localStorage.getItem("lex_username") ?? "")
      : "";

  const load = useCallback(() => {
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

  useEffect(() => {
    load();
  }, [load]);

  async function handleForceRelogin(username: string) {
    setForceReloginUser(username);
    try {
      await forceRelogin(username);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al forzar re-login.");
    } finally {
      setForceReloginUser(null);
    }
  }

  const byRole = users
    ? (["admin", "operator", "auditor", "analyst"] as const).map((role) => ({
        role,
        count: users.filter((u) => u.role === role).length,
      }))
    : [];

  return (
    <div>
      {creating && (
        <CreateModal
          onClose={() => setCreating(false)}
          onDone={() => {
            setCreating(false);
            load();
          }}
        />
      )}
      {editing && (
        <EditModal
          user={editing}
          currentUsername={currentUsername}
          onClose={() => setEditing(null)}
          onDone={() => {
            setEditing(null);
            load();
          }}
        />
      )}
      {deleting && (
        <DeleteDialog
          user={deleting}
          onClose={() => setDeleting(null)}
          onDone={() => {
            setDeleting(null);
            load();
          }}
        />
      )}
      {showInvite && (
        <InviteUserModal
          onClose={() => setShowInvite(false)}
          onSuccess={() => setShowInvite(false)}
        />
      )}

      <div className="mb-6 flex items-start justify-between">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">Usuarios</h1>
          <p className="text-sm text-gray-500 mt-1">
            Usuarios con acceso al panel de administración.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowInvite(true)}
            className="px-3 py-1.5 text-sm font-medium bg-blue-600 text-white rounded hover:bg-blue-700 flex items-center gap-1.5"
          >
            <svg
              className="w-4 h-4"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"
              />
            </svg>
            Invitar
          </button>
          <button
            onClick={() => setCreating(true)}
            className="px-3 py-1.5 text-sm font-medium bg-[#b30000] text-white rounded hover:bg-[#8b0000] flex items-center gap-1.5"
          >
            <svg
              className="w-4 h-4"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M12 4v16m8-8H4"
              />
            </svg>
            Crear usuario
          </button>
        </div>
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
        <div className="text-center py-16 text-gray-400">
          <p className="text-sm">Sin usuarios configurados.</p>
          <p className="text-xs mt-1">
            Usa el botón &ldquo;Crear usuario&rdquo; para añadir el primero.
          </p>
        </div>
      ) : users ? (
        <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
          <table className="min-w-full text-sm">
            <thead className="bg-gray-50 text-gray-600 text-xs uppercase">
              <tr>
                <th className="px-4 py-3 text-left font-medium">Usuario</th>
                <th className="px-4 py-3 text-left font-medium">Rol</th>
                <th className="px-4 py-3 text-left font-medium">Permisos</th>
                <th className="px-4 py-3 text-right font-medium">Acciones</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {users.map((u) => (
                <tr key={u.username} className="hover:bg-gray-50">
                  <td className="px-4 py-3 font-medium text-gray-900 font-mono">
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
                    {ROLE_PERMS[u.role]}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center justify-end gap-2">
                      <Link
                        href={`/admin/users/${u.username}/sessions` as never}
                        className="text-xs text-gray-500 hover:text-gray-700 hover:underline"
                      >
                        Sesiones
                      </Link>
                      {u.username !== currentUsername && (
                        <button
                          onClick={() => void handleForceRelogin(u.username)}
                          disabled={forceReloginUser === u.username}
                          title="Forzar re-login (invalida todos los tokens activos)"
                          className="text-xs px-2 py-0.5 rounded border border-orange-300 text-orange-700 hover:bg-orange-50 disabled:opacity-50 transition-colors"
                        >
                          {forceReloginUser === u.username ? "…" : "Re-login"}
                        </button>
                      )}
                      <button
                        onClick={() => setEditing(u)}
                        title="Editar"
                        className="p-1 text-gray-400 hover:text-blue-600 rounded"
                      >
                        <svg
                          className="w-4 h-4"
                          fill="none"
                          stroke="currentColor"
                          viewBox="0 0 24 24"
                        >
                          <path
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            strokeWidth={2}
                            d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"
                          />
                        </svg>
                      </button>
                      {u.username !== currentUsername && (
                        <button
                          onClick={() => setDeleting(u)}
                          title="Eliminar"
                          className="p-1 text-gray-400 hover:text-red-600 rounded"
                        >
                          <svg
                            className="w-4 h-4"
                            fill="none"
                            stroke="currentColor"
                            viewBox="0 0 24 24"
                          >
                            <path
                              strokeLinecap="round"
                              strokeLinejoin="round"
                              strokeWidth={2}
                              d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"
                            />
                          </svg>
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}
