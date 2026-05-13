# ADR 0041 — Networking y seguridad de red en AWS

**Estado:** Accepted  
**Fecha:** 2026-05-13  
**Decisores:** Ignacio Bernal (Santander)  
**ADRs relacionados:** 0036 (regiones), 0037 (multi-account), 0042 (persistencia),
0043 (CDK), 0044 (DORA)  
**Sub-fases afectadas:** 9.1 – 9.5

---

## Contexto

El stack local no tiene superficie de red expuesta: todo corre en docker-compose con bridge
network privada. En AWS necesitamos diseñar desde cero la segmentación de red, el acceso
desde Internet, el acceso humano a los sistemas, y el cifrado en tránsito y en reposo.

DORA Artículos 9 y 10 exigen:

- Segmentación de red y control de acceso mínimo.
- Cifrado de datos en tránsito y en reposo.
- Capacidad de logging y detección de acceso no autorizado.

El diseño debe ser "secure by default": nada expuesto que no deba estarlo.

---

## Decisión

### Topología VPC por cuenta `workloads-*`

Cada cuenta workloads (dev, pre, pro) tiene su propia VPC con la siguiente estructura:

```
VPC: 10.0.0.0/16 (workloads-dev) — eu-central-1, 3 AZs

┌─────────────────────────── AZ: eu-central-1a ─────────────────────────────┐
│  subnet-public-a    10.0.0.0/24    ALB, NAT GW                             │
│  subnet-private-a   10.0.10.0/24   ECS tasks, AgentCore, Lambda            │
│  subnet-data-a      10.0.20.0/24   Aurora, ElastiCache, Secrets endpoints  │
└────────────────────────────────────────────────────────────────────────────┘
(× 3 AZs: a → 10.0.0/10/20, b → 10.0.1/11/21, c → 10.0.2/12/22)
```

**3 capas de subnet por AZ:**

| Subnet              | CIDR ejemplo         | Qué va aquí                                                |
| ------------------- | -------------------- | ---------------------------------------------------------- |
| `public-{az}`       | 10.0.{0,1,2}.0/24    | Application Load Balancer, NAT Gateway                     |
| `private-app-{az}`  | 10.0.{10,11,12}.0/24 | ECS Fargate (API, Web), AgentCore Runtime, Lambda (tools)  |
| `private-data-{az}` | 10.0.{20,21,22}.0/24 | Aurora Serverless v2, ElastiCache, VPC Endpoint interfaces |

**NAT Gateway:** uno por AZ (3 total). Coste ~$110/mes. Justificado en banca: si una AZ
cae, las otras dos AZs tienen su propio NAT GW y no pierden conectividad de salida.
El tráfico de salida es principalmente hacia ECR (pull de imágenes) y OCSP (TLS validation).
Los servicios AWS críticos (Bedrock, S3, KMS, etc.) se acceden via VPC Endpoints.

### VPC Endpoints

Reducen egreso a Internet + mejoran compliance (tráfico nunca sale de la red AWS):

| Endpoint                                      | Tipo      | Servicio                 |
| --------------------------------------------- | --------- | ------------------------ |
| `com.amazonaws.eu-central-1.bedrock-runtime`  | Interface | Bedrock Converse API     |
| `com.amazonaws.eu-central-1.bedrock`          | Interface | Bedrock control plane    |
| `com.amazonaws.eu-central-1.agentcore`        | Interface | AgentCore Runtime        |
| `com.amazonaws.eu-central-1.secretsmanager`   | Interface | Secrets Manager          |
| `com.amazonaws.eu-central-1.kms`              | Interface | KMS                      |
| `com.amazonaws.eu-central-1.ecr.api` + `.dkr` | Interface | ECR (pull de imágenes)   |
| `com.amazonaws.eu-central-1.logs`             | Interface | CloudWatch Logs          |
| `com.amazonaws.eu-central-1.monitoring`       | Interface | CloudWatch Metrics       |
| `com.amazonaws.eu-central-1.ssmmessages`      | Interface | SSM Session Manager      |
| `com.amazonaws.eu-central-1.s3`               | Gateway   | S3 (sin coste por datos) |
| `com.amazonaws.eu-central-1.dynamodb`         | Gateway   | DynamoDB (si se usa)     |

Los endpoints Interface se despliegan en `private-data-{az}` subnets. Security Group
de endpoint: solo tráfico desde `private-app-{az}` del mismo account.

### Acceso desde Internet (usuarios de la aplicación)

```
Usuario (HTTPS) → CloudFront → WAF → ALB (public subnet) → ECS Fargate Web (private-app)
                                                           → ECS Fargate API (private-app)
```

**CloudFront:**

- Distribución con origen `ALB DNS`.
- WAF asociado en edge (us-east-1, obligatorio para WAF en CloudFront).
- ACM certificate (eu-central-1 para ALB; us-east-1 para CloudFront).
- Caché desactivado para el API (`/api/*`); caché activado para assets estáticos Next.js.

**WAF Managed Rules (en orden de evaluación):**

1. `AWSManagedRulesCommonRuleSet` — protección OWASP top 10.
2. `AWSManagedRulesKnownBadInputsRuleSet` — inputs maliciosos conocidos.
3. `AWSManagedRulesSQLiRuleSet` — SQL injection.
4. Rate limit: 1.000 requests / 5 min por IP. Bloqueo automático.

- **Modo en dev:** `COUNT` (log sin bloquear) para no interrumpir desarrollo.
- **Modo en pre/pro:** `BLOCK`.

