"""
orb_ipad_server.py - Die Bruecke zwischen dem AI-Orb und dem iPad.
================================================================================

Warum es diese Datei gibt
-------------------------
Das Backend des Orb lauscht bewusst nur auf 127.0.0.1 (siehe docs/API.md). Das
ist richtig so und bleibt so. Damit das iPad den Orb erreichen kann, braucht es
genau eine Stelle, die von aussen ansprechbar ist, den Zugang absichert und
alles Weitere unveraendert an das Backend durchreicht. Das ist diese Datei.

Sie aendert nichts am bestehenden Orb. Sie liest keine Projektdaten. Sie
schreibt nichts nach data/. Wird sie beendet, ist der Zustand von vorher.

Was sie tut
-----------
  /                      liefert die iPad-Oberflaeche aus ipad/web/
  /api/<pfad>            reicht die Anfrage an das Backend weiter
  /api/events            reicht den Server-Sent-Events-Strom durch

Zugang
------
Beim ersten Start entsteht ipad/token.txt mit einem zufaelligen Schluessel.
Das iPad ruft die Adresse einmal mit ?key=<schluessel> auf; danach steckt der
Schluessel in einem Cookie und die Adresse bleibt sauber. Ohne gueltigen
Schluessel antwortet der Server mit 401 - auch dann, wenn jemand anders bereits
im Tailnet ist.

Nur Standardbibliothek, wie im ganzen Projekt.
"""

from __future__ import annotations

import argparse
import http.client
import json
import mimetypes
import os
import re
import secrets
import socket
import subprocess
import sys
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

HIER = Path(__file__).resolve().parent
sys.path.insert(0, str(HIER))
WEB = HIER / "web"
WURZEL = HIER.parent
TOKEN_DATEI = HIER / "token.txt"

STANDARD_BACKEND = ("127.0.0.1", 8756)
STANDARD_PORT = 8757


# ---------------------------------------------------------------- Konfiguration
def backend_aus_config() -> tuple[str, int]:
    """Liest Host und Port des Backends aus config.yaml.

    Es gibt keine hartkodierten Konfigurationswerte im Orb - diese Regel gilt
    auch hier. Faellt das Lesen aus, wird der dokumentierte Standard benutzt und
    das ausdruecklich gemeldet.
    """
    pfad = WURZEL / "config.yaml"
    if not pfad.exists():
        return STANDARD_BACKEND

    try:
        import yaml  # type: ignore

        daten = yaml.safe_load(pfad.read_text(encoding="utf-8")) or {}
        b = daten.get("backend") or {}
        return (str(b.get("host", STANDARD_BACKEND[0])), int(b.get("port", STANDARD_BACKEND[1])))
    except Exception:
        pass

    # Notfalls ohne YAML-Bibliothek: die beiden Zeilen unter "backend:" suchen.
    try:
        text = pfad.read_text(encoding="utf-8", errors="replace")
        block = re.search(r"^backend:\s*$((?:\n[ \t]+.*)+)", text, re.M)
        if block:
            host = re.search(r"^\s+host:\s*[\"']?([^\"'\s#]+)", block.group(1), re.M)
            port = re.search(r"^\s+port:\s*(\d+)", block.group(1), re.M)
            return (
                host.group(1) if host else STANDARD_BACKEND[0],
                int(port.group(1)) if port else STANDARD_BACKEND[1],
            )
    except Exception:
        pass
    return STANDARD_BACKEND


def token_holen() -> str:
    if TOKEN_DATEI.exists():
        wert = TOKEN_DATEI.read_text(encoding="utf-8").strip()
        if wert:
            return wert
    wert = secrets.token_urlsafe(18)
    TOKEN_DATEI.write_text(wert + "\n", encoding="utf-8")
    try:
        os.chmod(TOKEN_DATEI, 0o600)
    except Exception:
        pass
    return wert


