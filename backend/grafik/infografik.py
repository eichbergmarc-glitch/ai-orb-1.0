"""Lokale, reproduzierbare Infografiken fuer erklaerende Dokumente.

Das Modul verwendet nur Pillow und braucht weder einen Bilddienst noch ein
Sprachmodell. Aus einem gegliederten Text entsteht eine hochaufgeloeste
Uebersicht mit Titel, Kernaussagen und einem klaren visuellen Lesefluss.
"""

from __future__ import annotations

import re
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


_NAVY = (5, 20, 45)
_NAVY_LIGHT = (12, 42, 78)
_CYAN = (38, 190, 255)
_BLUE = (40, 105, 255)
_VIOLET = (134, 86, 255)
_WHITE = (244, 249, 255)
_MUTED = (178, 202, 226)


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = (
        Path("C:/Windows/Fonts/seguisb.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf"),
        Path("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"),
    )
    for candidate in candidates:
        if candidate.is_file():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()


def _sauber(text: str) -> str:
    return " ".join(
        re.sub(r"^\s*(?:#{1,4}|[-*•]|\d+[.)])\s*", "", str(text or "")).split()
    )


def _karten_aus(inhalt: str, *, hoechstens: int = 6) -> list[tuple[str, str]]:
    """Extrahiert Ueberschriften und Kernaussagen aus Markdown oder Fliesstext."""

    karten: list[tuple[str, str]] = []
    aktuelle_ueberschrift = "Kernaussage"
    absatz: list[str] = []

    def speichern() -> None:
        nonlocal absatz
        text = _sauber(" ".join(absatz))
        if text:
            karten.append((aktuelle_ueberschrift, text))
        absatz = []

    for roh in str(inhalt or "").splitlines():
        zeile = roh.strip()
        if not zeile:
            speichern()
            continue
        treffer = re.match(r"^#{1,4}\s+(.+)$", zeile)
        if treffer:
            speichern()
            aktuelle_ueberschrift = _sauber(treffer.group(1)) or "Kernaussage"
            continue
        absatz.append(zeile)
    speichern()

    if len(karten) < 2:
        saetze = [
            _sauber(satz)
            for satz in re.split(r"(?<=[.!?])\s+", str(inhalt or ""))
            if len(_sauber(satz)) >= 24
        ]
        karten = [(f"Aspekt {index}", satz) for index, satz in enumerate(saetze, 1)]

    ergebnis: list[tuple[str, str]] = []
    for titel, text in karten:
        if len(ergebnis) >= hoechstens:
            break
        kurz = text[:330].rsplit(" ", 1)[0] if len(text) > 330 else text
        ergebnis.append((titel[:58], kurz))
    return ergebnis or [("Ueberblick", "Die wichtigsten Zusammenhaenge auf einen Blick.")]


def _zeilen(text: str, *, breite: int) -> list[str]:
    return textwrap.wrap(_sauber(text), width=max(12, breite), break_long_words=False)


