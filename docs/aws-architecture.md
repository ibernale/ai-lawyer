# Arquitectura AWS — lex-agents Fase 9

Diagrama de arquitectura objetivo para el despliegue bancario en AWS.
Región primaria: `eu-central-1` (Frankfurt). Región secundaria: `eu-west-1` (Irlanda).

Ver ADRs 0036–0045 para las decisiones que sustentan cada componente.

---

## 1. AWS Organizations — estructura de cuentas

```mermaid
graph TD
    ROOT["🏢 root / management<br/>Organizations · Control Tower<br/>Facturación consolidada · SCPs"]

    ROOT --> LA["📦 log-archive<br/>CloudTrail org-wide<br/>VPC Flow Logs<br/>S3 Object Lock WORM<br/>Retención 7 años"]
    ROOT --> SEC["🔒 security<br/>GuardDuty aggregator<br/>Security Hub<br/>AWS Config aggregator<br/>Audit Manager"]
    ROOT --> NET["🌐 network<br/>Transit Gateway hub<br/>Route53 Resolver<br/>VPC Endpoints centralizados"]
    ROOT --> DEV["💻 workloads-dev<br/>Fase 9.1–9.5<br/>ECS · AgentCore · Aurora<br/>Bedrock KB · Observabilidad"]
    ROOT --> PRE["🧪 workloads-pre<br/>Provisionado en Fase 9.5<br/>Sin workloads todavía"]
    ROOT --> PRO["🚀 workloads-pro<br/>NO en Fase 9<br/>Upgrade path Fase 10"]

    style PRO fill:#eee,stroke:#bbb,color:#999
    style ROOT fill:#232f3e,color:#fff,stroke:#232f3e
    style LA fill:#3f8624,color:#fff
    style SEC fill:#dd3522,color:#fff
    style NET fill:#8c4fff,color:#fff
    style DEV fill:#1a73e8,color:#fff
    style PRE fill:#0093d1,color:#fff
```

---

## 2. VPC — topología de red (workloads-dev, eu-central-1)

```mermaid
graph TB
    subgraph INTERNET["☁️ Internet"]
        USER["👤 Usuario\n(HTTPS)"]
    end

    subgraph CF["CloudFront + WAF edge (us-east-1)"]
        CDN["CloudFront Distribution\nWAF: CRS + SQLi + RateLimit\nACM Certificate"]
    end

    subgraph VPC["VPC 10.0.0.0/16 — eu-central-1 (3 AZs)"]
        subgraph PUB["Subnets Public (ALB + NAT GW)"]
            ALB["Application Load Balancer\nTLS 1.3 · HTTPS only"]
            NAT["NAT Gateway × 3\n(1 por AZ)"]
        end

        subgraph APP["Subnets Private-App (ECS + AgentCore + Lambda)"]
            APITASK["ECS Fargate\nlex-agents API\n(FastAPI :8000)"]
            WEBTASK["ECS Fargate\nlex-agents Web\n(Next.js :3000)"]
            AC["AgentCore Runtime\nOrchestratorV2\nPlanner/Maker/Judge"]
            LAMBDA["Lambda (VPC)\nTools: search_rag\nverify_citations\nkill_switch_check"]
        end

        subgraph DATA["Subnets Private-Data (Aurora + Endpoints)"]
            AURORA["Aurora Serverless v2\nPostgreSQL 16 + pgvector\nKMS CMK encrypted"]
            EPBR["VPC Endpoint\nBedrock Runtime"]
            EPKMS["VPC Endpoint\nKMS · Secrets Manager\nECR · CloudWatch"]
            EPS3["VPC Endpoint (GW)\nS3"]
        end
    end

    subgraph AWS_MANAGED["Servicios AWS gestionados (eu-central-1)"]
        BEDROCK["Amazon Bedrock\nClaude Opus 4.7\nSonnet 4.6 · Haiku 4.5"]
        BEDROCKC["Amazon Bedrock\nKnowledge Bases\n(Custom Chunking)"]
        SAGEMAKEREP["SageMaker Serverless\nbge-m3 embedder\nbge-reranker-v2-m3"]
        SM["Secrets Manager\nANTHROPIC_API_KEY\nJWT_SECRET · DB_PASSWORD"]
    end

    subgraph S3_BUCKETS["S3 (eu-central-1)"]
        S3RAW["lex-agents-raw-dev\nBOE XML · EUR-Lex XML"]
        S3CAN["lex-agents-canonical-dev\nChunks JSON"]
        S3BCK["lex-agents-backups-dev\nObject Lock WORM"]
    end

    USER -->|HTTPS| CDN
    CDN -->|HTTPS| ALB
    ALB --> APITASK
    ALB --> WEBTASK
    APITASK --> AC
    APITASK --> AURORA
    AC --> LAMBDA
    AC --> EPBR --> BEDROCK
    LAMBDA --> BEDROCKC
    BEDROCKC --> AURORA
    BEDROCKC --> SAGEMAKEREP
    APITASK --> EPKMS --> SM
    APITASK --> EPS3 --> S3BCK
    AC --> EPS3

    style VPC fill:#f0f7ff,stroke:#1a73e8
    style PUB fill:#fff3e0,stroke:#f57c00
    style APP fill:#e8f5e9,stroke:#388e3c
    style DATA fill:#fce4ec,stroke:#c62828
    style AWS_MANAGED fill:#fff8e1,stroke:#f9a825
    style S3_BUCKETS fill:#f3e5f5,stroke:#7b1fa2
```