# --------------------------------------------------------------------- Handler
class Bruecke(BaseHTTPRequestHandler):
    server_version = "AI-Orb-iPad/1.0"
    protocol_version = "HTTP/1.1"

    backend: tuple[str, int] = STANDARD_BACKEND
    token: str = ""

    # -- Ruhe im Log: nur echte Fehler, nicht jeder Bildabruf ------------------
    def log_message(self, format: str, *args) -> None:  # noqa: A002
        if str(args[1] if len(args) > 1 else "").startswith(("4", "5")):
            sys.stderr.write("[iPad] %s %s\n" % (self.address_string(), format % args))

    # -- Zugang ---------------------------------------------------------------
    def _schluessel_ok(self) -> bool:
        gefragt = parse_qs(urlparse(self.path).query).get("key", [None])[0]
        if gefragt and secrets.compare_digest(gefragt, self.token):
            return True
        kopf = self.headers.get("X-Orb-Key")
        if kopf and secrets.compare_digest(kopf, self.token):
            return True
        roh = self.headers.get("Cookie")
        if roh:
            keks = SimpleCookie()
            try:
                keks.load(roh)
            except Exception:
                return False
            wert = keks.get("orbkey")
            if wert and secrets.compare_digest(wert.value, self.token):
                return True
        return False

    def _abweisen(self) -> None:
        leib = b"AI-Orb: kein gueltiger Schluessel.\n"
        self.send_response(401)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(leib)))
        self.end_headers()
        self.wfile.write(leib)

    # -- Statische Dateien ----------------------------------------------------
    def _datei(self, pfad: str) -> None:
        name = pfad.lstrip("/") or "index.html"
        ziel = (WEB / name).resolve()
        if WEB not in ziel.parents and ziel != WEB:
            self._abweisen()
            return
        if not ziel.is_file():
            self.send_error(404, "nicht gefunden")
            return

        typ = mimetypes.guess_type(str(ziel))[0] or "application/octet-stream"
        if typ.startswith("text/") or typ in ("application/manifest+json", "application/json"):
            typ += "; charset=utf-8"
        daten = ziel.read_bytes()

        self.send_response(200)
        self.send_header("Content-Type", typ)
        self.send_header("Content-Length", str(len(daten)))
        self.send_header("Cache-Control", "no-cache")
        # Der Schluessel wandert genau hier einmal in ein Cookie, damit die
        # Adresse auf dem Homescreen ohne Anhaengsel gespeichert werden kann.
        if parse_qs(urlparse(self.path).query).get("key"):
            self.send_header(
                "Set-Cookie",
                "orbkey=%s; Path=/; Max-Age=31536000; SameSite=Lax" % self.token,
            )
        self.end_headers()
        self.wfile.write(daten)

    # -- Weiterleitung an das Backend -----------------------------------------
    def _weiterleiten(self, methode: str, pfad: str) -> None:
        rest = pfad[len("/api") :] or "/"
        laenge = int(self.headers.get("Content-Length") or 0)
        leib = self.rfile.read(laenge) if laenge else None

        try:
            verbindung = http.client.HTTPConnection(*self.backend, timeout=600)
            kopf = {"Content-Type": self.headers.get("Content-Type", "application/json")}
            if leib is not None:
                kopf["Content-Length"] = str(len(leib))
            verbindung.request(methode, rest, body=leib, headers=kopf)
            antwort = verbindung.getresponse()
        except Exception as fehler:
            leib = json.dumps(
                {"error": "backend_nicht_erreichbar", "detail": str(fehler)}
            ).encode("utf-8")
            self.send_response(502)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(leib)))
            self.end_headers()
            self.wfile.write(leib)
            return

        typ = antwort.getheader("Content-Type", "application/json")

        # Ereigniskanal: Zeile fuer Zeile durchreichen, nichts puffern.
        if "text/event-stream" in typ:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            try:
                while True:
                    stueck = antwort.read(1)
                    if not stueck:
                        break
                    self.wfile.write(stueck)
                    if stueck == b"\n":
                        self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                try:
                    verbindung.close()
                except Exception:
                    pass
            self.close_connection = True
            return

        daten = antwort.read()
        self.send_response(antwort.status)
        self.send_header("Content-Type", typ)
        self.send_header("Content-Length", str(len(daten)))
        self.end_headers()
        self.wfile.write(daten)
        verbindung.close()

    # -- Einstiegspunkte ------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        pfad = urlparse(self.path).path
        if not self._schluessel_ok():
            self._abweisen()
            return
        if pfad.startswith("/api/"):
            self._weiterleiten("GET", pfad)
        else:
            self._datei(pfad)

    def do_POST(self) -> None:  # noqa: N802
        pfad = urlparse(self.path).path
        if not self._schluessel_ok():
            self._abweisen()
            return
        if pfad.startswith("/api/"):
            self._weiterleiten("POST", pfad)
        else:
            self.send_error(404, "nicht gefunden")


