# Análisis de Documentos — Alcance, Limitaciones y Cumplimiento

**Actualizado:** 2026-05-11
**ADR de referencia:** ADR 0026 (Document Agents), ADR 0028 (Mitigaciones sin experto)

---

## Alcance del servicio

El módulo de análisis de documentos de lex-agents permite subir documentos jurídicos
(contratos, resoluciones, correos electrónicos) para obtener un análisis preliminar
asistido por IA. El análisis puede incluir:

- Resumen ejecutivo de partes, objeto, fechas clave
- Identificación de cláusulas principales
- Señalización de riesgos potenciales (penalizaciones, responsabilidades, incumplimientos)
- Comparativa entre dos versiones de un mismo documento

## Limitaciones técnicas

| Límite | Valor |
|--------|-------|
| Tamaño máximo por archivo | 50 MB |
| Páginas máximas por PDF | 200 páginas |
| Formatos soportados | PDF, DOCX, TXT, EML |
| PDFs protegidos con contraseña | No soportados |
| PDFs con solo imágenes (sin texto) | No soportados (sin OCR) |
| Tiempo de retención en memoria | 30 minutos desde la subida |

## Limitaciones del análisis

1. **Cobertura normativa limitada**: El sistema cita normativa indexada en las fuentes
   disponibles (BOE, EUR-Lex, AEPD, EDPB, BdE, EBA, ESMA, FCA). La normativa no
   indexada no se referenciará aunque sea aplicable.

2. **Sin jurisprudencia activa**: El módulo de análisis documental no accede a
   jurisprudencia de CENDOJ ni Tribunal Constitucional (estado AMBER — ver
   `cendoj-status.md`). Los análisis carecen de referencia jurisprudencial directa.

3. **Complejidad documental**: Contratos de alta complejidad, convenios multijurisdiccionales
   o estructuras societarias complejas pueden requerir segmentación manual o análisis
   dividido en partes.

4. **Idiomas**: Optimizado para español (ES). Documentos en inglés, portugués o
   francés pueden producir resultados de menor calidad en la extracción de entidades.

5. **Tablas y gráficos**: El contenido de tablas se aplana a texto. Los gráficos,
   diagramas e imágenes incrustadas no se analizan.

## Privacidad e invariante de no retención (RGPD)

**El texto completo de los documentos NO se almacena en ninguna base de datos.**

Lo que se almacena de forma permanente:
- `trace_id` (UUID de la sesión de análisis)
- SHA-256 del archivo original (huella digital, no el contenido)
- Resumen estructurado del análisis (`DocumentAnalysisResult`) — sin texto del documento

Lo que se elimina automáticamente:
- Bytes del archivo: tras el parseo, no se escriben a disco
- Texto parseado: en memoria durante máximo 30 minutos
- Segmentos: en memoria, eliminados al ejecutar `DELETE /api/v1/documents/{doc_id}`

**Base jurídica del tratamiento**: Interés legítimo del grupo para prestación de
asistencia jurídica interna (Art. 6.1.f RGPD). El tratamiento se limita al mínimo
necesario (principio de minimización — Art. 5.1.c RGPD).

**No se realiza transferencia internacional** de los documentos subidos. Los
documentos se procesan en los sistemas de Anthropic (API externa) para la generación
del análisis. Anthropic actúa como encargado del tratamiento conforme al DPA vigente.

**Política de retención**: 30 minutos en memoria volátil. No existe recuperación
posterior al borrado o expiración del TTL.

## Obligación de revisión por jurista cualificado

**Todo análisis generado por este módulo es un BORRADOR ASISTIDO POR IA.**

El análisis:
- No constituye dictamen jurídico ni asesoramiento legal en el sentido del art. 3
  de la Ley 2/1974, de Colegios Profesionales.
- No puede ser presentado a terceros, reguladores ni partes contractuales sin
  revisión y firma de un abogado colegiado responsable.
- No sustituye la due diligence jurídica en operaciones corporativas, financieras
  o regulatorias.

**Responsabilidad**: El uso de este sistema para tomar decisiones sin revisión
cualificada es responsabilidad exclusiva del usuario. El sistema declara
explícitamente las lagunas y las afirmaciones que no ha podido verificar contra
fuentes primarias.

## Proceso de escalado ante riesgo alto

Si el análisis identifica:
- Penalizaciones económicas significativas (>100.000 EUR)
- Posible incumplimiento regulatorio (MIFID II, CRR, DORA, RGPD)
- Cláusulas de resolución anticipada o expropiación
- Obligaciones de notificación a reguladores

→ Escalar de inmediato a la Dirección Jurídica del Grupo Santander.
→ No firmar ni ejecutar el documento hasta revisión legal completa.

## Contacto

Dudas sobre el módulo de documentos: equipo lex-agents (`lex-agents@gruposantander.com`)
Cuestiones jurídicas sobre contratos: Dirección Jurídica del Grupo Santander
