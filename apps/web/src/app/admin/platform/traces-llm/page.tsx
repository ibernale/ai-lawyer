"use client";

import { IframeEmbed } from "@/components/admin/IframeEmbed";

const LANGFUSE_URL = process.env.NEXT_PUBLIC_LANGFUSE_URL ?? "";

export default function TracesLlmPage() {
  return (
    <div className="flex flex-col h-full">
      <div className="mb-4">
        <h1 className="text-xl font-semibold text-gray-900">Traces LLM</h1>
        <p className="text-sm text-gray-500 mt-0.5">
          Trazas de invocaciones a modelos via Langfuse.
        </p>
      </div>
      <IframeEmbed
        src={LANGFUSE_URL}
        title="Langfuse"
        className="flex-1"
        envVarName="NEXT_PUBLIC_LANGFUSE_URL"
      />
    </div>
  );
}
