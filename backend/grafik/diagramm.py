"""Zeichnet Diagramme als PNG - allein mit Pillow, ohne Netz und ohne matplotlib.

Warum selbst zeichnen statt matplotlib zu benutzen: matplotlib zieht numpy,
Schriftcaches und rund neunzig Megabyte hinter sich her, und der Orb soll
seine Bilder auch dann noch herstellen koennen, wenn nichts nachinstalliert
wurde. Pillow ist ohnehin da - es wird schon fuers Bildschirmlesen
gebraucht. Was hier fehlt, sind Achsenskalen fuer Logarithmen und
Fehlerbalken. Was hier steht, deckt das ab, was in einem Bericht vorkommt.

## Die Regeln, nach denen gezeichnet wird

Sie stammen nicht aus dem Geschmack, sondern aus einer geprueften
Farbfolge und ein paar harten Festlegungen:

* Die acht Reihenfarben stehen in fester Reihenfolge und werden **nie im
  Kreis** weitergegeben. Ab der neunten Reihe wird zusammengefasst, nicht
  eine neue Farbe erfunden.
* Es gibt **nur eine Werteachse**. Zwei Groessen mit verschiedenen
  Einheiten in ein Bild zu zwingen ist der haeufigste Diagrammfehler; dann
  lieber zwei Bilder.
* Farbe traegt nie allein die Bedeutung. Ab zwei Reihen gibt es immer eine
  Legende, und Werte stehen als Zahl am Objekt.
* Gitter und Achsen treten zurueck, die Daten nicht. Text bleibt in
  Textfarben - nie in der Farbe seiner Reihe.

Die Farben sind auf Farbfehlsichtigkeit geprueft (Rot-Gruen- und
Blau-Gelb-Schwaeche); die Reihenfolge ist das Mittel dafuer und deshalb
nicht beliebig umstellbar. Fuer Punktdiagramme, bei denen jede Farbe neben
jeder anderen liegen kann, reicht die Pruefung nur fuer drei Reihen - dort
wird bei drei abgeschnitten.

## Warum dreifach gezeichnet und dann verkleinert wird

Pillow kennt keine Kantenglaettung. Ein schraeger Strich waere eine Treppe.
Deshalb entsteht alles in dreifacher Groesse und wird am Ende mit einem
guten Filter heruntergerechnet. Das kostet ein paar Zehntelsekunden und ist
der Unterschied zwischen "sieht nach Programm aus" und "sieht nach Druck
aus".
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

from backend.system.logging_setup import get_logger

logger = get_logger(__name__)

#: Vergroesserungsfaktor beim Zeichnen. Am Ende wird darauf zurueckgerechnet.
_SKALA = 3

#: Die acht Reihenfarben in gepruefter Reihenfolge (heller Untergrund).
REIHENFARBEN: tuple[str, ...] = (
    "#2a78d6",  # Blau
    "#eb6834",  # Orange
    "#1baf7a",  # Tuerkis
    "#eda100",  # Gelb
    "#e87ba4",  # Magenta
    "#008300",  # Gruen
    "#4a3aa7",  # Violett
    "#e34948",  # Rot
)

#: Ab wie vielen Reihen zusammengefasst wird.
_MAX_REIHEN = len(REIHENFARBEN)

#: Punktdiagramme stellen jede Farbe neben jede andere. Dafuer ist nur der
#: Anfang der Folge geprueft.
_MAX_REIHEN_PUNKTE = 3

#: Mehr Tortenstuecke kann niemand mehr unterscheiden.
_MAX_STUECKE = 6

_UNTERGRUND = "#ffffff"
_TEXT_STARK = "#0b0b0b"
_TEXT_MITTEL = "#52514e"
_TEXT_LEISE = "#77756f"
_GITTER = "#e7e6e3"
_ACHSE = "#c9c8c4"

_ARTEN = ("balken", "linie", "torte", "punkte")

#: Schriften, der Reihe nach probiert. Die erste, die es gibt, gewinnt.
_SCHRIFTEN_NORMAL = (
    r"C:\Windows\Fonts\segoeui.ttf",
    r"C:\Windows\Fonts\arial.ttf",
    r"C:\Windows\Fonts\calibri.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
)
_SCHRIFTEN_FETT = (
    r"C:\Windows\Fonts\seguisb.ttf",
    r"C:\Windows\Fonts\segoeuib.ttf",
    r"C:\Windows\Fonts\arialbd.ttf",
    r"C:\Windows\Fonts\calibrib.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
)


class DiagrammFehler(ValueError):
    """Die Angaben ergeben kein zeichenbares Diagramm."""


@dataclass(slots=True)
class Reihe:
    """Eine Datenreihe: ein Name und ein Wert je Kategorie."""

    name: str
    werte: list[float] = field(default_factory=list)


# ---------------------------------------------------------------------------
#  Zahlen und Schrift
# ---------------------------------------------------------------------------


def _zahl(wert: float, *, stellen: int | None = None) -> str:
    """Formatiert eine Zahl deutsch: Punkt als Tausender, Komma als Dezimale."""

    if stellen is None:
        stellen = 0 if abs(wert - round(wert)) < 1e-9 else 1
    text = f"{wert:,.{stellen}f}"
    # Erst die englischen Trennzeichen gegen Platzhalter tauschen, damit sich
    # die beiden Ersetzungen nicht gegenseitig auffressen.
    return text.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def _schrift(groesse: int, *, fett: bool = False):
    from PIL import ImageFont

    for pfad in _SCHRIFTEN_FETT if fett else _SCHRIFTEN_NORMAL:
        try:
            return ImageFont.truetype(pfad, groesse)
        except OSError:
            continue
    # Kein TrueType gefunden. Die eingebaute Schrift ist haesslich, aber
    # lesbar - und ein Diagramm ohne Beschriftung waere wertlos.
    try:
        return ImageFont.load_default(size=groesse)
    except TypeError:  # Pillow vor 10.1
        return ImageFont.load_default()


def _breite(zeichner, text: str, schrift) -> float:
    links, _, rechts, _ = zeichner.textbbox((0, 0), text, font=schrift)
    return rechts - links


def _hoehe(zeichner, text: str, schrift) -> float:
    _, oben, _, unten = zeichner.textbbox((0, 0), text, font=schrift)
    return unten - oben


def _kuerzen(zeichner, text: str, schrift, grenze: float) -> str:
    """Kuerzt einen Text mit Auslassungspunkten auf eine Breite."""

    if _breite(zeichner, text, schrift) <= grenze:
        return text
    gekuerzt = text
    while gekuerzt and _breite(zeichner, gekuerzt + "…", schrift) > grenze:
        gekuerzt = gekuerzt[:-1]
    return (gekuerzt + "…") if gekuerzt else ""


# ---------------------------------------------------------------------------
#  Achsenteilung
# ---------------------------------------------------------------------------


def _runde_schrittweite(spanne: float, ziel_anzahl: int) -> float:
    """Sucht eine Schrittweite, die ein Mensch im Kopf nachrechnen kann.

    Also 1, 2, 2.5, 5, 10 mal einer Zehnerpotenz - nie 3.7 oder 0.83.
    """

    if spanne <= 0:
        return 1.0
    roh = spanne / max(1, ziel_anzahl)
    potenz = 10 ** math.floor(math.log10(roh))
    for vielfaches in (1.0, 2.0, 2.5, 5.0, 10.0):
        if roh <= vielfaches * potenz:
            return vielfaches * potenz
    return 10.0 * potenz


def _achsenbereich(werte: list[float]) -> tuple[float, float, float]:
    """Bestimmt Unter- und Obergrenze der Werteachse samt Schrittweite.

    Die Null bleibt drin, solange alle Werte dasselbe Vorzeichen haben - eine
    abgeschnittene Achse laesst kleine Unterschiede gross aussehen und ist
    die verbreitetste Art, mit einem korrekten Diagramm zu luegen.
    """

    echte = [w for w in werte if w is not None and math.isfinite(w)]
    if not echte:
        return 0.0, 1.0, 0.5

    tief = min(echte)
    hoch = max(echte)
    if tief > 0:
        tief = 0.0
    if hoch < 0:
        hoch = 0.0
    if hoch == tief:
        hoch = tief + 1.0

    schritt = _runde_schrittweite(hoch - tief, 5)
    unten = math.floor(tief / schritt) * schritt
    oben = math.ceil(hoch / schritt) * schritt
    if oben == unten:
        oben = unten + schritt
    return unten, oben, schritt


# ---------------------------------------------------------------------------
#  Das Diagramm
# ---------------------------------------------------------------------------


def _vorbereiten(
    art: str,
    kategorien: list[str],
    reihen: list[Reihe],
) -> tuple[list[str], list[Reihe], str]:
    """Prueft die Angaben und fasst ueberzaehlige Reihen zusammen."""

    art = (art or "").strip().lower()
    if art in ("saeule", "säule", "bar", "balkendiagramm"):
        art = "balken"
    elif art in ("linien", "verlauf", "line"):
        art = "linie"
    elif art in ("kreis", "kuchen", "pie", "donut", "ring"):
        art = "torte"
    elif art in ("punkt", "streu", "scatter"):
        art = "punkte"
    if art not in _ARTEN:
        raise DiagrammFehler(
            f"Unbekannte Diagrammart '{art}'. Moeglich sind: {', '.join(_ARTEN)}."
        )

    kategorien = [str(k).strip() for k in kategorien]
    if not kategorien:
        raise DiagrammFehler("Ohne Kategorien laesst sich nichts zeichnen.")

    sauber: list[Reihe] = []
    for reihe in reihen:
        werte = [float(w) if w is not None and math.isfinite(float(w)) else 0.0
                 for w in list(reihe.werte)[: len(kategorien)]]
        werte += [0.0] * (len(kategorien) - len(werte))
        sauber.append(Reihe(name=str(reihe.name).strip() or "Reihe", werte=werte))

    if not sauber:
        raise DiagrammFehler("Ohne Werte laesst sich nichts zeichnen.")

    grenze = _MAX_REIHEN_PUNKTE if art == "punkte" else _MAX_REIHEN
    if len(sauber) > grenze:
        # Nicht die Farbfolge im Kreis weiterdrehen, sondern zusammenfassen.
        # Zwei Reihen in derselben Farbe waeren schlimmer als eine Sammelreihe.
        rest = sauber[grenze - 1:]
        summe = [sum(r.werte[i] for r in rest) for i in range(len(kategorien))]
        sauber = sauber[: grenze - 1] + [Reihe(name="Sonstige", werte=summe)]
        logger.info(
            "Diagramm: %d Reihen zu 'Sonstige' zusammengefasst (Grenze %d).",
            len(rest), grenze,
        )

    return kategorien, sauber, art


#: Die Baender unter der Zeichenflaeche, von oben nach unten. Sie werden hier
#: reserviert und weiter unten in genau dieser Reihenfolge beschriftet - beides
#: aus denselben Zahlen, damit sich Kategorien und Legende nicht ueberlagern.
_BAND_KATEGORIEN = 26
_BAND_ACHSE_X = 24
_BAND_LEGENDE = 30


def _flaeche(
    zeichner,
    breite: int,
    hoehe: int,
    titel: str,
    quelle: str,
    achse_y: str,
    achse_x: str,
    mit_legende: bool,
    mit_kategorien: bool,
) -> tuple[float, float, float, float]:
    """Zeichnet Titel und Fussnote und gibt die freie Zeichenflaeche zurueck."""

    s = _SKALA
    links, rechts = 20 * s, 22 * s
    oben, unten = 18 * s, 18 * s

    if titel:
        schrift = _schrift(21 * s, fett=True)
        zeichner.text((links, oben), titel, font=schrift, fill=_TEXT_STARK)
        oben += _hoehe(zeichner, titel, schrift) + 17 * s

    if quelle:
        schrift = _schrift(11 * s)
        text = _kuerzen(zeichner, quelle, schrift, breite - links - rechts)
        hoch = _hoehe(zeichner, text, schrift)
        zeichner.text((links, hoehe - unten - hoch), text, font=schrift, fill=_TEXT_LEISE)
        unten += hoch + 12 * s

    if mit_kategorien:
        unten += _BAND_KATEGORIEN * s
    if achse_x:
        unten += _BAND_ACHSE_X * s
    if mit_legende:
        unten += _BAND_LEGENDE * s
    if achse_y:
        oben += 20 * s

    return links, oben, breite - rechts, hoehe - unten


def _legende(zeichner, reihen: list[Reihe], links: float, y: float, rechts: float) -> None:
    """Setzt die Legende in eine Zeile, mittig unter das Diagramm.

    Sie ist ab zwei Reihen Pflicht: Ohne sie traegt die Farbe die Bedeutung
    allein, und wer Farben schlecht unterscheidet, sieht dann nur bunte
    Balken.
    """

    s = _SKALA
    schrift = _schrift(12 * s)
    punkt, abstand, luecke = 9 * s, 7 * s, 20 * s

    stuecke = [(r.name, REIHENFARBEN[i % len(REIHENFARBEN)]) for i, r in enumerate(reihen)]
    gesamt = sum(punkt + abstand + _breite(zeichner, n, schrift) for n, _ in stuecke)
    gesamt += luecke * (len(stuecke) - 1)

    x = links + max(0.0, (rechts - links - gesamt) / 2)
    for name, farbe in stuecke:
        mitte = y + punkt / 2
        zeichner.ellipse([x, mitte - punkt / 2, x + punkt, mitte + punkt / 2], fill=farbe)
        x += punkt + abstand
        zeichner.text((x, y - 2 * s), name, font=schrift, fill=_TEXT_MITTEL)
        x += _breite(zeichner, name, schrift) + luecke


def _werteachse(
    zeichner,
    links: float,
    oben: float,
    rechts: float,
    unten: float,
    tief: float,
    hoch: float,
    schritt: float,
    einheit: str,
) -> tuple[float, float]:
    """Zeichnet Gitterlinien und Achsenbeschriftung. Gibt die Datenflaeche zurueck."""

    s = _SKALA
    schrift = _schrift(12 * s)

    marken: list[float] = []
    wert = tief
    while wert <= hoch + schritt / 1000:
        marken.append(round(wert, 10))
        wert += schritt

    breiteste = max(
        _breite(zeichner, _zahl(m) + (f" {einheit}" if einheit else ""), schrift)
        for m in marken
    )
    daten_links = links + breiteste + 10 * s

    for marke in marken:
        anteil = (marke - tief) / (hoch - tief)
        y = unten - anteil * (unten - oben)
        farbe = _ACHSE if abs(marke) < 1e-12 else _GITTER
        zeichner.line([daten_links, y, rechts, y], fill=farbe, width=max(1, s // 2))
        text = _zahl(marke) + (f" {einheit}" if einheit else "")
        zeichner.text(
            (daten_links - 10 * s - _breite(zeichner, text, schrift),
             y - _hoehe(zeichner, text, schrift) / 2 - 2 * s),
            text, font=schrift, fill=_TEXT_MITTEL,
        )

    return daten_links, rechts


def _kategorienachse(
    zeichner,
    kategorien: list[str],
    daten_links: float,
    y: float,
    breite_je: float,
) -> None:
    """Beschriftet die Kategorien unter der Achse, notfalls gekuerzt."""

    s = _SKALA
    schrift = _schrift(12 * s)
    for i, name in enumerate(kategorien):
        mitte = daten_links + breite_je * (i + 0.5)
        text = _kuerzen(zeichner, name, schrift, breite_je - 6 * s)
        zeichner.text(
            (mitte - _breite(zeichner, text, schrift) / 2, y),
            text, font=schrift, fill=_TEXT_MITTEL,
        )


def _balken(
    zeichner, kategorien, reihen, daten_links, rechts, oben, unten, tief, hoch
) -> None:
    s = _SKALA
    schrift = _schrift(11 * s)
    breite_je = (rechts - daten_links) / len(kategorien)
    gruppe = breite_je * 0.68
    luecke = 2 * s  # Der Trennspalt zwischen benachbarten Balken.
    balken = max(3 * s, (gruppe - luecke * (len(reihen) - 1)) / len(reihen))
    radius = min(4 * s, balken / 2)
    null_y = unten - (0 - tief) / (hoch - tief) * (unten - oben)

    # Werte nur beschriften, wenn sie nicht zur Zahlentapete werden.
    beschriften = len(kategorien) * len(reihen) <= 24

    for k in range(len(kategorien)):
        start = daten_links + breite_je * (k + 0.5) - gruppe / 2
        for r, reihe in enumerate(reihen):
            wert = reihe.werte[k]
            x0 = start + r * (balken + luecke)
            x1 = x0 + balken
            y = unten - (wert - tief) / (hoch - tief) * (unten - oben)
            farbe = REIHENFARBEN[r % len(REIHENFARBEN)]
            o, u = (y, null_y) if wert >= 0 else (null_y, y)
            if u - o < 1:
                continue
            # Oben rund, unten buendig auf der Nulllinie: erst ein rundes
            # Rechteck ueber die volle Hoehe, dann die untere Rundung mit
            # einem geraden Rechteck wieder zudecken.
            zeichner.rounded_rectangle([x0, o, x1, u], radius=radius, fill=farbe)
            if u - o > radius:
                if wert >= 0:
                    zeichner.rectangle([x0, u - radius, x1, u], fill=farbe)
                else:
                    zeichner.rectangle([x0, o, x1, o + radius], fill=farbe)
            if beschriften:
                text = _zahl(wert)
                tx = x0 + balken / 2 - _breite(zeichner, text, schrift) / 2
                ty = (o - _hoehe(zeichner, text, schrift) - 7 * s) if wert >= 0 else (u + 5 * s)
                zeichner.text((tx, ty), text, font=schrift, fill=_TEXT_MITTEL)


def _linie(
    zeichner, kategorien, reihen, daten_links, rechts, oben, unten, tief, hoch
) -> None:
    s = _SKALA
    breite_je = (rechts - daten_links) / len(kategorien)
    punkte_zeigen = len(kategorien) <= 14

    for r, reihe in enumerate(reihen):
        farbe = REIHENFARBEN[r % len(REIHENFARBEN)]
        stellen = [
            (daten_links + breite_je * (i + 0.5),
             unten - (wert - tief) / (hoch - tief) * (unten - oben))
            for i, wert in enumerate(reihe.werte)
        ]
        if len(stellen) > 1:
            zeichner.line([p for stelle in stellen for p in stelle],
                          fill=farbe, width=2 * s, joint="curve")
        if punkte_zeigen:
            radius = 4 * s
            for x, y in stellen:
                # Der weisse Ring haelt sich kreuzende Reihen auseinander.
                zeichner.ellipse([x - radius - s, y - radius - s,
                                  x + radius + s, y + radius + s], fill=_UNTERGRUND)
                zeichner.ellipse([x - radius, y - radius, x + radius, y + radius], fill=farbe)


def _punkte(
    zeichner, kategorien, reihen, daten_links, rechts, oben, unten, tief, hoch
) -> None:
    s = _SKALA
    breite_je = (rechts - daten_links) / len(kategorien)
    radius = 5 * s
    for r, reihe in enumerate(reihen):
        farbe = REIHENFARBEN[r % len(REIHENFARBEN)]
        # Die Reihen leicht versetzen, damit gleiche Werte einander nicht
        # vollstaendig verdecken.
        versatz = (r - (len(reihen) - 1) / 2) * min(8 * s, breite_je * 0.14)
        for i, wert in enumerate(reihe.werte):
            x = daten_links + breite_je * (i + 0.5) + versatz
            y = unten - (wert - tief) / (hoch - tief) * (unten - oben)
            zeichner.ellipse([x - radius - s, y - radius - s,
                              x + radius + s, y + radius + s], fill=_UNTERGRUND)
            zeichner.ellipse([x - radius, y - radius, x + radius, y + radius], fill=farbe)


def _torte(zeichner, kategorien, werte, links, oben, rechts, unten) -> None:
    """Zeichnet einen Ring mit Beschriftung aussen und der Summe in der Mitte."""

    s = _SKALA
    summe = sum(w for w in werte if w > 0)
    if summe <= 0:
        raise DiagrammFehler("Ein Tortendiagramm braucht Werte groesser als null.")

    schrift = _schrift(12 * s)
    schrift_mitte = _schrift(20 * s, fett=True)
    schrift_klein = _schrift(11 * s)

    # Platz fuer die Beschriftung aussen lassen.
    mx = (links + rechts) / 2
    my = (oben + unten) / 2
    radius = min(rechts - links, unten - oben) / 2 - 62 * s
    radius = max(radius, 30 * s)
    innen = radius * 0.58

    winkel = -90.0
    for i, (name, wert) in enumerate(zip(kategorien, werte)):
        if wert <= 0:
            continue
        anteil = wert / summe
        weite = anteil * 360.0
        farbe = REIHENFARBEN[i % len(REIHENFARBEN)]
        zeichner.pieslice([mx - radius, my - radius, mx + radius, my + radius],
                          start=winkel, end=winkel + weite, fill=farbe)

        mitte_winkel = math.radians(winkel + weite / 2)
        # Beschriftung aussen, mit Fuehrungspunkt: an einem Ring liest sich
        # der Anteil sonst nur bei den grossen Stuecken.
        px = mx + math.cos(mitte_winkel) * (radius + 14 * s)
        py = my + math.sin(mitte_winkel) * (radius + 14 * s)
        prozent = f"{_zahl(anteil * 100, stellen=(0 if anteil >= 0.1 else 1))} %"
        beschriftung = _kuerzen(zeichner, name, schrift, 150 * s)
        breite_text = max(_breite(zeichner, beschriftung, schrift),
                          _breite(zeichner, prozent, schrift_klein))
        tx = px if math.cos(mitte_winkel) >= 0 else px - breite_text
        zeichner.text((tx, py - 15 * s), beschriftung, font=schrift, fill=_TEXT_STARK)
        zeichner.text((tx, py + 2 * s), prozent, font=schrift_klein, fill=_TEXT_MITTEL)

        winkel += weite

    # Erst das Loch, dann die Trennspalte - sonst zerschneiden die Spalte
    # auch die Mitte.
    zeichner.ellipse([mx - innen, my - innen, mx + innen, my + innen], fill=_UNTERGRUND)

    winkel = -90.0
    for wert in werte:
        if wert <= 0:
            continue
        bogen = math.radians(winkel)
        zeichner.line(
            [mx + math.cos(bogen) * innen, my + math.sin(bogen) * innen,
             mx + math.cos(bogen) * radius, my + math.sin(bogen) * radius],
            fill=_UNTERGRUND, width=2 * s,
        )
        winkel += wert / summe * 360.0

    text = _zahl(summe)
    zeichner.text((mx - _breite(zeichner, text, schrift_mitte) / 2,
                   my - _hoehe(zeichner, text, schrift_mitte) / 2 - 6 * s),
                  text, font=schrift_mitte, fill=_TEXT_STARK)
    zeichner.text((mx - _breite(zeichner, "gesamt", schrift_klein) / 2, my + 10 * s),
                  "gesamt", font=schrift_klein, fill=_TEXT_LEISE)


def diagramm_zeichnen(
    *,
    art: str,
    titel: str,
    kategorien: list[str],
    reihen: list[Reihe],
    ziel: Path,
    achse_x: str = "",
    achse_y: str = "",
    einheit: str = "",
    quelle: str = "",
    breite: int = 1000,
    hoehe: int = 620,
) -> Path:
    """Zeichnet ein Diagramm und speichert es als PNG.

    Args:
        art: ``balken``, ``linie``, ``torte`` oder ``punkte``.
        titel: Ueberschrift im Bild.
        kategorien: Die Beschriftung der waagerechten Achse beziehungsweise
            die Namen der Tortenstuecke.
        reihen: Eine oder mehrere Datenreihen. Beim Tortendiagramm zaehlt
            nur die erste.
        ziel: Wohin die PNG-Datei geschrieben wird.
        achse_x: Beschriftung der waagerechten Achse.
        achse_y: Beschriftung der Werteachse.
        einheit: Einheit hinter den Achsenzahlen, etwa ``%`` oder ``EUR``.
        quelle: Fussnote unter dem Bild - woher die Zahlen stammen.
        breite: Bildbreite in Bildpunkten.
        hoehe: Bildhoehe in Bildpunkten.

    Returns:
        Der Pfad der geschriebenen Datei.

    Raises:
        DiagrammFehler: Wenn die Angaben kein Diagramm ergeben.
        RuntimeError: Wenn Pillow fehlt.
    """

    try:
        from PIL import Image, ImageDraw
    except ImportError as fehler:  # pragma: no cover - Pillow ist eingerichtet.
        raise RuntimeError(
            "Zum Zeichnen wird Pillow gebraucht. Installieren mit: "
            "pip install -r requirements-vision.txt"
        ) from fehler

    kategorien, reihen, art = _vorbereiten(art, kategorien, reihen)

    breite = max(420, min(int(breite), 2400))
    hoehe = max(300, min(int(hoehe), 1800))
    s = _SKALA
    gross = Image.new("RGB", (breite * s, hoehe * s), _UNTERGRUND)
    zeichner = ImageDraw.Draw(gross)

    mit_legende = art != "torte" and len(reihen) >= 2
    links, oben, rechts, unten = _flaeche(
        zeichner, breite * s, hoehe * s, titel.strip(), quelle.strip(),
        achse_y.strip(), achse_x.strip() if art != "torte" else "",
        mit_legende, art != "torte",
    )

    if art == "torte":
        werte = [max(0.0, w) for w in reihen[0].werte]
        namen = list(kategorien)
        if len(namen) > _MAX_STUECKE:
            # Nach Groesse ordnen und den Rest zusammenfassen: Ein Ring mit
            # zwoelf Stuecken ist eine Farbtabelle, kein Diagramm.
            paare = sorted(zip(namen, werte), key=lambda p: p[1], reverse=True)
            kopf = paare[: _MAX_STUECKE - 1]
            rest = sum(w for _, w in paare[_MAX_STUECKE - 1:])
            namen = [n for n, _ in kopf] + ["Sonstige"]
            werte = [w for _, w in kopf] + [rest]
        _torte(zeichner, namen, werte, links, oben, rechts, unten)
    else:
        alle = [w for reihe in reihen for w in reihe.werte]
        tief, hoch, schritt = _achsenbereich(alle)
        daten_links, daten_rechts = _werteachse(
            zeichner, links, oben, rechts, unten, tief, hoch, schritt, einheit.strip()
        )
        zeichner.line([daten_links, unten, daten_rechts, unten],
                      fill=_ACHSE, width=max(1, s // 2))

        zeichenfunktion = {"balken": _balken, "linie": _linie, "punkte": _punkte}[art]
        zeichenfunktion(zeichner, kategorien, reihen, daten_links, daten_rechts,
                        oben, unten, tief, hoch)

        # Die Baender unter der Achse in derselben Reihenfolge fuellen, in der
        # sie oben reserviert wurden.
        y = unten + 9 * s
        breite_je = (daten_rechts - daten_links) / len(kategorien)
        _kategorienachse(zeichner, kategorien, daten_links, y, breite_je)
        y += _BAND_KATEGORIEN * s

        if achse_x.strip():
            schrift = _schrift(12 * s)
            text = achse_x.strip()
            zeichner.text(((daten_links + daten_rechts) / 2 - _breite(zeichner, text, schrift) / 2,
                           y), text, font=schrift, fill=_TEXT_LEISE)
            y += _BAND_ACHSE_X * s

        if achse_y.strip():
            schrift = _schrift(12 * s)
            zeichner.text((links, oben - 20 * s), achse_y.strip(),
                          font=schrift, fill=_TEXT_LEISE)

        if mit_legende:
            _legende(zeichner, reihen, links, y, rechts)

    klein = gross.resize((breite, hoehe), Image.LANCZOS)
    ziel = Path(ziel)
    ziel.parent.mkdir(parents=True, exist_ok=True)
    klein.save(ziel, format="PNG", optimize=True)
    logger.info("Diagramm gezeichnet: %s (%s, %d Reihen).", ziel, art, len(reihen))
    return ziel
