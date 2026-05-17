"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { listConsultations } from "@/lib/api";
import type { ConsultationSummary } from "@/lib/api";

const STATUS_DOT: Record<string, string> = {
  green: "bg-green-500",
  amber: "bg-amber-400",
  red: "bg-red-500",
  pending: "bg-gray-300",
};

export function RecentConsultations() {
  const [records, setRecords] = useState<ConsultationSummary[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    listConsultations({ limit: 5 })
      .then(setRecords)
      .catch(() => setRecords([]))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-8">
        <span className="h-5 w-5 animate-spin rounded-full border-2 border-brand-600 border-t-transparent" />
      </div>
    );
  }

  if (records.length === 0) {
    return (
      <p className="text-sm text-muted-foreground text-center py-6">
        Sin consultas todavía.{" "}
        <Link href="/consulta" className="text-brand-600 underline">
          Empieza aquí
        </Link>
      </p>
    );
  }

  return (
    <ul className="space-y-2">
      {records.map((r) => (
        <li key={r.trace_id}>
          <Link
            href={`/consulta?trace=${r.trace_id}`}
            className="flex items-start gap-3 rounded-md px-2 py-2 hover:bg-muted transition-colors group"
          >
            <span
              className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${STATUS_DOT[r.verification_status] ?? "bg-gray-300"}`}
              aria-label={r.verification_status}
            />
            <div className="min-w-0 flex-1">
              <p className="text-sm text-foreground truncate group-hover:text-brand-700">
                {r.query}
              </p>
              <p className="text-xs text-muted-foreground mt-0.5">
                {new Date(r.created_at).toLocaleString("es-ES", {
                  day: "2-digit",
                  month: "2-digit",
                  hour: "2-digit",
                  minute: "2-digit",
                })}
                {r.depth_used && (
                  <span className="ml-2 capitalize">{r.depth_used}</span>
                )}
              </p>
            </div>
          </Link>
        </li>
      ))}
    </ul>
  );
}
