"use client";

import { useState } from "react";
import { LegalDisclaimer } from "@/components/legal-disclaimer";
import { ResponseView } from "@/components/ResponseView";
import { consultQuery, getConsultation } from "@/lib/api";
import type { ConsultResponse } from "@/lib/api";

const JURISDICTIONS = [
  { code: "ES", label: "España" },
  { code: "EU", label: "UE" },
  { code: "UK", label: "Reino Unido" },
  { code: "BR", label: "Brasil" },
  { code: "MX", label: "México" },
  { code: "US", label: "EE.UU." },
  { code: "PL", label: "Polonia" },
  { code: "PT", label: "Portugal" },
  { code: "AR", label: "Argentina" },
  { code: "DE", label: "Alemania" },
  { code: "CH", label: "Suiza" },
];

const OUTPUT_TYPES = [
  { value: "dictamen", label: "Dictamen" },
  { value: "nota", label: "Nota informativa" },
  { value: "memo_comite", label: "Memo de comité" },
  { value: "analisis_riesgo", label: "Análisis de riesgo" },
];

const DEPTH_OPTIONS: {
  value: "shallow" | "standard" | "deep";
  label: string;
  tooltip: string;
}[] = [
  {
    value: "shallow",
    label: "Rápido",
    tooltip: "Ruta directa: router → especialista → verificación. Sin planificación. ~10s.",
  },
  {
    value: "standard",
    label: "Estándar",
    tooltip:
      "Planner descompone la consulta y coordina especialistas. Verificación completa. ~30s.",
  },
  {
    value: "deep",
    label: "Profundo",
    tooltip:
      "Planner + Maker(s) + Judge iterativo (máx. 2 iter.). Mayor calidad, más coste y tiempo. ~60s.",
  },
];

export default function ConsultaPage({
  searchParams,
}: {
  searchParams: Record<string, string | undefined>;
}) {
  const [query, setQuery] = useState("");
  const [outputType, setOutputType] = useState("dictamen");
  const [depth, setDepth] = useState<"shallow" | "standard" | "deep">("standard");
  const [selectedJurisdictions, setSelectedJurisdictions] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [response, setResponse] = useState<ConsultResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Load from trace ID if provided via ?trace=...
  const traceId = searchParams["trace"];
  const [loaded, setLoaded] = useState(false);

  if (traceId && !loaded && !response) {
    setLoaded(true);
    getConsultation(traceId)
      .then(setResponse)
      .catch((e: Error) => setError(e.message));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!query.trim()) return;
    setLoading(true);
    setError(null);
    setResponse(null);
    try {
      const resp = await consultQuery(query.trim(), outputType, undefined, depth, selectedJurisdictions);
      setResponse(resp);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error desconocido");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-screen flex-col">
      {/* Permanent disclaimer banner — not dismissable */}
      <div className="sticky top-0 z-40 bg-amber-50 border-b border-amber-200 px-4 py-2">
        <p className="text-xs text-amber-800 text-center">
          <strong>Borrador asistido por IA.</strong> Requiere validación por jurista cualificado
          antes de cualquier uso. No constituye asesoramiento legal. Sistema en fase MVP, dataset
          y prompts no validados por experto humano.{" "}
          <a href="/legal" className="underline font-medium hover:text-amber-900">
            Más información
          </a>
        </p>
      </div>

      <main className="flex-1 mx-auto w-full max-w-4xl px-4 py-8 space-y-6">
        <header>
          <h1 className="text-2xl font-bold tracking-tight">Consulta jurídica</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Regulación bancaria · RGPD · Laboral · Mercantil · Penal económico · Administrativo
          </p>
        </header>

        <form onSubmit={handleSubmit} className="space-y-3">
          <textarea
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Escriba su consulta normativa…"
            rows={5}
            className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring resize-y"
            disabled={loading}
          />

          {/* Depth selector */}
          <div className="flex items-center gap-1">
            <span className="text-sm font-medium text-muted-foreground mr-1">Profundidad:</span>
            {DEPTH_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                type="button"
                title={opt.tooltip}
                onClick={() => setDepth(opt.value)}
                disabled={loading}
                className={[
                  "px-3 py-1 text-xs font-medium rounded-md border transition-colors",
                  depth === opt.value
                    ? "bg-primary text-primary-foreground border-primary"
                    : "bg-background text-muted-foreground border-input hover:bg-accent hover:text-accent-foreground",
                  "disabled:opacity-50 disabled:cursor-not-allowed",
                ].join(" ")}
              >
                {opt.label}
              </button>
            ))}
          </div>

          {/* Jurisdiction multi-select chips */}
          <div className="space-y-1">
            <span className="text-sm font-medium text-muted-foreground">
              Jurisdicciones{" "}
              <span className="text-xs font-normal">(vacío = autodetectar)</span>:
            </span>
            <div className="flex flex-wrap gap-1.5">
              {JURISDICTIONS.map((j) => {
                const active = selectedJurisdictions.includes(j.code);
                return (
                  <button
                    key={j.code}
                    type="button"
                    disabled={loading}
                    onClick={() =>
                      setSelectedJurisdictions((prev) =>
                        active ? prev.filter((c) => c !== j.code) : [...prev, j.code],
                      )
                    }
                    className={[
                      "px-2.5 py-1 text-xs font-medium rounded-full border transition-colors",
                      active
                        ? "bg-primary text-primary-foreground border-primary"
                        : "bg-background text-muted-foreground border-input hover:bg-accent hover:text-accent-foreground",
                      "disabled:opacity-50 disabled:cursor-not-allowed",
                    ].join(" ")}
                  >
                    {j.code}
                    <span className="ml-1 hidden sm:inline text-[10px] opacity-70">{j.label}</span>
                  </button>
                );
              })}
              {selectedJurisdictions.length > 0 && (
                <button
                  type="button"
                  onClick={() => setSelectedJurisdictions([])}
                  disabled={loading}
                  className="px-2 py-1 text-xs text-muted-foreground hover:text-foreground underline"
                >
                  Limpiar
                </button>
              )}
            </div>
          </div>

          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2">
              <label htmlFor="output-type" className="text-sm font-medium whitespace-nowrap">
                Tipo de documento:
              </label>
              <select
                id="output-type"
                value={outputType}
                onChange={(e) => setOutputType(e.target.value)}
                disabled={loading}
                className="rounded-md border border-input bg-background px-2 py-1.5 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
              >
                {OUTPUT_TYPES.map((t) => (
                  <option key={t.value} value={t.value}>
                    {t.label}
                  </option>
                ))}
              </select>
            </div>

            <button
              type="submit"
              disabled={loading || !query.trim()}
              className="ml-auto rounded-md bg-primary px-5 py-2 text-sm font-semibold text-primary-foreground shadow-sm hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {loading ? (
                <span className="flex items-center gap-2">
                  <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-primary-foreground border-t-transparent" />
                  Consultando…
                </span>
              ) : (
                "Consultar"
              )}
            </button>
          </div>
        </form>

        {error && (
          <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
            {error}
          </div>
        )}

        {response && (
          <ResponseView
            response={response}
            selectedJurisdictions={selectedJurisdictions}
          />
        )}
      </main>

      <LegalDisclaimer />
    </div>
  );
}
