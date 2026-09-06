"""Eine Landkarte des Wissens - kein Studienplan.

## Die Korrektur, aus der diese Datei entstand

Zuerst stand hier ein Studienplan: Module in Semestern, eine feste
Reihenfolge, Prüffragen auf drei Stufen. Der Benutzer hat das zurück-
gewiesen, und er hatte recht::

    "Ich will nicht ein zeitlich eingeschränktes Studium machen, es geht
     mir darum, das Wissen auch wirklich mir anzueignen. Wie lange ich
     für welches Thema benötige ist unerheblich."

Ein Semesterplan beantwortet eine Frage, die sich hier nicht stellt -
nämlich wie man ein Pensum in eine Frist bringt. Das ist die Frage einer
Prüfungsordnung, nicht die eines Lernenden. Wer etwas wirklich verstehen
will, braucht keinen Zeitplan, sondern eine Orientierung: Wo bin ich,
was hängt womit zusammen, und was fehlt mir noch, um das da drüben zu
verstehen?

## Was eine Landkarte anders macht als ein Plan

Ein Plan sagt: erst das, dann das. Eine Landkarte sagt: von hier kommt
man dorthin, und dieser Weg führt über jenen Punkt. Der Unterschied ist
nicht Wortklauberei - er entscheidet, wer die Richtung bestimmt.

* **Keine Semester.** Nichts hier weiss, wie lange etwas dauert.
* **Aber Abhängigkeiten.** Sie sind keine Vorschrift, sondern eine
  Tatsache über die Sache selbst: Man kann das Morphem nicht bestimmen,
  ohne das Phonem zu kennen. Wer trotzdem dort anfangen will, darf das -
  der Orb sagt dann, was ihm dabei fehlen wird, statt es zu verbieten.
* **Keine Prüffragen, sondern Gesprächsanlässe.** Fragen stehen hier
  nicht, um abgefragt zu werden, sondern weil sie gute Fragen sind: Sie
  bringen ein Gespräch an die Stelle, an der sich zeigt, ob jemand die
  Sache durchschaut hat.
* **Interessen zählen.** Die Landkarte kennt Querverbindungen zwischen
  Gebieten, und wer sich für Latein interessiert, kommt über den Kasus
  auch zur deutschen Grammatik. Ein Semesterplan hätte ihn stattdessen
  ins vierte Semester verwiesen.

## Was von den Stufen bleibt

Die drei Tiefen - kennen, anwenden, beurteilen - bleiben, aber sie sind
keine Leiter mehr, die man hochsteigt. Sie beschreiben, wie tief ein
Gespräch über eine Sache gerade geht, und der Orb liest das am Gesagten
ab statt es abzufragen. Wer fragt "was heisst Morphem", steht anderswo
als wer fragt "warum scheitert der Morphembegriff beim Ablaut" - und
beides ist derselben Person an verschiedenen Tagen möglich.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

#: Wie tief ein Gespräch über eine Sache geht. Keine Leiter, sondern eine
#: Beschreibung: Woran man merkt, worüber gerade gesprochen wird.
TIEFEN: tuple[str, ...] = ("kennen", "anwenden", "beurteilen")

TIEFEN_KLARTEXT: dict[str, str] = {
    "kennen": "Was ist das, wie heisst das, wo gehört das hin",
    "anwenden": "An einem Fall zeigen, analysieren, selbst machen",
    "beurteilen": "Grenzen sehen, Positionen abwägen, Forschung einordnen",
}


class LandkarteFehler(ValueError):
    """Eine Landkarte verweist auf etwas, das es nicht gibt."""


@dataclass(frozen=True, slots=True)
class Anlass:
    """Eine Frage, die ein Gespräch an die richtige Stelle bringt.

    Ausdrücklich KEINE Prüfungsfrage. Der Benutzer hat auch das
    zurückgewiesen: „Der Orb soll auch nicht einfach plump irgendwelche
    Tests mit mir machen." Diese Fragen stellt man, weil sie das Gespräch
    weiterbringen - und was sie über den Stand des Gegenübers verraten,
    ist ein Nebenertrag, kein Zweck.

    ``woran_man_es_merkt`` sagt deshalb nicht „richtige Antwort", sondern
    was eine Antwort zeigt, wenn die Sache durchschaut ist.
    """

    frage: str
    tiefe: str
    woran_man_es_merkt: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.tiefe not in TIEFEN:
            raise LandkarteFehler(
                f"Unbekannte Tiefe {self.tiefe!r} bei {self.frage!r}. "
                f"Erlaubt: {', '.join(TIEFEN)}."
            )


@dataclass(frozen=True, slots=True)
class Thema:
    """Ein Punkt auf der Landkarte."""

    kennung: str
    titel: str
    #: Worum es geht. Der Text, aus dem der Orb entwickelt, was er sagt.
    abriss: str
    #: Was man versteht, wenn man es verstanden hat.
    worum_es_geht: tuple[str, ...] = ()
    #: Kennungen von Themen, die man dafür braucht. Keine Vorschrift -
    #: eine Tatsache über die Sache. Wer trotzdem hier einsteigt, bekommt
    #: gesagt, was ihm fehlen wird.
    baut_auf: tuple[str, ...] = ()
    #: Wohin es von hier aus weitergeht - für den, der Lust bekommt.
    fuehrt_zu: tuple[str, ...] = ()
    anlaesse: tuple[Anlass, ...] = ()
    begriffe: tuple[str, ...] = ()
    literatur: tuple[str, ...] = ()
    #: Ob und womit sich hier etwas ZEIGEN lässt. Leer heisst: Dieses
    #: Thema lebt vom Argument, nicht vom Bild - und dann ist eine Folie
    #: Beiwerk. Siehe :mod:`backend.studium.zeigen`.
    zeigenswert: tuple[str, ...] = ()

    def anlaesse_der_tiefe(self, tiefe: str) -> tuple[Anlass, ...]:
        return tuple(a for a in self.anlaesse if a.tiefe == tiefe)


@dataclass(frozen=True, slots=True)
class Gebiet:
    """Ein Gebiet der Landkarte - eine Gegend, kein Modul."""

    kennung: str
    titel: str
    beschreibung: str
    themen: tuple[Thema, ...]

    def thema(self, kennung: str) -> Thema | None:
        for t in self.themen:
            if t.kennung == kennung:
                return t
        return None


@dataclass(frozen=True, slots=True)
class Feld:
    """Ein Fachgebiet als Ganzes."""

    kennung: str
    titel: str
    gegenstand: str
    methode: str
    aufgaben: tuple[str, ...]
    gebiete: tuple[Gebiet, ...]
    nachbarn: tuple[str, ...] = ()
    #: Womit man einsteigen kann, ohne etwas vorauszusetzen. Mehrere -
    #: denn es gibt mehr als einen Anfang, und welcher passt, hängt am
    #: Interesse und nicht an einer Ordnung.
    einstiege: tuple[str, ...] = ()

    # --- Zugriff ------------------------------------------------------------

    def alle_themen(self) -> tuple[Thema, ...]:
        return tuple(t for g in self.gebiete for t in g.themen)

    def thema(self, kennung: str) -> Thema | None:
        for t in self.alle_themen():
            if t.kennung == kennung:
                return t
        return None

    def gebiet(self, kennung: str) -> Gebiet | None:
        for g in self.gebiete:
            if g.kennung == kennung:
                return g
        return None

    def gebiet_von(self, thema_kennung: str) -> Gebiet | None:
        for g in self.gebiete:
            if g.thema(thema_kennung) is not None:
                return g
        return None

    def was_fehlt(self, thema_kennung: str, bekannt: Iterable[str]) -> tuple[str, ...]:
        """Was man für ein Thema braucht und noch nicht berührt hat.

        Rekursiv, denn Voraussetzungen haben selbst welche. Das Ergebnis
        ist eine Auskunft, kein Verbot: Der Orb sagt „dafür brauchst du
        eigentlich noch X" und fragt, ob man das kurz mitnehmen will.
        """

        gesehen = set(bekannt)
        fehlend: list[str] = []
        offen = [thema_kennung]
        besucht: set[str] = set()
        while offen:
            aktuell = offen.pop()
            if aktuell in besucht:
                continue
            besucht.add(aktuell)
            thema = self.thema(aktuell)
            if thema is None:
                continue
            for vorher in thema.baut_auf:
                if vorher not in gesehen and vorher not in fehlend:
                    fehlend.append(vorher)
                offen.append(vorher)
        return tuple(fehlend)

    def nachbarschaft(self, thema_kennung: str) -> dict[str, tuple[str, ...]]:
        """Was rund um ein Thema liegt - zurück, vorwärts, nebenan."""

        thema = self.thema(thema_kennung)
        if thema is None:
            return {}
        weiter = list(thema.fuehrt_zu)
        for anderes in self.alle_themen():
            if thema_kennung in anderes.baut_auf and anderes.kennung not in weiter:
                weiter.append(anderes.kennung)
        gebiet = self.gebiet_von(thema_kennung)
        nebenan = tuple(
            t.kennung for t in (gebiet.themen if gebiet else ()) if t.kennung != thema_kennung
        )
        return {"baut_auf": thema.baut_auf, "fuehrt_zu": tuple(weiter), "nebenan": nebenan}

    def umfang(self) -> dict[str, int]:
        themen = self.alle_themen()
        return {
            "gebiete": len(self.gebiete),
            "themen": len(themen),
            "anlaesse": sum(len(t.anlaesse) for t in themen),
            "begriffe": sum(len(t.begriffe) for t in themen),
        }

    # --- Selbstprüfung ------------------------------------------------------

    def pruefen(self) -> list[str]:
        """Sucht Widersprüche - Verweise ins Leere und Ringschlüsse."""

        klagen: list[str] = []
        alle = {t.kennung for t in self.alle_themen()}

        doppelt = _doppelte(t.kennung for t in self.alle_themen())
        klagen.extend(f"Themenkennung {k!r} kommt doppelt vor." for k in doppelt)

        for thema in self.alle_themen():
            if not thema.abriss.strip():
                klagen.append(f"Thema {thema.kennung!r} hat keinen Abriss.")
            if not thema.worum_es_geht:
                klagen.append(f"Thema {thema.kennung!r} sagt nicht, worum es geht.")
            if not thema.anlaesse:
                klagen.append(
                    f"Thema {thema.kennung!r} hat keinen einzigen Gesprächsanlass – "
                    "dann kommt der Orb dort nie ins Gespräch."
                )
            for verweis in (*thema.baut_auf, *thema.fuehrt_zu):
                if verweis not in alle:
                    klagen.append(
                        f"Thema {thema.kennung!r} verweist auf {verweis!r}, "
                        "das es hier nicht gibt."
                    )

        for einstieg in self.einstiege:
            if einstieg not in alle:
                klagen.append(f"Einstieg {einstieg!r} ist kein Thema dieses Felds.")
            else:
                thema = self.thema(einstieg)
                if thema is not None and thema.baut_auf:
                    klagen.append(
                        f"Einstieg {einstieg!r} setzt selbst etwas voraus "
                        f"({', '.join(thema.baut_auf)}) – dann ist es keiner."
                    )

        klagen.extend(self._ringschluesse())
        return klagen

    def _ringschluesse(self) -> list[str]:
        """Findet Themen, die sich im Kreis voraussetzen.

        Ein Ring wäre für den Lernenden eine Sackgasse: Für A braucht man
        B und für B wieder A - er käme nirgends hinein.
        """

        klagen: list[str] = []
        farbe: dict[str, int] = {}

        def gehen(kennung: str, pfad: list[str]) -> None:
            farbe[kennung] = 1
            thema = self.thema(kennung)
            for vorher in (thema.baut_auf if thema else ()):
                if farbe.get(vorher) == 1:
                    ring = " → ".join([*pfad, kennung, vorher])
                    klagen.append(f"Ringschluss: {ring}")
                elif farbe.get(vorher, 0) == 0:
                    gehen(vorher, [*pfad, kennung])
            farbe[kennung] = 2

        for thema in self.alle_themen():
            if farbe.get(thema.kennung, 0) == 0:
                gehen(thema.kennung, [])
        return klagen


def _doppelte(kennungen: Iterable[str]) -> list[str]:
    gesehen: set[str] = set()
    doppelt: list[str] = []
    for k in kennungen:
        if k in gesehen and k not in doppelt:
            doppelt.append(k)
        gesehen.add(k)
    return doppelt


# ---------------------------------------------------------------------------
#  Das Verzeichnis
# ---------------------------------------------------------------------------

_FELDER: dict[str, Feld] = {}


def eintragen(feld: Feld) -> Feld:
    """Nimmt ein Feld auf - nach Prüfung."""

    klagen = feld.pruefen()
    if klagen:
        raise LandkarteFehler(
            f"Die Landkarte {feld.kennung!r} ist nicht stimmig:\n- "
            + "\n- ".join(klagen)
        )
    _FELDER[feld.kennung] = feld
    return feld


def felder() -> tuple[Feld, ...]:
    _laden()
    return tuple(_FELDER[k] for k in sorted(_FELDER))


def feld(kennung: str) -> Feld | None:
    _laden()
    return _FELDER.get(kennung)


def feld_suchen(text: str) -> Feld | None:
    """Findet das Feld, von dem eine Äusserung handelt."""

    _laden()
    knapp = " " + " ".join(str(text or "").lower().split()) + " "
    if not knapp.strip():
        return None
    aliases = {
        " linguistik ": "sprachwissenschaft",
        " allgemeine sprachwissenschaft ": "sprachwissenschaft",
        " literaturwissenschaft ": "germanistik",
        " deutsche literatur ": "germanistik",
        " ökonomie ": "wirtschaft",
        " oekonomie ": "wirtschaft",
        " volkswirtschaft ": "wirtschaft",
        " vwl ": "wirtschaft",
        " betriebswirtschaft ": "wirtschaft",
        " bwl ": "wirtschaft",
    }
    for alias, kennung in aliases.items():
        if alias in knapp:
            return _FELDER.get(kennung)
    for f in felder():
        if f.kennung in knapp or f" {f.titel.lower()} " in knapp:
            return f
    for f in felder():
        for g in f.gebiete:
            if g.titel.lower() in knapp:
                return f
    for f in felder():
        for t in f.alle_themen():
            if t.titel.lower() in knapp:
                return f
    return None


def thema_suchen(text: str) -> tuple[Feld, Thema] | None:
    """Findet das Thema, von dem eine Äusserung handelt.

    Zuerst über den Titel, dann über die Fachbegriffe: Wer „Affrikate"
    sagt, meint die Lautverschiebung, auch wenn er sie nicht nennt. Das
    längste Zutreffende gewinnt.
    """

    _laden()
    knapp = " " + " ".join(str(text or "").lower().split()) + " "
    if not knapp.strip():
        return None

    beste: tuple[Feld, Thema] | None = None
    gewicht = 0
    for f in felder():
        for t in f.alle_themen():
            titel = t.titel.lower()
            if titel in knapp and len(titel) > gewicht:
                beste, gewicht = (f, t), len(titel)
    if beste is not None:
        return beste

    for f in felder():
        for t in f.alle_themen():
            for begriff in t.begriffe:
                b = begriff.lower()
                if len(b) <= gewicht:
                    continue
                # Ab fuenf Zeichen genuegt der Wortanfang - so trifft
                # "Flexionsendung" den Begriff "Flexion". Kuerzere Begriffe
                # ("Kant", "Hume") zaehlen nur als GANZES Wort: "kant" als
                # Anfang traefe sonst auch die Kantone.
                if len(b) >= 5 and f" {b}" in knapp:
                    beste, gewicht = (f, t), len(b)
                elif len(b) == 4 and f" {b} " in knapp:
                    beste, gewicht = (f, t), len(b)
    return beste


_geladen = False


def _laden() -> None:
    global _geladen
    if _geladen:
        return
    _geladen = True
    from backend.studium.fachplaene import alle_eintragen  # noqa: PLC0415

    alle_eintragen()
