import { StatusBadge } from "@/components/status-badge";
import { getHealth } from "@/lib/api";
import type { HealthResponse } from "@/lib/api";

async function fetchHealth(): Promise<HealthResponse | null> {
  try {
    return await getHealth();
  } catch {
    return null;
  }
}

export default async function HomePage() {
  const health = await fetchHealth();

  return (
    <div className="max-w-2xl space-y-8">
      <div>
        <h2 className="text-2xl font-semibold text-foreground">
          Regulatorio bancario UE+ES
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Consulta sobre normativa prudencial, supervisión y solvencia de
          entidades de crédito.
        </p>
      </div>

      {/* System status card */}
      <section className="rounded-lg border border-border bg-card p-5 shadow-sm">
        <h3 className="mb-4 text-sm font-semibold uppercase tracking-wider text-muted-foreground">
          Estado del sistema
        </h3>
        {health === null ? (
          <div className="flex items-center gap-3">
            <StatusBadge status="unavailable" label="API no disponible" />
            <span className="text-sm text-muted-foreground">
              No se puede conectar al backend. Comprueba que los servicios están
              arrancados con <code className="font-mono text-xs">make dev</code>
              .
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
            <div className="border-t border-border pt-3">
              <span className="text-xs text-muted-foreground">
                Versión: <span className="font-mono">{health.version}</span>
              </span>
            </div>
          </div>
        )}
      </section>

      {/* Query area placeholder */}
      <section className="rounded-lg border border-dashed border-border bg-muted/30 p-8 text-center">
        <p className="text-sm text-muted-foreground">
          La interfaz de consulta jurídica se implementará en Fase 2.
        </p>
      </section>
    </div>
  );
}
