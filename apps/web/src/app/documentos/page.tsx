"use client";

import type React from "react";
import { useCallback, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type {
  AnalysisMode,
  AnalysisResponse,
  CompareResponse,
  UploadResponse,
} from "@/lib/api";
import {
  analyzeDocument,
  compareDocuments,
  deleteDocument,
  uploadDocument,
} from "@/lib/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type UploadedDoc = UploadResponse & { file: File };

// ---------------------------------------------------------------------------
// DocChip — purple [DOC:s] chip used inline in analysis text
// ---------------------------------------------------------------------------

function DocChip({ idx }: { idx: number }) {
  return (
    <span className="inline-flex items-center rounded bg-purple-100 px-1.5 py-0.5 text-xs font-mono font-medium text-purple-700 mx-0.5">
      §{idx}
    </span>
  );
}

function renderAnalysisText(text: string) {
  const parts = text.split(/(\[DOC:\d+\])/g);
  return parts.map((part, i) => {
    const docMatch = part.match(/^\[DOC:(\d+)\]$/);
    if (docMatch) {
      return <DocChip key={i} idx={parseInt(docMatch[1]!, 10)} />;
    }
    return (
      <ReactMarkdown
        key={i}
        remarkPlugins={[remarkGfm]}
        components={{
          p: ({ children }) => <span className="block mb-2">{children}</span>,
        }}
      >
        {part}
      </ReactMarkdown>
    );
  });
}

// ---------------------------------------------------------------------------
// DropZone
// ---------------------------------------------------------------------------

function DropZone({
  onFiles,
  disabled,
}: {
  onFiles: (files: File[]) => void;
  disabled?: boolean;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragging(false);
      if (disabled) return;
      const files = Array.from(e.dataTransfer.files);
      if (files.length > 0) onFiles(files);
    },
    [onFiles, disabled],
  );

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        if (!disabled) setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
      onClick={() => !disabled && inputRef.current?.click()}
      className={[
        "flex flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-12 cursor-pointer transition-colors select-none",
        dragging
          ? "border-primary bg-primary/5"
          : "border-border hover:border-primary/50 hover:bg-muted/40",
        disabled ? "opacity-50 cursor-not-allowed" : "",
      ].join(" ")}
    >
      <span className="text-4xl mb-3">📄</span>
      <p className="text-sm font-medium text-foreground">
        Arrastra un documento aquí o haz clic para seleccionar
      </p>
      <p className="text-xs text-muted-foreground mt-1">
        PDF, DOCX, TXT, EML · máx. 50 MB · 200 páginas PDF
      </p>
      <input
        ref={inputRef}
        type="file"
        className="sr-only"
        accept=".pdf,.docx,.txt,.eml"
        multiple
        onChange={(e) => {
          const files = Array.from(e.target.files ?? []);
          if (files.length > 0) onFiles(files);
        }}
        disabled={disabled}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// DocumentCard
// ---------------------------------------------------------------------------

function DocumentCard({
  doc,
  isSelected,
  onSelect,
  onDelete,
}: {
  doc: UploadedDoc;
  isSelected: boolean;
  onSelect: () => void;
  onDelete: () => void;
}) {
  const mimeLabel: Record<string, string> = {
    "application/pdf": "PDF",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
      "DOCX",
    "text/plain": "TXT",
    "message/rfc822": "EML",
  };

  return (
    <div
      className={[
        "flex items-center justify-between rounded-lg border px-4 py-3 cursor-pointer transition-colors",
        isSelected
          ? "border-primary bg-primary/5"
          : "border-border hover:border-primary/30 hover:bg-muted/30",
      ].join(" ")}
      onClick={onSelect}
    >
      <div className="flex items-center gap-3 min-w-0">
        <span className="text-xl shrink-0">
          {doc.mime_type.includes("pdf")
            ? "📕"
            : doc.mime_type.includes("word")
              ? "📘"
              : doc.mime_type.includes("plain")
                ? "📄"
                : "📧"}
        </span>
        <div className="min-w-0">
          <p className="text-sm font-medium truncate">{doc.filename}</p>
          <p className="text-xs text-muted-foreground">
            {mimeLabel[doc.mime_type] ?? doc.mime_type} ·{" "}
            {doc.segment_count} segmentos
            {doc.page_count != null ? ` · ${doc.page_count} pp.` : ""}
          </p>
        </div>
      </div>
      <div className="flex items-center gap-2 shrink-0 ml-4">
        {isSelected && (
          <span className="text-xs font-medium text-primary">✓ Seleccionado</span>
        )}
        <button
          onClick={(e) => {
            e.stopPropagation();
            onDelete();
          }}
          className="text-xs text-muted-foreground hover:text-red-500 transition-colors px-1"
          title="Eliminar documento"
        >
          ×
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// AnalysisPanel
// ---------------------------------------------------------------------------

function AnalysisPanel({
  result,
}: {
  result: AnalysisResponse | CompareResponse;
}) {
  const isCompare = "diff_text" in result;
  const text = isCompare ? result.diff_text : result.analysis_text;
  const statusColor = {
    green: "bg-green-50 border-green-200 text-green-800",
    amber: "bg-amber-50 border-amber-200 text-amber-800",
    red: "bg-red-50 border-red-200 text-red-800",
  }[result.verification_status];

  return (
    <div className="space-y-3">
      <div className={`rounded-md border px-3 py-2 text-xs ${statusColor}`}>
        Verificación: <strong>{result.verification_status.toUpperCase()}</strong>
        {" · "}
        <span className="font-mono opacity-70">
          trace: {"trace_id" in result ? result.trace_id.slice(0, 8) : "—"}
        </span>
      </div>
      <article className="rounded-lg border border-border bg-background p-5 text-sm leading-relaxed prose prose-sm max-w-none">
        {renderAnalysisText(text)}
      </article>
      <p className="text-xs text-muted-foreground italic">
        Este análisis es un borrador asistido por IA y requiere validación por
        un jurista cualificado.
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

const MODE_LABELS: Record<AnalysisMode, string> = {
  resumen_ejecutivo: "Resumen ejecutivo",
  analisis_clausulas: "Análisis de cláusulas",
  riesgos: "Riesgos identificados",
  comparativa: "Comparativa",
};

export default function DocumentosPage() {
  const [docs, setDocs] = useState<UploadedDoc[]>([]);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [uploading, setUploading] = useState(false);
  const [analysing, setAnalysing] = useState(false);
  const [mode, setMode] = useState<AnalysisMode>("riesgos");
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<
    AnalysisResponse | CompareResponse | null
  >(null);
  const [error, setError] = useState<string | null>(null);

  async function handleFiles(files: File[]) {
    setUploading(true);
    setError(null);
    for (const file of files) {
      try {
        const uploaded = await uploadDocument(file);
        setDocs((prev) => [...prev, { ...uploaded, file }]);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Error al subir el archivo");
      }
    }
    setUploading(false);
  }

  function toggleSelect(docId: string) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(docId)) {
        next.delete(docId);
      } else {
        if (next.size >= 2) {
          // Keep only the most recent and this new one
          const arr = Array.from(next);
          next.delete(arr[0]!);
        }
        next.add(docId);
      }
      return next;
    });
  }

  async function handleDelete(docId: string) {
    try {
      await deleteDocument(docId);
    } catch {
      // ignore — TTL will clean it up
    }
    setDocs((prev) => prev.filter((d) => d.doc_id !== docId));
    setSelectedIds((prev) => {
      const next = new Set(prev);
      next.delete(docId);
      return next;
    });
  }

  async function handleAnalyse() {
    const ids = Array.from(selectedIds);
    if (ids.length === 0) return;
    setAnalysing(true);
    setError(null);
    setResult(null);
    try {
      if (ids.length === 2 && mode === "comparativa") {
        const res = await compareDocuments(
          ids as [string, string],
          query || "Compara estos dos documentos.",
        );
        setResult(res);
      } else {
        const res = await analyzeDocument(
          ids[0]!,
          query || "Analiza este documento.",
          mode,
        );
        setResult(res);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error en el análisis");
    } finally {
      setAnalysing(false);
    }
  }

  const selectedCount = selectedIds.size;
  const canCompare = selectedCount === 2;
  const canAnalyse = selectedCount >= 1 && !analysing;

  return (
    <div className="mx-auto max-w-3xl px-4 py-8 space-y-6">
      <div>
        <h1 className="text-xl font-semibold">Análisis de documentos</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Sube contratos, resoluciones o correos para análisis jurídico asistido
          por IA.
        </p>
      </div>

      {/* Drop zone */}
      <DropZone onFiles={handleFiles} disabled={uploading} />
      {uploading && (
        <p className="text-xs text-muted-foreground animate-pulse">
          Subiendo documento…
        </p>
      )}

      {/* Document list */}
      {docs.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
            Documentos subidos ({docs.length})
          </p>
          {docs.map((doc) => (
            <DocumentCard
              key={doc.doc_id}
              doc={doc}
              isSelected={selectedIds.has(doc.doc_id)}
              onSelect={() => toggleSelect(doc.doc_id)}
              onDelete={() => handleDelete(doc.doc_id)}
            />
          ))}
          <p className="text-xs text-muted-foreground">
            Selecciona 1 documento para analizar, o 2 para comparar.
          </p>
        </div>
      )}

      {/* Analysis controls */}
      {selectedCount > 0 && (
        <div className="rounded-lg border border-border p-4 space-y-4">
          <div className="flex flex-wrap gap-2">
            {(Object.keys(MODE_LABELS) as AnalysisMode[]).map((m) => (
              <button
                key={m}
                onClick={() => setMode(m)}
                disabled={m === "comparativa" && !canCompare}
                className={[
                  "rounded-full px-3 py-1 text-xs font-medium transition-colors border",
                  mode === m
                    ? "bg-primary text-primary-foreground border-primary"
                    : "border-border hover:border-primary/50 hover:bg-muted/40 disabled:opacity-40",
                ].join(" ")}
              >
                {MODE_LABELS[m]}
              </button>
            ))}
          </div>

          <textarea
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={
              mode === "comparativa"
                ? "¿Qué aspectos quieres comparar? (opcional)"
                : "¿Qué quieres analizar? (opcional)"
            }
            rows={2}
            className="w-full rounded border border-input bg-background px-3 py-2 text-sm resize-none placeholder:text-muted-foreground"
          />

          <button
            onClick={handleAnalyse}
            disabled={!canAnalyse}
            className="w-full rounded bg-primary text-primary-foreground px-4 py-2 text-sm font-medium hover:bg-primary/90 disabled:opacity-50 transition-colors"
          >
            {analysing
              ? "Analizando…"
              : mode === "comparativa"
                ? "Comparar documentos"
                : "Analizar documento"}
          </button>
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* Analysis result */}
      {result && <AnalysisPanel result={result} />}
    </div>
  );
}
