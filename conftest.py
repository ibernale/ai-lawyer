"""Root conftest.py — ensures evals/src is on sys.path before evals packages are imported.

With --import-mode=importlib the project root (.) is on sys.path which causes
`import evals` to resolve to ./evals/ (test runner dir) rather than
./evals/src/evals/ (the actual package).  Prepending the src path fixes it.
"""

import sys
from pathlib import Path

_root = Path(__file__).parent
for _src in [
    _root / "evals" / "src",
]:
    _s = str(_src)
    if _s not in sys.path:
        sys.path.insert(0, _s)
