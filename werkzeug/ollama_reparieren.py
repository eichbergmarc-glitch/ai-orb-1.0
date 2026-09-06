"""
ollama_reparieren.py - Bringt das lokale Sprachmodell zum Laufen.
================================================================================

Warum es diese Datei gibt
-------------------------
"Lokales Sprachmodell nicht erreichbar" kann sechs verschiedene Dinge
bedeuten: Ollama fehlt, Ollama laeuft nicht, das Modell ist nicht geladen,
in ``config.yaml`` steht ein anderer Name als tatsaechlich da ist, der
Abschnitt ``ai.fallback`` fehlt ganz - oder alles ist da und nur die erste
Antwort dauert so lange, dass es wie ein Ausfall aussieht.

Dieses Programm geht die Kette durch, repariert unterwegs und beweist am
Ende, dass es traegt: Es stellt dem Modell eine echte Frage und zeigt die
Antwort mit der gemessenen Zeit. Was danach hier steht, gilt.

Der Offline-Betrieb
-------------------
Der Orb ist so gebaut, dass ``ai.primary`` zuerst gefragt wird und
``ai.fallback`` einspringt, wenn das misslingt. Steht vorn ein Anbieter aus
dem Netz, wartet der Orb ohne Internet erst dessen Zeitlimit ab, bevor er
das lokale Modell fragt. Bei dreissig Sekunden Zeitlimit heisst das:
dreissig Sekunden Stille vor jeder Antwort.

Mit ``--offline`` wird das lokale Modell nach vorn gestellt und der
Netzanbieter zum Rueckfall. Der Orb antwortet dann sofort aus dem eigenen
Rechner. ``--online`` stellt es zurueck. Beides mit Sicherung.

Benutzung
---------
    python werkzeug/ollama_reparieren.py            pruefen und reparieren
    python werkzeug/ollama_reparieren.py --laden    das Modell auch holen
    python werkzeug/ollama_reparieren.py --offline  lokal nach vorn stellen
    python werkzeug/ollama_reparieren.py --online   wieder zurueck
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

HIER = Path(__file__).resolve().parent
WURZEL = HIER.parent
CONFIG = WURZEL / "config.yaml"
DIAGNOSE = WURZEL / "ollama-diagnose.txt"

#: Wo Ollama unter Windows landet, wenn es nicht im Pfad steht. Dieselbe
#: Liste wie in backend/launcher/ollama_service.py - bewusst doppelt, damit
#: dieses Werkzeug auch dann laeuft, wenn der Orb selbst nicht startet.
WINDOWS_ORTE = (
    r"%LOCALAPPDATA%\Programs\Ollama\ollama.exe",
    r"%PROGRAMFILES%\Ollama\ollama.exe",
    r"%PROGRAMFILES(X86)%\Ollama\ollama.exe",
)

STANDARD_ADRESSE = "http://127.0.0.1:11434"

_zeilen: list[str] = []


def sagen(text: str = "") -> None:
    print(text, flush=True)
    _zeilen.append(text)


def schritt(nr: int, gesamt: int, titel: str) -> None:
    sagen()
    sagen(f"[{nr}/{gesamt}] {titel}")


def gut(text: str) -> bool:
    sagen(f"      OK   {text}")
    return True


def halt(text: str, rat: str = "") -> bool:
    sagen(f"      HALT {text}")
    for zeile in rat.splitlines():
        if zeile:
            sagen(f"           {zeile}")
    return False


def notiz(text: str) -> None:
    sagen(f"      ..   {text}")


# ------------------------------------------------------------- Ollama finden
def ollama_programm() -> str | None:
    gefunden = shutil.which("ollama") or shutil.which("ollama.exe")
    if gefunden:
        return gefunden
    if platform.system() == "Windows":
        for ort in WINDOWS_ORTE:
            pfad = Path(os.path.expandvars(ort))
            try:
                if pfad.is_file():
                    return str(pfad)
            except OSError:
                continue
    return None


def befehl(*teile: str, zeit: int = 120) -> tuple[int, str]:
    try:
        lauf = subprocess.run(list(teile), capture_output=True, text=True,
                              timeout=zeit, encoding="utf-8", errors="replace")
        return lauf.returncode, (lauf.stdout + lauf.stderr).strip()
    except FileNotFoundError:
        return 127, f"{teile[0]} nicht gefunden"
    except subprocess.TimeoutExpired:
        return 124, f"{teile[0]} antwortete nicht in {zeit}s"
    except Exception as fehler:  # noqa: BLE001
        return 1, str(fehler)


# --------------------------------------------------------- Ollama ansprechen
def hole(adresse: str, pfad: str, zeit: float = 5.0):
    with urllib.request.urlopen(f"{adresse}{pfad}", timeout=zeit) as antwort:
        return json.loads(antwort.read().decode("utf-8", "replace"))


def sende(adresse: str, pfad: str, nutzlast: dict, zeit: float | None = 120.0):
    anfrage = urllib.request.Request(
        f"{adresse}{pfad}",
        data=json.dumps(nutzlast).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(anfrage, timeout=zeit) as antwort:
        return json.loads(antwort.read().decode("utf-8", "replace"))


def laeuft(adresse: str) -> bool:
    try:
        hole(adresse, "/api/tags", zeit=3.0)
        return True
    except Exception:  # noqa: BLE001
        return False


def modelle(adresse: str) -> list[str]:
    try:
        daten = hole(adresse, "/api/tags", zeit=8.0)
    except Exception:  # noqa: BLE001
        return []
    return [str(e.get("name", "")) for e in daten.get("models", []) if e]


def passt(gewuenscht: str, vorhanden: list[str]) -> str | None:
    """Findet das passende Modell. Nachsichtig wie im Orb selbst.

    Ollama fuehrt ``llama3.1:8b`` gelegentlich als
    ``llama3.1:8b-instruct-q4_0``. Wer das Grundmodell verlangt, soll damit
    zufrieden sein.
    """

    ziel = gewuenscht.strip().lower()
    klein = {m.lower(): m for m in vorhanden}
    if ziel in klein:
        return klein[ziel]
    grund = ziel.split(":")[0]
    for k, echt in klein.items():
        if k.split(":")[0] == grund:
            return echt
    return None


# ------------------------------------------------------------- config.yaml
def config_lesen() -> dict:
    if not CONFIG.exists():
        return {}
    try:
        import yaml  # type: ignore

        return yaml.safe_load(CONFIG.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        return {}


def config_schreiben(daten: dict) -> bool:
    try:
        import yaml  # type: ignore
    except Exception:  # noqa: BLE001
        halt("PyYAML fehlt - die Konfiguration kann nicht geschrieben werden.")
        return False
    sicherung = CONFIG.with_suffix(".yaml.vor-ollama")
    if not sicherung.exists():
        sicherung.write_bytes(CONFIG.read_bytes())
    CONFIG.write_text(
        yaml.safe_dump(daten, allow_unicode=True, sort_keys=False, width=100),
        encoding="utf-8",
    )
    notiz(f"Sicherung: {sicherung.name}")
    return True


# ==================================================================== Die Kette
def kette(laden: bool, modellwunsch: str) -> bool:
    gesamt = 6

    # ---------------------------------------------------------------- 1
    schritt(1, gesamt, "Konfiguration")
    daten = config_lesen()
    if not daten:
        halt(
            "config.yaml liess sich nicht lesen.",
            "Entweder fehlt sie, oder PyYAML ist nicht installiert.\n"
            "Es wird mit den Vorgabewerten weitergearbeitet.",
        )
    ki = (daten.get("ai") or {}) if isinstance(daten, dict) else {}
    rueckfall = ki.get("fallback") or {}
    haupt = ki.get("primary") or {}

    adresse = str(rueckfall.get("base_url", "") or STANDARD_ADRESSE).rstrip("/")
    modell = modellwunsch or str(rueckfall.get("model", "") or "").strip()

    if not rueckfall:
        halt(
            "In config.yaml gibt es keinen Abschnitt 'ai.fallback'.",
            "Ohne ihn hat der Orb gar kein lokales Modell - er kann dann\n"
            "grundsaetzlich nicht offline antworten. Am Ende dieses Laufs\n"
            "steht, wie der Abschnitt aussehen muss.",
        )
    else:
        gut(f"ai.fallback: engine={rueckfall.get('engine', '?')}  model={modell or '?'}")
    if haupt:
        sagen(f"           ai.primary : engine={haupt.get('engine', '?')}  "
              f"model={haupt.get('model', '?')}  timeout={haupt.get('timeout', '?')}")
    if not modell:
        modell = "llama3.1:8b"
        notiz(f"Kein Modellname eingetragen. Es wird mit '{modell}' geprueft.")

    # ---------------------------------------------------------------- 2
    schritt(2, gesamt, "Ollama vorhanden")
    programm = ollama_programm()
    if not programm:
        notiz("Nicht gefunden. Versuche die Installation ueber winget ...")
        if not shutil.which("winget"):
            return halt(
                "winget gibt es auf diesem Rechner nicht.",
                "Von Hand: https://ollama.com/download\n"
                "Danach dieses Werkzeug erneut starten.",
            )
        code, ausgabe = befehl(
            "winget", "install", "--id", "Ollama.Ollama", "-e",
            "--accept-source-agreements", "--accept-package-agreements", zeit=900,
        )
        programm = ollama_programm()
        if not programm:
            return halt("Die Installation hat nicht geklappt.", ausgabe[-400:])
        notiz("Installiert.")
    gut(programm)

    # ---------------------------------------------------------------- 3
    schritt(3, gesamt, "Dienst laeuft")
    if laeuft(adresse):
        gut(f"Antwortet auf {adresse}")
    else:
        notiz("Antwortet nicht. Wird gestartet ...")
        kennzeichen = 0
        if platform.system() == "Windows":
            kennzeichen = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            subprocess.Popen(
                [programm, "serve"], stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, creationflags=kennzeichen,
            )
        except OSError as fehler:
            return halt(f"Ollama liess sich nicht starten: {fehler}")
        for _ in range(50):
            time.sleep(0.6)
            if laeuft(adresse):
                break
        if not laeuft(adresse):
            return halt(
                "Ollama hat nach 30 Sekunden nicht geantwortet.",
                "Starte es einmal von Hand, um die Meldung zu sehen:\n"
                f"  \"{programm}\" serve",
            )
        gut(f"Gestartet, antwortet auf {adresse}")

    # ---------------------------------------------------------------- 4
    schritt(4, gesamt, "Modell vorhanden")
    da = modelle(adresse)
    sagen(f"           Lokal vorhanden: {', '.join(da) if da else '(keins)'}")
    echt = passt(modell, da)
    if echt is None:
        if not laden:
            return halt(
                f"Das Modell '{modell}' ist nicht geladen.",
                "Das ist mit grosser Wahrscheinlichkeit dein Fehler.\n"
                "Zum Herunterladen dieses Werkzeug mit --laden aufrufen:\n"
                "  python werkzeug\\ollama_reparieren.py --laden\n"
                "Es sind je nach Modell mehrere Gigabyte.",
            )
        notiz(f"'{modell}' wird geladen. Das dauert und ist gross.")
        code, ausgabe = befehl(programm, "pull", modell, zeit=7200)
        if code != 0:
            return halt(f"Das Laden von '{modell}' ist fehlgeschlagen.", ausgabe[-500:])
        da = modelle(adresse)
        echt = passt(modell, da)
        if echt is None:
            return halt(f"'{modell}' ist auch nach dem Laden nicht da.")
        notiz("Geladen.")
    gut(f"'{echt}' ist da." + ("" if echt.lower() == modell.lower()
                               else f"  (eingetragen ist '{modell}')"))

    # ---------------------------------------------------------------- 5
    schritt(5, gesamt, "Ins Gedaechtnis holen")
    # Ein Modell, das erst beim ersten Satz von der Platte geladen wird,
    # braucht dafuer je nach Groesse zehn bis sechzig Sekunden. Genau die
    # erlebt der Benutzer als "nicht erreichbar". Mit einer leeren Anfrage
    # und keep_alive liegt es vorher bereit.
    begonnen = time.monotonic()
    try:
        sende(adresse, "/api/generate",
              {"model": echt, "prompt": "", "keep_alive": "30m"}, zeit=600.0)
        gut(f"Liegt bereit (nach {time.monotonic() - begonnen:.1f} s, bleibt 30 Minuten).")
    except Exception as fehler:  # noqa: BLE001
        notiz(f"Vorladen nicht moeglich ({str(fehler)[:80]}). Der Test laeuft trotzdem.")

    # ---------------------------------------------------------------- 6
    schritt(6, gesamt, "Eine echte Frage")
    frage = "Antworte in einem einzigen kurzen deutschen Satz: Was ist eine Quelle in der Geschichtswissenschaft?"
    begonnen = time.monotonic()
    try:
        antwort = sende(adresse, "/api/generate", {
            "model": echt, "prompt": frage, "stream": False,
            "keep_alive": "30m", "options": {"num_predict": 80},
        }, zeit=300.0)
    except Exception as fehler:  # noqa: BLE001
        return halt(f"Das Modell hat nicht geantwortet: {str(fehler)[:200]}")
    dauer = time.monotonic() - begonnen
    text = " ".join(str(antwort.get("response", "")).split())
    if not text:
        return halt("Das Modell antwortete leer.")
    gut(f"Geantwortet in {dauer:.1f} s:")
    sagen(f"           \"{text[:300]}\"")

    # ------------------------------------------------------- Offline-Urteil
    sagen()
    sagen("  Zum Offline-Betrieb:")
    haupt_engine = str(haupt.get("engine", "")).strip().lower()
    haupt_zeit = float(haupt.get("timeout", 0) or 0)
    if haupt_engine in ("", "ollama"):
        sagen("    Vorn steht bereits das lokale Modell. Der Orb antwortet ohne")
        sagen("    Umweg, auch ohne Internet.")
    else:
        sagen(f"    Vorn steht '{haupt_engine}' - ein Anbieter aus dem Netz. Ohne")
        sagen(f"    Internet wartet der Orb erst dessen Zeitlimit ab"
              + (f" ({haupt_zeit:.0f} s)" if haupt_zeit else "")
              + ",")
        sagen("    bevor er das lokale Modell fragt. Das sieht aus wie ein Ausfall.")
        sagen()
        sagen("    Umstellen mit:  python werkzeug\\ollama_reparieren.py --offline")
        sagen("    Zurueck mit  :  python werkzeug\\ollama_reparieren.py --online")

    if not rueckfall:
        sagen()
        sagen("  So muss der fehlende Abschnitt in config.yaml aussehen:")
        sagen()
        sagen("    ai:")
        sagen("      fallback:")
        sagen("        engine: ollama")
        sagen(f"        model: {echt}")
        sagen(f"        base_url: {adresse}")
        sagen("        timeout: 120")
    return True


# ============================================================ Reihenfolge drehen
def reihenfolge(nach_vorn: bool) -> int:
    daten = config_lesen()
    if not daten:
        print("config.yaml liess sich nicht lesen.")
        return 1
    ki = daten.setdefault("ai", {})
    haupt = ki.get("primary") or {}
    rueckfall = ki.get("fallback") or {}
    if not haupt or not rueckfall:
        print("Es braucht sowohl 'ai.primary' als auch 'ai.fallback'.")
        return 1

    lokal_vorn = str(haupt.get("engine", "")).lower() == "ollama"
    if nach_vorn and lokal_vorn:
        print("Das lokale Modell steht bereits vorn.")
        return 0
    if not nach_vorn and not lokal_vorn:
        print("Der Netzanbieter steht bereits vorn.")
        return 0

    ki["primary"], ki["fallback"] = rueckfall, haupt
    if not config_schreiben(daten):
        return 1
    if nach_vorn:
        print("Umgestellt: Das lokale Modell wird jetzt zuerst gefragt.")
        print("Der Netzanbieter bleibt als Rueckfall erhalten.")
    else:
        print("Zurueckgestellt: Der Netzanbieter wird wieder zuerst gefragt.")
    print("Der Orb muss neu gestartet werden, damit es wirkt.")
    return 0


def main() -> int:
    zerleger = argparse.ArgumentParser(description="Bringt das lokale Sprachmodell zum Laufen.")
    zerleger.add_argument("--laden", action="store_true",
                          help="Das Modell herunterladen, wenn es fehlt.")
    zerleger.add_argument("--modell", default="", help="Ein anderes Modell pruefen.")
    zerleger.add_argument("--offline", action="store_true",
                          help="Das lokale Modell nach vorn stellen.")
    zerleger.add_argument("--online", action="store_true",
                          help="Den Netzanbieter wieder nach vorn stellen.")
    argumente = zerleger.parse_args()

    if argumente.offline or argumente.online:
        return reihenfolge(nach_vorn=argumente.offline)

    strich = "=" * 70
    sagen(strich)
    sagen(" Lokales Sprachmodell")
    sagen(strich)
    sagen(f" {datetime.now():%d.%m.%Y %H:%M}   Ordner: {WURZEL}")

    try:
        geschafft = kette(argumente.laden, argumente.modell.strip())
    except Exception as fehler:  # noqa: BLE001
        import traceback

        geschafft = False
        sagen()
        sagen(f"      HALT Unerwarteter Fehler: {fehler}")
        for zeile in traceback.format_exc().splitlines():
            _zeilen.append("      " + zeile)

    sagen()
    sagen(strich)
    sagen(" Das lokale Modell traegt." if geschafft
          else " Es haengt noch. Die Stelle steht oben bei HALT.")
    sagen(f" Mitgeschrieben: {DIAGNOSE.name}")
    sagen(strich)
    try:
        DIAGNOSE.write_text("\n".join(_zeilen) + "\n", encoding="utf-8")
    except OSError:
        pass
    return 0 if geschafft else 1


if __name__ == "__main__":
    raise SystemExit(main())