---

## 3. Flujo de una consulta jurídica (end-to-end)

```mermaid
sequenceDiagram
    participant U as 👤 Usuario
    participant CF as CloudFront + WAF
    participant API as ECS API (FastAPI)
    participant AC as AgentCore Runtime
    participant GW as AgentCore Gateway (MCP)
    participant KB as Bedrock KB
    participant LLM as Bedrock LLM
    participant DB as Aurora pgvector

    U->>CF: POST /api/v1/consult (HTTPS)
    CF->>API: Request validada (WAF pass)
    API->>API: Auth JWT · Kill switch check
    API->>AC: ConsultRequest (depth, query)

    Note over AC: Session isolation microVM

    AC->>LLM: Planner.plan() — Claude Opus
    LLM-->>AC: PlannerOutput (branches, jurisdictions)

    AC->>GW: search_rag(expanded_query, filters)
    GW->>KB: RetrieveAndGenerate API
    KB->>DB: HNSW vector search + BM25
    DB-->>KB: Top-K chunks
    KB-->>GW: Reranked chunks
    GW-->>AC: AssembledContext + CitationMapping

    AC->>LLM: Specialist.run_async() — Claude Sonnet
    LLM-->>AC: AgentResponse (answer, citations)

    AC->>GW: verify_citations(answer, citations, chunks)
    GW->>LLM: CitationVerifierLLM — Claude Haiku
    LLM-->>GW: VerificationReport
    GW-->>AC: VerificationReport

    AC-->>API: ConsultResponse
    API->>DB: Store consultation (audit)
    API-->>U: JSON response (HTTPS)
```

---

## 4. Flujo de ingesta de documentos legales

```mermaid
flowchart LR
    BOE["BOE XML API\nboe.es"] -->|fetch| DAGSTER
    EURLEX["EUR-Lex Cellar API\nboe.es"] -->|fetch| DAGSTER

    subgraph DAGSTER["Dagster (ECS Fargate)"]
        FETCH["BoeSource.fetch()\nEurLexSource.fetch()"]
        PARSE["parse_to_canonical()\nCanonicalDocument"]
    end

    DAGSTER -->|raw XML| S3RAW["S3: lex-agents-raw-dev"]
    DAGSTER -->|canonical JSON| S3CAN["S3: lex-agents-canonical-dev"]
    S3CAN -->|S3 event| KB_JOB

    subgraph KB_JOB["Bedrock KB Ingestion Job"]
        CUSTOM["Custom Chunking Hook"]
    end

    CUSTOM -->|invoke| LAMBDA

    subgraph LAMBDA["Lambda: LegalChunker"]
        CHUNKER["LegalChunker\n(packages/ingest/)"]
        CTX["Contextualizer\n(Claude Haiku)"]
    end

    LAMBDA -->|chunks + context| EMBED

    subgraph EMBED["SageMaker Serverless"]
        BGE["bge-m3 embedder\n1024-dim dense + sparse"]
    end

    EMBED -->|vectors| AURORA["Aurora pgvector\nlegal_chunks table"]

    style DAGSTER fill:#fff3e0,stroke:#f57c00
    style KB_JOB fill:#e8f5e9,stroke:#388e3c
    style LAMBDA fill:#e3f2fd,stroke:#1565c0
    style EMBED fill:#fce4ec,stroke:#c62828
    style AURORA fill:#f3e5f5,stroke:#7b1fa2
```

---

## 5. Stack de observabilidad

