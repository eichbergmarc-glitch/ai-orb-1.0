"""Synapse lernt dazu: Datensaetze, Webseiten und Dateien in die Wissensbibliothek.

Angelegt am 22.11.2026 auf Marcs Wunsch ("eine Funktion, um die
Wissensdatenbank zu aktualisieren und zu erweitern").

## Drei Quellen

* **Datensaetze von Hugging Face** - ``hf:rajpurkar/squad``. Die meisten
  offenen Datensaetze (auch die auf de.shaip.com verlinkten, etwa SQuAD,
  DBpedia, Natural Questions) liegen dort. Abgerufen wird ueber den
  oeffentlichen "Dataset Viewer" (datasets-server.huggingface.co), in
  Paketen zu 100 Zeilen - ohne Zusatzbibliothek und ohne den ganzen
  Datensatz herunterzuladen.
* **Webseiten** - eine Adresse; der Text wird in Abschnitte zerlegt.
* **Dateien** - .txt, .md, .csv, .json, .jsonl vom eigenen Rechner.

Alles landet in ``eigenes_wissen.db`` (Tabelle ``wissen``). Von dort holt
die Bibliothek es bei passenden Fragen in den Kontext - online wie offline.

## Was hier bewusst NICHT geschieht

Kein Training. Ein Datensatz wird *nachschlagbar*, nicht ins Modell
eingebrannt. Das ist schneller, jederzeit rueckgaengig zu machen
(``art`` = ``datensatz:<name>``) und braucht keinen Grafikprozessor.
"""

from __future__ import annotations

import csv
import html
import io
import json
import re
import sqlite3
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Iterable

from backend.system.logging_setup import get_logger

logger = get_logger(__name__)

HF_API = "https://datasets-server.huggingface.co"
_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AI-Orb/Synapse"
#: Obergrenze je Auftrag - schuetzt vor einem versehentlichen "lerne alles"
#: (SQuAD hat 87 599 Zeilen, Natural Questions 300 000).
HOECHSTENS = 20000
_ABSCHNITT = 900  # Zeichen je Wissenseintrag (die Bibliothek kuerzt bei 2000)

#: Bekannte gute Quellen - damit Synapse auf "lerne Allgemeinwissen" nicht
#: raten muss. Zuerst deutsche.
VORSCHLAEGE: dict[str, str] = {
    "hf:rajpurkar/squad": "SQuAD - 87 000 Wissensfragen mit Antworttext (Englisch, Wikipedia)",
    "hf:fancyzhx/dbpedia_14": "DBpedia - 560 000 Kurzbeschreibungen von Dingen, Orten, Personen (Englisch)",
    "hf:google-research-datasets/natural_questions": "Natural Questions - echte Google-Fragen (Englisch, sehr gross)",
    "hf:microsoft/ms_marco": "MS MARCO - Suchfragen mit Textstellen (Englisch)",
}


# --- Hilfen ----------------------------------------------------------------

def _holen(url: str, *, zeitlimit: int = 30) -> bytes:
    anfrage = urllib.request.Request(url, headers={"User-Agent": _AGENT, "Accept": "*/*"})
    with urllib.request.urlopen(anfrage, timeout=zeitlimit) as antwort:  # noqa: S310 - feste Ziele
        return antwort.read()


def _json(url: str) -> dict[str, Any]:
    letzter: Exception | None = None
    for versuch in range(3):
        try:
            return json.loads(_holen(url).decode("utf-8"))
        except urllib.error.HTTPError as fehler:
            if fehler.code in (429, 500, 502, 503):
                letzter = fehler
                time.sleep(2 + 3 * versuch)
                continue
            try:
                inhalt = json.loads(fehler.read().decode("utf-8"))
            except Exception:  # noqa: BLE001
                inhalt = {}
            raise ImportFehler(str(inhalt.get("error") or f"HTTP {fehler.code}")) from fehler
        except (urllib.error.URLError, TimeoutError) as fehler:
            letzter = fehler
            time.sleep(2)
    raise ImportFehler(f"Der Dienst antwortet nicht: {letzter}")


