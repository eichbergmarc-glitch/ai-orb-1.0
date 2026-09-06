"""Deutsche Schreibweisen fuer eine verlaessliche Sprachausgabe.

Ziffern sind fuer eine TTS-Engine mehrdeutig. ``1789`` kann als Zahl,
Ziffernfolge oder englisch gepraegte Jahreszahl gelesen werden. Historische
Jahreszahlen werden deshalb vor jedem Sprachausgabe-Verfahren in genau die
deutsche Form umgewandelt, die der Orb sagen soll.
"""

from __future__ import annotations

import re

_EINER = (
    "null", "eins", "zwei", "drei", "vier", "fünf", "sechs", "sieben",
    "acht", "neun",
)
_KLEIN = {
    10: "zehn",
    11: "elf",
    12: "zwölf",
    13: "dreizehn",
    14: "vierzehn",
    15: "fünfzehn",
    16: "sechzehn",
    17: "siebzehn",
    18: "achtzehn",
    19: "neunzehn",
}
_ZEHNER = {
    20: "zwanzig",
    30: "dreißig",
    40: "vierzig",
    50: "fünfzig",
    60: "sechzig",
    70: "siebzig",
    80: "achtzig",
    90: "neunzig",
}


def zahl_in_worten(zahl: int) -> str:
    """Schreibt eine nichtnegative ganze Zahl bis 9999 als deutsches Wort."""

    wert = int(zahl)
    if not 0 <= wert <= 9999:
        return str(wert)
    if wert < 10:
        return _EINER[wert]
    if wert < 20:
        return _KLEIN[wert]
    if wert < 100:
        einer = wert % 10
        zehner = wert - einer
        return _ZEHNER[zehner] if not einer else ("ein" if einer == 1 else _EINER[einer]) + "und" + _ZEHNER[zehner]
    if wert < 1000:
        hunderter, rest = divmod(wert, 100)
        anfang = ("ein" if hunderter == 1 else _EINER[hunderter]) + "hundert"
        return anfang + (zahl_in_worten(rest) if rest else "")

    tausender, rest = divmod(wert, 1000)
    anfang = ("ein" if tausender == 1 else zahl_in_worten(tausender)) + "tausend"
    return anfang + (zahl_in_worten(rest) if rest else "")


def jahreszahl_in_worten(jahr: int) -> str:
    """Spricht ein Jahr nach deutscher Konvention aus.

    1789 wird zu ``siebzehnhundertneunundachtzig``; ab 2000 gilt die
    Tausenderform. Jahre zwischen 1000 und 1099 bleiben ebenfalls in der
    eindeutigen Tausenderform.
    """

    wert = int(jahr)
    if 1100 <= wert <= 1999:
        jahrhundert, rest = divmod(wert, 100)
        return zahl_in_worten(jahrhundert) + "hundert" + (
            zahl_in_worten(rest) if rest else ""
        )
    return zahl_in_worten(wert)


_JAHR = r"(?:1[0-9]{3}|2[0-1][0-9]{2})"
_AERA = re.compile(
    r"(?<!\d)([1-9]\d{0,3})\s*(v|n)\.\s*Chr\.?",
    flags=re.IGNORECASE,
)
_BEREICH = re.compile(
    rf"(?<!\d)({_JAHR})\s*[–—-]\s*({_JAHR})(?!\d)"
)
_VIERSTELLIG = re.compile(rf"(?<![\d.,])({_JAHR})(?!\d|[.,]\d)")
_KONTEXT_JAHR = re.compile(
    r"\b((?:im\s+)?Jahr|um|seit|ab)\s+([1-9]\d{2})\b",
    flags=re.IGNORECASE,
)


def jahreszahlen_sprechbar(text: str) -> str:
    """Ersetzt eindeutig erkennbare Jahreszahlen, ohne Messwerte anzutasten."""

    def _aera(treffer: re.Match[str]) -> str:
        jahr = int(treffer.group(1))
        wort = jahreszahl_in_worten(jahr) if jahr >= 1000 else zahl_in_worten(jahr)
        richtung = "vor Christus" if treffer.group(2).lower() == "v" else "nach Christus"
        return f"{wort} {richtung}"

    def _bereich(treffer: re.Match[str]) -> str:
        return (
            f"{jahreszahl_in_worten(int(treffer.group(1)))} bis "
            f"{jahreszahl_in_worten(int(treffer.group(2)))}"
        )

    def _kontext(treffer: re.Match[str]) -> str:
        return f"{treffer.group(1)} {zahl_in_worten(int(treffer.group(2)))}"

    ergebnis = _AERA.sub(_aera, str(text or ""))
    ergebnis = _BEREICH.sub(_bereich, ergebnis)
    ergebnis = _VIERSTELLIG.sub(
        lambda treffer: jahreszahl_in_worten(int(treffer.group(1))), ergebnis
    )
    return _KONTEXT_JAHR.sub(_kontext, ergebnis)


# ===================================================== Sprechbare Satzzeichen

#: Typografische Zeichen und ihre einfache Entsprechung.
#:
#: Modelle wie Supertonic prüfen ihren Zeichenvorrat streng und brechen bei
#: einem einzigen unbekannten Zeichen die ganze Ausgabe ab - im Betrieb
#: geschehen mit ``„`` und ``›``. Die Zeichen kommen zuverlässig vor,
#: sobald ein Sprachmodell ordentliche Typografie liefert. Gesprochen wird
#: ohnehin keines davon; die einfache Form ändert am Klang nichts.
_EINFACH = {
    "\u201e": '"',   # „
    "\u201c": '"',   # “
    "\u201d": '"',   # ”
    "\u201f": '"',
    "\u201a": "'",   # ‚
    "\u2018": "'",   # ‘
    "\u2019": "'",   # ’
    "\u00ab": '"',   # «
    "\u00bb": '"',   # »
    "\u2039": "'",   # ‹
    "\u203a": "'",   # ›
    "\u2013": "-",   # Halbgeviertstrich
    "\u2014": "-",   # Geviertstrich
    "\u2010": "-",
    "\u2011": "-",
    "\u2012": "-",
    "\u2212": "-",   # Minuszeichen
    "\u2026": "...", # Auslassungspunkte
    "\u00a0": " ",   # geschütztes Leerzeichen
    "\u202f": " ",
    "\u2009": " ",
    "\u200b": "",
    "\ufeff": "",
}

_EINFACH_MUSTER = re.compile("|".join(map(re.escape, _EINFACH)))


def satzzeichen_sprechbar(text: str) -> str:
    """Ersetzt typografische Zeichen durch ihre einfache Form.

    Absichtlich keine allgemeine Unicode-Normalisierung: Umlaute und ß
    sollen unangetastet bleiben, und was hier nicht aufgeführt ist, geht
    unverändert durch - unbekannte Zeichen behandelt die jeweilige Engine
    selbst.
    """

    return _EINFACH_MUSTER.sub(lambda t: _EINFACH[t.group(0)], str(text or ""))
