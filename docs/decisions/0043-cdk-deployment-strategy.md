# ADR 0043 — Estrategia de despliegue con AWS CDK v2 Python

**Estado:** Accepted  
**Fecha:** 2026-05-13  
**Decisores:** Ignacio Bernal (Santander)  
**ADRs relacionados:** 0004 (CI/CD), 0036 (regiones), 0037 (multi-account), 0041 (networking),
0042 (persistencia), 0044 (DORA)  
**Sub-fases afectadas:** 9.1 – 9.5

---

## Contexto

El despliegue actual usa `docker-compose` en local. Para AWS necesitamos IaC que:
1. Sea reproducible y versionada en Git.
2. Soporte múltiples entornos (dev, pre, pro) desde la misma base de código.
3. Sea mantenible por un equipo Python sin expertise en HCL/Terraform.
4. Integre con los CDK Constructs nativos de AWS para AgentCore y Bedrock KB.
5. Soporte deploy desde CI/CD sin long-lived credentials.

---

## Decisión

### IaC: AWS CDK v2 Python (no Terraform)

| Criterio | CDK v2 Python | Terraform (HCL) |
|---|---|---|
| Lenguaje | Python — mismo que la app | HCL — lenguaje adicional |
| CDK Constructs nativos | ✅ AgentCore, KB, SageMaker serverless | ⚠️ Via terraform-aws-provider; lag en nuevos servicios |
| AgentCore CLI | ✅ CDK como resource manager nativo | ❌ No integrado |
| Type safety | ✅ mypy-compatible | ❌ Sin tipos |
| Testing IaC | ✅ `aws_cdk.assertions` + pytest | ⚠️ `terraform test` (menos maduro) |
| Estado remoto | CDK → CloudFormation (gestionado por AWS) | S3 + DynamoDB lock (self-managed) |
| Portabilidad multi-cloud | ❌ AWS only | ✅ Multi-cloud |
| Curva de aprendizaje equipo | Baja (Python conocido) | Media (HCL nuevo) |

**Trade-off de portabilidad:** el proyecto es AWS-first por decisión de arquitectura (ADR 0036).
La portabilidad multi-cloud no es un objetivo en Fase 9 ni en Fase 10. El coste de portabilidad
(CDK → Terraform) en el futuro hipotético es inferior al coste de aprender HCL y perder
los CDK Constructs nativos hoy.

### Ubicación: `infra/cdk/` en el repo existente

No se crea un repo separado `lex-agents-infra` en Fase 9. Justificación:
- El equipo es pequeño; la colocación del código IaC con el código de aplicación evita drift.
- Los cambios de aplicación y de infraestructura suelen ir juntos (e.g., nueva variable de
  entorno en el código + nuevo secret en Secrets Manager).
- Cuando la plataforma crezca (Fase 10, múltiples equipos), se puede extraer `infra/cdk/`
  a un repo separado `lex-agents-infra` sin cambios de arquitectura.

### Estructura del proyecto CDK

```
infra/cdk/
├── app.py                      # CDK App entrypoint; instancia los stacks por entorno
├── cdk.json                    # CDK context + feature flags
├── cdk.context.json            # Parámetros por entorno (generado, en .gitignore)
├── requirements.txt            # aws-cdk-lib>=2.140.0, constructs>=10.0.0, boto3
├── requirements-dev.txt        # pytest, aws-cdk.assertions, mypy
└── stacks/
    ├── __init__.py
    ├── config.py               # EnvironmentConfig dataclass (dev|pre|pro)
    ├── network_stack.py        # VPC, subnets, NAT GW, VPC Endpoints, TGW attachment
    ├── data_stack.py           # Aurora cluster, S3 buckets, KMS CMKs, Secrets Manager
    ├── compute_stack.py        # ECS cluster, ALB, CloudFront, WAF, ACM, ECR repos
    ├── agents_stack.py         # AgentCore Runtime, Gateway (MCP), Memory
    ├── kb_stack.py             # Bedrock KB, SageMaker Endpoints (bge-m3, reranker)
    ├── observability_stack.py  # CloudWatch, X-Ray, Langfuse ECS, Grafana ECS
    └── security_stack.py       # GuardDuty enablement, Security Hub, Config rules, Backup
```

### Configuración por entorno

`stacks/config.py` define la variación entre entornos:

