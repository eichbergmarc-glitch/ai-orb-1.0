"""TIDAL: Musik suchen, in der App abspielen, Playlists anlegen und füllen.

Einrichtung und Hintergrund stehen in ``docs/TIDAL.md``.
"""

from __future__ import annotations

from backend.integrations.tidal.client import Playlist, TidalClient, TidalFehler, Titel
from backend.integrations.tidal.oauth import TidalAuth, TidalAuthFehler, TidalOAuthConfig

__all__ = [
    "Playlist",
    "TidalAuth",
    "TidalAuthFehler",
    "TidalClient",
    "TidalFehler",
    "TidalOAuthConfig",
    "Titel",
]
