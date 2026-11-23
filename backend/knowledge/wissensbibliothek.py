"""Synapses Wissensbibliothek - lokales Nachschlagewerk (22.11.2026).

Zwei SQLite-Datenbanken mit Volltextsuche (FTS5), beide unter
``%APPDATA%\\AI-Orb\\data\\wissen``:

* ``synapse_wikipedia_de.db`` - die deutsche Wikipedia (Einleitungen und bei
  langen Artikeln zwei Zusatzabschnitte), einmal in Colab gebaut, nur gelesen.
* ``eigenes_wissen.db`` - was Synapse laufend dazulernt: Schlagzeilen aus dem
  Nachrichtenlauf und Treffer aus Internetsuchen, jeweils mit Quelle und Datum.

Wozu: Das lokale Modell (synapse_lokal, 4 Milliarden Parameter) hat wenig
Weltwissen und erfindet, wenn es raten muss. Bekommt es vor der Antwort die
zwei, drei passenden Stellen mitgeliefert, erklaert es richtig und kann sagen,
woher es etwas weiss. Neues Wissen kommt ohne Nachtrainieren dazu - sofort.

Bewusst ohne Einbettungsmodell: FTS5 ist in Pythons SQLite eingebaut, sucht in
Millisekunden ueber Millionen Abschnitte, braucht kaum Arbeitsspeicher und
keinen Download. Fehlt eine Datenbank, liefert die Suche einfach nichts - der
Orb laeuft dann wie bisher.
"""
from __future__ import annotations

import re
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:  # im Orb
    from backend.system.logging_setup import get_logger
    from backend.utils.paths import get_data_dir
    logger = get_logger(__name__)
except Exception:  # eigenstaendig (Tests)
    import logging
    logger = logging.getLogger("wissensbibliothek")

    def get_data_dir() -> Path:  # type: ignore[misc]
        return Path.cwd()


WIKIPEDIA_DATEI = "synapse_wikipedia_de.db"
EIGENES_DATEI = "eigenes_wissen.db"

STOPP = frozenset("""
der die das den dem des ein eine einen einem einer eines und oder aber auch nicht ist sind war waren sein
wird werden wurde wurden hat haben hatte für von mit auf aus bei nach über unter durch zum zur als wie wenn
dass sich man kann muss ich du er sie es wir ihr mir dir mich dich uns euch was wer wo wann warum wieso weshalb
welche welcher welches welchen wieviel viele viel mal doch noch schon ja nein bitte erklär erkläre erklären
sag sage sagen kannst könntest weisst weißt wissen erzähl erzähle erzählen mir uns kurz einfach genau eigentlich
gibt gibts gib geben heisst heißt bedeutet bedeutung meinst meint hey hallo synapse etwas mehr denn so dann da
geht gehts gut schlecht heute gestern morgen jetzt gerade bin bist hast habe hab will willst möchte möchtest
""".split())
_WORT = re.compile(r"[0-9A-Za-zÀ-ÖØ-öø-ÿ]+")

# Smalltalk, Befehle und Gefuehle brauchen kein Nachschlagewerk.
_KEIN_NACHSCHLAGEN = re.compile(
    r"^\s*(hey |hallo |ok |okay )?(synapse,? )?(danke|tschüss|bis (bald|später|nachher)|gute nacht|guten (morgen|abend)|"
    r"wie geht('?s| es)|alles klar|ja|nein|genau|stimmt|super|cool|mir geht|ich bin (müde|traurig|froh|glücklich)|"
    r"öffne|starte|spiel|stopp|stop|wechsle|zeig mir|mach |stell )", re.I)

