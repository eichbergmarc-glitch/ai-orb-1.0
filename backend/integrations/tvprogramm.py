"""Das Fernsehprogramm fuer Synapse (22.11.2026).

Quelle: die freie XMLTV-Programmzeitschrift aus dem Projekt TV7_EPG_Data
(github.com/mathewmeconry/TV7_EPG_Data), naechtlich erneuert, rund 240
Sender mit Schweizer Programm (SRF, 3+, CH-Fenster von RTL/SAT.1/ProSieben,
Regionalsender) fuer etwa eine Woche. Sunrise selbst gibt sein Programm nur
angemeldeten Kunden heraus; die Sender sind aber dieselben.

Die Datei (gut 12 MB gepackt) wird hoechstens alle 12 Stunden geholt und in
eine kleine SQLite-Datenbank uebertragen. Abfragen laufen dann in
Millisekunden.
"""

from __future__ import annotations

import datetime as _dt
import gzip
import re
import sqlite3
import threading
import time
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from backend.system.logging_setup import get_logger

logger = get_logger(__name__)

QUELLE = "https://github.com/mathewmeconry/TV7_EPG_Data/raw/master/tv7_epg.xml.gz"
ERNEUERN_NACH = 12 * 3600
_SPERRE = threading.Lock()

#: Die Sender, die bei "was laeuft" ohne Angabe gezeigt werden.
HAUPTSENDER = (
    "srf1", "srfzwei", "srfinfo", "3plus", "daserste", "zdf", "arted", "3sat",
    "rtl(schweiz)", "sat.1(schweiz)", "prosieben(schweiz)", "vox(schweiz)",
    "kabeleins(schweiz)", "orf1", "orf2", "4plus", "5plus", "6plus", "tvplus",
)

