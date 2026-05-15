"use client";

import { useEffect, useState } from "react";
import { getSystemState, setFlag, type FlagRow } from "@/lib/api";

function ReasonDialog({
  title,
  initialValue,
  onConfirm,
  onCancel,
}: {
  title: string;
  initialValue: string;
  onConfirm: (value: string, reason: string) => void;
  onCancel: () => void;
}) {
  const [value, setValue] = useState(initialValue);
  const [reason, setReason] = useState("");
  const [valueError, setValueError] = useState("");

  function validateJson(raw: string): boolean {
    try {
      JSON.parse(raw);
      setValueError("");
      return true;
    } catch {
      setValueError("JSON inválido");
      return false;
    }
  }

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg shadow-xl p-6 w-full max-w-md">
        <h2 className="text-base font-semibold mb-4">{title}</h2>

        <div className="mb-3">
          <label className="block text-xs font-medium text-gray-600 mb-1">
            Valor (JSON)
          </label>
          <textarea
            className={`w-full border rounded p-2 text-sm font-mono resize-none h-20 focus:outline-none focus:ring-2 focus:ring-blue-500 ${valueError ? "border-red-400" : "border-gray-300"}`}
            value={value}
            onChange={(e) => {
              setValue(e.target.value);
              if (valueError) validateJson(e.target.value);
            }}
            onBlur={() => validateJson(value)}
          />
          {valueError && (
            <p className="text-xs text-red-600 mt-1">{valueError}</p>
          )}
        </div>

        <div className="mb-4">
          <label className="block text-xs font-medium text-gray-600 mb-1">
            Motivo del cambio
          </label>
          <textarea
            className="w-full border border-gray-300 rounded p-2 text-sm resize-none h-16 focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="Obligatorio..."
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            autoFocus
          />
        </div>

        <div className="flex gap-3 justify-end">
          <button
            onClick={onCancel}
            className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900 border border-gray-300 rounded"
          >
            Cancelar
          </button>
          <button
            onClick={() => {
              if (!validateJson(value)) return;
              onConfirm(value, reason);
            }}
            disabled={!reason.trim()}
            className="px-4 py-2 text-sm font-medium bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            Guardar
          </button>
        </div>
      </div>
    </div>
  );
}

function flagValueDisplay(raw: string): string {
  try {
    const parsed = JSON.parse(raw);
    if (typeof parsed === "boolean") return parsed ? "true" : "false";
    if (typeof parsed === "number") return String(parsed);
    if (typeof parsed === "string") return parsed;
    return JSON.stringify(parsed);
  } catch {
    return raw;
  }
}

function FlagTypeBadge({ raw }: { raw: string }) {
  let type = "unknown";
  try {
    const v = JSON.parse(raw);
    type = Array.isArray(v) ? "array" : typeof v;
  } catch {
    type = "string";
  }

  const colors: Record<string, string> = {
    boolean: "bg-purple-100 text-purple-700",
    number: "bg-blue-100 text-blue-700",
    string: "bg-green-100 text-green-700",
    object: "bg-orange-100 text-orange-700",
    array: "bg-yellow-100 text-yellow-700",
  };

  return (
    <span
      className={`text-[10px] font-medium px-1.5 py-0.5 rounded ${colors[type] ?? "bg-gray-100 text-gray-600"}`}
    >
      {type}
    </span>
  );
}

function CreateFlagDialog({
  onConfirm,
  onCancel,
}: {
  onConfirm: (key: string, value: string, reason: string) => void;
  onCancel: () => void;
}) {
  const [key, setKey] = useState("");
  const [value, setValue] = useState("true");
  const [reason, setReason] = useState("");
  const [valueError, setValueError] = useState("");

  function validateJson(raw: string): boolean {
    try {
      JSON.parse(raw);
      setValueError("");
      return true;
    } catch {
      setValueError("JSON inválido");
      return false;
    }
  }

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg shadow-xl p-6 w-full max-w-md">
        <h2 className="text-base font-semibold mb-4">Nuevo feature flag</h2>
        <div className="space-y-3">
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">
              Clave del flag
            </label>
            <input
              type="text"
              required
              value={key}
              onChange={(e) => setKey(e.target.value)}
              className="border border-gray-300 rounded p-2 text-sm font-mono w-full focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="feature.mi_funcionalidad"
              autoFocus
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">
              Valor (JSON)
            </label>
            <textarea
              className={`w-full border rounded p-2 text-sm font-mono resize-none h-20 focus:outline-none focus:ring-2 focus:ring-blue-500 ${valueError ? "border-red-400" : "border-gray-300"}`}
              value={value}
              onChange={(e) => {
                setValue(e.target.value);
                if (valueError) validateJson(e.target.value);
              }}
              onBlur={() => validateJson(value)}
            />
            {valueError && (
              <p className="text-xs text-red-600 mt-1">{valueError}</p>
            )}
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">
              Motivo
            </label>
            <textarea
              className="w-full border border-gray-300 rounded p-2 text-sm resize-none h-16 focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="Obligatorio..."
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
          </div>
        </div>
        <div className="flex gap-3 justify-end mt-4">
          <button
            onClick={onCancel}
            className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900 border border-gray-300 rounded"
          >
            Cancelar
          </button>
          <button
            onClick={() => {
              if (!validateJson(value) || !key.trim() || !reason.trim()) return;
              onConfirm(key.trim(), value, reason);
            }}
            disabled={!key.trim() || !reason.trim()}
            className="px-4 py-2 text-sm font-medium bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            Crear flag
          </button>
        </div>
      </div>
    </div>
  );
}