class ImportFehler(RuntimeError):
    """Ein Import liess sich nicht durchfuehren - die Nachricht ist fuer Marc."""


def _abschnitte(text: str, laenge: int = _ABSCHNITT) -> list[str]:
    """Zerlegt langen Text an Absaetzen/Saetzen in handliche Stuecke."""

    text = re.sub(r"[ \t]+", " ", str(text or "")).strip()
    if len(text) <= laenge:
        return [text] if text else []
    teile: list[str] = []
    aktuell = ""
    for satz in re.split(r"(?<=[.!?])\s+|\n{2,}", text):
        if len(aktuell) + len(satz) + 1 > laenge and aktuell:
            teile.append(aktuell.strip())
            aktuell = ""
        aktuell += " " + satz
    if aktuell.strip():
        teile.append(aktuell.strip())
    return teile


def _zeichenkette(wert: Any) -> str:
    if isinstance(wert, str):
        return wert
    if isinstance(wert, dict):
        # SQuAD: {"text": ["Antwort"], "answer_start": [..]}
        for schluessel in ("text", "value", "label"):
            if schluessel in wert:
                return _zeichenkette(wert[schluessel])
        return ""
    if isinstance(wert, list):
        return "; ".join(s for s in (_zeichenkette(w) for w in wert[:5]) if s)
    if isinstance(wert, (int, float)):
        return str(wert)
    return ""


def zeile_zu_eintrag(zeile: dict[str, Any], name: str) -> tuple[str, str] | None:
    """Macht aus einer Datensatzzeile (Titel, Text) - je nach Aufbau.

    Frage-Antwort-Datensaetze werden zu "Frage: ... Antwort: ... (Kontext)",
    Lexikon-Datensaetze zu Titel + Beschreibung, alles andere zu den
    zusammengefuegten Textfeldern.
    """

    feld = {str(k).lower(): v for k, v in zeile.items()}
    frage = _zeichenkette(feld.get("question") or feld.get("query") or feld.get("frage") or "")
    antwort = _zeichenkette(feld.get("answers") or feld.get("answer") or feld.get("antwort") or "")
    kontext = _zeichenkette(feld.get("context") or feld.get("passage") or feld.get("kontext") or "")
    titel = _zeichenkette(feld.get("title") or feld.get("titel") or feld.get("name") or "")
    titel = titel.replace("_", " ").strip()
    if frage and (antwort or kontext):
        text = f"Frage: {frage.strip()} Antwort: {antwort.strip() or '-'}"
        if kontext:
            text += f" Hintergrund: {kontext.strip()}"
        return (titel or frage)[:300], text
    inhalt = _zeichenkette(feld.get("content") or feld.get("text") or feld.get("abstract")
                           or feld.get("description") or feld.get("beschreibung") or "")
    if not inhalt:
        inhalt = " | ".join(f"{k}: {v}" for k, v in feld.items()
                            if isinstance(v, str) and 3 < len(v) < 2000 and k not in ("id", "url"))
    if not inhalt.strip():
        return None
    if not titel:
        titel = re.split(r"(?<=[.!?])\s", inhalt.strip(), maxsplit=1)[0][:120]
    return titel[:300], inhalt.strip()


# --- Eintragen -------------------------------------------------------------

def eintragen(eintraege: Iterable[tuple[str, str]], *, quelle: str, art: str) -> int:
    """Schreibt viele Eintraege in einem Zug (eine Transaktion statt tausend)."""

    from backend.knowledge.wissensbibliothek import bibliothek

    bib = bibliothek()
    datum = time.strftime("%d.%m.%Y")
    zeilen = []
    for titel, text in eintraege:
        for nummer, stueck in enumerate(_abschnitte(text)):
            if len(titel) + len(stueck) < 15:
                continue
            zeilen.append(((titel if nummer == 0 else f"{titel} ({nummer + 1})")[:300],
                           stueck[:2000], quelle[:500], art, datum))
    if not zeilen:
        return 0
    with bib._lock:  # noqa: SLF001 - dieselbe Sperre wie merke()
        con = bib._eigenes()  # noqa: SLF001
        if con is None:
            raise ImportFehler("Die Wissensbibliothek ist nicht verfuegbar.")
        try:
            con.executemany(
                "INSERT INTO wissen(titel, text, quelle, art, datum) VALUES (?,?,?,?,?)", zeilen
            )
            con.commit()
        except sqlite3.Error as fehler:
            raise ImportFehler(f"Eintragen fehlgeschlagen: {fehler}") from fehler
    return len(zeilen)


