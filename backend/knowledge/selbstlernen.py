"""Synapse erweitert ihr Wissen selbst (23.11.2026).

Drei Wege, alle ohne Kosten:

1. **Wissensluecken merken.** Jede Wissensfrage von Marc wird im Hintergrund
   gegen die Bibliothek geprueft. Findet sich nichts Passendes, kommt die
   Frage auf die Lernliste (``wissen/luecken.jsonl``).
2. **Lernlauf.** Alle zwei Stunden (zuerst 10 Minuten nach dem Start) holt
   Synapse zu bis zu acht offenen Luecken den passenden, AKTUELLEN Artikel
   aus der deutschen Wikipedia (die eingebaute Kopie ist von 2023) und nimmt
   ihn in ``eigenes_wissen.db`` auf (Art ``selbst gelernt``).
3. **Interessengebiete.** Einmal pro Woche frischt sie die Themen aus
   ``wissen.interessen`` (config.yaml) auf.

Dazu kommt, was schon seit dem 22.11. von selbst gespeichert wird: jede
Internetsuche und jede abgerufene Nachricht.
"""

from __future__ import annotations

import json
import re
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from backend.system.logging_setup import get_logger

logger = get_logger(__name__)

WIKI_API = "https://de.wikipedia.org/w/api.php"
_AGENT = "AI-Orb-Synapse/1.0 (persoenlicher Sprachassistent; Lernlauf)"
TAKT = 2 * 3600
ERSTER_LAUF = 600
PRO_LAUF = 8
_SPERRE = threading.Lock()
_gesehen: list[str] = []
_gestartet = False

_FRAGEWORT = re.compile(
    r"\b(was|wer|wie|wo|wann|warum|wieso|weshalb|welche[rsmn]?|erklär|erklaer|erzähl|erzaehl|"
    r"bedeutet|heisst|heißt|gibt es|kennst du|weisst du|weißt du)\b", re.I)
_KEIN_LERNSTOFF = re.compile(
    r"(wetter|uhrzeit|wie spät|wie spaet|nachrichten|news|termin|kalender|erinner|mail|"
    r"musik|tidal|spiel |fernseh|tv|läuft|laeuft|timer|wecker|licht|lauter|leiser|pause|"
    r"wie geht|mir geht|bin müde|bin traurig|dein name|wer bist du|kannst du mich)", re.I)


def _ordner() -> Path:
    from backend.utils.paths import get_data_dir

    ordner = get_data_dir() / "wissen"
    ordner.mkdir(parents=True, exist_ok=True)
    return ordner


def _json(url: str) -> dict[str, Any]:
    anfrage = urllib.request.Request(url, headers={"User-Agent": _AGENT})
    with urllib.request.urlopen(anfrage, timeout=20) as antwort:  # noqa: S310 - feste Quelle
        return json.loads(antwort.read().decode("utf-8"))


# --- 1. Luecken erkennen ------------------------------------------------------

def ist_wissensfrage(text: str) -> bool:
    t = " ".join(str(text or "").split())
    t = re.sub(r"^(hey |hallo |ok |okay )?synapse[,.!]?\s*", "", t, flags=re.I)
    if len(t.split()) < 3 or _KEIN_LERNSTOFF.search(t):
        return False
    return bool(_FRAGEWORT.search(t) or t.endswith("?"))


def luecke_melden(frage: str) -> None:
    """Prueft im Hintergrund, ob die Bibliothek die Frage abdeckt."""

    frage = " ".join(str(frage or "").split())[:300]
    if not ist_wissensfrage(frage):
        return
    frage = re.sub(r"^(hey |hallo |ok |okay )?synapse[,.!]?\s*", "", frage, flags=re.I)
    schluessel = frage.lower()
    with _SPERRE:
        if schluessel in _gesehen:
            return
        _gesehen.append(schluessel)
        del _gesehen[:-300]

    def pruefen() -> None:
        try:
            from backend.knowledge.wissensbibliothek import bibliothek

            treffer = bibliothek().suche(frage, limit=2)
            gut = any(f.abdeckung >= 0.75 or f.titel_treffer >= 1 for f in treffer)
            if gut:
                return
            with _SPERRE, open(_ordner() / "luecken.jsonl", "a", encoding="utf-8") as datei:
                datei.write(json.dumps({"frage": frage, "zeit": time.time(), "stand": "offen"},
                                       ensure_ascii=False) + "\n")
            logger.info("Wissensluecke gemerkt: %r", frage[:80])
        except Exception:  # noqa: BLE001 - Lernen ist Zugabe
            logger.debug("Lueckenpruefung gescheitert.", exc_info=True)

    threading.Thread(target=pruefen, name="wissensluecke", daemon=True).start()


def thema_vormerken(thema: str) -> None:
    with _SPERRE, open(_ordner() / "luecken.jsonl", "a", encoding="utf-8") as datei:
        datei.write(json.dumps({"frage": thema, "zeit": time.time(), "stand": "offen", "von": "marc"},
                               ensure_ascii=False) + "\n")


