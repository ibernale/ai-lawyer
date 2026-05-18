"""Clause-level chunker for contract documents — Fase 13A."""

from __future__ import annotations

import hashlib
import re

from pydantic import BaseModel


class ContractChunk(BaseModel):
    chunk_id: str       # SHA256(contract_id + "::" + clause_path)
    contract_id: str
    clause_path: str    # e.g. "Section 3 > 3.1 > (a)"
    clause_title: str   # e.g. "Representations and Warranties"
    text: str
    char_offset: int
    chunk_index: int


# ---------------------------------------------------------------------------
# Clause detection patterns (ordered by specificity)
# ---------------------------------------------------------------------------

# Matches:
#   CLÁUSULA PRIMERA / CLÁUSULA SEGUNDA ... (Spanish ordinal)
#   FIRST. / SECOND. (English ordinal header)
#   DEFINITIONS / RECITALS / WHEREAS / CONSIDERANDO (special blocks)
#   Article 1 / Section 1 (word + number)
#   1. / 1.1 / 1.1.1 (numeric dotted)

_CLAUSE_RE = re.compile(
    r"""
    (?:^|\n)
    (
        # Spanish ordinal clauses: CLÁUSULA PRIMERA, CLÁUSULA DÉCIMA, etc.
        CL[AÁ]USULA\s+[A-ZÁÉÍÓÚÜÑ]+[A-ZÁÉÍÓÚÜÑ\s]*
        |
        # Spanish: CONSIDERANDO
        CONSIDERANDO[:\s]
        |
        # English special blocks: DEFINITIONS, RECITALS, WHEREAS
        (?:DEFINITIONS|RECITALS|WHEREAS|SCHEDULE|EXHIBIT|ANNEX)[:\s]?
        |
        # Word + number: Article 1, Section 1, Clause 1
        (?:Article|Section|Clause|Chapter|Part|Artículo|Sección|Apartado)\s+\d+(?:\.\d+)*
        |
        # Numeric dotted: 1. / 1.1 / 1.1.1 followed by space and uppercase/title
        \d+(?:\.\d+)*\.\s+[A-ZÁÉÍÓÚÜÑ][A-Za-záéíóúüñ\s\-]{2,}
        |
        # Numeric dotted (short): 1. / 2. / 10. — standalone section numbers
        \d{1,3}\.\s+
    )
    """,
    re.VERBOSE | re.MULTILINE,
)

_MIN_CHUNK_CHARS = 200
_SENTENCE_END_RE = re.compile(r"(?<=[.!?])\s+")


# ---------------------------------------------------------------------------
# ContractChunker
# ---------------------------------------------------------------------------