**ALB:**

- HTTPS only (HTTP redirige a HTTPS).
- TLS policy `ELBSecurityPolicy-TLS13-1-2-2021-06` (TLS 1.2 mínimo, TLS 1.3 preferido).
- Health checks cada 30s.
- Target groups: ECS Fargate API (port 8000) y Web (port 3000).

### Acceso humano (operadores, desarrolladores)

**IAM Identity Center + SSM Session Manager:**

- Sin bastion hosts. Sin SSH expuesto.
- Acceso a containers ECS: `aws ecs execute-command` via SSM Session Manager. Requiere
  rol IAM con `ssmmessages:*` y `ecs:ExecuteCommand`. Auditable en CloudTrail.
- Acceso a Aurora: via SSM port forwarding a la instancia Aurora o via Aurora Query
  Editor en consola AWS (requiere rol con `rds:DescribeDBClusters`).

**Client VPN:** NO en Fase 9. El overhead de gestión (PKI, client configs, revocación)
y la ausencia de SSO Santander hacen que el beneficio no justifique el coste. Se añade
en Fase 10 junto con la integración Azure AD.

### Acceso entre servicios internos

**Security Groups mínimo privilegio:**

| Origen          | Destino          | Puerto | Protocolo   |
| --------------- | ---------------- | ------ | ----------- |
| ALB SG          | ECS API SG       | 8000   | TCP         |
| ALB SG          | ECS Web SG       | 3000   | TCP         |
| ECS API SG      | Aurora SG        | 5432   | TCP         |
| ECS API SG      | VPC Endpoints SG | 443    | TCP (HTTPS) |
| AgentCore SG    | VPC Endpoints SG | 443    | TCP (HTTPS) |
| Lambda tools SG | VPC Endpoints SG | 443    | TCP (HTTPS) |
| Lambda tools SG | Aurora SG        | 5432   | TCP         |

Sin reglas `0.0.0.0/0` en subnets privadas (solo a través de NAT GW para salida).

### Cifrado

**En reposo:**

- KMS Customer Managed Keys: una CMK por entorno (`lex-agents-dev-cmk`, `lex-agents-pre-cmk`).
- Aurora: `StorageEncrypted=true` con CMK. Backups también cifrados con CMK.
- S3: `SSE-KMS` con CMK para todos los buckets.
- EBS (si se usa en SageMaker): cifrado con CMK.
- Secrets Manager: cifrado automático con CMK.
- CloudWatch Logs: cifrado con CMK (grupos de logs sensibles).

**En tránsito:**

- ALB: TLS 1.2+ (TLS 1.3 preferido). Sin HTTP.
- Aurora: `require_secure_transport=1`. TLS con certificado AWS RDS.
- Bedrock via VPC Endpoint: HTTPS (TLS 1.3). Sin salida a Internet.
- Inter-container (ECS internal): cifrado a nivel de red en la VPC AWS (tráfico entre
  ENIs en la misma VPC está cifrado en tránsito desde 2021 en Nitro instances).

**Secrets Manager para todas las credenciales:**

- `ANTHROPIC_API_KEY` (fallback Anthropic API): en Secrets Manager, rotación manual semestral.
- Aurora password: en Secrets Manager, rotación automática AWS cada 30 días.
- `NOTIFICATION_WEBHOOK_SECRET`: en Secrets Manager.
- `JWT_SECRET`: en Secrets Manager.
- Sin variables de entorno con credenciales en ECS task definitions. Solo referencias a
  Secrets Manager via `valueFrom`.

---

## Alternativas consideradas

### VPC con menos subnets (solo public + private)

Rechazada. La capa `private-data` aísla Aurora y los endpoints de secretos de los
containers de aplicación. Si un container ECS se compromete, no tiene acceso directo
a los endpoints de secretos desde la misma subnet. Este aislamiento es de bajo coste
(más CIDR blocks, no más recursos) y cumple con la defensa en profundidad de DORA art.9.

### AWS PrivateLink en lugar de VPC Endpoints

PrivateLink es la tecnología subyacente de VPC Endpoints Interface. Los endpoints que
listamos son PrivateLink bajo el capó. No aplica separar la decisión.

### WAF solo en ALB (sin CloudFront)

Posible, pero más caro (WAF en ALB se cobra por request de forma diferente) y sin los
beneficios de caché de CloudFront para assets estáticos. CloudFront + WAF en edge es el
patrón estándar para aplicaciones web en AWS.

---

## Trade-offs y consecuencias

| Trade-off                           | Impacto                                                                                                                                              |
| ----------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| NAT GW × 3 (~$110/mes)              | Coste fijo significativo, pero necesario para HA DORA. Alternativa: NAT Instance (EC2 t3.nano ~$10/mes) con menor fiabilidad — rechazada para banca. |
| VPC Endpoints (~$20/mes)            | Reducen egreso + simplifican compliance. El ahorro en data transfer y el beneficio de compliance justifican el coste.                                |
| Security Groups complejos           | Mitigado por CDK: los SGs se definen en código; el `NetworkStack` exporta referencias a los SGs para los stacks de compute y data.                   |
| TLS 1.3 obligatorio                 | Algunos clientes corporativos legacy usan TLS 1.2 (permitido). TLS 1.1 y anteriores: bloqueados.                                                     |
| SSM Session Manager requiere agente | Incluido en todas las AMIs Amazon Linux; en ECS Fargate requiere activar `enableExecuteCommand=true` en el task.                                     |
