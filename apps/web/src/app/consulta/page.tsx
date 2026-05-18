"use client";

import { Suspense, useCallback, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { ChangeAlertBanner } from "@/components/ChangeAlertBanner";
import { ResponseView } from "@/components/ResponseView";
import { StreamProgressBar } from "@/components/StreamProgressBar";
import { ErrorBanner } from "@/components/ui/error-banner";
import { consultQueryStream, getConsultation } from "@/lib/api";
import type { ConsultResponse } from "@/lib/api";

const JURISDICTION_CODES = [
  "ES", "EU", "UK", "BR", "MX", "US", "PL", "PT", "AR", "DE", "CH",
] as const;

const OUTPUT_TYPE_VALUES = [
  "dictamen",
  "nota",
  "memo_comite",
  "analisis_riesgo",
] as const;

function ConsultaInner() {
  const searchParams = useSearchParams();
  const t = useTranslations("consulta");
  const tLayout = useTranslations("layout");
  const tJurisdictions = useTranslations("jurisdictions");

  const DEPTH_OPTIONS: {
    value: "shallow" | "standard" | "deep";
    label: string;
    tooltip: string;
  }[] = [
    {
      value: "shallow",
      label: t("depthShallow"),
      tooltip: t("depthShallowTooltip"),
    },
    {
      value: "standard",
      label: t("depthStandard"),
      tooltip: t("depthStandardTooltip"),
    },
    {
      value: "deep",
      label: t("depthDeep"),
      tooltip: t("depthDeepTooltip"),
    },
  ];

  const OUTPUT_TYPES = [
    { value: "dictamen", label: t("outputDictamen") },
    { value: "nota", label: t("outputNota") },
    { value: "memo_comite", label: t("outputMemoComite") },
    { value: "analisis_riesgo", label: t("outputAnalisisRiesgo") },
  ];

  const [query, setQuery] = useState("");
  const [outputType, setOutputType] = useState("dictamen");
  const [depth, setDepth] = useState<"shallow" | "standard" | "deep">(
    "standard",
  );
  const [selectedJurisdictions, setSelectedJurisdictions] = useState<string[]>(
    [],
  );
  const [streaming, setStreaming] = useState(false);
  const [streamStep, setStreamStep] = useState("");
  const [streamMessage, setStreamMessage] = useState("");
  const [streamPct, setStreamPct] = useState(0);
  const [answerDraft, setAnswerDraft] = useState("");
  const [response, setResponse] = useState<ConsultResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const cancelRef = useRef<(() => void) | null>(null);

  // Load from trace ID if provided via ?trace=...
  const traceId = searchParams.get("trace") ?? undefined;
  const [loaded, setLoaded] = useState(false);

  if (traceId && !loaded && !response) {
    setLoaded(true);
    getConsultation(traceId)
      .then(setResponse)
      .catch((e: Error) => setError(e.message));
  }

  const handleCancel = useCallback(() => {
    cancelRef.current?.();
    setStreaming(false);
    setAnswerDraft("");
    setStreamStep("");
    setStreamMessage("");
    setStreamPct(0);
  }, []);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!query.trim()) return;
    setStreaming(true);
    setError(null);
    setResponse(null);
    setAnswerDraft("");
    setStreamStep("routing");
    setStreamMessage(t("initiating"));
    setStreamPct(0);

    const cancel = consultQueryStream(
      query.trim(),
      {
        onProgress: (step, message, pct) => {
          setStreamStep(step);
          setStreamMessage(message);
          setStreamPct(pct);
        },
        onToken: (delta) => {
          setAnswerDraft((prev: string) => prev + delta);
        },
        onResult: (resp) => {
          setResponse(resp);
        },
        onError: (msg) => {
          setError(msg);
          setStreaming(false);
          setAnswerDraft("");
        },
        onDone: () => {
          setStreaming(false);
          setAnswerDraft("");
        },
      },
      {
        outputType,
        depth,
        jurisdictions: selectedJurisdictions,
      },
    );
    cancelRef.current = cancel;
  }

  return (
    <div className="flex min-h-screen flex-col">
      {/* Permanent disclaimer banner — not dismissable */}
      <div className="sticky top-0 z-40 bg-amber-50 border-b border-amber-200 px-4 py-2">
        <p className="text-xs text-amber-800 text-center">
          <strong>{tLayout("draftNotice")}</strong> {tLayout("draftRequires")}{" "}
          {tLayout("draftDisclaimer")}{" "}
          <a
            href={tLayout("legalPage")}
            className="underline font-medium hover:text-amber-900"
          >
            {tLayout("moreInfo")}
          </a>
        </p>
      </div>

      <main className="flex-1 mx-auto w-full max-w-4xl px-4 py-8 space-y-6">
        {/* Regulation change alert banner (Fase 11D.2) */}
        <ChangeAlertBanner />

        <header>
          <h1 className="text-2xl font-bold tracking-tight">
            {t("title")}
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {t("subtitle")}
          </p>
        </header>

        <form onSubmit={handleSubmit} className="space-y-3">
          <textarea
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t("placeholder")}
            rows={5}
            className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring resize-y"
            disabled={streaming}
          />

          {/* Depth selector */}
          <div className="flex items-center gap-1">
            <span className="text-sm font-medium text-muted-foreground mr-1">
              {t("depthLabel")}
            </span>
            {DEPTH_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                type="button"
                title={opt.tooltip}
                onClick={() => setDepth(opt.value)}
                disabled={streaming}
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
              {t("jurisdictionsLabel")}{" "}
              <span className="text-xs font-normal">
                {t("jurisdictionsHint")}
              </span>
              :
            </span>
            <div className="flex flex-wrap gap-1.5">
              {JURISDICTION_CODES.map((code) => {
                const active = selectedJurisdictions.includes(code);
                return (
                  <button
                    key={code}
                    type="button"
                    disabled={streaming}
                    onClick={() =>
                      setSelectedJurisdictions((prev) =>
                        active
                          ? prev.filter((c) => c !== code)
                          : [...prev, code],
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
                    {code}
                    <span className="ml-1 hidden sm:inline text-[10px] opacity-70">
                      {tJurisdictions(code)}
                    </span>
                  </button>
                );
              })}
              {selectedJurisdictions.length > 0 && (
                <button
                  type="button"
                  onClick={() => setSelectedJurisdictions([])}
                  disabled={streaming}
                  className="px-2 py-1 text-xs text-muted-foreground hover:text-foreground underline"
                >
                  Limpiar
                </button>
              )}
            </div>
          </div>

          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2">
              <label
                htmlFor="output-type"
                className="text-sm font-medium whitespace-nowrap"
              >
                {t("outputTypeLabel")}
              </label>
              <select
                id="output-type"
                value={outputType}
                onChange={(e) => setOutputType(e.target.value)}
                disabled={streaming}
                className="rounded-md border border-input bg-background px-2 py-1.5 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
              >
                {OUTPUT_TYPES.map((ot) => (
                  <option key={ot.value} value={ot.value}>
                    {ot.label}
                  </option>
                ))}
              </select>
            </div>

            <button
              type="submit"
              disabled={streaming || !query.trim()}
              className="ml-auto rounded-md bg-primary px-5 py-2 text-sm font-semibold text-primary-foreground shadow-sm hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {t("submitButton")}
            </button>
          </div>
        </form>

        {error && <ErrorBanner message={error} />}

        {streaming && (
          <StreamProgressBar
            step={streamStep}
            message={streamMessage}
            pct={streamPct}
            answerDraft={answerDraft}
            onCancel={handleCancel}
          />
        )}

        {!streaming && response && (
          <ResponseView
            response={response}
            selectedJurisdictions={selectedJurisdictions}
          />
        )}
      </main>
    </div>
  );
}

export default function ConsultaPage() {
  return (
    <Suspense>
      <ConsultaInner />
    </Suspense>
  );
}
