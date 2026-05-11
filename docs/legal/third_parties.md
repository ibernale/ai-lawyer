# Terceros y subprocesadores — lex-agents

> **Versión:** 0.1.0 · **Fecha:** 2026-05-11

Este documento describe todos los servicios de terceros utilizados por
lex-agents y qué información les llega.

---

## 1. Anthropic, Inc. — API de IA generativa

| Atributo | Detalle |
|----------|---------|
| **Servicio** | Anthropic API |
| **Modelos usados** | `claude-opus-4-7` (routing, specialist), `claude-haiku-4-5-20251001` (verificador, rewriter) |
| **Datos enviados** | Texto de la consulta jurídica del usuario + fragmentos de normas recuperados por el motor RAG (hasta ~10 fragmentos de ~500 tokens cada uno). No se envían datos personales de clientes de forma intencional. |
| **Datos NO enviados** | Credenciales, datos de negocio internos, PII de clientes, historial completo de consultas. |
| **Propósito del envío** | Generación de respuesta jurídica, extracción de claims, verificación de citas, reformulación de consulta. |
| **Ubicación** | Servidores Anthropic (EE.UU.). Transferencia cubierta por SCCs según términos de Anthropic. |
| **Retención por Anthropic** | Según política de Anthropic. Para evitar retención, contratar **Zero Data Retention (ZDR)**. |
| **Enlace** | https://www.anthropic.com/privacy |

---

## 2. Qdrant — Base de datos vectorial (local)

| Atributo | Detalle |
|----------|---------|
| **Servicio** | Qdrant OSS v1.11.0, self-hosted en Docker |
| **Datos almacenados** | Embeddings de fragmentos de normas públicas (BOE, EUR-Lex) + metadatos (fuente, artículo, fecha) |
| **Datos NO almacenados** | Consultas de usuarios, respuestas generadas, datos personales |
| **Ubicación** | Exclusivamente local (volumen Docker en el host del desarrollador) |
| **Tercero externo** | No. Ningún dato sale del host. |

---

## 3. HuggingFace — Modelos de embedding y reranking (local)

| Atributo | Detalle |
|----------|---------|
| **Modelos** | `BAAI/bge-m3` (embeddings), `BAAI/bge-reranker-v2-m3` (reranking) |
| **Uso** | Carga local al iniciar el servicio API. Los modelos se descargan de HuggingFace Hub al primer inicio. |
| **Datos enviados a HuggingFace** | Solo la descarga inicial del modelo (pesos). Ningún texto de consulta o norma se envía a HuggingFace en tiempo de ejecución. |
| **Inferencia** | Local, en CPU/GPU del host. |

---

## 4. Jaeger — Trazas distribuidas (local)

| Atributo | Detalle |
|----------|---------|
| **Servicio** | Jaeger all-in-one v1.59, self-hosted en Docker |
| **Datos almacenados** | Spans de ejecución (latencias, nombres de operación, atributos de OTel). No contienen el texto de las consultas. |
| **Ubicación** | Exclusivamente local (memoria/volumen Docker) |
| **Acceso** | Solo desde el host (`http://localhost:16686`) |

---

## 5. GitHub — Control de versiones y CI

| Atributo | Detalle |
|----------|---------|
| **Servicio** | GitHub (repositorio privado `ibernale/ai-lawyer`) |
| **Datos almacenados** | Código fuente, configuración, dataset de evaluación (normas públicas). No contiene datos personales ni secretos (protegidos por `.gitignore` y `detect-secrets`). |
| **CI/CD** | GitHub Actions ejecuta tests, linting, evals y escaneos de seguridad. Los secrets de CI (`ANTHROPIC_API_KEY`) se almacenan cifrados en GitHub Secrets. |

---

## 6. Resumen de flujo de datos

```
Usuario
  │ query (texto libre)
  ▼
API (local:8000)
  │ query + contexto RAG
  ▼
Anthropic API ──────── (único dato que sale del host)
  │ respuesta generada
  ▼
Verificador (local)
  ▼
SQLite local ─── historial consultas
  ▼
Usuario (respuesta + citas)
```

Todo lo demás (Qdrant, Jaeger, SQLite, modelos BGE) permanece en el host local.
