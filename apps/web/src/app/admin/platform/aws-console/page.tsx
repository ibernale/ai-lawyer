"use client";

import { useEffect, useState } from "react";
import { getHealth, type HealthResponse } from "@/lib/api";
import { AwsServiceCard } from "@/components/admin/AwsServiceCard";

type DepStatus = "healthy" | "degraded" | "unavailable" | "checking";

function StatusDot({ status }: { status: DepStatus }) {
  const colors: Record<DepStatus, string> = {
    healthy: "bg-green-500",
    degraded: "bg-yellow-500",
    unavailable: "bg-red-500",
    checking: "bg-gray-300 animate-pulse",
  };
  const labels: Record<DepStatus, string> = {
    healthy: "Activo",
    degraded: "Degradado",
    unavailable: "No disponible",
    checking: "Comprobando...",
  };
  return (
    <span className="flex items-center gap-1.5 text-xs text-gray-600">
      <span className={`w-2 h-2 rounded-full ${colors[status]}`} />
      {labels[status]}
    </span>
  );
}

function HealthCard({ name, status }: { name: string; status: DepStatus }) {
  return (
    <div className="bg-white border border-gray-200 rounded-lg p-4">
      <p className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-2">
        {name}
      </p>
      <StatusDot status={status} />
    </div>
  );
}

export default function AwsConsolePage() {
  const [health, setHealth] = useState<HealthResponse | null>(null);

  useEffect(() => {
    getHealth()
      .then(setHealth)
      .catch(() => null);
  }, []);

  function dep(key: string): DepStatus {
    if (!health) return "checking";
    const v = (health as unknown as Record<string, unknown>).deps_status as
      | Record<string, string>
      | undefined;
    if (!v) return "unavailable";
    const s = v[key];
    if (s === "healthy") return "healthy";
    if (s === "degraded") return "degraded";
    return "unavailable";
  }

  const apiStatus: DepStatus = !health
    ? "checking"
    : health.status === "healthy"
      ? "healthy"
      : health.status === "degraded"
        ? "degraded"
        : "unavailable";

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-xl font-semibold text-gray-900">
          Plataforma & AWS
        </h1>
        <p className="text-sm text-gray-500 mt-0.5">
          Estado de servicios de la plataforma y acceso federado a la consola
          AWS.
        </p>
      </div>

      {/* Inline health monitoring */}
      <section className="mb-8">
        <h2 className="text-sm font-semibold text-gray-700 mb-3">
          Estado de servicios
        </h2>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <HealthCard name="API" status={apiStatus} />
          <HealthCard name="Base de datos" status={dep("db")} />
          <HealthCard name="Qdrant (RAG)" status={dep("qdrant")} />
          <HealthCard name="Auth" status={dep("auth")} />
        </div>
      </section>

      {/* AWS federation */}
      <section>
        <h2 className="text-sm font-semibold text-gray-700 mb-1">
          Acceso federado a consola AWS
        </h2>
        <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded px-3 py-2 mb-4">
          Requiere IAM Identity Center configurado. En entorno local los botones
          &ldquo;Abrir en AWS&rdquo; no funcionarán.
        </p>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5 gap-4">
          <AwsServiceCard
            service="cloudwatch"
            name="CloudWatch"
            description="Dashboards de métricas, alarmas y logs de la infraestructura."
          />
          <AwsServiceCard
            service="xray"
            name="X-Ray"
            description="Service map y trazas distribuidas en AWS."
          />
          <AwsServiceCard
            service="agentcore"
            name="AgentCore Observability"
            description="Monitoring de agentes en Bedrock AgentCore."
          />
          <AwsServiceCard
            service="step-functions"
            name="Step Functions"
            description="Ejecuciones históricas de los pipelines de ingesta."
          />
          <AwsServiceCard
            service="bedrock"
            name="Bedrock"
            description="Logs y métricas de invocaciones a modelos de lenguaje."
          />
        </div>
      </section>
    </div>
  );
}