export default function FlagsPage() {
  const [flags, setFlags] = useState<FlagRow[] | null>(null);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState<FlagRow | null>(null);
  const [creating, setCreating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");

  function load() {
    getSystemState()
      .then((s) => setFlags(s.flags))
      .catch(() => setError("No se pudo cargar los flags."));
  }

  useEffect(() => {
    load();
  }, []);

  async function handleSave(rawValue: string, reason: string) {
    if (!editing) return;
    setSaving(true);
    setSaveError("");
    try {
      const parsed = JSON.parse(rawValue);
      await setFlag(editing.key, parsed, reason);
      setEditing(null);
      load();
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : "Error al guardar");
    } finally {
      setSaving(false);
    }
  }

  async function handleCreate(key: string, rawValue: string, reason: string) {
    setSaving(true);
    setSaveError("");
    try {
      const parsed = JSON.parse(rawValue);
      await setFlag(key, parsed, reason);
      setCreating(false);
      load();
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : "Error al crear flag");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div>
      {creating && (
        <CreateFlagDialog
          onConfirm={handleCreate}
          onCancel={() => setCreating(false)}
        />
      )}

      <div className="mb-6 flex items-start justify-between">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">Feature Flags</h1>
          <p className="text-sm text-gray-500 mt-1">
            Flags de configuración del sistema. Los cambios tienen efecto
            inmediato y quedan registrados en el audit trail.
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => setCreating(true)}
            className="px-3 py-1.5 text-sm font-medium bg-blue-600 text-white rounded hover:bg-blue-700"
          >
            + Nuevo flag
          </button>
          <button
            onClick={load}
            className="px-3 py-1.5 text-sm border border-gray-300 rounded hover:bg-gray-50"
          >
            Actualizar
          </button>
        </div>
      </div>

      {error && (
        <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2 mb-4">
          {error}
        </p>
      )}

      {saveError && (
        <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2 mb-4">
          {saveError}
        </p>
      )}

      {!flags ? (
        <div className="space-y-2">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-12 bg-gray-100 rounded animate-pulse" />
          ))}
        </div>
      ) : flags.length === 0 ? (
        <div className="text-center py-16 text-gray-400">
          <p className="text-sm font-medium">
            No hay feature flags configurados.
          </p>
          <p className="text-xs mt-1 mb-4">
            Usa el botón &ldquo;+ Nuevo flag&rdquo; para crear el primero.
          </p>
          <button
            onClick={() => setCreating(true)}
            className="px-4 py-2 text-sm font-medium bg-blue-600 text-white rounded hover:bg-blue-700"
          >
            + Nuevo flag
          </button>
        </div>
      ) : (
        <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
          <table className="min-w-full text-sm">
            <thead className="bg-gray-50 text-gray-600 text-xs uppercase">
              <tr>
                <th className="px-4 py-3 text-left font-medium">Flag</th>
                <th className="px-4 py-3 text-left font-medium">Tipo</th>
                <th className="px-4 py-3 text-left font-medium">Valor</th>
                <th className="px-4 py-3 text-left font-medium">
                  Última modificación
                </th>
                <th className="px-4 py-3 text-left font-medium">Por</th>
                <th className="px-4 py-3 text-right font-medium">Acción</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {flags.map((f) => (
                <tr key={f.key} className="hover:bg-gray-50">
                  <td className="px-4 py-3 font-mono font-medium text-gray-900">
                    {f.key}
                  </td>
                  <td className="px-4 py-3">
                    <FlagTypeBadge raw={f.value} />
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-gray-700 max-w-xs truncate">
                    {flagValueDisplay(f.value)}
                  </td>
                  <td className="px-4 py-3 text-gray-500 text-xs">
                    {f.updated_at
                      ? new Date(f.updated_at).toLocaleString()
                      : "—"}
                  </td>
                  <td className="px-4 py-3 text-gray-500 text-xs">
                    {f.updated_by || "—"}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <button
                      onClick={() => setEditing(f)}
                      disabled={saving}
                      className="px-2 py-1 text-xs bg-gray-100 hover:bg-gray-200 text-gray-700 rounded disabled:opacity-50"
                    >
                      Editar
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {editing && (
        <ReasonDialog
          title={`Editar flag: ${editing.key}`}
          initialValue={editing.value}
          onConfirm={handleSave}
          onCancel={() => setEditing(null)}
        />
      )}
    </div>
  );
}