EIGENES_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS wissen USING fts5(
    titel, text, quelle UNINDEXED, art UNINDEXED, datum UNINDEXED,
    tokenize = 'unicode61 remove_diacritics 2'
);
"""


def suchbegriffe(frage: str) -> list[str]:
    begriffe: list[str] = []
    for w in _WORT.findall(frage or ""):
        k = w.lower()
        zahlwort = any(z.isdigit() for z in k)
        if (len(k) < 3 and not zahlwort) or k in STOPP or k in begriffe:
            continue
        begriffe.append(k)
    return begriffe[:8]


def stamm(begriff: str) -> str:
    """Grober Wortstamm: lange Woerter verlieren die Endung (Gründung -> Gründu*)."""
    if begriff.isdigit() or len(begriff) <= 5:
        return begriff
    return begriff[: max(5, len(begriff) - 2)]


def fts_ausdruck(begriffe: list[str], verknuepfung: str = "OR") -> str:
    teile = [f'"{b}"' if any(z.isdigit() for z in b) else f'"{stamm(b)}"*' for b in begriffe]
    return f" {verknuepfung} ".join(teile)


# Seiten ohne eigenen Inhalt: Titellisten, Redewendungen, Begriffsklaerungen.
_UNERGIEBIG = re.compile(r"(ist der Titel (folgender|von)|ist der Name folgender|steht für:|bezeichnet:|"
                         r"^redensartlich|Filmtitel|bezeichnet folgende)", re.I)


@dataclass
class Fundstelle:
    titel: str
    text: str
    quelle: str
    herkunft: str          # "wikipedia" oder die Art im eigenen Wissen
    datum: str = ""
    abdeckung: float = 0.0
    titel_treffer: int = 0
    rang: float = 0.0

    def zeile(self, max_zeichen: int) -> str:
        text = self.text.strip().replace("\n", " ")
        if len(text) > max_zeichen:
            schnitt = text[:max_zeichen]
            ende = schnitt.rfind(". ")
            text = (schnitt[: ende + 1] if ende > max_zeichen * 0.5 else schnitt.rsplit(" ", 1)[0] + " …")
        if self.herkunft == "wikipedia":
            woher = f"Wikipedia{', Stand ' + self.datum if self.datum else ''}"
        elif self.herkunft == "nachricht":
            woher = f"Nachricht vom {self.datum}" if self.datum else "Nachricht"
        else:
            woher = f"gefunden am {self.datum}" if self.datum else "eigenes Wissen"
        return f"• «{self.titel}» ({woher}): {text}"


class Wissensbibliothek:
    def __init__(self, ordner: Path | None = None) -> None:
        self._ordner = Path(ordner) if ordner else get_data_dir() / "wissen"
        self._lock = threading.Lock()
        self._wiki: sqlite3.Connection | None = None
        self._wiki_stand = ""
        self._wiki_versucht = 0.0
        self._eigen: sqlite3.Connection | None = None

    # --- Verbindungen ------------------------------------------------------
    @property
    def ordner(self) -> Path:
        return self._ordner

    def _wikipedia(self) -> sqlite3.Connection | None:
        if self._wiki is not None:
            return self._wiki
        if time.time() - self._wiki_versucht < 60:      # nicht bei jeder Frage auf die Platte schauen
            return None
        self._wiki_versucht = time.time()
        pfad = self._ordner / WIKIPEDIA_DATEI
        if not pfad.exists():
            return None
        try:
            con = sqlite3.connect(f"file:{pfad.as_posix()}?mode=ro", uri=True, check_same_thread=False)
            zeile = con.execute("SELECT wert FROM meta WHERE schluessel='stand'").fetchone()
            self._wiki_stand = zeile[0] if zeile else ""
            self._wiki = con
            anzahl = con.execute("SELECT wert FROM meta WHERE schluessel='artikel'").fetchone()
            logger.info("Wissensbibliothek geladen: %s Wikipedia-Artikel (Stand %s).",
                        anzahl[0] if anzahl else "?", self._wiki_stand or "?")
        except Exception as fehler:  # noqa: BLE001
            logger.warning("Wikipedia-Bibliothek nicht lesbar (%s): %s", pfad, fehler)
            self._wiki = None
        return self._wiki

    def _eigenes(self) -> sqlite3.Connection | None:
        if self._eigen is not None:
            return self._eigen
        try:
            self._ordner.mkdir(parents=True, exist_ok=True)
            con = sqlite3.connect(self._ordner / EIGENES_DATEI, check_same_thread=False)
            con.executescript(EIGENES_SCHEMA)
            self._eigen = con
        except Exception as fehler:  # noqa: BLE001
            logger.warning("Eigenes Wissen nicht verfuegbar: %s", fehler)
            self._eigen = None
        return self._eigen

    # --- Suchen ------------------------------------------------------------
    @staticmethod
    def _bewerten(zeilen, begriffe, herkunft, stand_fest="") -> list[Fundstelle]:
        ergebnis = []
        for zeile in zeilen:
            titel, text, quelle, art, datum, rang = zeile
            if _UNERGIEBIG.search(str(text)[:200]):
                continue
            heu = f"{titel} {text}".lower()
            abgedeckt = sum(1 for b in begriffe if stamm(b) in heu)
            titel_treffer = sum(1 for b in begriffe if stamm(b) in str(titel).lower())
            anteil = abgedeckt / len(begriffe)
            if anteil < 0.5 and not titel_treffer:
                continue
            ergebnis.append(Fundstelle(str(titel), str(text), str(quelle or ""),
                                       herkunft if herkunft == "wikipedia" else str(art or herkunft),
                                       stand_fest or str(datum or ""), round(anteil, 2), titel_treffer, float(rang)))
        return ergebnis

    def suche(self, frage: str, *, limit: int = 3) -> list[Fundstelle]:
        begriffe = suchbegriffe(frage)
        if not begriffe:
            return []
        funde: list[Fundstelle] = []
        varianten = [fts_ausdruck(begriffe, "AND")] + ([fts_ausdruck(begriffe, "OR")] if len(begriffe) > 1 else [])
        with self._lock:
            eigen = self._eigenes()
            if eigen is not None:
                for ausdruck in varianten:
                    try:
                        zeilen = eigen.execute(
                            "SELECT titel, text, quelle, art, datum, bm25(wissen, 3.0, 1.0) AS r FROM wissen "
                            "WHERE wissen MATCH ? ORDER BY r LIMIT 8", (ausdruck,)).fetchall()
                    except sqlite3.Error as fehler:
                        logger.debug("Suche im eigenen Wissen: %s", fehler)
                        break
                    gefunden = self._bewerten(zeilen, begriffe, "eigen")
                    if gefunden:
                        funde += gefunden
                        break
            wiki = self._wikipedia()
            if wiki is not None:
                for ausdruck in varianten:
                    try:
                        zeilen = wiki.execute(
                            "SELECT titel, text, url, '', '', bm25(artikel, 3.0, 1.0) AS r FROM artikel "
                            "WHERE artikel MATCH ? ORDER BY r LIMIT 15", (ausdruck,)).fetchall()
                    except sqlite3.Error as fehler:
                        logger.debug("Suche in Wikipedia: %s", fehler)
                        break
                    gefunden = self._bewerten(zeilen, begriffe, "wikipedia", self._wiki_stand)
                    if len(gefunden) >= 2 or ausdruck == varianten[-1]:
                        funde += gefunden
                        break
        # Eigenes (neueres) Wissen zuerst, dann Titeltreffer, Abdeckung, Rang.
        funde.sort(key=lambda f: (f.herkunft == "wikipedia", -f.abdeckung, f.rang, -f.titel_treffer))
        gesehen: set[str] = set()
        ergebnis: list[Fundstelle] = []
        for f in funde:
            schluessel = f.titel.lower()
            if schluessel in gesehen:
                continue
            gesehen.add(schluessel)
            ergebnis.append(f)
            if len(ergebnis) >= limit:
                break
        return ergebnis

    def kontext_fuer(self, frage: str, *, max_zeichen: int = 1400, limit: int = 3) -> str:
        """Kurzer Systemtext mit den passenden Stellen - oder '' wenn nichts passt."""
        if not frage or _KEIN_NACHSCHLAGEN.search(frage):
            return ""
        try:
            funde = self.suche(frage, limit=limit)
        except Exception:  # noqa: BLE001 - die Bibliothek darf nie die Antwort verhindern
            logger.debug("Nachschlagen fehlgeschlagen.", exc_info=True)
            return ""
        if not funde:
            return ""
        kopf = ("NACHSCHLAGEN: Passende Stellen aus deiner Wissensbibliothek. Stuetze dich darauf, wenn sie "
                "zur Frage passen, und erfinde nichts darueber hinaus. Passt nichts, ignoriere sie. Bei Zahlen "
                "und Daten nenne kurz die Herkunft (zum Beispiel «laut Wikipedia»).")
        je = max(250, (max_zeichen - len(kopf)) // len(funde))
        return "\n".join([kopf, *(f.zeile(je) for f in funde)])

    # --- Laufend lernen ----------------------------------------------------
    def merke(self, titel: str, text: str, *, quelle: str = "", art: str = "eigen", datum: str = "") -> bool:
        """Traegt neues Wissen ein. Dubletten (gleiche Quelle und Titel) werden aktualisiert."""
        titel, text = str(titel or "").strip(), str(text or "").strip()
        if not titel or len(titel) + len(text) < 15:
            return False
        datum = datum or time.strftime("%d.%m.%Y")
        with self._lock:
            con = self._eigenes()
            if con is None:
                return False
            try:
                if quelle:
                    con.execute("DELETE FROM wissen WHERE quelle = ? AND titel = ?", (quelle, titel))
                con.execute("INSERT INTO wissen(titel, text, quelle, art, datum) VALUES (?,?,?,?,?)",
                            (titel[:300], text[:2000], quelle[:500], art, datum))
                con.commit()
                return True
            except sqlite3.Error as fehler:
                logger.debug("Merken fehlgeschlagen: %s", fehler)
                return False

    def status(self) -> dict[str, Any]:
        info: dict[str, Any] = {"ordner": str(self._ordner)}
        with self._lock:
            wiki = self._wikipedia()
            if wiki is not None:
                meta = dict(wiki.execute("SELECT schluessel, wert FROM meta").fetchall())
                info["wikipedia"] = {"artikel": meta.get("artikel"), "abschnitte": meta.get("abschnitte"),
                                     "stand": meta.get("stand"), "quelle": meta.get("quelle")}
            else:
                info["wikipedia"] = None
            eigen = self._eigenes()
            info["eigenes_wissen"] = eigen.execute("SELECT count(*) FROM wissen").fetchone()[0] if eigen else None
        return info


_BIBLIOTHEK: Wissensbibliothek | None = None
_BIBLIOTHEK_LOCK = threading.Lock()


def bibliothek() -> Wissensbibliothek:
    global _BIBLIOTHEK
    with _BIBLIOTHEK_LOCK:
        if _BIBLIOTHEK is None:
            _BIBLIOTHEK = Wissensbibliothek()
        return _BIBLIOTHEK


# --- Zuschnitt fuer das lokale Gehirn ------------------------------------------

_WERKZEUG_START = "Dir stehen Werkzeuge zur Verfügung."
_SPRECHWEISE_START = "SPRECHWEISE (Pflicht"


def zusatzkontext_kuerzen(text: str, max_zeichen: int = 1000) -> str:
    """Wirft Werkzeugverzeichnis und Sprech-Markup-Anleitung weg, kuerzt den Rest.

    Das lokale Modell kann keine Werkzeuge aufrufen und kennt das Markup nicht;
    beides kostete auf der CPU nur Sekunden. Gedaechtnis und Suchtreffer stehen
    im Zusatzkontext vorn und bleiben erhalten.
    """
    text = str(text or "")
    for marke in (_WERKZEUG_START, _SPRECHWEISE_START):
        stelle = text.find(marke)
        if stelle >= 0:
            text = text[:stelle]
    text = text.strip()
    if len(text) > max_zeichen:
        text = text[:max_zeichen].rsplit("\n", 1)[0].strip()
    return text


def lokaler_kontext(weitere: list[str], frage: str, *, zusatz_hoechstens: int = 1000,
                    wissen_hoechstens: int = 1400) -> list[str]:
    """Systemteile fuer das lokale Gehirn: passende Bibliotheksstellen + knapper Zusatzkontext."""
    teile: list[str] = []
    wissen = bibliothek().kontext_fuer(frage, max_zeichen=wissen_hoechstens)
    if wissen:
        teile.append(wissen)
        logger.info("Nachgeschlagen fuer das lokale Gehirn: %d Zeichen.", len(wissen))
    zusatz = zusatzkontext_kuerzen("\n\n".join(t for t in weitere if t), zusatz_hoechstens)
    if zusatz:
        teile.append(zusatz)
    return teile
