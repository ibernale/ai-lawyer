"""Legal source implementations.

GREEN (active):
  BoeSource, EurlexSource, AepdSource, EdpbSource, BdeSource,
  EbaSource, EsmaSource, LegislationUkSource, FcaSource

AMBER (blocked — see docs/legal/cendoj-status.md):
  CendojSource, CendojPuntualSource (dev only), TribunalConstitucionalSource

RED (blocked — see docs/legal/comerciales-status.md):
  AranzadiSource, LaLeySource, TirantSource
"""

from lex_agents_ingest.sources.aepd import AepdSource
from lex_agents_ingest.sources.aranzadi import AranzadiSource
from lex_agents_ingest.sources.bde import BdeSource
from lex_agents_ingest.sources.boe import BoeSource
from lex_agents_ingest.sources.cendoj import CendojPuntualSource, CendojSource
from lex_agents_ingest.sources.eba import EbaSource
from lex_agents_ingest.sources.edpb import EdpbSource
from lex_agents_ingest.sources.esma import EsmaSource
from lex_agents_ingest.sources.eurlex import EurlexSource
from lex_agents_ingest.sources.fca import FcaSource
from lex_agents_ingest.sources.laley import LaLeySource
from lex_agents_ingest.sources.legislation_uk import LegislationUkSource
from lex_agents_ingest.sources.tirant import TirantSource
from lex_agents_ingest.sources.tribunal_constitucional import TribunalConstitucionalSource

__all__ = [
    # GREEN
    "BoeSource",
    "EurlexSource",
    "AepdSource",
    "EdpbSource",
    "BdeSource",
    "EbaSource",
    "EsmaSource",
    "LegislationUkSource",
    "FcaSource",
    # AMBER
    "CendojSource",
    "CendojPuntualSource",
    "TribunalConstitucionalSource",
    # RED
    "AranzadiSource",
    "LaLeySource",
    "TirantSource",
]
