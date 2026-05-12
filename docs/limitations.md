# Limitaciones de la plataforma lex-agents

> Versión: Fase 7.4 — 2026-05-12
> Este documento reemplaza cualquier mención anterior de limitaciones dispersa en otros archivos.

---

## 1. Jurisdicciones soportadas

| Jurisdicción | Nivel de cobertura | Notas |
|---|---|---|
| **España (ES)** | Completa | BOE indexado (leyes, RD, circulares BdE). Fuente principal. |
| **Unión Europea (EU)** | Completa | EUR-Lex indexado (reglamentos, directivas, decisiones BCE/EBA/ESMA). |
| **Brasil (BR)** | Parcial | INLABS-DOU en integración parcial (LGPD, regulación BACEN básica). Planner anota "asesoría local recomendada" para normas no indexadas. |
| **México (MX)** | Parcial | SIDOF-DOF en integración parcial (CNBV básica). Cobertura incompleta; planner anota limitación. |
| **Reino Unido (UK)** | Insuficiente | Sin fuentes primarias indexadas. Solo referencias cruzadas desde EUR-Lex (pre-Brexit). Consultas UK retornan degraded response con aviso explícito. |

Cualquier jurisdicción no listada arriba es **explícitamente rechazada** por el detector de consultas no soportadas.

---

## 2. Ramas jurídicas activas

Las siguientes seis ramas tienen especialistas activos:

1. **Regulatorio bancario UE+ES** — CRR, CRD IV/V, Ley 10/2014, Circular BdE, MREL, Basilea III.
2. **Datos personales** — RGPD, LOPDGDD, Directiva ePrivacy, LGPD (BR, parcial), CNBV/LFPDPPP (MX, parcial).
3. **Laboral** — ET, LOLS, negociación colectiva bancaria, regulación teletrabajo.
4. **Mercantil** — LSC, regulación sociedades, contratos mercantiles, UTE.
5. **Penal económico** — compliance penal, responsabilidad penal persona jurídica (art. 31 bis CP), blanqueo.
6. **Administrativo** — procedimiento administrativo, recursos, sanciones BdE/CNMV.

Ramas **no activas** en Fase 7 (planificadas para fases futuras): derecho fiscal, derecho de seguros,
derecho de la competencia, derecho concursal, propiedad intelectual, derecho de familia.

---

## 3. Consultas NO soportadas

El detector de consultas no soportadas rechaza explícitamente cuatro categorías de patrones con una
respuesta degradada estructurada. No se intenta una respuesta de baja confianza.

| Categoría | Ejemplos de consultas rechazadas | Respuesta degradada |
|---|---|---|
| **Jurisdicción no soportada** | "¿Cuál es la ley aplicable en China?", "Derecho federal de EE.UU.", "Ley bancaria suiza" | Declara la jurisdicción como no soportada; lista las jurisdicciones disponibles. |
| **Rama jurídica fuera de alcance** | "Derecho de herencias", "Custodia de menores", "Derecho fiscal corporativo", "Propiedad intelectual" | Declara la rama como fuera de alcance; lista las ramas activas. |
| **Solicitud de actuación procesal** | "Redacta el escrito de demanda", "Presenta el recurso", "Firma el contrato", "Actúa como mi abogado" | Declara que la plataforma no realiza actuaciones procesales autónomas; recomienda abogado cualificado. |
| **Consulta sin base normativa indexada** | Hechos muy específicos sin anclaje regulatorio conocido, preguntas de estrategia legal pura | Declara incapacidad de fundamentar la respuesta; lista las fuentes disponibles. |

Las consultas rechazadas se registran con `rejection_reason` para auditoría y mejora continua.

---

## 4. Fuentes en desarrollo

Las siguientes fuentes están integradas en modo parcial o de desarrollo y **no deben considerarse
fuentes primarias definitivas** hasta que alcancen el estado de producción completo:

### CENDOJ (Centro de Documentación Judicial)

- **Estado**: Modo desarrollo (`cendoj_mode=dev`).
- **Limitación de cuota**: `CENDOJ_DAILY_QUOTA` con tope fijo. Cuando se agota, las consultas
  que requieren jurisprudencia caen en modo degradado silencioso (solo BOE+EUR-Lex).
- **Sin autorización CGPJ de producción**: La autorización formal del Consejo General del Poder
  Judicial para el uso en producción está pendiente. Hasta su concesión, no se puede elevar la
  cuota ni indexar el corpus completo de jurisprudencia.
- **Bloqueo de citas rotas**: El verificador de citas aplica un bloqueo estricto: cualquier
  reclamación jurisprudencial basada en CENDOJ con referencia rota provoca un `503` antes de
  devolver la respuesta, en lugar del comportamiento estándar de degradación a RED.