```python
@dataclass
class EnvironmentConfig:
    env: Literal["dev", "pre", "pro"]
    account: str
    region: str = "eu-central-1"
    # Aurora
    aurora_min_acu: float = 0.0     # dev: auto-pause; pre/pro: 0.5
    aurora_max_acu: float = 8.0
    aurora_backup_days: int = 7     # dev: 7, pre: 35, pro: 35
    # ECS
    api_task_count: int = 2         # dev: 2, pre: 2, pro: 4
    api_cpu: int = 1024             # dev: 1024, pre: 2048, pro: 2048
    fargate_spot: bool = True       # dev: True, pre: False, pro: False
    # WAF
    waf_mode: str = "COUNT"         # dev: COUNT, pre/pro: BLOCK
    # Backups
    backup_vault_lock_days: int = 7  # dev: 7, pre: 35, pro = 2555 (7 años DORA)
```

`app.py` instancia los stacks para cada entorno:
```python
dev_config = EnvironmentConfig(env="dev", account=DEV_ACCOUNT_ID)
NetworkStack(app, "LexAgents-Dev-Network", config=dev_config, ...)
DataStack(app, "LexAgents-Dev-Data", config=dev_config, network_stack=net, ...)
...
```

### Orden de despliegue y dependencias entre stacks

```
NetworkStack
    │
    ▼
DataStack (depende de NetworkStack: subnets, SGs)
    │
    ├──► ComputeStack (depende de NetworkStack + DataStack: cluster, ALB, secrets)
    │
    ├──► AgentsStack (depende de NetworkStack + DataStack: AgentCore, Memory)
    │        │
    │        └──► KnowledgeBaseStack (depende de AgentsStack + DataStack: KB, SageMaker)
    │
    ├──► ObservabilityStack (depende de ComputeStack: CloudWatch, Langfuse ECS)
    │
    └──► SecurityStack (independiente: GuardDuty, Config, Backup policies)
```

CDK maneja las dependencias explícitas via `.add_dependency()` o referencias cruzadas
de outputs entre stacks.

### Pipeline de despliegue: GitHub Actions OIDC

Sin long-lived AWS credentials en CI/CD.

**Configuración OIDC:**
```yaml
# .github/workflows/deploy-dev.yml
permissions:
  id-token: write
  contents: read

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: arn:aws:iam::${{ vars.DEV_ACCOUNT_ID }}:role/GitHubActionsDeployRole
          aws-region: eu-central-1
      - run: cd infra/cdk && cdk deploy --all --require-approval never
```

**Rol `GitHubActionsDeployRole`** en cada cuenta workloads:
- Trust policy: `token.actions.githubusercontent.com` con condition `repo:ibernale/ai-lawyer:*`.
- Permissions: `AdministratorAccess` en dev (flexibilidad para iteración); scope reducido
  en pre/pro (solo stacks específicos).
- Se crea bootstrappeando CDK en cada cuenta: `cdk bootstrap --trust <management-account-id>`.

**Aprobación manual en pre/pro:**
- Workflow `deploy-pre.yml` tiene `environment: pre` con protection rule que requiere
  aprobación de un revisor antes de continuar.

### Testing de IaC

```python
# infra/cdk/tests/test_network_stack.py
from aws_cdk.assertions import Template

def test_vpc_has_three_azs():
    template = Template.from_stack(NetworkStack(app, "Test", config=dev_config))
    template.resource_count_is("AWS::EC2::Subnet", 9)  # 3 tipos × 3 AZs

def test_nat_gateway_per_az():
    template.resource_count_is("AWS::EC2::NatGateway", 3)
```

Tests ejecutados en CI con `uv run pytest infra/cdk/tests/ -v`.

---

## Trade-offs y consecuencias

| Trade-off | Impacto |
|---|---|
| CDK → CloudFormation state | El estado vive en CloudFormation (gestionado por AWS). No hay S3 backend que mantener. Downside: no hay `terraform state mv` para renombrar recursos sin destroy. |
| `infra/cdk/` en mismo repo | PRs que tocan tanto app como infra son visibles. Puede crecer el repo; mitigado con `.gitignore` para `cdk.out/` y `node_modules`. |
| CDK requiere Node.js para el CLI | `npm install -g aws-cdk` en CI. Alternativa: `pip install aws-cdk-cli` (Python wrapper). El código de los stacks es Python puro. |
| Testing de IaC con `cdk.assertions` | Solo verifica el template generado, no el comportamiento real en AWS. Complementar con smoke tests post-deploy. |
| Un stack por concern | 7 stacks con dependencias. Más despliegues en CI, pero fallos aislados. Orden de despliegue documentado arriba. |
