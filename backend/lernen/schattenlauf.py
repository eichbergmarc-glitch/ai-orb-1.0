"""Der Schattenlauf: beide rechnen, nur einer antwortet.

Der Schüler löst dieselbe Aufgabe wie der Lehrer, ohne dass der Benutzer
etwas davon merkt. Verglichen wird gegen die Rubrik; gespeichert wird
**nicht** das Gespräch, sondern die Lehre daraus.

Was gespeichert wird
    Die Fehlerklasse ("Werkzeug nicht aufgerufen, obwohl verlangt"), die
    Kategorie, die Werkzeugentscheidung und ein Verbesserungsvorschlag.

Was nicht gespeichert wird
    Der Wortlaut der Anfrage, Namen, Adressen, Zugangsdaten, Dateipfade mit
    dem Benutzernamen, und alles, was durch die Anonymisierung fällt. Auch
    keine internen Gedankengänge des Lehrers - danach wird nicht gefragt
    und was ungefragt käme, wird nicht abgelegt.

Der Schattenlauf ist standardmässig AUS (``lernen.schattenlauf_aktiv``). Er
kostet lokale Rechenzeit, und Rechenzeit ist bei diesem Orb das knappste
Gut.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any

from backend.config import get_config
from backend.system.logging_setup import get_logger
from backend.utils.store import JsonStore

logger = get_logger(__name__)

#: Muster, die vor jeder Speicherung entfernt werden. Lieber einmal zu viel
#: unkenntlich gemacht als einmal zu wenig.
_MUSTER: tuple[tuple[str, str], ...] = (
    (r"[\w.+-]+@[\w-]+\.[\w.]+", "<mail>"),
    (r"\b(?:\+41|0041|0)[\s/.-]?\d{2}[\s/.-]?\d{3}[\s/.-]?\d{2}[\s/.-]?\d{2}\b", "<telefon>"),
    (r"\b[A-Z]{2}\d{2}[\sA-Z0-9]{10,30}\b", "<iban>"),
    (r"\b(?:sk|pk|api|key|token|bearer)[-_]?[A-Za-z0-9_\-]{16,}\b", "<schluessel>"),
    (r"[A-Za-z]:\\Users\\[^\\\s]+", "<benutzerordner>"),
    (r"/(?:home|Users)/[^/\s]+", "<benutzerordner>"),
    (r"\bhttps?://\S+", "<adresse>"),
    (r"\b\d{6,}\b", "<zahl>"),
)


def anonymisieren(text: str) -> str:
    """Entfernt Personenbezug und Geheimnisse aus einem Text.

    Das ist kein Ersatz für Nachdenken darüber, was überhaupt gespeichert
    wird - es ist die letzte Schranke davor.
    """

    sauber = str(text or "")
    for muster, ersatz in _MUSTER:
        sauber = re.sub(muster, ersatz, sauber, flags=re.IGNORECASE)
    return sauber


@dataclass
class Lehre:
    """Was aus einem Schattenlauf übrig bleiben darf."""

    kategorie: str
    fehlerklasse: str
    werkzeugentscheidung: str = ""
    verbesserungsvorschlag: str = ""
    aufgabenmuster: str = ""
    zeitpunkt: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kategorie": self.kategorie,
            "fehlerklasse": self.fehlerklasse,
            "werkzeugentscheidung": self.werkzeugentscheidung,
            "verbesserungsvorschlag": self.verbesserungsvorschlag,
            "aufgabenmuster": self.aufgabenmuster,
            "zeitpunkt": self.zeitpunkt,
        }


#: Die Fehlerklassen, die der Vergleich unterscheiden kann. Bewusst wenige
#: und abstrakt - sie sollen ueber viele Faelle hinweg zaehlbar sein.
FEHLERKLASSEN: tuple[str, ...] = (
    "werkzeug_nicht_aufgerufen",
    "falsches_werkzeug",
    "werkzeugaufruf_ungueltig",
    "inhaltlich_unvollstaendig",
    "erfundene_angabe",
    "zu_lang",
    "zu_kurz",
    "sprache_verfehlt",
    "kein_unterschied",
)


class Schattenbuch:
    """Sammelt die Lehren - anonymisiert, gezählt, ohne Wortlaut."""

    def __init__(self, *, store: JsonStore | None = None) -> None:
        self._store = store or JsonStore("lernen/schattenbuch.json", {"lehren": []})
        konfig = get_config()
        self._aktiv = bool(konfig.get("lernen.schattenlauf_aktiv", False))
        self._je_stunde = max(
            0, int(konfig.get("lernen.schattenlaeufe_je_stunde", 20) or 0)
        )
        self._zeiten: list[float] = []

    @property
    def aktiv(self) -> bool:
        return self._aktiv

    def darf_laufen(self) -> bool:
        """Ob jetzt ein weiterer Schattenlauf erlaubt ist."""

        if not self._aktiv or self._je_stunde <= 0:
            return False
        jetzt = time.time()
        self._zeiten = [z for z in self._zeiten if jetzt - z < 3600.0]
        if len(self._zeiten) >= self._je_stunde:
            return False
        self._zeiten.append(jetzt)
        return True

    def eintragen(self, lehre: Lehre) -> None:
        """Legt eine Lehre ab - anonymisiert, ohne Wortlaut der Anfrage."""

        sauber = Lehre(
            kategorie=lehre.kategorie,
            fehlerklasse=lehre.fehlerklasse,
            werkzeugentscheidung=anonymisieren(lehre.werkzeugentscheidung),
            verbesserungsvorschlag=anonymisieren(lehre.verbesserungsvorschlag),
            aufgabenmuster=anonymisieren(lehre.aufgabenmuster)[:120],
            zeitpunkt=lehre.zeitpunkt,
        )
        lehren = list(self._store.get("lehren", []) or [])
        lehren.append(sauber.to_dict())
        self._store.set("lehren", lehren[-2000:])

    def haeufigste_fehler(self, kategorie: str = "", *, anzahl: int = 5) -> list[tuple[str, int]]:
        """Woran es am häufigsten hakt - die Arbeitsliste für Verbesserungen."""

        zaehler: dict[str, int] = {}
        for roh in self._store.get("lehren", []) or []:
            if kategorie and roh.get("kategorie") != kategorie:
                continue
            klasse = str(roh.get("fehlerklasse", "")) or "unbekannt"
            zaehler[klasse] = zaehler.get(klasse, 0) + 1
        return sorted(zaehler.items(), key=lambda paar: paar[1], reverse=True)[:anzahl]


def fehlerklasse_bestimmen(
    *,
    verlangte_werkzeuge: list[str],
    schueler_werkzeuge: list[str],
    schueler_aufruf_ungueltig: bool,
    schueler_punkte: float,
    lehrer_punkte: float,
    schueler_halluzination: bool,
) -> str:
    """Ordnet einen Unterschied einer der festen Fehlerklassen zu."""

    if schueler_aufruf_ungueltig:
        return "werkzeugaufruf_ungueltig"
    if verlangte_werkzeuge:
        fehlend = [w for w in verlangte_werkzeuge if w not in schueler_werkzeuge]
        if fehlend and not schueler_werkzeuge:
            return "werkzeug_nicht_aufgerufen"
        if fehlend and schueler_werkzeuge:
            return "falsches_werkzeug"
    if schueler_halluzination:
        return "erfundene_angabe"
    if schueler_punkte < lehrer_punkte:
        return "inhaltlich_unvollstaendig"
    return "kein_unterschied"


__all__ = [
    "FEHLERKLASSEN",
    "Lehre",
    "Schattenbuch",
    "anonymisieren",
    "fehlerklasse_bestimmen",
]
