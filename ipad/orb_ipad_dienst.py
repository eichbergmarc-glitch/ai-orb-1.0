"""
orb_ipad_dienst.py - Haelt den iPad-Zugang dauerhaft bereit.
================================================================================

Warum es diese Datei gibt
-------------------------
Die Bruecke von Hand zu starten ist eine Huerde, die jedes Mal wiederkommt.
Gefragt war: Das iPad soll erreichbar sein, sobald der Orb laeuft - ohne
weiteres Zutun.

Der naheliegende Weg waere, die Bruecke vom Startskript des Orb aus mit
aufzurufen. Der ist hier bewusst nicht gewaehlt. Er wuerde bedeuten, in den
Start des Orb einzugreifen, und damit koennte ein Fehler in der Bruecke den
Orb selbst am Starten hindern. Das waere ein schlechter Tausch: Der iPad-
Zugang ist eine Annehmlichkeit, der Orb ist die Sache selbst.

Stattdessen laeuft dieser Begleiter still im Hintergrund und wartet. Ist
der Orb aus, meldet die Bruecke dem iPad schlicht "keine Verbindung" - was
zutrifft. Startet der Orb, ist sie schon da. Aus Sicht des Benutzers ist
das genau das Gewuenschte: Orb starten, iPad tippen, fertig. Und geht hier
etwas schief, merkt der Orb davon nichts.

Was der Begleiter tut
---------------------
  1. Er prueft, ob er schon laeuft. Ein zweiter waere nutzlos und wuerde
     sich am belegten Port die Zaehne ausbeissen.
  2. Er sorgt dafuer, dass der Port im Tailnet freigegeben ist. Gleich nach
     dem Anmelden braucht Tailscale dafuer manchmal ein paar Sekunden -
     deshalb mehrere Versuche mit wachsendem Abstand.
  3. Er startet die Bruecke und stellt sie wieder her, falls sie abstuerzt.
  4. Er schreibt mit, was er tut, nach ``logs/ipad-bruecke.log``.

Benutzung
---------
    python ipad/orb_ipad_dienst.py                 einmal starten
    python ipad/orb_ipad_dienst.py --einrichten    beim Anmelden mitstarten
    python ipad/orb_ipad_dienst.py --entfernen     das wieder zuruecknehmen
    python ipad/orb_ipad_dienst.py --zustand       nachsehen, wie es steht
"""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time
from datetime import datetime
from http.server import ThreadingHTTPServer
from pathlib import Path

HIER = Path(__file__).resolve().parent
WURZEL = HIER.parent
sys.path.insert(0, str(HIER))

from orb_ipad_server import (  # noqa: E402
    STANDARD_PORT,
    Bruecke,
    backend_aus_config,
    tailscale_adresse,
    token_holen,
)

PROTOKOLL = WURZEL / "logs" / "ipad-bruecke.log"
#: Ab dieser Groesse wird das Protokoll einmal umgehaengt statt zu wachsen.
PROTOKOLL_HOECHSTENS = 512_000
AUTOSTART_NAME = "AI-Orb-iPad.vbs"


# --------------------------------------------------------------- Mitschreiben
def notiz(text: str) -> None:
    """Schreibt eine Zeile ins Protokoll und, wenn moeglich, auf den Schirm."""

    zeile = f"{datetime.now():%d.%m.%Y %H:%M:%S}  {text}"
    try:
        PROTOKOLL.parent.mkdir(parents=True, exist_ok=True)
        if PROTOKOLL.exists() and PROTOKOLL.stat().st_size > PROTOKOLL_HOECHSTENS:
            PROTOKOLL.replace(PROTOKOLL.with_suffix(".log.alt"))
        with PROTOKOLL.open("a", encoding="utf-8") as datei:
            datei.write(zeile + "\n")
    except OSError:
        pass
    try:
        print(zeile, flush=True)
    except Exception:  # noqa: BLE001 - ohne Konsole (pythonw) gibt es kein stdout.
        pass