def _luecken() -> list[dict[str, Any]]:
    pfad = _ordner() / "luecken.jsonl"
    if not pfad.exists():
        return []
    return [json.loads(z) for z in pfad.read_text(encoding="utf-8").splitlines() if z.strip()]


def _luecken_schreiben(eintraege: list[dict[str, Any]]) -> None:
    pfad = _ordner() / "luecken.jsonl"
    pfad.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in eintraege[-500:]),
                    encoding="utf-8")


# --- 2. Lernen aus der aktuellen Wikipedia ----------------------------------

def wikipedia_lernen(thema: str, *, artikel: int = 1) -> list[str]:
    """Sucht Artikel zum Thema und nimmt sie auf. Gibt die Titel zurueck."""

    from backend.knowledge.wissen_import import eintragen
    from backend.knowledge.wissensbibliothek import suchbegriffe

    begriffe = " ".join(b for b in suchbegriffe(thema) if b not in ("synapse", "erklär", "erklaer", "erzähl", "unterschied")) or thema
    suche = _json(f"{WIKI_API}?action=query&list=search&format=json&utf8=1&srlimit={artikel}"
                  f"&srsearch={urllib.parse.quote(begriffe)}")
    titel = [t["title"] for t in (suche.get("query") or {}).get("search", [])][:artikel]
    gelernt = []
    for name in titel:
        daten = _json(f"{WIKI_API}?action=query&prop=extracts&explaintext=1&exsectionformat=plain"
                      f"&redirects=1&format=json&utf8=1&titles={urllib.parse.quote(name)}")
        for seite in ((daten.get("query") or {}).get("pages") or {}).values():
            text = str(seite.get("extract") or "")
            text = re.split(r"\n\s*(Literatur|Weblinks|Einzelnachweise|Siehe auch)\s*\n", text)[0][:8000]
            if len(text) < 200:
                continue
            url = "https://de.wikipedia.org/wiki/" + urllib.parse.quote(seite.get("title", name).replace(" ", "_"))
            if eintragen([(str(seite.get("title", name)), text)], quelle=url, art="selbst gelernt"):
                gelernt.append(str(seite.get("title", name)))
    return gelernt


def lernlauf(*, hoechstens: int = PRO_LAUF) -> dict[str, Any]:
    eintraege = _luecken()
    offen = [e for e in eintraege if e.get("stand") == "offen"]
    bericht: dict[str, Any] = {"offen": len(offen), "gelernt": [], "ohne_treffer": []}
    for eintrag in offen[:hoechstens]:
        try:
            titel = wikipedia_lernen(eintrag["frage"])
        except Exception as fehler:  # noqa: BLE001 - kein Netz: spaeter nochmal
            logger.info("Lernlauf unterbrochen: %s", fehler)
            break
        eintrag["stand"] = "gelernt" if titel else "nichts gefunden"
        eintrag["titel"] = titel
        eintrag["gelernt_am"] = time.strftime("%d.%m.%Y")
        (bericht["gelernt"] if titel else bericht["ohne_treffer"]).append(
            f"{eintrag['frage'][:80]} -> {', '.join(titel)}" if titel else eintrag["frage"][:80])
    _luecken_schreiben(eintraege)
    # 3. Interessengebiete einmal pro Woche
    try:
        from backend.config.config_loader import get_config

        interessen = [str(t) for t in (get_config().get("wissen.interessen", []) or []) if str(t).strip()]
    except Exception:  # noqa: BLE001
        interessen = []
    stand_datei = _ordner() / "interessen_stand.json"
    stand = json.loads(stand_datei.read_text(encoding="utf-8")) if stand_datei.exists() else {}
    for thema in interessen:
        if time.time() - float(stand.get(thema, 0)) < 7 * 24 * 3600:
            continue
        try:
            titel = wikipedia_lernen(thema, artikel=2)
            stand[thema] = time.time()
            if titel:
                bericht["gelernt"].append(f"Interessengebiet {thema} -> {', '.join(titel)}")
        except Exception:  # noqa: BLE001
            break
    stand_datei.write_text(json.dumps(stand, ensure_ascii=False), encoding="utf-8")
    if bericht["gelernt"]:
        logger.info("Lernlauf: %d Themen gelernt: %s", len(bericht["gelernt"]), "; ".join(bericht["gelernt"])[:400])
    return bericht


def heute_gelernt() -> list[str]:
    heute = time.strftime("%d.%m.%Y")
    return [f"{e['frage'][:80]} -> {', '.join(e.get('titel') or [])}"
            for e in _luecken() if e.get("gelernt_am") == heute and e.get("titel")]


def hintergrund_starten() -> None:
    global _gestartet
    with _SPERRE:
        if _gestartet:
            return
        _gestartet = True

    def schleife() -> None:
        time.sleep(ERSTER_LAUF)
        while True:
            try:
                lernlauf()
            except Exception:  # noqa: BLE001
                logger.info("Lernlauf gestolpert.", exc_info=True)
            time.sleep(TAKT)

    threading.Thread(target=schleife, name="selbstlernen", daemon=True).start()
    logger.info("Selbstlernen aktiv: Lernlauf alle %d Stunden.", TAKT // 3600)
