"""Specialist: legal document analyst using [DOC:s] + [REF:n] citations (ADR 0026)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import structlog

_MODEL = "claude-opus-4-7"
_TEMPERATURE = 0.2
_MAX_TOKENS = 4096


def _find_repo_root(start: Path) -> Path:
    current = start
    for _ in range(20):
        if (current / "pyproject.toml").exists() and (current / "docs").exists():
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    raise FileNotFoundError(f"Could not locate repo root from {start}")


class DocumentAnalystSpecialist:
    """Analyses uploaded legal documents using [DOC:s] + [REF:n] citations (ADR 0026)."""

    def __init__(self, client) -> None:
        self._client = client
        self._logger: structlog.BoundLogger = structlog.get_logger(__name__)
        self._prompt = self._load_prompt()

    def _load_prompt(self) -> str:
        """Load from docs/prompts/document_analyst/v1.md, strip frontmatter, return body."""
        repo_root = _find_repo_root(Path(__file__).parent)
        prompt_path = repo_root / "docs" / "prompts" / "document_analyst" / "v1.md"

        if not prompt_path.exists():
            raise FileNotFoundError(f"Prompt not found: {prompt_path}")

        raw = prompt_path.read_text(encoding="utf-8")

        if not raw.startswith("---"):
            raise ValueError(f"Missing YAML frontmatter in {prompt_path}")

        parts = raw.split("---", 2)
        if len(parts) < 3:
            raise ValueError(f"Malformed frontmatter in {prompt_path}")

        return parts[2].strip()

    async def analyse(
        self,
        doc_context: str,
        query: str,
        rag_chunks: list[dict],
        mode: Literal[
            "resumen_ejecutivo", "analisis_clausulas", "riesgos", "comparativa"
        ] = "riesgos",
    ) -> str:
        """Return markdown analysis with [DOC:s] + [REF:n] citations.

        Args:
            doc_context: Formatted document text with [DOC:s] markers.
                Expected format:
                    DOCUMENTO: {filename}
                    ---
                    [DOC:1] CLÁUSULA PRIMERA
                    Texto de la cláusula...
                    [DOC:2] CLÁUSULA SEGUNDA
                    Texto...
            query: User's analysis request.
            rag_chunks: Normative chunks for [REF:n] citations. Each dict
                should contain 'hierarchy_path' and 'text' keys.
            mode: Analysis mode — one of resumen_ejecutivo, analisis_clausulas,
                riesgos, comparativa.

        Returns:
            Markdown analysis with [DOC:s] and [REF:n] inline citations.
        """
        segment_count = doc_context.count("[DOC:")

        self._logger.info(
            "document_analyst.analyse.start",
            mode=mode,
            segment_count=segment_count,
        )

        # Build normative reference context
        if rag_chunks:
            ref_lines = ["NORMATIVA DE REFERENCIA:"]
            for i, chunk in enumerate(rag_chunks, start=1):
                hierarchy_path = chunk.get("hierarchy_path", "")
                text = chunk.get("text", "")[:300]
                ref_lines.append(f"[REF:{i}] {hierarchy_path}: {text}")
            rag_context = "\n".join(ref_lines)
        else:
            rag_context = "NORMATIVA DE REFERENCIA: (sin fragmentos recuperados)"

        user_content = (
            f"{doc_context}\n\n"
            f"---\n\n"
            f"{rag_context}\n\n"
            f"---\n\n"
            f"Modo de análisis: {mode}\n\n"
            f"Consulta: {query}"
        )

        resp = self._client.messages_create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            system=self._prompt,
            messages=[{"role": "user", "content": user_content}],
        )

        text_block = next(
            (b for b in resp.content if getattr(b, "type", None) == "text"), None
        )
        if text_block is None:
            answer = (
                "No se pudo generar el análisis del documento. "
                "Consulte los servicios jurídicos especializados.\n\n"
                "**AVISO**: Este análisis es un borrador asistido por IA y "
                "requiere validación por un jurista cualificado."
            )
        else:
            answer = text_block.text  # type: ignore[union-attr]

        self._logger.info(
            "document_analyst.analyse.done",
            response_length=len(answer),
        )

        return answer
