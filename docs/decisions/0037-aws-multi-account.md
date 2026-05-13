# ADR 0037 — Arquitectura multi-account AWS simplificada

**Estado:** Accepted  
**Fecha:** 2026-05-13  
**Decisores:** Ignacio Bernal (Santander)  
**ADRs relacionados:** 0036 (regiones), 0041 (networking), 0043 (CDK), 0044 (DORA)  
**Sub-fases afectadas:** 9.1 – 9.5

---

## Contexto

DORA Artículo 8 exige un marco de gestión de riesgo ICT con separación de privilegios,
inventario completo de activos y acceso mínimo. Una cuenta AWS única viola estos principios:
un compromiso de credenciales en el entorno de desarrollo podría afectar logs de auditoría
y controles de seguridad.

AWS Organizations + Control Tower es el patrón estándar del sector para implementar esa
separación de forma gestionada, con coste marginal para las cuentas de gestión.

---

## Decisión

### Estructura de 7 cuentas AWS Organizations

```
root (management)
├── log-archive
├── security
├── network
├── workloads-dev       ← activa desde Fase 9.1
├── workloads-pre       ← provisionada en Fase 9.5, sin workloads aún
└── workloads-pro       ← NO en Fase 9 (upgrade path documentado)
```

#### Cuenta `management`
- AWS Organizations root + facturación consolidada.
- AWS Control Tower con landing zone en eu-central-1.
- Service Control Policies (SCPs) aplicadas a toda la organización.
- Sin workloads ni datos de clientes.
- Acceso: solo administradores de plataforma con MFA hardware.

SCPs obligatorias en todas las cuentas hija:
```
DenyNonEURegions      — deny si aws:RequestedRegion ∉ {eu-central-1, eu-west-1}
DenyUnencryptedData   — deny S3 sin SSE-KMS, deny Aurora sin encryption
DenyRootAccess        — deny si aws:PrincipalType = Root (excepto emergency break-glass)
DenyExternalShare     — deny Resource Access Manager shares fuera de la org
RequireMFA            — deny ConsoleLogin sin MFA en IAM Identity Center
```

#### Cuenta `log-archive`
- Destino central de todos los logs de la organización:
  - CloudTrail (organización-wide): todos los eventos de management + data en todas
    las cuentas → S3 con Object Lock (WORM, modo Compliance, retención 7 años DORA).
  - VPC Flow Logs: todos los VPCs de workloads-dev y workloads-pre.
  - Application logs: CloudWatch Logs → Kinesis Firehose → S3 log-archive.
  - Config snapshots y historial de cambios.
- S3 Glacier Instant Retrieval para logs > 90 días (coste reducido).
- Sin compute propio. Solo S3 + Athena para queries ad-hoc sobre logs.
- Acceso: solo auditores (rol `lex-auditor`) y Security. workloads-dev no puede leer
  sus propios logs de auditoría en log-archive (separación física).

#### Cuenta `security`
- GuardDuty delegated administrator: agrega findings de todas las cuentas.
- Security Hub: agregador central, estándar CIS AWS Foundations Benchmark.
- AWS Config aggregator: compliance rules org-wide.
- AWS Audit Manager: evidencias automatizadas para auditorías DORA.
- AWS Inspector: escaneo de vulnerabilidades en imágenes ECR de workloads-dev.
- Sin workloads productivos. Solo consume datos de otras cuentas.

#### Cuenta `network`
- Transit Gateway (TGW) hub-and-spoke: conecta workloads-dev y workloads-pre
  entre sí y con servicios centrales.
- Route53 Resolver centralizado: DNS privado compartido entre cuentas.
- VPC Endpoints compartidos para servicios de alto volumen (Bedrock, S3, ECR):
  reduce coste frente a un endpoint por cuenta.
- AWS Network Firewall (opcional Fase 10 si tráfico inter-account lo justifica).

#### Cuenta `workloads-dev`
- Entorno de desarrollo + CI/CD. Objetivo de sub-fases 9.1–9.5.
- Todos los stacks CDK se despliegan aquí primero.
- Aurora Serverless v2 con auto-pause fuera de horario laboral.
- ECS Fargate con Fargate Spot para tasks no críticas (ahorro ~30%).
- No contiene datos de clientes reales; solo datos de prueba y eval.