def _konzept_zeichnen(
    draw: ImageDraw.ImageDraw,
    karten: list[tuple[str, str]],
    *,
    breite: int,
    hoehe: int,
    rand: int,
    title_font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    card_title_font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    body_font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
) -> None:
    """Zeichnet Kern plus fachliche Dimensionen als echte Konzeptkarte."""

    kern_titel, kern_text = karten[0]
    aussen = karten[1:6]
    mitte_x = breite // 2
    mitte_y = 565
    anzahl = len(aussen)
    positionen = {
        0: [],
        1: [(mitte_x, 335)],
        2: [(300, 545), (breite - 300, 545)],
        3: [(300, 335), (breite - 300, 335), (mitte_x, 800)],
        4: [(300, 335), (breite - 300, 335), (300, 790), (breite - 300, 790)],
        5: [
            (300, 335),
            (breite - 300, 335),
            (250, 790),
            (breite - 250, 790),
            (mitte_x, 820),
        ],
    }[anzahl]
    akzente = (_CYAN, _VIOLET, (49, 218, 173), (255, 170, 56), (240, 92, 159))

    # Verbindungen zuerst, damit sie sauber hinter den Knoten liegen.
    for index, (x, y) in enumerate(positionen):
        akzent = akzente[index % len(akzente)]
        draw.line((mitte_x, mitte_y, x, y), fill=(*akzent[:3],), width=5)
        knoten_x = int(mitte_x + (x - mitte_x) * 0.54)
        knoten_y = int(mitte_y + (y - mitte_y) * 0.54)
        draw.ellipse(
            (knoten_x - 9, knoten_y - 9, knoten_x + 9, knoten_y + 9),
            fill=akzent,
        )

    # Zentraler Zusammenhang statt einer blossen ersten Listenkarte.
    kern_box = (mitte_x - 245, mitte_y - 92, mitte_x + 245, mitte_y + 92)
    draw.rounded_rectangle(
        kern_box,
        radius=34,
        fill=(13, 54, 98),
        outline=_CYAN,
        width=4,
    )
    draw.text(
        (kern_box[0] + 28, kern_box[1] + 22),
        _sauber(kern_titel),
        font=card_title_font,
        fill=_WHITE,
    )
    for line_index, line in enumerate(_zeilen(kern_text, breite=42)[:4]):
        draw.text(
            (kern_box[0] + 28, kern_box[1] + 67 + line_index * 25),
            line,
            font=body_font,
            fill=_MUTED,
        )

    knoten_breite = 400
    knoten_hoehe = 168
    for index, ((ueberschrift, text), (x, y)) in enumerate(zip(aussen, positionen)):
        akzent = akzente[index % len(akzente)]
        x1, y1 = x - knoten_breite // 2, y - knoten_hoehe // 2
        x2, y2 = x1 + knoten_breite, y1 + knoten_hoehe
        draw.rounded_rectangle(
            (x1, y1, x2, y2),
            radius=25,
            fill=(8, 34, 68),
            outline=akzent,
            width=3,
        )
        draw.ellipse((x1 + 20, y1 + 18, x1 + 60, y1 + 58), fill=akzent)
        draw.text(
            (x1 + 76, y1 + 21),
            _sauber(ueberschrift)[:31],
            font=card_title_font,
            fill=_WHITE,
        )
        for line_index, line in enumerate(_zeilen(text, breite=36)[:4]):
            draw.text(
                (x1 + 24, y1 + 73 + line_index * 24),
                line,
                font=body_font,
                fill=_MUTED,
            )


