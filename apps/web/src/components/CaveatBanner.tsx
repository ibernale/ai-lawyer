"use client";

import type { CitationMapping } from "@/lib/api";

/**
 * Reinforced caveat banner for all pages showing AI-generated legal responses.
 * Required by ADR 0028 — shown above every response until external expert validation
 * is completed (deferred to Fase 8).
 */

function hasCendojCitation(citations: CitationMapping[]): boolean {
  return citations.some(
    (c) =>
      c.source_id.startsWith("CENDOJ") ||
      c.source_id.includes("STS") ||
      c.source_id.includes("SAN") ||
      c.source_id.includes("SAP"),
  );
}

export function CaveatBanner({
  citations = [],
}: {
  citations?: CitationMapping[];
}) {
  const showCendoj = hasCendojCitation(citations);

  return (
    <div className="space-y-2">
      {/* Primary MVP caveat */}
      <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3">
        <p className="text-xs font-semibold text-red-900 leading-snug">
          Sistema en MVP fase 7 &mdash; sin validación por jurista cualificado
          externo.
        </p>
        <p className="mt-1 text-xs text-red-800 leading-relaxed">
          Cada respuesta es un <strong>BORRADOR</strong> que requiere
          verificación humana cualificada antes de cualquier uso operativo. Las
          citas jurisprudenciales (sentencias, autos) son especialmente sensibles
          y deben verificarse contra la fuente original. No constituye
          asesoramiento legal.
        </p>
      </div>

      {/* CENDOJ-specific warning (amber) */}
      {showCendoj && (
        <div className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3">
          <p className="text-xs font-semibold text-amber-900">
            ⚠ Citas a jurisprudencia recuperadas en modo desarrollo
          </p>
          <p className="mt-0.5 text-xs text-amber-800">
            Acceso rate-limited a CENDOJ sin autorización CGPJ formal para uso
            productivo. Verificar cada sentencia referenciada en la fuente
            oficial antes de citar.
          </p>
        </div>
      )}
    </div>
  );
}

/** Compact variant for the global layout footer area — no citations context needed. */
export function CaveatFooterNote() {
  return (
    <p className="text-[11px] text-muted-foreground px-4 py-2 border-t border-border bg-muted/20 leading-relaxed">
      <strong>AVISO:</strong> Respuestas generadas por IA. MVP fase 7, sin
      validación experta externa. Borrador — requiere verificación jurídica
      cualificada.
    </p>
  );
}
