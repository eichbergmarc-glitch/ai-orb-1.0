"""Das Tagebuch - diktierte Einträge, dauerhaft und schön nachlesbar.

Der Benutzer hat es am 20.08.2026 so bestellt: Er diktiert die Einträge,
der Orb bewahrt sie auf und pflegt daraus eine "schön dargestellte
Tagebuch-Datei, die ich jederzeit nachlesen kann".

Zwei Dateien, zwei Rollen:

* ``data/tagebuch.json`` ist die WAHRHEIT - jeder Eintrag mit Zeitpunkt,
  unverändert, für immer. Die Datei steht auf der Schutzliste: Kein
  Werkzeug des Orb darf sie überschreiben, denn ein Tagebuch lässt sich
  nicht wiederherstellen. Und weil ``data/`` in der .gitignore steht,
  verlässt kein Eintrag je den Rechner.
* ``Dokumente/AI-Orb/Tagebuch.html`` (und ``.pdf``) ist die ANSICHT -
  aus den Einträgen erzeugt, nach jedem Schreiben frisch, im Stil eines
  ruhigen Buches: Serifen, warmes Papier, die Einträge nach Tagen
  geordnet, die jüngsten oben. Sie liegt BEWUSST bei den Dokumenten des
  Benutzers und nicht in den Anwendungsdaten: Ein echtes Tagebuch muss
  sich ohne den Orb aufschlagen lassen (Doppelklick, 23.08.2026). Dazu
  kommt einmalig eine Verknüpfung "Tagebuch" auf dem Desktop. Die
  Ansicht zu verlieren kostet nichts; sie entsteht aus der Wahrheit neu.

Bewusst KEIN Sprachmodell in der Kette: Was diktiert wird, wird
wortgetreu abgelegt. Ein Tagebuch, das die Maschine "verbessert",
gehörte nicht mehr dem, der es führt.
"""

from __future__ import annotations

import base64
import html
import json
import mimetypes
import re
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from backend.system.logging_setup import get_logger

logger = get_logger(__name__)

#: Deutsche Namen selbst gebaut: Die Windows-Python-Laufzeit des Orb hat
#: keine verlässliche deutsche Locale, und ein Tagebuch mit "Wednesday"
#: darin wäre keines.
_WOCHENTAGE = (
    "Montag", "Dienstag", "Mittwoch", "Donnerstag",
    "Freitag", "Samstag", "Sonntag",
)
_MONATE = (
    "Januar", "Februar", "März", "April", "Mai", "Juni", "Juli",
    "August", "September", "Oktober", "November", "Dezember",
)


def _datum_lang(zeitpunkt: datetime) -> str:
    """"Mittwoch, 20. August 2026" - wie man ein Tagebuch datiert."""

    return (
        f"{_WOCHENTAGE[zeitpunkt.weekday()]}, {zeitpunkt.day}. "
        f"{_MONATE[zeitpunkt.month - 1]} {zeitpunkt.year}"
    )


@dataclass(slots=True)
class Eintrag:
    """Ein Tagebucheintrag - wortgetreu, mit Zeitpunkt."""

    zeit: float
    text: str
    titel: str = ""
    bilder: list[dict[str, str]] = field(default_factory=list)

    @property
    def zeitpunkt(self) -> datetime:
        return datetime.fromtimestamp(self.zeit)

    def to_dict(self) -> dict[str, object]:
        return {
            "zeit": self.zeit, "text": self.text, "titel": self.titel,
            "bilder": self.bilder,
        }

    @classmethod
    def from_dict(cls, daten: dict[str, object]) -> "Eintrag":
        return cls(
            zeit=float(daten.get("zeit", 0.0) or 0.0),
            text=str(daten.get("text", "") or ""),
            titel=str(daten.get("titel", "") or ""),
            bilder=[
                {"pfad": str(b.get("pfad", "")), "nachweis": str(b.get("nachweis", ""))}
                for b in (daten.get("bilder", []) or [])
                if isinstance(b, dict) and b.get("pfad")
            ],
        )