#### Cuenta `workloads-pre`
- Provisionada en Fase 9.5 con la misma IaC que workloads-dev (contexto `pre` en CDK).
- Sin workloads en Fase 9. Objetivo: validar el patrón CDK en pre antes de que se necesite.
- Aurora sin auto-pause (simula producción).
- WAF en modo block (vs count en dev).

#### Cuenta `workloads-pro`
- **No se crea en Fase 9.**
- Se activa en Fase 10 cuando entre workload productivo con SLA formal.
- Upgrade path: copiar CDK context `pro` desde workloads-pre. Tiempo estimado: 1 sprint.

---

## IAM Identity Center (AWS SSO)

Punto único de acceso humano a todas las cuentas.

**Configuración Fase 9:**
- Identity store: IAM Identity Center nativo (no conectado a Azure AD todavía).
  La integración con Azure AD / SSO Santander es un pre-requisito de Fase 10 (sub-fase 9.1).
- MFA: obligatorio para todos los usuarios (reforzado por SCP `RequireMFA`).
- Sesiones: duración máxima 8h; re-autenticación con MFA.

**Permission Sets (roles) por cuenta:**

| Permission Set | Cuentas | Acceso |
|---|---|---|
| `PlatformAdmin` | management | Administración plena Organizations + Control Tower |
| `SecurityAdmin` | security | GuardDuty, Security Hub, Audit Manager |
| `LogsAuditor` | log-archive | S3 read-only sobre logs de auditoría |
| `DevAdmin` | workloads-dev | AdministratorAccess (CDK deploy, debugging) |
| `DevReadOnly` | workloads-dev | ReadOnlyAccess (analistas, revisores) |
| `PreAdmin` | workloads-pre | AdministratorAccess |
| `NetworkAdmin` | network | VPC, TGW, Route53 |

En Fase 10: integración con Azure AD convierte los Permission Sets en grupos AD mapeados.

---

## Alternativas consideradas

### Cuenta única
**Rechazada.** Viola DORA art. 8 (separación de privilegios) y DORA art. 10 (logs
inmutables). Un compromiso en dev borraría el audit trail. Imposible cumplir sin separación.

### Más de 7 cuentas (e.g., cuenta separada por servicio)
**Rechazada para Fase 9.** El overhead de gestión supera el beneficio para un equipo pequeño.
El patrón de 7 cuentas (management/log-archive/security/network + workloads por entorno)
es la arquitectura AWS de referencia ("landing zone") con el menor número de cuentas que
cumple DORA. Se amplía en Fase 10.

### AWS Control Tower sin Organizations custom
**Aceptada como base.** Control Tower gestiona la creación de cuentas y garantiza la
aplicación de guardrails (SCPs + Config rules). Se prefiere a un setup manual porque
incluye preventive + detective guardrails preconfigurados.

---

## Trade-offs y consecuencias

| Trade-off | Impacto |
|---|---|
| 7 cuentas implican billing por cuenta en algunos servicios | ~$200/mes extra (aceptable vs beneficio DORA) |
| IAM IC nativo sin AD en Fase 9 | Gestión manual de usuarios hasta SSO en Fase 10 |
| workloads-pro ausente hasta Fase 10 | No hay prod en Fase 9; coherente con la estrategia de validación previa |
| Log-archive centralizado con S3 Object Lock | Logs inmutables aunque workloads-dev quede comprometida |
| SCPs restrictivas desde el inicio | Algunos servicios AWS requieren región adicional para configuración; documentar excepciones |

### Blast radius acotado

Si workloads-dev queda comprometida (credenciales filtradas, supply chain):
- Los logs de auditoría en log-archive son inmutables (Object Lock WORM).
- GuardDuty y Security Hub detectan el compromiso desde la cuenta security.
- workloads-pre y workloads-pro no se ven afectados.
- management y log-archive requieren credenciales separadas con MFA hardware.
