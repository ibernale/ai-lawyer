---
name: document-parsing
description: |
  Protocol for parsing, segmenting, and analysing uploaded legal documents
  (PDF, DOCX, TXT, EML). Covers format detection, hard limits, the privacy
  invariant, ParsedDocument / DocumentSegment types, [DOC:s] citation syntax,
  and integration with the Document Agents pipeline (ADR 0026).
---

# Document Parsing Skill

## Hard limits (non-negotiable)

| Constraint | Limit | Error to raise |
|-----------|-------|----------------|
| File size | 50 MB | `DocumentTooLargeError` |
| PDF pages | 200 pages | `DocumentTooLargeError` |
| Supported MIME | pdf, docx, txt, eml | `UnsupportedFormatError` |

## Privacy invariant (ADR 0026)

Documents are **never persisted** to disk or database beyond the session.
What IS stored (trace only):
- `trace_id` (UUID)
- SHA-256 hash of raw bytes
- Structured `DocumentAnalysisResult` summary (no raw text)

What is NEVER stored:
- Raw bytes
- Parsed full text
- Segment text

## Type hierarchy

```
ParsedDocument
  ├── doc_id: str            # UUID assigned at upload
  ├── filename: str
  ├── mime_type: str
  ├── sha256: str            # hex digest of raw bytes
  ├── page_count: int | None # PDF only
  ├── text: str              # full concatenated text (in-memory only)
  ├── metadata: dict[str, str]
  └── segments: list[DocumentSegment]

DocumentSegment
  ├── segment_id: str        # "{doc_id}::{index}"
  ├── index: int             # 1-based (maps to [DOC:s])
  ├── segment_type: SegmentType
  ├── text: str
  ├── page_start: int | None
  └── heading: str | None

SegmentType = Literal[
  "clausula", "considerando", "antecedente",
  "acuerdo", "resolucion", "fundamento",
  "firma", "anexo", "parrafo", "thread"
]

ExtractedEntities
  ├── parties: list[str]         # names, NIF/CIF
  ├── norms_referenced: list[str] # art. N, BOE-A-..., ECLI:...
  ├── key_dates: list[date]
  └── risk_clauses: list[str]    # liability, penalty, termination

DocumentAnalysisResult
  ├── doc_id: str
  ├── trace_id: str
  ├── sha256: str
  ├── filename: str
  ├── segment_count: int
  ├── entities: ExtractedEntities
  ├── analysis_text: str         # markdown answer with [DOC:s] + [REF:n]
  ├── verification_status: Literal["green", "amber", "red"]
  └── analysed_at: datetime
```

## Citation syntax

`[DOC:s]` — reference to segment at 1-based index `s` within the parsed document.

Combined with normative citations:
> "La cláusula 7 [DOC:3] establece una penalización del 5%, lo que podría vulnerar el art. 80 LGT [REF:2]."

Rules:
- `[DOC:s]` must resolve to an actual segment in the `ParsedDocument.segments` list.
- `[DOC:s]` is **only** valid within a response that includes the document as context.
- Never invent a `[DOC:s]` index that does not exist in the current document.
- `[DOC:s]` cites document facts; `[REF:n]` cites normative/jurisprudential chunks from Qdrant.

## Parser responsibilities by format

### PDF (`parsers/pdf.py`)
- Library: `pymupdf4llm` (markdown-aware extraction)
- Check page count BEFORE parsing; raise `DocumentTooLargeError` if > 200
- Preserve page numbers in segment metadata

### DOCX (`parsers/docx.py`)
- Library: `python-docx`
- Respect heading styles (Heading 1/2/3 → `heading` field in segment)
- Tables → flattened text with `| col | col |` markdown

### TXT (`parsers/txt.py`)
- Library: `chardet` for encoding detection
- Normalise to UTF-8 before processing
- No structural metadata available; all content → `parrafo` segments

### EML (`parsers/eml.py`)
- Library: `mailparser`
- Extract body text + recursively process text/plain attachments
- Non-text attachments → list in metadata, not parsed
- Thread boundary detection: `>` quoted lines → separate `thread` segment

## Legal segmentation patterns

Patterns are applied in order; first match wins per line/block.

| Pattern (regex, case-insensitive) | `segment_type` |
|----------------------------------|----------------|
| `^CLÁUSULA\s+\w+` | `clausula` |
| `^CONSIDERANDO\s+\w+` | `considerando` |
| `^ANTECEDENTES?` | `antecedente` |
| `^(ACUERDA|SE ACUERDA|RESUELVE)` | `acuerdo` |
| `^FUNDAMENTO(S)? DE DERECHO` | `fundamento` |
| `^RESOLUCI[ÓO]N` | `resolucion` |
| `^FALLO` | `resolucion` |
| `^ANEXO\s+\w+` | `anexo` |
| `firma\|signature\|signed` | `firma` |
| `^>` (EML quoted reply) | `thread` |
| *(default)* | `parrafo` |

## Entity extraction

### Fast path (regex, no LLM)
- NIF/CIF: `[A-Z]\d{8}` / `\d{8}[A-Z]`
- Article references: `art(?:ículo)?\.?\s*\d+[\w\.]*`
- BOE references: `BOE-[A-Z]-\d{4}-\d+`
- ECLI: `ECLI:[A-Z]+:[A-Z]+:\d{4}:\d+`
- Dates: ISO + Spanish (`\d{1,2}\s+de\s+\w+\s+de\s+\d{4}`)
- Amounts: `\d[\d.,]+\s*(?:euros?|EUR|%)`

### LLM fallback (Haiku) — only when regex yields < 3 entities
Prompt: extract parties, risk clauses (liability/penalty/termination), key obligations.
Max tokens: 512. Do NOT use for documents > 50k tokens.

## Integration with Document Agents pipeline

```
upload → dispatcher → parser → segmenter → entity extractor
                                                ↓
                              DocumentAnalystSpecialist
                              (uses [DOC:s] + [REF:n])
                                                ↓
                              VerifierPipeline (DocSegmentVerifier)
                                                ↓
                              DocumentAnalysisResult → API response
```

## What NOT to do

- Do not write parsed text to disk at any point.
- Do not log segment text (only segment count and type distribution).
- Do not call the full `claude-opus-4-7` model for entity extraction.
- Do not parse password-protected PDFs — raise `ParseError("password_protected")`.
- Do not attempt OCR on image-only PDFs — raise `ParseError("image_only_pdf")`.
