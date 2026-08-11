"""Zerlegt eine entstehende Antwort in sprechbare Sätze.

Der Orb bekommt seine Antwort inzwischen stückweise, während sie entsteht.
Damit kann er anfangen zu reden, lange bevor der letzte Satz gedacht ist –
das ist der Unterschied zwischen „er antwortet nach fünf Sekunden" und
„nach anderthalb", obwohl das Denken gleich lange dauert.

Zwei Dinge stehen dem im Weg, und beide löst dieses Modul:

Erstens kommen die Stücke nicht als Sätze. Mal ist es ein Wort, mal eine
Silbe. Wer sie einzeln vorliest, klingt wie ein kaputtes Radio. Gesprochen
wird deshalb erst, wenn ein Satz vollständig beisammen ist.

Zweitens ruft das Modell mitten in der Antwort Werkzeuge auf – als
eingezäunter Block (```werkzeug … ```). Der darf unter keinen Umständen
vorgelesen werden: Er ist Maschinensprache und dauerte vorgelesen länger
als die Antwort selbst. Was innerhalb eines Zauns steht, wird hier
zurückgehalten; alles davor und danach ist gewöhnlicher Text.

Das Zurückhalten ist bewusst vorsichtig: Sobald ein Backtick auftaucht,
wartet das Modul ab, bis klar ist, ob daraus ein Zaun wird. Lieber einen
Sekundenbruchteil später sprechen als einmal ``` vorlesen.
"""

from __future__ import annotations

import re

#: Ein Satz endet an einem dieser Zeichen, gefolgt von Leerraum.
#:
#: Der Doppelpunkt steht bewusst nicht dabei: „Es gibt drei Gründe:" ist
#: kein Satz, den man allein stehen lassen möchte.
_SENTENCE_END = re.compile(r"[.!?…]+[\"'»)\]]*(\s|$)")

#: Abkürzungen, nach deren Punkt der Satz weitergeht.
#:
#: Ohne diese Liste zerfiele „Der Vertrag von 1815 bzw. der Wiener
#: Kongress" in zwei Bruchstücke, und der Orb legte mitten im Gedanken eine
#: Sprechpause ein.
_ABBREVIATIONS: frozenset[str] = frozenset(
    {
        "bzw",
        "ca",
        "d.h",
        "dr",
        "etc",
        "evtl",
        "ggf",
        "inkl",
        "jh",
        "nr",
        "prof",
        "sog",
        "st",
        "u.a",
        "usw",
        "v.a",
        "vgl",
        "z.b",
        "zzgl",
    }
)

#: Der Zaun, in dem Werkzeugaufrufe stehen.
_FENCE = "```"

#: So viele Zeichen dürfen am Ende offen bleiben, während auf die
#: Entscheidung „Zaun oder nicht" gewartet wird.
_FENCE_LOOKAHEAD = len(_FENCE)


