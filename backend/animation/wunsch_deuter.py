"""Deutet einen gesprochenen Wunsch in eine Änderung der Animation.

Der Benutzer will die Animation dem Orb erklären können, statt Werte von
Hand zu ändern: „mach die Punkte grösser", „die Fäden länger", „ruhiger",
„andere Farben – grün und gelb". Dieses Modul übersetzt solche Sätze in
konkrete Änderungen an den Werten unter ``orb.animation`` in der
config.yaml.

## Warum eine Deutung und kein Sprachmodell

Für „grösser/kleiner/schneller/heller" ein Sprachmodell zu fragen wäre mit
Kanonen auf Spatzen geschossen: langsam, teuer, und gelegentlich denkt es
sich etwas aus. Diese Wünsche sind eine kleine, geschlossene Menge – ein
Wort, eine Richtung, ein Wert. Eine Tabelle trifft sie schneller und
verlässlicher.

Für alles, was sich NICHT als Wertänderung fassen lässt („lass sie wie ein
Herzschlag pulsieren"), ist dieses Modul bewusst nicht zuständig. Es gibt
dann ehrlich zurück, dass es den Wunsch nicht als Werteänderung erkennt –
und der Orb greift zum mächtigeren Weg, dem Umschreiben des Codes.

## Warum relative Schritte und keine absoluten Werte

„Grösser" heisst nicht „Grösse 0.8", sondern „grösser als jetzt". Deshalb
liefert die Deutung FAKTOREN und SUMMANDEN auf den aktuellen Wert, keine
Zielwerte. So kann der Benutzer „noch grösser" sagen und es wird noch
einmal grösser – wie bei einem Menschen, dem man über die Schulter schaut.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Aenderung:
    """Eine einzelne Änderung an einem Animationswert.

    Entweder ``faktor`` (multiplikativ, für Grössen und Tempo) oder
    ``summand`` (additiv, für Farbtöne) – nie beides. ``grenzen`` hält den
    Wert in einem sinnvollen Bereich, damit „viel kleiner", dreimal
    gesagt, den Punkt nicht auf null schrumpft.
    """

    schluessel: str
    faktor: float | None = None
    summand: float | None = None
    zielwert: float | None = None
    grenzen: tuple[float, float] = (0.0, 999.0)

    def anwenden(self, aktuell: float) -> float:
        if self.zielwert is not None:
            neu = self.zielwert
        elif self.faktor is not None:
            neu = aktuell * self.faktor
        elif self.summand is not None:
            neu = aktuell + self.summand
        else:
            neu = aktuell
        lo, hi = self.grenzen
        return max(lo, min(hi, neu))


@dataclass
class Deutung:
    """Das Ergebnis einer Deutung."""

    aenderungen: list[Aenderung] = field(default_factory=list)
    #: Was dem Benutzer als Bestätigung gesagt wird.
    erklaerung: str = ""
    #: Wahr, wenn KEINE Werteänderung erkannt wurde – dann ist der Wunsch
    #: ein Fall für das Umschreiben des Codes, nicht für dieses Modul.
    unklar: bool = False

    @property
    def erkannt(self) -> bool:
        return bool(self.aenderungen)


#: Farbnamen zu Farbton (0..1 im Farbkreis).
#:
#: Rot steht als 1.0 und zusätzlich als 0.0 – im Farbkreis ist beides Rot.
#: Welches genommen wird, entscheidet die Nähe zum jeweils anderen Punkt,
#: damit der Übergang beim Verschmelzen den kurzen Weg nimmt.
FARBEN: dict[str, float] = {
    "rot": 1.0,
    "orange": 0.075,
    "gelb": 0.15,
    "grün": 0.33,
    "gruen": 0.33,
    "grun": 0.33,
    "türkis": 0.48,
    "tuerkis": 0.48,
    "cyan": 0.5,
    "blau": 0.62,
    "hellblau": 0.55,
    "violett": 0.78,
    "lila": 0.78,
    "magenta": 0.9,
    "pink": 0.92,
    "weiss": -1.0,  # Sonderfall (siehe _farbwunsch)
    "weiß": -1.0,
}

#: Grenzen je Wert – gerechnet, nicht geraten.
#:
#: Der Abstand darf nicht null werden (Punkte fielen zusammen) und nicht
#: über den Fensterrand hinaus. Das Tempo nicht null (Stillstand) und nicht
#: so schnell, dass es flimmert. Die Fäden brauchen mindestens ein paar
#: Glieder, sonst gibt es keine Spur, und höchstens so viele, dass es die
#: Bildrate nicht drückt.
_GRENZEN: dict[str, tuple[float, float]] = {
    "abstand": (0.2, 1.4),
    "punkt_groesse": (0.35, 3.0),
    "verschmelzen": (0.4, 3.5),
    "schweif_laenge": (6, 120),
    "tempo": (0.2, 4.0),
    "helligkeit": (0.4, 2.5),
    "scale": (0.15, 1.6),
}

#: Die Wörter, an denen ein Wunsch hängt. Reihenfolge egal, es zählt das
#: Vorkommen. Mehrwortige zuerst geprüft, damit „viel grösser" nicht schon
#: bei „grösser" hängenbleibt.
_MEHR = ("mehr", "grösser", "groesser", "größer", "stärker", "staerker", "höher", "hoeher")
_WENIG = ("weniger", "kleiner", "schwächer", "schwaecher", "niedriger", "geringer")


def _hat(text: str, woerter) -> bool:
    return any(w in text for w in woerter)


def _stufe(text: str) -> float:
    """Wie stark die Änderung ausfällt – 'viel/deutlich' verstärkt sie."""

    if _hat(text, ("viel", "deutlich", "sehr", "wesentlich", "doppelt")):
        return 1.6
    if _hat(text, ("etwas", "ein bisschen", "bisschen", "leicht", "einen tick", "minimal")):
        return 1.12
    return 1.3


def _richtung(text: str) -> int:
    """+1 = mehr, -1 = weniger, 0 = keine Richtung im Satz."""

    if _hat(text, _MEHR):
        return 1
    if _hat(text, _WENIG):
        return -1
    return 0


def _groessen_wunsch(text: str) -> list[Aenderung]:
    """Deutet Wünsche zu Grösse, Abstand, Tempo, Fäden, Verschmelzen, Licht."""

    stufe = _stufe(text)
    r = _richtung(text)
    aend: list[Aenderung] = []

    def faktor(schluessel: str) -> Aenderung:
        f = stufe if r >= 0 else 1.0 / stufe
        return Aenderung(schluessel, faktor=f, grenzen=_GRENZEN[schluessel])

    # Fäden / Schweif – additiv in Gliedern, das ist greifbarer als ein
    # Faktor ("zehn länger" wäre absurd, "länger" heisst: spürbar mehr).
    if _hat(text, ("faden", "fäden", "faeden", "spur", "streifen", "schweif", "schwanz")):
        schritt = 14 if stufe < 1.4 else 26
        aend.append(
            Aenderung("schweif_laenge", summand=schritt * (1 if r >= 0 else -1),
                      grenzen=_GRENZEN["schweif_laenge"])
        )
        return aend

    # Tempo
    if _hat(text, ("schnell", "langsam", "tempo", "ruhig", "hektisch", "träge", "traege",
                   "flott", "gemächlich", "gemaechlich")):
        # "ruhig/langsam/träge" sind für sich schon "weniger".
        langsamer = _hat(text, ("langsam", "ruhig", "träge", "traege", "gemächlich", "gemaechlich"))
        schneller = _hat(text, ("schnell", "hektisch", "flott"))
        f = stufe if (schneller or r > 0) else (1.0 / stufe if (langsamer or r < 0) else 1.0)
        aend.append(Aenderung("tempo", faktor=f, grenzen=_GRENZEN["tempo"]))
        return aend

    # Abstand
    if _hat(text, ("abstand", "auseinander", "enger", "weiter", "näher", "naeher", "getrennt")):
        weiter = _hat(text, ("auseinander", "weiter", "getrennt")) or r > 0
        f = stufe if weiter else 1.0 / stufe
        aend.append(Aenderung("abstand", faktor=f, grenzen=_GRENZEN["abstand"]))
        return aend

    # Verschmelzen
    if _hat(text, ("verschmelz", "verschmilz", "zusammen", "vereini", "nebel")):
        f = stufe if r >= 0 else 1.0 / stufe
        aend.append(Aenderung("verschmelzen", faktor=f, grenzen=_GRENZEN["verschmelzen"]))
        return aend

    # Helligkeit
    if _hat(text, ("hell", "dunkl", "dunkel", "leucht", "strahl", "blass",
                   "kräftig", "kraeftig", "matt", "gedämpft", "gedaempft")):
        dunkler = _hat(text, ("dunkl", "dunkel", "blass", "matt", "gedämpft", "gedaempft"))
        f = (1.0 / stufe) if dunkler else stufe
        aend.append(Aenderung("helligkeit", faktor=f, grenzen=_GRENZEN["helligkeit"]))
        return aend

    # Punktgrösse – "dicker/dünner", oder "grösser/kleiner" OHNE ein
    # anderes Ziel im Satz.
    if _hat(text, ("dicker", "dünner", "duenner", "fetter", "feiner")):
        aend.append(faktor("punkt_groesse"))
        return aend

    # "grösser/kleiner" ganz allgemein → die GESAMTGRÖSSE (orb.scale),
    # das ist, was der Benutzer meint, wenn er nichts weiter sagt.
    if r != 0 and _hat(text, ("punkt", "kugel", "ball", "orb", "animation", "gross",
                              "groß", "klein")):
        aend.append(
            Aenderung("scale", faktor=stufe if r > 0 else 1.0 / stufe,
                      grenzen=_GRENZEN["scale"])
        )
        return aend

    return aend


def _farbwunsch(text: str, aktuell_a: float, aktuell_b: float) -> list[Aenderung]:
    """Deutet Farbwünsche wie „mach sie grün und gelb"."""

    if not _hat(text, ("farb", "färb", "faerb")) and not any(n in text for n in FARBEN):
        return []

    gefunden: list[float] = []
    for name, ton in FARBEN.items():
        if name in text and ton not in gefunden:
            gefunden.append(ton)

    if not gefunden:
        return []

    aend: list[Aenderung] = []
    # Zwei Farben genannt → beide Punkte. Eine Farbe → der Punkt, der ihr
    # ferner steht, wechselt zu ihr (der andere bleibt, damit ein Kontrast
    # bleibt).
    if len(gefunden) >= 2:
        aend.append(Aenderung("farbe_a", zielwert=_gueltig(gefunden[0]), grenzen=(0.0, 1.0)))
        aend.append(Aenderung("farbe_b", zielwert=_gueltig(gefunden[1]), grenzen=(0.0, 1.0)))
    else:
        ton = _gueltig(gefunden[0])
        # An den ferneren Punkt vergeben.
        if abs(ton - aktuell_a) >= abs(ton - aktuell_b):
            aend.append(Aenderung("farbe_a", zielwert=ton, grenzen=(0.0, 1.0)))
        else:
            aend.append(Aenderung("farbe_b", zielwert=ton, grenzen=(0.0, 1.0)))
    return aend


