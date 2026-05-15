"use client";

import { IframeEmbed } from "@/components/admin/IframeEmbed";

const JAEGER_URL = process.env.NEXT_PUBLIC_JAEGER_URL ?? "";

export default function TracesInfraPage() {
  return (
    <div className="flex flex-col h-full">
      <div className="mb-4">
        <h1 className="text-xl font-semibold text-gray-900">Traces Infra</h1>
        <p className="text-sm text-gray-500 mt-0.5">
          Trazas distribuidas de la infraestructura via Jaeger.
        </p>
      </div>
      <IframeEmbed src={JAEGER_URL} title="Jaeger" className="flex-1" />
    </div>
  );
}
