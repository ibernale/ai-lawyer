"use client";

import { useState } from "react";
import { getFederationUrl } from "@/lib/api";
import type { AwsService } from "@/lib/api";

interface AwsServiceCardProps {
  service: AwsService;
  name: string;
  description: string;
  dashboard?: string;
  resourceId?: string;
}

export function AwsServiceCard({
  service,
  name,
  description,
  dashboard,
  resourceId,
}: AwsServiceCardProps) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleOpen() {
    setLoading(true);
    setError("");
    try {
      const { url } = await getFederationUrl(service, { dashboard, resourceId });
      window.open(url, "_blank", "noopener,noreferrer");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al generar URL");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="bg-white border border-gray-200 rounded-lg p-4 flex flex-col gap-3 hover:border-gray-300 transition-colors">
      <div className="flex items-start justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold text-gray-900">{name}</h3>
          <p className="text-xs text-gray-500 mt-0.5">{description}</p>
        </div>
        <span className="shrink-0 text-[10px] font-medium uppercase tracking-wide bg-orange-50 text-orange-600 border border-orange-200 px-1.5 py-0.5 rounded">
          AWS
        </span>
      </div>

      {error && (
        <p className="text-xs text-red-600 bg-red-50 border border-red-200 rounded px-2 py-1">
          {error}
        </p>
      )}

      <button
        onClick={handleOpen}
        disabled={loading}
        className="mt-auto w-full px-3 py-1.5 text-xs font-medium bg-gray-900 text-white rounded hover:bg-gray-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-1.5"
      >
        {loading ? (
          <>
            <span className="w-3 h-3 border-2 border-white border-t-transparent rounded-full animate-spin" />
            Generando acceso...
          </>
        ) : (
          <>
            Abrir en AWS
            <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
            </svg>
          </>
        )}
      </button>

      <p className="text-[10px] text-gray-400 text-center">
        Se abre en la consola AWS autenticada
      </p>
    </div>
  );
}
