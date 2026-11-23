"""Abspielen über die TIDAL-App und Steuern über die Medientasten.

Die öffentliche TIDAL-API spielt nichts ab. Der Orb öffnet deshalb den
gefundenen Titel oder die Playlist per ``tidal://``-Link in der
TIDAL-Desktop-App und drückt danach - wenn gewünscht - die
Wiedergabe-Medientaste. Pause, weiter, zurück und Lautstärke laufen
ebenfalls über die Medientasten von Windows; die TIDAL-App hört darauf.
"""

from __future__ import annotations

import os
import sys
import threading
import time
import webbrowser

from backend.system.logging_setup import get_logger

logger = get_logger(__name__)

#: Virtuelle Tastencodes von Windows für die Medientasten.
MEDIENTASTEN: dict[str, int] = {
    "pause": 0xB3,        # Wiedergabe/Pause (dieselbe Taste)
    "weiter": 0xB3,
    "abspielen": 0xB3,
    "naechster": 0xB0,
    "vorheriger": 0xB1,
    "stopp": 0xB2,
    "lauter": 0xAF,
    "leiser": 0xAE,
    "stumm": 0xAD,
}


def taste_druecken(aktion: str, *, wiederholen: int = 1) -> bool:
    """Drückt eine Medientaste. Gibt ``False`` zurück, wenn es nicht geht."""

    code = MEDIENTASTEN.get(aktion)
    if code is None or sys.platform != "win32":
        return False
    try:
        import ctypes

        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        for _ in range(max(1, wiederholen)):
            user32.keybd_event(code, 0, 0x0001, 0)          # KEYEVENTF_EXTENDEDKEY
            user32.keybd_event(code, 0, 0x0001 | 0x0002, 0)  # ... | KEYEVENTF_KEYUP
        return True
    except Exception:  # noqa: BLE001 - ohne Medientaste läuft der Rest weiter.
        logger.exception("Die Medientaste liess sich nicht drücken.")
        return False


def in_app_oeffnen(app_link: str, web_link: str, *, danach_abspielen: bool = False, warte_sekunden: float = 4.0) -> str:
    """Öffnet einen Link in der TIDAL-App, sonst im Browser.

    Returns:
        ``"app"`` oder ``"browser"`` - wo es geöffnet wurde.
    """

    wo = "browser"
    if sys.platform == "win32":
        try:
            os.startfile(app_link)  # type: ignore[attr-defined]
            wo = "app"
        except OSError:
            logger.info("Keine TIDAL-App für %s gefunden - Browser.", app_link)
    if wo == "browser":
        webbrowser.open(web_link, new=2)

    if wo == "app" and danach_abspielen:
        # Die App braucht einen Moment, bis die Seite geladen ist. Im
        # Hintergrund warten, damit der Orb nicht so lange stumm bleibt.
        def _spaeter() -> None:
            time.sleep(warte_sekunden)
            taste_druecken("abspielen")

        threading.Thread(target=_spaeter, name="tidal-abspielen", daemon=True).start()
    return wo
