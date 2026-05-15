# 0058 — Política de marca y aprobación pendiente

**Status:** Accepted  
**Date:** 2026-05-15

## Context

lex-agents es una plataforma desarrollada en el contexto de Grupo Santander
para uso interno del área jurídica bancaria. El uso de la identidad visual
corporativa de Santander (logo, tagline, iconografía, copy oficial) está
sujeto a aprobación formal por parte de los equipos de Marca y Marketing
del Grupo.

Sin esta aprobación explícita, la incorporación de assets oficiales en la
plataforma — aunque sea de uso interno — puede:

1. Incumplir las brand guidelines internas de Santander, exponiendo al
   equipo de desarrollo a objeciones de Marca.
2. Crear inconsistencias con las versiones oficiales del logo o copy si
   se aplican versiones incorrectas.
3. Generar ambigüedad sobre si la plataforma ha sido aprobada y validada
   por Santander como herramienta corporativa oficial.

Este ADR establece límites claros entre lo que se puede hacer en Fase 10
sin aprobación adicional y lo que requiere el proceso formal de aprobación
de Marca Santander.

## Decision

### Lo que NO se hace en Fase 10 sin aprobación formal de Marca/Marketing Santander

Las siguientes acciones están **bloqueadas** hasta recibir aprobación escrita
del equipo de Marca de Santander:

1. **Uso del logo Santander** en cualquier asset desplegado (favicon, header,
   emails, documentación pública, presentaciones).
2. **Tagline o slogan corporativo** de Santander en cualquier texto visible
   al usuario.
3. **Iconografía corporativa** propietaria de Santander (el "llama" o llamas,
   iconos del design system interno Santander si existen).
4. **Reproducción de páginas oficiales** de Santander o layouts que imiten
   directamente la web/app de Santander con usuarios que puedan confundirlas
   con el producto oficial.
5. **Nombre de producto con marca**: "Santander LexAgents", "Santander Legal AI"
   o cualquier combinación que incluya la marca Santander en el nombre del
   producto sin aprobación de Marca.

### Lo que SÍ se hace en Fase 10 sin necesidad de aprobación adicional

Las siguientes acciones están **permitidas** y se implementan en Fase 10:

1. **Paleta de colores corporativa**: los valores hex de la paleta Santander
   son información públicamente disponible (usada en la web pública de
   Santander, en documentos de inversores, etc.). Su aplicación en un
   diseño interno no requiere aprobación específica de Marca.
2. **Diseño profesional alineado con banca**: interfaz de alta calidad, seria,
   con vocabulario visual bancario, sin afirmar ser un producto oficial.
3. **Slot configurable para logo y branding completo** (ADR 0057): la
   arquitectura está preparada para el logo oficial; el placeholder no
   implica uso del logo real.
4. **Referencia textual interna**: en documentación interna y commits se puede
   mencionar "para uso en Santander" o "contexto Santander" sin usar la marca
   en assets visibles al usuario.

### Proceso cuando llegue la aprobación de Marca Santander

Al recibir aprobación formal (email o documento de Marca/Marketing):

1. **Sustitución del logo placeholder** (`NEXT_PUBLIC_BRAND_LOGO_SRC` en
   variables de entorno) con el SVG oficial proporcionado por Marca.
   El componente `<Logo />` (ADR 0057) no requiere modificación de código.
2. **Aplicación de assets oficiales**: favicon, og:image, email headers.
3. **Revisión de copy**: todos los textos visibles al usuario pasan por
   revisión de Marketing para asegurar el tono de voz correcto.
4. **Verificación de brand guidelines**: clear space del logo, tamaños
   mínimos, variantes permitidas (monocroma, negativa, etc.).
5. **Documentación en el repositorio**: el fichero
   `docs/legal/brand-approval-process.md` se actualiza con la fecha de
   aprobación, el nombre del contacto en Marca y los assets aprobados.

### Proceso de aprobación

El proceso formal está documentado en `docs/legal/brand-approval-process.md`
y recoge:

- Contacto del equipo de Marca Santander responsable.
- Materiales necesarios para la solicitud (mockups, descripción del uso,
  alcance de la plataforma).
- Criterios de aprobación conocidos (si se han comunicado).
- Estado actual de la solicitud y fecha de última actualización.

La solicitud de aprobación debe iniciarse en paralelo con el desarrollo de
Fase 10, no al final, para minimizar el tiempo de bloqueo antes de producción.

## Alternatives considered

**Usar el logo Santander desde el inicio con la justificación de "uso interno":**

- Pro: la plataforma luce corporativa desde el primer día de piloto.
- Con: uso sin aprobación de Marca puede generar fricciones con el equipo
  corporativo y potencialmente requerir rollback de assets si el logo usado
  no es la versión correcta o el uso no está permitido.
- Rechazado: el riesgo reputacional y corporativo no justifica la ganancia
  estética en fase de piloto.

**No usar ningún elemento visual relacionado con Santander:**

- Pro: cero riesgo de marca.
- Con: la plataforma no transmite su contexto corporativo; usuarios de
  Santander que la reciben pueden percibirla como una herramienta externa
  no oficial, reduciendo la confianza.
- Rechazado: la paleta de colores pública y el slot de logo son el compromiso
  correcto.

## Consequences

**Positivo:**

- Riesgo legal y corporativo acotado: ningún asset con marca registrada se
  despliega sin aprobación formal.
- El equipo de desarrollo puede avanzar en Fase 10 sin bloquearse esperando
  aprobación de Marca.
- La arquitectura preparada (slot de logo, env vars de branding) hace la
  transición al branding oficial trivial cuando llegue.
- Queda documentado explícitamente para cualquier auditoría interna de marca.

**Negativo:**

- El producto en piloto inicial no luce con el logo oficial. Esto puede ser
  percibido como falta de madurez por algunos stakeholders.
- Requiere iniciar el proceso de aprobación de Marca en paralelo — que tiene
  su propio timeline burocrático.
- `docs/legal/brand-approval-process.md` debe crearse y mantenerse actualizado
  (tarea de sub-fase 10.1).
