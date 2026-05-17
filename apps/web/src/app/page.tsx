export const dynamic = "force-dynamic";

import { Suspense } from "react";
import Link from "next/link";
import { StatusBadge } from "@/components/status-badge";
import { getHealth } from "@/lib/api";
import type { HealthResponse } from "@/lib/api";
import { RecentConsultations } from "@/components/RecentConsultations";

async function fetchHealth(): Promise<HealthResponse | null> {
  try {
    return await getHealth();
  } catch {
    return null;
  }
}

function QuickActionCard({
  href,
  title,
  description,
  icon,
  cta,
}: {
  href: string;
  title: string;
  description: string;
  icon: React.ReactNode;
  cta: string;
}) {
  return (
    <Link
      href={href}
      className="group flex flex-col gap-3 rounded-lg border border-border bg-card p-5 shadow-sm hover:border-brand-300 hover:shadow-md transition-all"
    >
      <div className="flex items-center gap-3">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-brand-50 text-brand-700 group-hover:bg-brand-100 transition-colors">
          {icon}
        </div>
        <h3 className="text-sm font-semibold text-foreground">{title}</h3>
      </div>
      <p className="text-xs text-muted-foreground leading-relaxed">
        {description}
      </p>
      <span className="mt-auto text-xs font-medium text-brand-600 group-hover:text-brand-700">
        {cta} →
      </span>
    </Link>
  );
}

export default async function HomePage() {
  const health = await fetchHealth();

  return (
    <div className="mx-auto max-w-4xl px-6 py-8 space-y-8">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Dashboard</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Regulación bancaria UE+ES · RGPD · Laboral · Mercantil
        </p>
      </div>

      {/* Quick actions */}
      <section aria-labelledby="acciones-title">
        <h2
          id="acciones-title"
          className="mb-3 text-sm font-semibold uppercase tracking-wider text-muted-foreground"
        >
          Acceso rápido
        </h2>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <QuickActionCard
            href="/consulta"
            title="Nueva consulta"
            description="Consulta normativa con citación verificable. Modo rápido, estándar o profundo."
            cta="Consultar"
            icon={
              <svg
                className="w-5 h-5"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
                aria-hidden="true"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={1.8}
                  d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-3 3-3-3z"
                />
              </svg>
            }
          />
          <QuickActionCard
            href="/historico"
            title="Histórico"
            description="Busca y filtra consultas anteriores por texto, profundidad o estado de verificación."
            cta="Ver historial"
            icon={
              <svg
                className="w-5 h-5"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
                aria-hidden="true"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={1.8}
                  d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"
                />
              </svg>
            }
          />
          <QuickActionCard
            href="/documentos"
            title="Documentos"
            description="Analiza contratos y documentos legales. Extrae riesgos, cláusulas y resúmenes ejecutivos."
            cta="Subir documento"
            icon={
              <svg
                className="w-5 h-5"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
                aria-hidden="true"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={1.8}
                  d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
                />
              </svg>
            }
          />
        </div>
      </section>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* System status */}
        <section
          aria-labelledby="estado-title"
          className="rounded-lg border border-border bg-card p-5 shadow-sm"
        >
          <h2
            id="estado-title"
            className="mb-4 text-sm font-semibold uppercase tracking-wider text-muted-foreground"
          >
            Estado del sistema
          </h2>
          {health === null ? (
            <div className="flex items-center gap-3">
              <StatusBadge status="unavailable" label="API no disponible" />
              <span className="text-sm text-muted-foreground">
                Comprueba que los servicios están arrancados con{" "}
                <code className="font-mono text-xs">make dev</code>.
              </span>
            </div>
          ) : (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium">API</span>
                <StatusBadge status={health.status} />
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm text-muted-foreground">
                  Qdrant (índice vectorial)
                </span>
                <StatusBadge status={health.deps_status.qdrant} />
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm text-muted-foreground">
                  Anthropic API
                </span>
                <StatusBadge
                  status={
                    health.deps_status.anthropic_api === "configured"
                      ? "healthy"
                      : "degraded"
                  }
                  label={
                    health.deps_status.anthropic_api === "configured"
                      ? "Configurada"
                      : "No configurada"
                  }
                />
              </div>
              <div className="border-t border-border pt-3 flex items-center justify-between">
                <span className="text-xs text-muted-foreground">
                  Versión: <span className="font-mono">{health.version}</span>
                </span>
                <Link
                  href="/admin"
                  className="text-xs text-brand-600 hover:underline"
                >
                  Panel admin →
                </Link>
              </div>
            </div>
          )}
        </section>

        {/* Recent consultations */}
        <section
          aria-labelledby="recientes-title"
          className="rounded-lg border border-border bg-card p-5 shadow-sm"
        >
          <div className="flex items-center justify-between mb-4">
            <h2
              id="recientes-title"
              className="text-sm font-semibold uppercase tracking-wider text-muted-foreground"
            >
              Últimas consultas
            </h2>
            <Link
              href="/historico"
              className="text-xs text-brand-600 hover:underline"
            >
              Ver todo →
            </Link>
          </div>
          <Suspense
            fallback={
              <div className="flex items-center justify-center py-8">
                <span className="h-5 w-5 animate-spin rounded-full border-2 border-brand-600 border-t-transparent" />
              </div>
            }
          >
            <RecentConsultations />
          </Suspense>
        </section>
      </div>
    </div>
  );
}