def _dokumente_ordner() -> Path:
    """Wo das lesbare Buch hingehört: zu den Dokumenten des Benutzers.

    Der Anlass (23.08.2026): Das Buch lag in den Anwendungsdaten - dort
    findet es kein Mensch. "Der Orb soll ein ECHTES Tagebuch anlegen,
    welches ich auch öffnen und lesen kann" heisst: eine sichtbare Datei
    an einem Ort, den der Benutzer kennt, doppelklickbar, ohne den Orb
    fragen zu müssen.
    """

    zuhause = Path.home()
    for kandidat in (
        zuhause / "OneDrive" / "Dokumente",
        zuhause / "OneDrive" / "Documents",
        zuhause / "Documents",
        zuhause / "Dokumente",
    ):
        if kandidat.is_dir():
            return kandidat / "AI-Orb"
    return zuhause / "Documents" / "AI-Orb"


def _desktop_ordner() -> Path | None:
    zuhause = Path.home()
    for kandidat in (zuhause / "OneDrive" / "Desktop", zuhause / "Desktop"):
        if kandidat.is_dir():
            return kandidat
    return None


@dataclass(slots=True)
class Tagebuch:
    """Bewahrt die Einträge auf und pflegt die schöne Ansicht."""

    ordner: Path
    #: Wo das LESBARE Buch liegt (HTML und PDF). Ohne Angabe derselbe
    #: Ordner wie die Ablage; der Orb übergibt den Dokumente-Ordner.
    lese_ordner: Path | None = None
    eintraege: list[Eintrag] = field(default_factory=list)
    #: Die Zeile auf dem Titelblatt, z.B. "Daniel Peter Glor · 2026".
    untertitel: str = ""
    #: Ob die Desktop-Verknüpfung schon einmal angelegt wurde. Nur einmal:
    #: Wer sie löscht, will sie los sein - sie kommt nicht wieder.
    verknuepfung_angelegt: bool = False
    #: Ist die Ablage beschädigt, steht hier der Grund - und das Tagebuch
    #: verweigert jedes Schreiben, damit nichts die alte Datei überrollt.
    #: Bewusst KEIN Fehler beim Start: Ein kaputtes Tagebuch darf den Orb
    #: nicht am Aufwachen hindern.
    defekt: str = ""

    def __post_init__(self) -> None:
        self._laden()

    # --- Ablage -----------------------------------------------------------------

    @property
    def _ablage(self) -> Path:
        return self.ordner / "tagebuch.json"

    @property
    def _lesbar(self) -> Path:
        return self.lese_ordner if self.lese_ordner is not None else self.ordner

    @property
    def ansicht(self) -> Path:
        return self._lesbar / "Tagebuch.html"

    @property
    def pdf(self) -> Path:
        """Die PDF-Fassung - fuer Apps, die PDF lesen (Microsoft Journal).

        Der Benutzer wollte sein Tagebuch in Microsoft Journal. Die App
        hat keine Schnittstelle, ueber die ein Programm Text hineinlegen
        koennte - sie ist fuers Handschreiben gebaut. Was sie KANN, ist
        PDF einlesen. Deshalb haelt der Orb neben dem Buch im Browser
        immer auch diese PDF aktuell: Sie laesst sich in Journal
        importieren und dort handschriftlich weiterfuehren.
        """

        return self._lesbar / "Tagebuch.pdf"

    def _laden(self) -> None:
        if not self._ablage.is_file():
            return
        try:
            daten = json.loads(self._ablage.read_text(encoding="utf-8"))
            self.eintraege = [
                Eintrag.from_dict(e) for e in daten.get("eintraege", [])
            ]
            self.untertitel = str(daten.get("untertitel", "") or "")
            self.verknuepfung_angelegt = bool(daten.get("verknuepfung_angelegt", False))
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as fehler:
            # Nicht überschreiben, was man nicht lesen kann: Eine defekte
            # Tagebuchdatei bleibt liegen, bis ein Mensch sie ansieht.
            logger.error("Das Tagebuch liess sich nicht lesen: %s", fehler)
            self.defekt = (
                "Die Tagebuchdatei ist beschädigt und wird nicht angerührt - "
                "bitte data/tagebuch.json ansehen. Bis dahin nehme ich keine "
                "neuen Einträge an, damit nichts Altes überschrieben wird."
            )

    def _speichern(self) -> None:
        self.ordner.mkdir(parents=True, exist_ok=True)
        # Die Verknüpfung VOR dem Schreiben der Ablage: So steht ihr
        # "schon angelegt" mit im selben Schreibvorgang, und ein Neustart
        # legt keine zweite an, wenn der Benutzer sie geloescht hat.
        self._verknuepfung_anlegen()
        inhalt = json.dumps(
            {
                "untertitel": self.untertitel,
                "verknuepfung_angelegt": self.verknuepfung_angelegt,
                "eintraege": [e.to_dict() for e in self.eintraege],
            },
            ensure_ascii=False,
            indent=2,
        )
        # Erst die Wahrheit, dann die Ansicht - und die Wahrheit über eine
        # Zwischendatei, damit ein Absturz mitten im Schreiben nie eine
        # halbe Tagebuchdatei hinterlässt.
        zwischen = self._ablage.with_suffix(".json.neu")
        zwischen.write_text(inhalt, encoding="utf-8")
        zwischen.replace(self._ablage)
        try:
            self._lesbar.mkdir(parents=True, exist_ok=True)
            self.ansicht.write_text(self.als_html(), encoding="utf-8")
        except OSError as fehler:
            logger.warning("Die Tagebuch-Ansicht liess sich nicht schreiben: %s", fehler)
        try:
            self.pdf.write_bytes(self.als_pdf_bytes())
        except Exception as fehler:  # noqa: BLE001 - die PDF ist Zugabe, nie Huerde.
            logger.warning("Die Tagebuch-PDF liess sich nicht schreiben: %s", fehler)

    def _verknuepfung_anlegen(self) -> None:
        """Legt EINMAL eine Verknüpfung "Tagebuch" auf den Desktop.

        Ein echtes Tagebuch will man aufschlagen, ohne jemanden zu fragen.
        Die Verknüpfung zeigt auf die HTML-Fassung; ein Doppelklick öffnet
        sie im Browser. Nur einmal angelegt: Wer sie löscht, will sie los
        sein, und sie kommt nicht bei jedem Eintrag wieder.
        """

        if self.verknuepfung_angelegt or not self.eintraege:
            return
        desktop = _desktop_ordner()
        if desktop is None:
            return
        ziel = desktop / "Tagebuch.url"
        try:
            adresse = self.ansicht.resolve().as_uri()
            ziel.write_text(
                f"[InternetShortcut]\r\nURL={adresse}\r\n", encoding="utf-8"
            )
            self.verknuepfung_angelegt = True
            # Das Zeichen sofort festhalten - ohne erneutes _speichern,
            # sonst drehte sich das im Kreis. Die Ablage stimmt beim
            # naechsten Eintrag ohnehin wieder.
            logger.info("Desktop-Verknüpfung zum Tagebuch angelegt: %s", ziel)
        except OSError as fehler:
            logger.warning("Die Tagebuch-Verknüpfung liess sich nicht anlegen: %s", fehler)

    def titelblatt_setzen(self, text: str) -> str:
        """Setzt die Zeile auf dem Titelblatt, z.B. "Daniel Peter Glor · 2026"."""

        if self.defekt:
            raise TagebuchFehler(self.defekt)
        self.untertitel = " ".join(str(text or "").split())
        self._speichern()
        return self.untertitel

    # --- Führen -----------------------------------------------------------------

    def eintragen(self, text: str, *, titel: str = "") -> Eintrag:
        """Nimmt einen diktierten Eintrag wortgetreu auf."""

        if self.defekt:
            raise TagebuchFehler(self.defekt)
        knapp = " ".join(str(text or "").split())
        if not knapp:
            raise TagebuchFehler("Ein leerer Eintrag ist keiner.")
        eintrag = Eintrag(zeit=time.time(), text=knapp, titel=str(titel or "").strip())
        self.eintraege.append(eintrag)
        self._speichern()
        logger.info("Tagebucheintrag aufgenommen (%d Zeichen).", len(knapp))
        return eintrag

    def letzten_streichen(self) -> Eintrag | None:
        """Nimmt den jüngsten Eintrag zurück - für das Fehldiktat.

        Nur den jüngsten: Ältere Einträge streicht der Benutzer selbst in
        der Datei, wenn er es wirklich will. Ein Werkzeug, das beliebige
        Einträge löscht, wäre gefährlicher als das Ärgernis, das es heilt.
        """

        if self.defekt:
            raise TagebuchFehler(self.defekt)
        if not self.eintraege:
            return None
        eintrag = self.eintraege.pop()
        self._speichern()
        logger.info("Der jüngste Tagebucheintrag wurde gestrichen.")
        return eintrag

    @staticmethod
    def _suchform(text: str) -> str:
        """Macht gesprochene Datums-/Zeitangaben vergleichbar."""

        return " ".join(re.sub(r"[^0-9a-zäöüß]+", " ", str(text).lower()).split())

    def _eintrag_finden(
        self, *, suchtext: str = "", position: str = "letzter"
    ) -> Eintrag | None:
        """Findet einen Eintrag nach Inhalt, Titel, Datum, Uhrzeit oder Lage."""

        if not self.eintraege:
            return None
        gesucht = self._suchform(suchtext)
        if not gesucht:
            return self.eintraege[0] if position == "erster" else self.eintraege[-1]

        kandidaten = (
            self.eintraege if position == "erster" else reversed(self.eintraege)
        )
        for eintrag in kandidaten:
            zeitpunkt = eintrag.zeitpunkt
            if gesucht == "heute" and zeitpunkt.date() == datetime.now().date():
                return eintrag
            heuhaufen = self._suchform(
                f"{eintrag.titel} {eintrag.text} {_datum_lang(zeitpunkt)} "
                f"{zeitpunkt.strftime('%H:%M')} Uhr"
            )
            if gesucht in heuhaufen:
                return eintrag
        return None

    def eintrag_streichen(
        self, suchtext: str, *, position: str = "letzter"
    ) -> Eintrag | None:
        """Streicht den juengsten Eintrag, der die Beschreibung enthaelt."""

        if self.defekt:
            raise TagebuchFehler(self.defekt)
        eintrag = self._eintrag_finden(suchtext=suchtext, position=position)
        if eintrag is None:
            return None
        self.eintraege.remove(eintrag)
        self._speichern()
        logger.info("Beschriebener Tagebucheintrag wurde gestrichen.")
        return eintrag

    def eintrag_aendern(
        self,
        *,
        modus: str,
        text: str = "",
        alt: str = "",
        neu: str = "",
        suchtext: str = "",
        position: str = "letzter",
    ) -> Eintrag:
        """Aendert einen Eintrag gezielt, ohne Datum oder Bilder zu verlieren."""

        if self.defekt:
            raise TagebuchFehler(self.defekt)
        eintrag = self._eintrag_finden(suchtext=suchtext, position=position)
        if eintrag is None:
            raise TagebuchFehler("Kein passender Tagebucheintrag gefunden.")

        inhalt = str(eintrag.text)
        if modus == "ersetzen_gesamt":
            geaendert = " ".join(str(text or "").split())
            if not geaendert:
                raise TagebuchFehler("Die neue Fassung ist leer.")
        elif modus == "anhaengen":
            zusatz = " ".join(str(text or "").split())
            if not zusatz:
                raise TagebuchFehler("Die Ergänzung ist leer.")
            geaendert = f"{inhalt.rstrip()} {zusatz}".strip()
        elif modus in {"ersetzen", "entfernen"}:
            gesucht = " ".join(str(alt or text or "").split())
            if not gesucht:
                raise TagebuchFehler("Es wurde kein zu ändernder Text genannt.")
            treffer = re.search(re.escape(gesucht), inhalt, flags=re.IGNORECASE)
            if treffer is None:
                raise TagebuchFehler(
                    "Der genannte Wortlaut steht nicht im ausgewählten Eintrag."
                )
            ersatz = "" if modus == "entfernen" else " ".join(str(neu or "").split())
            geaendert = (
                inhalt[:treffer.start()] + ersatz + inhalt[treffer.end():]
            )
            geaendert = " ".join(geaendert.split())
        else:
            raise TagebuchFehler("Diese Tagebuchänderung ist nicht bekannt.")

        eintrag.text = geaendert
        self._speichern()
        logger.info("Tagebucheintrag geändert (%d Zeichen).", len(geaendert))
        return eintrag

    def bild_einfuegen(self, pfad: str | Path, *, nachweis: str = "") -> Eintrag:
        """Haengt eine dauerhafte lokale Bildkopie an den juengsten Eintrag."""

        if self.defekt:
            raise TagebuchFehler(self.defekt)
        if not self.eintraege:
            raise TagebuchFehler("Das Tagebuch hat noch keinen Eintrag für das Bild.")
        quelle = Path(pfad)
        if not quelle.is_file() or quelle.suffix.lower() not in {
            ".jpg", ".jpeg", ".png", ".webp", ".gif"
        }:
            raise TagebuchFehler("Die ausgewählte Bilddatei ist nicht verfügbar.")
        bildordner = self.ordner / "tagebuch-bilder"
        bildordner.mkdir(parents=True, exist_ok=True)
        ziel = bildordner / f"{int(time.time() * 1000)}-{quelle.name}"
        shutil.copy2(quelle, ziel)
        self.eintraege[-1].bilder.append(
            {"pfad": str(ziel), "nachweis": str(nachweis or "").strip()}
        )
        self._speichern()
        return self.eintraege[-1]

    @staticmethod
    def _bild_html(bild: dict[str, str]) -> str:
        pfad = Path(str(bild.get("pfad", "")))
        try:
            mime = mimetypes.guess_type(pfad.name)[0] or "image/jpeg"
            daten = base64.b64encode(pfad.read_bytes()).decode("ascii")
        except OSError:
            return ""
        nachweis = html.escape(str(bild.get("nachweis", "") or ""))
        caption = f"<figcaption>{nachweis}</figcaption>" if nachweis else ""
        return (
            '<figure class="tagebuchbild">'
            f'<img src="data:{mime};base64,{daten}" alt="Bild zum Tagebucheintrag">'
            f"{caption}</figure>"
        )

    def nachsehen(
        self, *, suchwort: str = "", hoechstens: int = 5
    ) -> list[Eintrag]:
        """Die jüngsten Einträge, wahlweise nur die mit einem Suchwort."""

        wort = str(suchwort or "").strip().lower()
        passende = [
            e
            for e in self.eintraege
            if not wort or wort in e.text.lower() or wort in e.titel.lower()
        ]
        return passende[-max(1, hoechstens):][::-1]

    # --- Die schöne Ansicht -------------------------------------------------------

    def als_html(self) -> str:
        """Das ganze Tagebuch als eine in sich ruhende HTML-Seite."""

        tage: dict[str, list[Eintrag]] = {}
        for eintrag in sorted(self.eintraege, key=lambda e: e.zeit, reverse=True):
            schluessel = _datum_lang(eintrag.zeitpunkt)
            tage.setdefault(schluessel, []).append(eintrag)

        teile: list[str] = []
        letztes_jahr: int | None = None
        for tag, eintraege in tage.items():
            jahr = eintraege[0].zeitpunkt.year
            if jahr != letztes_jahr:
                teile.append(
                    f'<div class="jahr" id="jahr-{jahr}"><span>{jahr}</span></div>'
                )
                letztes_jahr = jahr
            karten = []
            for e in eintraege:
                titel_html = (
                    f'<h3>{html.escape(e.titel)}</h3>' if e.titel else ""
                )
                absaetze = "".join(
                    f"<p>{html.escape(a.strip())}</p>"
                    for a in e.text.split(" | ")
                    if a.strip()
                ) or f"<p>{html.escape(e.text)}</p>"
                bilder_html = "".join(self._bild_html(b) for b in e.bilder)
                karten.append(
                    '<article class="eintrag">'
                    f'<div class="uhrzeit">{e.zeitpunkt.strftime("%H:%M")} Uhr</div>'
                    f"{titel_html}{absaetze}{bilder_html}</article>"
                )
            teile.append(
                f'<section class="tag"><h2>{html.escape(tag)}</h2>'
                + "".join(karten)
                + "</section>"
            )

        inhalt = "".join(teile) or (
            '<p class="leer">Noch kein Eintrag. Sag: '
            "&bdquo;Orb, neuer Tagebucheintrag &hellip;&ldquo;</p>"
        )
        anzahl = len(self.eintraege)
        anzahl_tage = len(tage)
        jahre = sorted({e.zeitpunkt.year for e in self.eintraege}, reverse=True)
        jahresnav = "".join(
            f'<a href="#jahr-{jahr}">{jahr}</a>' for jahr in jahre
        )
        uebersicht = (
            f'<div class="kennzahl"><strong>{anzahl}</strong><span>Einträge</span></div>'
            f'<div class="kennzahl"><strong>{anzahl_tage}</strong><span>Tage</span></div>'
            f'<div class="kennzahl"><strong>{len(jahre)}</strong><span>Jahre</span></div>'
        )
        stand = _datum_lang(datetime.now())
        untertitel = html.escape(self.untertitel) if self.untertitel else (
            "aufgeschrieben vom Orb, Wort f&uuml;r Wort"
        )
        return _VORLAGE.format(
            inhalt=inhalt,
            anzahl=anzahl,
            stand=stand,
            untertitel=untertitel,
            uebersicht=uebersicht,
            jahresnav=jahresnav,
        )


    def als_pdf_bytes(self) -> bytes:
        """Das Tagebuch als PDF - mit der Satzengine der PDF-Werkzeuge.

        Bewusst deren interne Engine statt einer zweiten: Ein Dokument,
        zwei Setzer, das driftet auseinander. Die Engine braucht keine
        Sicherheitspruefung, weil hier keine fremden Pfade vorkommen -
        nur eigener Text.
        """

        from backend.tools.pdf_tools import _build_pdf, _Layout

        titel = "Tagebuch" + (f" - {self.untertitel}" if self.untertitel else "")
        satz = _Layout(titel)
        tage: dict[str, list[Eintrag]] = {}
        for eintrag in sorted(self.eintraege, key=lambda e: e.zeit, reverse=True):
            tage.setdefault(_datum_lang(eintrag.zeitpunkt), []).append(eintrag)
        for tag, eintraege in tage.items():
            satz.heading(tag, level=2)
            for e in eintraege:
                kopf = f"{e.zeitpunkt.strftime('%H:%M')} Uhr"
                if e.titel:
                    kopf += f" - {e.titel}"
                satz.paragraph(kopf, bullet="-")
                for absatz in e.text.split(" | "):
                    if absatz.strip():
                        satz.paragraph(absatz.strip())
                satz.gap(6.0)
        if not self.eintraege:
            satz.paragraph("Noch kein Eintrag.")
        return _build_pdf(satz, title=titel)


