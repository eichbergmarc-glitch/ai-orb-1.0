"""Projektweite pytest-Konfiguration.

Stellt sicher, dass das Projekt-Root-Verzeichnis (und damit das Paket
``backend``) unabhängig vom Arbeitsverzeichnis, aus dem ``pytest``
aufgerufen wird, importierbar ist.
"""

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

# Tests deliberately produce error, provider and voice events. Keep them in a
# per-process ignored directory and out of the real ``logs`` directory. This
# must happen before a backend module configures logging during collection.
os.environ.setdefault(
    "AI_ORB_LOG_DIR",
    str(PROJECT_ROOT / ".pytest_cache" / "logs" / str(os.getpid())),
)
