# ADR 0011 — Política de fuentes y go/no-go

**Status:** Accepted
**Date:** 2026-05-11
**Deciders:** ibernale
**Extiende:** ADR 0006 (Estrategia de Ingesta)

---

## Context

ADR 0006 establece el principio "API oficial > scraping HTML" y define las dos fuentes
activas: BOE y EUR-Lex (regulatorio bancario). La expansión de ramas de ADR 0010 exige
incorporar nuevas fuentes jurídicas. No todas son equivalentes en términos de acceso
legal, calidad técnica y autorización requerida.

Este ADR extiende ADR 0006 con una tabla de go/no-go por fuente y los procesos de
desbloqueo para fuentes AMBER y RED.

---

## Principios heredados de ADR 0006

1. **API oficial > scraping HTML** siempre que exista
2. **Rate limiting**: ≤ 0.5 req/s salvo especificación distinta de la fuente
3. **Formato preferido**: XML > JSON > XHTML > HTML
4. **Sin PDF** como fuente primaria (frágil para extracción estructurada)

---

## Tabla de go/no-go por fuente

### GREEN — integración autorizada, puede implementarse ya

| Fuente                                       | Cobertura                       | Acceso técnico                                                                                     | Licencia                                        | Notas de implementación                                                                 |
| -------------------------------------------- | ------------------------------- | -------------------------------------------------------------------------------------------------- | ----------------------------------------------- | --------------------------------------------------------------------------------------- |
| **BOE — consolidados**                       | ES normativa consolidada        | `https://www.boe.es/buscar/act.php` XML                                                            | Datos abiertos RD 806/2015                      | Complementa la ingesta de diario; prioridad para ET, TRLSC, LOPDGDD                     |
| **BOE — anuncios y resoluciones**            | ES procedimiento administrativo | API XML existente, tipo "BOE-A"                                                                    | Ídem                                            | Cubre resoluciones sancionadoras BdE/CNMV referenciadas en dictámenes                   |
| **EUR-Lex — jurisprudencia TJUE (C-series)** | UE all branches                 | Cellar SPARQL + `celex: 6XXXX`                                                                     | Datos abiertos UE                               | Sentencias C-series; requiere parser específico para formato ECLI                       |
| **AEPD Resoluciones**                        | ES datos personales             | Buscador público `https://www.aepd.es/resoluciones`                                                | Publicación oficial; uso no comercial implícito | Scraping estructurado HTML (no hay API XML); frecuencia máxima 1 req/3s                 |
| **EDPB Guidelines + Opinions**               | UE datos personales             | `https://edpb.europa.eu/our-work-tools/documents`                                                  | CC BY 4.0                                       | PDFs con estructura consistente; parseable con pdfminer como excepción a regla anti-PDF |
| **BdE Circulares y guías supervisoras**      | ES regulatorio bancario         | `https://www.bde.es/wbe/es/publicaciones/`                                                         | Publicación oficial BdE                         | XML disponible para circulares; complementa cobertura CRR/CRD                           |
| **EBA Q&As Single Rulebook**                 | UE regulatorio bancario         | `https://www.eba.europa.eu/single-rule-book-qa` API JSON                                           | Datos abiertos EBA                              | Formato JSON estructurado; alta relevancia para rama bancaria                           |
| **ESMA Q&As**                                | UE mercados de capitales        | `https://www.esma.europa.eu/convergence/guidelines-and-recommendations`                            | Publicación oficial ESMA                        | HTML con estructura semiestructurada; conectar con `mercantil_societario`               |
| **legislation.gov.uk + FCA Handbook**        | UK regulatorio                  | `https://www.legislation.gov.uk/developer/formats` API XML; FCA `https://www.handbook.fca.org.uk/` | Open Government Licence v3                      | Relevante para Santander UK; activar junto con jurisdicción `GB`                        |

### AMBER — técnicamente posible, bloqueado hasta revisión/autorización

| Fuente                                        | Cobertura               | Bloqueo                                                                                                                                  | Responsable desbloqueo                  | Condición de desbloqueo                                                                                                                                                     |
| --------------------------------------------- | ----------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **CENDOJ jurisprudencia**                     | ES todas las ramas      | Descarga masiva requiere autorización expresa del CGPJ (Art. 560 LOPJ). Términos de uso del buscador web prohíben scraping automatizado. | Legal del Grupo + DPO                   | Solicitud formal al CGPJ por parte de Santander España. Plazo estimado: 3-6 meses. Mientras tanto: modo "consulta puntual" ≤50 req/día vía buscador público para desarrollo |
| **Tribunal Constitucional (HJTC)**            | ES constitucional       | Términos de uso no explican la posibilidad de descarga masiva. Web pública sin API declarada.                                            | Legal del Grupo                         | Verificación jurídica de ToU + confirmación de ausencia de restricción. Estimado: 2 semanas                                                                                 |
| **Boletines autonómicos (DOGC, BOJA, DOGA…)** | ES normativa autonómica | Heterogeneidad de licencias; algunos no declaran datos abiertos explícitamente                                                           | Compliance + Legal                      | Revisar ToU fuente a fuente; empezar por las 3 CCAA con mayor actividad bancaria (Cataluña, Andalucía, Madrid)                                                              |
| **DRE (Brasil) + DOF (México)**               | Santander Group LatAm   | Fuentes técnicamente públicas pero requieren validación del alcance de uso por equipos jurídicos de Santander Brasil/México              | Equipos legales locales SAN-BR / SAN-MX | Sign-off de cada equipo local; activar como jurisdicciones `BR` y `MX` separadas                                                                                            |

