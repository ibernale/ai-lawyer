"""fetch_raw handler for BOE — Lambda step in ingest_boe state machine.

Re-exports the top-level fetch_raw handler which already handles BOE via the
``source`` field in PipelineEvent.
"""

from lex_pipeline_aws.fetch_raw import lambda_handler  # re-export

__all__ = ["lambda_handler"]