class ContractChunker:
    """Split contract text into clause-level chunks."""

    MAX_CHUNK_CHARS: int = 3000

    def chunk(self, text: str, contract_id: str) -> list[ContractChunk]:
        """Split contract text into clause-level chunks.

        Strategy:
        1. Try regex-based clause detection (numbered sections).
        2. Fall back to paragraph-based splitting if no structure detected.
        3. Merge very short chunks (<MIN_CHUNK_CHARS) with the next chunk.
        4. Split very long chunks (>MAX_CHUNK_CHARS) at sentence boundaries.
        """
        raw_chunks = self._split_by_clauses(text, contract_id)
        if not raw_chunks:
            raw_chunks = self._split_by_paragraphs(text, contract_id)

        merged = self._merge_short(raw_chunks, contract_id)
        result: list[ContractChunk] = []
        for chunk in merged:
            result.extend(self._split_long(chunk, contract_id))

        # Re-index after merges/splits
        for idx, chunk in enumerate(result):
            object.__setattr__(chunk, "chunk_index", idx) if chunk.model_config.get("frozen") else setattr(chunk, "chunk_index", idx)

        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _make_chunk_id(self, contract_id: str, clause_path: str) -> str:
        raw = f"{contract_id}::{clause_path}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def _split_by_clauses(self, text: str, contract_id: str) -> list[ContractChunk]:
        """Regex-based clause detection."""
        matches = list(_CLAUSE_RE.finditer(text))
        if not matches:
            return []

        chunks: list[ContractChunk] = []
        for i, match in enumerate(matches):
            start = match.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            clause_header = match.group(1).strip()
            chunk_text = text[start:end].strip()
            if not chunk_text:
                continue
            clause_path = f"Clause {i + 1}"
            chunks.append(
                ContractChunk(
                    chunk_id=self._make_chunk_id(contract_id, f"{clause_path}:{clause_header}"),
                    contract_id=contract_id,
                    clause_path=clause_path,
                    clause_title=clause_header[:100],
                    text=chunk_text,
                    char_offset=start,
                    chunk_index=i,
                )
            )
        return chunks

    def _split_by_paragraphs(self, text: str, contract_id: str) -> list[ContractChunk]:
        """Fallback: split on double newlines (paragraph breaks)."""
        paragraphs = re.split(r"\n{2,}", text)
        chunks: list[ContractChunk] = []
        offset = 0
        idx = 0
        for para in paragraphs:
            stripped = para.strip()
            if not stripped:
                offset += len(para) + 2
                continue
            title = stripped[:80].split("\n")[0]
            clause_path = f"Para {idx + 1}"
            chunks.append(
                ContractChunk(
                    chunk_id=self._make_chunk_id(contract_id, f"{clause_path}:{offset}"),
                    contract_id=contract_id,
                    clause_path=clause_path,
                    clause_title=title,
                    text=stripped,
                    char_offset=offset,
                    chunk_index=idx,
                )
            )
            offset += len(para) + 2
            idx += 1
        return chunks

    def _merge_short(
        self, chunks: list[ContractChunk], contract_id: str
    ) -> list[ContractChunk]:
        """Merge chunks shorter than _MIN_CHUNK_CHARS with the following chunk."""
        if not chunks:
            return chunks

        merged: list[ContractChunk] = []
        pending: ContractChunk | None = None

        for chunk in chunks:
            if pending is None:
                pending = chunk
            elif len(pending.text) < _MIN_CHUNK_CHARS:
                # Merge pending into current
                combined_text = pending.text + "\n\n" + chunk.text
                combined_path = f"{pending.clause_path} + {chunk.clause_path}"
                pending = ContractChunk(
                    chunk_id=self._make_chunk_id(contract_id, combined_path),
                    contract_id=contract_id,
                    clause_path=combined_path,
                    clause_title=pending.clause_title,
                    text=combined_text,
                    char_offset=pending.char_offset,
                    chunk_index=pending.chunk_index,
                )
            else:
                merged.append(pending)
                pending = chunk

        if pending is not None:
            merged.append(pending)

        return merged

    def _split_long(
        self, chunk: ContractChunk, contract_id: str
    ) -> list[ContractChunk]:
        """Split chunks exceeding MAX_CHUNK_CHARS at sentence boundaries."""
        if len(chunk.text) <= self.MAX_CHUNK_CHARS:
            return [chunk]

        sentences = _SENTENCE_END_RE.split(chunk.text)
        parts: list[ContractChunk] = []
        current_parts: list[str] = []
        current_len = 0
        sub_idx = 0

        for sentence in sentences:
            if current_len + len(sentence) > self.MAX_CHUNK_CHARS and current_parts:
                sub_text = " ".join(current_parts)
                sub_path = f"{chunk.clause_path} ({sub_idx + 1})"
                parts.append(
                    ContractChunk(
                        chunk_id=self._make_chunk_id(contract_id, sub_path),
                        contract_id=contract_id,
                        clause_path=sub_path,
                        clause_title=chunk.clause_title,
                        text=sub_text,
                        char_offset=chunk.char_offset,
                        chunk_index=chunk.chunk_index,
                    )
                )
                current_parts = [sentence]
                current_len = len(sentence)
                sub_idx += 1
            else:
                current_parts.append(sentence)
                current_len += len(sentence) + 1

        if current_parts:
            sub_text = " ".join(current_parts)
            sub_path = (
                f"{chunk.clause_path} ({sub_idx + 1})" if sub_idx > 0 else chunk.clause_path
            )
            parts.append(
                ContractChunk(
                    chunk_id=self._make_chunk_id(contract_id, sub_path),
                    contract_id=contract_id,
                    clause_path=sub_path,
                    clause_title=chunk.clause_title,
                    text=sub_text,
                    char_offset=chunk.char_offset,
                    chunk_index=chunk.chunk_index,
                )
            )

        return parts if parts else [chunk]
