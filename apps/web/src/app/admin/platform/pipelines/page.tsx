"use client";

import { AwsServiceCard } from "@/components/admin/AwsServiceCard";

export default function PipelinesPage() {
  return (
    <div>
      <div className="mb-6">
        <h1 className="text-xl font-semibold text-gray-900">Pipelines</h1>
        <p className="text-sm text-gray-500 mt-0.5">
          Estado de ejecuciones de ingesta gestionadas por AWS Step Functions.
        </p>
      </div>
      <div className="max-w-sm">
        <AwsServiceCard
          service="step-functions"
          name="Step Functions"
          description="Ejecuciones de los pipelines de ingesta BOE y EUR-Lex."
        />
      </div>
    </div>
  );
}