**Modo "consulta puntual" para CENDOJ (desarrollo):**
Implementar `CendojPuntualSource` con rate limit estricto (≤50 req/día, pause de 5s entre requests), sin persistencia en base de datos en producción, con flag `cendoj_puntual_enabled: bool = False` en Settings. Este modo es exclusivamente para desarrollo y validación de calidad; **nunca se activa en producción hasta autorización CGPJ**.

### RED — bloqueado hasta contrato o licencia formal

| Fuente                         | Cobertura         | Bloqueo                                                                | Responsable desbloqueo                                                           |
| ------------------------------ | ----------------- | ---------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| **Aranzadi (Thomson Reuters)** | ES/EU multi-rama  | Propiedad intelectual Thomson Reuters; contenido bajo licencia de pago | Santander Legal: negociación contrato API. Sin acceso técnico previo al contrato |
| **La Ley (Wolters Kluwer)**    | ES multi-rama     | Ídem                                                                   | Santander Legal: negociación contrato API                                        |
| **Tirant lo Blanch**           | ES/EU multi-rama  | Ídem                                                                   | Santander Legal: negociación contrato API                                        |
| **Lefebvre (Memento)**         | ES fiscal/laboral | Ídem                                                                   | Santander Legal: negociación contrato API                                        |

Para fuentes RED: **no se crea ningún conector técnico** hasta que exista contrato firmado. Crear infraestructura técnica para contenido sin licencia crea riesgo legal independientemente de si se usa en producción.

---

## Proceso de desbloqueo AMBER

1. **Identificación**: el equipo técnico levanta un issue en GitHub con label `source:amber` indicando la fuente y el bloqueo específico
2. **Revisión Legal**: Legal del Grupo emite nota de viabilidad jurídica (plazo máximo: 4 semanas desde issue)
3. **Aprobación**: Compliance y Riesgos Operacionales firman la activación
4. **Activación técnica**: PR que cambia `enabled: false` → `enabled: true` en la configuración de la fuente + documentación del sign-off en `docs/sources/<fuente>.md`
5. **Auditoría**: queda registrado en este ADR como cambio de estado (AMBER → GREEN)

## Proceso de desbloqueo RED

Idéntico al AMBER más:

- Contrato API firmado por Santander Legal (adjunto o referenciado en el issue)
- Conector técnico se implementa **después** del contrato, no antes
- La activación en producción requiere aprobación adicional de Dirección de Tecnología

---

## Criterios de calidad de fuente

Para que una fuente GREEN se incorpore activamente al pipeline de ingesta debe cumplir:

| Criterio                              | Mínimo                                                                   |
| ------------------------------------- | ------------------------------------------------------------------------ |
| Frecuencia de actualización declarada | ≤ 1 semana de lag para normativa vigente                                 |
| Formato de texto extraíble            | XML estructurado, JSON, o HTML con DOM estable (no PDFs escaneados)      |
| Idioma principal                      | ES o EU (EN, FR, DE aceptado con traducción automática marcada como tal) |
| Disponibilidad del endpoint           | ≥ 99 % mensual (verificar histórico o SLA declarado)                     |
| Política de uso explícita             | Datos abiertos declarados o uso no comercial permitido documentado       |

---

## Consequences

**Positivo:**

- La tabla elimina la ambigüedad sobre qué puede integrarse ya vs. qué requiere proceso
- El modo "consulta puntual" para CENDOJ permite avanzar en calidad del golden dataset sin esperar autorización masiva
- Las fuentes RED quedan protegidas frente a implantaciones técnicas prematuras que crearían riesgo legal

**Negativo/Riesgos:**

- CENDOJ AMBER bloquea la mejora de ramas como `laboral_es` y `penal_economico` que dependen fuertemente de jurisprudencia; el modo puntual mitiga parcialmente
- El proceso de desbloqueo AMBER requiere coordinación con equipos no técnicos; sin SLA real puede alargarse indefinidamente → los 4 semanas máximos del proceso deben acordarse formalmente

**Neutral:**

- Las fuentes RED (Aranzadi, La Ley, Tirant) aportarían mejoras sustanciales de calidad pero su ausencia no bloquea el MVP ni las Fases 6.x; la base de fuentes abiertas es suficiente para un sistema de primera consulta
