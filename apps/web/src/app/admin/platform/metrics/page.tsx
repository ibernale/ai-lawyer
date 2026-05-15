"use client";

import { IframeEmbed } from "@/components/admin/IframeEmbed";

const GRAFANA_URL = process.env.NEXT_PUBLIC_GRAFANA_URL ?? "";

export default function MetricsPage() {
  return (
    <div className="flex flex-col h-full">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">Metrics</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            Dashboards de métricas via Grafana.
          </p>
        </div>
      </div>
      <IframeEmbed
        src={GRAFANA_URL ? `${GRAFANA_URL}?kiosk` : ""}
        title="Grafana"
        className="flex-1"
      />
    </div>
  );
}
