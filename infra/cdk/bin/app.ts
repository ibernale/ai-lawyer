import * as cdk from 'aws-cdk-lib';
import { Aspects } from 'aws-cdk-lib';
import { AwsSolutionsChecks, HIPAASecurityChecks } from 'cdk-nag';

import { getAccounts } from '../lib/config/accounts';
import { PRIMARY_REGION, DR_REGION } from '../lib/config/environments';
import { OrganizationsStack } from '../lib/stacks/organizations';
import { IdentityCenterStack } from '../lib/stacks/identity-center';
import { KmsStack } from '../lib/stacks/kms';
import { LogArchiveStack } from '../lib/stacks/log-archive';
import { SecurityBaselineStack } from '../lib/stacks/security-baseline';
import { NetworkHubStack } from '../lib/stacks/network-hub';
import { NetworkSpokeStack } from '../lib/stacks/network-spoke';
import { GithubOidcStack } from '../lib/stacks/github-oidc';
import { AppEcrStack } from '../lib/stacks/app-ecr';
import { AppServicesStack } from '../lib/stacks/app-services';

const app = new cdk.App();
const accounts = getAccounts(app);

// ── Management account ────────────────────────────────────────────────────
const mgmtEnv = { account: accounts.management, region: PRIMARY_REGION };

new OrganizationsStack(app, 'LexAgents-Organizations', { env: mgmtEnv });
new IdentityCenterStack(app, 'LexAgents-IdentityCenter', { env: mgmtEnv });

// ── Log archive account ───────────────────────────────────────────────────
const logArchiveEnv = { account: accounts.logArchive, region: PRIMARY_REGION };

const logArchiveKms = new KmsStack(app, 'LexAgents-LogArchive-Kms', {
  env: logArchiveEnv,
  envName: 'logarchive',
  includeWorkloadKeys: false,
});

new LogArchiveStack(app, 'LexAgents-LogArchive', {
  env: logArchiveEnv,
  drRegion: DR_REGION,
  kmsStack: logArchiveKms,
});

// ── Security account ──────────────────────────────────────────────────────
const securityEnv = { account: accounts.security, region: PRIMARY_REGION };

new SecurityBaselineStack(app, 'LexAgents-SecurityBaseline', {
  env: securityEnv,
  managementAccountId: accounts.management,
});

// ── Network account ───────────────────────────────────────────────────────
const networkEnv = { account: accounts.network, region: PRIMARY_REGION };

new NetworkHubStack(app, 'LexAgents-NetworkHub', { env: networkEnv });

// ── Workloads-dev account ─────────────────────────────────────────────────
const devEnv = { account: accounts.workloadsDev, region: PRIMARY_REGION };

// devKms is retained for future DataStack in Fase 9.2
const _devKms = new KmsStack(app, 'LexAgents-Dev-Kms', {
  env: devEnv,
  envName: 'dev',
  includeWorkloadKeys: true,
});

const networkSpoke = new NetworkSpokeStack(app, 'LexAgents-Dev-Network', {
  env: devEnv,
  envName: 'dev',
  logArchiveAccountId: accounts.logArchive,
});

const devEcr = new AppEcrStack(app, 'LexAgents-Dev-Ecr', {
  env: devEnv,
  envName: 'dev',
});

new AppServicesStack(app, 'LexAgents-Dev-App', {
  env: devEnv,
  envName: 'dev',
  networkStack: networkSpoke,
  ecrStack: devEcr,
});

new GithubOidcStack(app, 'LexAgents-Dev-GithubOidc', {
  env: devEnv,
  envName: 'dev',
  githubRepo: 'ibernale/ai-lawyer',
  githubBranch: 'main',
});

// cdk-nag: compliance checks on all stacks
Aspects.of(app).add(new AwsSolutionsChecks({ verbose: false }));
Aspects.of(app).add(new HIPAASecurityChecks({ verbose: false }));

app.synth();
