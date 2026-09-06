"""Die Blindbewertung: der Bewerter darf nicht wissen, wen er bewertet.

Ohne diese Vorkehrung ist die Bewertung wertlos. Ein Urteil über zwei
Antworten, von denen die eine erkennbar vom eigenen Haus stammt, misst
Loyalität, nicht Qualität. Und Sprachmodelle sind darin auffällig: Sie
bevorzugen die erste Antwort, sie bevorzugen die längere, und sie bevorzugen
das, was nach ihnen selbst klingt.

Drei Vorkehrungen, jede einzeln überprüfbar:

**Maskierung.** Aus beiden Texten verschwindet, was auf die Herkunft
deuten könnte: Modell- und Anbieternamen, Selbstbezeichnungen,
Versionsangaben, typische Signaturen. Was übrig bleibt, ist die Antwort.

**Losverfahren.** Welcher Kandidat Etikett A bekommt, entscheidet ein Wurf,
der an der Vergleichskennung hängt - nicht an der Reihenfolge des
Aufrufers. Dieselbe Kennung ergibt dieselbe Zuteilung (nachvollziehbar),
verschiedene Kennungen streuen (nicht ausrechenbar aus der Aufrufreihenfolge).

**Auflösung erst danach.** Der Bewerter gibt ein Etikett zurück, nicht einen
Namen. Erst ``aufloesen`` verbindet Etikett und Herkunft - und dann ist das
Urteil schon gefällt.

Was der Bewerter zu sehen bekommt, liefert ``sicht()``. Genau dieser Text
wird im Test auf Lecks geprüft; alles andere wäre eine Prüfung der Absicht
statt der Umsetzung.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from backend.system.logging_setup import get_logger

logger = get_logger(__name__)

#: Wörter, die die Herkunft verraten. Bewusst grosszügig: Ein zu viel
#: maskiertes Wort kostet ein bisschen Lesbarkeit, ein zu wenig maskiertes
#: kostet die ganze Messung.
_HERKUNFTSWOERTER: tuple[str, ...] = (
    "claude", "anthropic", "sonnet", "opus", "haiku",
    "ollama", "llama", "lfm", "mistral", "qwen", "gemma", "phi-3", "phi3",
    "openai", "gpt", "chatgpt", "luna", "terra", "grok", "openrouter",
    "hermes", "deepseek", "kokoro", "gemini", "copilot",
    "ai-orb", "ai orb", "aiorb",
)

#: Wendungen, mit denen sich ein Modell selbst benennt.
_SELBSTBEZEICHNUNGEN: tuple[str, ...] = (
    r"ich bin (?:ein|eine|das|der)?\s*(?:gro(?:ss|ß)es?\s+)?sprachmodell",
    r"als (?:ki|ai|sprachmodell|assistent(?:in)?)\b",
    r"ich wurde von [^.]{0,40}(?:trainiert|entwickelt|gebaut)",
    r"mein wissensstand (?:reicht|endet)[^.]{0,40}",
    r"\bmodellversion\b[^.]{0,20}",
)

#: Womit ersetzt wird. Ein einheitliches Zeichen, damit die Länge nicht
#: selbst zum Hinweis wird.
MASKE = "[…]"

#: Das vierte moegliche Ergebnis neben A, B und Gleichstand: Es kam kein
#: lesbares Urteil zustande. Ausdruecklich KEIN Gleichstand.
UNMOEGLICH = "unmoeglich"

#: Woran ein ausgesprochener Gleichstand erkannt wird.
_GLEICHWERTIG: tuple[str, ...] = ("GLEICH", "UNENTSCHIEDEN", "EBENBUERTIG", "TIE")


@dataclass
class Kandidat:
    """Eine Antwort mit ihrer Herkunft - die Herkunft bleibt hier."""

    herkunft: str
    text: str
    #: Wie viele Werkzeuge liefen. Wird dem Bewerter NICHT gezeigt, weil
    #: sich daran das lokale Modell erkennen liesse.
    werkzeuge: tuple[str, ...] = field(default_factory=tuple)


def lecks_finden(text: str) -> list[str]:
    """Findet alles, was die Herkunft verraten würde.

    Diese Funktion ist zugleich Werkzeug und Prüfstein: Sie maskiert, und
    der Test benutzt sie, um zu belegen, dass nach dem Maskieren nichts
    mehr übrig ist.
    """

    gefunden: list[str] = []
    klein = str(text or "").lower()
    for wort in _HERKUNFTSWOERTER:
        if re.search(rf"\b{re.escape(wort)}\b", klein):
            gefunden.append(wort)
    for muster in _SELBSTBEZEICHNUNGEN:
        treffer = re.search(muster, klein)
        if treffer:
            gefunden.append(treffer.group(0)[:40])
    return gefunden


def maskieren(text: str) -> str:
    """Entfernt aus einer Antwort, was auf ihre Herkunft deutet."""

    sauber = str(text or "")
    for muster in _SELBSTBEZEICHNUNGEN:
        sauber = re.sub(muster, MASKE, sauber, flags=re.IGNORECASE)
    for wort in _HERKUNFTSWOERTER:
        sauber = re.sub(
            rf"\b{re.escape(wort)}\b", MASKE, sauber, flags=re.IGNORECASE
        )
    return sauber


@dataclass
class Blindvorlage:
    """Zwei maskierte Antworten unter den Etiketten A und B."""

    kennung: str
    aufgabe: str
    a: Kandidat
    b: Kandidat
    #: Ob A der erste übergebene Kandidat war. Nur zur Auflösung.
    a_war_erster: bool = True

    def sicht(self) -> str:
        """Genau das, was der Bewerter zu sehen bekommt - und nichts sonst."""

        return (
            f"Aufgabe:\n{self.aufgabe}\n\n"
            f"Antwort A:\n{maskieren(self.a.text)}\n\n"
            f"Antwort B:\n{maskieren(self.b.text)}"
        )

    def aufloesen(self, etikett: str) -> str:
        """Übersetzt ein Etikett in die Herkunft - erst nach dem Urteil."""

        marke = str(etikett or "").strip().upper()
        if marke == "A":
            return self.a.herkunft
        if marke == "B":
            return self.b.herkunft
        return ""


def vorlage_bauen(
    *,
    kennung: str,
    aufgabe: str,
    erster: Kandidat,
    zweiter: Kandidat,
    lage: str = "los",
) -> Blindvorlage:
    """Baut eine Vorlage und lost die Etiketten aus.

    Der Wurf hängt an der Vergleichskennung, nicht an der Reihenfolge des
    Aufrufers. Damit ist dieselbe Vergleichung reproduzierbar und die
    Reihenfolge trotzdem nicht vorhersagbar, wenn man nur die Aufrufe kennt.
    """

    # ``lage`` steuert die Reihenfolge:
    #   "los"      - ausgelost aus der Kennung (Vorgabe, reproduzierbar)
    #   "normal"   - der erste Kandidat steht auf A
    #   "getauscht"- der zweite Kandidat steht auf A
    #
    # Die beiden festen Lagen sind fuer die Positionskontrolle da: Dasselbe
    # Paar wird einmal so und einmal so vorgelegt. Wer beide Male dieselbe
    # ANTWORT vorzieht, hat die Antwort bewertet; wer beide Male dasselbe
    # ETIKETT waehlt, die Position.
    if lage == "normal":
        tauschen = False
    elif lage == "getauscht":
        tauschen = True
    else:
        wurf = int(hashlib.sha256(kennung.encode("utf-8")).hexdigest()[:8], 16)
        tauschen = bool(wurf % 2)
    a, b = (zweiter, erster) if tauschen else (erster, zweiter)
    return Blindvorlage(
        kennung=kennung, aufgabe=aufgabe, a=a, b=b, a_war_erster=not tauschen
    )


@dataclass
class Blindurteil:
    """Was aus einer Blindbewertung folgt."""

    kennung: str
    besser: str
    begruendung: str
    #: "lehrer", "schueler" oder "" bei Gleichstand - erst nach der Auflösung.
    gewinner_herkunft: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "kennung": self.kennung,
            "besser": self.besser,
            "begruendung": self.begruendung,
            "gewinner_herkunft": self.gewinner_herkunft,
        }


def blind_bewerten(
    vorlage: Blindvorlage,
    urteiler: Callable[[str], tuple[str, str]],
) -> Blindurteil:
    """Holt ein Urteil ein, ohne die Herkunft preiszugeben.

    Args:
        urteiler: Bekommt ``vorlage.sicht()`` und gibt ``("A"|"B"|"gleich",
            Begründung)`` zurück. Er bekommt sonst nichts - kein
            Modellname, keine Werkzeugliste, keine Reihenfolgeinformation.
    """

    try:
        etikett, begruendung = urteiler(vorlage.sicht())
    except Exception as fehler:  # noqa: BLE001 - ein Bewerter darf nichts reissen.
        logger.warning("Der Blindbewerter ist gescheitert: %s", fehler)
        return Blindurteil(vorlage.kennung, UNMOEGLICH, f"Bewerter gescheitert: {fehler}")

    marke = str(etikett or "").strip().upper().rstrip(".:!")
    if marke in {"A", "B"}:
        return Blindurteil(
            kennung=vorlage.kennung,
            besser=marke,
            begruendung=str(begruendung),
            gewinner_herkunft=vorlage.aufloesen(marke),
        )
    if any(wort in marke for wort in _GLEICHWERTIG):
        return Blindurteil(vorlage.kennung, "gleich", str(begruendung))

    # Weder A noch B noch ein Wort fuer Gleichstand: Der Bewerter hat
    # geantwortet, aber nicht geurteilt. Das als "gleichwertig" zu zaehlen
    # waere die bequeme Luege - ein unlesbares Urteil ist KEIN Urteil, und
    # ein Stapel unlesbarer Urteile darf keine Uebergabe rechtfertigen.
    return Blindurteil(
        vorlage.kennung,
        UNMOEGLICH,
        f"Unlesbares Urteil: {str(begruendung)[:160]}",
    )


def auswertbare(urteile: list[Blindurteil]) -> list[Blindurteil]:
    """Die Urteile, die wirklich eines sind."""

    return [u for u in urteile if u.besser != UNMOEGLICH]


def gleichwertigkeitsquote(urteile: list[Blindurteil], *, schueler: str) -> float:
    """Anteil der Vergleiche, in denen der Schüler nicht unterlegen war.

    Gleichstand zählt als gleichwertig - das ist der Sinn der Schwelle
    ``lernen.mindest_blindurteil``: Es geht nicht darum, den Lehrer zu
    schlagen, sondern nicht schlechter zu sein.

    Ein Vergleich, der technisch nicht zustande kam, steht im **Nenner**,
    aber nie im Zähler. Das ist Absicht: Sonst könnte ein kaputter
    Bewerter, der zwanzigmal nichts sagt und einmal "gleich", eine Quote
    von 100 % erzeugen. So zieht jeder misslungene Vergleich die Quote
    nach unten - wer messen will, muss messen können.
    """

    if not urteile:
        return 0.0
    nicht_unterlegen = sum(
        1
        for urteil in urteile
        if urteil.besser == "gleich" or urteil.gewinner_herkunft == schueler
    )
    return nicht_unterlegen / len(urteile)


# --- Positionskontrolle ----------------------------------------------------

#: Die fuenf Zustaende, die ein positionskontrolliertes Paarurteil haben
#: kann. Die ersten drei sind Urteile, die letzten beiden nicht.
PAARZUSTAENDE: tuple[str, ...] = (
    "stabil_lehrer",
    "stabil_schueler",
    "stabil_gleich",
    "positionsinstabil",
    "unmoeglich",
)


@dataclass
class Paarurteil:
    """Was aus BEIDEN Durchgängen eines Paares folgt.

    Ein einzelnes A/B-Urteil sagt wenig: Viele Modelle bevorzugen die
    erste Antwort, gleich was drinsteht. Am 01.09.2026 wählte der damalige
    Bewerter 36-mal A und 16-mal B - dieselbe Verteilung hätte auch ein
    Würfel mit Schlagseite erzeugt. Deshalb wird jedes Paar zweimal
    vorgelegt, in beiden Reihenfolgen, und nur ein in beiden Durchgängen
    übereinstimmendes Urteil zählt.
    """

    kennung: str
    zustand: str
    #: "lehrer", "schueler" oder "" - erst nach beiden Durchgängen.
    gewinner_herkunft: str
    #: Was der Bewerter im ersten und im zweiten Durchgang wählte.
    etikett_normal: str
    etikett_getauscht: str
    begruendung_normal: str = ""
    begruendung_getauscht: str = ""

    @property
    def stabil(self) -> bool:
        return self.zustand.startswith("stabil")

    def to_dict(self) -> dict[str, Any]:
        return {
            "kennung": self.kennung,
            "zustand": self.zustand,
            "gewinner_herkunft": self.gewinner_herkunft,
            "etikett_normal": self.etikett_normal,
            "etikett_getauscht": self.etikett_getauscht,
            "begruendung_normal": self.begruendung_normal[:400],
            "begruendung_getauscht": self.begruendung_getauscht[:400],
        }


def paarurteil_bilden(
    *, kennung: str, normal: Blindurteil, getauscht: Blindurteil, lehrer: str, schueler: str
) -> Paarurteil:
    """Führt zwei Durchgänge zu einem Urteil zusammen.

    Die Regeln, und warum sie so streng sind:

    * Kam einer der beiden Durchgänge nicht zustande, gibt es kein Urteil
      (``unmoeglich``). Aus einem halben Vergleich einen ganzen zu machen,
      wäre genau die Art von Grosszügigkeit, die eine Übergabe
      rechtfertigen würde, die niemand geprüft hat.
    * Sagen beide Durchgänge "gleich", ist es ein Gleichstand.
    * Zeigen beide auf dieselbe HERKUNFT, ist das Urteil positionsstabil.
    * Zeigen sie auf verschiedene Herkünfte - typischerweise, weil beide
      Male dasselbe Etikett gewählt wurde -, ist es ``positionsinstabil``.
      Ein solches Urteil wird NICHT zur Stimme; es wird gezählt.
    """

    if normal.besser == UNMOEGLICH or getauscht.besser == UNMOEGLICH:
        return Paarurteil(
            kennung=kennung,
            zustand=UNMOEGLICH,
            gewinner_herkunft="",
            etikett_normal=normal.besser,
            etikett_getauscht=getauscht.besser,
            begruendung_normal=normal.begruendung,
            begruendung_getauscht=getauscht.begruendung,
        )

    if normal.besser == "gleich" and getauscht.besser == "gleich":
        zustand, gewinner = "stabil_gleich", ""
    elif normal.gewinner_herkunft and normal.gewinner_herkunft == getauscht.gewinner_herkunft:
        gewinner = normal.gewinner_herkunft
        zustand = "stabil_schueler" if gewinner == schueler else "stabil_lehrer"
    else:
        zustand, gewinner = "positionsinstabil", ""

    return Paarurteil(
        kennung=kennung,
        zustand=zustand,
        gewinner_herkunft=gewinner,
        etikett_normal=normal.besser,
        etikett_getauscht=getauscht.besser,
        begruendung_normal=normal.begruendung,
        begruendung_getauscht=getauscht.begruendung,
    )


def paarquote(urteile: list[Paarurteil], *, schueler_zustand: str = "stabil_schueler") -> float:
    """Anteil der Paare, in denen der Schüler stabil nicht unterlegen war.

    Nenner sind ALLE Paare - auch die instabilen und die gescheiterten.
    Ein Bewerter, der bei der Hälfte der Paare die Meinung wechselt, kann
    damit keine hohe Quote erzeugen, und das ist der Sinn der Sache.
    """

    if not urteile:
        return 0.0
    zaehler = sum(
        1
        for u in urteile
        if u.zustand in {"stabil_gleich", schueler_zustand}
    )
    return zaehler / len(urteile)


def bewerterguete(urteile: list[Paarurteil]) -> dict[str, Any]:
    """Die Diagnosezahlen zum Bewerter selbst.

    Nicht die Prüflinge werden hier gemessen, sondern der Richter. Eine
    Gleichwertigkeitsquote von einem Bewerter, der die Position bewertet
    statt die Antwort, ist kein Messwert, sondern ein Zufallsergebnis.
    """

    gesamt = len(urteile)
    stabil = [u for u in urteile if u.stabil]
    instabil = [u for u in urteile if u.zustand == "positionsinstabil"]
    unmoeglich = [u for u in urteile if u.zustand == UNMOEGLICH]
    etiketten = [u.etikett_normal for u in urteile] + [
        u.etikett_getauscht for u in urteile
    ]
    entschieden = [e for e in etiketten if e in {"A", "B"}]
    return {
        "paare": gesamt,
        "durchgaenge": len(etiketten),
        "a_siege": etiketten.count("A"),
        "b_siege": etiketten.count("B"),
        "gleich_urteile": etiketten.count("gleich"),
        "technisch_gescheitert": etiketten.count(UNMOEGLICH),
        "stabil": len(stabil),
        "positionsinstabil": len(instabil),
        "unmoeglich": len(unmoeglich),
        "positionswechselrate": (len(instabil) / gesamt) if gesamt else 0.0,
        "verwertbar_anteil": (len(stabil) / gesamt) if gesamt else 0.0,
        # Wie schief die Etikettenwahl liegt: 0.5 waere ausgeglichen, 1.0
        # hiesse "immer A". Das ist der Wert, an dem der alte Bewerter
        # auffiel (36 zu 16 = 0.69).
        "a_anteil": (etiketten.count("A") / len(entschieden)) if entschieden else 0.0,
    }



# --- Der Modellbewerter und die Befangenheitsschranke ---------------------

#: Was der Bewerter als Anweisung bekommt. Sie nennt keine Herkunft, keine
#: Reihenfolge und keine Werkzeuge - und verlangt ausdruecklich ein Etikett
#: statt eines Namens.
URTEILSANWEISUNG = (
    "Du bewertest zwei Antworten auf dieselbe Aufgabe. Du weisst nicht, "
    "woher sie stammen, und sollst nicht darueber spekulieren.\n"
    "Bewerte ausschliesslich: Richtigkeit, Vollstaendigkeit, Verstaendlichkeit "
    "und Angemessenheit der Laenge.\n"
    "Laenge allein ist kein Vorteil. Die Reihenfolge sagt nichts aus.\n"
    "Antworte in genau zwei Zeilen:\n"
    "URTEIL: A oder B oder gleich\n"
    "GRUND: ein Satz."
)


class Befangen(RuntimeError):
    """Der vorgesehene Bewerter ist selbst Teilnehmer des Vergleichs."""


def _urteil_lesen(text: str) -> tuple[str, str]:
    """Liest ``URTEIL:`` und ``GRUND:`` aus der Antwort des Bewerters."""

    etikett = ""
    grund = ""
    for zeile in str(text or "").splitlines():
        schlank = zeile.strip()
        if schlank.upper().startswith("URTEIL:"):
            etikett = schlank.split(":", 1)[1].strip()
        elif schlank.upper().startswith("GRUND:"):
            grund = schlank.split(":", 1)[1].strip()
    return etikett, grund or str(text or "").strip()[:200]


def modellurteiler(
    frage_stellen: Callable[[str], str],
    *,
    bewerter: str,
    teilnehmer: tuple[str, ...],
) -> Callable[[str], tuple[str, str]]:
    """Baut einen Bewerter aus einem Modell - wenn es nicht selbst antritt.

    Ein Modell, das seine eigene Antwort bewertet, misst nichts. Deshalb
    ist das hier keine Warnung, sondern ein Abbruch: Wer im Vergleich
    steht, darf ihn nicht entscheiden.

    Args:
        frage_stellen: Schickt einen Text an das Bewertermodell und gibt
            dessen Antwort zurueck. Bewusst hereingereicht, damit
            austauschbar bleibt, wer urteilt.
        bewerter: Name des Bewertermodells.
        teilnehmer: Die Modelle, deren Antworten verglichen werden.

    Raises:
        Befangen: Wenn der Bewerter selbst antritt.
    """

    if bewerter in set(teilnehmer):
        raise Befangen(
            f"'{bewerter}' steht selbst im Vergleich und darf nicht urteilen"
        )

    def urteilen(sicht: str) -> tuple[str, str]:
        antwort = frage_stellen(f"{URTEILSANWEISUNG}\n\n{sicht}")
        return _urteil_lesen(antwort)

    return urteilen


@dataclass
class Vergleichsfall:
    """Ein Paar Antworten zu einer Aufgabe, noch unbewertet."""

    kennung: str
    aufgabe: str
    lehrer: Kandidat
    schueler: Kandidat


def vergleichsreihe(
    faelle: list[Vergleichsfall],
    urteiler: Callable[[str], tuple[str, str]],
    *,
    schueler: str = "schueler",
) -> tuple[list[Blindurteil], float]:
    """Bewertet eine ganze Reihe blind und gibt die Gleichwertigkeitsquote.

    Genau diese Quote traegt ``Pruefergebnis.blindurteil_gleichwertig`` und
    damit eine der sechs Uebergabebedingungen. Sie entsteht hier aus
    einzelnen Urteilen - nicht aus einer Schaetzung.
    """

    urteile: list[Blindurteil] = []
    for fall in faelle:
        vorlage = vorlage_bauen(
            kennung=fall.kennung,
            aufgabe=fall.aufgabe,
            erster=fall.lehrer,
            zweiter=fall.schueler,
        )
        urteile.append(blind_bewerten(vorlage, urteiler))
    return urteile, gleichwertigkeitsquote(urteile, schueler=schueler)


__all__ = [
    "MASKE",
    "PAARZUSTAENDE",
    "Paarurteil",
    "bewerterguete",
    "paarquote",
    "paarurteil_bilden",
    "UNMOEGLICH",
    "auswertbare",
    "URTEILSANWEISUNG",
    "Befangen",
    "Vergleichsfall",
    "modellurteiler",
    "vergleichsreihe",
    "Blindurteil",
    "Blindvorlage",
    "Kandidat",
    "blind_bewerten",
    "gleichwertigkeitsquote",
    "lecks_finden",
    "maskieren",
    "vorlage_bauen",
]
