# Guía de Usuario — Lex Agents

**Versión:** 10.0  
**Audiencia:** Abogados, analistas bancarios y personal de cumplimiento normativo

---

## 1. ¿Qué es Lex Agents?

Lex Agents es una plataforma interna de consulta jurídica especializada para el ámbito bancario. Combina modelos de lenguaje (IA) con una base de conocimiento normativa actualizada (BOE, EUR-Lex) para responder preguntas sobre regulación bancaria en España y la Unión Europea.

**Capacidades principales:**

- Consultas sobre regulación bancaria UE y española (CRR, CRD, BRRD, PSD2, MiFID II, entre otras).
- Análisis comparativo entre jurisdicciones.
- Referencias directas a artículos, considerandos y normativa aplicable.
- Trazabilidad de fuentes: cada afirmación incluye la cita verificable.

> **⚠️ Aviso legal obligatorio:** Lex Agents es una herramienta de apoyo a la investigación jurídica. Sus respuestas **no constituyen asesoramiento jurídico**. Todo resultado debe ser revisado y validado por un profesional jurídico cualificado antes de ser utilizado en decisiones o documentos legales. El uso de esta herramienta no exime de la responsabilidad profesional del usuario.

---

## 2. Acceso

**URL de acceso:** La URL interna será comunicada por el equipo de Tecnología a través de los canales habituales.

**Roles disponibles:**

| Rol        | Acceso                                        |
| ---------- | --------------------------------------------- |
| `user`     | Consultas jurídicas estándar                  |
| `operator` | Consultas + panel de administración (lectura) |
| `admin`    | Acceso completo incluyendo configuración      |

**¿No tienes acceso?**

1. Contacta con tu responsable directo para que solicite el acceso correspondiente.
2. El alta de usuarios se gestiona a través del equipo de Tecnología (contacto en la sección de Soporte).
3. Los accesos se aprueban en un plazo máximo de 2 días hábiles.

> El acceso está restringido a la red corporativa o VPN. Asegúrate de estar conectado antes de acceder.

---

## 3. Consultas Jurídicas

### Cómo formular preguntas

Para obtener mejores resultados, formula las consultas de forma específica e incluye el contexto relevante:

- ✅ **Bien:** "¿Qué requisitos de capital establece el artículo 92 del CRR para exposiciones al riesgo de crédito?"
- ❌ **Evitar:** "¿Qué dice la normativa bancaria?"

### Tipos de consulta

**Consulta regulatoria directa:** Pregunta sobre el contenido de una norma específica, un requisito concreto o una definición.

> _Ejemplo: "¿Cuál es el umbral de SREP para la ratio de capital de nivel 1 según la CRD V?"_

**Consulta comparativa:** Compara el tratamiento de una materia entre dos o más jurisdicciones o marcos normativos.

> _Ejemplo: "Comparar el régimen de resolución bancaria en España vs. el marco BRRD de la UE."_

**Consulta de fuente:** Localiza el texto de un artículo concreto o una disposición.

> _Ejemplo: "Texto del artículo 45 de la Directiva 2014/59/UE (BRRD)."_

### Jurisdicciones disponibles

- **España:** BOE, normativa del Banco de España, CNMV.
- **Unión Europea:** EUR-Lex, BCE, EBA, ESMA, SRB.

---

## 4. Interpretar Resultados

### Estado de verificación de citas

Cada respuesta incluye las fuentes utilizadas con un indicador de estado:

| Indicador | Significado                                                                 |
| --------- | --------------------------------------------------------------------------- |
| 🟢 Verde  | Cita verificada contra el chunk indexado. Alta confianza.                   |
| 🟡 Ámbar  | Cita localizada pero con coincidencia parcial. Revisar el texto original.   |
| 🔴 Rojo   | No se pudo verificar la cita. **No usar sin consultar la fuente primaria.** |

### Cómo leer las citas

Cada cita incluye:

- **Instrumento normativo:** nombre oficial y número de referencia.
- **Artículo/disposición:** número de artículo o sección específica.
- **Fragmento relevante:** texto literal extraído de la fuente.
- **Fecha de indexación:** fecha en que el documento fue incorporado a la base de conocimiento.

> Si la fecha de indexación es anterior a una modificación normativa reciente, la información podría estar desactualizada. Consulta siempre la versión vigente en la fuente oficial.

### Limitaciones conocidas

- La base de conocimiento se actualiza periódicamente, no en tiempo real.
- Las consultas muy amplias o ambiguas pueden generar respuestas menos precisas.
- El sistema puede no cubrir normativa muy reciente (publicada después de la última actualización del índice).
- No cubre jurisprudencia (sentencias de tribunales).

---

## 5. Soporte

### Contactos

| Tipo de consulta                         | Contacto                                        |
| ---------------------------------------- | ----------------------------------------------- |
| Problemas de acceso o credenciales       | Equipo de Tecnología — canal interno de soporte |
| Error en una respuesta o cita incorrecta | Equipo Legal Digital — formulario de reporte    |
| Sugerencias de mejora                    | Product Manager de Lex Agents                   |

### Cómo reportar un error

Si identificas una respuesta incorrecta o una cita que no corresponde al texto original:

1. Copia la consulta exacta que realizaste.
2. Copia la respuesta obtenida e identifica el fragmento erróneo.
3. Indica la fuente correcta si la conoces.
4. Envía esta información al equipo de Legal Digital a través del formulario de reporte (enlace disponible en el portal interno).

Los reportes de errores contribuyen a mejorar la calidad del sistema para todos los usuarios.

---

_Última actualización: Fase 10. Para documentación técnica, consultar la guía de administración._
