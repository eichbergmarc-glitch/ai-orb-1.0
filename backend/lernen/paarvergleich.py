"""Der Paarvergleich: zwei Antworten, ein blinder Bewerter, ein Urteil.

Bis zum 1. September 2026 bewertete der Messlauf jede Antwort für sich -
gegen Erwartung und Rubrik. Das beantwortet "war die Antwort richtig", aber
nicht "war der Schüler so gut wie der Lehrer". Genau das verlangt aber
Übergabebedingung 4, und deshalb stand ``blindurteil_gleichwertig``
dauerhaft auf 0: Es gab schlicht niemanden, der Paare verglichen hätte.

Dieses Modul schliesst die Lücke in drei Schritten:

1. **Antworten aufheben.** Der Messlauf legt je Lauf und Modell ab, was das
   Modell geantwortet hat (``data/lernen/antworten/<lauf>-<modell>.jsonl``).
   Ohne diesen Schritt gäbe es später nichts zu vergleichen.
2. **Paare bilden und blind vorlegen.** Zu jedem Prüfstück, das beide
   beantwortet haben, wird eine Vorlage gebaut: maskiert, mit ausgelostem
   A/B, ohne Herkunft, ohne Werkzeugliste, ohne Laufnamen.
3. **Ein drittes Modell urteilen lassen.** Nicht der Lehrer, nicht der
   Schüler - beide sind befangen, und ``modellurteiler`` bricht ab, wenn
   man es doch versucht.

Die Urteile landen in ``data/lernen/blindurteile.jsonl``, angehängt, nie
geändert. Aus ihnen entsteht die Gleichwertigkeitsquote, und nur aus ihnen.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from backend.lernen.blindbewertung import (
    UNMOEGLICH,
    URTEILSANWEISUNG,
    Paarurteil,
    bewerterguete,
    paarquote,
    paarurteil_bilden,
    Blindurteil,
    Kandidat,
    Vergleichsfall,
    auswertbare,
    gleichwertigkeitsquote,
    blind_bewerten,
    modellurteiler,
    vorlage_bauen,
)
from backend.system.logging_setup import get_logger
from backend.utils.paths import get_data_dir

logger = get_logger(__name__)

#: Die Herkunftsnamen im Vergleich. Sie sind bewusst neutral: Der Bewerter
#: bekommt sie nie zu sehen, und in den Urteilen steht die Rolle, nicht das
#: Modell - so bleibt die Ablage auch dann lesbar, wenn ein anderes Modell
#: die Rolle uebernimmt.
LEHRER = "lehrer"
SCHUELER = "schueler"


# --- Schritt 1: Antworten aufheben ----------------------------------------


@dataclass
class Antwort:
    """Was ein Modell zu einem Prüfstück gesagt hat."""

    lauf: str
    modell: str
    fall: str
    kategorie: str
    aufgabe: str
    antwort: str
    werkzeuge: list[str]
    zeitpunkt: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "lauf": self.lauf,
            "modell": self.modell,
            "fall": self.fall,
            "kategorie": self.kategorie,
            "aufgabe": self.aufgabe,
            "antwort": self.antwort,
            "werkzeuge": list(self.werkzeuge),
            "zeitpunkt": self.zeitpunkt,
        }


class Antwortablage:
    """Hebt die Antworten eines Laufs auf - je Lauf und Modell eine Datei.

    Warum nicht in ``messungen.jsonl``: Die Messreihe ist eine Reihe von
    Messwerten und soll es bleiben. Antworten sind Rohmaterial für den
    Vergleich, oft lang, und werden nach der Auswertung nicht mehr
    gebraucht. Getrennte Dateien halten beides sauber.
    """

    def __init__(self, *, verzeichnis: Path | None = None) -> None:
        self._basis = verzeichnis or (get_data_dir() / "lernen" / "antworten")
        self._basis.mkdir(parents=True, exist_ok=True)
        self._sperre = threading.Lock()

    def pfad(self, lauf: str, modell: str) -> Path:
        sicher = "".join(z if z.isalnum() or z in "-_" else "_" for z in f"{lauf}-{modell}")
        return self._basis / f"{sicher}.jsonl"

    def ablegen(self, antwort: Antwort) -> None:
        with self._sperre:
            try:
                with self.pfad(antwort.lauf, antwort.modell).open(
                    "a", encoding="utf-8"
                ) as datei:
                    datei.write(json.dumps(antwort.to_dict(), ensure_ascii=False) + "\n")
            except OSError:
                logger.exception("Eine Antwort liess sich nicht ablegen.")

    def lesen(self, lauf: str, modell: str) -> dict[str, Antwort]:
        """Alle Antworten eines Laufs, nach Prüfstück."""

        pfad = self.pfad(lauf, modell)
        gefunden: dict[str, Antwort] = {}
        if not pfad.exists():
            return gefunden
        try:
            for zeile in pfad.read_text(encoding="utf-8").splitlines():
                if not zeile.strip():
                    continue
                roh = json.loads(zeile)
                gefunden[str(roh.get("fall", ""))] = Antwort(
                    lauf=str(roh.get("lauf", "")),
                    modell=str(roh.get("modell", "")),
                    fall=str(roh.get("fall", "")),
                    kategorie=str(roh.get("kategorie", "")),
                    aufgabe=str(roh.get("aufgabe", "")),
                    antwort=str(roh.get("antwort", "")),
                    werkzeuge=list(roh.get("werkzeuge", [])),
                    zeitpunkt=float(roh.get("zeitpunkt", 0.0)),
                )
        except (OSError, ValueError):
            logger.exception("Die Antwortablage liess sich nicht lesen: %s", pfad)
        return gefunden


# --- Schritt 2: Paare bilden ----------------------------------------------


def paare_bilden(
    ablage: Antwortablage, *, lauf: str, lehrer: str, schueler: str
) -> list[tuple[str, Vergleichsfall]]:
    """Bildet die Vergleichsfälle - nur, wo beide geantwortet haben.

    Returns:
        Je Paar die Kategorie und den Vergleichsfall. Die Kennung des
        Falls ist ``<lauf>-<fall>``: eindeutig genug fürs Auslosen und
        fürs Wiederfinden, und der Bewerter sieht sie ohnehin nie.
    """

    vom_lehrer = ablage.lesen(lauf, lehrer)
    vom_schueler = ablage.lesen(lauf, schueler)

    paare: list[tuple[str, Vergleichsfall]] = []
    for fall in sorted(set(vom_lehrer) & set(vom_schueler)):
        eine = vom_lehrer[fall]
        andere = vom_schueler[fall]
        if not eine.antwort.strip() or not andere.antwort.strip():
            continue
        paare.append(
            (
                eine.kategorie or andere.kategorie,
                Vergleichsfall(
                    kennung=f"{lauf}-{fall}",
                    aufgabe=eine.aufgabe or andere.aufgabe,
                    lehrer=Kandidat(LEHRER, eine.antwort, tuple(eine.werkzeuge)),
                    schueler=Kandidat(SCHUELER, andere.antwort, tuple(andere.werkzeuge)),
                ),
            )
        )
    fehlend = set(vom_lehrer) ^ set(vom_schueler)
    if fehlend:
        logger.warning(
            "%d Pruefstuecke lassen sich nicht paaren (nur ein Modell hat "
            "geantwortet): %s",
            len(fehlend),
            ", ".join(sorted(fehlend)),
        )
    return paare


# --- Schritt 3: Urteile ablegen -------------------------------------------


class Urteilsablage:
    """Die Blindurteile - angehängt, nie geändert."""

    def __init__(self, *, verzeichnis: Path | None = None) -> None:
        basis = verzeichnis or (get_data_dir() / "lernen")
        basis.mkdir(parents=True, exist_ok=True)
        self._pfad = basis / "blindurteile.jsonl"
        self._sperre = threading.Lock()

    @property
    def pfad(self) -> Path:
        return self._pfad

    def anhaengen(
        self,
        urteil: Paarurteil,
        *,
        lauf: str,
        kategorie: str,
        bewerter: str,
        lehrer: str,
        schueler: str,
    ) -> None:
        """Legt ein positionskontrolliertes Paarurteil ab.

        Beide Durchgänge stehen mit drin - wer nachrechnen will, ob ein
        Urteil zu Recht als stabil gilt, soll das können, ohne den Lauf
        zu wiederholen.
        """

        eintrag = {
            **urteil.to_dict(),
            "lauf": lauf,
            "kategorie": kategorie,
            "bewerter": bewerter,
            "lehrermodell": lehrer,
            "schuelermodell": schueler,
            "zeitpunkt": time.time(),
        }
        with self._sperre:
            try:
                with self._pfad.open("a", encoding="utf-8") as datei:
                    datei.write(json.dumps(eintrag, ensure_ascii=False) + "\n")
            except OSError:
                logger.exception("Ein Blindurteil liess sich nicht ablegen.")

    def alle(self, *, lauf: str = "") -> list[dict[str, Any]]:
        if not self._pfad.exists():
            return []
        eintraege: list[dict[str, Any]] = []
        try:
            for zeile in self._pfad.read_text(encoding="utf-8").splitlines():
                if not zeile.strip():
                    continue
                roh = json.loads(zeile)
                if lauf and roh.get("lauf") != lauf:
                    continue
                eintraege.append(roh)
        except (OSError, ValueError):
            logger.exception("Die Urteilsablage liess sich nicht lesen.")
        return eintraege


def quoten_je_kategorie(
    eintraege: list[dict[str, Any]]
) -> dict[str, dict[str, float | int]]:
    """Gleichwertigkeitsquote und Bewerterdiagnose je Kategorie.

    Genau diese Werte gehen als ``blindurteil_gleichwertig`` und
    ``blindurteile_auswertbar`` in das Prüfergebnis ein - berechnet aus
    abgelegten Urteilen, nie eingetragen. Zählt werden nur
    positionsstabile Urteile; instabile und gescheiterte stehen im
    Nenner und drücken die Quote, wie sie sollen.
    """

    nach_kategorie: dict[str, list[Paarurteil]] = {}
    for roh in eintraege:
        urteil = Paarurteil(
            kennung=str(roh.get("kennung", "")),
            zustand=str(roh.get("zustand", "")),
            gewinner_herkunft=str(roh.get("gewinner_herkunft", "")),
            etikett_normal=str(roh.get("etikett_normal", "")),
            etikett_getauscht=str(roh.get("etikett_getauscht", "")),
        )
        nach_kategorie.setdefault(str(roh.get("kategorie", "")), []).append(urteil)

    ausgabe: dict[str, dict[str, float | int]] = {}
    for kategorie, urteile in nach_kategorie.items():
        guete = bewerterguete(urteile)
        ausgabe[kategorie] = {
            "paare": len(urteile),
            "auswertbar": guete["stabil"],
            "positionsinstabil": guete["positionsinstabil"],
            "unmoeglich": guete["unmoeglich"],
            "positionswechselrate": guete["positionswechselrate"],
            "a_anteil": guete["a_anteil"],
            "schueler_gewinnt": sum(
                1 for u in urteile if u.zustand == "stabil_schueler"
            ),
            "lehrer_gewinnt": sum(1 for u in urteile if u.zustand == "stabil_lehrer"),
            "gleichstand": sum(1 for u in urteile if u.zustand == "stabil_gleich"),
            "gleichwertig": paarquote(urteile),
        }
    return ausgabe


# --- Der Lauf ---------------------------------------------------------------


async def blindvergleich(
    *,
    lauf: str,
    lehrer: str,
    schueler: str,
    bewerter: str,
    manager: Any,
    ablage: Antwortablage | None = None,
    urteile: Urteilsablage | None = None,
) -> dict[str, Any]:
    """Führt den Paarvergleich eines Laufs durch - mit echtem Modell.

    Args:
        bewerter: Der Providername des urteilenden Modells. Er darf weder
            Lehrer noch Schüler sein; ``modellurteiler`` bricht sonst mit
            ``Befangen`` ab, und das ist keine Warnung, sondern das Ende.
        manager: Der ProviderManager, über den das Bewertermodell gefragt
            wird. Hereingereicht, damit dieselbe Funktion im Test mit einem
            Doppel läuft - der ECHTE Lauf reicht den echten Manager herein.
    """

    from backend.orchestrator.providers.base_provider import ChatMessage

    ablage = ablage or Antwortablage()
    urteile = urteile or Urteilsablage()

    paare = paare_bilden(ablage, lauf=lauf, lehrer=lehrer, schueler=schueler)
    if not paare:
        logger.warning(
            "Kein einziges Paar fuer Lauf '%s' - wurden beide Modelle gemessen?", lauf
        )
        return {"lauf": lauf, "paare": 0, "urteile": [], "quoten": {}}

    # Der Urteiler ist synchron, der Providermanager asynchron. Statt zu
    # verschachteln wird die Antwort des Bewerters vorher geholt und dem
    # Urteiler dann nur noch gereicht. Die Frage, die dabei gestellt wird,
    # ist genau die, die `modellurteiler` auch selbst stellen wuerde:
    # Anweisung plus maskierte Sicht, sonst nichts.
    geholt = {"roh": ""}

    def _gereichte_antwort(_frage: str) -> str:
        roh = geholt["roh"]
        if not roh.strip():
            raise RuntimeError("Der Bewerter hat nicht geantwortet.")
        return roh

    # Die Befangenheitsschranke greift HIER, vor dem ersten Paar: Steht der
    # Bewerter selbst im Vergleich, endet der Lauf mit `Befangen`.
    urteiler = modellurteiler(
        _gereichte_antwort, bewerter=bewerter, teilnehmer=(lehrer, schueler)
    )

    ergebnisse: list[Paarurteil] = []
    kategorie_je_paar: dict[str, str] = {}

    async def _durchgang(fall: Any, lage: str) -> Any:
        """Ein Durchgang: Vorlage bauen, Bewerter fragen, Urteil lesen."""

        vorlage = vorlage_bauen(
            kennung=fall.kennung,
            aufgabe=fall.aufgabe,
            erster=fall.lehrer,
            zweiter=fall.schueler,
            lage=lage,
        )
        try:
            antwort = await manager.chat(
                [ChatMessage(role="user", content=f"{URTEILSANWEISUNG}\n\n{vorlage.sicht()}")],
                preferred=bewerter,
            )
            geholt["roh"] = str(getattr(antwort, "text", "") or "")
        except Exception as fehler:  # noqa: BLE001 - ein Ausfall ist ein Messwert.
            logger.warning(
                "Der Bewerter '%s' antwortete nicht (%s): %s",
                bewerter,
                lage,
                fehler,
            )
            geholt["roh"] = ""
        return blind_bewerten(vorlage, urteiler)

    for kategorie, fall in paare:
        kategorie_je_paar[fall.kennung] = kategorie
        # Beide Reihenfolgen, nacheinander, mit demselben Bewerter.
        normal = await _durchgang(fall, "normal")
        getauscht = await _durchgang(fall, "getauscht")
        urteil = paarurteil_bilden(
            kennung=fall.kennung,
            normal=normal,
            getauscht=getauscht,
            lehrer=LEHRER,
            schueler=SCHUELER,
        )
        urteile.anhaengen(
            urteil,
            lauf=lauf,
            kategorie=kategorie,
            bewerter=bewerter,
            lehrer=lehrer,
            schueler=schueler,
        )
        ergebnisse.append(urteil)
        logger.info(
            "Paarurteil %s: %s (A/B je Durchgang: %s / %s)",
            fall.kennung,
            urteil.zustand,
            urteil.etikett_normal,
            urteil.etikett_getauscht,
        )

    quoten = quoten_je_kategorie(urteile.alle(lauf=lauf))
    guete = bewerterguete(ergebnisse)
    gesamt = paarquote(ergebnisse)
    logger.info(
        "Blindvergleich %s: %d Paare, %d stabil, %d positionsinstabil, Wechselrate %.2f, A-Anteil %.2f, Quote %.2f",
        lauf,
        guete["paare"],
        guete["stabil"],
        guete["positionsinstabil"],
        guete["positionswechselrate"],
        guete["a_anteil"],
        gesamt,
    )
    return {
        "lauf": lauf,
        "bewerter": bewerter,
        "bewertermodell": str(getattr(manager, "modell_von", lambda _n: "")(bewerter) or ""),
        "paare": len(ergebnisse),
        "gleichwertig_gesamt": gesamt,
        "guete": guete,
        "quoten": quoten,
    }


__all__ = [
    "LEHRER",
    "SCHUELER",
    "Antwort",
    "Antwortablage",
    "Urteilsablage",
    "blindvergleich",
    "paare_bilden",
    "quoten_je_kategorie",
]
