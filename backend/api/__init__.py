"""Lokale API-Schicht von AI-Orb.

Stellt den HTTP-/SSE-Server bereit, über den die Electron-Anwendung
(Desktop Layer) mit dem Backend kommuniziert. Der Server lauscht
ausschließlich auf ``127.0.0.1`` (siehe ``config.yaml``, Abschnitt
``backend``) und ist damit von außerhalb des lokalen Rechners nicht
erreichbar.

Der Server verwendet ausschließlich die Python-Standardbibliothek und
benötigt daher kein Web-Framework.
"""

from backend.api.http_server import ApiRouter, LocalApiServer, SseBroker
from backend.api.server import build_router, create_server

__all__ = ["ApiRouter", "LocalApiServer", "SseBroker", "build_router", "create_server"]
