"""Der Chatverlauf: jede Anfrage und jede Antwort, ueber Neustarts hinweg.

Marc, 16.11.2026: "Der Chat soll zudem auch den Verlauf der Anfragen
anzeigen." Bis dahin stand im Chatfenster nur, was in genau diesem Fenster
getippt worden war - Gesprochenes fehlte am Rechner ganz, und nach einem
Neustart war das Fenster leer.

Der Verlauf ist bewusst etwas anderes als das Gespraechsgedaechtnis des
Orchestrators: Jenes wird gekuerzt, zusammengefasst und bei einer neuen
Unterhaltung geleert, weil es dem MODELL dient. Dieses hier dient dem
MENSCHEN, der nachlesen will - es wird nur angehaengt und am Anfang
abgeschnitten, wenn es zu lang wird.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from backend.system.logging_setup import get_logger

logger = get_logger(__name__)

#: So viele Zeilen bleiben erhalten.
HOECHSTENS = 600
#: Laenger wird eine einzelne Zeile nicht gespeichert (Vorlesungsabschnitte).
ZEILE_HOECHSTENS = 6000

_WOCHENTAGE = ("Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag")


def _tag(zeit: float) -> str:
    lokal = time.localtime(zeit)
    return f"{_WOCHENTAGE[lokal.tm_wday]}, {lokal.tm_mday:02d}.{lokal.tm_mon:02d}.{lokal.tm_year}"


class Chatverlauf:
    """Haelt die letzten Zeilen des Gespraechs fest - threadsicher."""

    def __init__(self, datei: Path | None = None, *, hoechstens: int = HOECHSTENS) -> None:
        if datei is None:
            from backend.utils.paths import get_data_dir

            datei = get_data_dir() / "chatverlauf.json"
        self._datei = Path(datei)
        self._hoechstens = max(10, int(hoechstens))
        self._sperre = threading.Lock()
        self._zeilen: list[dict[str, Any]] = []
        self._laden()

    def _laden(self) -> None:
        try:
            roh = json.loads(self._datei.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except Exception:  # noqa: BLE001 - ein kaputter Verlauf ist kein Startfehler.
            logger.warning("Der Chatverlauf war nicht lesbar und beginnt neu.")
            return
        if isinstance(roh, list):
            self._zeilen = [
                zeile for zeile in roh
                if isinstance(zeile, dict) and str(zeile.get("text", "")).strip()
            ][-self._hoechstens:]

    def _speichern(self) -> None:
        try:
            self._datei.parent.mkdir(parents=True, exist_ok=True)
            ablage = self._datei.with_suffix(".tmp")
            ablage.write_text(
                json.dumps(self._zeilen, ensure_ascii=False), encoding="utf-8"
            )
            ablage.replace(self._datei)
        except Exception:  # noqa: BLE001 - der Verlauf darf nie eine Antwort kosten.
            logger.debug("Der Chatverlauf liess sich nicht speichern.", exc_info=True)

    def eintragen(self, rolle: str, text: str, *, quelle: str = "") -> dict[str, Any] | None:
        """Haengt eine Zeile an und gibt sie zurueck (``None``, wenn leer)."""

        text = str(text or "").strip()
        if not text:
            return None
        zeit = time.time()
        zeile = {
            "rolle": "user" if rolle == "user" else "orb",
            "text": text[:ZEILE_HOECHSTENS],
            "zeit": round(zeit, 1),
            "quelle": str(quelle or ""),
        }
        with self._sperre:
            # Dieselbe Zeile zweimal hintereinander (etwa bei einer
            # wiederholten Abgabe vom Handy) wird nur einmal vermerkt.
            if self._zeilen:
                letzte = self._zeilen[-1]
                if (
                    letzte.get("rolle") == zeile["rolle"]
                    and letzte.get("text") == zeile["text"]
                    and zeit - float(letzte.get("zeit", 0) or 0) < 20
                ):
                    return None
            self._zeilen.append(zeile)
            del self._zeilen[: -self._hoechstens]
            self._speichern()
        return self.fuer_anzeige(zeile)

    @staticmethod
    def fuer_anzeige(zeile: dict[str, Any]) -> dict[str, Any]:
        zeit = float(zeile.get("zeit", 0) or 0)
        return {
            **zeile,
            "uhrzeit": time.strftime("%H:%M", time.localtime(zeit)) if zeit else "",
            "tag": _tag(zeit) if zeit else "",
        }

    def letzte(self, anzahl: int = 80) -> list[dict[str, Any]]:
        anzahl = max(1, min(int(anzahl or 80), self._hoechstens))
        with self._sperre:
            auswahl = list(self._zeilen[-anzahl:])
        return [self.fuer_anzeige(zeile) for zeile in auswahl]

    def leeren(self) -> None:
        with self._sperre:
            self._zeilen.clear()
            self._speichern()
