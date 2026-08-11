"""Themenwissen – wie sich der Orb in ein Gebiet einarbeitet.

Es gab schon ein Werkzeug namens ``wissen_aneignen``, und es war
angeschlossen. Was es tat, war trotzdem kein Lernen: Es las die Quellen,
gab den gelesenen Text in die eine Antwort – und legte im Gedächtnis nur
die Trefferzeile der Suchmaschine ab. Titel, ein Satz, ein Link. Wer eine
Woche später nach dem Thema fragte, bekam eine Linkliste zurück. Das ist
ein Lesezeichen, kein Wissen.

Dieses Modul dreht das um. Der Unterschied liegt in drei Punkten:

**Gespeichert wird die Substanz, nicht der Fundort.** Aus dem gelesenen
Text wird eine Reihe einzelner, für sich verständlicher Aussagen destilliert
– jede mit ihrer Quelle. Eine Aussage, die man ohne den Umgebungstext nicht
versteht, ist später wertlos; deshalb wird ausdrücklich danach verlangt.

**Was offen blieb, wird ebenfalls festgehalten.** Ein Thema ist nie fertig,
und das Nützlichste an einer Recherche ist oft die Frage, die sie
aufgeworfen hat. Aus diesen offenen Fragen speist sich das Vertiefen: Wer
„lerne mehr darüber" sagt, bekommt nicht dieselbe Suche noch einmal,
sondern die nächste Schicht.

**Gelesene Quellen werden vermerkt.** Ohne dieses Gedächtnis läse der Orb
beim Vertiefen wieder dieselben drei Seiten und käme nie weiter.

## Zur Verlässlichkeit

Jede Aussage trägt ihre Quelle mit, und zwar bis in die Antwort hinein.
Der Benutzer arbeitet wissenschaftlich; eine Behauptung ohne Herkunft ist
für ihn nicht bloss unschön, sondern unbrauchbar. Aussagen aus dem
Gespräch tragen ihn selbst als Quelle – auch das ist eine Herkunft, und
eine bessere als die meisten.

## Was hier NICHT geschieht

Es wird nichts zusammengefasst, gewichtet oder bewertet, was das Modell
nicht ausdrücklich hergegeben hat. Der Orb erfindet keine Aussage, die in
keiner Quelle stand – und wenn das Modell nichts Brauchbares liefert,
bleibt das Thema eben leer. Ein leeres Thema ist ehrlich; ein gefülltes
mit erfundenem Inhalt wäre Schaden.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.system.logging_setup import get_logger
from backend.utils.paths import get_data_dir

logger = get_logger(__name__)

#: So viele Aussagen werden je Durchgang höchstens übernommen.
#:
#: Die Grenze ist nicht technisch, sondern inhaltlich: Wer aus drei Seiten
#: vierzig Aussagen zieht, hat den Text zerhackt und nicht verstanden. Zwölf
#: zwingen zur Auswahl, und Auswahl ist der Teil, auf den es ankommt.
MAX_AUSSAGEN = 12

#: So viele offene Fragen werden je Durchgang übernommen.
MAX_FRAGEN = 6

#: So viel Text je Quelle geht an das Modell.
#:
#: Mehr bringt wenig und kostet viel: Der Anfang eines Artikels trägt fast
#: immer die Kernaussagen, das Ende Literaturverzeichnisse und Fussnoten.
ZEICHEN_JE_QUELLE = 6000


def _schluessel(thema: str) -> str:
    """Macht aus einem Thema einen Dateinamen.

    Kleingeschrieben und auf Buchstaben, Ziffern und Bindestriche
    reduziert – sonst legte „Kalter Krieg" und „kalter krieg" zwei Themen
    an, und der Orb wüsste von jedem die Hälfte.
    """

    klein = thema.strip().lower()
    klein = re.sub(r"[^a-z0-9äöüß]+", "-", klein).strip("-")
    return klein[:80] or "ohne-namen"


@dataclass
class Aussage:
    """Eine einzelne, für sich verständliche Feststellung."""

    text: str
    quelle: str = ""
    #: ``fakt``, ``wahrscheinlich`` oder ``strittig``.
    sicherheit: str = "wahrscheinlich"
    zeit: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "quelle": self.quelle,
            "sicherheit": self.sicherheit,
            "zeit": self.zeit,
        }

    @staticmethod
    def from_dict(daten: dict[str, Any]) -> "Aussage":
        return Aussage(
            text=str(daten.get("text", "")),
            quelle=str(daten.get("quelle", "")),
            sicherheit=str(daten.get("sicherheit", "wahrscheinlich")),
            zeit=float(daten.get("zeit", time.time())),
        )


@dataclass
class Thema:
    """Alles, was der Orb zu einem Gebiet weiss."""

    name: str
    aussagen: list[Aussage] = field(default_factory=list)
    offene_fragen: list[str] = field(default_factory=list)
    #: Bereits gelesene Quellen – damit das Vertiefen weiterkommt.
    gelesen: list[str] = field(default_factory=list)
    begonnen: float = field(default_factory=time.time)
    zuletzt: float = field(default_factory=time.time)
    #: Wie oft daran gearbeitet wurde.
    durchgaenge: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "aussagen": [a.to_dict() for a in self.aussagen],
            "offene_fragen": list(self.offene_fragen),
            "gelesen": list(self.gelesen),
            "begonnen": self.begonnen,
            "zuletzt": self.zuletzt,
            "durchgaenge": self.durchgaenge,
        }

    @staticmethod
    def from_dict(daten: dict[str, Any]) -> "Thema":
        return Thema(
            name=str(daten.get("name", "")),
            aussagen=[Aussage.from_dict(a) for a in daten.get("aussagen", [])],
            offene_fragen=[str(f) for f in daten.get("offene_fragen", [])],
            gelesen=[str(q) for q in daten.get("gelesen", [])],
            begonnen=float(daten.get("begonnen", time.time())),
            zuletzt=float(daten.get("zuletzt", time.time())),
            durchgaenge=int(daten.get("durchgaenge", 0)),
        )

    def quellen(self) -> list[str]:
        """Alle Quellen, aus denen Aussagen stammen – ohne Wiederholung."""

        gesehen: list[str] = []
        for aussage in self.aussagen:
            if aussage.quelle and aussage.quelle not in gesehen:
                gesehen.append(aussage.quelle)
        return gesehen

    def bericht(self) -> str:
        """Was der Orb zu diesem Thema weiss, zum Vorlesen."""

        if not self.aussagen:
            return f"Zu {self.name} weiss ich noch nichts."

        zeilen = [
            f"Zu {self.name} weiss ich {len(self.aussagen)} Dinge aus "
            f"{len(self.quellen())} Quellen:",
            "",
        ]
        for aussage in self.aussagen:
            herkunft = f" (Quelle: {aussage.quelle})" if aussage.quelle else ""
            zeilen.append(f"- {aussage.text}{herkunft}")

        if self.offene_fragen:
            zeilen.append("")
            zeilen.append("Offen ist noch:")
            for frage in self.offene_fragen:
                zeilen.append(f"- {frage}")

        return "\n".join(zeilen)

    def kurz(self) -> str:
        """Eine knappe Fassung für den Denk-Kontext.

        Der Unterschied zu :meth:`bericht` ist keine Formatierung, sondern
        die Menge: In den Denk-Kontext gehen bei jeder Frage ein paar
        hundert Zeichen; ein vollständiges Dossier verdrängte dort alles
        andere, einschliesslich der Frage selbst.
        """

        if not self.aussagen:
            return ""
        teile = [f"Zum Thema {self.name} ist bekannt:"]
        for aussage in self.aussagen[-8:]:
            herkunft = f" [{aussage.quelle}]" if aussage.quelle else ""
            teile.append(f"- {aussage.text}{herkunft}")
        return "\n".join(teile)


class Themenspeicher:
    """Legt Themen auf der Festplatte ab und holt sie zurück.

    Eine Datei je Thema, kein gemeinsamer Sammelband. Der Grund ist
    Haltbarkeit: Wird eine Datei beim Schreiben beschädigt – Stromausfall,
    volle Platte –, ist ein Thema verloren und nicht alle.
    """

    def __init__(self, ordner: Path | None = None) -> None:
        self._ordner = ordner or (get_data_dir() / "themen")
        try:
            self._ordner.mkdir(parents=True, exist_ok=True)
        except OSError as fehler:
            logger.warning("Der Themenordner ließ sich nicht anlegen: %s", fehler)

    @property
    def ordner(self) -> Path:
        return self._ordner

    def laden(self, thema: str) -> Thema:
        """Holt ein Thema – oder legt ein leeres an."""

        pfad = self._ordner / f"{_schluessel(thema)}.json"
        if not pfad.is_file():
            return Thema(name=thema.strip())
        try:
            daten = json.loads(pfad.read_text(encoding="utf-8"))
            return Thema.from_dict(daten)
        except (OSError, ValueError) as fehler:
            # Eine unlesbare Datei darf nicht das ganze Lernen aufhalten.
            # Sie wird nicht gelöscht: Vielleicht lässt sich von Hand noch
            # etwas retten, und Wissen wegzuwerfen ist schlimmer, als es
            # einmal nicht zu finden.
            logger.warning("Thema '%s' ließ sich nicht lesen: %s", thema, fehler)
            return Thema(name=thema.strip())

    def speichern(self, thema: Thema) -> bool:
        """Schreibt ein Thema. Gibt zurück, ob es geklappt hat."""

        thema.zuletzt = time.time()
        pfad = self._ordner / f"{_schluessel(thema.name)}.json"
        try:
            # Erst daneben schreiben, dann umbenennen: Bricht der Vorgang
            # ab, steht die alte Fassung noch. Ein halb geschriebenes
            # Thema wäre schlimmer als ein veraltetes.
            vorlaeufig = pfad.with_suffix(".json.neu")
            vorlaeufig.write_text(
                json.dumps(thema.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            vorlaeufig.replace(pfad)
            return True
        except OSError as fehler:
            logger.error("Thema '%s' ließ sich nicht sichern: %s", thema.name, fehler)
            return False

    def alle(self) -> list[Thema]:
        """Alle Themen, das zuletzt bearbeitete zuerst."""

        themen: list[Thema] = []
        try:
            dateien = sorted(self._ordner.glob("*.json"))
        except OSError:
            return []
        for pfad in dateien:
            try:
                themen.append(Thema.from_dict(json.loads(pfad.read_text(encoding="utf-8"))))
            except (OSError, ValueError):
                continue
        themen.sort(key=lambda t: t.zuletzt, reverse=True)
        return themen

    def namen(self) -> list[str]:
        return [t.name for t in self.alle()]

    def passend(self, text: str, *, limit: int = 2) -> list[Thema]:
        """Findet Themen, die in einem Satz vorkommen.

        Verglichen wird ueber WORTSTAEMME und nicht ueber ganze Woerter,
        und das ist im Deutschen keine Feinheit, sondern die ganze Frage.
        "Was weisst du ueber den Kalten Krieg?" soll das Thema "Kalter
        Krieg" finden - aber "kalten" ist nicht "kalter", und ein Vergleich
        auf Gleichheit findet hier nie etwas. Genau daran waere die
        Wiedererkennung im Gespraech gescheitert: Der Orb haette sein
        eigenes Wissen gehabt und waere nie darauf gekommen.

        Der Stamm ist das Wort ohne seine letzten beiden Zeichen, mindestens
        aber vier. Das ist keine Grammatik, sondern eine Faustregel - sie
        deckt die haeufigen Endungen ab (-er, -en, -es, -em) und ist kurz
        genug, dass sie nicht ueber das Ziel hinausschiesst.

        Kurze Woerter zaehlen nicht mit: "der" oder "und" traefen auf jeden
        Satz zu.
        """

        klein = text.lower()
        treffer: list[tuple[int, Thema]] = []

        for thema in self.alle():
            name = thema.name.lower().strip()
            if not name:
                continue

            worte = [w for w in re.split(r"[^a-z0-9äöüß]+", name) if len(w) >= 4]
            if not worte:
                continue

            staemme = [w[: max(4, len(w) - 2)] for w in worte]
            if all(stamm in klein for stamm in staemme):
                # Gewichtet mit der Laenge des Themennamens: "Zweiter
                # Weltkrieg" ist genauer als "Krieg", und wer beides
                # gespeichert hat, will das genauere zuerst.
                treffer.append((sum(len(w) for w in worte), thema))

        treffer.sort(key=lambda p: p[0], reverse=True)
        return [t for _, t in treffer[:limit]]
