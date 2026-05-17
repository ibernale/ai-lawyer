"use client";

import type React from "react";

const STEP_LABELS: Record<string, string> = {
  routing: "Analizando consulta",
  planning: "Elaborando plan jurídico",
  retrieval: "Recuperando fuentes",
  specialists: "Consultando especialistas",
  judging: "Revisando coherencia",
  verifying: "Verificando citas",
};

interface Props {
  step: string;
  message: string;
  pct: number;
  answerDraft: string;
  onCancel?: () => void;
}

export function StreamProgressBar({
  step,
  message,
  pct,
  answerDraft,
  onCancel,
}: Props) {
  const label = STEP_LABELS[step] ?? step;

  return (
    <div className="space-y-4">
      {/* Progress header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="h-4 w-4 animate-spin rounded-full border-2 border-[#EC0000] border-t-transparent" />
          <span className="text-sm font-medium text-gray-700">{label}</span>
        </div>
        {onCancel && (
          <button
            onClick={onCancel}
            className="text-xs text-gray-400 hover:text-gray-600 transition-colors"
          >
            Cancelar
          </button>
        )}
      </div>

      {/* Progress bar */}
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-gray-100">
        <div
          className="h-full rounded-full bg-[#EC0000] transition-all duration-500 ease-out"
          style={{ width: `${pct}%` }}
        />
      </div>

      {/* Step message */}
      <p className="text-xs text-gray-500">{message}</p>

      {/* Token stream — rendered when specialist starts responding */}
      {answerDraft && (
        <div className="mt-4 rounded-lg border border-gray-100 bg-gray-50 p-4">
          <p className="mb-2 text-xs font-medium uppercase tracking-wide text-gray-400">
            Respuesta en curso
          </p>
          <div className="max-h-64 overflow-y-auto">
            <pre className="whitespace-pre-wrap font-sans text-sm text-gray-700">
              {answerDraft}
              <span className="inline-block h-4 w-0.5 animate-pulse bg-[#EC0000] align-middle" />
            </pre>
          </div>
        </div>
      )}
    </div>
  );
}
