"""parse_canonical handler for EUR-Lex — Lambda step in ingest_eur_lex state machine.

Re-exports the top-level parse_canonical handler which already handles EUR-Lex
via the ``source`` field in PipelineEvent.
"""

from lex_pipeline_aws.parse_canonical import lambda_handler  # re-export

__all__ = ["lambda_handler"]
