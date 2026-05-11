# Política de privacidad — lex-agents MVP

> **Ámbito:** Uso interno en entorno de desarrollo. No desplegado en producción
> ni accesible fuera de la red local del desarrollador.
> **Fecha:** 2026-05-11 · **Versión:** 0.1.0

---

## 1. Responsable del tratamiento

Uso interno por equipos de desarrollo del Grupo Santander. No hay un
responsable formal designado hasta que el sistema salga del entorno MVP.

---

## 2. Datos que se procesan

| Categoría                  | Dato                                                               | Dónde                                  | Retención                                  |
| -------------------------- | ------------------------------------------------------------------ | -------------------------------------- | ------------------------------------------ |
| Consultas jurídicas        | Texto de la query del usuario                                      | SQLite local (`data/consultations.db`) | Manual; sin purga automática en MVP        |
| Respuestas generadas       | Texto completo de la respuesta + citas                             | SQLite local                           | Ídem                                       |
| Trazas de ejecución        | `trace_id`, latencia, modelo, coste estimado                       | SQLite local                           | Ídem                                       |
| Logs de aplicación         | Eventos de sistema (nivel INFO+); PII redactado antes de escritura | stdout / fichero local                 | Rotación por el sistema operativo del host |
| Feedback de usuario        | Tipo de incidencia + descripción + extracto de respuesta           | `evals/feedback/*.json`                | Manual                                     |
| Datos enviados a Anthropic | Query del usuario + fragmentos de normas recuperados de Qdrant     | API Anthropic (ver §4)                 | Según política de Anthropic                |

**No se procesan** datos especialmente sensibles (salud, ideología, biometría)
ni datos de clientes de Santander. Las queries deben ser consultas jurídicas
técnicas, no datos personales de terceros.

---

## 3. Base jurídica asumida

**Uso interno en entorno de desarrollo.** La base jurídica asumida para el
tratamiento es el interés legítimo del responsable en el desarrollo y prueba
de herramientas de trabajo interno (art. 6.1.f RGPD), bajo la condición de
que el sistema permanezca en entorno local y no procese datos personales reales
de clientes.

Antes de cualquier despliegue fuera del entorno de desarrollo, se deberá
realizar una Evaluación de Impacto en la Protección de Datos (EIPD) y obtener
la aprobación del DPO corporativo.

---

## 4. Subprocesadores

### 4.1 Anthropic, Inc.

- **Servicio:** Anthropic API (modelos claude-opus-4-7, claude-haiku-4-5)
- **Qué se envía:** El texto de la consulta jurídica + fragmentos de normas
  recuperados por el motor RAG. No se envían datos personales de clientes
  de forma intencional; el sistema aplica redacción de PII en logs, pero
  no hay garantía de que las queries de los usuarios no contengan referencias
  a personas identificables.
- **Ubicación del procesamiento:** Servidores de Anthropic (EE.UU.),
  cubiertos por las Cláusulas Contractuales Tipo de la UE (SCCs) según
  los términos de uso de Anthropic.
- **Retención:** Anthropic puede retener datos de la API según su política
  de privacidad vigente. Para contextos corporativos con requisitos estrictos,
  se recomienda contratar la opción **Zero Data Retention (ZDR)** de Anthropic,
  que garantiza que las llamadas a la API no se usan para entrenamiento ni se
  almacenan más allá de la duración de la llamada.
- **Referencia:** https://www.anthropic.com/privacy

### 4.2 Qdrant (base de datos vectorial)

- **Servicio:** Qdrant OSS, ejecutado localmente en Docker.
- **Qué contiene:** Fragmentos de normas públicas (BOE, EUR-Lex) con sus
  embeddings. No contiene datos personales.
- **Ubicación:** Exclusivamente local (volumen Docker en el host).

### 4.3 SQLite (historial de consultas)

- **Servicio:** aiosqlite, base de datos local en `data/consultations.db`.
- **Qué contiene:** Historial de consultas y respuestas (ver §2).
- **Ubicación:** Exclusivamente local.

---

## 5. Derechos de los usuarios

En entorno MVP/desarrollo interno, no se han implementado mecanismos formales
de ejercicio de derechos RGPD (acceso, rectificación, supresión, portabilidad).
El historial puede eliminarse manualmente borrando `data/consultations.db`.

---

## 6. Seguridad

- Autenticación JWT en todos los endpoints `/api/v1/*`.
- PII redactado en logs antes de escritura a stdout.
- Comunicación con Anthropic API cifrada en tránsito (HTTPS/TLS).
- Qdrant y SQLite sin cifrado en reposo en MVP. Pendiente para v0.2.0.
- Secrets (ANTHROPIC_API_KEY, JWT_SECRET) en `.env` local, no commiteados.

---

## 7. Cambios a esta política

Esta política se actualizará antes de cualquier despliegue fuera del entorno
de desarrollo local. Versión versionada junto al código fuente.
