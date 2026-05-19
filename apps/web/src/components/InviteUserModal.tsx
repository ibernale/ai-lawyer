"use client";

import { useState } from "react";
import { X, Mail, Copy, CheckCircle } from "lucide-react";
import { sendInvitation } from "@/lib/api";
import type { Invitation } from "@/lib/api";

const ROLES = [
  { value: "analyst", label: "Analista" },
  { value: "auditor", label: "Auditor" },
  { value: "operator", label: "Operador" },
  { value: "admin", label: "Administrador" },
];

interface Props {
  onClose: () => void;
  onSuccess?: (invitation: Invitation) => void;
}

export default function InviteUserModal({ onClose, onSuccess }: Props) {
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("analyst");
  const [ttlHours, setTtlHours] = useState(72);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<Invitation | null>(null);
  const [copied, setCopied] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      const inv = await sendInvitation(email, role, ttlHours);
      setResult(inv);
      onSuccess?.(inv);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Error al enviar la invitación.",
      );
    } finally {
      setLoading(false);
    }
  }

  async function handleCopy() {
    if (!result?.invite_url) return;
    await navigator.clipboard.writeText(result.invite_url);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md mx-4">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
          <div className="flex items-center gap-2">
            <Mail className="w-5 h-5 text-blue-600" />
            <h2 className="text-lg font-semibold text-gray-900">
              Invitar usuario
            </h2>
          </div>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 transition-colors"
            aria-label="Cerrar"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="px-6 py-5">
          {result ? (
            /* Success state */
            <div className="space-y-4">
              <div className="flex items-center gap-2 text-green-700">
                <CheckCircle className="w-5 h-5" />
                <span className="font-medium">Invitación creada</span>
              </div>
              <p className="text-sm text-gray-600">
                Comparte este enlace con{" "}
                <span className="font-medium">{result.email}</span>. Expira en{" "}
                {ttlHours} horas.
              </p>
              <div className="bg-gray-50 border border-gray-200 rounded-lg p-3">
                <p className="text-xs text-gray-500 mb-1">
                  Enlace de invitación
                </p>
                <p className="text-sm font-mono break-all text-gray-800">
                  {result.invite_url}
                </p>
              </div>
              <button
                onClick={handleCopy}
                className="w-full flex items-center justify-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg text-sm hover:bg-blue-700 transition-colors"
              >
                <Copy className="w-4 h-4" />
                {copied ? "¡Copiado!" : "Copiar enlace"}
              </button>
              <button
                onClick={onClose}
                className="w-full px-4 py-2 border border-gray-300 rounded-lg text-sm text-gray-700 hover:bg-gray-50 transition-colors"
              >
                Cerrar
              </button>
            </div>
          ) : (
            /* Form state */
            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Email
                </label>
                <input
                  type="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="usuario@empresa.com"
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Rol
                </label>
                <select
                  value={role}
                  onChange={(e) => setRole(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
                >
                  {ROLES.map((r) => (
                    <option key={r.value} value={r.value}>
                      {r.label}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Validez del enlace
                </label>
                <select
                  value={ttlHours}
                  onChange={(e) => setTtlHours(Number(e.target.value))}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
                >
                  <option value={24}>24 horas</option>
                  <option value={72}>72 horas (recomendado)</option>
                  <option value={168}>7 días</option>
                </select>
              </div>

              {error && (
                <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
                  {error}
                </p>
              )}

              <div className="flex gap-3 pt-1">
                <button
                  type="button"
                  onClick={onClose}
                  className="flex-1 px-4 py-2 border border-gray-300 rounded-lg text-sm text-gray-700 hover:bg-gray-50 transition-colors"
                >
                  Cancelar
                </button>
                <button
                  type="submit"
                  disabled={loading}
                  className="flex-1 flex items-center justify-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg text-sm hover:bg-blue-700 disabled:opacity-50 transition-colors"
                >
                  <Mail className="w-4 h-4" />
                  {loading ? "Enviando…" : "Crear invitación"}
                </button>
              </div>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}
