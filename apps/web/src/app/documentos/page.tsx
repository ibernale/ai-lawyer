"use client";

import { useRef, useState } from "react";
import {
  uploadDocument,
  analyzeDocument,
  compareDocuments,
  deleteDocument,
} from "@/lib/api";
import type { UploadResponse, AnalysisResponse, AnalysisMode } from "@/lib/api";
import { ErrorBanner } from "@/components/ui/error-banner";

const ANALYSIS_MODES: { value: AnalysisMode; label: string; desc: string }[] = [
  {
    value: "resumen_ejecutivo",
    label: "Resumen ejecutivo",
    desc: "Síntesis de los puntos clave del documento.",
  },
  {
    value: "analisis_clausulas",
    label: "Análisis de cláusulas",
    desc: "Revisión detallada de cada cláusula con implicaciones legales.",
  },
  {
    value: "riesgos",
    label: "Análisis de riesgos",
    desc: "Identificación de cláusulas problemáticas o riesgos legales.",
  },
  {
    value: "comparativa",
    label: "Comparativa",
    desc: "Comparación entre dos documentos (requiere subir dos ficheros).",
  },
];

type Doc = UploadResponse & { file: File };

function VerificationBadge({ status }: { status: "green" | "amber" | "red" }) {
  const cfg = {
    green: { cls: "bg-green-100 text-green-800", label: "Verificado" },
    amber: { cls: "bg-amber-100 text-amber-800", label: "Parcial" },
    red: { cls: "bg-red-100 text-red-800", label: "Revisar" },
  };
  const { cls, label } = cfg[status];
  return (
    <span
      className={`inline-flex items-center rounded px-2 py-0.5 text-xs font-medium ${cls}`}
    >
      {label}
    </span>
  );
}

