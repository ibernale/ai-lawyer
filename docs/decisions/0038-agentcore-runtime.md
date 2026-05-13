# ADR 0038 — AgentCore como runtime de agentes en AWS

**Estado:** Accepted  
**Fecha:** 2026-05-13  
**Decisores:** Ignacio Bernal (Santander)  
**ADRs relacionados:** 0001 (stack), 0012 (PMJ), 0013 (memoria), 0018 (BaseSpecialist),
0022 (memory impl.), 0039 (Bedrock), 0043 (CDK)  
**Sub-fases afectadas:** 9.2 – 9.4

---

## Contexto

`packages/agents/` contiene el orquestador PMJ (Planner/Maker/Judge), los especialistas,
el router y el coordinador cross-jurisdiction. En producción local corren como código Python
dentro del proceso FastAPI. Para el despliegue AWS necesitamos:

1. **Session isolation:** cada consulta jurídica es independiente; sin riesgo de leak
   de contexto entre usuarios concurrentes.
2. **Long-running support:** consultas complejas (depth=deep, múltiples especialistas
   en paralelo) pueden tardar 30-120 segundos; no toleran timeout de Lambda (15 min
   máximo, pero cold-start costoso).
3. **Memory persistente gestionada:** la memoria procedimental y semántica de ADR 0022
   requiere storage fuera del proceso para escalar horizontalmente.
4. **Tool exposure estandarizada:** el Gateway MCP para exponer herramientas internas
   (search_rag, verify_citations, kill_switch_check, etc.) debe estar auditado y con
   auth por llamada.
5. **Managed infrastructure:** para banca con DORA, infra gestionada por proveedor
   cualificado reduce el alcance del control interno de seguridad.

---

## Decisión

### Adoptar AWS AgentCore como runtime de los agentes

AWS AgentCore es el servicio de hosting para agentes AI de AWS, disponible en GA en
eu-central-1. Es framework-agnostic: el código Python existente de `packages/agents/`
se adapta con cambios superficiales en el wrapper de entrada.

### Componentes adoptados en Fase 9

#### AgentCore Runtime
- **Qué hace:** hospeda el código de agente en microVMs aisladas por sesión. Cada
  invocación obtiene un entorno limpio. Soporta sesiones long-running (streaming).
- **Adopción:** `OrchestratorV2` y los especialistas se exponen via `@app.entrypoint`.
  El wrapper recibe el `ConsultRequest`, llama al código existente, devuelve `ConsultResponse`.
  La lógica de Planner/Maker/Judge permanece intacta.
- **CDK deploy:** construct `agentcore.AgentCoreRuntime` en `AgentsStack`.
- **Canary deployments:** AgentCore Runtime soporta deployment con traffic split
  (e.g., 90%/10% entre versiones de prompt). Se usa para A/B testing de nuevas versiones
  de prompts de especialistas (complementa ADR 0021).

#### AgentCore Memory
- **Qué hace:** almacenamiento persistente de memoria procedural y semántica, gestionado
  por AWS. Reemplaza el SQLite local de `packages/memory/` (ADR 0022).
- **Memoria procedural:** plantillas de análisis, atajos de routing, formatos de citación.
  Continúa siendo de solo lectura en runtime (human-only writes via PR, ADR 0013).
  Los seeds se importan desde `docs/knowledge/` al inicializar el entorno.
- **Memoria semántica:** resúmenes de regulaciones, patrones detectados, índices de
  conceptos. Gestionada y accesible cross-session.
- **Memoria episódica:** continúa **DESACTIVADA** per ADR 0013 (riesgo RGPD no resuelto).

#### AgentCore Gateway (MCP)
- **Qué hace:** expone las herramientas internas como MCP tools con auth por llamada
  y audit automático. Los agentes llaman a las tools via Gateway en lugar de invocaciones
  directas en proceso.
- **Tools expuestas via Gateway:**
  ```
  search_rag              → packages/rag/ HybridRetriever
  verify_citations        → packages/verifier/ CitationVerifier
  get_audit_sample        → packages/audit/ AuditTrailManager
  query_rewriter          → packages/rag/ LegalQueryRewriter
  kill_switch_check       → packages/admin/ SystemStateManager
  get_cost_estimate       → packages/finops/
  ```
- **Auth:** IAM roles por tool; cada agente solo puede llamar a las tools de su scope.
- **Audit:** cada llamada a tool queda registrada en CloudTrail via Gateway.

#### AgentCore Observability
- **Qué hace:** captura traces AWS-nativas del Runtime → CloudWatch Logs Insights.
- **Integración con stack existente:** los traces AgentCore se agregan en CloudWatch;
  Langfuse sigue siendo el hub para prompt management, replay y evaluaciones (ADR 0030).
  No se sustituye Langfuse; AgentCore Observability es complementario para la capa AWS.
