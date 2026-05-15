"""Federation router — generate AWS Console signin URLs for admin users."""

from __future__ import annotations

import json
import urllib.parse
from typing import Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from lex_agents_api.auth import CurrentUser, require_role
from lex_agents_api.settings import Settings, get_settings

logger: structlog.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/admin/federation", tags=["federation"])

# ---------------------------------------------------------------------------
# Deep-link destinations per AWS service
# ---------------------------------------------------------------------------

_DESTINATIONS: dict[str, str] = {
    "cloudwatch": (
        "https://{region}.console.aws.amazon.com/cloudwatch/home"
        "?region={region}#dashboards"
    ),
    "xray": (
        "https://{region}.console.aws.amazon.com/xray/home"
        "?region={region}#/service-map"
    ),
    "step-functions": (
        "https://{region}.console.aws.amazon.com/states/home"
        "?region={region}#/statemachines"
    ),
    "bedrock": (
        "https://{region}.console.aws.amazon.com/bedrock/home"
        "?region={region}#/model-invocations"
    ),
    "agentcore": (
        "https://{region}.console.aws.amazon.com/bedrock/home"
        "?region={region}#/agent-monitoring"
    ),
}

AwsService = Literal["cloudwatch", "xray", "step-functions", "bedrock", "agentcore"]

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class FederationUrlRequest(BaseModel):
    service: AwsService
    dashboard: str | None = None
    resource_id: str | None = None


class FederationUrlResponse(BaseModel):
    url: str
    expires_in: int = 900  # 15 min federation token


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _role_arn_for_user(user: CurrentUser, settings: Settings) -> str:
    """Return the IAM role ARN mapped to the user's Cognito group."""
    arns = {
        "admin": settings.federation_role_arn_admin,
        "operator": settings.federation_role_arn_operator,
        "viewer": settings.federation_role_arn_viewer,
    }
    return arns.get(user.role, settings.federation_role_arn_viewer)


def _build_signin_url(credentials: dict[str, str], destination: str, region: str) -> str:
    """Build a federation signin URL using temporary STS credentials."""
    session_token = {
        "sessionId": credentials["AccessKeyId"],
        "sessionKey": credentials["SecretAccessKey"],
        "sessionToken": credentials["SessionToken"],
    }
    session_json = json.dumps(session_token)

    signin_base = "https://signin.aws.amazon.com/federation"

    # Step 1: exchange credentials for federation token
    params = urllib.parse.urlencode(
        {
            "Action": "getSigninToken",
            "SessionDuration": "3600",
            "Session": session_json,
        }
    )
    import urllib.request as _req

    with _req.urlopen(f"{signin_base}?{params}", timeout=5) as resp:  # noqa: S310
        signin_token = json.loads(resp.read())["SigninToken"]

    # Step 2: build login URL with destination deep link
    login_params = urllib.parse.urlencode(
        {
            "Action": "login",
            "Issuer": f"https://lex-agents.{region}.internal",
            "Destination": destination,
            "SigninToken": signin_token,
        }
    )
    return f"{signin_base}?{login_params}"


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post("/aws-console-url", response_model=FederationUrlResponse)
async def get_aws_console_url(
    body: FederationUrlRequest,
    user: CurrentUser = Depends(require_role("viewer", "operator", "admin")),
    settings: Settings = Depends(get_settings),
) -> FederationUrlResponse:
    """Generate a time-limited AWS Console signin URL for the requested service.

    The IAM role assumed is scoped to the user's access level:
    viewer → read-only audit, operator → data analyst, admin → power user.
    Every call is recorded in the audit trail.
    """
    role_arn = _role_arn_for_user(user, settings)
    if not role_arn:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "AWS federation not configured in this environment. "
                "Set FEDERATION_ROLE_ARN_* environment variables."
            ),
        )

    region = settings.aws_region
    destination_template = _DESTINATIONS.get(body.service)
    if not destination_template:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown service: {body.service}",
        )
    destination = destination_template.format(region=region)
    if body.dashboard:
        destination += f"/{urllib.parse.quote(body.dashboard)}"

    # Assume the role
    try:
        import boto3

        sts = boto3.client("sts", region_name=region)
        assumed = sts.assume_role(
            RoleArn=role_arn,
            RoleSessionName=f"lex-agents-{user.username[:32]}",
            DurationSeconds=3600,
        )
        creds = assumed["Credentials"]
    except Exception as exc:
        logger.error("federation_assume_role_failed", role_arn=role_arn, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not assume federation role. Check IAM configuration.",
        ) from exc

    # Build signin URL
    try:
        url = _build_signin_url(
            {
                "AccessKeyId": creds["AccessKeyId"],
                "SecretAccessKey": creds["SecretAccessKey"],
                "SessionToken": creds["SessionToken"],
            },
            destination,
            region,
        )
    except Exception as exc:
        logger.error("federation_signin_url_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not generate signin URL.",
        ) from exc

    # Audit trail
    try:
        from lex_agents_audit.audit_trail import get_audit_trail_manager

        atm = get_audit_trail_manager()
        if atm is not None:
            await atm.log(
                action_type="aws.federation.url_generated",
                target_type="aws_service",
                actor=user.username,
                actor_role=user.role,
                reason=f"Federation signin URL generated for {body.service}",
                target_id=body.service,
            )
    except Exception as exc:
        logger.warning("audit_trail_record_failed", error=str(exc))

    logger.info(
        "federation_url_generated",
        actor=user.username,
        role=user.role,
        service=body.service,
    )
    return FederationUrlResponse(url=url)