def vergessen(art: str) -> int:
    """Entfernt alles, was mit dieser Herkunft (z. B. 'datensatz:squad') kam."""

    from backend.knowledge.wissensbibliothek import bibliothek

    bib = bibliothek()
    with bib._lock:  # noqa: SLF001
        con = bib._eigenes()  # noqa: SLF001
        if con is None:
            return 0
        anzahl = con.execute("DELETE FROM wissen WHERE art = ?", (art,)).rowcount
        con.commit()
        return int(anzahl or 0)


# --- Quellen ---------------------------------------------------------------

def aus_huggingface(name: str, *, anzahl: int = 1000, ab: int = 0, split: str = "") -> dict[str, Any]:
    """Holt Zeilen eines Hugging-Face-Datensatzes ueber den Dataset Viewer."""

    name = name.strip().removeprefix("hf:").strip("/ ")
    if not re.fullmatch(r"[\w.-]+(/[\w.-]+)?", name):
        raise ImportFehler(f"'{name}' ist kein gueltiger Datensatzname (Form: besitzer/name).")
    teile = _json(f"{HF_API}/splits?dataset={urllib.parse.quote(name, safe='/')}")
    splits = teile.get("splits") or []
    if not splits:
        raise ImportFehler(str(teile.get("error") or "Der Datensatz hat keine lesbaren Teile."))
    wahl = next((s for s in splits if split and s.get("split") == split), None) \
        or next((s for s in splits if s.get("split") == "train"), None) or splits[0]
    config, teil = wahl["config"], wahl["split"]
    anzahl = max(1, min(HOECHSTENS, int(anzahl)))
    kurz = name.split("/")[-1]
    art = f"datensatz:{kurz}"
    eingetragen = gelesen = 0
    gesamt = None
    versatz = max(0, int(ab))
    while gelesen < anzahl:
        paket = min(100, anzahl - gelesen)
        daten = _json(
            f"{HF_API}/rows?dataset={urllib.parse.quote(name, safe='/')}"
            f"&config={urllib.parse.quote(config)}&split={urllib.parse.quote(teil)}"
            f"&offset={versatz}&length={paket}"
        )
        gesamt = daten.get("num_rows_total", gesamt)
        zeilen = [z.get("row") or {} for z in daten.get("rows") or []]
        if not zeilen:
            break
        eintraege = [e for e in (zeile_zu_eintrag(z, kurz) for z in zeilen) if e]
        eingetragen += eintragen(eintraege, quelle=f"https://huggingface.co/datasets/{name}", art=art)
        gelesen += len(zeilen)
        versatz += len(zeilen)
        if gesamt is not None and versatz >= int(gesamt):
            break
    logger.info("Datensatz %s: %d Zeilen gelesen, %d Eintraege (ab %d, gesamt %s).",
                name, gelesen, eingetragen, ab, gesamt)
    return {"name": name, "teil": f"{config}/{teil}", "gelesen": gelesen,
            "eingetragen": eingetragen, "gesamt": gesamt, "weiter_ab": versatz, "art": art}


def _html_zu_text(roh: str) -> tuple[str, str]:
    titel = re.search(r"<title[^>]*>(.*?)</title>", roh, re.I | re.S)
    roh = re.sub(r"(?is)<(script|style|nav|footer|header|noscript|svg)[^>]*>.*?</\1>", " ", roh)
    roh = re.sub(r"(?i)<br\s*/?>|</(p|div|li|h[1-6]|tr)>", "\n\n", roh)
    text = html.unescape(re.sub(r"<[^>]+>", " ", roh))
    text = re.sub(r"\n\s*\n+", "\n\n", re.sub(r"[ \t\r]+", " ", text)).strip()
    return (html.unescape(titel.group(1)).strip() if titel else ""), text


