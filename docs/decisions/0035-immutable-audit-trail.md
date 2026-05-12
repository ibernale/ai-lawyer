# ADR 0035 — Audit Trail Inmutable

- **Estado:** Accepted
- **Fecha:** 2026-05-12
- **Autores:** @ibernale
- **Fase:** 8.0 — Capa de control y observabilidad operacional

---

## Contexto

Las capacidades de Fase 8 introducen operaciones con impacto alto y potencialmente irreversible: ejecutar un kill switch, degradar el panel de jueces, aprobar un prompt que cambia el comportamiento del sistema, desactivar una fuente de ingesta. Estas acciones deben ser **trazables**, **atribuibles** y **no repudiables**.

El sistema ya tiene una tabla `audit_samples` (creada en Fase 7) para muestras de calidad de consultas. Pero no existe un registro operacional de acciones de administración.

Requisitos del audit trail:

1. **Append-only**: ningún registro puede modificarse o eliminarse una vez creado.
2. **Atribución**: cada registro debe identificar quién realizó la acción.
3. **Integridad verificable**: debe ser posible detectar si alguien borró registros intermedios.
4. **Contexto suficiente**: antes/después del estado cambiado, motivo.
5. **Integración con trazas LLM**: enlace al trace de Langfuse cuando la acción se origina en una consulta.

---

## Decisión

**Tabla `audit_trail` append-only en SQLite con integridad garantizada por trigger SQL y cadena de hashes SHA-256.**

---

## Schema

```sql
CREATE TABLE IF NOT EXISTS audit_trail (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT    NOT NULL,   -- ISO-8601 UTC, ej: "2026-05-12T14:00:00.000Z"
    actor_user_id   TEXT    NOT NULL,   -- UUID del usuario que realizó la acción
    actor_role      TEXT    NOT NULL,   -- rol en el momento de la acción (admin|operator|viewer)
    action_type     TEXT    NOT NULL,   -- ver enum controlado abajo
    target_type     TEXT,               -- agent|source|prompt|memory|sample|flag|user|system
    target_id       TEXT,               -- identificador del objeto afectado
    before_state    TEXT,               -- JSON con estado anterior (opcional)
    after_state     TEXT,               -- JSON con estado posterior (opcional)
    reason          TEXT,               -- obligatorio para acciones críticas (ver trigger)
    correlation_id  TEXT,               -- trace_id de Langfuse si aplica
    ip_address      TEXT,               -- NULL en Fase 8 local; placeholder para Fase 9
    checksum_prev   TEXT    NOT NULL    -- SHA-256 del registro id-1 serializado
);
```

### `action_type` — enum controlado

| Valor | Descripción |
|---|---|
| `kill_switch_engage` | Activación del kill switch global o de componente |
| `kill_switch_release` | Desactivación del kill switch |
| `flag_changed` | Cambio de feature flag |
| `prompt_promoted` | Versión de prompt aprobada y mergeada |
| `prompt_rejected` | Versión de prompt rechazada |
| `source_disabled` | Fuente de ingesta desactivada |
| `source_enabled` | Fuente de ingesta reactivada |
| `source_rematerialized` | Forzado de re-materialización de asset Dagster |
| `memory_edited` | Edición de memoria semántica o procedimental |
| `audit_sample_reviewed` | Revisión de audit sample (veredicto + notas) |
| `audit_trail_exported` | Exportación del audit trail (meta-audit) |
| `user_created` | Creación de usuario |
| `user_deactivated` | Desactivación de usuario |
| `user_role_changed` | Cambio de rol de usuario |
| `cost_alert_fired` | Disparo de alerta de reconciliación de costes |

Nuevos `action_type` se añaden vía PR con actualización de este ADR.

---

## Append-only por trigger SQL

```sql
-- Bloquear UPDATE sobre audit_trail
CREATE TRIGGER audit_trail_no_update
    BEFORE UPDATE ON audit_trail
BEGIN
    SELECT RAISE(ABORT, 'audit_trail is append-only: UPDATE not allowed');
END;

-- Bloquear DELETE sobre audit_trail
CREATE TRIGGER audit_trail_no_delete
    BEFORE DELETE ON audit_trail
BEGIN
    SELECT RAISE(ABORT, 'audit_trail is append-only: DELETE not allowed');
END;
```

Los triggers se crean en la misma transacción que la tabla. Cualquier intento de `UPDATE` o `DELETE` (incluso desde la consola SQLite) lanza `ABORT` y hace rollback de la transacción completa.

---

## Cadena de hashes

### Propósito

Detectar borrado o modificación de registros intermedios sin necesitar una base de datos externa o ledger blockchain.

### Mecanismo

Al insertar el registro `id = N`:

```python
import hashlib, json

def compute_checksum(prev_record: dict | None) -> str:
    if prev_record is None:
        return hashlib.sha256(b"GENESIS").hexdigest()
    canonical = json.dumps(prev_record, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()
```

El campo `checksum_prev` del registro `N` contiene el hash del registro `N-1` serializado en JSON canónico. El primer registro usa el hash de `b"GENESIS"` como ancla.

### Verificación de integridad