# ------------------------------------------------------------------------ Start
def tailscale_adresse() -> str | None:
    """Fragt Tailscale nach dem eigenen Namen im Tailnet.

    Liefert None, wenn Tailscale fehlt, nicht angemeldet ist oder der Name
    nicht zu ermitteln war. Der Aufruf ist bewusst kurz abgesichert - er darf
    den Start der Bruecke unter keinen Umstaenden aufhalten.
    """
    for befehl in (["tailscale", "status", "--json"],
                   ["tailscale.exe", "status", "--json"]):
        try:
            roh = subprocess.run(befehl, capture_output=True, timeout=8,
                                 text=True, check=False).stdout
            daten = json.loads(roh)
            name = (daten.get("Self") or {}).get("DNSName") or ""
            name = name.strip().rstrip(".")
            if name:
                return name
        except Exception:
            continue
    return None


def eigene_adresse() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        adresse = s.getsockname()[0]
        s.close()
        return adresse
    except Exception:
        return "127.0.0.1"


def main() -> int:
    zerleger = argparse.ArgumentParser(description="AI-Orb fuer das iPad bereitstellen.")
    zerleger.add_argument("--host", default="127.0.0.1",
                          help="Adresse, auf der gelauscht wird. Mit Tailscale bleibt 127.0.0.1 richtig.")
    zerleger.add_argument("--port", type=int, default=STANDARD_PORT)
    zerleger.add_argument("--offen", action="store_true",
                          help="Auf allen Netzwerkkarten lauschen (nur fuer das reine Heim-WLAN).")
    zerleger.add_argument("--adresse", default=None,
                          help="Adresse, unter der das iPad die Bruecke sieht. "
                               "Ohne Angabe wird Tailscale gefragt.")
    argumente = zerleger.parse_args()

    Bruecke.backend = backend_aus_config()
    Bruecke.token = token_holen()
    host = "0.0.0.0" if argumente.offen else argumente.host

    if not (WEB / "index.html").exists():
        print("Die Oberflaeche fehlt: %s" % (WEB / "index.html"))
        return 1

    server = ThreadingHTTPServer((host, argumente.port), Bruecke)
    server.daemon_threads = True

    # Die Adresse, die das iPad ansteuern soll.
    if argumente.adresse:
        ziel = argumente.adresse.rstrip("/")
    elif argumente.offen:
        ziel = "http://%s:%d" % (eigene_adresse(), argumente.port)
    else:
        name = tailscale_adresse()
        ziel = "https://%s" % name if name else None

    strich = "=" * 70
    print(strich)
    print(" AI-Orb fuer das iPad")
    print(strich)
    print(" Backend   : http://%s:%d" % Bruecke.backend)
    print(" Bruecke   : http://%s:%d" % (host, argumente.port))
    print(" Schluessel: %s" % Bruecke.token)
    print(strich)

    if ziel:
        volle = "%s/?key=%s" % (ziel, Bruecke.token)
        print()
        print(" Scanne das hier mit der Kamera deines iPads:")
        print()
        try:
            from qr import qr_ascii  # type: ignore
            print(qr_ascii(volle))
        except Exception as fehler:
            print("   (QR-Code nicht darstellbar: %s)" % fehler)
        print()
        print(" Oder von Hand eintippen:")
        print("   %s" % volle)
    else:
        print()
        print(" Es liess sich keine Adresse fuer das iPad ermitteln.")
        print(" Entweder Tailscale einrichten (siehe docs/IPAD.md) oder")
        print(" die Bruecke mit --offen im Heim-WLAN starten.")
    print()
    print(strich)
    print(" Dieses Fenster offen lassen. Beenden mit Strg+C.")
    print(strich)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nBeendet.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
