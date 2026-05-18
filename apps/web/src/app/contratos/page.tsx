"use client";

import { useCallback, useRef, useState } from "react";
import Link from "next/link";
import { Upload } from "lucide-react";
import { ContractAnalysisView } from "@/components/ContractAnalysisView";
import { ErrorBanner } from "@/components/ui/error-banner";
import { analyzeContractStream } from "@/lib/api";
import type { ContractAnalysis } from "@/lib/api";

const ACCEPTED_TYPES = [
  "application/pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
];
const MAX_SIZE_MB = 20;
const MAX_SIZE_BYTES = MAX_SIZE_MB * 1024 * 1024;

// ─── Upload Zone ───────────────────────────────────────────────────────────

function UploadZone({
  file,
  onFileSelected,
  disabled,
}: {
  file: File | null;
  onFileSelected: (f: File) => void;
  disabled: boolean;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragOver(false);
    const dropped = e.dataTransfer.files[0];
    if (dropped && ACCEPTED_TYPES.includes(dropped.type)) {
      onFileSelected(dropped);
    }
  }

  function handleChange(e: React.ChangeEvent<HTMLInputElement>) {
    const selected = e.target.files?.[0];
    if (selected) onFileSelected(selected);
    // Reset so same file can be re-selected
    e.target.value = "";
  }

  return (
    <div
      role="button"
      tabIndex={disabled ? -1 : 0}
      aria-label="Zona de carga de archivos"
      onClick={() => !disabled && inputRef.current?.click()}
      onKeyDown={(e) => {
        if (!disabled && (e.key === "Enter" || e.key === " ")) {
          inputRef.current?.click();
        }
      }}
      onDragOver={(e) => {
        e.preventDefault();
        if (!disabled) setDragOver(true);
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={handleDrop}
      className={[
        "flex flex-col items-center justify-center gap-4 rounded-xl border-2 border-dashed px-6 py-16 transition-colors cursor-pointer",
        dragOver
          ? "border-brand-600 bg-brand-50 dark:bg-brand-950/20"
          : file
            ? "border-brand-400 bg-brand-50/50 dark:bg-brand-950/10"
            : "border-border bg-muted/20 hover:border-brand-400 hover:bg-muted/40",
        disabled ? "pointer-events-none opacity-50" : "",
      ].join(" ")}
    >
      <input
        ref={inputRef}
        type="file"
        accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        className="sr-only"
        onChange={handleChange}
        disabled={disabled}
      />

      <div className="rounded-full bg-brand-100 p-4 dark:bg-brand-900/30">
        <Upload className="h-7 w-7 text-brand-700 dark:text-brand-400" />
      </div>

      {file ? (
        <div className="text-center space-y-1">
          <p className="text-sm font-semibold text-foreground truncate max-w-xs">
            {file.name}
          </p>
          <p className="text-xs text-muted-foreground">
            {(file.size / 1024 / 1024).toFixed(2)} MB
          </p>
          <p className="text-xs text-brand-600 dark:text-brand-400">
            Haz clic para cambiar el archivo
          </p>
        </div>
      ) : (
        <div className="text-center space-y-1.5">
          <p className="text-sm font-medium text-foreground">
            Arrastra un contrato aquí o{" "}
            <span className="text-brand-600 dark:text-brand-400 underline underline-offset-2">
              haz clic para seleccionar
            </span>
          </p>
          <p className="text-xs text-muted-foreground">
            PDF o DOCX · máx. {MAX_SIZE_MB} MB
          </p>
        </div>
      )}
    </div>
  );
}

// ─── Analyzing state ───────────────────────────────────────────────────────

function AnalyzingState({
  filename,
  progress,
  stepLabel,
  onCancel,
}: {
  filename: string;
  progress: number;
  stepLabel: string;
  onCancel: () => void;
}) {
  return (
    <div className="flex flex-col items-center gap-8 py-12">
      {/* Spinner */}
      <div className="relative h-20 w-20">
        <span className="absolute inset-0 rounded-full border-4 border-muted" />
        <span className="absolute inset-0 rounded-full border-4 border-brand-600 border-t-transparent animate-spin" />
        <span className="absolute inset-0 flex items-center justify-center text-sm font-bold text-brand-700 dark:text-brand-400">
          {Math.round(progress)}%
        </span>
      </div>

      {/* Filename */}
      <div className="text-center space-y-1">
        <p className="text-base font-semibold text-foreground">
          Analizando contrato…
        </p>
        <p className="text-sm text-muted-foreground truncate max-w-sm">
          {filename}
        </p>
      </div>

      {/* Progress bar */}
      <div className="w-full max-w-md space-y-2">
        <div className="h-2 rounded-full bg-muted overflow-hidden">
          <div
            className="h-full rounded-full bg-brand-600 transition-all duration-500"
            style={{ width: `${progress}%` }}
          />
        </div>
        <p className="text-xs text-muted-foreground text-center animate-pulse">
          {stepLabel}
        </p>
      </div>

      <button
        type="button"
        onClick={onCancel}
        className="rounded-md border border-border px-4 py-2 text-sm text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
      >
        Cancelar
      </button>
    </div>
  );
}

// ─── Main page ─────────────────────────────────────────────────────────────

const INITIAL_STEP_LABEL = "Iniciando análisis…";

type PageState = "upload" | "analyzing" | "results";

export default function ContratosPage() {
  const [pageState, setPageState] = useState<PageState>("upload");
  const [file, setFile] = useState<File | null>(null);
  const [fileSizeError, setFileSizeError] = useState<string | null>(null);
  const [progress, setProgress] = useState(0);
  const [stepLabel, setStepLabel] = useState(INITIAL_STEP_LABEL);
  const [analysis, setAnalysis] = useState<ContractAnalysis | null>(null);
  const [error, setError] = useState<string | null>(null);

  // cleanup function returned by analyzeContractStream
  const cleanupRef = useRef<(() => void) | null>(null);

  function handleFileSelected(f: File) {
    if (f.size > MAX_SIZE_BYTES) {
      setFileSizeError(
        `El archivo supera el límite de ${MAX_SIZE_MB} MB (${(f.size / 1024 / 1024).toFixed(1)} MB).`,
      );
      return;
    }
    setFileSizeError(null);
    setFile(f);
    setError(null);
  }

  const handleCancel = useCallback(() => {
    cleanupRef.current?.();
    cleanupRef.current = null;
    setPageState("upload");
    setProgress(0);
    setStepLabel(INITIAL_STEP_LABEL);
  }, []);

  function handleAnalyze() {
    if (!file) return;
    setError(null);
    setPageState("analyzing");
    setProgress(0);
    setStepLabel(INITIAL_STEP_LABEL);

    const cleanup = analyzeContractStream(file, {
      onProgress: (step, _message, pct) => {
        setStepLabel(step || _message || INITIAL_STEP_LABEL);
        setProgress(pct);
      },
      onResult: (result) => {
        setAnalysis(result);
        setProgress(100);
        setPageState("results");
      },
      onError: (msg) => {
        setError(msg);
        setPageState("upload");
      },
      onDone: () => {
        // results already set via onResult; nothing extra needed
      },
    });
    cleanupRef.current = cleanup;
  }

  function handleReset() {
    setFile(null);
    setAnalysis(null);
    setError(null);
    setFileSizeError(null);
    setProgress(0);
    setStepLabel(INITIAL_STEP_LABEL);
    setPageState("upload");
  }

  // ── Results ──────────────────────────────────────────────────────────────
  if (pageState === "results" && analysis) {
    return (
      <div className="flex min-h-screen flex-col">
        <main className="flex-1 mx-auto w-full max-w-7xl px-4 py-8 space-y-6">
          <header className="flex items-center justify-between flex-wrap gap-3">
            <div>
              <h1 className="text-2xl font-bold tracking-tight">
                Análisis de contratos
              </h1>
              <p className="mt-1 text-sm text-muted-foreground">
                Resultado del análisis para{" "}
                <span className="font-medium text-foreground">
                  {analysis.filename}
                </span>
              </p>
            </div>
            <div className="flex items-center gap-3">
              <Link
                href="/historico"
                className="rounded-md border border-border px-4 py-2 text-sm text-muted-foreground hover:bg-muted transition-colors"
              >
                Ver histórico
              </Link>
              <button
                type="button"
                onClick={handleReset}
                className="rounded-md bg-brand-700 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-800 transition-colors"
              >
                Nuevo análisis
              </button>
            </div>
          </header>

          <ContractAnalysisView analysis={analysis} />
        </main>
      </div>
    );
  }

  // ── Analyzing ─────────────────────────────────────────────────────────────
  if (pageState === "analyzing" && file) {
    return (
      <div className="flex min-h-screen flex-col">
        <main className="flex-1 mx-auto w-full max-w-2xl px-4 py-8">
          <header className="mb-8">
            <h1 className="text-2xl font-bold tracking-tight">
              Análisis de contratos
            </h1>
          </header>
          <AnalyzingState
            filename={file.name}
            progress={progress}
            stepLabel={stepLabel}
            onCancel={handleCancel}
          />
        </main>
      </div>
    );
  }

  // ── Upload ─────────────────────────────────────────────────────────────────
  return (
    <div className="flex min-h-screen flex-col">
      <main className="flex-1 mx-auto w-full max-w-2xl px-4 py-8 space-y-6">
        <header>
          <h1 className="text-2xl font-bold tracking-tight">
            Análisis de contratos
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Sube un contrato para identificar su tipo, marco legal y riesgos
          </p>
        </header>

        {error && (
          <ErrorBanner
            message={error}
            onRetry={file ? handleAnalyze : undefined}
          />
        )}

        {fileSizeError && <ErrorBanner message={fileSizeError} />}

        <UploadZone
          file={file}
          onFileSelected={handleFileSelected}
          disabled={false}
        />

        <div className="flex justify-end">
          <button
            type="button"
            onClick={handleAnalyze}
            disabled={!file}
            className="rounded-md bg-brand-700 px-6 py-2.5 text-sm font-semibold text-white hover:bg-brand-800 disabled:opacity-40 disabled:cursor-not-allowed transition-colors shadow-sm"
          >
            Analizar contrato
          </button>
        </div>
      </main>
    </div>
  );
}
