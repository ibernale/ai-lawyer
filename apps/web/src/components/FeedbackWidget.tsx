"use client";

import { useState } from "react";

type FeedbackVerdict = "aceptable" | "dudoso" | "incorrecto";

const VERDICTS: { value: FeedbackVerdict; label: string; cls: string }[] = [
  {
    value: "aceptable",
    label: "✅ Aceptable",
    cls: "border-green-200 text-green-800 hover:bg-green-50 data-[active=true]:bg-green-100 data-[active=true]:border-green-400",
  },
  {
    value: "dudoso",
    label: "❓ Dudoso",
    cls: "border-amber-200 text-amber-800 hover:bg-amber-50 data-[active=true]:bg-amber-100 data-[active=true]:border-amber-400",
  },
  {
    value: "incorrecto",
    label: "❌ Incorrecto",
    cls: "border-red-200 text-red-800 hover:bg-red-50 data-[active=true]:bg-red-100 data-[active=true]:border-red-400",
  },
];

const API_BASE =
  typeof window === "undefined"
    ? (process.env["API_BASE_URL"] ?? "http://localhost:8000")
    : (process.env["NEXT_PUBLIC_API_URL"] ?? "http://localhost:8000");

export function FeedbackWidget({ traceId }: { traceId: string }) {
  const [selected, setSelected] = useState<FeedbackVerdict | null>(null);
  const [notes, setNotes] = useState("");
  const [expanded, setExpanded] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleVerdict(v: FeedbackVerdict) {
    setSelected(v);
    setExpanded(true);
  }

  async function handleSubmit() {
    if (!selected) return;
    setSubmitting(true);
    setError(null);
    try {
      const token =
        typeof window !== "undefined"
          ? sessionStorage.getItem("lex_agents_token")
          : null;
      const res = await fetch(`${API_BASE}/api/v1/feedback`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ trace_id: traceId, verdict: selected, notes }),
      });
      if (!res.ok) throw new Error(`${res.status}`);
      setDone(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al enviar");
    } finally {
      setSubmitting(false);
    }
  }

  if (done) {
    return (
      <div className="flex items-center gap-2 text-xs text-green-700">
        <span>✓</span>
        <span>Feedback guardado. Gracias.</span>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <p className="text-xs text-muted-foreground font-medium">
        ¿Esta respuesta es correcta?
      </p>
      <div className="flex flex-wrap gap-2">
        {VERDICTS.map((v) => (
          <button
            key={v.value}
            data-active={selected === v.value}
            onClick={() => handleVerdict(v.value)}
            className={`rounded border px-3 py-1.5 text-xs font-medium transition-colors ${v.cls}`}
          >
            {v.label}
          </button>
        ))}
      </div>

      {expanded && (
        <div className="space-y-2">
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={2}
            placeholder="Notas opcionales (qué falla, qué fuente contradice…)"
            className="w-full rounded border border-input bg-background px-2 py-1.5 text-xs resize-none"
          />
          {error && <p className="text-xs text-red-600">{error}</p>}
          <button
            onClick={handleSubmit}
            disabled={submitting}
            className="rounded bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            {submitting ? "Enviando…" : "Enviar feedback"}
          </button>
        </div>
      )}
    </div>
  );
}
