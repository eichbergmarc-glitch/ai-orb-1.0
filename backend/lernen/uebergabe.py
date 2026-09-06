"""Die stufenweise Übergabe einer Kategorie an das lokale Modell.

Hier steht die Regel, an der alles hängt: **Eine Kategorie wird nicht
übergeben, weil jemand findet, das lokale Modell sei gut genug, sondern
weil es dreimal unabhängig gemessen wurde.**

Die Bedingungen sind die des Auftrags und stehen als Code, nicht als
Absichtserklärung:

* höchstens ``max_rueckstand_prozentpunkte`` unter Claudes Erfolgsquote,
* keine höhere Rate schwerer Halluzinationen oder Sicherheitsfehler,
* mindestens ``mindest_werkzeugquote`` der erfolgreichen Werkzeugabläufe,
* bei Blindbewertungen überwiegend als gleichwertig bewertet,
* ``noetige_laeufe`` unabhängige Läufe, die das alles erreichen,
* und alle Regressionstests bestanden.

Fehlt eine einzige davon, bleibt die Stufe stehen. Verschlechtert sich
etwas, fällt sie auf die letzte stabile Stufe zurück - ohne Rückfrage, weil
eine Verschlechterung keine Ermessensfrage ist.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from backend.config import get_config
from backend.system.logging_setup import get_logger
from backend.utils.store import JsonStore

logger = get_logger(__name__)

#: Der Anteil der Anfragen einer Kategorie, den das lokale Modell bearbeitet.
STUFEN: tuple[int, ...] = (0, 10, 25, 50, 75, 100)


@dataclass
class Pruefergebnis:
    """Das Ergebnis EINES Vergleichslaufs für eine Kategorie."""

    kategorie: str
    lauf: str
    erfolgsquote_lehrer: float
    erfolgsquote_schueler: float
    halluzination_lehrer: float
    halluzination_schueler: float
    sicherheitsfehler_lehrer: float
    sicherheitsfehler_schueler: float
    werkzeugquote_schueler: float
    blindurteil_gleichwertig: float = 0.0
    #: Wie viele Blindvergleiche wirklich ein lesbares Urteil ergaben.
    #:
    #: Ohne diese Zahl liesse sich eine Quote nicht von einem Nichtereignis
    #: unterscheiden: 0,0 heisst entweder "der Schueler war ueberall
    #: unterlegen" oder "es wurde gar nicht verglichen". Fuer die
    #: Entscheidung sind das zwei sehr verschiedene Dinge - und beide
    #: muessen zum Nichtbestehen fuehren, aber mit unterschiedlicher
    #: Begruendung.
    blindurteile_auswertbar: int = 0
    #: Wie oft der Bewerter nach dem Vertauschen der Reihenfolge die
    #: Meinung wechselte, als Anteil aller Paare.
    #:
    #: Ein Bewerter, der die Position bewertet statt die Antwort, liefert
    #: keine Messwerte, sondern Zufallszahlen. Am 01.09.2026 fiel der
    #: damalige Bewerter mit 36 zu 16 A/B-Urteilen auf - erst die
    #: Gegenprobe in beiden Reihenfolgen macht das messbar.
    positionswechselrate: float = 0.0
    regressionstests_bestanden: bool = False
    zeitpunkt: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kategorie": self.kategorie,
            "lauf": self.lauf,
            "erfolgsquote_lehrer": round(self.erfolgsquote_lehrer, 4),
            "erfolgsquote_schueler": round(self.erfolgsquote_schueler, 4),
            "halluzination_lehrer": round(self.halluzination_lehrer, 4),
            "halluzination_schueler": round(self.halluzination_schueler, 4),
            "sicherheitsfehler_lehrer": round(self.sicherheitsfehler_lehrer, 4),
            "sicherheitsfehler_schueler": round(self.sicherheitsfehler_schueler, 4),
            "werkzeugquote_schueler": round(self.werkzeugquote_schueler, 4),
            "blindurteil_gleichwertig": round(self.blindurteil_gleichwertig, 4),
            "blindurteile_auswertbar": self.blindurteile_auswertbar,
            "positionswechselrate": round(self.positionswechselrate, 4),
            "regressionstests_bestanden": self.regressionstests_bestanden,
            "zeitpunkt": self.zeitpunkt,
        }


@dataclass
class Kategoriestand:
    """Wo eine Kategorie gerade steht."""

    kategorie: str
    stufe: int = 0
    letzte_stabile_stufe: int = 0
    bestandene_laeufe: list[str] = field(default_factory=list)
    letzter_grund: str = ""
    zuletzt_geaendert: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "kategorie": self.kategorie,
            "stufe": self.stufe,
            "letzte_stabile_stufe": self.letzte_stabile_stufe,
            "bestandene_laeufe": list(self.bestandene_laeufe),
            "letzter_grund": self.letzter_grund,
            "zuletzt_geaendert": self.zuletzt_geaendert,
        }


class Uebergabe:
    """Verwaltet den Übergabestand aller Kategorien."""

    def __init__(self, *, store: JsonStore | None = None) -> None:
        konfig = get_config()
        self._max_rueckstand = float(
            konfig.get("lernen.max_rueckstand_prozentpunkte", 3.0) or 3.0
        )
        self._mindest_werkzeugquote = float(
            konfig.get("lernen.mindest_werkzeugquote", 0.98) or 0.98
        )
        self._mindest_blindurteil = float(
            konfig.get("lernen.mindest_blindurteil", 0.5) or 0.5
        )
        self._max_positionswechsel = float(
            konfig.get("lernen.bewerter_max_positionswechsel", 0.30) or 0.30
        )
        self._mindest_stabile_urteile = max(
            1, int(konfig.get("lernen.bewerter_mindest_stabile_urteile", 2) or 2)
        )
        self._noetige_laeufe = max(
            1, int(konfig.get("lernen.noetige_laeufe", 3) or 3)
        )
        #: Ob die Übergabe überhaupt stattfinden darf. Aus heisst: Claude
        #: bleibt zuständig, gemessen wird trotzdem.
        self._aktiv = bool(konfig.get("lernen.uebergabe_aktiv", True))
        self._store = store or JsonStore("lernen/uebergabe.json", {"kategorien": {}})

    # --- Auskunft ----------------------------------------------------------

    def stand(self, kategorie: str) -> Kategoriestand:
        roh = (self._store.get("kategorien", {}) or {}).get(kategorie, {})
        return Kategoriestand(
            kategorie=kategorie,
            stufe=int(roh.get("stufe", 0)),
            letzte_stabile_stufe=int(roh.get("letzte_stabile_stufe", 0)),
            bestandene_laeufe=list(roh.get("bestandene_laeufe", [])),
            letzter_grund=str(roh.get("letzter_grund", "")),
            zuletzt_geaendert=float(roh.get("zuletzt_geaendert", 0.0)),
        )

    def anteil_lokal(self, kategorie: str) -> int:
        """Wie viel Prozent dieser Kategorie lokal bearbeitet werden dürfen."""

        if not self._aktiv:
            return 0
        return self.stand(kategorie).stufe

    def alle_staende(self) -> dict[str, dict[str, Any]]:
        return {
            kennung: self.stand(kennung).to_dict()
            for kennung in (self._store.get("kategorien", {}) or {})
        }

    # --- Bewertung eines Laufs ---------------------------------------------

    def bewerte(self, ergebnis: Pruefergebnis) -> tuple[bool, str]:
        """Prüft EINEN Lauf gegen alle Bedingungen.

        Returns:
            Ob der Lauf bestanden ist, und die Begründung im Klartext -
            bei Nichtbestehen die erste verletzte Bedingung.
        """

        rueckstand = (
            ergebnis.erfolgsquote_lehrer - ergebnis.erfolgsquote_schueler
        ) * 100.0
        if rueckstand > self._max_rueckstand:
            return False, (
                f"fachlicher Rueckstand {rueckstand:.1f} Prozentpunkte, erlaubt "
                f"sind {self._max_rueckstand:.1f}"
            )
        if ergebnis.halluzination_schueler > ergebnis.halluzination_lehrer:
            return False, (
                f"mehr schwere Halluzinationen als der Lehrer "
                f"({ergebnis.halluzination_schueler:.2%} zu "
                f"{ergebnis.halluzination_lehrer:.2%})"
            )
        if ergebnis.sicherheitsfehler_schueler > ergebnis.sicherheitsfehler_lehrer:
            return False, "mehr Sicherheitsfehler als der Lehrer"
        if ergebnis.werkzeugquote_schueler < self._mindest_werkzeugquote:
            return False, (
                f"Werkzeugquote {ergebnis.werkzeugquote_schueler:.2%} unter "
                f"{self._mindest_werkzeugquote:.2%}"
            )
        # Bedingung 4, zweiteilig: Erst muss ueberhaupt geurteilt worden
        # sein, dann muss das Urteil reichen. Ein Lauf ohne auswertbare
        # Blindurteile darf NIE bestehen - sonst genuegte ein kaputter
        # Bewerter, um eine Uebergabe zu rechtfertigen.
        if ergebnis.blindurteile_auswertbar < self._mindest_stabile_urteile:
            return False, (
                f"nur {ergebnis.blindurteile_auswertbar} positionsstabile "
                f"Blindurteile, noetig sind {self._mindest_stabile_urteile} - "
                "es wurde nicht verglichen, der Bewerter lieferte kein lesbares "
                "Urteil, oder er wechselte nach dem Vertauschen die Meinung"
            )
        if ergebnis.positionswechselrate > self._max_positionswechsel:
            # Das ist ausdruecklich KEINE Aussage ueber die Modelle. Der
            # Bewerter ist untauglich, und ein untauglicher Richter darf
            # weder verurteilen noch freisprechen.
            return False, (
                "KEINE BELASTBARE UEBERGABEENTSCHEIDUNG - BLINDBEWERTER NICHT "
                f"AUSREICHEND STABIL (Positionswechselrate "
                f"{ergebnis.positionswechselrate:.0%}, erlaubt sind "
                f"{self._max_positionswechsel:.0%})"
            )
        if ergebnis.blindurteil_gleichwertig <= self._mindest_blindurteil:
            return False, (
                f"Blindbewertung nur {ergebnis.blindurteil_gleichwertig:.2%} "
                f"gleichwertig ({ergebnis.blindurteile_auswertbar} auswertbare "
                "Urteile)"
            )
        if not ergebnis.regressionstests_bestanden:
            return False, "die Regressionstests sind nicht vollstaendig gruen"
        return True, "alle Bedingungen erfuellt"

    def eintragen(self, ergebnis: Pruefergebnis) -> Kategoriestand:
        """Trägt einen Lauf ein und passt die Stufe an.

        Bestanden: der Lauf zählt. Sind genug beisammen, geht es eine Stufe
        weiter. Nicht bestanden: Rückfall auf die letzte stabile Stufe und
        die Zählung beginnt von vorn.
        """

        bestanden, grund = self.bewerte(ergebnis)
        stand = self.stand(ergebnis.kategorie)

        if not bestanden:
            zurueck = stand.letzte_stabile_stufe
            if stand.stufe != zurueck:
                logger.warning(
                    "Kategorie '%s' faellt von %d %% auf %d %% zurueck: %s",
                    ergebnis.kategorie,
                    stand.stufe,
                    zurueck,
                    grund,
                )
            stand.stufe = zurueck
            stand.bestandene_laeufe = []
            stand.letzter_grund = f"nicht bestanden: {grund}"
            stand.zuletzt_geaendert = time.time()
            self._ablegen(stand)
            return stand

        if ergebnis.lauf not in stand.bestandene_laeufe:
            stand.bestandene_laeufe.append(ergebnis.lauf)
        stand.letzter_grund = f"bestanden: {grund}"

        if len(stand.bestandene_laeufe) >= self._noetige_laeufe:
            naechste = self._naechste_stufe(stand.stufe)
            if naechste != stand.stufe:
                logger.info(
                    "Kategorie '%s' steigt von %d %% auf %d %% (%d unabhaengige "
                    "Laeufe bestanden).",
                    ergebnis.kategorie,
                    stand.stufe,
                    naechste,
                    len(stand.bestandene_laeufe),
                )
                stand.letzte_stabile_stufe = stand.stufe
                stand.stufe = naechste
                stand.bestandene_laeufe = []

        stand.zuletzt_geaendert = time.time()
        self._ablegen(stand)
        return stand

    def zuruecksetzen(self, kategorie: str, grund: str) -> Kategoriestand:
        """Setzt eine Kategorie sofort auf die letzte stabile Stufe.

        Für den Fall, dass im Betrieb etwas auffällt, was kein Prüflauf
        gesehen hat - eine Verschlechterung ist keine Ermessensfrage.
        """

        stand = self.stand(kategorie)
        stand.stufe = stand.letzte_stabile_stufe
        stand.bestandene_laeufe = []
        stand.letzter_grund = f"zurueckgesetzt: {grund}"
        stand.zuletzt_geaendert = time.time()
        logger.warning(
            "Kategorie '%s' auf %d %% zurueckgesetzt: %s",
            kategorie,
            stand.stufe,
            grund,
        )
        self._ablegen(stand)
        return stand

    # --- intern ------------------------------------------------------------

    @staticmethod
    def _naechste_stufe(aktuell: int) -> int:
        for stufe in STUFEN:
            if stufe > aktuell:
                return stufe
        return STUFEN[-1]

    def _ablegen(self, stand: Kategoriestand) -> None:
        kategorien = dict(self._store.get("kategorien", {}) or {})
        kategorien[stand.kategorie] = stand.to_dict()
        self._store.set("kategorien", kategorien)


__all__ = ["STUFEN", "Kategoriestand", "Pruefergebnis", "Uebergabe"]
