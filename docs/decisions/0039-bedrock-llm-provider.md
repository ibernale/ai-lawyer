# ADR 0039 — Bedrock como provider LLM primario; Anthropic API como fallback

**Estado:** Accepted  
**Fecha:** 2026-05-13  
**Decisores:** Ignacio Bernal (Santander)  
**ADRs relacionados:** 0001 (stack), 0003 (RAG), 0029 (FinOps), 0036 (regiones),
0038 (AgentCore), 0044 (DORA)  
**Sub-fases afectadas:** 9.2 – 9.3

---

## Contexto

En dev local, todos los agentes llaman a `AnthropicClientWrapper` que apunta directamente
a `api.anthropic.com`. Para el despliegue AWS hay dos motivaciones para cambiar el provider:

1. **Data residency:** las llamadas a `api.anthropic.com` salen de la VPC hacia Internet
   con destino a servidores de Anthropic en US. En DORA y bajo las directrices BdE, los
   datos de clientes en un prompt jurídico (names, case details, regulatory questions) no
   deben procesarse fuera del EEA sin garantías contractuales formales.

2. **Postura de seguridad:** `AnthropicClientWrapper` usa una API key de larga duración
   almacenada en `.env`. En AWS, el patrón IAM + Bedrock elimina las API keys de larga
   duración y sustituye por roles IAM de corta duración con audit nativo en CloudTrail.

Amazon Bedrock hospeda los modelos Claude de Anthropic en regiones AWS, incluyendo
eu-central-1. Las llamadas no salen del EEA. Anthropic y AWS comparten acuerdo de servicio
que cubre el procesamiento en Bedrock.

---

## Decisión

### Bedrock como provider primario en AWS

Todas las llamadas LLM en el entorno AWS (`workloads-dev`, `workloads-pre`, `workloads-pro`)
van a Amazon Bedrock por defecto.

Anthropic API directa (`api.anthropic.com`) queda como:
- **Provider en dev local** (docker-compose, desarrolladores desde su máquina).
- **Fallback de emergencia** en AWS si Bedrock tiene incidencia.
- Configurable via variable de entorno `LLM_PROVIDER=bedrock|anthropic`.

### Implementación: `BedrockAnthropicClient`

Nuevo cliente en `packages/shared/src/lex_agents_shared/bedrock_client.py` que implementa
la misma interfaz pública que `AnthropicClientWrapper`:

```python
class BedrockAnthropicClient:
    """Bedrock Converse API wrapper — misma interfaz que AnthropicClientWrapper."""

    def messages_create(self, **kwargs: Any) -> anthropic.types.Message:
        """Llama a Bedrock Converse API y devuelve respuesta compatible."""

    @property
    def circuit_state(self) -> str:
        """closed | open | half_open"""
```

**Implementación técnica:**
- Usa `boto3` + `bedrock-runtime` Converse API (no el cliente legacy `invoke_model`).
- La Converse API es la API unificada de Bedrock que acepta el mismo formato de mensajes
  que la Anthropic Messages API. La adaptación de `kwargs` es mínima.
- Mantiene el circuit-breaker y retry con backoff exponencial del wrapper original.
- Auth: boto3 usa automáticamente el rol IAM del task ECS / AgentCore Runtime (sin API keys).
- Todos los callers (`OrchestratorV2`, `LegalPlanner`, `LegalJudge`, especialistas,
  `Contextualizer`, `CitationVerifierLLM`, `QueryRewriter`) llaman a la misma interfaz sin cambios.

**Selección dinámica de cliente** en `packages/shared/src/lex_agents_shared/client_factory.py`:
```python
def get_llm_client(settings: Settings) -> AnthropicClientWrapper | BedrockAnthropicClient:
    if settings.llm_provider == "bedrock":
        return BedrockAnthropicClient(region=settings.aws_region)
    return AnthropicClientWrapper(api_key=settings.anthropic_api_key.get_secret_value())
```

### Modelos en Bedrock

Los mismos modelos usados en local, con sus IDs de Bedrock:

| Uso | Modelo local | ID Bedrock | Notas |
|---|---|---|---|
| Planner, Judge, razonamiento jurídico | `claude-opus-4-7` | `anthropic.claude-opus-4-7-v1:0` | |
| Makers especialistas | `claude-sonnet-4-6` | `anthropic.claude-sonnet-4-6-v1:0` | |
| Contextualizer, Verifier LLM, Query Rewriter, Reranker fallback | `claude-haiku-4-5` | `anthropic.claude-haiku-4-5-20251001-v1:0` | |