def aus_webseite(url: str) -> dict[str, Any]:
    if not re.match(r"https?://", url):
        raise ImportFehler("Die Adresse muss mit http:// oder https:// beginnen.")
    try:
        roh = _holen(url).decode("utf-8", errors="replace")
    except Exception as fehler:  # noqa: BLE001
        raise ImportFehler(f"Die Seite liess sich nicht laden: {fehler}") from fehler
    titel, text = _html_zu_text(roh)
    titel = titel or urllib.parse.urlparse(url).netloc
    absaetze = [a for a in text.split("\n\n") if len(a.split()) >= 8]
    if not absaetze:
        raise ImportFehler("Auf der Seite steht kein zusammenhaengender Text.")
    eingetragen = eintragen([(titel, "\n\n".join(absaetze))], quelle=url, art="webseite")
    return {"name": titel, "eingetragen": eingetragen, "art": "webseite"}


def aus_datei(pfad: str, *, anzahl: int = HOECHSTENS) -> dict[str, Any]:
    datei = Path(pfad).expanduser()
    if not datei.is_file():
        raise ImportFehler(f"Die Datei {datei} gibt es nicht.")
    endung = datei.suffix.lower()
    inhalt = datei.read_text(encoding="utf-8", errors="replace")
    eintraege: list[tuple[str, str]] = []
    if endung == ".jsonl":
        for zeile in inhalt.splitlines()[:anzahl]:
            with __import__("contextlib").suppress(json.JSONDecodeError):
                obj = json.loads(zeile)
                if isinstance(obj, dict) and (e := zeile_zu_eintrag(obj, datei.stem)):
                    eintraege.append(e)
    elif endung == ".json":
        obj = json.loads(inhalt)
        liste = obj if isinstance(obj, list) else (obj.get("data") or obj.get("rows") or [obj])
        for z in liste[:anzahl]:
            if isinstance(z, dict) and (e := zeile_zu_eintrag(z, datei.stem)):
                eintraege.append(e)
    elif endung in (".csv", ".tsv"):
        leser = csv.DictReader(io.StringIO(inhalt), delimiter="\t" if endung == ".tsv" else ",")
        for nummer, z in enumerate(leser):
            if nummer >= anzahl:
                break
            if (e := zeile_zu_eintrag(z, datei.stem)):
                eintraege.append(e)
    else:  # .txt, .md und alles Lesbare
        eintraege.append((datei.stem.replace("_", " "), inhalt))
    eingetragen = eintragen(eintraege, quelle=str(datei), art=f"datei:{datei.stem}")
    return {"name": datei.name, "eingetragen": eingetragen, "art": f"datei:{datei.stem}"}


def aufnehmen(quelle: str, *, anzahl: int = 1000, ab: int = 0) -> dict[str, Any]:
    """Waehlt den passenden Weg fuer eine Quelle."""

    quelle = str(quelle or "").strip()
    if not quelle:
        raise ImportFehler("Es fehlt die Quelle.")
    treffer = re.match(r"https?://huggingface\.co/datasets/([\w.-]+/[\w.-]+)", quelle)
    if treffer:
        return aus_huggingface(treffer.group(1), anzahl=anzahl, ab=ab)
    if quelle.startswith("hf:"):
        return aus_huggingface(quelle, anzahl=anzahl, ab=ab)
    if re.match(r"https?://", quelle):
        return aus_webseite(quelle)
    if re.fullmatch(r"[\w.-]+/[\w.-]+", quelle) and not Path(quelle).expanduser().exists():
        return aus_huggingface(quelle, anzahl=anzahl, ab=ab)
    return aus_datei(quelle, anzahl=anzahl)


def bestand() -> list[tuple[str, int]]:
    """Was die Bibliothek nach Herkunft enthaelt."""

    from backend.knowledge.wissensbibliothek import bibliothek

    bib = bibliothek()
    with bib._lock:  # noqa: SLF001
        con = bib._eigenes()  # noqa: SLF001
        if con is None:
            return []
        return [(str(a), int(n)) for a, n in
                con.execute("SELECT art, count(*) FROM wissen GROUP BY art ORDER BY 2 DESC").fetchall()]