#: Deutsche Arten -> Kategorien der Quelle.
ARTEN: dict[str, tuple[str, ...]] = {
    "film": ("Movie",),
    "serie": ("Series",),
    "doku": ("Documentary", "Reportage"),
    "dokumentation": ("Documentary", "Reportage"),
    "krimi": ("Crime",),
    "komoedie": ("Comedy",),
    "action": ("Action",),
    "drama": ("Drama",),
    "sport": ("Sport", "Sports", "Football", "Ice Hockey", "Tennis", "Skiing"),
    "nachrichten": ("News",),
    "show": ("Entertainment", "Game-Show", "Talk-Show", "Reality"),
    "kinder": ("Kids", "Animation"),
    "musik": ("Music",),
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS sender(id TEXT PRIMARY KEY, name TEXT);
CREATE TABLE IF NOT EXISTS sendung(
    sender TEXT, start INTEGER, ende INTEGER, titel TEXT, untertitel TEXT,
    beschreibung TEXT, kategorien TEXT, jahr TEXT, folge TEXT);
CREATE INDEX IF NOT EXISTS sendung_zeit ON sendung(start, ende);
CREATE TABLE IF NOT EXISTS stand(schluessel TEXT PRIMARY KEY, wert TEXT);
"""


def _ordner() -> Path:
    from backend.utils.paths import get_data_dir

    ordner = get_data_dir() / "tv"
    ordner.mkdir(parents=True, exist_ok=True)
    return ordner


def _zeit(xmlzeit: str) -> int:
    # "20261122201000 +0100"
    teile = (xmlzeit or "").split()
    basis = _dt.datetime.strptime(teile[0][:14], "%Y%m%d%H%M%S")
    versatz = teile[1] if len(teile) > 1 else "+0000"
    vz = 1 if versatz[0] == "+" else -1
    delta = _dt.timedelta(hours=int(versatz[1:3]), minutes=int(versatz[3:5]))
    return int((basis - vz * delta).replace(tzinfo=_dt.timezone.utc).timestamp())


def _schluessel(name: str) -> str:
    return re.sub(r"[\s_-]+", "", str(name or "").lower()).replace("+", "plus")


def aktualisieren(*, erzwingen: bool = False) -> int:
    """Holt die Programmzeitschrift, wenn sie aelter als 12 Stunden ist."""

    with _SPERRE:
        db = _ordner() / "programm.db"
        con = sqlite3.connect(db)
        try:
            con.executescript(SCHEMA)
            stand = con.execute("SELECT wert FROM stand WHERE schluessel='geholt'").fetchone()
            if stand and not erzwingen and time.time() - float(stand[0]) < ERNEUERN_NACH:
                return 0
            anfrage = urllib.request.Request(QUELLE, headers={"User-Agent": "AI-Orb/Synapse"})
            with urllib.request.urlopen(anfrage, timeout=90) as antwort:  # noqa: S310 - feste Quelle
                roh = gzip.decompress(antwort.read())
            wurzel = ET.fromstring(roh)
            sender = [(c.get("id", ""), c.findtext("display-name") or "") for c in wurzel.findall("channel")]
            jetzt = time.time() - 6 * 3600
            zeilen = []
            for p in wurzel.iterfind("programme"):
                try:
                    start, ende = _zeit(p.get("start", "")), _zeit(p.get("stop", ""))
                except (ValueError, IndexError):
                    continue
                if ende < jetzt:
                    continue
                zeilen.append((
                    p.get("channel", ""), start, ende, p.findtext("title") or "",
                    p.findtext("sub-title") or "", (p.findtext("desc") or "")[:600],
                    ",".join(c.text or "" for c in p.findall("category")),
                    p.findtext("date") or "", p.findtext("episode-num") or "",
                ))
            con.execute("DELETE FROM sender")
            con.execute("DELETE FROM sendung")
            con.executemany("INSERT OR REPLACE INTO sender VALUES (?,?)", sender)
            con.executemany("INSERT INTO sendung VALUES (?,?,?,?,?,?,?,?,?)", zeilen)
            con.execute("INSERT OR REPLACE INTO stand VALUES ('geholt', ?)", (str(time.time()),))
            con.commit()
            logger.info("TV-Programm aktualisiert: %d Sender, %d Sendungen.", len(sender), len(zeilen))
            return len(zeilen)
        finally:
            con.close()


def _verbindung() -> sqlite3.Connection:
    try:
        aktualisieren()
    except Exception as fehler:  # noqa: BLE001 - ein altes Programm ist besser als keins
        logger.info("TV-Programm nicht erneuert: %s", fehler)
    con = sqlite3.connect(_ordner() / "programm.db")
    con.executescript(SCHEMA)
    return con


def zeitfenster(wann: str, *, jetzt: _dt.datetime | None = None) -> tuple[int, int, str]:
    """'jetzt', 'heute abend', 'morgen', 'morgen abend', '20:15', '24.11. 20:00' -> (von, bis, Beschreibung)."""

    jetzt = jetzt or _dt.datetime.now()
    w = " ".join(str(wann or "jetzt").lower().split())
    tag = jetzt.date()
    if "übermorgen" in w or "uebermorgen" in w:
        tag += _dt.timedelta(days=2)
    elif "morgen" in w:
        tag += _dt.timedelta(days=1)
    treffer = re.search(r"(\d{1,2})\.(\d{1,2})\.?(\d{2,4})?", w)
    if treffer:
        jahr = int(treffer.group(3) or tag.year)
        jahr += 2000 if jahr < 100 else 0
        tag = _dt.date(jahr, int(treffer.group(2)), int(treffer.group(1)))
        w = w.replace(treffer.group(0), " ")
    uhr = re.search(r"(\d{1,2})(?:[:.h](\d{2}))?\s*(?:uhr)?\b", w)
    if "abend" in w or "primetime" in w:
        von = _dt.datetime.combine(tag, _dt.time(19, 45)); bis = von + _dt.timedelta(hours=4)
        text = "am Abend"
    elif "nacht" in w:
        von = _dt.datetime.combine(tag, _dt.time(22, 30)); bis = von + _dt.timedelta(hours=4)
        text = "in der Nacht"
    elif "nachmittag" in w:
        von = _dt.datetime.combine(tag, _dt.time(13, 0)); bis = von + _dt.timedelta(hours=5)
        text = "am Nachmittag"
    elif "morgen" in w and not uhr and tag != jetzt.date() and "abend" not in w:
        von = _dt.datetime.combine(tag, _dt.time(6, 0)); bis = von + _dt.timedelta(hours=18)
        text = "den ganzen Tag"
    elif uhr:
        von = _dt.datetime.combine(tag, _dt.time(int(uhr.group(1)) % 24, int(uhr.group(2) or 0)))
        bis = von + _dt.timedelta(minutes=1)
        text = f"um {von:%H:%M}"
    elif "heute" in w and "jetzt" not in w:
        von = max(jetzt, _dt.datetime.combine(tag, _dt.time(6, 0))); bis = _dt.datetime.combine(tag, _dt.time(23, 59))
        text = "heute"
    else:
        von = jetzt; bis = jetzt + _dt.timedelta(minutes=1)
        text = "jetzt"
    if tag != jetzt.date():
        text += f" ({tag:%d.%m.})"
    return int(von.timestamp()), int(bis.timestamp()), text


def _arten_filter(art: str) -> tuple[str, ...]:
    a = _schluessel(art).replace("ö", "oe")
    for name, kategorien in ARTEN.items():
        if a.startswith(name[:4]):
            return kategorien
    return ()


def suchen(*, sender: str = "", wann: str = "jetzt", suche: str = "", art: str = "",
           anzahl: int = 25) -> tuple[list[dict[str, Any]], str]:
    von, bis, wann_text = zeitfenster(wann)
    con = _verbindung()
    try:
        alle = dict(con.execute("SELECT id, name FROM sender").fetchall())
        bedingungen = ["s.ende > ?", "s.start < ?"]
        werte: list[Any] = [von, bis]
        if suche.strip():
            # Titelsuche: ab jetzt, die ganze Woche
            bedingungen = ["s.ende > ?", "(s.titel LIKE ? OR s.untertitel LIKE ?)"]
            muster = f"%{suche.strip()}%"
            werte = [int(time.time()) if wann in ("", "jetzt") else von, muster, muster]
        wahl = []
        if sender.strip():
            for teil in re.split(r"[,;/]| und ", sender):
                k = _schluessel(teil)
                if not k:
                    continue
                wahl += [i for i, n in alle.items() if _schluessel(n) == k or i == k]
                if not wahl:
                    wahl += [i for i, n in alle.items() if k in _schluessel(n)]
        elif not suche.strip():
            wahl = [i for i in alle if _schluessel(i) in HAUPTSENDER or _schluessel(alle[i]) in HAUPTSENDER]
        if wahl:
            bedingungen.append(f"s.sender IN ({','.join('?' * len(wahl))})")
            werte += wahl
        kategorien = _arten_filter(art) if art else ()
        if kategorien:
            teile = ["s.kategorien LIKE ?" for _ in kategorien]
            werte_art: list[Any] = [f"%{k}%" for k in kategorien]
            # Die Quelle vergibt Kategorien lueckenhaft - darum Ersatzmerkmale.
            if "Movie" in kategorien:
                teile.append("((s.ende - s.start) >= 4800 AND s.kategorien NOT LIKE '%Series%' "
                             "AND s.kategorien NOT LIKE '%News%' AND s.kategorien NOT LIKE '%Sport%' "
                             "AND (s.untertitel = '' OR s.untertitel = s.titel) "
                             "AND s.titel NOT LIKE '%DOK%' AND s.titel NOT LIKE '%Fußball%' "
                             "AND s.titel NOT LIKE '%Fussball%')")
            if "Documentary" in kategorien:
                teile += ["s.titel LIKE '%DOK%'", "s.titel LIKE '%Doku%'", "s.titel LIKE '%Reportage%'"]
            if "Series" in kategorien:
                teile.append("(s.untertitel <> '' AND s.untertitel <> s.titel AND (s.ende - s.start) <= 4200)")
            bedingungen.append("(" + " OR ".join(teile) + ")")
            werte += werte_art
        zeilen = con.execute(
            "SELECT s.sender, s.start, s.ende, s.titel, s.untertitel, s.beschreibung, s.kategorien, s.jahr "
            f"FROM sendung s WHERE {' AND '.join(bedingungen)} ORDER BY s.start LIMIT ?",
            (*werte, max(1, min(80, anzahl))),
        ).fetchall()
    finally:
        con.close()
    gesehen: set[tuple[str, int, str]] = set()
    eindeutig = []
    for z in zeilen:
        schluessel = (z[0], z[1], z[3])
        if schluessel not in gesehen:
            gesehen.add(schluessel)
            eindeutig.append(z)
    zeilen = eindeutig
    ergebnis = [{
        "sender": alle.get(z[0], z[0]), "sender_id": z[0],
        "start": _dt.datetime.fromtimestamp(z[1]), "ende": _dt.datetime.fromtimestamp(z[2]),
        "titel": z[3], "untertitel": z[4] if z[4] != z[3] else "", "beschreibung": z[5],
        "kategorien": z[6], "jahr": z[7],
    } for z in zeilen]
    return ergebnis, wann_text


def zeile(s: dict[str, Any], *, mit_text: bool = False) -> str:
    tag = "" if s["start"].date() == _dt.date.today() else f"{s['start']:%a %d.%m.} "
    teil = f"{tag}{s['start']:%H:%M}-{s['ende']:%H:%M} {s['sender']}: {s['titel']}"
    if s["untertitel"]:
        teil += f" - {s['untertitel']}"
    extra = ", ".join(x for x in (s["kategorien"].replace(",", "/"), s["jahr"]) if x)
    if extra:
        teil += f" ({extra})"
    if mit_text and s["beschreibung"]:
        teil += f". {s['beschreibung'][:160]}"
    return teil
