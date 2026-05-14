import { App } from "aws-cdk-lib";

export interface AccountConfig {
  management: string;
  logArchive: string;
  security: string;
  network: string;
  workloadsDev: string;
  workloadsPre?: string;
}

export function getAccounts(app: App): AccountConfig {
  const raw = app.node.tryGetContext("lexAgents:accounts");
  if (!raw) {
    throw new Error(
      'Missing CDK context "lexAgents:accounts". ' +
        "Copy cdk.context.json.example to cdk.context.json and fill in account IDs.",
    );
  }
  return raw as AccountConfig;
}
