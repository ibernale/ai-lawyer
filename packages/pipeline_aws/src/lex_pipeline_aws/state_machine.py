"""Step Functions ASL state machine definition for the ingest pipeline (ADR 0047).

The state machine JSON is generated at CDK synth time by PipelineStack.
This module provides the Python-side helper to build the ASL dict given
Lambda ARNs and ECS configuration.

Pipeline flow:
  FetchRaw (Lambda)
    → ParseCanonical (Lambda)
    → ChunkDocument (Lambda)
    → ContextualizeChunks (Lambda)
    → EmbedChunks (ECS RunTask)
    → IndexToQdrant (ECS RunTask)
    → Done

Error handling:
  - All Lambda states: Retry 2× with exponential backoff (interval 30s, backoff 2×)
  - All Lambda states: Catch → PipelineFailed state
  - ECS RunTask states: no retry (ECS task retries internally); Catch → PipelineFailed
"""

from __future__ import annotations

from typing import Any


def build_asl(
    *,
    fetch_raw_arn: str,
    parse_canonical_arn: str,
    chunk_document_arn: str,
    contextualize_chunks_arn: str,
    embed_chunks_task_definition_arn: str,
    index_to_qdrant_task_definition_arn: str,
    ecs_cluster_arn: str,
    ecs_subnets: list[str],
    ecs_security_groups: list[str],
    log_group_arn: str,
) -> dict[str, Any]:
    """Return the Step Functions ASL definition as a Python dict.

    Args:
        fetch_raw_arn: Lambda ARN for FetchRaw stage.
        parse_canonical_arn: Lambda ARN for ParseCanonical stage.
        chunk_document_arn: Lambda ARN for ChunkDocument stage.
        contextualize_chunks_arn: Lambda ARN for ContextualizeChunks stage.
        embed_chunks_task_definition_arn: ECS task definition ARN for EmbedChunks.
        index_to_qdrant_task_definition_arn: ECS task definition ARN for IndexToQdrant.
        ecs_cluster_arn: ECS cluster ARN.
        ecs_subnets: List of private subnet IDs for ECS RunTask.
        ecs_security_groups: List of SG IDs for ECS RunTask.
        log_group_arn: CloudWatch log group ARN for state machine execution logs.
    """

    def _lambda_state(
        name: str,
        lambda_arn: str,
        next_state: str,
    ) -> dict[str, Any]:
        return {
            "Type": "Task",
            "Resource": "arn:aws:states:::lambda:invoke",
            "Parameters": {
                "FunctionName": lambda_arn,
                "Payload.$": "$",
            },
            "ResultSelector": {
                "Payload.$": "$.Payload",
            },
            "ResultPath": "$",
            "OutputPath": "$.Payload",
            "Retry": [
                {
                    "ErrorEquals": ["Lambda.ServiceException", "Lambda.AWSLambdaException",
                                    "Lambda.SdkClientException", "Lambda.TooManyRequestsException"],
                    "IntervalSeconds": 30,
                    "MaxAttempts": 2,
                    "BackoffRate": 2.0,
                }
            ],
            "Catch": [
                {
                    "ErrorEquals": ["States.ALL"],
                    "Next": "PipelineFailed",
                    "ResultPath": "$.error",
                }
            ],
            "Next": next_state,
        }

    def _ecs_run_task_state(
        name: str,
        task_definition_arn: str,
        next_state: str,
    ) -> dict[str, Any]:
        return {
            "Type": "Task",
            "Resource": "arn:aws:states:::ecs:runTask.sync",
            "Parameters": {
                "LaunchType": "FARGATE",
                "Cluster": ecs_cluster_arn,
                "TaskDefinition": task_definition_arn,
                "NetworkConfiguration": {
                    "AwsvpcConfiguration": {
                        "Subnets": ecs_subnets,
                        "SecurityGroups": ecs_security_groups,
                        "AssignPublicIp": "DISABLED",
                    }
                },
                "Overrides": {
                    "ContainerOverrides": [
                        {
                            "Name": "pipeline-worker",
                            "Environment": [
                                {"Name": "PIPELINE_EVENT", "Value.$": "States.JsonToString($)"},
                            ],
                        }
                    ]
                },
            },
            "Catch": [
                {
                    "ErrorEquals": ["States.ALL"],
                    "Next": "PipelineFailed",
                    "ResultPath": "$.error",
                }
            ],
            "Next": next_state,
        }

    return {
        "Comment": "lex-agents ingest pipeline (ADR 0047): FetchRaw → ParseCanonical → ChunkDocument → ContextualizeChunks → EmbedChunks → IndexToQdrant",
        "StartAt": "FetchRaw",
        "States": {
            "FetchRaw": _lambda_state("FetchRaw", fetch_raw_arn, "ParseCanonical"),
            "ParseCanonical": _lambda_state("ParseCanonical", parse_canonical_arn, "ChunkDocument"),
            "ChunkDocument": _lambda_state("ChunkDocument", chunk_document_arn, "ContextualizeChunks"),
            "ContextualizeChunks": _lambda_state("ContextualizeChunks", contextualize_chunks_arn, "EmbedChunks"),
            "EmbedChunks": _ecs_run_task_state("EmbedChunks", embed_chunks_task_definition_arn, "IndexToQdrant"),
            "IndexToQdrant": _ecs_run_task_state("IndexToQdrant", index_to_qdrant_task_definition_arn, "Done"),
            "Done": {
                "Type": "Succeed",
                "Comment": "Pipeline completed successfully",
            },
            "PipelineFailed": {
                "Type": "Fail",
                "ErrorPath": "$.error.Error",
                "CausePath": "$.error.Cause",
                "Comment": "Pipeline failed — check CloudWatch Logs for details",
            },
        },
    }


# ---------------------------------------------------------------------------
# EventBridge schedule payload
# ---------------------------------------------------------------------------

def build_schedule_input(source: str, run_date: str) -> dict[str, Any]:
    """Return the input payload for a scheduled pipeline execution.

    Args:
        source: "boe" | "eur_lex"
        run_date: ISO date string "YYYY-MM-DD"
    """
    return {
        "source": source,
        "run_date": run_date,
        "status": "pending",
        "pipeline_version": "0.1.0",
    }


# ---------------------------------------------------------------------------
# Convenience: print ASL for inspection
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json

    sample_asl = build_asl(
        fetch_raw_arn="arn:aws:lambda:eu-central-1:123456789:function:lex-agents-dev-fetch-raw",
        parse_canonical_arn="arn:aws:lambda:eu-central-1:123456789:function:lex-agents-dev-parse-canonical",
        chunk_document_arn="arn:aws:lambda:eu-central-1:123456789:function:lex-agents-dev-chunk-document",
        contextualize_chunks_arn="arn:aws:lambda:eu-central-1:123456789:function:lex-agents-dev-contextualize-chunks",
        embed_chunks_task_definition_arn="arn:aws:ecs:eu-central-1:123456789:task-definition/lex-agents-dev-embed-chunks",
        index_to_qdrant_task_definition_arn="arn:aws:ecs:eu-central-1:123456789:task-definition/lex-agents-dev-index-qdrant",
        ecs_cluster_arn="arn:aws:ecs:eu-central-1:123456789:cluster/lex-agents-dev",
        ecs_subnets=["subnet-abc123", "subnet-def456"],
        ecs_security_groups=["sg-pipeline123"],
        log_group_arn="arn:aws:logs:eu-central-1:123456789:log-group:/lex-agents/dev/stepfunctions",
    )
    print(json.dumps(sample_asl, indent=2))