Los model IDs se centralizan en `packages/shared/src/lex_agents_shared/models.py` con
constantes por provider:
```python
BEDROCK_OPUS    = "anthropic.claude-opus-4-7-v1:0"
BEDROCK_SONNET  = "anthropic.claude-sonnet-4-6-v1:0"
BEDROCK_HAIKU   = "anthropic.claude-haiku-4-5-20251001-v1:0"
ANTHROPIC_OPUS  = "claude-opus-4-7"
ANTHROPIC_SONNET = "claude-sonnet-4-6"
ANTHROPIC_HAIKU  = "claude-haiku-4-5-20251001"
```

### Prompt caching en Bedrock

Bedrock soporta prompt caching con descuento del ~90% en tokens cacheados. Se aplica al
mismo patrón que en local (ADR 0003):
- El contexto RAG se marca como cacheable cuando supera 1024 tokens.
- El system prompt de cada especialista se cachea entre invocaciones del mismo agente
  dentro de una sesión AgentCore.
- El `BedrockAnthropicClient` pasa `cache_control` blocks via la Converse API.

### Cross-region inference

Si eu-central-1 está congestionado para Claude Opus (latencia p99 > 10s):
- Activar **Bedrock cross-region inference** que puede enrutar a eu-west-1 o, en último
  caso, us-east-1.
- **Restricción de data residency:** el cross-region a US solo se activa para llamadas
  sin datos de cliente en el contexto (e.g., razonamiento auxiliar interno del Planner
  sobre estructura de la consulta, no sobre el contenido de documentos o datos del usuario).
- Implementación: `InferenceProfileArn` en la Converse API request cuando
  `settings.bedrock_cross_region_enabled = True`.
- Esta restricción se impone a nivel de configuración y se audita via CloudTrail.

### Cost tracking

`packages/finops/` (ADR 0029) integra con **Bedrock Usage & Cost API** en AWS:
- Métricas: `InputTokens`, `OutputTokens`, `CacheReadTokens`, `CacheWriteTokens` por modelo.
- Reemplaza la estimación manual de tokens del `AnthropicClientWrapper.messages_create()`.
- La tabla `anthropic_usage_hourly` en Aurora (ADR 0042) pasa a llamarse
  `llm_usage_hourly` con columna `provider` para soportar ambos providers.
- Alertas existentes de cost spike (ADR 0029) se mantienen; la fuente de datos cambia.

---

## Justificación

| Criterio | Bedrock | Anthropic API directa |
|---|---|---|
| Data residency EEA | ✅ Datos en eu-central-1 | ⚠️ Requiere verificación contractual |
| Auth | ✅ IAM roles (sin keys largas) | ⚠️ API key larga duración |
| CloudTrail audit | ✅ Nativo en cada llamada | ❌ No disponible |
| AgentCore integración | ✅ Nativa | ❌ Llamada externa |
| Prompt caching | ✅ Mismo comportamiento | ✅ Mismo comportamiento |
| Modelos disponibles | ✅ Opus/Sonnet/Haiku | ✅ Opus/Sonnet/Haiku |
| Pricing | = mismo que Anthropic | = mismo que Bedrock |
| Disponibilidad dev local | ❌ Requiere AWS creds | ✅ Solo API key |

La combinación Bedrock (producción) + Anthropic API (local) optimiza en ambos entornos.

---

## Alternativas consideradas

### Bedrock solo (sin fallback Anthropic API)
Rechazada para Fase 9. Los desarrolladores en local necesitan iterar rápido sin configurar
credenciales AWS. El fallback `LLM_PROVIDER=anthropic` en local mantiene la experiencia
de desarrollo sin cambios.

### Azure OpenAI / GPT-4
Rechazada. Los agentes están calibrados para Claude (razonamiento jurídico, prompt caching,
estilos de output). Cambiar de modelo base requeriría re-evaluar todo el golden dataset.
Fuera del scope de Fase 9.

---

## Trade-offs y consecuencias

| Trade-off | Impacto |
|---|---|
| `BedrockAnthropicClient` nuevo código | ~200 líneas en packages/shared. Tests de equivalencia contra Anthropic API en CI. |
| Bedrock Converse API vs Messages API | Conversión de `system` prompt y `messages` es directa; `tool_use` tiene formato ligeramente distinto — wrapper lo abstrae. |
| IAM roles en ECS/AgentCore | Simplifica seguridad (sin Secrets Manager para LLM key) pero requiere configurar task roles CDK. |
| Cross-region inference data residency | Restricción operacional: solo para llamadas sin datos de cliente. Política documentada y auditable via CloudTrail. |
