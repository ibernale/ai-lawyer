# CENDOJ y Tribunal Constitucional — Estado AMBER

**Actualizado:** 2026-05-11
**Estado:** AMBER — acceso técnicamente posible, bloqueado hasta autorización

---

## CENDOJ (Centro de Documentación Judicial)

### Situación legal

- El CGPJ (Consejo General del Poder Judicial) gestiona CENDOJ.
- La descarga masiva de jurisprudencia requiere **autorización expresa del CGPJ** conforme al Art. 560 LOPJ.
- Los términos de uso del buscador web público de CENDOJ prohíben el scraping automatizado.
- Referencia normativa: Art. 560.1.19º LOPJ — el CGPJ tiene competencia exclusiva sobre la publicación de resoluciones judiciales.

### Por qué está bloqueado

1. La descarga masiva sin autorización vulneraría los ToU del portal público.
2. El CGPJ puede interpretar el scraping masivo como uso no autorizado de su base de datos (Directiva 96/9/CE, sui generis).
3. Riesgo reputacional para Santander España ante un regulador judicial.

### Proceso de desbloqueo

1. **Responsable:** Legal del Grupo Santander + DPO Santander España
2. **Acción requerida:** Solicitud formal al CGPJ para autorización de descarga masiva con fines de asistencia jurídica interna
3. **Plazo estimado:** 3-6 meses desde presentación de solicitud
4. **Documento necesario:** Resolución favorable del CGPJ o acuerdo de acceso a datos jurisprudenciales

### Seguimiento

- Abrir issue GitHub con label `source:amber` y asignar a Legal del Grupo
- El issue debe actualizarse con el estado de la solicitud al CGPJ mensualmente

### Modo DEV (CendojPuntualSource)

Mientras se tramita la autorización, existe un modo de desarrollo **exclusivo para validación de calidad del golden dataset**:

- Activar con `CENDOJ_DEV_MODE=true` (variable de entorno)
- Límite estricto: **≤50 req/día** (persistido en `/tmp/cendoj_puntual_counter.json`)
- `asyncio.sleep(5)` entre cada petición
- **Nunca activar en producción** sin autorización CGPJ
- Los documentos obtenidos en modo DEV no se indexan en la base de datos de producción

---

## Tribunal Constitucional (HJTC)

### Situación legal

- El Tribunal Constitucional publica sus sentencias en su web pública.
- Los términos de uso del portal TC no declaran explícitamente si se permite la descarga automatizada masiva.
- A diferencia de CENDOJ, no existe una norma LOPJ específica que regule el acceso masivo; pero la ausencia de autorización explícita genera incertidumbre jurídica.

### Por qué está bloqueado

1. Los ToU del portal TC son ambiguos respecto al scraping automatizado.
2. El TC no ha publicado una API oficial ni declarado los datos como "abiertos".
3. Riesgo legal bajo la Directiva de bases de datos (96/9/CE) si la web del TC se considera una base de datos protegida.

### Proceso de desbloqueo

1. **Responsable:** Legal del Grupo Santander
2. **Acción requerida:** Análisis jurídico de los ToU del portal TC + confirmación de ausencia de restricción
3. **Plazo estimado:** 2 semanas desde asignación a Legal
4. **Documento necesario:** Nota de Legal confirmando viabilidad

### Seguimiento

- Abrir issue GitHub con label `source:amber` y asignar a Legal del Grupo
- El proceso es más corto que CENDOJ: sólo requiere revisión de ToU, no autorización de tercero

---

## Proceso de activación (AMBER → GREEN)

Cuando se obtenga la autorización correspondiente:

1. Mover el issue de GitHub a estado "autorizado"
2. Crear PR que:
   - Elimina `raise NotImplementedError(...)` de la clase correspondiente
   - Implementa el scraper real
   - Añade `source_id` a las Literal de `CanonicalDocument`
   - Actualiza este documento con fecha de activación y referencia al sign-off
3. El PR requiere aprobación de Legal y Compliance antes de merge
4. Actualizar ADR 0011 con el cambio de estado
