"""Der Fähigkeitskatalog: was der Orb können muss, versioniert.

Das ist die Messlatte. Sie steht bewusst in einer eigenen Datei mit einer
Version und einer Prüfsumme, denn wer eine Messlatte verschieben kann,
misst nichts mehr. Änderungen daran sind laut den Regeln der
Selbstverbesserung freigabepflichtig - die Prüfsumme macht sie sichtbar.

Jedes Prüfstück gehört zu genau einer der acht Kategorien und sagt, wie es
bewertet wird:

``deterministisch``
    Die Antwort lässt sich maschinell prüfen - eine Zahl, ein Dateiname,
    ein Werkzeugaufruf. Kein Modell bewertet hier irgendetwas.
``werkzeug``
    Geprüft wird, ob die richtigen Werkzeuge in der richtigen Reihenfolge
    liefen und ob sie erfolgreich waren.
``rubrik``
    Freier Text. Bewertet wird gegen feste, vorab formulierte Kriterien -
    nicht gegen "wirkt gut".

Die Prüfstücke hier sind der Anfangsbestand. Er ist ausdrücklich klein und
ehrlich beschriftet: Ein Katalog, der alles abdeckt und nie gelaufen ist,
wäre wertlos gegenüber einem kleinen, der wirklich läuft.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

#: Die acht Aufgabenkategorien. Reihenfolge und Kennungen sind stabil -
#: an ihnen hängen die Messreihen.
KATEGORIEN: tuple[tuple[str, str], ...] = (
    ("alltagsdialog", "Alltagsdialog und deutsche Sprache"),
    ("geschichte_philosophie", "Geschichte und Philosophie"),
    ("recherche", "Rechercheplanung und Quellenkritik"),
    ("werkzeugwahl", "Werkzeugauswahl und Werkzeugausführung"),
    ("rechnerbedienung", "Dateien, Programme, Browser, Mail und Kalender"),
    ("gedaechtnis", "Gedächtnis, Lernbegleitung und Personalisierung"),
    ("programmierung", "Programmierung und Fehlerdiagnose"),
    ("darstellung", "Zusammenfassungen und längere Argumentationen"),
)

#: Erhöhen, wenn Prüfstücke dazukommen oder sich ändern. Alte Messreihen
#: bleiben lesbar, gelten aber nur für ihre eigene Version.
KATALOG_VERSION = "1.2.0"


@dataclass(frozen=True)
class Pruefstueck:
    """Eine einzelne Aufgabe, an der gemessen wird."""

    kennung: str
    kategorie: str
    aufgabe: str
    #: ``deterministisch``, ``werkzeug`` oder ``rubrik``.
    art: str
    #: Für ``deterministisch``: Zeichenketten, die in der Antwort stehen
    #: müssen (alle davon, Gross- und Kleinschreibung egal).
    erwartet: tuple[str, ...] = field(default_factory=tuple)
    #: Für ``deterministisch``: Zeichenketten, die NICHT vorkommen dürfen.
    verboten: tuple[str, ...] = field(default_factory=tuple)
    #: Für ``werkzeug``: welche Werkzeuge laufen müssen.
    werkzeuge: tuple[str, ...] = field(default_factory=tuple)
    #: Für ``rubrik``: die Kriterien, je eines einen Punkt wert.
    kriterien: tuple[str, ...] = field(default_factory=tuple)
    #: Ob die Aufgabe ohne Netz überhaupt lösbar ist.
    offline_loesbar: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "kennung": self.kennung,
            "kategorie": self.kategorie,
            "aufgabe": self.aufgabe,
            "art": self.art,
            "erwartet": list(self.erwartet),
            "verboten": list(self.verboten),
            "werkzeuge": list(self.werkzeuge),
            "kriterien": list(self.kriterien),
            "offline_loesbar": self.offline_loesbar,
        }


_PRUEFSTUECKE: tuple[Pruefstueck, ...] = (
    # --- 1. Alltagsdialog und deutsche Sprache ---------------------------
    Pruefstueck(
        "alltag_01", "alltagsdialog",
        "Sag mir in zwei Sätzen, wie das Wetter im Winter in der Schweiz ist.",
        "rubrik",
        kriterien=(
            "antwortet auf Deutsch",
            "hoechstens drei Saetze",
            "keine erfundene Ortsangabe oder Zahl",
            "beantwortet die Frage, statt auszuweichen",
        ),
    ),
    Pruefstueck(
        "alltag_02", "alltagsdialog",
        "Wie viel ist siebzehn mal drei?",
        "deterministisch",
        erwartet=("51",),
    ),
    Pruefstueck(
        "alltag_03", "alltagsdialog",
        "Formuliere den Satz hoeflicher: 'Schick mir das Dokument.'",
        "rubrik",
        kriterien=(
            "gibt eine umformulierte Fassung",
            "ist erkennbar hoeflicher",
            "behaelt die Bedeutung",
            "kommentiert nicht ausschweifend",
        ),
    ),
    # --- 2. Geschichte und Philosophie -----------------------------------
    Pruefstueck(
        "fach_01", "geschichte_philosophie",
        "In welchem Jahr endete der Zweite Weltkrieg in Europa?",
        "deterministisch",
        erwartet=("1945",),
    ),
    Pruefstueck(
        "fach_02", "geschichte_philosophie",
        "Erklaere in drei Saetzen, was Kant unter dem kategorischen Imperativ "
        "versteht.",
        "rubrik",
        kriterien=(
            "nennt die Verallgemeinerbarkeit der Maxime",
            "unterscheidet ihn von einem hypothetischen Imperativ oder nennt "
            "die Unbedingtheit",
            "erfindet kein Zitat",
            "bleibt bei drei bis vier Saetzen",
        ),
    ),
    Pruefstueck(
        "fach_03", "geschichte_philosophie",
        "Nenne einen verbreiteten Irrtum ueber die Aufklaerung und berichtige "
        "ihn.",
        "rubrik",
        kriterien=(
            "benennt einen wirklichen Irrtum",
            "berichtigt ihn sachlich",
            "erfindet keine Namen oder Jahreszahlen",
            "bleibt knapp",
        ),
    ),
    # --- 3. Rechercheplanung und Quellenkritik ---------------------------
    Pruefstueck(
        "recherche_01", "recherche",
        "Ich will wissen, ob eine Studie zu Schlafmangel bei Studierenden "
        "belastbar ist. Wie gehst du vor? Nenne die Schritte.",
        "rubrik",
        kriterien=(
            "nennt die Herkunft der Studie als Pruefpunkt",
            "nennt Stichprobe oder Methode",
            "nennt Gegenpruefung durch weitere Quellen",
            "behauptet kein Ergebnis, das es nicht kennt",
        ),
    ),
    Pruefstueck(
        "recherche_02", "recherche",
        "Was spricht dagegen, eine einzelne Zeitungsmeldung als Beleg zu "
        "nehmen?",
        "rubrik",
        kriterien=(
            "nennt fehlende Gegenpruefung",
            "nennt moegliche Verkuerzung oder Interessenlage",
            "bleibt sachlich statt pauschal",
        ),
    ),
    # --- 4. Werkzeugauswahl und Werkzeugausfuehrung -----------------------
    Pruefstueck(
        "werkzeug_01", "werkzeugwahl",
        "Suche im Internet, wie das Wetter morgen in Solothurn wird.",
        "werkzeug",
        werkzeuge=("internet_suchen",),
        offline_loesbar=False,
    ),
    Pruefstueck(
        "werkzeug_02", "werkzeugwahl",
        "Wie spaet ist es?",
        "werkzeug",
        werkzeuge=("aktuelle_zeit",),
    ),
    Pruefstueck(
        "werkzeug_03", "werkzeugwahl",
        "Rechne mir aus, wie viele Sekunden ein Tag hat.",
        "deterministisch",
        erwartet=("86400",),
    ),
    # --- 5. Dateien, Programme, Browser, Mail, Kalender -------------------
    Pruefstueck(
        "rechner_01", "rechnerbedienung",
        "Zeig mir, welche Dateien in meinem Dokumente-Ordner liegen.",
        "werkzeug",
        werkzeuge=("ordner_auflisten",),
    ),
    Pruefstueck(
        # Seit 1.2.0 gegen den Probekalender messbar (siehe
        # backend/lernen/kalenderprobe.py). "Zahnarzt" steht NICHT in der
        # Aufgabe - wer den Termin nennt, hat das Werkzeug wirklich
        # aufgerufen UND sein Ergebnis gelesen. Damit prueft der Fall
        # beides: die Werkzeugwahl und die Deutung des Ergebnisses.
        #
        # offline_loesbar ist jetzt True: Der Probekalender braucht kein
        # Netz und kein Konto.
        "rechner_02", "rechnerbedienung",
        "Was steht diese Woche in meinem Kalender?",
        "werkzeug",
        werkzeuge=("termine_ansehen",),
        erwartet=("Zahnarzt",),
        offline_loesbar=True,
    ),
    # --- 6. Gedaechtnis, Lernbegleitung, Personalisierung ------------------
    Pruefstueck(
        "gedaechtnis_01", "gedaechtnis",
        "Merk dir: Ich trinke Kaffee ohne Zucker.",
        "werkzeug",
        werkzeuge=("vorliebe_merken",),
    ),
    Pruefstueck(
        "gedaechtnis_02", "gedaechtnis",
        "Leg mir eine Karteikarte an: Frage 'Wer schrieb die Kritik der "
        "reinen Vernunft?', Antwort 'Immanuel Kant'.",
        "werkzeug",
        werkzeuge=("karteikarte_anlegen",),
    ),
    # --- 7. Programmierung und Fehlerdiagnose ------------------------------
    Pruefstueck(
        "code_01", "programmierung",
        "Schreibe eine Python-Funktion, die eine Liste von Zahlen aufsteigend "
        "sortiert zurueckgibt. Nur der Code.",
        "deterministisch",
        erwartet=("def ", "sorted", "return"),
    ),
    Pruefstueck(
        "code_02", "programmierung",
        "Dieser Code wirft einen Fehler: 'for i in range(10) print(i)'. "
        "Was fehlt?",
        "deterministisch",
        erwartet=(":",),
        kriterien=("benennt den fehlenden Doppelpunkt",),
    ),
    # --- 8. Zusammenfassungen und laengere Argumentationen -----------------
    Pruefstueck(
        "darstellung_01", "darstellung",
        "Fasse in fuenf Saetzen zusammen, warum Quellenkritik zur "
        "Geschichtswissenschaft gehoert.",
        "rubrik",
        kriterien=(
            "haelt sich an die Laengenvorgabe",
            "nennt mindestens zwei verschiedene Gruende",
            "baut die Saetze aufeinander auf",
            "erfindet keine Belege",
        ),
    ),
    Pruefstueck(
        "darstellung_02", "darstellung",
        "Argumentiere in einem Absatz fuer und in einem gegen die These, dass "
        "Sprachmodelle das Lernen erleichtern.",
        "rubrik",
        kriterien=(
            "liefert beide Seiten",
            "die Gegenseite ist nicht bloss eine Strohpuppe",
            "bleibt bei zwei Absaetzen",
            "keine erfundenen Studien",
        ),
    ),
)


@dataclass(frozen=True)
class Pruefkatalog:
    """Der vollständige Katalog mit Version und Prüfsumme."""

    version: str
    stuecke: tuple[Pruefstueck, ...]

    @property
    def pruefsumme(self) -> str:
        """Ein Fingerabdruck über alle Prüfstücke.

        Wer die Messlatte verschiebt, ändert diese Zahl. Messreihen halten
        sie fest, damit sich später nicht streiten lässt, wogegen gemessen
        wurde.
        """

        roh = json.dumps(
            [stueck.to_dict() for stueck in self.stuecke],
            sort_keys=True,
            ensure_ascii=False,
        )
        return hashlib.sha256(roh.encode("utf-8")).hexdigest()[:16]

    def fuer(self, kategorie: str) -> tuple[Pruefstueck, ...]:
        return tuple(s for s in self.stuecke if s.kategorie == kategorie)

    def offline_taugliche(self) -> tuple[Pruefstueck, ...]:
        return tuple(s for s in self.stuecke if s.offline_loesbar)

    def kategorien(self) -> tuple[str, ...]:
        return tuple(kennung for kennung, _titel in KATEGORIEN)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "pruefsumme": self.pruefsumme,
            "kategorien": {k: t for k, t in KATEGORIEN},
            "stuecke": [s.to_dict() for s in self.stuecke],
        }


def katalog() -> Pruefkatalog:
    """Der gültige Fähigkeitskatalog."""

    return Pruefkatalog(version=KATALOG_VERSION, stuecke=_PRUEFSTUECKE)


__all__ = [
    "KATALOG_VERSION",
    "KATEGORIEN",
    "Pruefkatalog",
    "Pruefstueck",
    "katalog",
]
