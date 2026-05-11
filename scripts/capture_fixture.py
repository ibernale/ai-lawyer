#!/usr/bin/env python3
"""Capture a fixture XML from live sources for offline testing.

Usage:
    python scripts/capture_fixture.py boe BOE-A-2014-6732
    python scripts/capture_fixture.py eurlex 32013R0575
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import httpx


def _capture_boe(doc_id: str, dest: Path) -> None:
    url = f"https://boe.es/diario_boe/xml.php?id={doc_id}"
    print(f"Fetching BOE {doc_id} from {url}")
    with httpx.Client(timeout=30) as client:
        resp = client.get(url)
        resp.raise_for_status()
    dest.write_bytes(resp.content)
    checksum = hashlib.sha256(resp.content).hexdigest()
    print(f"Saved to {dest}  ({len(resp.content)} bytes, sha256={checksum[:16]}…)")


def _capture_eurlex(doc_id: str, dest: Path) -> None:
    sparql_url = "https://publications.europa.eu/webapi/rdf/sparql"
    query = f"""
    PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
    SELECT ?work WHERE {{
      ?work cdm:resource_legal_id_celex "{doc_id}" .
    }}
    """
    print(f"Resolving EUR-Lex {doc_id} via SPARQL…")
    with httpx.Client(timeout=30) as client:
        resp = client.post(
            sparql_url,
            data={"query": query, "format": "application/sparql-results+json"},
            headers={"Accept": "application/sparql-results+json"},
        )
        resp.raise_for_status()
        bindings = resp.json()["results"]["bindings"]

    if bindings:
        cellar_uri = bindings[0]["work"]["value"]
        print(f"Cellar URI: {cellar_uri}")
        with httpx.Client(timeout=30) as client:
            resp = client.get(cellar_uri, headers={"Accept": "application/xml"})
            resp.raise_for_status()
    else:
        fallback = f"https://eur-lex.europa.eu/legal-content/ES/TXT/XML/?uri=CELEX:{doc_id}"
        print(f"SPARQL returned no results, trying fallback: {fallback}")
        with httpx.Client(timeout=30) as client:
            resp = client.get(fallback, timeout=30)
            resp.raise_for_status()

    dest.write_bytes(resp.content)
    checksum = hashlib.sha256(resp.content).hexdigest()
    print(f"Saved to {dest}  ({len(resp.content)} bytes, sha256={checksum[:16]}…)")


def main() -> None:
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)

    source, doc_id = sys.argv[1], sys.argv[2]
    base = Path(__file__).parent.parent / "packages" / "ingest" / "tests" / "fixtures"

    if source == "boe":
        dest = base / "boe" / f"{doc_id}.xml"
        dest.parent.mkdir(parents=True, exist_ok=True)
        _capture_boe(doc_id, dest)
    elif source == "eurlex":
        dest = base / "eurlex" / f"{doc_id}.xml"
        dest.parent.mkdir(parents=True, exist_ok=True)
        _capture_eurlex(doc_id, dest)
    else:
        print(f"Unknown source: {source}. Use 'boe' or 'eurlex'.")
        sys.exit(1)


if __name__ == "__main__":
    main()
