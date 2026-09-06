"""
selbstverbesserung.py - Der Nachtlauf der Evolution Engine.
================================================================================

Was hier fehlte
---------------
Der Orb hat die Selbstverbesserung bereits vollstaendig: fuenfzehn Module in
``backend/evolution`` - Codeanalyse, Architekturpruefung, Fehlersuche in den
Protokollen, Ideengenerator, Patchbau in einer Arbeitskopie, Testlauf,
Review, Risikobewertung, Ruecknahme. Alles da, alles benutzbar.

Was fehlte, war das Einfachste und das Entscheidende: **Es hat es nie von
selbst getan.** ``EvolutionEngine.analyze()`` wird von niemandem gerufen.
Die Maschine steht, weil niemand den Schluessel dreht.

Diese Datei dreht ihn. Einmal pro Nacht.

Wie der Lauf abgesichert ist
----------------------------
Die Sicherheitsregeln der Engine bleiben unangetastet - sie sind dort fest
eingebaut und werden hier nicht umgangen, sondern benutzt:

  * Gearbeitet wird ausschliesslich in der Arbeitskopie. An den
    produktiven Dateien aendert dieser Lauf nichts. Nie.
  * Ein Patch wird erst dann vorgeschlagen, wenn Tests und Review ihn
    durchgelassen haben.
  * Uebernommen wird nichts. Am Ende steht ein Vorschlag, und der wartet
    auf dein Antippen.

Dazu drei eigene Grenzen, die dieser Lauf setzt:

  * Ein Zeitbudget. Ein Nachtlauf, der bis zum Mittag rechnet, ist keiner.
  * Eine Obergrenze fuer die Zahl der Patches je Nacht. Zehn Vorschlaege,
    die niemand liest, sind schlechter als zwei, die jemand liest.
  * Die Reihenfolge der Schwerpunkte. Der Ideengenerator findet mehr, als
    sich in einer Nacht abarbeiten laesst; welche zuerst drankommen,
    entscheidet, ob der Lauf nuetzt.

Benutzung
---------
    python werkzeug/selbstverbesserung.py                  nur analysieren
    python werkzeug/selbstverbesserung.py --patches        auch Patches bauen
    python werkzeug/selbstverbesserung.py --bericht        letzten Bericht zeigen
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

HIER = Path(__file__).resolve().parent
WURZEL = HIER.parent
sys.path.insert(0, str(WURZEL))

BERICHTE = WURZEL / "data" / "evolution"
PROTOKOLL = WURZEL / "logs" / "selbstverbesserung.log"

#: Wie lange ein Nachtlauf hoechstens dauern darf.
ZEITBUDGET = 45 * 60.0

#: Wie viele Patches je Lauf hoechstens entstehen.
#:
#: Zehn Vorschlaege, die niemand liest, sind schlechter als zwei, die
#: jemand liest. Die Zahl ist bewusst klein.
PATCHES_JE_NACHT = 3

#: Die Schwerpunkte in der Reihenfolge, in der sie abgearbeitet werden.
#: Fehler zuerst - das sind echte Probleme aus dem Betrieb statt vermuteter.
SCHWERPUNKTE = ("fehler", "leistung", "tests", "dokumentation")

#: Woran eine Idee einem Schwerpunkt zugeordnet wird. Der Ideengenerator
#: benennt seine Kategorien nicht einheitlich, deshalb wird auf Wortstaemme
#: geprueft statt auf feste Namen.
MERKMALE = {
    "fehler": ("bug", "fehler", "exception", "absturz", "crash", "error"),
    "leistung": ("performance", "leistung", "langsam", "slow", "speicher", "memory"),
    "tests": ("test", "abdeckung", "coverage"),
    "dokumentation": ("doku", "docstring", "documentation", "lesbar", "komplex",
                      "duplicate", "wiederholung", "aufraeum", "refactor"),
}

_zeilen: list[str] = []


def sagen(text: str = "") -> None:
    print(text, flush=True)
    _zeilen.append(f"{datetime.now():%H:%M:%S}  {text}" if text else "")


def protokoll_schreiben() -> None:
    try:
        PROTOKOLL.parent.mkdir(parents=True, exist_ok=True)
        with PROTOKOLL.open("a", encoding="utf-8") as datei:
            datei.write("\n".join(_zeilen) + "\n")
    except OSError:
        pass


# ------------------------------------------------------------ Ideen ordnen
def schwerpunkt_von(idee: dict) -> str:
    """Ordnet eine Idee einem Schwerpunkt zu."""

    text = " ".join(
        str(idee.get(feld, "")) for feld in
        ("category", "kategorie", "title", "titel", "description", "beschreibung", "type")
    ).lower()
    for name in SCHWERPUNKTE:
        if any(merkmal in text for merkmal in MERKMALE[name]):
            return name
    return "sonstiges"


def ideen_ordnen(ideen: list[dict]) -> list[dict]:
    """Sortiert nach Schwerpunkt, innerhalb dessen nach Prioritaet.

    Die Reihenfolge der Schwerpunkte ist die Entscheidung des Benutzers und
    wird nicht von der Bewertung des Ideengenerators ueberstimmt: Eine
    hochbewertete Dokumentationsidee kommt nach einer niedrig bewerteten
    Fehleridee.
    """

    rang = {name: i for i, name in enumerate(SCHWERPUNKTE)}

    def gewicht(idee: dict) -> tuple[int, float]:
        name = schwerpunkt_von(idee)
        prio = idee.get("priority", idee.get("prioritaet", idee.get("score", 0)))
        try:
            prio = float(prio)
        except (TypeError, ValueError):
            prio = 0.0
        return (rang.get(name, len(rang)), -prio)

    return sorted(ideen, key=gewicht)


# --------------------------------------------------------------- Der Lauf
def lauf(mit_patches: bool) -> dict:
    from backend.evolution.evolution_engine import EvolutionEngine

    ende = time.monotonic() + ZEITBUDGET
    sagen("=" * 66)
    sagen(f"Nachtlauf {datetime.now():%d.%m.%Y %H:%M}")
    sagen("=" * 66)

    motor = EvolutionEngine()

    sagen()
    sagen("[1/3] Selbstanalyse")
    begonnen = time.monotonic()
    analyse = motor.analyze()
    sagen(f"      {len(analyse.get('findings', []))} Befunde, "
          f"{len(analyse.get('ideas', []))} Ideen in "
          f"{time.monotonic() - begonnen:.0f} s")

    code = analyse.get("code", {})
    architektur = analyse.get("architecture", {})
    sagen(f"      {code.get('modules', 0)} Module, {code.get('lines', 0)} Zeilen, "
          f"Wartbarkeit {architektur.get('maintainability', 0):.2f}, "
          f"{architektur.get('cycles', 0)} Ringschluesse")

    geordnet = ideen_ordnen(list(analyse.get("ideas", [])))
    sagen()
    sagen("[2/3] Die aussichtsreichsten Ideen")
    for nummer, idee in enumerate(geordnet[:10], 1):
        titel = str(idee.get("title") or idee.get("titel") or idee.get("id") or "?")
        sagen(f"      {nummer:2d}. [{schwerpunkt_von(idee):13s}] {titel[:70]}")
    if not geordnet:
        sagen("      Keine. Das ist ein gutes Zeichen - oder die Analyse fand nichts,")
        sagen("      woran sie ansetzen kann.")

    gebaut: list[dict] = []
    sagen()
    if not mit_patches:
        sagen("[3/3] Patches: uebersprungen (ohne --patches wird nur analysiert)")
    else:
        sagen(f"[3/3] Patches bauen (hoechstens {PATCHES_JE_NACHT})")
        gebaut = patches_bauen(motor, ende)

    offen = []
    try:
        offen = motor.pending_patches()
    except Exception as fehler:  # noqa: BLE001
        sagen(f"      Die offenen Patches liessen sich nicht lesen: {fehler}")

    sagen()
    sagen("=" * 66)
    sagen(f"Fertig. {len(gebaut)} neue Vorschlaege, {len(offen)} warten insgesamt.")
    if offen:
        sagen("Freigeben auf dem iPad: die Seite 'Vorschlaege' im Orb.")
    sagen("=" * 66)

    return {
        "zeitpunkt": time.time(),
        "datum": f"{datetime.now():%d.%m.%Y %H:%M}",
        "analyse": {
            "befunde": len(analyse.get("findings", [])),
            "ideen": len(analyse.get("ideas", [])),
            "module": code.get("modules", 0),
            "zeilen": code.get("lines", 0),
            "wartbarkeit": architektur.get("maintainability", 0.0),
            "ringschluesse": architektur.get("cycles", 0),
        },
        "ideen": [
            {
                "titel": str(i.get("title") or i.get("titel") or i.get("id") or "?"),
                "schwerpunkt": schwerpunkt_von(i),
                "beschreibung": str(i.get("description") or i.get("beschreibung") or ""),
            }
            for i in geordnet[:20]
        ],
        "neue_patches": gebaut,
        "offene_patches": offen,
        "bugs": analyse.get("bugs", {}),
    }


def modell_holen():
    """Das lokale Modell aus der Konfiguration - oder None.

    Genommen wird der Abschnitt, in dem ``engine: ollama`` steht, egal ob
    er vorn oder hinten haengt. Wer auf Offline-Betrieb umgestellt hat, hat
    ihn unter ``ai.primary``; sonst steht er unter ``ai.fallback``.
    """

    from werkzeug.patchschmied import Modell

    try:
        import yaml  # type: ignore

        daten = yaml.safe_load((WURZEL / "config.yaml").read_text(encoding="utf-8")) or {}
    except Exception as fehler:  # noqa: BLE001
        sagen(f"      config.yaml nicht lesbar ({fehler}) - keine Patches moeglich.")
        return None

    ki = daten.get("ai") or {}
    for rolle in ("fallback", "primary"):
        abschnitt = ki.get(rolle) or {}
        if str(abschnitt.get("engine", "")).lower() == "ollama":
            name = str(abschnitt.get("model", "")).strip()
            adresse = str(abschnitt.get("base_url", "") or "http://127.0.0.1:11434")
            if name:
                sagen(f"      Modell: {name} ueber {adresse}")
                return Modell(adresse, name)
    sagen("      In config.yaml steht kein Ollama-Abschnitt - keine Patches moeglich.")
    sagen("      Erst SPRACHMODELL-REPARIEREN.bat laufen lassen.")
    return None


def patches_bauen(motor, ende: float) -> list[dict]:
    """Sucht konkrete Stellen, laesst das Modell sie beheben, prueft alles.

    Die Ziele kommen NICHT aus dem Ideengenerator. Der liefert Sammelbefunde
    - "159 ueberlange Funktionen", "Wartbarkeit verbessern" -, und eine
    Sammlung laesst sich nicht patchen. Gebraucht wird eine Datei und ein
    Funktionsname. Genau die sucht der Patchschmied selbst: aus den
    Rueckverfolgungen in den Protokollen und aus dem Quelltext.
    """

    from werkzeug import patchschmied as ps

    modell = modell_holen()
    if modell is None:
        return []

    ziele = ps.ziele_aus_protokollen(WURZEL) + ps.ziele_aus_code(WURZEL)
    if not ziele:
        sagen("      Keine konkrete Stelle gefunden, an der sich ansetzen liesse.")
        return []
    sagen(f"      {len(ziele)} konkrete Stellen gefunden.")

    gebaut: list[dict] = []
    for ziel in ziele:
        if len(gebaut) >= PATCHES_JE_NACHT:
            sagen("      Obergrenze erreicht.")
            break
        if time.monotonic() > ende:
            sagen("      Zeitbudget aufgebraucht.")
            break

        kurz = f"{ziel.datei.name}::{ziel.funktion}"
        ergebnis = ps.schmieden(ziel, modell)
        if not ergebnis.gelungen:
            # Das ist der Normalfall, nicht der Ausnahmefall. Ein Modell
            # dieser Groesse liefert oefter Unbrauchbares als Brauchbares -
            # deshalb steht die Pruefung davor.
            sagen(f"      - {kurz}: verworfen ({ergebnis.grund})")
            continue

        try:
            patch = motor.prepare_patch(
                title=ziel.titel(),
                description=f"{ziel.problem}\n\n{ziel.auftrag}",
                changes=ergebnis.aenderungen,
            )
            kennung = str(patch.get("id", ""))
            pruefung = motor.validate_patch(kennung)
        except Exception as fehler:  # noqa: BLE001
            sagen(f"      - {kurz}: Bau fehlgeschlagen ({str(fehler)[:70]})")
            continue

        if not pruefung.get("proposable"):
            sagen(f"      - {kurz}: durch die Pruefung gefallen "
                  f"({str(pruefung.get('summary', ''))[:60]})")
            try:
                motor.discard_patch(kennung)
            except Exception:  # noqa: BLE001
                pass
            continue

        sagen(f"      + {kurz}: bereit, Risiko {pruefung.get('risk', '?')}")
        gebaut.append({
            "id": kennung,
            "titel": ziel.titel(),
            "risiko": pruefung.get("risk", ""),
            "zusammenfassung": pruefung.get("summary", ""),
        })
    return gebaut


def bericht_schreiben(daten: dict) -> Path:
    BERICHTE.mkdir(parents=True, exist_ok=True)
    ziel = BERICHTE / "letzter-lauf.json"
    ziel.write_text(json.dumps(daten, ensure_ascii=False, indent=2, default=str),
                    encoding="utf-8")
    verlauf = BERICHTE / "verlauf.jsonl"
    with verlauf.open("a", encoding="utf-8") as datei:
        datei.write(json.dumps({
            "zeitpunkt": daten["zeitpunkt"], "datum": daten["datum"],
            **daten["analyse"], "neue_patches": len(daten["neue_patches"]),
        }, ensure_ascii=False, default=str) + "\n")
    return ziel


def ziele_zeigen() -> int:
    """Zeigt, welche konkreten Stellen der Patchschmied findet.

    Zwei Sekunden statt eines langen Modelllaufs - und die Antwort auf die
    eigentliche Frage: Gibt es ueberhaupt etwas, woran sich ansetzen laesst?
    Findet er nichts aus den Protokollen, fehlen dort die Rueckverfolgungen;
    dann nennt kein Fehlereintrag eine Datei, und raten waere schlechter als
    nichts zu tun.
    """

    from werkzeug import patchschmied as ps

    aus_log = ps.ziele_aus_protokollen(WURZEL, hoechstens=10)
    aus_code = ps.ziele_aus_code(WURZEL, hoechstens=10)

    strich = "=" * 70
    print(strich)
    print(" Konkrete Stellen, an denen der Patchschmied ansetzen kann")
    print(strich)

    print()
    print(f" Aus den Protokollen ({len(aus_log)}):")
    if not aus_log:
        print("   keine. In logs/*.log steht keine Rueckverfolgung, die auf eine")
        print("   Datei dieses Projekts zeigt. Ohne 'File \"...\", line N, in ...'")
        print("   nennt ein Fehlereintrag keinen Ort - und geraten wird nicht.")
    for ziel in aus_log:
        print(f"   {ziel.gewicht:2d}x  {ziel.datei.name}::{ziel.funktion}")
        print(f"        {ziel.problem[:64]}")

    print()
    print(f" Aus dem Quelltext ({len(aus_code)}):")
    if not aus_code:
        print("   keine.")
    for ziel in aus_code:
        print(f"   [{ziel.art:13s}] {ziel.datei.name}::{ziel.funktion} - {ziel.problem}")

    print()
    print(strich)
    gesamt = len(aus_log) + len(aus_code)
    if gesamt:
        print(f" {gesamt} Stellen. Mit --patches laesst der Orb das Modell daran")
        print(f" arbeiten (hoechstens {PATCHES_JE_NACHT} je Lauf).")
    else:
        print(" Nichts Konkretes gefunden. Ein Lauf mit --patches waere umsonst.")
    print(strich)
    return 0


def bericht_zeigen() -> int:
    ziel = BERICHTE / "letzter-lauf.json"
    if not ziel.exists():
        print("Es gibt noch keinen Bericht. Einmal ohne --bericht laufen lassen.")
        return 1
    daten = json.loads(ziel.read_text(encoding="utf-8"))
    print("=" * 66)
    print(f" Letzter Nachtlauf: {daten.get('datum')}")
    print("=" * 66)
    a = daten.get("analyse", {})
    print(f"  {a.get('befunde')} Befunde, {a.get('ideen')} Ideen")
    print(f"  {a.get('module')} Module, {a.get('zeilen')} Zeilen, "
          f"Wartbarkeit {a.get('wartbarkeit', 0):.2f}")
    print()
    for nummer, idee in enumerate(daten.get("ideen", [])[:10], 1):
        print(f"  {nummer:2d}. [{idee['schwerpunkt']:13s}] {idee['titel'][:60]}")
    offen = daten.get("offene_patches", [])
    print()
    print(f"  {len(offen)} Patches warten auf deine Freigabe.")
    for patch in offen:
        print(f"     - {patch.get('title', '?')[:60]}  (Risiko {patch.get('risk', '?')})")
    return 0


AUFGABE = "AI-Orb Selbstverbesserung"


def python_ohne_fenster() -> Path:
    hier = Path(sys.executable)
    ohne = hier.with_name("pythonw.exe")
    return ohne if ohne.exists() else hier


def zeitplan_einrichten(uhrzeit: str) -> int:
    """Traegt den Nachtlauf in die Aufgabenplanung von Windows ein.

    Als Aufgabe des angemeldeten Benutzers - ohne Administratorrechte und
    ohne Dienst. Laeuft der Rechner zur genannten Zeit nicht, holt Windows
    die Aufgabe beim naechsten Anmelden nach.
    """

    import subprocess

    befehlszeile = (
        f'"{python_ohne_fenster()}" "{Path(__file__).resolve()}" --patches'
    )
    lauf = subprocess.run(
        ["schtasks", "/Create", "/TN", AUFGABE, "/TR", befehlszeile,
         "/SC", "DAILY", "/ST", uhrzeit, "/F"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if lauf.returncode != 0:
        print("Der Zeitplan liess sich nicht eintragen:")
        print((lauf.stdout + lauf.stderr).strip()[:400])
        return 1
    print(f"Eingetragen: taeglich um {uhrzeit} Uhr.")
    print("Nachsehen mit:  schtasks /Query /TN \"" + AUFGABE + "\"")
    return 0


def zeitplan_entfernen() -> int:
    import subprocess

    lauf = subprocess.run(["schtasks", "/Delete", "/TN", AUFGABE, "/F"],
                          capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if lauf.returncode != 0:
        print("Es war kein Zeitplan eingetragen.")
        return 0
    print("Der Nachtlauf ist entfernt.")
    return 0


def main() -> int:
    zerleger = argparse.ArgumentParser(description="Der Nachtlauf der Selbstverbesserung.")
    zerleger.add_argument("--einrichten", metavar="HH:MM", nargs="?", const="03:00",
                          help="Taeglichen Nachtlauf eintragen (Vorgabe 03:00).")
    zerleger.add_argument("--entfernen", action="store_true",
                          help="Den Nachtlauf wieder austragen.")
    zerleger.add_argument("--patches", action="store_true",
                          help="Nicht nur analysieren, sondern Patches bauen und pruefen.")
    zerleger.add_argument("--bericht", action="store_true",
                          help="Den letzten Bericht anzeigen.")
    zerleger.add_argument("--ziele", action="store_true",
                          help="Nur zeigen, welche konkreten Stellen es gibt.")
    argumente = zerleger.parse_args()

    if argumente.einrichten:
        return zeitplan_einrichten(argumente.einrichten)
    if argumente.entfernen:
        return zeitplan_entfernen()
    if argumente.ziele:
        return ziele_zeigen()
    if argumente.bericht:
        return bericht_zeigen()

    try:
        daten = lauf(argumente.patches)
    except Exception as fehler:  # noqa: BLE001
        sagen()
        sagen(f"Der Lauf ist gescheitert: {fehler}")
        for zeile in traceback.format_exc().splitlines():
            _zeilen.append("      " + zeile)
        protokoll_schreiben()
        print(f"\nEinzelheiten in {PROTOKOLL}")
        return 1

    ziel = bericht_schreiben(daten)
    protokoll_schreiben()
    print(f"\nBericht: {ziel}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
