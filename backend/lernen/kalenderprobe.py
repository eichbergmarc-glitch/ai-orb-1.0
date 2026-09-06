"""Ein Kalender zum Messen - dieselbe Schnittstelle, feste Termine.

Warum es diese Datei gibt: ``rechner_02`` fragt "was steht diese Woche in
meinem Kalender?" und verlangt dafür ``termine_ansehen``. Dieses Werkzeug
spricht mit Google, und ohne Anmeldung war es in keinem Messlauf
angemeldet. Beide Modelle standen deshalb in fünf Läufen auf "nicht
bestanden" - für etwas, das sie nicht zu verantworten hatten. Eine Messung,
die fehlende Zugangsdaten als Modellschwäche verbucht, misst den Rechner
des Benutzers, nicht das Modell.

Was hier ausgetauscht wird, ist **ausschliesslich die Datenquelle**. Der
Probekalender bietet genau die Methode, die ``TermineAnsehenTool`` aufruft
(``termine(von=, bis=, suche=, limit=)`` mit ``Termin``-Objekten), und
wird in dasselbe ``build_kalender_tools`` gereicht. Werkzeugname,
Parameter, Rückgabeformat und Fehlerverhalten sind damit die echten - es
ist kein nachgebautes Werkzeug, sondern das richtige mit einem anderen
Kalender dahinter.

Was der Prüfling **nicht** bekommt: die Antwort. Die Termine stehen
nirgends in der Aufgabe; wer sie nennen will, muss das Werkzeug aufrufen.
Und beide Modelle bekommen dieselben Termine - die Liste hängt nur vom
Wochentag ab, nicht vom Modell, nicht vom Lauf und nicht vom Zufall.

Für den echten Zugang gibt es weiterhin den Weg über ``KalenderClient``;
er gehört in einen Integrationstest, nicht in eine Modellmessung.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from backend.integrations.kalender.client import KalenderFehler, Termin
from backend.integrations.kalender.zeit import ortszeit
from backend.system.logging_setup import get_logger

logger = get_logger(__name__)

#: Die Probetermine, als Abstand in TAGEN AB HEUTE.
#:
#: Bewusst relativ zu heute und nicht zum Montag: Sonst fiele der
#: Dienstagstermin an einem Mittwoch aus dem Zeitraum "woche", und
#: derselbe Prüffall haette je nach Wochentag ein anderes Ergebnis. Alle
#: vier liegen innerhalb der naechsten sieben Tage - an jedem Wochentag.
#:
#: Bewusst wenige und unverwechselbar: Ein Modell, das ``termine_ansehen``
#: wirklich aufruft, kann "Zahnarzt" nennen; eines, das rät, nicht. Genau
#: das soll der Prüffall unterscheiden.
PROBETERMINE: tuple[dict[str, Any], ...] = (
    {"tag": 1, "stunde": 9, "dauer": 60, "titel": "Teambesprechung", "ort": "Büro"},
    {"tag": 2, "stunde": 14, "dauer": 45, "titel": "Zahnarzt", "ort": "Bahnhofstrasse"},
    {"tag": 3, "stunde": 18, "dauer": 120, "titel": "Elternabend", "ort": "Schulhaus"},
    {"tag": 5, "stunde": 11, "dauer": 30, "titel": "Velo abholen", "ort": "Werkstatt"},
)

#: Woran sich das Ergebnis eines gelungenen Aufrufs erkennen lässt.
PROBE_STICHWORTE: tuple[str, ...] = tuple(
    str(eintrag["titel"]) for eintrag in PROBETERMINE
)


class Probekalender:
    """Ein Kalender mit festen Terminen - für Messläufe, nicht für den Betrieb.

    Args:
        gestoert: Wenn gesetzt, wirft jeder Zugriff ``KalenderFehler`` mit
            diesem Text. Damit lässt sich prüfen, dass ein
            Authentifizierungs- oder Netzfehler als Umgebungsfehler
            eingeordnet wird und nicht als Modellfehler - ohne dafür eine
            echte Anmeldung kaputtmachen zu müssen.
        heute: Der Bezugstag. Ohne Angabe der heutige.
    """

    #: Damit der Messlauf im Protokoll sagen kann, womit er gemessen hat.
    quelle = "probekalender"

    def __init__(self, *, gestoert: str = "", heute: datetime | None = None) -> None:
        self._gestoert = str(gestoert or "")
        self._heute = ortszeit(heute) if heute else ortszeit()

    def _tagesanfang(self) -> datetime:
        return self._heute.replace(hour=0, minute=0, second=0, microsecond=0)

    def alle(self) -> list[Termin]:
        """Die Probewoche als Terminliste."""

        heute = self._tagesanfang()
        termine: list[Termin] = []
        for nummer, eintrag in enumerate(PROBETERMINE, start=1):
            beginn = heute + timedelta(
                days=int(eintrag["tag"]), hours=int(eintrag["stunde"])
            )
            termine.append(
                Termin(
                    id=f"probe-{nummer}",
                    titel=str(eintrag["titel"]),
                    beginn=beginn,
                    ende=beginn + timedelta(minutes=int(eintrag["dauer"])),
                    ganztags=False,
                    ort=str(eintrag.get("ort", "")),
                    beschreibung="",
                    kalender="probe",
                )
            )
        return termine

    # --- Die Schnittstelle, die das echte Werkzeug aufruft ----------------

    def termine(
        self,
        *,
        von: datetime | None = None,
        bis: datetime | None = None,
        suche: str = "",
        limit: int = 20,
    ) -> list[Termin]:
        """Wie ``KalenderClient.termine`` - nur ohne Google."""

        if self._gestoert:
            raise KalenderFehler(self._gestoert)

        von = ortszeit(von) if von else self._tagesanfang()
        bis = ortszeit(bis) if bis else (von + timedelta(days=7))
        stichwort = str(suche or "").strip().lower()

        gefunden = [
            termin
            for termin in self.alle()
            if termin.beginn is not None
            and von <= termin.beginn < bis
            and (not stichwort or stichwort in termin.titel.lower())
        ]
        gefunden.sort(key=lambda t: t.beginn or von)
        return gefunden[: max(1, int(limit or 20))]


def probekalender_werkzeuge(*, gestoert: str = "") -> list[Any]:
    """Baut die ECHTEN Kalenderwerkzeuge über den Probekalender."""

    from backend.tools.kalender_tools import build_kalender_tools

    return build_kalender_tools(Probekalender(gestoert=gestoert))


__all__ = [
    "PROBETERMINE",
    "PROBE_STICHWORTE",
    "Probekalender",
    "probekalender_werkzeuge",
]
