import sys
from pathlib import Path

# Ensure evals/src is on sys.path so `from evals.runners.xxx` imports work
# when pytest runs with --import-mode=importlib from the repo root.
_evals_src = Path(__file__).parent.parent / "src"
if str(_evals_src) not in sys.path:
    sys.path.insert(0, str(_evals_src))