# ------------------------------------------------------------ Einzelstueck
def laeuft_schon(port: int) -> bool:
    """Antwortet auf dem Port bereits jemand?

    Geprueft wird durch Anklopfen, nicht durch eine Sperrdatei: Eine Datei
    kann nach einem Absturz liegen bleiben und den Neustart fuer immer
    verhindern. Ein offener Port kann das nicht.
    """

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as verbindung:
        verbindung.settimeout(1.0)
        return verbindung.connect_ex(("127.0.0.1", port)) == 0


# ------------------------------------------------------------- Tailscale
def tailscale_befehl(*argumente: str) -> tuple[int, str]:
    for programm in ("tailscale", "tailscale.exe"):
        try:
            lauf = subprocess.run(
                [programm, *argumente], capture_output=True, text=True, timeout=20,
            )
            return lauf.returncode, (lauf.stdout + lauf.stderr).strip()
        except FileNotFoundError:
            continue
        except Exception as fehler:  # noqa: BLE001
            return 1, str(fehler)
    return 127, "Tailscale ist nicht installiert."


def freigabe_sichern(port: int, versuche: int = 6) -> str | None:
    """Gibt den Port im Tailnet frei und liefert den Namen des Rechners.

    Mehrere Versuche mit wachsendem Abstand: Beim Start des Rechners ist
    der Tailscale-Dienst oft noch nicht so weit, und ein einziger
    Fehlschlag wuerde den iPad-Zugang fuer die ganze Sitzung kosten.
    """

    code, _ = tailscale_befehl("version")
    if code == 127:
        # Gar nicht installiert - dann hat Warten keinen Zweck.
        notiz("Tailscale ist nicht installiert. Die Bruecke laeuft nur lokal.")
        return None

    for versuch in range(1, versuche + 1):
        name = tailscale_adresse()
        if name:
            code, ausgabe = tailscale_befehl("serve", "--bg", str(port))
            if code != 0:
                # Aeltere Fassungen kennen --bg noch nicht.
                code, ausgabe = tailscale_befehl(
                    "serve", "https", "/", f"http://127.0.0.1:{port}"
                )
            if code == 0:
                notiz(f"Im Tailnet freigegeben: https://{name}/")
                return name
            notiz(f"Freigabe fehlgeschlagen ({ausgabe[:160]})")
            if "cert" in ausgabe.lower() or "https" in ausgabe.lower():
                notiz(
                    "  Wahrscheinlich fehlt der Haken: login.tailscale.com/admin/dns"
                    " -> HTTPS Certificates -> Enable."
                )
            return None
        if versuch < versuche:
            notiz(f"Tailscale noch nicht bereit (Versuch {versuch}). Warte.")
            time.sleep(min(30.0, 2.0 * versuch))
    notiz("Tailscale meldet sich nicht. Die Bruecke laeuft trotzdem, nur lokal.")
    return None


# ------------------------------------------------------- Autostart einrichten
def autostart_ordner() -> Path:
    daten = os.environ.get("APPDATA")
    if not daten:
        raise SystemExit("Diese Funktion gibt es nur unter Windows.")
    return Path(daten) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def python_ohne_fenster() -> Path:
    """Der Python-Starter ohne Konsolenfenster, sonst der gewoehnliche."""

    hier = Path(sys.executable)
    ohne = hier.with_name("pythonw.exe")
    return ohne if ohne.exists() else hier


def autostart_einrichten() -> int:
    ziel = autostart_ordner() / AUTOSTART_NAME
    starter = python_ohne_fenster()
    # Ein winziges Skript, das den Begleiter ohne sichtbares Fenster startet.
    # Der Umweg ueber VBScript ist der einzige Weg, unter Windows ohne
    # zusaetzliche Rechte und ohne aufblitzendes Fenster mitzustarten.
    inhalt = (
        'Set Schale = CreateObject("WScript.Shell")\r\n'
        f'Schale.CurrentDirectory = "{WURZEL}"\r\n'
        f'Schale.Run """{starter}"" ""{HIER / "orb_ipad_dienst.py"}""", 0, False\r\n'
    )
    ziel.parent.mkdir(parents=True, exist_ok=True)
    ziel.write_text(inhalt, encoding="utf-8")
    notiz(f"Beim Anmelden wird jetzt mitgestartet: {ziel}")
    return 0


