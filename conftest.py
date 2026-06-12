import sys
from pathlib import Path

collect_ignore_glob = ["tests/fixtures/*"]

# Ensure the project root is on PYTHONPATH so `orchestrator` is importable.
root = Path(__file__).parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))