```mermaid
graph LR
    subgraph SOURCES["Fuentes de telemetría"]
        ECS_API["ECS API\n(OTel SDK)"]
        AC_OBS["AgentCore\nObservability"]
        AURORA_MON["Aurora\nEnhanced Monitoring"]
    end

    subgraph COLLECT["Recolección"]
        OTEL["OTel Collector\n(ECS sidecar)"]
        CW_AGENT["CloudWatch Agent"]
    end

    subgraph STORE["Almacenamiento"]
        CW_LOGS["CloudWatch Logs\nStructlog JSON"]
        CW_METRICS["CloudWatch Metrics\nPrometheus-compat"]
        XRAY["AWS X-Ray\nDistributed traces"]
        LANGFUSE["Langfuse\n(ECS self-hosted)\nPrompt management\nEval replay"]
    end

    subgraph VIZ["Visualización y alertas"]
        GRAFANA["Grafana\n(ECS self-hosted)\nDashboards\nAlertas Tier 1/2"]
        CW_INS["CloudWatch\nLogs Insights\nAd-hoc queries"]
    end

    ECS_API -->|OTLP gRPC| OTEL
    AC_OBS -->|traces| OTEL
    OTEL -->|traces| XRAY
    OTEL -->|metrics| CW_METRICS
    OTEL -->|traces + spans| LANGFUSE
    ECS_API -->|structlog JSON| CW_LOGS
    AURORA_MON --> CW_AGENT --> CW_METRICS
    CW_METRICS --> GRAFANA
    CW_LOGS --> CW_INS
    CW_LOGS --> GRAFANA
    XRAY --> GRAFANA
```

---

## 6. Stack de seguridad y DR

```mermaid
graph TD
    subgraph DETECT["Detección (cuenta security)"]
        GD["GuardDuty\nThreat detection ML\nAll accounts aggregator"]
        SH["Security Hub\nCIS Benchmark\nCompliance score"]
        CONFIG["AWS Config\nResource inventory\nCompliance rules"]
    end

    subgraph LOG["Logging inmutable (cuenta log-archive)"]
        CT["CloudTrail\nOrganization-wide\nMgmt + data events"]
        VFL["VPC Flow Logs\nAll workload VPCs"]
        S3WORM["S3 Object Lock\nWORM Compliance\nRetención 7 años"]
    end

    subgraph BACKUP["Backup y DR"]
        AWSBKP["AWS Backup\nAurora PITR 35d\nCross-region eu-west-1"]
        S3REP["S3 Replication\neu-central-1 → eu-west-1"]
        DRPLAN["DR Plan\ndocs/runbook.md\nRTO ≤ 4h · RPO ≤ 1h"]
    end

    subgraph INCIDENT["Respuesta a incidentes"]
        IM["AWS Incident Manager\nP1/P2 playbooks\nTimeline para DORA notif."]
        SNS["SNS\nAlertas críticas\n→ email + Grafana webhook"]
    end

    GD --> SH
    SH --> IM
    CT --> S3WORM
    VFL --> S3WORM
    AWSBKP --> S3REP
    IM --> SNS

    style DETECT fill:#fce4ec,stroke:#c62828
    style LOG fill:#e8f5e9,stroke:#388e3c
    style BACKUP fill:#e3f2fd,stroke:#1565c0
    style INCIDENT fill:#fff3e0,stroke:#f57c00
```

---

## Referencias

| Componente | ADR |
|---|---|
| Regiones y residencia de datos | [ADR 0036](decisions/0036-aws-regions-data-residency.md) |
| Estructura multi-account | [ADR 0037](decisions/0037-aws-multi-account.md) |
| AgentCore Runtime | [ADR 0038](decisions/0038-agentcore-runtime.md) |
| Bedrock como provider LLM | [ADR 0039](decisions/0039-bedrock-llm-provider.md) |
| RAG en AWS (Bedrock KB + Aurora pgvector) | [ADR 0040](decisions/0040-rag-aws-bedrock-kb.md) |
| Networking y seguridad | [ADR 0041](decisions/0041-aws-networking-security.md) |
| Persistencia y estado | [ADR 0042](decisions/0042-aws-persistence.md) |
| CDK deployment strategy | [ADR 0043](decisions/0043-cdk-deployment-strategy.md) |
| DORA controls mapping | [ADR 0044](decisions/0044-dora-controls-mapping.md) |
| Cost model fase inicial | [ADR 0045](decisions/0045-cost-model-fase-inicial.md) |