def autostart_entfernen() -> int:
    ziel = autostart_ordner() / AUTOSTART_NAME
    if ziel.exists():
        ziel.unlink()
        notiz("Der Mitstart beim Anmelden ist entfernt.")
    else:
        notiz("Es war kein Mitstart eingerichtet.")
    return 0


def autostart_steht() -> bool:
    try:
        return (autostart_ordner() / AUTOSTART_NAME).exists()
    except SystemExit:
        return False


# ------------------------------------------------------------------ Zustand
def zustand_zeigen(port: int) -> int:
    host, backend_port = backend_aus_config()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as verbindung:
        verbindung.settimeout(1.5)
        orb_laeuft = verbindung.connect_ex((host, backend_port)) == 0
    name = tailscale_adresse()
    strich = "=" * 70
    print(strich)
    print(" Zustand des iPad-Zugangs")
    print(strich)
    print(f"  Orb-Backend    : {'laeuft' if orb_laeuft else 'aus'}  ({host}:{backend_port})")
    print(f"  Bruecke        : {'laeuft' if laeuft_schon(port) else 'aus'}  (127.0.0.1:{port})")
    print(f"  Tailscale      : {name or 'nicht angemeldet'}")
    print(f"  Mitstart       : {'eingerichtet' if autostart_steht() else 'nicht eingerichtet'}")
    print(f"  Protokoll      : {PROTOKOLL}")
    if name:
        print()
        print(f"  Adresse fuers iPad: https://{name}/")
    print(strich)
    return 0


# --------------------------------------------------------------------- Lauf
def dauerlauf(port: int, host: str = "127.0.0.1") -> int:
    """Startet die Bruecke und haelt sie am Leben."""

    Bruecke.backend = backend_aus_config()
    Bruecke.token = token_holen()

    notiz("=" * 60)
    notiz(f"Begleiter gestartet. Backend: {Bruecke.backend[0]}:{Bruecke.backend[1]}")
    name = freigabe_sichern(port)
    if name:
        notiz(f"iPad-Adresse: https://{name}/?key={Bruecke.token}")

    pause = 2.0
    while True:
        try:
            server = ThreadingHTTPServer((host, port), Bruecke)
            server.daemon_threads = True
        except OSError as fehler:
            notiz(f"Port {port} liess sich nicht belegen ({fehler}). Neuer Versuch in {pause:.0f}s.")
            time.sleep(pause)
            pause = min(60.0, pause * 2)
            continue

        notiz(f"Bruecke hoert auf http://{host}:{port}")
        pause = 2.0
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            notiz("Beendet.")
            server.server_close()
            return 0
        except Exception as fehler:  # noqa: BLE001 - ein Absturz darf nicht das Ende sein.
            notiz(f"Bruecke abgestuerzt ({fehler}). Neustart in 3 s.")
            try:
                server.server_close()
            except Exception:  # noqa: BLE001
                pass
            time.sleep(3.0)


def main() -> int:
    zerleger = argparse.ArgumentParser(description="Haelt den iPad-Zugang bereit.")
    zerleger.add_argument("--port", type=int, default=STANDARD_PORT)
    zerleger.add_argument("--einrichten", action="store_true",
                          help="Beim Anmelden mitstarten.")
    zerleger.add_argument("--entfernen", action="store_true",
                          help="Den Mitstart zuruecknehmen.")
    zerleger.add_argument("--zustand", action="store_true",
                          help="Nachsehen, wie es steht.")
    argumente = zerleger.parse_args()

    if argumente.einrichten:
        return autostart_einrichten()
    if argumente.entfernen:
        return autostart_entfernen()
    if argumente.zustand:
        return zustand_zeigen(argumente.port)

    if laeuft_schon(argumente.port):
        notiz(f"Auf Port {argumente.port} laeuft bereits jemand. Nichts zu tun.")
        return 0
    return dauerlauf(argumente.port)


if __name__ == "__main__":
    raise SystemExit(main())
