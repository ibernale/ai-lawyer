# ADR 0046 — CDK TypeScript para infraestructura AWS

**Estado:** Accepted
**Fecha:** 2026-05-13
**Decisores:** Ignacio Bernal (Santander)
**ADRs relacionados:** 0043 (CDK deployment strategy — AMENDED)
**Sub-fases afectadas:** 9.1 – 9.5

---

## Contexto

ADR 0043 decidió usar AWS CDK v2 Python para la infraestructura, argumentando
que compartir lenguaje con la aplicación reduciría la fricción del equipo. Sin
embargo, al comenzar a diseñar la estructura real de `infra/cdk/` en Fase 9.1,
se identificaron razones técnicas suficientemente fuertes para cambiar a
TypeScript. Este ADR documenta la decisión y enmienda ADR 0043.

---

## Decisión

**Usar AWS CDK v2 TypeScript** para todo el código de infraestructura en
`infra/cdk/`. El código de aplicación Python en `packages/` y `apps/` no
se modifica.

---

## Justificación

### 1. CDK es TypeScript-first en documentación y ejemplos

La documentación oficial de AWS CDK, todos los ejemplos en aws-samples, los
CDK L3 constructs publicados en Constructs Hub, y la propia CLI de CDK están
escritos y pensados en TypeScript. Usar Python CDK implica traducir ejemplos
constantemente y encontrar que los tipos de algunas propiedades no están
completamente tipados o tienen notas como "generated from TypeScript".

### 2. Ecosistema de herramientas IaC es TS-first

Las herramientas más usadas en el ecosistema CDK asumen TypeScript:

| Herramienta | TS | Python |
|---|---|---|
| cdk-nag (Compliance checks) | ✅ Nativo | ⚠️ Port, lag en actualizaciones |
| projen (Project scaffolding) | ✅ Nativo | ⚠️ Soporte parcial |
| CDK Constructs Hub | ✅ Publicados en TS | Bindings generados |
| CDK testing (`Template.fromStack`) | ✅ Jest + `@aws-cdk/assertions` | pytest |
| CDK Pipelines | ✅ TS first | ⚠️ Menos ejemplos |

### 3. Mejor inferencia de tipos para props CDK

Los tipos CDK como `BucketProps`, `VpcProps`, `CfnRole.PolicyDocumentProperty`
son objetos anidados complejos. TypeScript da autocompletion y errores en
tiempo de compilación. Python equivale a `dict[str, Any]` con decoradores
de dataclass que el IDE no resuelve igual de bien.

Ejemplo concreto: una política S3 de Object Lock en Python requiere consultar
la documentación para cada campo. En TypeScript, `@aws-cdk/aws-s3` proporciona
`ObjectLockRetention.compliance(Duration.days(2555))` con tipado completo.

### 4. Separación limpia de workspaces — no hay acoplamiento de lenguaje

`infra/cdk/` es un pnpm workspace independiente con su propio `package.json`,
`tsconfig.json` y `jest.config.ts`. No comparte código con `packages/` Python.
Los ingenieros que trabajan en CDK no necesitan conocer la app Python y
viceversa. El argumento "mismo lenguaje que la app" pierde peso cuando el
workspace es completamente independiente.

### 5. El equipo DevOps/Platform ya usa Node/TypeScript

El repo ya tiene `apps/web` en TypeScript/Next.js con pnpm como package manager.
El CI ya ejecuta `tsc --noEmit`, `eslint`, y `jest` para TypeScript.
Añadir `infra/cdk/` como workspace TypeScript reutiliza el toolchain existente
sin instalar Python adicional en el pipeline de infra.

---

## Alternativas consideradas

### Mantener CDK Python (ADR 0043)

**Pros:**
- Mismo lenguaje que `packages/` Python
- Sin setup de Node en el entorno de un desarrollador Python puro

**Contras:**
- Documentación y ejemplos requieren traducción constante
- cdk-nag tiene lag en actualizaciones del port Python
- Tipado inferior para props complejas
- El CI ya tiene Node; no hay ahorro real en configuración

**Veredicto:** Descartado. El coste de traducción continua supera el beneficio
de uniformidad de lenguaje, especialmente dado que el workspace es independiente.

### Terraform (HCL)

Descartado en ADR 0043 por las razones allí documentadas. No reconsiderado.

---

## Trade-offs y consecuencias

| Trade-off | Impacto |
|---|---|
| ADR 0043 Python → TS | ADR 0043 queda enmendado. Los stacks CDK en Fase 9.1+ usan TypeScript. |
| Tests con Jest no pytest | El CI necesita un job `cdk-test` que corra `jest` dentro de `infra/cdk/`. No afecta a los tests Python existentes. |
| Node.js en imagen CI de infra | La imagen `ubuntu-latest` de GitHub Actions ya tiene Node 20. `npm install -g aws-cdk` o `pnpm exec cdk`. |
| Curva de aprendizaje | Mínima — los CDK constructs y la lógica de stacks son similares en ambos lenguajes. Los desarrolladores Python del equipo necesitan TypeScript básico. |

### Cambios en el repositorio

- `infra/cdk/` creado como pnpm workspace con TypeScript.
- `package.json` root: `"infra/cdk"` añadido a workspaces.
- `Makefile`: targets `cdk-synth`, `cdk-diff`, `cdk-deploy-dev`, `cdk-nag`.
- ADR 0043 nota al pie: "IaC language: ver ADR 0046 (TypeScript)."

### Sin impacto

- `packages/` Python: sin cambios.
- `apps/api/` FastAPI: sin cambios.
- `apps/web/` Next.js: sin cambios.
- Procesos de evaluación, ingesta, y test Python: sin cambios.
