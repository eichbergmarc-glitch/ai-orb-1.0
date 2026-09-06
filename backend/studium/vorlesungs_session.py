"""Zustand und Ablauf einer fortlaufenden gesprochenen Vorlesung.

Eine Vorlesung ist kein einzelner Gespraechszug. Das Sprachmodell kann zwar
sagen, es werde nach einer Pause fortfahren, aber ohne einen technischen
Folgeauftrag endet der Ablauf mit genau diesem Satz. Diese kleine
Zustandsmaschine macht das Versprechen zu einem echten Ablauf:

* Start und Fortsetzung werden eindeutig erkannt,
* jeder Abschnitt bekommt einen nummerierten, zusammenhaengenden Auftrag,
* der Fortschritt ueberlebt einen Neustart,
* eine Wortmeldung des Benutzers pausiert den Ablauf sofort.

Das Modul erzeugt selbst keine Modellanfragen und keine Zeitgeber. Dadurch
bleibt es unabhaengig von Mikrofon und Provider und laesst sich vollstaendig
testen. Die Sprachpipeline uebernimmt lediglich das Warten und Sprechen.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from backend.system.logging_setup import get_logger
from backend.utils.paths import get_data_dir

logger = get_logger(__name__)

VORLESUNGS_MARKER = "[AI-ORB:VORLESUNG]"

_VIER_URSACHEN_ERGAENZUNGEN: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"\b(?:materialursache|materiale\s+ursache|causa\s+materialis)\b", re.I),
        "Die Materialursache bezeichnet den Stoff, aus dem etwas besteht.",
    ),
    (
        re.compile(r"\b(?:formursache|formale\s+ursache|causa\s+formalis)\b", re.I),
        "Die Formursache bezeichnet Gestalt und Wesensform eines Dinges.",
    ),
    (
        re.compile(r"\b(?:wirkursache|wirkende\s+ursache|causa\s+efficiens)\b", re.I),
        "Die Wirkursache bezeichnet, wer oder was die Veränderung hervorbringt.",
    ),
    (
        re.compile(
            r"\b(?:zweckursache|zielursache|finalursache|finale\s+ursache|"
            r"causa\s+finalis)\b",
            re.I,
        ),
        "Die Zweck- oder Zielursache bezeichnet, wozu etwas entsteht oder dient – sein Telos.",
    ),
)


def ist_vorlesungssegment(text: str) -> bool:
    """Ob ``text`` ein interner Auftrag fuer einen Vorlesungsabschnitt ist."""

    return str(text or "").lstrip().startswith(VORLESUNGS_MARKER)


def lehrstoff_vervollstaendigen(antwort: str) -> str:
    """Schliesst eine angekuendigte feste Fachliste vor dem Folgezuege ab.

    Tokenlimits koennen einen Abschnitt exakt zwischen dem dritten und
    vierten Punkt abschneiden. Fuer die Vier-Ursachen-Lehre ist die Ordnung
    eindeutig und stabil; fehlende Glieder werden deshalb knapp ergaenzt,
    statt einen fachlich falschen Dreiersatz zu speichern und anzuzeigen.
    """

    text = str(antwort or "").strip()
    if not re.search(r"\bvier\s+ursachen\b", text, re.IGNORECASE):
        return text
    fehlend = [
        ergaenzung
        for muster, ergaenzung in _VIER_URSACHEN_ERGAENZUNGEN
        if not muster.search(text)
    ]
    if not fehlend:
        return text
    uebergang = (
        "Der noch fehlende Punkt gehört vollständig dazu:"
        if len(fehlend) == 1
        else "Für die vollständige Viererordnung fehlen noch diese Punkte:"
    )
    return f"{text} {uebergang} {' '.join(fehlend)}"


def _normalisieren(text: str) -> str:
    return " ".join(
        str(text or "")
        .lower()
        .replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
        .replace("ß", "ss")
        .strip(" .,!?:;")
        .split()
    )


def _enthaelt_vorlesungswort(text: str) -> bool:
    """Erkennt auch typische Whisper-Varianten von ``Vorlesung``."""

    worte = re.findall(r"[a-z0-9]+", text)
    return any(
        stamm in wort
        for wort in worte
        for stamm in ("vorles", "vorlaes", "vorlass", "vorleis")
    )


@dataclass(slots=True)
class VorlesungsStand:
    auftrag: str = ""
    thema: str = ""
    naechster_abschnitt: int = 1
    aktiv: bool = False
    pausiert: bool = False
    abgeschlossen: bool = False
    letzter_auszug: str = ""


class VorlesungsSession:
    """Persistente, vom Benutzer jederzeit unterbrechbare Vorlesung."""

    _UNBRAUCHBARE_ANTWORTEN = (
        "diese aktion kann nicht rückgängig gemacht werden",
        "diese aktion kann nicht rueckgaengig gemacht werden",
        "soll ich sie wirklich ausführen",
        "soll ich sie wirklich ausfuehren",
        "ich kann gerade kein sprachmodell erreichen",
        "dazu fällt mir gerade nichts ein",
        "dazu faellt mir gerade nichts ein",
        "da ist bei mir etwas schiefgegangen",
        "ich habe nicht erkannt, welches programm",
        "das tagebuch ist aufgeschlagen",
        "ich habe das tagebuch jetzt geöffnet",
        "ich habe das tagebuch jetzt geoeffnet",
        "der tagebucheintrag ist fertig und gespeichert",
    )

    _PAUSIEREN = (
        "pausiere die vorlesung", "vorlesung pausieren",
        "unterbrich die vorlesung", "vorlesung unterbrechen",
        "beende die vorlesung", "vorlesung beenden", "hoer mit der vorlesung auf",
        "stoppe die vorlesung", "stopp die vorlesung",
    )
    _START = (
        "vorlesung ueber", "vorlesung zu", "vorlesung zum",
        "vorlesung halten", "halte eine vorlesung", "halte mir eine vorlesung",
        "ganze vorlesung", "vollstaendige vorlesung", "vortrag ueber",
    )

    def __init__(self, path: Path | None = None, *, max_abschnitte: int = 24) -> None:
        self.path = path or (get_data_dir() / "vorlesung.json")
        self.max_abschnitte = max(1, int(max_abschnitte))
        self.stand = VorlesungsStand()
        #: Alle Vorlesungen, nach Fach getrennt.
        #:
        #: Bis zum 26.08.2026 gab es genau EINEN Stand in genau EINER
        #: Datei. Wer nach siebzehn Abschnitten Philosophie eine Vorlesung
        #: ueber Geschichte begann, ueberschrieb damit die Philosophie -
        #: lautlos, und der Fortschritt war weg. Ein spaeteres "Fahre fort"
        #: setzte dann die zuletzt gestartete fort, egal welche gemeint
        #: war. Genau das hat der Benutzer als Verwechslung von
        #: Philosophie und Geschichte gemeldet.
        self._alle: dict[str, VorlesungsStand] = {}
        self._aktiv_schluessel: str = ""
        #: Welches Fach der letzte Befehl ausdruecklich genannt hat.
        #: ``befehl()`` merkt es sich, ``fortsetzen()`` holt es ab - so
        #: bleiben die Aufrufstellen in der Sprachpipeline unveraendert.
        self._gewuenschtes_fach: str = ""
        self._laden()

    # --- Faecher auseinanderhalten ---------------------------------------

    @staticmethod
    def _schluessel(thema: str) -> str:
        """Der Ablageschluessel einer Vorlesung.

        Bewusst das normalisierte Thema selbst und keine kluge Zuordnung zu
        einer Fachliste. "Geschichte der Philosophie" enthaelt beide
        Faecher; jede Regel, die daraus eines waehlt, liegt in der Haelfte
        der Faelle falsch. Zwei verschieden benannte Vorlesungen bekommen
        deshalb zwei Plaetze - und das ist genau, was hier gebraucht wird.
        """

        knapp = _normalisieren(str(thema or ""))
        knapp = re.sub(r"^(?:die|der|das|den|dem)\s+", "", knapp)
        return " ".join(knapp.split())[:80] or "vorlesung"

    def _passenden_schluessel(self, genannt: str) -> str:
        """Sucht zu einem genannten Thema die vorhandene Vorlesung.

        Verglichen wird in beide Richtungen: "Geschichte" findet
        "geschichte der antike", und "Vorlesung ueber die Geschichte der
        Antike" findet "geschichte". Anders gesagt: Der Benutzer muss den
        Titel nicht wiederholen koennen.
        """

        gesucht = self._schluessel(genannt)
        if not gesucht:
            return ""
        if gesucht in self._alle:
            return gesucht
        for schluessel in self._alle:
            if gesucht in schluessel or schluessel in gesucht:
                return schluessel
        return ""

    def _wechseln(self, schluessel: str) -> None:
        """Macht die Vorlesung mit diesem Schluessel zur laufenden."""

        if not schluessel or schluessel not in self._alle:
            return
        self._aktiv_schluessel = schluessel
        self.stand = self._alle[schluessel]

    @property
    def faecher(self) -> list[str]:
        """Alle gespeicherten Vorlesungen - fuer Diagnose und Rueckfragen."""

        return sorted(self._alle)

    @property
    def aktiv(self) -> bool:
        return self.stand.aktiv and not self.stand.pausiert and not self.stand.abgeschlossen

    @property
    def vorhanden(self) -> bool:
        return bool(self.stand.auftrag)

    # --- Thema und Befehl: erneuerte Erkennung ----------------------------
    #
    # Warum das hier steht: Am 26.08.2026 sagte der Benutzer
    #
    #   "ich moechte gerne dass du mir die einfuehrungsvorlesung ueber die
    #    geschichtswissenschaft haeltst und zwar ueber das mittelalter"
    #
    # und in data/vorlesung.json landete als Thema
    #
    #   "die geschichtswissenschaft haeltst und zwar ueber das mittelalter"
    #
    # Drei Fehler auf einmal: das Verb "haeltst" blieb im Thema stehen, die
    # Einengung "und zwar ueber das Mittelalter" wurde nicht als solche
    # erkannt, und die Umlaute waren fort, weil die Erkennung auf dem
    # normalisierten Text arbeitete. Der Orb hielt daraufhin eine allgemeine
    # Einfuehrung in die Geschichtswissenschaft - er begann bei Aegypten,
    # nicht beim Mittelalter.
    #
    # Dazu kam: Von zwanzig natuerlich gesprochenen Auftraegen fuer eine NEUE
    # Vorlesung erkannte die alte Fassung zehn ueberhaupt nicht. Diese Saetze
    # liefen als gewoehnliche Frage weiter - mit dem alten Vorlesungsverlauf
    # im Gespraech. Das ist die Ursache von "er kann keine neue Vorlesung
    # beginnen, er knuepft einfach dort an wo er war".

    #: Ein Wort, das eine Vorlesung benennt - in der Schreibweise des
    #: Originaltextes, also mit Umlauten.
    _LEHRWORT = (
        r"(?:einf(?:\u00fc|ue)hrungs)?"
        r"(?:vorl(?:es|\u00e4s|aes|ass|eis)\w*|vortrag|seminar)"
    )

    _THEMA_MUSTER = re.compile(
        _LEHRWORT
        + r"\s+(?:\u00fcber|ueber|zu|zum|zur|in|betreffend)\s+"
        r"(?:dem\s+|das\s+)?(?:Thema\s+)?(.+)",
        re.IGNORECASE,
    )
    _THEMA_DOPPELPUNKT = re.compile(_LEHRWORT + r"\s*[:,-]\s*(.+)", re.IGNORECASE)
    _THEMA_STICHWORT = re.compile(r"\bThema\s*[:,]?\s+(.+)", re.IGNORECASE)
    _THEMA_LEHRVERB = re.compile(
        r"\b(?:doziere?|dozieren|referiere?|referieren|unterrichte?|unterrichten"
        r"|trag\w*\s+vor|lehre?)\b\s+(?:\u00fcber|ueber|zu|zum|zur)\s+(.+)",
        re.IGNORECASE,
    )

    #: "... als Vorlesung" am Satzende benennt die Form, nicht das Thema.
    _ALS_FORM = re.compile(
        r"\s+als\s+(?:einf(?:\u00fc|ue)hrungs)?"
        r"(?:vorl(?:es|\u00e4s|aes|ass|eis)\w*|vortrag|seminar)\s*$",
        re.IGNORECASE,
    )

    #: Verben und Floskeln der Bitte. Sie stehen im Deutschen gern hinter dem
    #: Thema ("... ueber Kant halten") oder mitten darin.
    _BITTWORT = re.compile(
        r"\b(?:h(?:\u00e4|ae)lt?st|h(?:\u00e4|ae)lst|halten|abhalten|abzuhalten"
        r"|halte|machst|machen|mache|mach|gibst|gib|gibt"
        r"|erz(?:\u00e4|ae)hlst|erz(?:\u00e4|ae)hlen|erz(?:\u00e4|ae)hl"
        r"|vortragen|vortr(?:\u00e4|ae)gst|referierst|referieren|dozierst"
        r"|dozieren|unterrichtest|unterrichten|bitte|f(?:\u00fc|ue)r\s+mich"
        r"|mir|uns|du)\b",
        re.IGNORECASE,
    )

    #: Wo der Satz das Thema noch einmal einengt.
    _EINENGUNG = re.compile(
        r"\b(?:und\s+zwar|speziell|insbesondere|genauer\s+gesagt"
        r"|n(?:\u00e4|ae)mlich|schwerpunktm(?:\u00e4|ae)ssig"
        r"|schwerpunktm(?:\u00e4|ae)\u00dfig|mit\s+schwerpunkt|konkret"
        r"|im\s+besonderen)\b"
        r"(?:\s+(?:\u00fcber|ueber|zu|zum|zur|auf|das|die|der))*\s*",
        re.IGNORECASE,
    )

    #: Ein neuer Hauptsatz beendet das Thema.
    _SATZENDE = re.compile(
        r"[.!?;]|\s+(?:damit|weil|denn|aber|sodass|so\s+dass)\b", re.IGNORECASE
    )
    _ARTIKEL = re.compile(
        r"^(?:die|der|das|den|dem|des|eine[nmrs]?|ein)\s+", re.IGNORECASE
    )

    #: Ausdrueckliche Ansage, dass etwas Neues beginnen soll. Sie schlaegt
    #: jede Fortsetzung - sonst knuepft der Orb an die alte Vorlesung an.
    _NEUANFANG = re.compile(
        r"\b(?:neue[nmrs]?|weitere[nmrs]?|andere[nmrs]?|naechste[nmrs]?"
        r"|noch\s+eine)\s+(?:\w+\s+){0,2}?"
        r"\w*(?:vorl(?:es|aes|ass|eis)\w*|vortrag|seminar)\b"
        r"|\bvon\s+vorne?\s+(?:anfangen|beginnen|starten)\b"
        r"|\bneues\s+thema\b"
    )

    #: Einem Lehrwort folgt in wenigen Woertern ein Thema. Das ist die Regel,
    #: die bisher fehlte: Wer ein Thema nennt, will eine neue Vorlesung.
    _THEMA_GENANNT = re.compile(
        r"\w*(?:vorl(?:es|aes|ass|eis)\w*|vortrag|seminar)\b"
        r"(?:\s+\w+){0,2}?\s+(?:ueber|zu|zum|zur|in|thema)\s+\w+"
    )
    _LEHRVERB_GENANNT = re.compile(
        r"\b(?:dozier\w*|referier\w*|unterricht\w*|lehr\w*|trag\w*\s+vor)\b"
        r"(?:\s+\w+){0,2}?\s+(?:ueber|zu|zum|zur)\s+\w+"
    )
    _LEHRWORT_MIT_WORT = re.compile(
        r"\w*(?:vorl(?:es|aes|ass|eis)\w*|vortrag|seminar)\b\s*[:,-]?\s*\w+"
    )

    #: Der Rahmen einer Bitte. Bewusst weit - Menschen sagen es auf zwanzig
    #: Arten, und jede nicht erkannte Art landet als gewoehnliche Frage im
    #: laufenden Vorlesungsgespraech.
    _BITTRAHMEN = re.compile(
        r"\b(?:ich\s+(?:moechte|will|haette|brauche|wuensche|bitte"
        r"|wuerde\s+gern)|kannst\s+du|koennen\s+sie|koenntest\s+du"
        r"|wuerdest\s+du|magst\s+du|lass\s+uns|lasst\s+uns"
        r"|wir\s+(?:machen|starten|beginnen|nehmen)|gib\s+mir|gib\s+mal"
        r"|halte?|haltst|haelst|haeltst|starte?|beginne?|fang|mach|mache"
        r"|erzaehl\w*|bitte|gestalte?|referiere|doziere|unterrichte"
        r"|bring\s+mir\s+bei)\b"
    )

    #: Getrennte Verben des Anhaltens: "halt die Vorlesung AN".
    _ANHALTEN_GETRENNT = re.compile(
        r"\b(?:halt|h(?:oe)?r|brich|brech)\w*\b(?:\s+\w+){0,4}\s+(?:an|auf|ab)\b"
    )
    _ANHALTEWORTE = (
        "stopp", "stop", "pause", "pausier", "beend", "unterbrich",
        "anhalt", "aufhoer", "abbrech", "schluss", "genug", "reicht",
    )

    #: Nackte Zurufe. Kurz, eindeutig, und nur bei vorhandener Vorlesung.
    _ZURUFE = frozenset({
        "weiter", "weiter bitte", "bitte weiter", "weiter gehts",
        "weiter im text", "weiter im stoff", "und weiter",
    })
    _STARTMARKER = (
        "halt", "beginn", "starte", "einfuehr", "komplett", "vollstaendig",
        "ganz ab", "bis ich", "ohne unterbrech", "durchgehend",
        "selbststaendig",
    )
    _FORT_LOSE = re.compile(
        r"\b(?:fahr\w*|mach\w*|setz\w*)\b(?:\s+\w+){0,7}\s+(?:fort|weiter)\b"
    )
    #: Wendungen der Fortsetzung. Gegenueber frueher um die Faelle ergaenzt,
    #: in denen das Verb am Satzende steht ("... die Vorlesung fortsetzen").
    _FORTSETZEN = (
        "fahre fort", "fahr fort", "mach weiter", "mache weiter",
        "fahre mit der vorlesung fort", "fahr mit der vorlesung fort",
        "weiter mit der vorlesung", "setze die vorlesung fort",
        "vorlesung fortsetzen", "halte die vorlesung weiter",
        "fortsetzen", "fortfahren", "weitermachen",
    )
    _WEITERREDEN = (
        "selbststaendig", "durchgehend", "ohne unterbrech",
        "nicht immer rueckfrag", "keine rueckfrag", "einfach weiter",
    )

    @classmethod
    def _saeubern(cls, teil: str) -> str:
        """Nimmt Artikel, Bittwoerter und Satzzeichen aus einem Themenstueck."""

        stueck = cls._BITTWORT.sub(" ", str(teil or ""))
        stueck = " ".join(stueck.split()).strip(" .,!?:;-\u2013\u2014")
        while True:
            gekuerzt = cls._ARTIKEL.sub("", stueck).strip()
            if gekuerzt == stueck:
                break
            stueck = gekuerzt
        return stueck

    @classmethod
    def _thema_aus(cls, text: str) -> str:
        """Das Thema einer Vorlesung aus dem gesprochenen Satz.

        Gearbeitet wird auf dem ORIGINALTEXT. Die frueher benutzte
        normalisierte Fassung machte aus "Franzoesische Revolution" ein
        "franzoesische revolution" - und genau dieser Text stand danach als
        Thema im Auftrag an das Sprachmodell.
        """

        roh = " ".join(str(text or "").split()).strip(" .")
        if not roh:
            return ""

        treffer = (
            cls._THEMA_MUSTER.search(roh)
            or cls._THEMA_DOPPELPUNKT.search(roh)
            or cls._THEMA_STICHWORT.search(roh)
            or cls._THEMA_LEHRVERB.search(roh)
        )
        if not treffer:
            return roh[:240]

        rest = cls._SATZENDE.split(treffer.group(1), maxsplit=1)[0]
        rest = cls._ALS_FORM.sub("", rest)

        teile = cls._EINENGUNG.split(rest, maxsplit=1)
        breit = cls._saeubern(teile[0])
        eng = cls._saeubern(teile[1]) if len(teile) > 1 else ""
        if eng:
            eng = eng[0].upper() + eng[1:]

        if breit and eng:
            thema = "%s, Schwerpunkt %s" % (breit, eng)
        else:
            thema = breit or eng
        if not thema:
            return roh[:240]
        return (thema[0].upper() + thema[1:])[:240]

    def befehl(self, text: str) -> str:
        """Liefert ``start``, ``fortsetzen``, ``pausieren`` oder ``""``.

        Die Reihenfolge traegt die ganze Bedeutung: Ein ausdrueckliches
        "neue Vorlesung" wird VOR jeder Fortsetzung geprueft, und eine
        Fortsetzung greift nur noch, wenn eine Vorlesung laeuft, das Wort
        Vorlesung faellt oder der Satz ein nackter Zuruf ist. "Fahre mit dem
        Programm fort" loeste vorher eine Vorlesung aus.
        """

        klein = _normalisieren(text)
        if not klein:
            return ""
        worte = klein.split()
        hat_lehrwort = bool(
            _enthaelt_vorlesungswort(klein)
            or re.search(r"\b(?:vortrag|seminar)\b", klein)
        )

        # --- 1. anhalten --------------------------------------------------
        if self.aktiv and klein in {"stop", "stopp", "halt", "pause", "pausieren"}:
            return "pausieren"
        if self.vorhanden and any(wendung in klein for wendung in self._PAUSIEREN):
            return "pausieren"
        if self.vorhanden and hat_lehrwort and self._ANHALTEN_GETRENNT.search(klein):
            return "pausieren"
        if self.vorhanden and hat_lehrwort and any(
            wort in klein for wort in self._ANHALTEWORTE
        ):
            return "pausieren"

        # --- 2. ausdruecklich etwas Neues ---------------------------------
        if self._NEUANFANG.search(klein) and (hat_lehrwort or "neues thema" in klein):
            self._gewuenschtes_fach = ""
            return "start"

        # --- 3. fortsetzen ------------------------------------------------
        if self.vorhanden and klein in self._ZURUFE:
            return "fortsetzen"
        darf_fortsetzen = self.vorhanden and (
            self.aktiv or hat_lehrwort or len(worte) <= 3
        )
        if darf_fortsetzen and any(wendung in klein for wendung in self._FORTSETZEN):
            genannt = self._thema_aus(text) if hat_lehrwort else ""
            bisher = _normalisieren(self.stand.thema)
            neu = _normalisieren(genannt)
            if neu and bisher and neu not in bisher and bisher not in neu:
                # Ein anderes Fach. Kennen wir es bereits, ist das ein
                # Wechsel und keine neue Vorlesung - der begonnene Stand
                # darf dabei nicht verloren gehen.
                if self._passenden_schluessel(genannt):
                    self._gewuenschtes_fach = genannt
                    return "fortsetzen"
                return "start"
            self._gewuenschtes_fach = genannt
            return "fortsetzen"
        if darf_fortsetzen and self._FORT_LOSE.search(klein):
            return "fortsetzen"
        if (
            self.vorhanden
            and hat_lehrwort
            and any(marker in klein for marker in self._WEITERREDEN)
            and not self._THEMA_GENANNT.search(klein)
        ):
            return "fortsetzen"

        # --- 4. beginnen --------------------------------------------------
        if not hat_lehrwort:
            return ""
        if self._THEMA_GENANNT.search(klein) or self._LEHRVERB_GENANNT.search(klein):
            return "start"
        if (
            self._LEHRWORT_MIT_WORT.search(klein)
            and self._BITTRAHMEN.search(klein)
            and any(marker in klein for marker in self._STARTMARKER)
        ):
            return "start"
        return ""


    def starten(self, auftrag: str) -> str:
        sauber = " ".join(str(auftrag or "").split()).strip()
        thema = self._thema_aus(sauber)
        schluessel = self._schluessel(thema or sauber)
        # Nur DIESES Fach beginnt von vorn. Alle anderen Vorlesungen
        # bleiben unberuehrt stehen - das ist der ganze Unterschied zu
        # frueher, wo eine neue Vorlesung die vorige ueberschrieb.
        self.stand = VorlesungsStand(
            auftrag=sauber,
            thema=thema,
            naechster_abschnitt=1,
            aktiv=True,
        )
        self._alle[schluessel] = self.stand
        self._aktiv_schluessel = schluessel
        self._gewuenschtes_fach = ""
        self._speichern()
        return self.naechster_auftrag()

    def fortsetzen(self, thema: str = "") -> str:
        """Setzt fort - wenn ein Fach genannt ist, genau dieses.

        Das genannte Fach kommt entweder als Argument oder aus dem letzten
        ``befehl()``-Aufruf. Damit heisst "Fahre fort mit der Vorlesung
        Geschichte" wirklich Geschichte, auch wenn zuletzt Philosophie
        lief.
        """

        genannt = thema or self._gewuenschtes_fach
        self._gewuenschtes_fach = ""
        if genannt:
            passend = self._passenden_schluessel(genannt)
            if passend:
                self._wechseln(passend)
        if not self.vorhanden:
            return ""
        self.stand.aktiv = True
        self.stand.pausiert = False
        self.stand.abgeschlossen = False
        self._speichern()
        return self.naechster_auftrag()

    def pausieren(self) -> None:
        if not self.vorhanden:
            return
        self.stand.aktiv = False
        self.stand.pausiert = True
        self._speichern()

    def benutzer_unterbricht(self) -> None:
        """Eine Wortmeldung unterbricht nur die aktuelle Rede, nicht die Sitzung.

        Der Aufnahmeweg stoppt den Folgezeitgeber bereits beim ersten Ton und
        setzt ihn nach der beantworteten Wortmeldung erneut. Dauerhaft pausiert
        wird ausschliesslich bei einem echten Stop-/Pause-Befehl.
        """

        return

    def naechster_auftrag(self) -> str:
        """Baut den internen Auftrag fuer den naechsten Abschnitt."""

        nummer = self.stand.naechster_abschnitt
        auszug = self.stand.letzter_auszug.strip()
        anschluss = (
            "Knuepfe unmittelbar an diesen Auszug des vorigen Abschnitts an: "
            f"{auszug}\n"
            if auszug
            else "Beginne mit einer kurzen Orientierung und steige dann direkt in das Thema ein.\n"
        )
        letzter = nummer >= self.max_abschnitte
        ende = (
            "Dies ist der letzte geplante Abschnitt. Runde die Gesamtvorlesung ab "
            "und beende sie mit dem exakten Satz: Damit ist diese Vorlesung abgeschlossen."
            if letzter
            else
            "Beende nur diesen Abschnitt an einer natuerlichen inhaltlichen Stelle. "
            "Frage NICHT, ob du fortfahren sollst, kuendige keine Pause an und sage "
            "nicht, dass du spaeter oder bei Schweigen weitermachst. Die Technik ruft "
            "den Folgeabschnitt automatisch auf."
        )
        return (
            f"{VORLESUNGS_MARKER}\n"
            f"Fortlaufende gesprochene Vorlesung, Abschnitt {nummer} von "
            f"hoechstens {self.max_abschnitte}.\n"
            f"Urspruenglicher Auftrag: {self.stand.auftrag}\n"
            f"Thema: {self.stand.thema or self.stand.auftrag}\n"
            f"{anschluss}"
            "Trage den Stoff wie ein ruhiger, fachlich praeziser Professor vor. "
            "Schreibe zusammenhaengenden, gut sprechbaren Fliesstext ohne Markdown, "
            "Aufzaehlungszeichen oder Meta-Kommentare. Verwende mittellange, klar "
            "abgeschlossene Saetze statt langer Nebensatzketten. Wiederhole den Auftrag nicht. "
            "Der Abschnitt soll substanziell sein, aber einen klaren Schwerpunkt haben. "
            "Wenn du eine feste Anzahl nennst, nenne unmittelbar alle Punkte "
            "vollstaendig und knapp, bevor du einen davon vertiefst. Beginne keine "
            "Aufzaehlung, die dieser Abschnitt nicht vollstaendig abschliessen kann. "
            f"{ende}"
        )

    def abschnitt_beendet(self, antwort: str, *, erfolgreich: bool = True) -> None:
        if not self.vorhanden:
            return
        if not erfolgreich:
            self.pausieren()
            return

        sauber = " ".join(str(antwort or "").split()).strip()
        normalisiert = sauber.casefold()
        voriger = " ".join(self.stand.letzter_auszug.split()).strip().casefold()
        # Eine technische Rueckfrage, ein Providerfehler oder dieselbe Antwort
        # wie im vorigen Durchlauf ist kein Vorlesungsabschnitt. Vor allem darf
        # daraus niemals automatisch der naechste Modellaufruf entstehen: Das
        # waere eine schnelle Endlosschleife, die den Orb wie eingefroren
        # erscheinen laesst und Provider sowie CPU belastet.
        unbrauchbar = (
            not sauber
            or any(marker in normalisiert for marker in self._UNBRAUCHBARE_ANTWORTEN)
            or (bool(voriger) and normalisiert == voriger)
        )
        if unbrauchbar:
            logger.warning(
                "Vorlesung pausiert: Die Modellantwort war kein brauchbarer Abschnitt (%r).",
                sauber[:160],
            )
            self.pausieren()
            return

        if sauber:
            self.stand.letzter_auszug = sauber[-900:]
        self.stand.naechster_abschnitt += 1

        vollendet = (
            "damit ist diese vorlesung abgeschlossen" in sauber.lower()
            or self.stand.naechster_abschnitt > self.max_abschnitte
        )
        if vollendet:
            self.stand.aktiv = False
            self.stand.pausiert = False
            self.stand.abgeschlossen = True
        self._speichern()

    def status(self) -> dict[str, object]:
        return {
            **asdict(self.stand),
            "max_abschnitte": self.max_abschnitte,
        }


    @staticmethod
    def _explizites_thema_aus(normalisiert: str) -> str:
        treffer = re.search(
            r"(?:(?:einfuehrung|einfuehrungs)?vorl(?:es|aes|ass|eis)\w*|vortrag)"
            r"\s+(?:ueber|zu|zum|zur|in)\s+(.+)",
            str(normalisiert or ""),
        )
        if not treffer:
            return ""
        thema = re.split(
            r"[.!?;,]|\s+(?:und\s+)?(?:mach|mache|fahre|halte|bis|ohne)\b",
            treffer.group(1),
            maxsplit=1,
        )[0]
        return thema.strip(" .,!?:;")[:240]

    def _stand_aus(self, daten: dict) -> VorlesungsStand:
        erlaubt = VorlesungsStand.__dataclass_fields__.keys()
        return VorlesungsStand(
            **{name: daten[name] for name in erlaubt if name in daten}
        )

    def _laden(self) -> None:
        try:
            if not self.path.exists():
                return
            daten = json.loads(self.path.read_text(encoding="utf-8"))

            # Zwei Dateiformen, und die alte muss weiterhin gelesen werden:
            # Auf dem Rechner des Benutzers liegt eine Philosophie-Vorlesung
            # bei Abschnitt 18. Sie beim Umbau zu verlieren waere genau der
            # Schaden, der hier behoben werden soll.
            roh = daten.get("vorlesungen")
            if isinstance(roh, dict):
                self._alle = {
                    str(schluessel): self._stand_aus(wert)
                    for schluessel, wert in roh.items()
                    if isinstance(wert, dict)
                }
                # "aktiv_fach" und nicht "aktiv": Das flache Feld "aktiv"
                # ist ein Wahrheitswert der laufenden Vorlesung und steht
                # aus Vertraeglichkeitsgruenden weiterhin daneben.
                self._aktiv_schluessel = str(daten.get("aktiv_fach", "") or "")
            else:
                # Alte, flache Form: genau eine Vorlesung.
                einzeln = self._stand_aus(daten)
                schluessel = self._schluessel(einzeln.thema or einzeln.auftrag)
                self._alle = {schluessel: einzeln} if einzeln.auftrag else {}
                self._aktiv_schluessel = schluessel if einzeln.auftrag else ""
                if self._alle:
                    logger.info(
                        "Vorlesungsstand in die fachgetrennte Ablage uebernommen: %r.",
                        schluessel,
                    )

            if self._aktiv_schluessel not in self._alle:
                self._aktiv_schluessel = next(iter(self._alle), "")
            self.stand = self._alle.get(self._aktiv_schluessel, VorlesungsStand())
            geaendert = not isinstance(roh, dict)
            # Eine ältere fehlerhafte Route konnte ihre technische Antwort
            # einmal als Lehrstoff speichern und dabei den Abschnittszähler
            # erhöhen. Diesen Zustand beim Laden selbst heilen, sonst knüpft
            # jede spätere Fortsetzung an "welches Programm?" an.
            for stand in self._alle.values():
                auszug = " ".join(stand.letzter_auszug.split()).casefold()
                if auszug and any(
                    marker in auszug for marker in self._UNBRAUCHBARE_ANTWORTEN
                ):
                    stand.letzter_auszug = ""
                    stand.naechster_abschnitt = max(1, stand.naechster_abschnitt - 1)
                    geaendert = True
                # Nach einem Programmstart nie ungefragt losreden. Der Stand
                # bleibt erhalten und ein "Fahre fort" setzt exakt dort fort.
                if stand.aktiv:
                    stand.aktiv = False
                    stand.pausiert = True
                    geaendert = True
            if geaendert:
                self._speichern()
        except (OSError, ValueError, TypeError):
            logger.warning("Der Vorlesungsstand konnte nicht geladen werden.", exc_info=True)
            self._alle = {}
            self._aktiv_schluessel = ""
            self.stand = VorlesungsStand()

    def _speichern(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.stand.auftrag:
                schluessel = self._aktiv_schluessel or self._schluessel(
                    self.stand.thema or self.stand.auftrag
                )
                self._aktiv_schluessel = schluessel
                self._alle[schluessel] = self.stand
            inhalt = {
                # Die flachen Felder bleiben zusaetzlich stehen: Ein
                # aelterer Lesezugriff (und ein Blick von Hand in die Datei)
                # findet damit weiterhin die LAUFENDE Vorlesung an
                # gewohnter Stelle.
                **asdict(self.stand),
                "aktiv_fach": self._aktiv_schluessel,
                "vorlesungen": {
                    schluessel: asdict(stand)
                    for schluessel, stand in self._alle.items()
                },
            }
            temporaer = self.path.with_suffix(self.path.suffix + ".tmp")
            temporaer.write_text(
                json.dumps(inhalt, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temporaer.replace(self.path)
        except OSError:
            logger.warning("Der Vorlesungsstand konnte nicht gespeichert werden.", exc_info=True)
