import Link from "next/link";

const DOCS = [
  {
    title: "Privacidad y tratamiento de datos",
    href: "/legal/privacy",
    description:
      "Qué datos se procesan, base legal, retención, Anthropic como subencargado y cómo ejercer derechos.",
  },
  {
    title: "Declaración sobre uso de IA",
    href: "/legal/ai-disclosure",
    description:
      "Qué hace y no hace el sistema, obligaciones del usuario, limitaciones conocidas del modelo.",
  },
  {
    title: "Terceros y flujo de datos",
    href: "/legal/third-parties",
    description:
      "Anthropic API, Qdrant, HuggingFace, Jaeger y GitHub: roles, datos transferidos y garantías.",
  },
  {
    title: "Limitaciones y advertencias",
    href: "/legal/limitations",
    description:
      "Alucinaciones, cobertura normativa limitada, dataset no validado por expertos, ausencia de jurisprudencia.",
  },
];

export default function LegalPage() {
  return (
    <div className="mx-auto max-w-2xl px-4 py-10 space-y-8">
      <header>
        <h1 className="text-2xl font-bold tracking-tight">Información legal</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          lex-agents es un sistema de apoyo interno en fase MVP. Todo el
          contenido generado es un borrador asistido por IA y requiere
          validación por un jurista cualificado antes de cualquier uso externo o
          toma de decisiones.
        </p>
      </header>

      <div className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
        <strong>Sistema en fase MVP.</strong> El dataset y los prompts no han
        sido validados por un experto humano.{" "}
        <code>expert_reviewed: false</code> en todos los casos del dataset de
        evaluación. No usar como ground truth jurídico.
      </div>

      <nav className="space-y-3">
        {DOCS.map((doc) => (
          <a
            key={doc.href}
            href={doc.href}
            className="block rounded-lg border border-border bg-background p-4 hover:bg-muted transition-colors"
          >
            <p className="font-medium text-sm">{doc.title}</p>
            <p className="mt-1 text-xs text-muted-foreground">
              {doc.description}
            </p>
          </a>
        ))}
      </nav>

      <p className="text-xs text-muted-foreground">
        <Link href="/consulta" className="underline hover:text-foreground">
          ← Volver a la consulta
        </Link>
      </p>
    </div>
  );
}
