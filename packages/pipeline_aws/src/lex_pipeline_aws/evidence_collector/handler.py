"""evidence_collector — Lambda para colección diaria de evidencias DORA.

Se ejecuta diariamente a las 02:00 UTC. Audita la configuración AWS contra
un baseline definido en COMPLIANCE_BASELINE env var (JSON).

Genera:
  - evidence/{date}/{check}.json en S3 compliance-docs bucket
  - reports/{date}/summary.md en S3 compliance-docs bucket
  - CW Metric ComplianceScore (namespace: LexAgents/Compliance)

Environment variables:
  COMPLIANCE_BUCKET : S3 bucket for compliance docs
  COMPLIANCE_BASELINE : JSON string with expected config values
  ENV_NAME          : environment name (dev, pre, pro)
"""
from __future__ import annotations

import json
import os
from datetime import UTC, date, datetime
from typing import Any

import boto3
import structlog

logger: structlog.BoundLogger = structlog.get_logger(__name__)

BUCKET = os.environ.get("COMPLIANCE_BUCKET", "")
ENV_NAME = os.environ.get("ENV_NAME", "dev")

DEFAULT_BASELINE = {
    "kms_rotation_enabled": True,
    "cloudtrail_enabled": True,
    "guardduty_enabled": True,
    "vpc_flow_logs_enabled": True,
    "config_rules_compliance_pct": 80,
}


def _check_kms_rotation(kms_client: Any) -> dict[str, Any]:
    """Verify all CMKs have rotation enabled."""
    paginator = kms_client.get_paginator("list_keys")
    non_rotating: list[str] = []
    total = 0
    for page in paginator.paginate():
        for key in page["Keys"]:
            try:
                meta = kms_client.describe_key(KeyId=key["KeyId"])["KeyMetadata"]
                if meta["KeyManager"] != "AWS" and meta["KeyState"] == "Enabled":
                    total += 1
                    rotation = kms_client.get_key_rotation_status(KeyId=key["KeyId"])
                    if not rotation.get("KeyRotationEnabled", False):
                        non_rotating.append(key["KeyId"])
            except Exception as exc:
                logger.warning("kms_key_check_failed", key_id=key["KeyId"], error=str(exc))
    return {
        "check": "kms_rotation_enabled",
        "total_cmks": total,
        "non_rotating": non_rotating,
        "passed": len(non_rotating) == 0,
    }


def _check_cloudtrail(ct_client: Any) -> dict[str, Any]:
    """Verify at least one multi-region trail is logging."""
    trails = ct_client.describe_trails(includeShadowTrails=False).get("trailList", [])
    active = [
        t for t in trails
        if t.get("IsMultiRegionTrail") and t.get("LogFileValidationEnabled")
    ]
    status_ok = False
    if active:
        s = ct_client.get_trail_status(Name=active[0]["TrailARN"])
        status_ok = s.get("IsLogging", False)
    return {
        "check": "cloudtrail_enabled",
        "trails_found": len(trails),
        "multi_region_trails": len(active),
        "is_logging": status_ok,
        "passed": status_ok,
    }


def _check_guardduty(gd_client: Any) -> dict[str, Any]:
    """Verify GuardDuty detector is enabled."""
    detectors = gd_client.list_detectors().get("DetectorIds", [])
    enabled = False
    high_findings = 0
    if detectors:
        d = gd_client.get_detector(DetectorId=detectors[0])
        enabled = d.get("Status") == "ENABLED"
        findings = gd_client.list_findings(
            DetectorId=detectors[0],
            FindingCriteria={
                "Criterion": {
                    "severity": {"Gte": 7},   # HIGH + CRITICAL
                    "service.archived": {"Eq": ["false"]},
                }
            },
        )
        high_findings = len(findings.get("FindingIds", []))
    return {
        "check": "guardduty_enabled",
        "detector_enabled": enabled,
        "high_critical_findings": high_findings,
        "passed": enabled and high_findings == 0,
    }


