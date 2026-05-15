"use client";

import Link from "next/link";
import { AwsServiceCard } from "@/components/admin/AwsServiceCard";

const IFRAME_TOOLS = [
  {
    href: "/admin/platform/metrics",
    name: "Grafana — Metrics",
    description: "Dashboards de métricas de sistema, agentes y RAG.",
    env: "NEXT_PUBLIC_GRAFANA_URL",
  },
  {
    href: "/admin/platform/traces-llm",
    name: "Langfuse — Traces LLM",
    description: "Trazas de invocaciones a modelos, prompts y evaluaciones.",
    env: "NEXT_PUBLIC_LANGFUSE_URL",
  },
  {
    href: "/admin/platform/traces-infra",
    name: "Jaeger — Traces Infra",
    description: "Trazas distribuidas de la infraestructura de la API.",
    env: "NEXT_PUBLIC_JAEGER_URL",
  },
  {
    href: "/admin/platform/pipelines",
    name: "Pipelines",
    description: "Estado de ejecuciones de Step Functions e ingesta.",
    env: null,
  },
];

export default function PlatformPage() {
  return (
    <div>
      <div className="mb-6">
        <h1 className="text-xl font-semibold text-gray-900">Platform</h1>
        <p className="text-sm text-gray-500 mt-1">
          Herramientas de observabilidad y acceso a la consola AWS.
        </p>
      </div>

      {/* Self-hosted tools — iframe pattern */}
      <section className="mb-8">
        <h2 className="text-sm font-semibold text-gray-700 mb-3 uppercase tracking-wide">
          Herramientas self-hosted
        </h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {IFRAME_TOOLS.map(({ href, name, description }) => (
            <Link
              key={href}
              href={href as never}
              className="bg-white border border-gray-200 rounded-lg p-4 hover:border-gray-400 hover:shadow-sm transition-all flex flex-col gap-2"
            >
              <div className="flex items-start justify-between gap-2">
                <h3 className="text-sm font-semibold text-gray-900">{name}</h3>
                <span className="shrink-0 text-[10px] font-medium uppercase tracking-wide bg-blue-50 text-blue-600 border border-blue-200 px-1.5 py-0.5 rounded">
                  iframe
                </span>
              </div>
              <p className="text-xs text-gray-500">{description}</p>
              <span className="mt-auto text-xs text-blue-600 font-medium">
                Ver detalles →
              </span>
            </Link>
          ))}
        </div>
      </section>

      {/* AWS native services — federation pattern */}
      <section>
        <h2 className="text-sm font-semibold text-gray-700 mb-1 uppercase tracking-wide">
          Servicios AWS
        </h2>
        <p className="text-xs text-gray-400 mb-3">
          Se abren en la consola AWS autenticada con tus credenciales de rol.
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
            description="Service map y trazas de la plataforma en AWS."
          />
          <AwsServiceCard
            service="agentcore"
            name="AgentCore"
            description="Observabilidad de los agentes en Bedrock AgentCore."
          />
          <AwsServiceCard
            service="step-functions"
            name="Step Functions"
            description="Ejecuciones de los pipelines de ingesta."
          />
          <AwsServiceCard
            service="bedrock"
            name="Bedrock"
            description="Logs de invocaciones a modelos de lenguaje."
          />
        </div>
      </section>
    </div>
  );
}
