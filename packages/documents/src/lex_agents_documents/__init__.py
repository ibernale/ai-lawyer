"""lex-agents Document Agents pipeline — ADR 0026."""

from lex_agents_documents.entities import EntityExtractor
from lex_agents_documents.exceptions import (
    DocumentTooLargeError,
    ParseError,
    UnsupportedFormatError,
)
from lex_agents_documents.segmentation import LegalSegmenter
from lex_agents_documents.types import (
    DocumentAnalysisResult,
    DocumentCompareResult,
    DocumentSegment,
    ExtractedEntities,
    ParsedDocument,
    SegmentType,
)

__all__ = [
    "ParsedDocument",
    "DocumentSegment",
    "ExtractedEntities",
    "DocumentAnalysisResult",
    "DocumentCompareResult",
    "SegmentType",
    "LegalSegmenter",
    "EntityExtractor",
    "ParseError",
    "UnsupportedFormatError",
    "DocumentTooLargeError",
]