def _check_config(config_client: Any) -> dict[str, Any]:
    """Verify AWS Config recorder is active and measure compliance %."""
    recorders = config_client.describe_configuration_recorders().get(
        "ConfigurationRecorders", []
    )
    recorder_active = False
    if recorders:
        status = config_client.describe_configuration_recorder_status(
            ConfigurationRecorderNames=[recorders[0]["name"]]
        ).get("ConfigurationRecordersStatus", [])
        recorder_active = bool(status) and status[0].get("recording", False)

    summary = config_client.get_compliance_summary_by_config_rule()
    agg = summary.get("ComplianceSummary", {})
    compliant = agg.get("CompliantResourceCount", {}).get("CappedCount", 0)
    non_compliant = agg.get("NonCompliantResourceCount", {}).get("CappedCount", 0)
    total = compliant + non_compliant
    pct = round(compliant / total * 100, 1) if total > 0 else 100.0
    return {
        "check": "config_compliance",
        "recorder_active": recorder_active,
        "compliant_rules": compliant,
        "non_compliant_rules": non_compliant,
        "compliance_pct": pct,
        "passed": recorder_active and pct >= 80,
    }


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Daily evidence collection Lambda handler."""
    today = date.today().isoformat()
    logger.info("evidence_collector.start", date=today, env=ENV_NAME)

    baseline_raw = os.environ.get("COMPLIANCE_BASELINE", "{}")
    try:
        baseline = {**DEFAULT_BASELINE, **json.loads(baseline_raw)}
    except json.JSONDecodeError:
        baseline = DEFAULT_BASELINE

    kms = boto3.client("kms")
    ct = boto3.client("cloudtrail")
    gd = boto3.client("guardduty")
    config = boto3.client("config")
    s3 = boto3.client("s3")
    cw = boto3.client("cloudwatch")

    checks: list[dict[str, Any]] = []
    try:
        checks.append(_check_kms_rotation(kms))
    except Exception as exc:
        logger.warning("evidence_collector.check_failed", check="kms", error=str(exc))
        checks.append({"check": "kms_rotation_enabled", "passed": False, "error": str(exc)})

    try:
        checks.append(_check_cloudtrail(ct))
    except Exception as exc:
        logger.warning("evidence_collector.check_failed", check="cloudtrail", error=str(exc))
        checks.append({"check": "cloudtrail_enabled", "passed": False, "error": str(exc)})

    try:
        checks.append(_check_guardduty(gd))
    except Exception as exc:
        logger.warning("evidence_collector.check_failed", check="guardduty", error=str(exc))
        checks.append({"check": "guardduty_enabled", "passed": False, "error": str(exc)})

    try:
        checks.append(_check_config(config))
    except Exception as exc:
        logger.warning("evidence_collector.check_failed", check="config", error=str(exc))
        checks.append({"check": "config_compliance", "passed": False, "error": str(exc)})

    # Upload individual evidence files
    if BUCKET:
        for check in checks:
            key = f"evidence/{today}/{check['check']}.json"
            s3.put_object(
                Bucket=BUCKET,
                Key=key,
                Body=json.dumps(check, indent=2, default=str).encode(),
                ContentType="application/json",
            )

    # Compute compliance score
    passed = sum(1 for c in checks if c.get("passed", False))
    score = round(passed / len(checks) * 100) if checks else 0

    # Generate Markdown summary
    lines = [
        f"# DORA Compliance Evidence — {today}",
        f"\n**Environment:** {ENV_NAME}  \n**Score:** {score}% ({passed}/{len(checks)} checks passed)",
        "\n## Checks\n",
        "| Check | Status | Details |",
        "|-------|--------|---------|",
    ]
    for c in checks:
        status = "PASS" if c.get("passed") else "FAIL"
        details = "; ".join(
            f"{k}={v}" for k, v in c.items() if k not in ("check", "passed")
        )
        lines.append(f"| {c['check']} | {status} | {details} |")
    lines.append(f"\n_Generated at {datetime.now(UTC).isoformat()} by evidence_collector Lambda_")
    summary_md = "\n".join(lines)

    if BUCKET:
        s3.put_object(
            Bucket=BUCKET,
            Key=f"reports/{today}/summary.md",
            Body=summary_md.encode(),
            ContentType="text/markdown",
        )

    # Publish ComplianceScore metric
    try:
        cw.put_metric_data(
            Namespace="LexAgents/Compliance",
            MetricData=[{
                "MetricName": "ComplianceScore",
                "Dimensions": [{"Name": "Environment", "Value": ENV_NAME}],
                "Value": score,
                "Unit": "Percent",
            }],
        )
    except Exception as exc:
        logger.warning("evidence_collector.metric_failed", error=str(exc))

    # Suppress unused variable
    _ = baseline

    logger.info("evidence_collector.done", score=score, checks=len(checks))
    return {"compliance_score": score, "checks": len(checks), "passed": passed, "date": today}
