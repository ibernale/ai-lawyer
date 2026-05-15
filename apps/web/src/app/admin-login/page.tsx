"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

// Use relative URL so the ALB routes /auth/token to the API in all envs.
// Falls back to localhost for local dev where web and API run on different ports.
const API_BASE =
  typeof window !== "undefined" && window.location.port === "3000"
    ? "http://localhost:8000"
    : "";

export default function AdminLoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/auth/token`, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({ username, password }).toString(),
      });
      if (!res.ok) {
        setError("Usuario o contraseña incorrectos.");
        return;
      }
      const data = (await res.json()) as { access_token: string };
      sessionStorage.setItem("lex_agents_token", data.access_token);
      router.replace("/admin");
    } catch {
      setError("Error de conexión. Inténtalo de nuevo.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center">
          <span className="text-4xl" aria-hidden="true">
            ⚖
          </span>
          <h1 className="mt-3 text-xl font-semibold text-gray-900">
            lex-agents
          </h1>
          <p className="text-sm text-gray-500 mt-1">Panel de administración</p>
        </div>

        <form
          onSubmit={handleSubmit}
          className="bg-white border border-gray-200 rounded-xl shadow-sm px-8 py-8 space-y-5"
        >
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Usuario
            </label>
            <input
              type="text"
              autoComplete="username"
              required
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="usuario@ejemplo.com"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Contraseña
            </label>
            <input
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>

          {error && (
            <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white font-medium text-sm rounded-lg py-2.5 transition-colors"
          >
            {loading ? "Accediendo..." : "Acceder"}
          </button>
        </form>

        <p className="mt-6 text-center text-xs text-gray-400">
          Acceso restringido — uso interno
        </p>
      </div>
    </div>
  );
}
