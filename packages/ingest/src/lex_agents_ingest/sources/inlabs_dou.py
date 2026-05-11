"""INLABS DOU (Diário Oficial da União — Brazil) source. ADR 0025."""

from __future__ import annotations

import io
import os
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

import structlog

from lex_agents_ingest.base import Source
from lex_agents_ingest.canonical import CanonicalBulletin, RawDocument

logger: structlog.BoundLogger = structlog.get_logger(__name__)

INLABS_BASE = "https://inlabs.in.gov.br/"

RELEVANT_AUTHORITIES = {
    "BCB",
    "CMN",
    "CVM",
    "LGPD",
    "Banco Central do Brasil",
    "Conselho Monetário Nacional",
}


class InlabsDOUSource(Source):
    """Source for the Brazilian Diário Oficial da União via INLABS API.

    Requires a valid ``INLABS_TOKEN`` env var in real mode.
    In fixture mode (*fixture_path* set) reads local XML files.
    """

    source_id = "inlabs_dou"
    rate_limit_rps: float = 0.5

    def __init__(
        self,
        token: str | None = None,
        fixture_path: Path | None = None,
    ) -> None:
        super().__init__()
        self._fixture_path = fixture_path

        if fixture_path is None:
            self._token = token or os.environ.get("INLABS_TOKEN")
            if not self._token:
                raise RuntimeError(
                    "INLABS_TOKEN env var required for real mode. See ADR 0025."
                )
        else:
            self._token = token

    # ------------------------------------------------------------------
    # list_documents
    # ------------------------------------------------------------------

    async def list_documents(self, for_date: date | None = None) -> list[str]:  # type: ignore[override]
        """Return relevant DOU document IDs for *for_date* (default today)."""
        if self._fixture_path is not None:
            return [p.stem for p in sorted(self._fixture_path.glob("*.xml"))]

        target = for_date or datetime.now(tz=timezone.utc).date()
        date_str = target.strftime("%Y-%m-%d")

        import httpx

        headers = {"Authorization": f"Bearer {self._token}"}
        url = f"{INLABS_BASE}dou/{date_str}"

        await self._rate_limiter.acquire()
        async with httpx.AsyncClient(headers=headers, timeout=60.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()

        # Response is a ZIP; extract XML filenames and filter by authority
        doc_ids: list[str] = []
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            for name in zf.namelist():
                if not name.endswith(".xml"):
                    continue
                # Quick authority filter: read just the first 2 KB
                with zf.open(name) as f:
                    snippet = f.read(2048).decode("utf-8", errors="replace")
                if any(auth in snippet for auth in RELEVANT_AUTHORITIES):
                    doc_ids.append(Path(name).stem)
        return doc_ids

    # ------------------------------------------------------------------
    # fetch
    # ------------------------------------------------------------------

    async def fetch(self, doc_id: str) -> RawDocument:
        """Return XML content for *doc_id*."""
        if self._fixture_path is not None:
            fixture_file = self._fixture_path / f"{doc_id}.xml"
            raw_bytes = fixture_file.read_bytes()
            return RawDocument(
                source="inlabs_dou",
                source_id=doc_id,
                raw_url=f"file://{fixture_file}",
                content_type="xml",
                raw_bytes=raw_bytes,
                fetched_at=datetime.now(tz=timezone.utc),
            )

        import httpx

        headers = {"Authorization": f"Bearer {self._token}"}
        # Derive date from doc_id pattern (dou_YYYYMMDD_*)
        url = f"{INLABS_BASE}dou/documento/{doc_id}"

        await self._rate_limiter.acquire()
        async with httpx.AsyncClient(headers=headers, timeout=60.0) as client:
            resp = await client.get(url)

        if resp.status_code == 404:
            raise FileNotFoundError(f"INLABS DOU document not found: {doc_id}")
        resp.raise_for_status()

        # Response may be a ZIP with a single XML entry
        content_type = resp.headers.get("content-type", "")
        if "zip" in content_type or resp.content[:2] == b"PK":
            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                xml_names = [n for n in zf.namelist() if n.endswith(".xml")]
                raw_bytes = zf.read(xml_names[0]) if xml_names else resp.content
        else:
            raw_bytes = resp.content

        return RawDocument(
            source="inlabs_dou",
            source_id=doc_id,
            raw_url=str(resp.url),
            content_type="xml",
            raw_bytes=raw_bytes,
            fetched_at=datetime.now(tz=timezone.utc),
        )

    # ------------------------------------------------------------------
    # parse_to_canonical
    # ------------------------------------------------------------------

    def parse_to_canonical(self, raw: RawDocument) -> CanonicalBulletin:  # type: ignore[override]
        """Parse a DOU XML document into a CanonicalBulletin."""
        root = ET.fromstring(raw.raw_bytes.decode("utf-8", errors="replace"))

        def _text(tag: str) -> str:
            el = root.find(f".//{tag}")
            return el.text.strip() if el is not None and el.text else ""

        autoridade = _text("autoridade") or _text("Autoridade")
        ementa = _text("ementa") or _text("Ementa")
        identifica = _text("identifica") or _text("Identifica")
        publicacao = _text("publicacaoDO") or _text("publicação") or _text("data")

        # Detect seção
        section: str | None = None
        secao_el = root.find(".//secao") or root.find(".//Secao")
        if secao_el is not None and secao_el.text:
            section = secao_el.text.strip()
        else:
            # Try from root tag attribute or parent path hints
            tag_name = root.tag.lower()
            for marker in ("secao1", "secao2", "secao3", "extra"):
                if marker in tag_name:
                    section = marker[-1] if marker != "extra" else "Extra"
                    break

        # Full text: concatenate all text nodes
        full_text = " ".join(el.strip() for el in root.itertext() if el.strip())

        # Parse publication date
        pub_date = datetime.now(tz=timezone.utc).date()
        if publicacao:
            for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
                try:
                    pub_date = datetime.strptime(publicacao[:10], fmt).date()
                    break
                except ValueError:
                    continue

        return CanonicalBulletin(
            source="inlabs_dou",
            source_id=raw.source_id,
            jurisdiction="BR",
            type="other",
            title=identifica or raw.source_id,
            publication_date=pub_date,
            full_text=full_text,
            raw_url=raw.raw_url,
            fetched_at=raw.fetched_at,
            bulletin="DOU",
            section=section,
            issuing_authority=autoridade,
            summary=ementa or None,
            extra={"language": "pt-BR"},
        )