class SpeechStream:
    """Sammelt Antwortstücke und gibt fertige Sätze zum Sprechen frei.

    Benutzung::

        strom = SpeechStream()
        for stueck in antwort_stuecke:
            for satz in strom.feed(stueck):
                await sprich(satz)
        for satz in strom.finish():
            await sprich(satz)

    Der Strom merkt sich in :attr:`spoken`, was er freigegeben hat. Damit
    lässt sich hinterher feststellen, was noch nachzusprechen ist – etwa
    wenn nach einem Werkzeugaufruf eine neue Antwort entstanden ist.
    """

    def __init__(self) -> None:
        #: Noch nicht freigegebener Text außerhalb eines Zauns.
        self._buffer = ""
        #: Ob wir uns gerade innerhalb eines Zauns befinden.
        self._inside_fence = False
        #: Alles, was der Zaun verschluckt hat – für die Nachschau.
        self._swallowed = ""
        #: Was bereits zum Sprechen freigegeben wurde.
        self.spoken = ""

    # --- Füttern ----------------------------------------------------------------

    def feed(self, piece: str) -> list[str]:
        """Nimmt ein Stück entgegen und gibt fertige Sätze zurück."""

        if not piece:
            return []

        self._buffer += piece
        return self._harvest(final=False)

    def finish(self) -> list[str]:
        """Gibt frei, was am Ende übrig ist – auch ohne Satzzeichen.

        Eine Antwort endet nicht immer mit einem Punkt. Was hier liegen
        bliebe, würde nie gesprochen.
        """

        saetze = self._harvest(final=True)
        rest = self._buffer.strip()
        self._buffer = ""
        if rest and not self._inside_fence:
            if _ist_maschinensprache(rest):
                self._swallowed += rest
            else:
                saetze.append(rest)
                self._merken(rest)
        return saetze

    # --- Innenleben --------------------------------------------------------------

    def _harvest(self, *, final: bool) -> list[str]:
        """Arbeitet den Puffer ab, bis nichts Sprechbares mehr darin ist."""

        saetze: list[str] = []

        while True:
            if self._inside_fence:
                ende = self._buffer.find(_FENCE)
                if ende < 0:
                    # Der Zaun ist noch offen: alles gehört ihm – bis auf
                    # ein paar Zeichen am Ende, die der Anfang des
                    # schliessenden Zauns sein könnten. Würden die
                    # mitverschluckt, käme der Zaun nie zusammen, und der
                    # Orb bliebe für den Rest der Antwort stumm.
                    offen = 0 if final else self._angefangener_zaun()
                    if offen:
                        self._swallowed += self._buffer[:-offen]
                        self._buffer = self._buffer[-offen:]
                    else:
                        self._swallowed += self._buffer
                        self._buffer = ""
                    return saetze
                self._swallowed += self._buffer[:ende]
                self._buffer = self._buffer[ende + len(_FENCE) :]
                self._inside_fence = False
                continue

            beginn = self._buffer.find(_FENCE)
            if beginn >= 0:
                # Vor dem Zaun steht gewöhnlicher Text – der darf gesprochen
                # werden, sobald er einen Satz ergibt.
                davor, self._buffer = self._buffer[:beginn], self._buffer[beginn + len(_FENCE) :]
                saetze.extend(self._saetze_aus(davor, final=True))
                self._inside_fence = True
                continue

            # Kein Zaun in Sicht. Ein angefangener Backtick am Ende könnte
            # aber der Anfang eines Zauns sein – so lange wird gewartet.
            offen = self._angefangener_zaun()
            if offen and not final:
                sicher = self._buffer[: len(self._buffer) - offen]
                gefunden, rest = self._teilen(sicher)
                saetze.extend(gefunden)
                self._buffer = rest + self._buffer[len(self._buffer) - offen :]
                return saetze

            gefunden, self._buffer = self._teilen(self._buffer)
            saetze.extend(gefunden)
            return saetze

    def _angefangener_zaun(self) -> int:
        """Wie viele Zeichen am Ende der Anfang eines Zauns sein könnten."""

        for laenge in range(min(_FENCE_LOOKAHEAD - 1, len(self._buffer)), 0, -1):
            if self._buffer.endswith(_FENCE[:laenge]):
                return laenge
        return 0

    def _saetze_aus(self, text: str, *, final: bool) -> list[str]:
        """Zerlegt einen abgeschlossenen Abschnitt vollständig."""

        gefunden, rest = self._teilen(text)
        if final:
            rest = rest.strip()
            if rest:
                gefunden.append(rest)
                self._merken(rest)
        else:
            self._buffer = rest + self._buffer
        return gefunden

    def _teilen(self, text: str) -> tuple[list[str], str]:
        """Trennt fertige Sätze vom noch unfertigen Rest."""

        saetze: list[str] = []
        position = 0

        for treffer in _SENTENCE_END.finditer(text):
            ende = treffer.end()
            kandidat = text[position:ende].strip()
            if not kandidat:
                position = ende
                continue
            if _endet_auf_abkuerzung(kandidat):
                continue
            if _ist_maschinensprache(kandidat):
                # Nicht sprechen, aber auch nicht verlieren: Der Aufruf
                # wird spaeter aus dem Gesamttext gelesen und ausgefuehrt.
                #
                # Noetig, seit ein Werkzeugaufruf auch OHNE Zaeunung
                # erkannt wird. Der Zaun hielt bisher alles zurueck; ein
                # nacktes JSON-Gebilde liefe ohne diese Zeile geradewegs in
                # die Sprachausgabe, und der Benutzer hoerte geschweifte
                # Klammern vorgelesen.
                self._swallowed += kandidat
                position = ende
                continue
            saetze.append(kandidat)
            self._merken(kandidat)
            position = ende

        return saetze, text[position:]

    def _merken(self, satz: str) -> None:
        self.spoken = f"{self.spoken} {satz}".strip() if self.spoken else satz

    # --- Nachschau ---------------------------------------------------------------

    @property
    def had_tool_call(self) -> bool:
        """Ob unterwegs ein Werkzeugblock aufgetaucht ist."""

        return bool(self._swallowed.strip()) or self._inside_fence


def _ist_maschinensprache(text: str) -> bool:
    """Ob ein Abschnitt ein Werkzeugaufruf ist statt eines Satzes.

    Bewusst eng: Nur was mit einer geschweiften Klammer beginnt UND einen
    Aufrufschluessel traegt, gilt als Maschinensprache. Ein Satz, in dem
    das Wort "Werkzeug" vorkommt, soll weiterhin gesprochen werden.
    """

    knapp = text.strip()
    if not knapp.startswith("{"):
        return False
    return '"werkzeug"' in knapp or '"tool"' in knapp


def _endet_auf_abkuerzung(text: str) -> bool:
    """Ob der Satz auf einer Abkürzung endet statt auf einem Satzende."""

    if not text.endswith("."):
        return False
    letztes = text[:-1].rsplit(" ", 1)[-1].lower()
    return letztes in _ABBREVIATIONS


def remaining_after(gesprochen: str, ganz: str) -> str:
    """Was von ``ganz`` noch zu sprechen ist, wenn ``gesprochen`` schon lief.

    Nach einem Werkzeugaufruf entsteht meist eine ganz neue Antwort – dann
    steht das bereits Gesprochene nicht mehr vorn, und es muss alles
    gesprochen werden. Ist es hingegen derselbe Text, bleibt nur der
    Schluss übrig.

    Verglichen wird über den Leerraum hinweg: Beim Sprechen fallen Umbrüche
    und doppelte Leerzeichen weg, und daran soll der Vergleich nicht
    scheitern.
    """

    ganz = (ganz or "").strip()
    gesprochen = (gesprochen or "").strip()
    if not gesprochen:
        return ganz
    if not ganz:
        return ""

    a = _normiert(gesprochen)
    b = _normiert(ganz)
    if not b.startswith(a):
        return ganz

    # Die Stelle im Originaltext finden, die dem normierten Präfix
    # entspricht – Zeichen für Zeichen, damit die Umbrüche nichts
    # verschieben.
    gezaehlt = 0
    for index, zeichen in enumerate(ganz):
        if not zeichen.isspace():
            gezaehlt += 1
        elif index > 0 and ganz[index - 1].isspace():
            continue
        else:
            gezaehlt += 1
        if gezaehlt >= len(a):
            return ganz[index + 1 :].strip()
    return ""


def _normiert(text: str) -> str:
    return " ".join(text.split())
