import * as config from "aws-cdk-lib/aws-config";
import { Construct } from "constructs";

/**
 * ComplianceBaseline — applies a set of AWS Config managed rules
 * to enforce CIS Level 1 and DORA-required controls.
 * Add this construct to any workloads account stack.
 */
export class ComplianceBaseline extends Construct {
  constructor(scope: Construct, id: string) {
    super(scope, id);

    // S3 bucket public access check
    new config.ManagedRule(this, "S3BucketPublicRead", {
      identifier:
        config.ManagedRuleIdentifiers.S3_BUCKET_LEVEL_PUBLIC_ACCESS_PROHIBITED,
    });

    // KMS key rotation check
    new config.ManagedRule(this, "KmsKeyRotation", {
      identifier:
        config.ManagedRuleIdentifiers.CMK_BACKING_KEY_ROTATION_ENABLED,
    });

    // RDS encryption check
    new config.ManagedRule(this, "RdsEncrypted", {
      identifier: config.ManagedRuleIdentifiers.RDS_STORAGE_ENCRYPTED,
    });

    // EBS encryption check
    new config.ManagedRule(this, "EbsEncrypted", {
      identifier: config.ManagedRuleIdentifiers.EC2_EBS_ENCRYPTION_BY_DEFAULT,
    });

    // CloudTrail enabled
    new config.ManagedRule(this, "CloudTrailEnabled", {
      identifier: config.ManagedRuleIdentifiers.CLOUD_TRAIL_ENABLED,
    });

    // GuardDuty enabled
    new config.ManagedRule(this, "GuardDutyEnabled", {
      identifier: config.ManagedRuleIdentifiers.GUARDDUTY_ENABLED_CENTRALIZED,
    });

    // Secrets Manager rotation
    new config.ManagedRule(this, "SecretsManagerRotation", {
      identifier:
        config.ManagedRuleIdentifiers.SECRETSMANAGER_ROTATION_ENABLED_CHECK,
    });

    // Required tags: Environment, Owner, CostCenter
    new config.ManagedRule(this, "RequiredTags", {
      identifier: config.ManagedRuleIdentifiers.REQUIRED_TAGS,
      inputParameters: {
        tag1Key: "Environment",
        tag2Key: "Owner",
        tag3Key: "CostCenter",
      },
    });
  }
}
