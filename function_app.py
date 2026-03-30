from __future__ import annotations

import sys
from pathlib import Path

CORE_DIR = Path(__file__).resolve().parent / "src" / "core"
if str(CORE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_DIR))

from orchestrator_serverless import app