- **OTel bridge:** los spans OTel existentes en `packages/agents/` se propagan al
  AgentCore Observability context via W3C trace context headers.

### Componentes AgentCore NO adoptados en Fase 9

| Componente | Decisión | Razón |
|---|---|---|
| **AgentCore Identity** | Placeholder Fase 10 | Requiere SSO Santander (Azure AD). No disponible en Fase 9. |
| **AgentCore Evaluations** | No adoptado | Mantenemos nuestro eval framework (ADR 0009/0014/0020). LeMAJ y adversarial evals son específicos de dominio jurídico; AgentCore Evaluations es genérico. |

---

## Justificación frente a alternativas

### ECS Fargate puro
Actualmente el API y la web corren en ECS Fargate. ¿Por qué no los agentes también?

| Criterio | ECS Fargate puro | AgentCore Runtime |
|---|---|---|
| Session isolation | Manual (código de app) | Nativa (microVM por sesión) |
| Memory persistente | Self-managed (SQLite → Aurora) | Gestionada por AWS |
| MCP Gateway con audit | Self-managed | Built-in |
| A/B testing de prompts | CI/CD manual | Canary nativo |
| Overhead operacional | Alto (ECS task definitions, scaling policies, healthchecks) | Bajo (CDK construct) |
| DORA infra gestionada | Parcialmente (ECS gestionado, pero lógica de agente expuesta) | AWS gestiona la capa de runtime |

**ECS Fargate seguimos usándolo** para la API FastAPI y la web Next.js, que son servicios
web estándar sin requisitos de session isolation de agente.

### Bedrock Agents (legacy / "classic")
Bedrock Agents exige Lambda + Knowledge Bases hardcodeadas. Nuestra arquitectura tiene:
- LegalChunker personalizado (incompatible con KB chunking estándar sin Custom Chunking).
- PMJ pattern en Python puro (no encaja en el modelo de Action Groups de Bedrock Agents).
- Necesidad de múltiples especialistas en paralelo (el modelo Bedrock Agents es secuencial).

AgentCore es el sucesor de Bedrock Agents, framework-agnostic. La migración futura desde
AgentCore es más limpia que desde Bedrock Agents.

### Self-managed Strands / LangGraph en ECS
Strands (AWS) y LangGraph (LangChain) son frameworks de orquestación de agentes que se
desplegarían en ECS. El código sería similar al actual pero:
- Requireen gestionar la infra subyacente (ECS tasks, scaling, isolation).
- No proporcionan Memory gestionada ni Gateway MCP con audit.
- Para banca con DORA, preferimos que AWS opere la capa de runtime y nosotros validemos
  el comportamiento del agente. Reduce el alcance del control interno de seguridad.

---

## Modelo de ejecución

```
ConsultRequest (API ECS)
    │
    ▼
AgentCore Runtime (eu-central-1)
    ├── microVM: OrchestratorV2.run()
    │       ├── Planner.plan()
    │       ├── Specialist.run_async()  ─── AgentCore Gateway ──► search_rag (Lambda VPC)
    │       │                                                   ──► verify_citations (Lambda VPC)
    │       ├── Judge.judge()
    │       └── Verifier.run()
    │
    ├── AgentCore Memory (procedural + semantic)
    └── AgentCore Observability → CloudWatch
                                → Langfuse (via OTel bridge)
```

---

## Trade-offs y consecuencias

| Trade-off | Impacto |
|---|---|
| Vendor lock-in en AgentCore | Exit strategy: `@app.entrypoint` es un wrapper delgado; el código del agente vuelve a ECS Fargate en <1 sprint. Ver ADR 0044. |
| Cold start AgentCore (~500 ms) | Aceptable; consultas jurídicas tardan segundos. Mitigable con provisioned concurrency en Fase 10 si SLA lo exige. |
| Coste AgentCore por invocación | $50–200/mes en dev. Escalar se paga por uso, no por instancia 24/7. Favorable frente a ECS task always-on. |
| Código Python actual sin cambios | Solo el entrypoint wrapper cambia. Tests existentes de packages/agents/ siguen válidos. |
| Memoria episódica sigue DISABLED | ADR 0013 vigente. AgentCore Memory no cambia la política; cambia la implementación del almacenamiento. |

### Sub-fases afectadas
- **9.2:** escribir `AgentsStack` CDK + wrapper `@app.entrypoint` para OrchestratorV2.
- **9.3:** adaptar `BedrockAnthropicClient` para llamadas dentro de AgentCore Runtime.
  Migrar `packages/memory/` → AgentCore Memory.
- **9.4:** configurar AgentCore Gateway con las tools internas.
