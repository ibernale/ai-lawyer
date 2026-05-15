"use client";

import { AwsServiceCard } from "@/components/admin/AwsServiceCard";

export default function AwsConsolePage() {
  return (
    <div>
      <div className="mb-6">
        <h1 className="text-xl font-semibold text-gray-900">AWS Console</h1>
        <p className="text-sm text-gray-500 mt-0.5">
          Acceso federado a servicios AWS nativos. El rol asignado determina
          los permisos en cada servicio.
        </p>
      </div>

      <div className="mb-4 bg-amber-50 border border-amber-200 rounded-lg px-4 py-3 text-xs text-amber-700">
        <strong>Nota:</strong> Al hacer clic en "Abrir en AWS" se generará un
        acceso temporal (~15 min) en la consola AWS. El acceso se registra en
        el audit trail.
      </div>

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
    </div>
  );
}
