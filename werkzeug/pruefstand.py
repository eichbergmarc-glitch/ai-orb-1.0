# -*- coding: utf-8 -*-
"""Der Pruefstand: geht einmal durch alle Funktionen des Orb und sagt, was laeuft.

Gedacht fuer die Frage "funktioniert das alles noch?", auf die man sonst nur
durch Ausprobieren eine Antwort bekommt. Der Pruefstand ruehrt nichts an: Er
liest, fragt und misst. Es wird keine Datei geaendert und kein Dienst
gestartet.

    python pruefstand.py              alles pruefen
    python pruefstand.py --kurz       nur die Zusammenfassung
    python pruefstand.py --nur netz   nur eine Gruppe (siehe --hilfe)

Am Ende steht der Bericht auch in ``pruefstand-bericht.txt`` neben dem Orb.
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

OK = "OK    "
WARN = "HINWEIS"
FEHLER = "FEHLER"

#: Saetze, mit denen ein Mensch eine Vorlesung beginnt. Sie muessen alle als
#: "start" erkannt werden - sonst laufen sie als gewoehnliche Frage in das
#: bereits laufende Vorlesungsgespraech und der Orb knuepft dort an, wo er war.
VORLESUNGSPROBEN_START = (
    "Halte mir eine Vorlesung über die Französische Revolution",
    "Ich hätte gerne eine Vorlesung über Astrophysik",
    "Kannst du mir eine Vorlesung über Kant halten?",
    "Lass uns eine Vorlesung über Statistik machen",
    "Neue Vorlesung über Thermodynamik",
    "Wir machen jetzt eine Vorlesung über römisches Recht",
    "Halte mir bitte einen Vortrag über Immanuel Kant",
    "Ich möchte eine Vorlesung zum Thema künstliche Intelligenz",
    "Ich möchte gerne dass du mir die Einführungsvorlesung über die "
    "Geschichtswissenschaft hältst und zwar über das Mittelalter",
    "Gib mir eine Einführungsvorlesung in die Volkswirtschaftslehre",
)
#: Saetze, die mit einer Vorlesung NICHTS zu tun haben.
VORLESUNGSPROBEN_NICHTS = (
    "Fahre mit dem Programm fort",
    "Mach mit der Datei weiter",
    "Ich mache das später weiter",
    "Schreib den Termin in den Kalender",
)


class Bericht:
    """Sammelt die Befunde und haelt die Zaehler."""

    def __init__(self, kurz: bool = False) -> None:
        self.zeilen: list[str] = []
        self.kurz = kurz
        self.zaehler = {OK: 0, WARN: 0, FEHLER: 0}
        self.gruppe = ""

    def abschnitt(self, titel: str) -> None:
        self.gruppe = titel
        self._schreiben("")
        self._schreiben("--- %s %s" % (titel, "-" * max(0, 62 - len(titel))))

    def sagen(self, stand: str, satz: str, mehr: str = "") -> None:
        self.zaehler[stand] = self.zaehler.get(stand, 0) + 1
        self._schreiben("  [%s] %s" % (stand, satz))
        if mehr and not self.kurz:
            for zeile in str(mehr).splitlines():
                self._schreiben("           %s" % zeile)

    def hinweis(self, satz: str) -> None:
        if not self.kurz:
            self._schreiben("           %s" % satz)

    def _schreiben(self, zeile: str) -> None:
        self.zeilen.append(zeile)
        print(zeile)

    def schluss(self) -> int:
        self._schreiben("")
        self._schreiben("=" * 70)
        self._schreiben(
            "  %d in Ordnung, %d Hinweise, %d Fehler"
            % (self.zaehler[OK], self.zaehler[WARN], self.zaehler[FEHLER])
        )
        self._schreiben("=" * 70)
        return 1 if self.zaehler[FEHLER] else 0


# --------------------------------------------------------------- Helfer ----

def orb_wurzel(start: Path) -> Path:
    for verzeichnis in (start, *start.parents):
        if (verzeichnis / "backend" / "api" / "http_server.py").is_file():
            return verzeichnis
    raise SystemExit(
        "Ich finde den Orb nicht. Lege den Pruefstand in den Ordner des Orb\n"
        "(dort, wo ORB-STARTEN.bat liegt) oder in den Unterordner werkzeug."
    )


def erreichbar(host: str, port: int, frist: float = 1.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=frist):
            return True
    except OSError:
        return False


def holen(adresse: str, frist: float = 4.0) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(adresse, timeout=frist) as antwort:
            return antwort.status, antwort.read(200000).decode("utf-8", "replace")
    except urllib.error.HTTPError as fehler:
        return fehler.code, ""
    except Exception:
        return 0, ""


def yaml_flach(text: str) -> dict[str, str]:
    """Liest die einfachen ``schluessel: wert``-Zeilen einer YAML-Datei.

    Bewusst kein YAML-Paket: Der Orb selbst kommt ohne aus, und der
    Pruefstand darf nichts voraussetzen, was der Orb nicht hat.
    """

    werte: dict[str, str] = {}
    pfad: list[tuple[int, str]] = []
    for rohzeile in text.splitlines():
        if not rohzeile.strip() or rohzeile.lstrip().startswith("#"):
            continue
        tiefe = len(rohzeile) - len(rohzeile.lstrip(" "))
        zeile = rohzeile.strip()
        if ":" not in zeile:
            continue
        name, _, wert = zeile.partition(":")
        name = name.strip()
        wert = wert.strip().strip('"').strip("'")
        while pfad and pfad[-1][0] >= tiefe:
            pfad.pop()
        voll = ".".join([teil for _, teil in pfad] + [name])
        if wert:
            werte[voll] = wert
        else:
            pfad.append((tiefe, name))
    return werte


# ------------------------------------------------------------- Pruefungen --

def pruefe_python(b: Bericht, wurzel: Path) -> None:
    b.abschnitt("Python")
    b.sagen(OK, "Python %d.%d.%d" % sys.version_info[:3])
    gebuendelt = wurzel / "runtime" / "python" / "python.exe"
    laeuft_gebuendelt = Path(sys.executable).resolve() == gebuendelt.resolve() \
        if gebuendelt.exists() else False
    if not gebuendelt.exists():
        b.sagen(WARN, "Kein gebuendeltes Python unter runtime\\python gefunden.")
    elif laeuft_gebuendelt:
        b.sagen(OK, "Der Pruefstand laeuft im gebuendelten Python des Orb.")
    else:
        b.sagen(WARN,
                "Der Pruefstand laeuft NICHT im gebuendelten Python.",
                "Der Orb selbst benutzt %s.\n"
                "Ergebnisse zu Paketen koennen deshalb abweichen." % gebuendelt)


def pruefe_dateien(b: Bericht, wurzel: Path) -> None:
    b.abschnitt("Quelltext")
    dateien = sorted((wurzel / "backend").rglob("*.py"))
    kaputt: list[str] = []
    for datei in dateien:
        if "__pycache__" in datei.parts:
            continue
        try:
            compile(datei.read_text(encoding="utf-8"), str(datei), "exec")
        except SyntaxError as fehler:
            kaputt.append("%s, Zeile %s: %s"
                          % (datei.relative_to(wurzel), fehler.lineno, fehler.msg))
        except OSError as fehler:
            kaputt.append("%s: %s" % (datei.relative_to(wurzel), fehler))
    anzahl = sum(1 for d in dateien if "__pycache__" not in d.parts)
    if kaputt:
        b.sagen(FEHLER, "%d von %d Dateien lassen sich nicht uebersetzen."
                % (len(kaputt), anzahl), "\n".join(kaputt[:10]))
    else:
        b.sagen(OK, "Alle %d Dateien unter backend lassen sich uebersetzen." % anzahl)


def pruefe_einstellungen(b: Bericht, wurzel: Path) -> None:
    b.abschnitt("Einstellungen")
    datei = wurzel / "config.yaml"
    if not datei.is_file():
        b.sagen(FEHLER, "config.yaml fehlt.")
        return
    try:
        werte = yaml_flach(datei.read_text(encoding="utf-8"))
    except OSError as fehler:
        b.sagen(FEHLER, "config.yaml nicht lesbar: %s" % fehler)
        return

    primaer = werte.get("ai.primary.engine") or werte.get("ai.primary.provider") or ""
    ersatz = werte.get("ai.fallback.engine") or werte.get("ai.fallback.provider") or ""
    if primaer:
        b.sagen(OK, "Erstes Sprachmodell: %s (%s)"
                % (primaer, werte.get("ai.primary.model", "Modell nicht benannt")))
    else:
        b.sagen(FEHLER, "In config.yaml ist kein ai.primary eingetragen.")
    if ersatz:
        b.sagen(OK, "Rueckfall: %s (%s)"
                % (ersatz, werte.get("ai.fallback.model", "Modell nicht benannt")))
    else:
        b.sagen(WARN, "Kein ai.fallback eingetragen - ohne Netz gibt es dann nichts.")

    freigabe = werte.get("security.pre_approved", "")
    if freigabe and freigabe.lower() in {"true", "ja", "yes", "1"}:
        b.sagen(WARN,
                "security.pre_approved steht auf %s." % freigabe,
                "Damit entfaellt die Rueckfrage auch bei schweren Rechten,\n"
                "einschliesslich der Aenderung des eigenen Programmtextes.\n"
                "Fuer 'Vorschlagen, du entscheidest' muss das aus sein.")
    else:
        b.sagen(OK, "Rueckfragen bei schweren Rechten sind eingeschaltet.")


def pruefe_netz(b: Bericht, wurzel: Path) -> None:
    b.abschnitt("Netz und Sprachmodelle")
    draussen = any(erreichbar(name, 443, 1.2)
                   for name in ("one.one.one.one", "dns.google", "example.com"))
    b.sagen(OK if draussen else WARN,
            "Internet erreichbar." if draussen else
            "Kein Internet erreichbar - der Orb muss offline arbeiten koennen.")

    if erreichbar("127.0.0.1", 11434, 1.5):
        stand, text = holen("http://127.0.0.1:11434/api/tags", 6.0)
        modelle: list[str] = []
        try:
            modelle = [m.get("name", "") for m in json.loads(text).get("models", [])]
        except Exception:
            pass
        if modelle:
            b.sagen(OK, "Ollama laeuft, %d Modell(e) geladen." % len(modelle),
                    ", ".join(modelle[:8]))
        else:
            b.sagen(FEHLER, "Ollama laeuft, meldet aber kein einziges Modell.",
                    "Ohne Modell gibt es offline keine Antwort.\n"
                    "Abhilfe: ollama pull <modellname>")
    else:
        b.sagen(FEHLER, "Ollama ist auf 127.0.0.1:11434 nicht erreichbar.",
                "Damit hat der Orb ohne Internet kein Sprachmodell.")


def pruefe_dienst(b: Bericht, wurzel: Path) -> None:
    b.abschnitt("Der Orb selbst")
    if not erreichbar("127.0.0.1", 8756, 1.5):
        b.sagen(WARN, "Der Orb laeuft gerade nicht (127.0.0.1:8756 ist zu).",
                "Starte den Orb und lasse den Pruefstand noch einmal laufen -\n"
                "dann werden auch die Schnittstellen mitgeprueft.")
        return
    b.sagen(OK, "Der Orb antwortet auf 127.0.0.1:8756.")
    for pfad, was in (("/health", "Lebenszeichen"),
                      ("/status", "Zustand"),
                      ("/memory/status", "Gedaechtnis"),
                      ("/evolution/status", "Selbstverbesserung")):
        stand, text = holen("http://127.0.0.1:8756" + pfad, 5.0)
        if stand == 200:
            b.sagen(OK, "%s (%s) antwortet." % (pfad, was))
        elif stand == 0:
            b.sagen(WARN, "%s (%s) antwortet nicht." % (pfad, was))
        else:
            b.sagen(WARN, "%s (%s) antwortet mit %d." % (pfad, was, stand))


def pruefe_vorlesung(b: Bericht, wurzel: Path) -> None:
    b.abschnitt("Vorlesungen")
    sys.path.insert(0, str(wurzel))
    try:
        from backend.studium.vorlesungs_session import (  # noqa: E402
            VorlesungsSession, VorlesungsStand,
        )
    except Exception as fehler:
        b.sagen(FEHLER, "vorlesungs_session laesst sich nicht laden: %s" % fehler)
        return

    def leer():
        sitzung = VorlesungsSession.__new__(VorlesungsSession)
        sitzung.stand = VorlesungsStand(auftrag="x", thema="Philosophie")
        sitzung._alle = {}
        sitzung._aktiv_schluessel = ""
        sitzung._gewuenschtes_fach = ""
        sitzung.max_abschnitte = 24
        return sitzung

    verfehlt = [s for s in VORLESUNGSPROBEN_START if leer().befehl(s) != "start"]
    if verfehlt:
        b.sagen(FEHLER,
                "%d von %d Auftraegen fuer eine NEUE Vorlesung werden nicht erkannt."
                % (len(verfehlt), len(VORLESUNGSPROBEN_START)),
                "Diese Saetze laufen als gewoehnliche Frage weiter und knuepfen\n"
                "an die laufende Vorlesung an:\n"
                + "\n".join(verfehlt))
    else:
        b.sagen(OK, "Alle %d Auftraege fuer eine neue Vorlesung werden erkannt."
                % len(VORLESUNGSPROBEN_START))

    falsch = [s for s in VORLESUNGSPROBEN_NICHTS if leer().befehl(s) != ""]
    if falsch:
        b.sagen(FEHLER,
                "%d Saetze ohne Vorlesungsbezug loesen eine Vorlesung aus."
                % len(falsch), "\n".join(falsch))
    else:
        b.sagen(OK, "Saetze ohne Vorlesungsbezug loesen nichts aus.")

    satz = VORLESUNGSPROBEN_START[8]
    thema = VorlesungsSession._thema_aus(satz)
    if "hält" in thema or "haelt" in thema or "haeltst" in thema:
        b.sagen(FEHLER, "Das erkannte Thema enthaelt noch das Verb der Bitte.",
                "erkannt: %r\nDamit bekommt das Sprachmodell einen unklaren\n"
                "Auftrag und haelt die falsche Vorlesung." % thema)
    elif "Mittelalter" not in thema and "mittelalter" not in thema:
        b.sagen(WARN, "Die Einengung des Themas geht verloren.", "erkannt: %r" % thema)
    else:
        b.sagen(OK, "Das Thema wird sauber erkannt: %r" % thema)

    stand_datei = wurzel / "data" / "vorlesung.json"
    if not stand_datei.is_file():
        b.hinweis("Noch keine gespeicherte Vorlesung.")
        return
    try:
        daten = json.loads(stand_datei.read_text(encoding="utf-8"))
    except (OSError, ValueError) as fehler:
        b.sagen(FEHLER, "data\\vorlesung.json ist nicht lesbar: %s" % fehler)
        return
    faecher = daten.get("vorlesungen", {})
    if not isinstance(faecher, dict):
        b.sagen(WARN, "data\\vorlesung.json hat noch die alte, einfache Form.")
        return
    b.sagen(OK, "%d gespeicherte Vorlesung(en)." % len(faecher))
    for name, wert in faecher.items():
        if not isinstance(wert, dict):
            continue
        b.hinweis("%-45s Abschnitt %s%s"
                  % (name[:45], wert.get("naechster_abschnitt", "?"),
                     " (abgeschlossen)" if wert.get("abgeschlossen") else ""))
        if any(w in name for w in ("haeltst", "haelst", "machst", "erzaehlst")):
            b.sagen(WARN,
                    "Der Ablagename enthaelt ein Verb: %r" % name,
                    "Er stammt aus der alten Themenerkennung. Der Fortschritt\n"
                    "bleibt erhalten; du kannst die Vorlesung unter diesem\n"
                    "Namen weiter fortsetzen oder neu beginnen.")


def pruefe_protokolle(b: Bericht, wurzel: Path) -> None:
    b.abschnitt("Protokolle der letzten 24 Stunden")
    ordner = wurzel / "logs"
    if not ordner.is_dir():
        b.sagen(WARN, "Kein Ordner logs gefunden.")
        return
    grenze = datetime.now() - timedelta(hours=24)
    gross: list[tuple[int, str]] = []
    fehlerzahl = 0
    beispiele: list[str] = []
    for datei in sorted(ordner.glob("*.log")):
        try:
            groesse = datei.stat().st_size
            if datetime.fromtimestamp(datei.stat().st_mtime) < grenze:
                continue
            gross.append((groesse, datei.name))
            text = datei.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for zeile in text.splitlines():
            if "| ERROR" in zeile or "| CRITICAL" in zeile:
                fehlerzahl += 1
                if len(beispiele) < 8:
                    beispiele.append(zeile.strip()[:160])
    gross.sort(reverse=True)
    if gross:
        b.sagen(OK, "%d Protokolldateien wurden heute geschrieben." % len(gross),
                "\n".join("%9d Byte  %s" % (g, n) for g, n in gross[:6]))
        riesig = [(g, n) for g, n in gross if g > 5_000_000]
        if riesig:
            b.sagen(WARN,
                    "Ungewoehnlich grosse Protokolle - meist ein Zeichen dafuer,\n"
                    "dass etwas in einer schnellen Schleife laeuft.",
                    "\n".join("%9d Byte  %s" % (g, n) for g, n in riesig))
    if fehlerzahl:
        b.sagen(WARN, "%d Fehlerzeilen in den letzten 24 Stunden." % fehlerzahl,
                "\n".join(beispiele))
    else:
        b.sagen(OK, "Keine Fehlerzeilen in den letzten 24 Stunden.")


def pruefe_ablage(b: Bericht, wurzel: Path) -> None:
    b.abschnitt("Ablage")
    for name in ("data", "logs", "data/evolution"):
        ordner = wurzel / name
        if not ordner.is_dir():
            b.sagen(WARN, "Ordner %s fehlt." % name)
            continue
        probe = ordner / ".pruefstand-schreibprobe"
        try:
            probe.write_text("x", encoding="utf-8")
            probe.unlink()
            b.sagen(OK, "%s ist da und beschreibbar." % name)
        except OSError as fehler:
            b.sagen(FEHLER, "%s ist nicht beschreibbar: %s" % (name, fehler))


GRUPPEN = {
    "python": pruefe_python,
    "quelltext": pruefe_dateien,
    "einstellungen": pruefe_einstellungen,
    "netz": pruefe_netz,
    "dienst": pruefe_dienst,
    "vorlesung": pruefe_vorlesung,
    "protokolle": pruefe_protokolle,
    "ablage": pruefe_ablage,
}


def main(argv: list[str] | None = None) -> int:
    zerleger = argparse.ArgumentParser(description=__doc__)
    zerleger.add_argument("--kurz", action="store_true", help="nur die Ergebniszeilen")
    zerleger.add_argument("--nur", action="append", default=[],
                          choices=sorted(GRUPPEN), help="nur diese Gruppe pruefen")
    args = zerleger.parse_args(argv)

    wurzel = orb_wurzel(Path(__file__).resolve().parent)
    b = Bericht(kurz=args.kurz)
    b._schreiben("Pruefstand fuer den AI-Orb")
    b._schreiben("Ordner : %s" % wurzel)
    b._schreiben("Zeit   : %s" % datetime.now().strftime("%d.%m.%Y %H:%M:%S"))

    namen = args.nur or list(GRUPPEN)
    beginn = time.time()
    for name in namen:
        try:
            GRUPPEN[name](b, wurzel)
        except Exception as fehler:  # eine Gruppe darf nie den Rest verhindern
            b.sagen(FEHLER, "Die Pruefung '%s' ist selbst gescheitert: %s"
                    % (name, fehler))
    b._schreiben("")
    b._schreiben("Dauer  : %.1f Sekunden" % (time.time() - beginn))
    schluss = b.schluss()

    ziel = wurzel / "pruefstand-bericht.txt"
    try:
        ziel.write_text("\n".join(b.zeilen) + "\n", encoding="utf-8")
        print()
        print("Bericht: %s" % ziel)
    except OSError as fehler:
        print("Bericht konnte nicht geschrieben werden: %s" % fehler)
    return schluss


if __name__ == "__main__":
    sys.exit(main())
