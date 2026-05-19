"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Building2,
  Plus,
  CheckCircle,
  XCircle,
  AlertCircle,
} from "lucide-react";
import { listTenants, createTenant, updateTenant } from "@/lib/api";
import type { Tenant } from "@/lib/api";

const PLANS = ["standard", "enterprise"];

function PlanBadge({ plan }: { plan: string }) {
  const isPro = plan === "enterprise";
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${
        isPro ? "bg-purple-100 text-purple-800" : "bg-gray-100 text-gray-600"
      }`}
    >
      {isPro ? "Enterprise" : "Standard"}
    </span>
  );
}

function StatusBadge({ disabled }: { disabled: boolean }) {
  return disabled ? (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs bg-red-100 text-red-700">
      <XCircle className="w-3 h-3" />
      Deshabilitado
    </span>
  ) : (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs bg-green-100 text-green-700">
      <CheckCircle className="w-3 h-3" />
      Activo
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

export default function TenantsPage() {
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [showCreate, setShowCreate] = useState(false);

  // Create form
  const [newId, setNewId] = useState("");
  const [newName, setNewName] = useState("");
  const [newPlan, setNewPlan] = useState("standard");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await listTenants();
      setTenants(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al cargar tenants.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setCreating(true);
    setCreateError("");
    try {
      await createTenant(newId, newName, newPlan);
      setShowCreate(false);
      setNewId("");
      setNewName("");
      setNewPlan("standard");
      await load();
    } catch (e) {
      setCreateError(e instanceof Error ? e.message : "Error al crear tenant.");
    } finally {
      setCreating(false);
    }
  }

  async function handleToggle(tenant: Tenant) {
    try {
      await updateTenant(tenant.id, { disabled: !tenant.disabled });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al actualizar tenant.");
    }
  }

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900 flex items-center gap-2">
            <Building2 className="w-6 h-6 text-gray-500" />
            Tenants
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            Gestión de organizaciones en la plataforma
          </p>
        </div>
        <button
          onClick={() => setShowCreate((v) => !v)}
          className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg text-sm hover:bg-blue-700 transition-colors"
        >
          <Plus className="w-4 h-4" />
          Nuevo tenant
        </button>
      </div>

      {/* Create form */}
      {showCreate && (
        <div className="mb-6 bg-white border border-gray-200 rounded-xl p-5 shadow-sm">
          <h2 className="text-sm font-semibold text-gray-800 mb-4">
            Crear tenant
          </h2>
          <form
            onSubmit={handleCreate}
            className="flex flex-wrap gap-3 items-end"
          >
            <div>
              <label className="block text-xs text-gray-600 mb-1">
                ID (slug)
              </label>
              <input
                required
                value={newId}
                onChange={(e) =>
                  setNewId(e.target.value.toLowerCase().replace(/\s+/g, "-"))
                }
                placeholder="santander-es"
                pattern="[a-z0-9\-]+"
                className="px-3 py-2 border border-gray-300 rounded-lg text-sm w-40 focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
            <div>
              <label className="block text-xs text-gray-600 mb-1">Nombre</label>
              <input
                required
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                placeholder="Santander España"
                className="px-3 py-2 border border-gray-300 rounded-lg text-sm w-48 focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
            <div>
              <label className="block text-xs text-gray-600 mb-1">Plan</label>
              <select
                value={newPlan}
                onChange={(e) => setNewPlan(e.target.value)}
                className="px-3 py-2 border border-gray-300 rounded-lg text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                {PLANS.map((p) => (
                  <option key={p} value={p}>
                    {p.charAt(0).toUpperCase() + p.slice(1)}
                  </option>
                ))}
              </select>
            </div>
            <button
              type="submit"
              disabled={creating}
              className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm hover:bg-blue-700 disabled:opacity-50 transition-colors"
            >
              {creating ? "Creando…" : "Crear"}
            </button>
            <button
              type="button"
              onClick={() => setShowCreate(false)}
              className="px-4 py-2 border border-gray-300 rounded-lg text-sm text-gray-700 hover:bg-gray-50 transition-colors"
            >
              Cancelar
            </button>
          </form>
          {createError && (
            <p className="mt-2 text-sm text-red-600">{createError}</p>
          )}
        </div>
      )}

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg flex items-center gap-2 text-sm text-red-700">
          <AlertCircle className="w-4 h-4 shrink-0" />
          {error}
        </div>
      )}

      <div className="bg-white border border-gray-200 rounded-xl overflow-hidden shadow-sm">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-200">
            <tr>
              <th className="px-4 py-3 text-left font-medium text-gray-600">
                ID
              </th>
              <th className="px-4 py-3 text-left font-medium text-gray-600">
                Nombre
              </th>
              <th className="px-4 py-3 text-left font-medium text-gray-600">
                Plan
              </th>
              <th className="px-4 py-3 text-left font-medium text-gray-600">
                Estado
              </th>
              <th className="px-4 py-3 text-left font-medium text-gray-600">
                Creado
              </th>
              <th className="px-4 py-3 text-left font-medium text-gray-600">
                Acciones
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {loading &&
              Array.from({ length: 3 }).map((_, i) => <SkeletonRow key={i} />)}

            {!loading && tenants.length === 0 && (
              <tr>
                <td
                  colSpan={6}
                  className="px-4 py-12 text-center text-gray-400"
                >
                  <Building2 className="w-8 h-8 mx-auto mb-2 opacity-40" />
                  <p>No hay tenants configurados</p>
                </td>
              </tr>
            )}

            {!loading &&
              tenants.map((t) => (
                <tr key={t.id} className="hover:bg-gray-50 transition-colors">
                  <td className="px-4 py-3 font-mono text-xs text-gray-600">
                    {t.id}
                  </td>
                  <td className="px-4 py-3 font-medium text-gray-900">
                    {t.name}
                  </td>
                  <td className="px-4 py-3">
                    <PlanBadge plan={t.plan} />
                  </td>
                  <td className="px-4 py-3">
                    <StatusBadge disabled={t.disabled} />
                  </td>
                  <td className="px-4 py-3 text-gray-500 text-xs">
                    {t.created_at.slice(0, 10)}
                  </td>
                  <td className="px-4 py-3">
                    {t.id !== "default" && (
                      <button
                        onClick={() => void handleToggle(t)}
                        className={`text-xs px-3 py-1 rounded border transition-colors ${
                          t.disabled
                            ? "border-green-300 text-green-700 hover:bg-green-50"
                            : "border-red-300 text-red-700 hover:bg-red-50"
                        }`}
                      >
                        {t.disabled ? "Habilitar" : "Deshabilitar"}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