def _gueltig(ton: float) -> float:
    """Der Sonderfall Weiss (−1) wird zu einem sehr blassen Ton."""

    return 0.0 if ton < 0 else ton


def deute(text: str, *, aktuell: dict[str, float] | None = None) -> Deutung:
    """Deutet einen gesprochenen Wunsch.

    Args:
        text: Was der Benutzer gesagt hat.
        aktuell: Die aktuellen Werte (für Farbwünsche, die den ferneren
            Punkt wählen). Fehlt es, werden die Vorgaben angenommen.

    Returns:
        Eine :class:`Deutung`. ``erkannt`` ist falsch und ``unklar`` wahr,
        wenn kein Werteänderungs-Wunsch zu erkennen war.
    """

    werte = {"farbe_a": 1.0, "farbe_b": 0.62}
    if aktuell:
        werte.update(aktuell)

    knapp = " " + " ".join(text.lower().split()) + " "

    aend = _groessen_wunsch(knapp)
    aend += _farbwunsch(knapp, werte["farbe_a"], werte["farbe_b"])

    if not aend:
        return Deutung(
            unklar=True,
            erklaerung=(
                "Das ist keine einfache Werteänderung – dafür schreibe ich "
                "den Code selbst um."
            ),
        )

    teile = [_beschreibe(a) for a in aend]
    return Deutung(aenderungen=aend, erklaerung="; ".join(t for t in teile if t))


def _beschreibe(a: Aenderung) -> str:
    """Ein kurzer Satz, was die Änderung tut – für die Bestätigung."""

    namen = {
        "scale": "die Grösse",
        "punkt_groesse": "die Punktgrösse",
        "abstand": "den Abstand",
        "verschmelzen": "das Verschmelzen",
        "schweif_laenge": "die Fäden",
        "tempo": "das Tempo",
        "helligkeit": "die Helligkeit",
        "farbe_a": "die erste Farbe",
        "farbe_b": "die zweite Farbe",
    }
    name = namen.get(a.schluessel, a.schluessel)
    if a.zielwert is not None:
        return f"{name} neu gesetzt"
    if a.faktor is not None:
        return f"{name} {'erhöht' if a.faktor > 1 else 'verringert'}"
    if a.summand is not None:
        return f"{name} {'verlängert' if a.summand > 0 else 'verkürzt'}"
    return ""
