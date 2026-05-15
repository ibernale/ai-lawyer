# Proceso de Aprobación de Cambios de Logo y Marca

**Versión:** 1.0  
**Audiencia:** Tech Lead, equipo de desarrollo, Equipo de Marca Santander  
**Aplica a:** Cambios de logotipo, icono de aplicación y elementos de identidad visual de Lex Agents

---

## Resumen del proceso

Cualquier cambio en el logotipo o identidad visual de Lex Agents requiere aprobación de dos partes: el Tech Lead técnico y el Equipo de Marca Santander. El proceso completo tiene una duración estimada de 3-5 días hábiles.

---

## Paso 1: Preparar el archivo SVG

El archivo de logo debe cumplir los siguientes requisitos técnicos antes de iniciar el proceso de aprobación:

**Requisitos obligatorios:**

- Formato: SVG (vectorial).
- Dimensiones mínimas del viewport: 200×200 píxeles.
- Fondo: transparente (sin `background` ni `rect` de fondo).
- El archivo debe renderizar correctamente tanto en modo claro como en modo oscuro.
- Tamaño máximo del archivo: 100 KB.

**Verificación de contraste (WCAG AA):**

Antes de enviar a aprobación, verificar que el logo cumple los requisitos de contraste WCAG AA:

- Ratio de contraste mínimo: 4.5:1 para texto, 3:1 para elementos gráficos.
- Herramientas recomendadas: [WebAIM Contrast Checker](https://webaim.org/resources/contrastchecker/) o Figma con plugin de accesibilidad.
- Documentar el ratio de contraste obtenido en la solicitud de aprobación.

---

## Paso 2: Subir a S3

Una vez el archivo pasa la verificación técnica:

```bash
aws s3 cp nuevo-logo.svg s3://lex-agents-assets/logos/nuevo-logo.svg \
  --content-type "image/svg+xml" \
  --cache-control "max-age=86400"
```

**Convención de nombres:** `{nombre-descriptivo}-v{versión}.svg`  
Ejemplo: `lex-agents-logo-horizontal-v2.svg`

Verificar que el archivo es accesible públicamente (si corresponde) o con las políticas de bucket correctas.

---

## Paso 3: Actualizar la variable de entorno en ECS

El logo activo se controla mediante la variable de entorno `NEXT_PUBLIC_LOGO_URL` en la definición de tarea ECS.

**Procedimiento:**

1. Abrir la consola AWS → ECS → Cluster de Lex Agents → Task Definition.
2. Crear una nueva revisión de la Task Definition.
3. Actualizar el valor de `NEXT_PUBLIC_LOGO_URL` con la URL S3 del nuevo logo.
4. Guardar la nueva revisión (no desplegar aún — esperar a la aprobación).

> ⚠️ No desplegar la nueva Task Definition hasta obtener las firmas de aprobación.

---

## Paso 4: Verificar contraste WCAG AA en contexto

Con el logo cargado en el entorno de staging (usando la nueva variable de entorno en un entorno de prueba):

1. Verificar la visualización en los fondos de la aplicación (claro y oscuro).
2. Ejecutar una auditoría de accesibilidad con Lighthouse o axe DevTools.
3. Capturar pantallas de la verificación para adjuntar a la solicitud de aprobación.

---

## Paso 5: Obtener firmas de aprobación

La solicitud de aprobación debe incluir:

- Archivo SVG (o URL S3).
- Capturas de pantalla del logo en contexto (modo claro y oscuro).
- Resultado de la verificación de contraste WCAG AA.
- Descripción del cambio y motivo.

**Firmas requeridas:**

| Aprobador                 | Rol                                                               | Plazo estimado   |
| ------------------------- | ----------------------------------------------------------------- | ---------------- |
| Tech Lead de Lex Agents   | Aprobación técnica (accesibilidad, integración)                   | 1 día hábil      |
| Equipo de Marca Santander | Aprobación de identidad visual y cumplimiento de brand guidelines | 2-3 días hábiles |

Ambas aprobaciones deben obtenerse antes de proceder al despliegue. Documentar las aprobaciones en el ticket correspondiente.

---

## Paso 6: Despliegue

Con ambas firmas obtenidas:

1. Actualizar la Task Definition en producción con la nueva `NEXT_PUBLIC_LOGO_URL`.
2. Forzar un nuevo despliegue del servicio ECS.
3. Verificar que el logo se muestra correctamente en producción.
4. Registrar el cambio en el Audit Trail (via comentario en el ticket o entrada manual si el sistema lo soporta).

---

## Rollback

Si el logo desplegado presenta problemas:

**Procedimiento de rollback inmediato:**

1. En la Task Definition ECS, eliminar el valor de `NEXT_PUBLIC_LOGO_URL` (dejar en blanco) o revertir a la revisión anterior de la Task Definition.
2. Forzar un nuevo despliegue.
3. La aplicación utilizará el fallback de iniciales **"LA"** (configurado en el componente de logo).

**Tiempo estimado de rollback:** < 5 minutos.

> El fallback a iniciales "LA" garantiza que la aplicación siempre muestra una identidad visual coherente, independientemente del estado de la variable de entorno.

---

## Historial de versiones de logo

| Versión | Fecha      | Descripción                | Aprobado por |
| ------- | ---------- | -------------------------- | ------------ |
| v1.0    | 2025-01-01 | Logo inicial (placeholder) | —            |

_Actualizar esta tabla con cada cambio aprobado._
