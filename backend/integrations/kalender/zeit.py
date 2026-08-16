"""Versteht Zeitangaben so, wie ein Mensch sie sagt.

Warum das nötig ist: Die Kalender-API will RFC-3339, also
``2026-09-15T14:00:00+02:00``. Gesagt wird aber "morgen um zwei",
"nächsten Dienstag" oder "am 15.9. halb elf". Dazwischen steht ein
Sprachmodell, das meistens - aber eben nur meistens - sauberes ISO
liefert. Ohne diese Übersetzung scheitert jeder dritte Termin an der
Schreibweise, und der Benutzer hört "das habe ich nicht verstanden",
obwohl er sich vollkommen klar ausgedrückt hat.

## Was verstanden wird

* ISO in jeder üblichen Form: ``2026-09-15T14:00``, ``2026-09-15 14:00``,
  ``2026-09-15``
* Deutsches Datum: ``15.09.2026``, ``15.9.``, ``15. September``
* Wortangaben: ``heute``, ``morgen``, ``übermorgen``, ``gestern``
* Wochentage: ``Dienstag``, ``nächsten Dienstag`` (immer der kommende)
* Verschiebungen: ``in 2 Stunden``, ``in 30 Minuten``, ``in 3 Tagen``,
  ``in einer Woche``
* Uhrzeiten: ``14:30``, ``14.30 Uhr``, ``14 Uhr``, ``halb drei``,
  ``viertel nach zehn``, ``mittags``, ``abends``

## Was bewusst nicht verstanden wird

Alles, was mehrdeutig bleibt. ``am Ersten`` könnte diesen oder nächsten
Monat meinen; ``09/10`` ist je nach Land September oder Oktober. In
solchen Fällen kommt ein Fehler mit Begründung - eine geratene Zeit im
Kalender ist schlimmer als eine Rückfrage.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta


class ZeitFehler(ValueError):
    """Die Zeitangabe war nicht eindeutig zu lesen."""


_WOCHENTAGE = {
    "montag": 0, "dienstag": 1, "mittwoch": 2, "donnerstag": 3,
    "freitag": 4, "samstag": 5, "sonnabend": 5, "sonntag": 6,
}

_MONATE = {
    "januar": 1, "jänner": 1, "februar": 2, "märz": 3, "maerz": 3, "april": 4,
    "mai": 5, "juni": 6, "juli": 7, "august": 8, "september": 9,
    "oktober": 10, "november": 11, "dezember": 12,
}

#: Tageszeiten als Uhrzeit. Bewusst grob - wer "abends" sagt, meint keine
#: bestimmte Minute, und ein Termin um 18 Uhr ist eine brauchbare Annahme.
_TAGESZEITEN = {
    "morgens": (8, 0), "vormittags": (10, 0), "mittags": (12, 0),
    "nachmittags": (15, 0), "abends": (18, 0), "nachts": (21, 0),
    "früh": (8, 0), "frueh": (8, 0),
}

_ZAHLWOERTER = {
    "ein": 1, "eine": 1, "einer": 1, "eins": 1, "zwei": 2, "drei": 3, "vier": 4,
    "fünf": 5, "fuenf": 5, "sechs": 6, "sieben": 7, "acht": 8, "neun": 9,
    "zehn": 10, "elf": 11, "zwölf": 12, "zwoelf": 12,
}


def _ortszeit(jetzt: datetime | None) -> datetime:
    """Die Gegenwart mit Zeitzone. Ohne Zone rechnet Google falsch."""

    if jetzt is None:
        jetzt = datetime.now()
    if jetzt.tzinfo is None:
        jetzt = jetzt.astimezone()
    return jetzt


def _menschliche_stunde(stunde: int) -> int:
    """Schiebt eine gesprochene Stundenangabe in die wache Tageszeit.

    "Halb drei" ist 14:30 und nicht 2:30. Niemand vereinbart einen Termin
    für halb drei nachts, und wer es doch tut, sagt "nachts" dazu. Die
    Grenze liegt bei sieben: "viertel vor acht" bleibt 7:45, weil das eine
    ganz gewöhnliche Uhrzeit ist.
    """

    return stunde + 12 if 0 <= stunde < 7 else stunde


def _uhrzeit_lesen(text: str) -> tuple[int, int] | None:
    """Sucht eine Uhrzeit im Text. ``None``, wenn keine drinsteht."""

    klein = text.lower()

    # "halb drei" = die halbe Stunde VOR drei, nicht danach.
    treffer = re.search(r"\bhalb\s+(\w+)", klein)
    if treffer:
        stunde = _ZAHLWOERTER.get(treffer.group(1)) or _als_zahl(treffer.group(1))
        if stunde is not None:
            return (_menschliche_stunde((stunde - 1) % 24), 30)

    treffer = re.search(r"\b(?:viertel\s+nach|viertel\s+ueber|viertel\s+über)\s+(\w+)", klein)
    if treffer:
        stunde = _ZAHLWOERTER.get(treffer.group(1)) or _als_zahl(treffer.group(1))
        if stunde is not None:
            return (_menschliche_stunde(stunde % 24), 15)

    treffer = re.search(r"\b(?:viertel\s+vor|dreiviertel)\s+(\w+)", klein)
    if treffer:
        stunde = _ZAHLWOERTER.get(treffer.group(1)) or _als_zahl(treffer.group(1))
        if stunde is not None:
            return (_menschliche_stunde((stunde - 1) % 24), 45)

    # 14:30, 14.30 Uhr, 14h30
    treffer = re.search(r"\b(\d{1,2})[:.h](\d{2})\b(?!\s*\d)", klein)
    if treffer:
        stunde, minute = int(treffer.group(1)), int(treffer.group(2))
        if stunde <= 23 and minute <= 59:
            return (stunde, minute)

    # "14 Uhr", "um 14"
    treffer = re.search(r"\b(?:um\s+)?(\d{1,2})\s*uhr\b", klein)
    if treffer and int(treffer.group(1)) <= 23:
        return (int(treffer.group(1)), 0)

    for wort, zeit in _TAGESZEITEN.items():
        if re.search(rf"\b{wort}\b", klein):
            return zeit

    return None


def _als_zahl(wort: str) -> int | None:
    try:
        return int(wort)
    except (TypeError, ValueError):
        return None


def _datum_lesen(text: str, heute: date) -> tuple[date | None, str]:
    """Sucht ein Datum im Text.

    Returns:
        Das Datum (oder ``None``) und den Text OHNE die Datumsangabe.

    Der zweite Rückgabewert ist der eigentliche Trick. Wird das Datum nicht
    herausgeschnitten, liest die Uhrzeitsuche danach aus "15.09.2026 14:30"
    die Zeit "15:09" - der Punkt gilt dort als Trenner zwischen Stunde und
    Minute. Genau so entstehen Termine, die scheinbar korrekt eingetragen
    sind und drei Stunden danebenliegen.
    """

    klein = text.lower().strip()

    def _ohne(treffer: re.Match) -> str:
        return (klein[: treffer.start()] + " " + klein[treffer.end():]).strip()

    if re.search(r"\bheute\b", klein):
        return heute, klein
    if re.search(r"\bmorgen\b", klein) and not re.search(r"\bmorgens\b", klein):
        return heute + timedelta(days=1), klein
    if re.search(r"\büber-?morgen\b|\bueber-?morgen\b", klein):
        return heute + timedelta(days=2), klein
    if re.search(r"\bgestern\b", klein):
        return heute - timedelta(days=1), klein

    # ISO: 2026-09-15
    treffer = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", klein)
    if treffer:
        try:
            gefunden = date(
                int(treffer.group(1)), int(treffer.group(2)), int(treffer.group(3))
            )
        except ValueError:
            return None, klein
        return gefunden, _ohne(treffer)

    # Deutsch: 15.09.2026 / 15.9.26 / 15.9.
    # Die Jahreszahl darf nicht in eine Uhrzeit hineingreifen - deshalb der
    # Blick auf das Zeichen danach: "3.2. 10:00" hat kein Jahr, sondern eine
    # Uhrzeit.
    treffer = re.search(r"\b(\d{1,2})\.\s*(\d{1,2})\.(?:\s*(\d{4}|\d{2})(?![:.\d]))?", klein)
    if treffer:
        tag, monat = int(treffer.group(1)), int(treffer.group(2))
        rohjahr = treffer.group(3)
        if rohjahr:
            jahr = int(rohjahr)
            jahr += 2000 if jahr < 100 else 0
        else:
            jahr = heute.year
        try:
            gefunden = date(jahr, monat, tag)
        except ValueError:
            return None, klein
        # Ohne Jahresangabe ist der naechste passende gemeint, nicht der
        # vergangene: Wer "am 3.2." sagt, meint im Dezember den kommenden.
        if not rohjahr and gefunden < heute:
            gefunden = date(jahr + 1, monat, tag)
        return gefunden, _ohne(treffer)

    # "15. September" / "15. Sept 2026"
    treffer = re.search(r"\b(\d{1,2})\.?\s+([a-zäöü]+)\.?(?:\s*(\d{4}))?", klein)
    if treffer:
        monatswort = treffer.group(2)
        monat = next(
            (nummer for name, nummer in _MONATE.items() if name.startswith(monatswort[:3])),
            None,
        )
        if monat is not None:
            tag = int(treffer.group(1))
            jahr = int(treffer.group(3)) if treffer.group(3) else heute.year
            try:
                gefunden = date(jahr, monat, tag)
            except ValueError:
                return None, klein
            if not treffer.group(3) and gefunden < heute:
                gefunden = date(jahr + 1, monat, tag)
            return gefunden, _ohne(treffer)

    # Wochentage: immer der KOMMENDE, auch ohne "nächsten".
    for name, nummer in _WOCHENTAGE.items():
        treffer = re.search(rf"\b{name}\b", klein)
        if treffer:
            vorwaerts = (nummer - heute.weekday()) % 7
            if vorwaerts == 0:
                vorwaerts = 7 if re.search(r"\bn(ä|ae)chste", klein) else 0
            return heute + timedelta(days=vorwaerts), _ohne(treffer)

    return None, klein


def _verschiebung_lesen(text: str, jetzt: datetime) -> datetime | None:
    """Liest 'in 2 Stunden', 'in einer Woche' und Ähnliches."""

    treffer = re.search(
        r"\bin\s+(\d+|ein(?:e[rn]?)?|zwei|drei|vier|fünf|fuenf|sechs|sieben|acht|neun|zehn|elf|zwölf|zwoelf)"
        r"\s*(minute|minuten|stunde|stunden|tag|tagen|woche|wochen|monat|monaten)\b",
        text.lower(),
    )
    if not treffer:
        return None

    menge = _als_zahl(treffer.group(1)) or _ZAHLWOERTER.get(treffer.group(1))
    if menge is None:
        return None

    einheit = treffer.group(2)
    if einheit.startswith("minute"):
        return jetzt + timedelta(minutes=menge)
    if einheit.startswith("stunde"):
        return jetzt + timedelta(hours=menge)
    if einheit.startswith("tag"):
        return jetzt + timedelta(days=menge)
    if einheit.startswith("woche"):
        return jetzt + timedelta(weeks=menge)
    return jetzt + timedelta(days=30 * menge)


def zeit_lesen(
    text: str,
    *,
    jetzt: datetime | None = None,
    standard_stunde: int = 9,
) -> tuple[datetime, bool]:
    """Liest eine Zeitangabe.

    Args:
        text: Was gesagt oder geschrieben wurde.
        jetzt: Die Gegenwart - im Test setzbar.
        standard_stunde: Welche Uhrzeit gilt, wenn nur ein Datum genannt
            wurde und der Termin trotzdem eine Uhrzeit braucht.

    Returns:
        Den Zeitpunkt mit Zeitzone und ob es ein ganztägiger Termin ist
        (also ob eine Uhrzeit fehlte).

    Raises:
        ZeitFehler: Wenn nichts Eindeutiges darin steht.
    """

    roh = " ".join(str(text or "").split())
    if not roh:
        raise ZeitFehler("Es fehlt die Zeitangabe.")

    jetzt = _ortszeit(jetzt)

    # Vollstaendiges ISO mit Zone - das kommt aus der API zurueck und soll
    # unveraendert wieder hineingehen.
    try:
        gelesen = datetime.fromisoformat(roh.replace("Z", "+00:00"))
        if gelesen.tzinfo is None:
            gelesen = gelesen.replace(tzinfo=jetzt.tzinfo)
        ganztags = len(roh) <= 10 and "T" not in roh
        return gelesen, ganztags
    except ValueError:
        pass

    verschoben = _verschiebung_lesen(roh, jetzt)
    if verschoben is not None:
        return verschoben, False

    tag, ohne_datum = _datum_lesen(roh, jetzt.date())
    uhrzeit = _uhrzeit_lesen(ohne_datum)

    if tag is None and uhrzeit is None:
        raise ZeitFehler(
            f"Aus '{roh}' ist keine eindeutige Zeit zu lesen. Bitte Datum und "
            f"Uhrzeit nennen, zum Beispiel '15.09.2026 14:30'."
        )

    if tag is None:
        # Nur eine Uhrzeit: heute, wenn sie noch kommt - sonst morgen.
        tag = jetzt.date()
        vorlaeufig = datetime.combine(tag, jetzt.time()).replace(
            hour=uhrzeit[0], minute=uhrzeit[1], second=0, microsecond=0,
            tzinfo=jetzt.tzinfo,
        )
        if vorlaeufig <= jetzt:
            tag = tag + timedelta(days=1)

    if uhrzeit is None:
        return (
            datetime(tag.year, tag.month, tag.day, standard_stunde, 0,
                     tzinfo=jetzt.tzinfo),
            True,
        )

    return (
        datetime(tag.year, tag.month, tag.day, uhrzeit[0], uhrzeit[1],
                 tzinfo=jetzt.tzinfo),
        False,
    )


def dauer_lesen(text: str, standard_minuten: int = 60) -> int:
    """Liest eine Dauer in Minuten: '90 Minuten', '1,5 Stunden', 'zwei Stunden'."""

    klein = " ".join(str(text or "").split()).lower()
    if not klein:
        return standard_minuten

    treffer = re.search(r"(\d+(?:[.,]\d+)?)\s*(minute|minuten|min|stunde|stunden|std|h)\b", klein)
    if treffer:
        menge = float(treffer.group(1).replace(",", "."))
        return max(1, int(round(menge * (60 if treffer.group(2)[0] in "sh" else 1))))

    treffer = re.search(
        r"\b(ein|eine|zwei|drei|vier|fünf|fuenf|sechs)\s*(stunde|stunden|minute|minuten)\b",
        klein,
    )
    if treffer:
        menge = _ZAHLWOERTER.get(treffer.group(1), 1)
        return menge * (60 if treffer.group(2).startswith("stunde") else 1)

    treffer = re.search(r"^\s*(\d+)\s*$", klein)
    if treffer:
        return max(1, int(treffer.group(1)))

    return standard_minuten
