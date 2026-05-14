export const PRIMARY_REGION = "eu-west-1";
export const DR_REGION = "eu-west-1";

export interface WorkloadVpcConfig {
  vpcCidr: string;
  azs: string[];
  publicSubnets: string[];
  privateAppSubnets: string[];
  privateDataSubnets: string[];
}

export const DEV_VPC_CONFIG: WorkloadVpcConfig = {
  vpcCidr: "10.10.0.0/16",
  azs: ["eu-west-1a", "eu-west-1b", "eu-west-1c"],
  publicSubnets: ["10.10.0.0/24", "10.10.1.0/24", "10.10.2.0/24"],
  privateAppSubnets: ["10.10.10.0/24", "10.10.11.0/24", "10.10.12.0/24"],
  privateDataSubnets: ["10.10.20.0/24", "10.10.21.0/24", "10.10.22.0/24"],
};

export const PRE_VPC_CONFIG: WorkloadVpcConfig = {
  vpcCidr: "10.11.0.0/16",
  azs: ["eu-central-1a", "eu-central-1b", "eu-central-1c"],
  publicSubnets: ["10.11.0.0/24", "10.11.1.0/24", "10.11.2.0/24"],
  privateAppSubnets: ["10.11.10.0/24", "10.11.11.0/24", "10.11.12.0/24"],
  privateDataSubnets: ["10.11.20.0/24", "10.11.21.0/24", "10.11.22.0/24"],
};

export const HUB_VPC_CIDR = "10.20.0.0/16";

// KMS key aliases per environment
export const KMS_ALIASES = {
  rds: (env: string) => `/alias/lex-agents-${env}-rds`,
  s3: (env: string) => `/alias/lex-agents-${env}-s3`,
  secrets: (env: string) => `/alias/lex-agents-${env}-secrets`,
  logs: (env: string) => `/alias/lex-agents-${env}-logs`,
  ebs: (env: string) => `/alias/lex-agents-${env}-ebs`,
} as const;
