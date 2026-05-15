import * as cdk from "aws-cdk-lib";
import { Aspects } from "aws-cdk-lib";
import { AwsSolutionsChecks, HIPAASecurityChecks } from "cdk-nag";

import { getAccounts } from "../lib/config/accounts";
import { PRIMARY_REGION, DR_REGION } from "../lib/config/environments";
import { OrganizationsStack } from "../lib/stacks/organizations";
import { IdentityCenterStack } from "../lib/stacks/identity-center";
import { KmsStack } from "../lib/stacks/kms";
import { LogArchiveStack } from "../lib/stacks/log-archive";
import { SecurityBaselineStack } from "../lib/stacks/security-baseline";
import { NetworkHubStack } from "../lib/stacks/network-hub";
import { NetworkSpokeStack } from "../lib/stacks/network-spoke";
import { GithubOidcStack } from "../lib/stacks/github-oidc";
import { AppEcrStack } from "../lib/stacks/app-ecr";
import { AppServicesStack } from "../lib/stacks/app-services";
import { DataStack } from "../lib/stacks/data";
import { ObservabilityStack } from "../lib/stacks/observability";
import { PipelinesStack } from "../lib/stacks/pipelines";
import { LangfuseStack } from "../lib/stacks/langfuse";
import { ComplianceStack } from "../lib/stacks/compliance";

const app = new cdk.App();
const accounts = getAccounts(app);

// ── Management account ────────────────────────────────────────────────────
const mgmtEnv = { account: accounts.management, region: PRIMARY_REGION };

new OrganizationsStack(app, "LexAgents-Organizations", { env: mgmtEnv });
new IdentityCenterStack(app, "LexAgents-IdentityCenter", { env: mgmtEnv });

// ── Log archive account ───────────────────────────────────────────────────
const logArchiveEnv = { account: accounts.logArchive, region: PRIMARY_REGION };

const logArchiveKms = new KmsStack(app, "LexAgents-LogArchive-Kms", {
  env: logArchiveEnv,
  envName: "logarchive",
  includeWorkloadKeys: false,
});

new LogArchiveStack(app, "LexAgents-LogArchive", {
  env: logArchiveEnv,
  drRegion: DR_REGION,
  kmsStack: logArchiveKms,
});

// ── Security account ──────────────────────────────────────────────────────
const securityEnv = { account: accounts.security, region: PRIMARY_REGION };

new SecurityBaselineStack(app, "LexAgents-SecurityBaseline", {
  env: securityEnv,
  managementAccountId: accounts.management,
});

// ── Network account ───────────────────────────────────────────────────────
const networkEnv = { account: accounts.network, region: PRIMARY_REGION };

new NetworkHubStack(app, "LexAgents-NetworkHub", { env: networkEnv });

// ── Workloads-dev account ─────────────────────────────────────────────────
const devEnv = { account: accounts.workloadsDev, region: PRIMARY_REGION };

const devKms = new KmsStack(app, "LexAgents-Dev-Kms", {
  env: devEnv,
  envName: "dev",
  includeWorkloadKeys: true,
});

const networkSpoke = new NetworkSpokeStack(app, "LexAgents-Dev-Network", {
  env: devEnv,
  envName: "dev",
  logArchiveAccountId: accounts.logArchive,
});

const devEcr = new AppEcrStack(app, "LexAgents-Dev-Ecr", {
  env: devEnv,
  envName: "dev",
});

const devData = new DataStack(app, "LexAgents-Dev-Data", {
  env: devEnv,
  envName: "dev",
  networkStack: networkSpoke,
  kmsStack: devKms,
});

const devLangfuse = new LangfuseStack(app, "LexAgents-Dev-Langfuse", {
  env: devEnv,
  envName: "dev",
  networkStack: networkSpoke,
});

const devApp = new AppServicesStack(app, "LexAgents-Dev-App", {
  env: devEnv,
  envName: "dev",
  networkStack: networkSpoke,
  ecrStack: devEcr,
  dataStack: devData,
  langfuseStack: devLangfuse,
});

const devPipelines = new PipelinesStack(app, "LexAgents-Dev-Pipelines", {
  env: devEnv,
  envName: "dev",
  networkStack: networkSpoke,
  dataStack: devData,
  appServicesStack: devApp,
});

const devObservability = new ObservabilityStack(
  app,
  "LexAgents-Dev-Observability",
  {
    env: devEnv,
    envName: "dev",
    networkStack: networkSpoke,
    appServicesStack: devApp,
    dataStack: devData,
    pipelinesStack: devPipelines,
  },
);

new GithubOidcStack(app, "LexAgents-Dev-GithubOidc", {
  env: devEnv,
  envName: "dev",
  githubRepo: "ibernale/ai-lawyer",
  githubBranch: "main",
});

// ── Compliance Stack (Fase 9.5) — DORA evidence collection ───────────────────
new ComplianceStack(app, "LexAgents-Dev-Compliance", {
  env: devEnv,
  envName: "dev",
  logsKey: devKms.logsKey,
  s3Key: devKms.s3Key!,
  alertTopic: devObservability.alertsTopic,
});

// ══════════════════════════════════════════════════════════════════════
// workloads-pre — infrastructure only, NO app deployed yet (Fase 9.5)
// ══════════════════════════════════════════════════════════════════════
const workloadsPreAccount = accounts.workloadsPre;
if (workloadsPreAccount && workloadsPreAccount !== "REPLACE_ME") {
  const preEnv = { account: workloadsPreAccount, region: PRIMARY_REGION };

  const kmsPreStack = new KmsStack(app, "KmsStackPre", {
    env: preEnv,
    envName: "pre",
    includeWorkloadKeys: true,
  });

  const networkPreStack = new NetworkSpokeStack(app, "NetworkSpokeStackPre", {
    env: preEnv,
    envName: "pre",
    logArchiveAccountId: accounts.logArchive,
  });

  const dataPreStack = new DataStack(app, "DataStackPre", {
    env: preEnv,
    envName: "pre",
    networkStack: networkPreStack,
    kmsStack: kmsPreStack,
  });
  dataPreStack.addDependency(networkPreStack);
  dataPreStack.addDependency(kmsPreStack);

  new AppEcrStack(app, "AppEcrStackPre", {
    env: preEnv,
    envName: "pre",
  });

  new GithubOidcStack(app, "GithubOidcStackPre", {
    env: preEnv,
    envName: "pre",
    githubRepo: "ibernale/ai-lawyer",
    githubBranch: "main",
  });
}

// cdk-nag: compliance checks on all stacks
Aspects.of(app).add(new AwsSolutionsChecks({ verbose: false }));
Aspects.of(app).add(new HIPAASecurityChecks({ verbose: false }));

app.synth();
