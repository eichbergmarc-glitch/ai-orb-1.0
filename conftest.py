"""Projektweite pytest-Konfiguration.

Stellt sicher, dass das Projekt-Root-Verzeichnis (und damit das Paket
``backend``) unabhängig vom Arbeitsverzeichnis, aus dem ``pytest``
aufgerufen wird, importierbar ist.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