export default function DocumentosPage() {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [docs, setDocs] = useState<Doc[]>([]);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);

  const [selectedDocId, setSelectedDocId] = useState<string | null>(null);
  const [mode, setMode] = useState<AnalysisMode>("riesgos");
  const [customQuery, setCustomQuery] = useState("");
  const [analysing, setAnalysing] = useState(false);
  const [result, setResult] = useState<AnalysisResponse | null>(null);
  const [analysisError, setAnalysisError] = useState<string | null>(null);

  async function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    e.target.value = "";

    setUploading(true);
    setUploadError(null);
    try {
      const resp = await uploadDocument(file);
      setDocs((prev) => [...prev, { ...resp, file }]);
    } catch (err) {
      setUploadError(
        err instanceof Error
          ? err.message
          : "No se pudo subir el documento. Asegúrate de que el servicio de documentos está disponible.",
      );
    } finally {
      setUploading(false);
    }
  }

  async function handleAnalyse() {
    if (!selectedDocId) return;
    setAnalysing(true);
    setAnalysisError(null);
    setResult(null);

    const query =
      customQuery.trim() ||
      ANALYSIS_MODES.find((m) => m.value === mode)?.desc ||
      "Analiza este documento.";

    try {
      if (mode === "comparativa") {
        if (docs.length < 2) {
          setAnalysisError(
            "La comparativa requiere al menos dos documentos subidos.",
          );
          return;
        }
        const a = docs[0]!;
        const b = docs[1]!;
        const cmp = await compareDocuments(
          [a.doc_id, b.doc_id],
          customQuery.trim() || "Compara estos dos documentos.",
        );
        setResult({
          doc_id: a.doc_id,
          trace_id: cmp.trace_id,
          filename: `${a.filename} ↔ ${b.filename}`,
          mode: "comparativa",
          analysis_text: cmp.diff_text,
          segment_count: 0,
          verification_status: cmp.verification_status,
          analysed_at: cmp.analysed_at,
        });
      } else {
        const res = await analyzeDocument(selectedDocId, query, mode);
        setResult(res);
      }
    } catch (err) {
      setAnalysisError(
        err instanceof Error
          ? err.message
          : "El análisis falló. Inténtalo de nuevo.",
      );
    } finally {
      setAnalysing(false);
    }
  }

  async function handleDelete(docId: string) {
    await deleteDocument(docId).catch(() => {});
    setDocs((prev) => prev.filter((d) => d.doc_id !== docId));
    if (selectedDocId === docId) setSelectedDocId(null);
    setResult(null);
  }

  return (
    <div className="flex min-h-screen flex-col">
      <div className="sticky top-0 z-40 bg-amber-50 border-b border-amber-200 px-4 py-2">
        <p className="text-xs text-amber-800 text-center">
          <strong>Análisis asistido por IA.</strong> El resultado es un borrador
          orientativo — requiere revisión por jurista cualificado.
        </p>
      </div>

      <main className="flex-1 mx-auto w-full max-w-4xl px-4 py-8 space-y-6">
        <header>
          <h1 className="text-2xl font-bold tracking-tight">
            Análisis de documentos
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Sube contratos, dictámenes o normativa para obtener un análisis
            asistido.
          </p>
        </header>

        {/* Upload zone */}
        <section className="space-y-3">
          <div
            className="rounded-lg border-2 border-dashed border-border bg-muted/20 p-8 text-center cursor-pointer hover:bg-muted/40 transition-colors"
            onClick={() => fileInputRef.current?.click()}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              const file = e.dataTransfer.files?.[0];
              if (file) {
                const dt = new DataTransfer();
                dt.items.add(file);
                if (fileInputRef.current) {
                  fileInputRef.current.files = dt.files;
                  fileInputRef.current.dispatchEvent(
                    new Event("change", { bubbles: true }),
                  );
                }
              }
            }}
          >
            {uploading ? (
              <div className="flex items-center justify-center gap-2">
                <span className="inline-block h-5 w-5 animate-spin rounded-full border-2 border-primary border-t-transparent" />
                <span className="text-sm text-muted-foreground">
                  Subiendo documento…
                </span>
              </div>
            ) : (
              <>
                <svg
                  className="mx-auto h-10 w-10 text-muted-foreground/50 mb-2"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                  aria-hidden="true"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={1.5}
                    d="M9 13h6m-3-3v6m5 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
                  />
                </svg>
                <p className="text-sm font-medium">
                  Arrastra un archivo o haz clic para seleccionar
                </p>
                <p className="text-xs text-muted-foreground mt-1">
                  PDF, DOCX, TXT · máximo 64 KB
                </p>
              </>
            )}
          </div>
          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf,.docx,.txt"
            className="hidden"
            onChange={handleFileChange}
          />

          {uploadError && (
            <ErrorBanner
              message={uploadError}
              onRetry={() => fileInputRef.current?.click()}
            />
          )}
        </section>

        {/* Document list */}
        {docs.length > 0 && (
          <section className="space-y-2">
            <p className="text-sm font-medium text-muted-foreground">
              Documentos subidos
            </p>
            <ul className="space-y-1">
              {docs.map((d) => (
                <li
                  key={d.doc_id}
                  onClick={() => setSelectedDocId(d.doc_id)}
                  className={`flex items-center gap-3 rounded-md border px-3 py-2 cursor-pointer transition-colors ${
                    selectedDocId === d.doc_id
                      ? "border-primary bg-primary/5"
                      : "border-border hover:bg-muted/40"
                  }`}
                >
                  <svg
                    className="h-4 w-4 text-muted-foreground shrink-0"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                    aria-hidden="true"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
                    />
                  </svg>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium truncate">{d.filename}</p>
                    <p className="text-xs text-muted-foreground">
                      {d.segment_count} segmentos ·{" "}
                      {d.page_count ? `${d.page_count} pág. · ` : ""}
                      expira{" "}
                      {new Date(d.expires_at).toLocaleDateString("es-ES")}
                    </p>
                  </div>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      void handleDelete(d.doc_id);
                    }}
                    className="text-muted-foreground hover:text-red-600 text-xs transition-colors"
                    title="Eliminar documento"
                  >
                    ✕
                  </button>
                </li>
              ))}
            </ul>
          </section>
        )}

        {/* Analysis controls */}
        {docs.length > 0 && (
          <section className="space-y-4 rounded-lg border border-border p-4">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {ANALYSIS_MODES.map((m) => (
                <button
                  key={m.value}
                  type="button"
                  onClick={() => setMode(m.value)}
                  className={`rounded-md border p-3 text-left transition-colors ${
                    mode === m.value
                      ? "border-primary bg-primary/5"
                      : "border-border hover:bg-muted/40"
                  }`}
                >
                  <p className="text-sm font-medium">{m.label}</p>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    {m.desc}
                  </p>
                </button>
              ))}
            </div>

            <textarea
              value={customQuery}
              onChange={(e) => setCustomQuery(e.target.value)}
              placeholder="Pregunta específica (opcional): p.ej. '¿Cuáles son las obligaciones de confidencialidad?'"
              rows={2}
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring resize-none"
              disabled={analysing}
            />

            {analysisError && (
              <ErrorBanner message={analysisError} onRetry={handleAnalyse} />
            )}

            <button
              onClick={handleAnalyse}
              disabled={analysing || (mode !== "comparativa" && !selectedDocId)}
              className="w-full rounded-md bg-primary px-5 py-2 text-sm font-semibold text-primary-foreground shadow-sm hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {analysing ? (
                <span className="flex items-center justify-center gap-2">
                  <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-primary-foreground border-t-transparent" />
                  Analizando…
                </span>
              ) : (
                "Analizar"
              )}
            </button>
          </section>
        )}

        {/* Result */}
        {result && (
          <section className="space-y-3">
            <div className="flex items-center gap-3">
              <h2 className="text-base font-semibold">
                Resultado del análisis
              </h2>
              <VerificationBadge status={result.verification_status} />
              <span className="text-xs text-muted-foreground ml-auto">
                {result.filename}
              </span>
            </div>
            <div className="rounded-lg border border-border bg-muted/10 p-4 text-sm leading-relaxed whitespace-pre-wrap max-h-[60vh] overflow-y-auto">
              {result.analysis_text}
            </div>
            <p className="text-xs text-muted-foreground">
              Analizado el{" "}
              {new Date(result.analysed_at).toLocaleString("es-ES")} ·{" "}
              {result.segment_count} segmentos procesados
            </p>
          </section>
        )}

        {docs.length === 0 && !uploading && (
          <div className="rounded-lg border border-dashed border-border p-8 text-center">
            <p className="text-sm text-muted-foreground">
              Sube un documento para comenzar el análisis.
            </p>
          </div>
        )}
      </main>
    </div>
  );
}
