"""lex-pipeline-aws — Lambda handlers for the Step Functions ingest pipeline.

Pipeline stages (ADR 0047):
  FetchRaw → ParseCanonical → ChunkDocument → ContextualizeChunks
  → EmbedChunks (ECS RunTask) → IndexToQdrant (ECS RunTask)

Each stage receives a shared event envelope and returns an updated copy.
"""