def infografik_zeichnen(
    *,
    titel: str,
    inhalt: str,
    ziel: Path,
    quelle: str = "",
    layout: str = "karten",
    breite: int = 1600,
    hoehe: int = 1000,
) -> Path:
    """Zeichnet eine moderne Uebersicht und speichert sie verlustfrei als PNG."""

    breite = max(1000, min(int(breite), 2400))
    hoehe = max(700, min(int(hoehe), 1600))
    bild = Image.new("RGB", (breite, hoehe), _NAVY)
    draw = ImageDraw.Draw(bild)

    # Ruhiger vertikaler Verlauf statt einer flachen Hintergrundfarbe.
    for y in range(hoehe):
        anteil = y / max(1, hoehe - 1)
        farbe = tuple(
            int(_NAVY[index] * (1 - anteil) + _NAVY_LIGHT[index] * anteil)
            for index in range(3)
        )
        draw.line((0, y, breite, y), fill=farbe)

    rand = int(breite * 0.055)
    draw.rounded_rectangle(
        (rand, 45, breite - rand, 205), radius=34,
        fill=(7, 28, 57), outline=(25, 112, 190), width=3,
    )
    draw.ellipse((rand + 28, 82, rand + 104, 158), fill=_BLUE, outline=_CYAN, width=4)
    draw.ellipse((rand + 51, 105, rand + 81, 135), fill=_WHITE)

    title_font = _font(46, bold=True)
    subtitle_font = _font(21)
    card_title_font = _font(25, bold=True)
    body_font = _font(20)
    small_font = _font(16)

    titel_zeilen = _zeilen(titel, breite=42)[:2]
    for index, zeile in enumerate(titel_zeilen):
        draw.text((rand + 135, 70 + index * 53), zeile, font=title_font, fill=_WHITE)
    draw.text(
        (rand + 138, 166), "Visuelle Zusammenfassung · erstellt von AI-Orb",
        font=subtitle_font, fill=_CYAN,
    )

    karten = _karten_aus(inhalt)
    if str(layout or "").casefold() in {"konzept", "concept", "overview"}:
        _konzept_zeichnen(
            draw,
            karten,
            breite=breite,
            hoehe=hoehe,
            rand=rand,
            title_font=title_font,
            card_title_font=card_title_font,
            body_font=body_font,
        )
        if quelle:
            quelle_text = _sauber(quelle)
            if len(quelle_text) > 170:
                quelle_text = quelle_text[:167].rsplit(" ", 1)[0] + "..."
            draw.text(
                (rand, hoehe - 35),
                f"Quelle: {quelle_text}",
                font=small_font,
                fill=_MUTED,
            )
        ziel = Path(ziel)
        ziel.parent.mkdir(parents=True, exist_ok=True)
        bild.save(ziel, format="PNG", optimize=True)
        return ziel

    # Vier Punkte wirken als ruhiges 2x2-Raster deutlich ausgewogener als
    # drei Karten oben und eine einzelne unten. Ab fuenf Punkten nutzen wir
    # die volle Breite mit drei Spalten.
    if len(karten) == 4:
        spalten = 2
    elif len(karten) >= 3:
        spalten = 3
    else:
        spalten = max(1, len(karten))
    zeilenanzahl = (len(karten) + spalten - 1) // spalten
    luecke = 28
    oben = 245
    unten = 82 if quelle else 48
    kartenbreite = (breite - 2 * rand - (spalten - 1) * luecke) // spalten
    kartenhoehe = (hoehe - oben - unten - (zeilenanzahl - 1) * luecke) // zeilenanzahl
    akzente = (_CYAN, _VIOLET, (49, 218, 173), (255, 170, 56), _BLUE, (240, 92, 159))

    for index, (ueberschrift, text) in enumerate(karten):
        reihe, spalte = divmod(index, spalten)
        x1 = rand + spalte * (kartenbreite + luecke)
        y1 = oben + reihe * (kartenhoehe + luecke)
        x2, y2 = x1 + kartenbreite, y1 + kartenhoehe
        akzent = akzente[index % len(akzente)]
        draw.rounded_rectangle(
            (x1, y1, x2, y2), radius=28,
            fill=(9, 32, 64), outline=(31, 74, 116), width=2,
        )
        draw.rounded_rectangle((x1, y1, x1 + 12, y2), radius=6, fill=akzent)
        draw.ellipse((x1 + 34, y1 + 28, x1 + 86, y1 + 80), fill=akzent)
        nummer = str(index + 1)
        box = draw.textbbox((0, 0), nummer, font=card_title_font)
        draw.text(
            (x1 + 60 - (box[2] - box[0]) / 2, y1 + 54 - (box[3] - box[1]) / 2),
            nummer, font=card_title_font, fill=_NAVY,
        )
        for line_index, line in enumerate(_zeilen(ueberschrift, breite=25)[:2]):
            draw.text((x1 + 104, y1 + 26 + line_index * 31), line, font=card_title_font, fill=_WHITE)

        max_body_lines = max(3, int((kartenhoehe - 126) / 28))
        for line_index, line in enumerate(_zeilen(text, breite=37)[:max_body_lines]):
            draw.text((x1 + 35, y1 + 111 + line_index * 28), line, font=body_font, fill=_MUTED)

    if quelle:
        quelle_text = _sauber(quelle)
        if len(quelle_text) > 170:
            quelle_text = quelle_text[:167].rsplit(" ", 1)[0] + "..."
        draw.text((rand, hoehe - 49), f"Quelle: {quelle_text}", font=small_font, fill=_MUTED)

    ziel = Path(ziel)
    ziel.parent.mkdir(parents=True, exist_ok=True)
    bild.save(ziel, format="PNG", optimize=True)
    return ziel
