# lex-agents AWS Architecture — Fase 9

## Multi-Account Structure

```mermaid
graph TB
    subgraph Management["Management Account (111...)"]
        ORG[AWS Organizations]
        IC[IAM Identity Center]
        SCPs[Service Control Policies]
    end

    subgraph LogArchive["Log Archive Account (222...)"]
        TRAIL[Org CloudTrail S3 WORM 7y]
        ATHENA[Athena Workgroup]
        FLOWLOGS[VPC Flow Logs]
    end

    subgraph Security["Security Account (333...)"]
        GD[GuardDuty Delegated Admin]
        SH[Security Hub]
        ALERTS[Security Alerts SNS]
        AM[Audit Manager - DORA]
    end

    subgraph Network["Network Account (444...)"]
        TGW[Transit Gateway Hub]
        HUB_VPC[Hub VPC 10.20.0.0/16]
        VPN[VPN / Direct Connect]
    end

    subgraph WorkloadsDev["Workloads-Dev Account (555...)"]
        subgraph DevVPC["Dev VPC 10.10.0.0/16"]
            ALB[Application Load Balancer]
            subgraph PrivateApp["Private-App Subnets"]
                ECS_API[ECS Fargate - API]
                ECS_WEB[ECS Fargate - Web]
                ECS_QDRANT[ECS Fargate - Qdrant]
                LANGFUSE[ECS Fargate - Langfuse]
            end
            subgraph PrivateData["Private-Data Subnets"]
                AURORA[Aurora Serverless v2 PG16]
                AURORA_LF[Aurora - Langfuse]
                EFS[EFS - Qdrant Storage]
            end
        end
        KMS[KMS CMKs x5]
        ECR[ECR - api, web]
        S3_RAW[S3 raw-ingest IA@30d Glacier@90d]
        S3_CAN[S3 canonical IA@60d]
        S3_EVALS[S3 evals]
        S3_BACK[S3 backups WORM 7y]
        SM[Secrets Manager]
        EVIDENCE[Lambda - evidence_collector]
        COMPLIANCE_BUCKET[S3 compliance-docs WORM 7y]
        OBS[ObservabilityStack - CW Alarms + Dashboards]
        COST[Cost Anomaly Detection]
    end

    subgraph WorkloadsPre["Workloads-Pre Account (REPLACE_ME)"]
        PRE_VPC[Pre VPC 10.11.0.0/16]
        PRE_KMS[KMS CMKs]
        PRE_AURORA[Aurora Serverless v2]
        PRE_ECR[ECR Repos]
    end

    Management --> LogArchive
    Management --> Security
    Management --> Network
    Management --> WorkloadsDev
    Management --> WorkloadsPre
    Network --> WorkloadsDev
    Network --> WorkloadsPre
    Security --> WorkloadsDev
    LogArchive --> TRAIL
```

## Legal Consultation Request Flow

```mermaid
sequenceDiagram
    participant U as User Browser
    participant CF as CloudFront
    participant ALB as ALB (public)
    participant WEB as ECS Web (Next.js)
    participant API as ECS API (FastAPI)
    participant QD as Qdrant
    participant AM as Anthropic Claude
    participant AURORA as Aurora PG

    U->>CF: GET /consulta
    CF->>ALB: Forward
    ALB->>WEB: Route /* to web
    WEB-->>U: React page
    U->>ALB: POST /api/v1/consult
    ALB->>API: Route /api/v1/*
    API->>QD: Vector search (top-k chunks)
    QD-->>API: Relevant chunks + metadata
    API->>AM: Claude API (system prompt + context + question)
    AM-->>API: Answer with citations
    API->>AURORA: Persist audit log entry
    API-->>U: {answer, citations, trace_id}
```

## Document Ingest Flow

```mermaid
sequenceDiagram
    participant EB as EventBridge Schedule
    participant SF as Step Functions
    participant L1 as Lambda fetch_raw
    participant L2 as Lambda format_sensor
    participant L3 as Lambda parse_canonical
    participant L4 as Lambda chunk_document
    participant L5 as Lambda contextualize_chunks
    participant S3R as S3 raw
    participant S3C as S3 canonical
    participant BKB as Bedrock Knowledge Base

    EB->>SF: Trigger daily pipeline (BOE / EUR-Lex)
    SF->>L1: Fetch raw documents
    L1->>S3R: Store raw PDFs/XML
    SF->>L2: Detect format changes
    SF->>L3: Parse to canonical JSON
    L3->>S3C: Store canonical
    SF->>L4: Chunk documents (512 tokens, 10% overlap)
    SF->>L5: Contextualize with Claude
    L5->>BKB: Upsert embeddings to Qdrant
```

## Observability Stack

```mermaid
graph LR
    CW_ALARMS[CW Alarms x7] --> SNS[SNS alerts-topic]
    SNS --> ROUTER[Lambda alert-router]
    ROUTER --> SLACK[Slack Webhook]
    EB[EventBridge] --> ROUTER

    subgraph Dashboards
        MAIN[lex-agents-dev main]
        PIPE[lex-agents-dev-pipeline]
        DORA_DASH[lex-agents-dev-dora]
        FINOPS[lex-agents-dev-finops]
    end

    LANGFUSE_UI[Langfuse UI] --> LF_AURORA[Langfuse Aurora]
    XRAY[X-Ray] --> XRAY_CONSOLE[X-Ray Console]
    EVIDENCE_L[evidence_collector Lambda] --> COMPLIANCE_S3[S3 compliance-docs]
    EVIDENCE_L --> CW_METRIC[CW ComplianceScore metric]
    CW_METRIC --> SCORE_ALARM[ComplianceScore < 90 Alarm]
    SCORE_ALARM --> SNS

    COST_MON[CE AnomalyMonitor] --> COST_SUB[CE AnomalySubscription]
    COST_SUB --> SNS
```

## Component Summary

| Component | Stack | Region | Purpose |
|-----------|-------|--------|---------|
| Aurora Serverless v2 PG16 | DataStack | eu-west-1 | Application DB with IAM auth |
| S3 raw-ingest | DataStack | eu-west-1 | Raw documents IA@30d, Glacier@90d |
| S3 canonical | DataStack | eu-west-1 | Normalised docs IA@60d |
| S3 backups | DataStack | eu-west-1 | WORM GOVERNANCE 7y, Glacier@30d |
| S3 compliance-docs | ComplianceStack | eu-west-1 | WORM COMPLIANCE 7y, evidence |
| ECS Cluster | AppServicesStack | eu-west-1 | Fargate Spot 75% api+web |
| Qdrant | AppServicesStack | eu-west-1 | Vector store on EFS (FARGATE only) |
| Langfuse | LangfuseStack | eu-west-1 | LLM observability (internal ALB) |
| evidence_collector | ComplianceStack | eu-west-1 | Daily DORA compliance checks |
| Cost Anomaly Monitor | ObservabilityStack | eu-west-1 | Spend anomaly detection |
| Org CloudTrail | LogArchiveStack | eu-west-1 | WORM COMPLIANCE 7y, Glacier@7d |
| GuardDuty | SecurityBaselineStack | eu-west-1 | Threat detection (security acct) |
| Audit Manager | SecurityBaselineStack | eu-west-1 | DORA quarterly assessment |
