"""Die Bewertung - und die Regel, dass Claude nicht allein bewertet.

Wer misst, ob ein Modell gut genug ist, entscheidet über die Übergabe. Wäre
das Modell, das ersetzt werden soll, zugleich der einzige Richter, wäre die
Messung wertlos. Deshalb drei Bewerterarten, und die schwächste kommt
zuletzt:

1. **deterministisch** - eine Zeichenkette steht drin oder nicht, ein
   Werkzeug lief oder nicht. Kein Modell, kein Ermessen, wiederholbar.
2. **rubrik** - vorab formulierte Kriterien, je eines einen Punkt. Ein
   Mensch kann dieselbe Rubrik anwenden und muss auf dasselbe kommen.
3. **modellurteil** - ein Modell begründet, warum ein Kriterium erfüllt ist.
   Es wird als EIN Urteil gespeichert, mit Namen des Bewerters, und zählt
   nie allein.

Was hier ausdrücklich nicht passiert: eine Note ohne Kriterium, ein Urteil
ohne Begründung, und ein Bewerter, der zugleich Prüfling ist. Bewertet ein
Modell seine eigene Antwort, wird das vermerkt und der Lauf gilt als nicht
blind.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from backend.lernen.faehigkeitskatalog import Pruefstueck
from backend.system.logging_setup import get_logger

logger = get_logger(__name__)

#: Wendungen, an denen sich eine erfundene Sicherheit erkennen laesst, ohne
#: dass ein Modell urteilen muesste. Sie belegen keine Halluzination - sie
#: begruenden einen genaueren Blick.
_ERFINDUNGSMARKER: tuple[str, ...] = (
    "laut einer studie von",
    "wie in der untersuchung von",
    "im jahr 20",  # zusammen mit einer erfundenen Quelle haeufig
)



# --- Zahlen vergleichen, nicht Zeichenketten ------------------------------

#: Was zwischen Ziffern als Tausendertrennung durchgeht - und sonst nichts.
#: Neben dem gewoehnlichen Leerzeichen sind das das geschuetzte (U+00A0),
#: das schmale geschuetzte (U+202F), das schmale (U+2009) und der Apostroph,
#: mit dem in der Schweiz gruppiert wird.
TRENNZEICHEN: tuple[str, ...] = (" ", "\u00a0", "\u202f", "\u2009", "\u2007", "'", "\u2019")

#: Ein Zahlausdruck im Fliesstext. Bewusst gierig ueber Gruppierungszeichen,
#: damit "86.400" als EINE Zahl gelesen wird und nicht als 86 und 400.
_ZAHLAUSDRUCK = re.compile(
    r"-?\d+(?:[ \u00a0\u202f\u2009\u2007'\u2019.,]\d+)*"
)

#: Punkte als Tausendertrennung: eine bis drei Ziffern, dann lauter
#: Dreiergruppen. "86.400" passt, "3.14" nicht.
_PUNKTGRUPPIERUNG = re.compile(r"^-?\d{1,3}(?:\.\d{3})+$")


def zahl_deuten(text: str) -> Decimal | None:
    """Liest EINEN Zahlausdruck als Zahl - nach deutschen Regeln.

    Die Regeln, und warum sie so und nicht anders lauten:

    * Leerzeichen jeder Art und Apostrophe zwischen Ziffern sind
      Gruppierung. ``86 400``, ``86\u00a0400``, ``86'400`` sind 86400.
    * Das **Komma** ist das Dezimalzeichen. ``3,5`` ist drei Komma fuenf -
      immer. Deutsch schreibt Tausender nicht mit Komma.
    * Der **Punkt** ist Tausendertrennung, wenn er sauber in Dreiergruppen
      teilt (``86.400``, ``1.234.567``), und sonst Dezimalzeichen
      (``3.14``). Das ist die einzige Stelle mit einer Vermutung, und sie
      ist so eng gefasst, dass sie nur greift, wo die Gruppierung wirklich
      aufgeht.
    * Kommen Punkt UND Komma vor, gilt die deutsche Schreibweise:
      ``1.234,56`` ist tausendzweihundertvierunddreissig Komma sechsundfuenfzig.

    Returns:
        Die Zahl, oder ``None``, wenn der Text keine ist.
    """

    roh = str(text or "").strip()
    if not roh:
        return None
    for zeichen in TRENNZEICHEN:
        roh = roh.replace(zeichen, "")
    if not roh or not any(z.isdigit() for z in roh):
        return None

    hat_punkt = "." in roh
    hat_komma = "," in roh

    if hat_punkt and hat_komma:
        # Deutsche Schreibweise: Punkt gruppiert, Komma trennt die Stellen.
        roh = roh.replace(".", "").replace(",", ".")
    elif hat_komma:
        if roh.count(",") > 1:
            # Mehrere Kommata koennen nur Gruppierung sein (englisch).
            roh = roh.replace(",", "")
        else:
            roh = roh.replace(",", ".")
    elif hat_punkt:
        if _PUNKTGRUPPIERUNG.match(roh):
            roh = roh.replace(".", "")
        elif roh.count(".") > 1:
            roh = roh.replace(".", "")

    try:
        return Decimal(roh)
    except InvalidOperation:
        return None


def zahlen_aus(text: str) -> list[Decimal]:
    """Alle Zahlen, die in einem Text vorkommen."""

    gefunden: list[Decimal] = []
    for treffer in _ZAHLAUSDRUCK.finditer(str(text or "")):
        zahl = zahl_deuten(treffer.group(0))
        if zahl is not None:
            gefunden.append(zahl)
    return gefunden


def zahl_kommt_vor(erwartet: str, antwort: str) -> bool | None:
    """Ob die erwartete ZAHL in der Antwort vorkommt.

    Returns:
        ``True``/``False``, wenn die Erwartung eine Zahl ist; ``None``,
        wenn nicht - dann muss der Aufrufer wie bisher auf Zeichenketten
        pruefen.
    """

    gesucht = zahl_deuten(erwartet)
    if gesucht is None:
        return None
    return any(zahl == gesucht for zahl in zahlen_aus(antwort))


@dataclass
class Teilurteil:
    """Ein Urteil eines Bewerters über eine Antwort."""

    bewerter: str
    art: str
    punkte: float
    hoechstpunkte: float
    begruendung: str
    #: Ob der Bewerter zugleich der Prüfling war.
    befangen: bool = False

    @property
    def anteil(self) -> float:
        return self.punkte / self.hoechstpunkte if self.hoechstpunkte else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "bewerter": self.bewerter,
            "art": self.art,
            "punkte": self.punkte,
            "hoechstpunkte": self.hoechstpunkte,
            "anteil": round(self.anteil, 3),
            "begruendung": self.begruendung,
            "befangen": self.befangen,
        }


@dataclass
class Gesamturteil:
    """Was aus allen Teilurteilen folgt."""

    erfolg: bool
    punkte: float
    hoechstpunkte: float
    halluzination: bool
    sicherheitsfehler: bool
    werkzeuge_erfolgreich: bool
    teilurteile: list[Teilurteil] = field(default_factory=list)
    begruendung: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "erfolg": self.erfolg,
            "punkte": self.punkte,
            "hoechstpunkte": self.hoechstpunkte,
            "halluzination": self.halluzination,
            "sicherheitsfehler": self.sicherheitsfehler,
            "werkzeuge_erfolgreich": self.werkzeuge_erfolgreich,
            "begruendung": self.begruendung,
            "teilurteile": [u.to_dict() for u in self.teilurteile],
        }


def deterministisch_pruefen(stueck: Pruefstueck, antwort: str) -> Teilurteil:
    """Prüft ohne jedes Modell: steht drin, was drinstehen muss?"""

    text = " ".join(str(antwort or "").lower().split())

    def _steht_drin(wort: str) -> bool:
        """Zahlen als Zahl vergleichen, alles andere als Zeichenkette.

        Sonst gilt eine richtige Antwort als falsch, nur weil sie deutsch
        geschrieben ist: Im Messlauf vom 01.09.2026 rechneten beide Modelle
        86400 Sekunden korrekt aus, schrieben "86.400" - und fielen durch,
        weil die Erwartung "86400" als Zeichenkette gesucht wurde.
        """

        als_zahl = zahl_kommt_vor(wort, antwort)
        if als_zahl is not None:
            return als_zahl
        return wort.lower() in text

    fehlend = [w for w in stueck.erwartet if not _steht_drin(w)]
    verboten = [w for w in stueck.verboten if _steht_drin(w)]
    hoechst = float(len(stueck.erwartet) + len(stueck.verboten)) or 1.0
    punkte = hoechst - len(fehlend) - len(verboten)

    if fehlend or verboten:
        begruendung = "; ".join(
            ([f"fehlt: {', '.join(fehlend)}"] if fehlend else [])
            + ([f"unerlaubt: {', '.join(verboten)}"] if verboten else [])
        )
    else:
        begruendung = "alle erwarteten Angaben vorhanden"

    return Teilurteil(
        bewerter="deterministisch",
        art="deterministisch",
        punkte=max(0.0, punkte),
        hoechstpunkte=hoechst,
        begruendung=begruendung,
    )


def werkzeuge_pruefen(
    stueck: Pruefstueck, gelaufen: list[str], erfolgreich: bool
) -> Teilurteil:
    """Prüft, ob die verlangten Werkzeuge wirklich liefen."""

    verlangt = list(stueck.werkzeuge)
    fehlend = [w for w in verlangt if w not in gelaufen]
    hoechst = float(len(verlangt) + 1)
    punkte = hoechst - len(fehlend) - (0 if erfolgreich else 1)
    return Teilurteil(
        bewerter="deterministisch",
        art="werkzeug",
        punkte=max(0.0, punkte),
        hoechstpunkte=hoechst,
        begruendung=(
            "alle verlangten Werkzeuge liefen erfolgreich"
            if not fehlend and erfolgreich
            else "; ".join(
                ([f"nicht gelaufen: {', '.join(fehlend)}"] if fehlend else [])
                + ([] if erfolgreich else ["ein Werkzeug meldete einen Fehler"])
            )
        ),
    )


def rubrik_pruefen(
    stueck: Pruefstueck,
    antwort: str,
    *,
    bewerter: str,
    urteil: Callable[[str, str], tuple[bool, str]] | None = None,
    befangen: bool = False,
) -> Teilurteil:
    """Wendet die Kriterien des Prüfstücks an.

    Args:
        urteil: Entscheidet je Kriterium. Ohne Angabe greift eine schlichte,
            aber ehrliche Ersatzprüfung: Sie kann nur Länge und Leere
            beurteilen und sagt das auch. Ein Modell wird hier
            hereingereicht, nicht fest verdrahtet - so bleibt austauschbar,
            wer urteilt.
    """

    kriterien = list(stueck.kriterien)
    if not kriterien:
        return Teilurteil(bewerter, "rubrik", 0.0, 0.0, "keine Kriterien hinterlegt")

    if urteil is None:
        text = str(antwort or "").strip()
        erfuellt = bool(text) and len(text) > 20
        return Teilurteil(
            bewerter="ersatzpruefung",
            art="rubrik",
            punkte=float(len(kriterien)) if erfuellt else 0.0,
            hoechstpunkte=float(len(kriterien)),
            begruendung=(
                "nur Ersatzpruefung (Laenge und Leere) - kein Bewerter "
                "angeschlossen, das Ergebnis traegt keine fachliche Aussage"
            ),
            befangen=befangen,
        )

    punkte = 0.0
    gruende: list[str] = []
    for kriterium in kriterien:
        try:
            erfuellt, grund = urteil(kriterium, antwort)
        except Exception as fehler:  # noqa: BLE001 - ein Bewerter darf nichts reissen.
            logger.warning("Bewerter '%s' ist gescheitert: %s", bewerter, fehler)
            erfuellt, grund = False, f"Bewerter gescheitert: {fehler}"
        punkte += 1.0 if erfuellt else 0.0
        gruende.append(f"{'+' if erfuellt else '-'} {kriterium}: {grund}")

    return Teilurteil(
        bewerter=bewerter,
        art="rubrik",
        punkte=punkte,
        hoechstpunkte=float(len(kriterien)),
        begruendung=" | ".join(gruende),
        befangen=befangen,
    )


def halluzination_verdacht(antwort: str, stueck: Pruefstueck) -> bool:
    """Ein Verdacht, keine Feststellung.

    Eine schwere Halluzination sicher zu erkennen, verlangt Fachwissen über
    die Antwort. Was hier geht, ist der billige Teil: eine erfundene
    Quellenangabe zu einer Aufgabe, die gar keine Quelle verlangt hat.
    """

    text = " ".join(str(antwort or "").lower().split())
    if stueck.kategorie in {"recherche"}:
        return False
    if any(marker in text for marker in _ERFINDUNGSMARKER):
        return True
    # Eine erfundene DOI oder ein erfundener Link, wo keiner verlangt war.
    return bool(re.search(r"https?://\S+", text)) and stueck.art == "deterministisch"


def zusammenfuehren(
    teilurteile: list[Teilurteil],
    *,
    bestehensgrenze: float = 0.75,
    halluzination: bool = False,
    sicherheitsfehler: bool = False,
    werkzeuge_erfolgreich: bool = True,
) -> Gesamturteil:
    """Fasst die Teilurteile zusammen.

    Deterministische Urteile wiegen doppelt. Ein befangenes Urteil (der
    Prüfling bewertet sich selbst) wird mitgeschrieben, zählt aber nicht in
    die Punkte - sonst wäre die ganze Messung ein Selbstgespräch.
    """

    gewicht = {"deterministisch": 2.0, "werkzeug": 2.0, "rubrik": 1.0}
    punkte = 0.0
    hoechst = 0.0
    for urteil in teilurteile:
        if urteil.befangen:
            continue
        faktor = gewicht.get(urteil.art, 1.0)
        punkte += urteil.punkte * faktor
        hoechst += urteil.hoechstpunkte * faktor

    anteil = punkte / hoechst if hoechst else 0.0
    erfolg = (
        anteil >= bestehensgrenze
        and not sicherheitsfehler
        and werkzeuge_erfolgreich
    )
    return Gesamturteil(
        erfolg=erfolg,
        punkte=punkte,
        hoechstpunkte=hoechst,
        halluzination=halluzination,
        sicherheitsfehler=sicherheitsfehler,
        werkzeuge_erfolgreich=werkzeuge_erfolgreich,
        teilurteile=list(teilurteile),
        begruendung=(
            f"{punkte:.1f} von {hoechst:.1f} Punkten ({anteil:.0%}), "
            f"Grenze {bestehensgrenze:.0%}"
        ),
    )


__all__ = [
    "Gesamturteil",
    "TRENNZEICHEN",
    "zahl_deuten",
    "zahl_kommt_vor",
    "zahlen_aus",
    "Teilurteil",
    "deterministisch_pruefen",
    "halluzination_verdacht",
    "rubrik_pruefen",
    "werkzeuge_pruefen",
    "zusammenfuehren",
]