class TagebuchFehler(RuntimeError):
    """Etwas am Tagebuch ging nicht - mit Begründung im Klartext."""


#: Die Seite selbst: ruhig, warm, ein Buch und kein Werkzeugfenster.
#: Alles eingebettet, nichts nachgeladen - die Datei steht für sich.
_VORLAGE = """<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tagebuch</title>
<style>
  :root {{
    --papier: #f7f2e8;
    --karte: #fffdf7;
    --tinte: #2e2a24;
    --nebentinte: #8a7f6e;
    --linie: #e0d6c3;
    --akzent: #8c1d18;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    background: var(--papier);
    color: var(--tinte);
    font-family: Georgia, "Times New Roman", serif;
    line-height: 1.65;
  }}
  .buch {{
    max-width: 46rem;
    margin: 0 auto;
    padding: 3rem 1.5rem 4rem;
  }}
  header {{
    text-align: center;
    margin-bottom: 2.5rem;
    padding-bottom: 1.5rem;
    border-bottom: 3px double var(--linie);
  }}
  header h1 {{
    font-size: 2.4rem;
    letter-spacing: 0.08em;
    margin: 0 0 0.4rem;
    font-weight: normal;
  }}
  header .untertitel {{
    color: var(--nebentinte);
    font-style: italic;
  }}
  .uebersicht {{
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 0.75rem;
    margin: 1.75rem 0 0;
  }}
  .kennzahl {{
    padding: 0.8rem 0.5rem;
    border: 1px solid var(--linie);
    border-radius: 8px;
    background: rgba(255, 253, 247, 0.7);
  }}
  .kennzahl strong {{ display: block; font-size: 1.35rem; font-weight: normal; }}
  .kennzahl span {{ color: var(--nebentinte); font-size: 0.78rem; text-transform: uppercase; letter-spacing: .08em; }}
  nav {{ text-align: center; margin: -1rem 0 2.5rem; }}
  nav a {{
    display: inline-block;
    color: var(--akzent);
    text-decoration: none;
    border-bottom: 1px solid var(--linie);
    margin: 0 .4rem;
    padding: .15rem .35rem;
  }}
  .jahr {{
    display: flex;
    align-items: center;
    gap: 1rem;
    color: var(--nebentinte);
    margin: 2.8rem 0 1.5rem;
    font-size: 1.35rem;
    letter-spacing: .12em;
  }}
  .jahr::before, .jahr::after {{ content: ""; height: 1px; background: var(--linie); flex: 1; }}
  .tag {{ margin: 2.2rem 0; }}
  .tag h2 {{
    font-size: 1.15rem;
    font-weight: normal;
    font-variant: small-caps;
    letter-spacing: 0.06em;
    color: var(--akzent);
    border-bottom: 1px solid var(--linie);
    padding-bottom: 0.3rem;
    margin: 0 0 1rem;
  }}
  .eintrag {{
    background: var(--karte);
    border: 1px solid var(--linie);
    border-radius: 6px;
    padding: 1.1rem 1.4rem;
    margin-bottom: 1rem;
    box-shadow: 0 1px 3px rgba(60, 45, 20, 0.08);
  }}
  .eintrag .uhrzeit {{
    float: right;
    color: var(--nebentinte);
    font-size: 0.85rem;
    font-style: italic;
  }}
  .eintrag h3 {{
    margin: 0 0 0.5rem;
    font-size: 1.05rem;
  }}
  .eintrag p {{ margin: 0.5rem 0; text-align: justify; hyphens: auto; }}
  .eintrag p:first-letter {{ }}
  .tagebuchbild {{ margin: 1.2rem 0 .25rem; }}
  .tagebuchbild img {{
    display: block;
    width: 100%;
    max-height: 34rem;
    object-fit: contain;
    border-radius: 5px;
    box-shadow: 0 2px 10px rgba(45, 34, 19, .16);
  }}
  .tagebuchbild figcaption {{
    margin-top: .45rem;
    color: var(--nebentinte);
    font-size: .78rem;
    text-align: center;
  }}
  .leer {{
    text-align: center;
    color: var(--nebentinte);
    font-style: italic;
    margin-top: 3rem;
  }}
  footer {{
    margin-top: 3rem;
    padding-top: 1rem;
    border-top: 3px double var(--linie);
    text-align: center;
    color: var(--nebentinte);
    font-size: 0.85rem;
    font-style: italic;
  }}
  @media print {{
    .eintrag {{ box-shadow: none; break-inside: avoid; }}
    body {{ background: white; }}
  }}
  @media (max-width: 34rem) {{
    .buch {{ padding: 2rem 1rem 3rem; }}
    .eintrag .uhrzeit {{ float: none; margin-bottom: .35rem; }}
  }}
</style>
</head>
<body>
<div class="buch">
  <header>
    <h1>Tagebuch</h1>
    <div class="untertitel">{untertitel}</div>
    <div class="uebersicht">{uebersicht}</div>
  </header>
  <nav aria-label="Jahre">{jahresnav}</nav>
  {inhalt}
  <footer>{anzahl} Eintr&auml;ge &middot; Stand: {stand}</footer>
</div>
</body>
</html>
"""