- **Indicador en respuesta**: Cuando se usan chunks CENDOJ, la respuesta incluye el flag
  `cendoj_source=true` y muestra el banner de alerta CENDOJ.

### INLABS-DOU (Brasil — Diário Oficial da União)

- **Estado**: Integración parcial. Cubre LGPD y regulación BACEN básica.
- **Limitación**: Cobertura incompleta de normas CNBV y regulación sectorial bancaria BR.
- **Impacto**: El planner anota "asesoría local recomendada" en consultas BR fuera del subconjunto indexado.

### SIDOF-DOF (México — Diario Oficial de la Federación)

- **Estado**: Integración parcial. Cubre regulación CNBV básica.
- **Limitación**: Sin cobertura de normas de la CONDUSEF, SAT ni regulación fiscal MX.
- **Impacto**: El planner anota limitación de cobertura en todas las consultas MX.

---

## 5. Sin validación experta externa

**Ninguna respuesta generada por lex-agents ha sido validada por un jurista externo cualificado.**

### Qué significa esto

- Los 33 casos dorados (+ 4 casos COMP) usados por LeMAJ y el suite adversarial fueron
  producidos internamente, no por un experto jurídico externo contratado.
- El análisis de cláusulas del agente documental no ha sido revisado contra un corpus representativo
  de contratos por ningún experto externo.
- La plataforma es un borrador asistido por IA. Todo output requiere revisión humana cualificada
  antes de cualquier uso profesional, interno o externo.

### Qué se hace al respecto (mitigaciones activas)

1. Banner de aviso reforzado en cada respuesta (no suprimible).
2. Widget de feedback (aceptable/dudoso/incorrecto) que alimenta el pipeline de reflexión.
3. Muestreo diario de auditoría — 5 respuestas/día revisadas asincrónicamente.
4. Detector de consultas no soportadas — rechaza 4 categorías de patrones de alto riesgo.
5. El pipeline de reflexión prioriza casos de feedback negativo antes del ciclo LeMAJ nocturno.

Ver ADR 0028 para la documentación completa de mitigaciones.

### Plan para Fase 8

- Contratación de jurista externo cualificado para validar 33+ casos dorados.
- Extensión del dataset validado a 100+ casos.
- Revisión del agente documental contra corpus representativo de contratos.

---

## 6. Documentos

El agente documental (Fase 7) tiene las siguientes limitaciones:

- **Tamaño máximo por documento**: 10 MB por archivo.
- **Formatos soportados**: PDF, DOCX. Otros formatos (XLS, HTML, imágenes) no son procesados.
- **Sin persistencia tras la sesión**: Los documentos subidos se procesan en memoria durante la
  sesión y no se almacenan. Al cerrar la sesión, el documento no puede recuperarse.
- **Sin indexación en Qdrant**: Los chunks del documento subido no se añaden al índice permanente.
  Solo están disponibles en el contexto de la consulta activa.
- **Citas con sintaxis `[DOC:s]`**: Las referencias a fragmentos del documento usan esta sintaxis
  específica, distinta de las citas normativas `[REF:n]`.
- **Solo análisis, no redacción**: El agente documental analiza y extrae cláusulas, pero no
  genera contratos ni redacta documentos nuevos de forma autónoma.

---

## 7. Derecho comparado

El módulo de derecho comparado (ADR 0027, Fase 7) tiene las siguientes limitaciones:

- **Máximo 5 jurisdicciones por consulta**: El módulo ComparativeView acepta hasta 5 jurisdicciones
  simultáneas. Superar este límite devuelve un error de validación.
- **No activación automática**: El módulo no se activa salvo que el usuario lo solicite
  explícitamente o el planner lo infiera del contexto de la consulta.
- **Cobertura BR y MX parcial**: Las divergencias identificadas en jurisdicciones BR y MX
  pueden ser incompletas debido a la cobertura parcial de INLABS-DOU y SIDOF-DOF.
- **Cobertura UK insuficiente**: Las columnas UK en la tabla pivot son producidas a partir de
  referencias cruzadas EUR-Lex pre-Brexit. No reflejan el estado actual del derecho UK.
- **Exportación XLSX**: La exportación de la tabla pivot a XLSX está disponible. El archivo
  no incluye citas fuente completas; solo los identificadores de normas. Las citas completas
  están en el panel de la respuesta.
- **Sin jurisprudencia comparada**: El módulo compara normas primarias y secundarias.
  La jurisprudencia comparada entre jurisdicciones no está soportada en Fase 7.
