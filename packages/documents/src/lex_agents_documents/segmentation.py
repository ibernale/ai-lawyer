"""Legal segmentation — splits a ParsedDocument into DocumentSegments."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from lex_agents_documents.types import DocumentSegment, ParsedDocument, SegmentType

if TYPE_CHECKING:
    pass

# Ordered patterns: first match wins per block.
_PATTERNS: list[tuple[re.Pattern[str], SegmentType]] = [
    (re.compile(r"^CLÁUSULA\s+\w+", re.IGNORECASE), "clausula"),
    (re.compile(r"^CLAUSULA\s+\w+", re.IGNORECASE), "clausula"),
    (re.compile(r"^CONSIDERANDO\s+\w+", re.IGNORECASE), "considerando"),
    (re.compile(r"^ANTECEDENTES?", re.IGNORECASE), "antecedente"),
    (re.compile(r"^(?:ACUERDA|SE ACUERDA|RESUELVE)", re.IGNORECASE), "acuerdo"),
    (re.compile(r"^FUNDAMENTOS?\s+DE\s+DERECHO", re.IGNORECASE), "fundamento"),
    (re.compile(r"^RESOLUCIÓN", re.IGNORECASE), "resolucion"),
    (re.compile(r"^RESOLUCION", re.IGNORECASE), "resolucion"),
    (re.compile(r"^FALLO", re.IGNORECASE), "resolucion"),
    (re.compile(r"^ANEXO\s+\w+", re.IGNORECASE), "anexo"),
    (re.compile(r"(?:firma|signature|signed)", re.IGNORECASE), "firma"),
    (re.compile(r"^>"), "thread"),
]

# Minimum non-empty text length for a segment to be emitted.
_MIN_SEGMENT_CHARS = 10


def _classify_block(text: str) -> SegmentType:
    stripped = text.strip()
    for pattern, seg_type in _PATTERNS:
        if pattern.match(stripped):
            return seg_type
    return "parrafo"


def _split_into_blocks(text: str) -> list[str]:
    """Split text into logical blocks separated by blank lines or structural headings."""
    blocks: list[str] = []
    current_lines: list[str] = []

    for line in text.splitlines():
        stripped = line.strip()

        # Structural heading → start new block
        is_heading = any(p.match(stripped) for p, _ in _PATTERNS[:10])  # skip firma/thread
        if is_heading and current_lines:
            block = "\n".join(current_lines).strip()
            if block:
                blocks.append(block)
            current_lines = [line]
            continue

        if stripped == "" and current_lines:
            block = "\n".join(current_lines).strip()
            if block:
                blocks.append(block)
            current_lines = []
        else:
            current_lines.append(line)

    if current_lines:
        block = "\n".join(current_lines).strip()
        if block:
            blocks.append(block)

    return blocks


class LegalSegmenter:
    """Segments a ParsedDocument into DocumentSegments in-place."""

    def segment(self, doc: ParsedDocument) -> list[DocumentSegment]:
        """Return segments list; also sets doc.segments."""
        blocks = _split_into_blocks(doc.text)
        segments: list[DocumentSegment] = []

        index = 1
        for block in blocks:
            if len(block) < _MIN_SEGMENT_CHARS:
                continue
            seg_type = _classify_block(block)
            heading_match = block.splitlines()[0].strip() if block else None

            segments.append(
                DocumentSegment(
                    segment_id=f"{doc.doc_id}::{index}",
                    index=index,
                    segment_type=seg_type,
                    text=block,
                    heading=heading_match if seg_type != "parrafo" else None,
                )
            )
            index += 1

        doc.segments = segments
        return segments
