# Fuentes Comerciales — Estado RED

**Actualizado:** 2026-05-11
**Estado:** RED — bloqueado hasta contrato API firmado

---

## Fuentes afectadas

| Fuente           | Propietario                | Clase Python     |
| ---------------- | -------------------------- | ---------------- |
| Aranzadi         | Thomson Reuters            | `AranzadiSource` |
| La Ley           | Wolters Kluwer             | `LaLeySource`    |
| Tirant lo Blanch | Tirant lo Blanch Editorial | `TirantSource`   |

---

## Por qué están bloqueadas

Los contenidos de estas plataformas son **propiedad intelectual protegida** de sus respectivos titulares:

1. **Propiedad intelectual:** los textos comentados, clasificaciones, resúmenes, concordancias y doctrina son obras derivadas protegidas por derechos de autor (Ley de Propiedad Intelectual, TRLPI).
2. **Bases de datos protegidas:** las colecciones de jurisprudencia, normativa comentada y doctrina están protegidas como bases de datos sui generis (Directiva 96/9/CE).
3. **Términos contractuales:** el acceso requiere suscripción con condiciones que prohíben expresamente la descarga masiva y el uso automatizado sin contrato API específico.

**Regla ADR 0011:** no se crea ningún conector técnico hasta que exista contrato firmado. Crear infraestructura para contenido sin licencia genera riesgo legal independientemente del uso en producción.

---

## Aranzadi (Thomson Reuters)

- **Contacto comercial:** Thomson Reuters Legal España — `https://legal.thomsonreuters.es/`
- **Proceso:** Santander Legal negocia contrato de API con Thomson Reuters
- **Alcance estimado de contenido:** CRR/CRD comentado, jurisprudencia comercial, legislación consolidada ES/UE
- **Responsable Santander:** Dirección Jurídica — División de Compras Tecnológicas

## La Ley (Wolters Kluwer)

- **Contacto comercial:** Wolters Kluwer España — `https://www.wolterskluwer.es/`
- **Proceso:** Santander Legal negocia contrato de API con Wolters Kluwer
- **Alcance estimado de contenido:** Memento Práctico Bancario, legislación financiera comentada
- **Responsable Santander:** Dirección Jurídica — División de Compras Tecnológicas

## Tirant lo Blanch

- **Contacto comercial:** Tirant lo Blanch Editorial — `https://www.tirant.com/`
- **Proceso:** Santander Legal negocia contrato de API con Tirant lo Blanch
- **Alcance estimado de contenido:** Jurisprudencia contencioso-administrativa, derecho bancario
- **Responsable Santander:** Dirección Jurídica — División de Compras Tecnológicas

---

## Proceso de desbloqueo RED → GREEN

El proceso RED es más exigente que AMBER:

1. **Contrato firmado:** Santander Legal proporciona contrato API firmado (adjunto o referenciado en el issue de GitHub)
2. **Issue GitHub:** abrir issue con label `source:red` + `source:contrato-firmado` adjuntando referencia al contrato
3. **Implementación técnica:** el conector se implementa **después** del contrato, no antes
4. **Aprobación:** el PR requiere aprobación de:
   - Legal del Grupo
   - Compliance
   - Dirección de Tecnología
5. **Activación producción:** aprobación adicional de Dirección de Tecnología antes de incluir en pipeline de producción
6. **ADR 0011:** actualizar con cambio de estado RED → GREEN y referencia al contrato

---

## Impacto en el MVP

La ausencia de fuentes RED no bloquea el MVP ni las Fases 6.x. La base de fuentes abiertas (BOE, EUR-Lex, AEPD, EDPB, BdE, EBA, ESMA, legislation.gov.uk) es suficiente para un sistema de primera consulta de calidad. Las fuentes RED añadirían:

- Mayor cobertura de jurisprudencia comentada
- Mejores concordancias normativas
- Doctrina especializada

Estas mejoras son deseables pero no críticas para el MVP bancario regulatorio.