```python
def verify_chain(records: list[dict]) -> list[int]:
    """Devuelve IDs de registros donde la cadena está rota."""
    broken = []
    for i, record in enumerate(records):
        expected_prev = records[i-1] if i > 0 else None
        expected_checksum = compute_checksum(expected_prev)
        if record["checksum_prev"] != expected_checksum:
            broken.append(record["id"])
    return broken
```

Un admin puede ejecutar `make verify-audit-trail` para verificar la integridad de la cadena completa. Si se detectan registros rotos, se genera una alerta y se registra en el propio audit trail (action_type=`audit_trail_integrity_violation`).

---

## Campos obligatorios por action_type

Para acciones críticas, el trigger verifica que `reason` no sea NULL:

```sql
CREATE TRIGGER audit_trail_require_reason
    BEFORE INSERT ON audit_trail
    WHEN NEW.action_type IN (
        'kill_switch_engage', 'kill_switch_release',
        'prompt_promoted', 'prompt_rejected',
        'source_disabled', 'user_deactivated', 'user_role_changed'
    )
BEGIN
    SELECT CASE
        WHEN NEW.reason IS NULL OR NEW.reason = ''
        THEN RAISE(ABORT, 'reason is required for this action_type')
    END;
END;
```

---

## Integración con ADR 0032 (Kill Switches y Feature Flags)

Toda acción sobre `system_state` debe crear un registro en `audit_trail` **en la misma transacción SQLite**:

```python
async with db.transaction():
    await db.execute(
        "UPDATE system_state SET value=?, updated_at=?, updated_by=? WHERE key=?",
        (new_value, now, user_id, key)
    )
    await db.execute(
        "INSERT INTO audit_trail (timestamp, actor_user_id, actor_role, "
        "action_type, target_type, target_id, before_state, after_state, "
        "reason, checksum_prev) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (now, user_id, role, action_type, "flag", key,
         json.dumps(old_value), json.dumps(new_value), reason, checksum)
    )
```

Si falla cualquier parte de la transacción, ambas operaciones hacen rollback. Esto garantiza que nunca haya un cambio de estado sin registro en el audit trail, ni un registro en el audit trail sin el cambio de estado correspondiente.

---

## Vista en frontend (sub-fase 8.4)

La UI de Operations Center (sub-fase 8.3) mostrará el audit trail con:

- **Filtros**: actor, action_type, target_type, rango de fechas.
- **Vista de diff**: for actions with `before_state`/`after_state`, render JSON diff.
- **Exportación**: CSV o JSON. El propio export genera un registro `audit_trail_exported` (meta-audit).
- **Verificación de integridad**: botón "Verificar cadena" ejecuta `verify_chain()` y muestra resultado.

---

## Retención

Según ADR 0034: retención **indefinida**. El audit trail es evidencia de gobernanza que puede necesitarse en una auditoría regulatoria años después del hecho. Se exporta periódicamente a backup inmutable (sub-fase 8.2).

---

## Alternativas consideradas

| Alternativa | Razón de descarte |
|---|---|
| **Append-only sin hash chain** | No detecta borrado selectivo de registros. Un actor con acceso directo a SQLite podría eliminar registros sin dejar rastro. |
| **Base de datos externa blockchain-like** (Hyperledger Fabric, etc.) | Sobredimensionado para MVP local. Añade 3–5 servicios de infraestructura. |
| **Event sourcing completo** | Requiere refactorización arquitectónica mayor. El sistema existente es command-based, no event-sourced. Podría adoptarse en Fase 9 si el volumen lo justifica. |
| **Append-only log de ficheros** | Sin queries SQL, sin índices. Dificulta filtrado y exportación. SQLite con triggers es más robusto y consultable. |
| **Audit log en Langfuse** | Langfuse está diseñado para trazas de LLM, no para acciones de administración del sistema. Además, la retención de Langfuse es 90 días (ADR 0034); el audit trail es indefinido. |

---

## Consecuencias

**Positivas:**
- Cualquier acción de administración es atribuible, con contexto completo (antes/después, motivo).
- La cadena de hashes permite demostrar a un auditor que el historial es completo e inalterado.
- La integración transaccional con `system_state` elimina la posibilidad de divergencia entre estado del sistema y su registro.
- El meta-audit de exportaciones proporciona trazabilidad completa incluso sobre el propio audit trail.

**Negativas / Riesgos:**
- Un atacante con acceso de escritura directo a SQLite podría eliminar el fichero completo y recrearlo. Mitigación: backup periódico a almacenamiento separado (sub-fase 8.2).
- La cadena de hashes asume que los registros se leen en orden por `id`. Si SQLite AUTOINCREMENT no garantiza orden estricto en concurrencia alta, pueden aparecer falsos positivos en la verificación. Mitigación: operaciones admin son raras y secuenciales; no se espera concurrencia alta en el audit trail.

**Deuda técnica aceptada:**
- Backup periódico a almacenamiento inmutable (sub-fase 8.2).
- UI de audit trail filtrable (sub-fase 8.3/8.4).
- Job de verificación de integridad en CI semanal (sub-fase 8.2).

---

## Referencias

- [ADR 0032](0032-kill-switch-feature-flags.md) — Integración transaccional con system_state
- [ADR 0033](0033-roles-auth.md) — Campos actor_user_id y actor_role
- [ADR 0034](0034-data-retention.md) — Retención indefinida del audit trail
