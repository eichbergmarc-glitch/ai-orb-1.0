"""Lokaler HTTP-Server von AI-Orb (ausschließlich Python-Standardbibliothek).

Dieser Server ist die einzige Brücke zwischen dem Python-Backend
(Cognitive-/System-/Data-Schicht) und der Electron-Anwendung (Desktop
Layer). Er lauscht ausschließlich auf ``127.0.0.1`` und ist damit von
außerhalb des lokalen Rechners nicht erreichbar.

Bewusst wird auf externe Web-Frameworks verzichtet:

* Die Installation auf Windows benötigt dadurch keine kompilierten
  Abhängigkeiten und funktioniert auch ohne Internetzugang.
* Der Kommunikationsweg bleibt vollständig nachvollziehbar.

Backend → Frontend erfolgt über **Server-Sent Events** (``GET /events``),
Frontend → Backend über ``POST``-Endpunkte. Beide Richtungen transportieren
ausschließlich Events des zentralen :class:`~backend.events.event_bus.EventBus`;
direkter Zugriff auf Fachmodule findet hier nicht statt.
"""

from __future__ import annotations

import hmac
import ipaddress
import json
import mimetypes
import os
import queue
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote, urlparse

from backend.system.logging_setup import get_logger

logger = get_logger(__name__)

# Typ einer Route-Funktion: erhält das geparste JSON-Body-Dict (bei POST)
# bzw. ein leeres Dict (bei GET) und gibt ein JSON-serialisierbares Ergebnis
# zurück.
RouteHandler = Callable[[dict[str, Any]], Any]

# Typ einer Route fuer unveraenderte Daten: bekommt die Rohdaten und die
# Kopfzeilen der Anfrage, gibt ein JSON-serialisierbares Ergebnis zurueck.
RawRouteHandler = Callable[[bytes, dict[str, str]], Any]


class SseClient:
    """Repräsentiert einen verbundenen Server-Sent-Events-Client.

    Jeder Client besitzt eine eigene, begrenzte Warteschlange. Läuft diese
    voll (z. B. weil das Frontend hängt), werden die ältesten Nachrichten
    verworfen, damit ein langsamer Client das Backend nicht blockiert.
    """

    def __init__(self, max_queue_size: int = 500) -> None:
        self.queue: queue.Queue[str] = queue.Queue(maxsize=max_queue_size)
        self.closed = False

    def push(self, message: str) -> None:
        """Stellt eine Nachricht zur Auslieferung ein (nicht blockierend)."""

        if self.closed:
            return
        try:
            self.queue.put_nowait(message)
        except queue.Full:
            try:
                self.queue.get_nowait()
                self.queue.put_nowait(message)
            except queue.Empty:  # pragma: no cover - Race, praktisch unmöglich
                pass


class SseBroker:
    """Verteilt Nachrichten an alle verbundenen SSE-Clients."""

    def __init__(self) -> None:
        self._clients: set[SseClient] = set()
        self._lock = threading.RLock()

    def register(self) -> SseClient:
        client = SseClient()
        with self._lock:
            self._clients.add(client)
        logger.info("Frontend-Client verbunden (%d aktiv).", len(self._clients))
        return client

    def unregister(self, client: SseClient) -> None:
        client.closed = True
        with self._lock:
            self._clients.discard(client)
        logger.info("Frontend-Client getrennt (%d aktiv).", len(self._clients))

    def broadcast(self, event_name: str, payload: dict[str, Any]) -> None:
        """Sendet ein Event an alle verbundenen Clients."""

        message = json.dumps(
            {"event": event_name, "payload": payload}, ensure_ascii=False, default=str
        )
        # Lock nur für Lesen-Snapshot halten, nicht für Push-Aufrufe
        with self._lock:
            clients = list(self._clients)
        # Push-Aufrufe sind nicht blockierend; Thread-Sicherheit ist gewährleistet
        for client in clients:
            client.push(message)

    @property
    def client_count(self) -> int:
        with self._lock:
            return len(self._clients)


class ApiRouter:
    """Einfache Routing-Tabelle für GET- und POST-Endpunkte."""

    def __init__(self) -> None:
        self._get_routes: dict[str, RouteHandler] = {}
        self._post_routes: dict[str, RouteHandler] = {}
        self._raw_routes: dict[str, RawRouteHandler] = {}

    def get(self, path: str, handler: RouteHandler) -> None:
        """Registriert einen GET-Endpunkt."""

        self._get_routes[path] = handler

    def post(self, path: str, handler: RouteHandler) -> None:
        """Registriert einen POST-Endpunkt."""

        self._post_routes[path] = handler

    def post_raw(self, path: str, handler: RawRouteHandler) -> None:
        """Registriert einen POST-Endpunkt, der die Daten unveraendert bekommt.

        Gebraucht fuer das, was kein JSON ist: eine Tonaufnahme vom iPad.
        Sie als Text zu verpacken kostete ein Drittel mehr Uebertragung
        und einen Umweg ueber Zeichenketten, den niemand braucht.
        """

        self._raw_routes[path] = handler

    def resolve(self, method: str, path: str) -> RouteHandler | None:
        table = self._get_routes if method == "GET" else self._post_routes
        return table.get(path)

    def resolve_raw(self, path: str) -> RawRouteHandler | None:
        """Findet einen Endpunkt fuer unveraenderte Daten."""

        return self._raw_routes.get(path)

    @property
    def routes(self) -> dict[str, list[str]]:
        """Gibt alle registrierten Routen zurück (für den Diagnose-Endpunkt)."""

        return {
            "GET": sorted(self._get_routes.keys()),
            "POST": sorted(self._post_routes.keys()) + sorted(self._raw_routes.keys()),
        }


class _RequestHandler(BaseHTTPRequestHandler):
    """Interner HTTP-Request-Handler.

    Wird von :class:`LocalApiServer` erzeugt; ``router``, ``broker`` und
    ``sse_path`` werden als Klassenattribute injiziert.
    """

    router: ApiRouter
    broker: SseBroker
    sse_path: str
    #: Verzeichnis der gebauten Oberflaeche. ``None`` heisst: Es gibt hier
    #: nichts auszuliefern (reiner API-Betrieb hinter Electron).
    static_root: Path | None = None
    #: Das Losungswort fuer Anfragen von anderen Geraeten. ``None`` heisst:
    #: Es gibt keines - dann wird von aussen niemand hereingelassen.
    zugangstoken: str | None = None
    #: Ohne Losungswort hereinlassen, aber nur aus privaten Netzen
    #: (eigenes WLAN, Tailscale). Schalter: AI_ORB_ZUGANG_OFFEN=1 in der .env.
    zugang_offen: bool = False
    server_version = "AI-Orb"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    # --- Hilfsfunktionen -------------------------------------------------

    #: Fehler, die bedeuten: Der Fragende ist gegangen.
    #:
    #: Das ist kein Serverfehler, sondern der Alltag eines Servers, den
    #: jemand im Sekundentakt fragt und dessen Fragen eine Frist haben.
    #: Läuft die Frist ab, schließt der Fragende die Verbindung – und wer
    #: dann noch antwortet, schreibt in ein totes Rohr.
    CLIENT_GONE = (
        ConnectionAbortedError,
        ConnectionResetError,
        BrokenPipeError,
    )

    def _send_json(self, status: int, data: Any) -> bool:
        """Schickt eine Antwort.

        Returns:
            Ob sie ankam. ``False`` heißt: Der Fragende ist gegangen.
            Das ist ein Umstand, kein Fehler.
        """

        try:
            body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)
            return True
        except self.CLIENT_GONE:
            return False

    def _read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    # --- HTTP-Methoden ---------------------------------------------------

    # --- Zugang von anderen Geraeten -------------------------------------

    #: Name des Kekses, in dem der Browser das Losungswort behaelt.
    ZUGANG_KEKS = "orb_zugang"

    #: Adressen, die "dieser Rechner" bedeuten.
    EIGENE_ADRESSEN = frozenset({"127.0.0.1", "::1", "::ffff:127.0.0.1"})

    def _ist_eigener_rechner(self) -> bool:
        """Ob die Anfrage vom Rechner selbst kommt.

        Electron fragt so - und soll kein Losungswort brauchen.

        Ein vorgeschalteter Tunnel (etwa ``tailscale serve``) meldet sich
        ebenfalls von 127.0.0.1, reicht aber ``X-Forwarded-For`` mit.
        Genau daran ist er zu erkennen: Wer weitergeleitet wurde, sass
        nicht an diesem Rechner - und muss das Losungswort zeigen.
        Ohne diese Unterscheidung waere der Schutz hinter jedem Tunnel
        wirkungslos, ausgerechnet dort, wo er gebraucht wird.
        """

        if self.headers.get("X-Forwarded-For"):
            return False

        # Zweites, unabhaengiges Merkmal: unter welchem Namen wurde
        # gefragt?
        #
        # Ein Tunnel meldet sich von 127.0.0.1 aus. Ob er dabei
        # "X-Forwarded-For" mitschickt, ist seine Entscheidung - und auf
        # eine fremde Entscheidung darf sich ein Schloss nicht allein
        # verlassen. Der Host-Kopf traegt dagegen immer die Adresse, die
        # der Fragende eingetippt hat; bei einem Tunnel ist das der Name
        # des Rechners im Netz, niemals "127.0.0.1". Faellt das eine
        # Merkmal aus, haelt das andere.
        host = self.headers.get("Host", "").split(":")[0].strip().lower()
        if host and host not in ("127.0.0.1", "localhost", "[::1]", "::1"):
            return False

        adresse = self.client_address[0] if self.client_address else ""
        return adresse in self.EIGENE_ADRESSEN

    def _keks_lesen(self, name: str) -> str | None:
        """Liest einen Keks aus dem Kopf der Anfrage."""

        roh = self.headers.get("Cookie", "")
        for teil in roh.split(";"):
            schluessel, _, wert = teil.strip().partition("=")
            if schluessel == name:
                return wert
        return None

    def _stimmt(self, wert: str | None) -> bool:
        """Vergleicht zwei Losungsworte zeitgleich.

        ``hmac.compare_digest`` braucht fuer jeden Vergleich gleich lang.
        Ein gewoehnlicher Vergleich braeuchte laenger, je mehr Zeichen am
        Anfang stimmen - daraus liesse sich das Wort Zeichen fuer Zeichen
        erraten.
        """

        if not wert or not self.zugangstoken:
            return False
        return hmac.compare_digest(wert.strip().lower(), self.zugangstoken.strip().lower())

    #: Adresse, unter der ein Geraet sein Losungswort abgibt.
    ZUGANG_PFAD = "/zugang"

    def _anmeldeseite(self, hinweis: str = "") -> str:
        """Die Seite, auf der ein neues Geraet sein Losungswort eintippt.

        Bewusst ein Formular und nicht nur ein Hinweis: Ein Losungswort
        von Hand in die Adresszeile eines iPad zu fummeln ist muehsam und
        geht oft schief. Ein Feld mit grosser Schrift, ohne
        Autokorrektur und ohne Grossschreibung am Wortanfang ist der
        Unterschied zwischen "geht" und "nervt".
        """

        meldung = (
            f"<p style='color:#ffb4a2;margin:0 0 1rem'>{hinweis}</p>" if hinweis else ""
        )
        return (
            "<!DOCTYPE html><html lang='de'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'>"
            "<title>AI-Orb</title></head>"
            "<body style='font-family:system-ui,-apple-system,sans-serif;"
            "background:radial-gradient(circle at 50% 35%,#0b2b56,#03152d 55%,#010816);"
            "color:#dce8f7;display:flex;align-items:center;justify-content:center;"
            "min-height:100vh;margin:0;padding:1.5rem'>"
            "<form method='post' action='/zugang' style='width:100%;max-width:22rem;"
            "text-align:center'>"
            "<h1 style='font-size:1.35rem;font-weight:600;margin:0 0 .4rem'>AI-Orb</h1>"
            "<p style='opacity:.75;line-height:1.5;margin:0 0 1.4rem'>"
            "Dieses Ger&auml;t ist noch nicht angemeldet.<br>Losungswort vom Rechner "
            "eintippen &ndash; einmalig.</p>"
            f"{meldung}"
            "<input name='wort' autofocus autocomplete='off' autocapitalize='off' "
            "autocorrect='off' spellcheck='false' enterkeyhint='go' "
            "placeholder='xxxx-xxxx-xxxx' "
            "style='width:100%;box-sizing:border-box;font-size:1.25rem;"
            "letter-spacing:.06em;text-align:center;padding:.85rem;border-radius:.7rem;"
            "border:1px solid #2a5f9e;background:#071b34;color:#dce8f7'>"
            "<button type='submit' style='width:100%;margin-top:.9rem;font-size:1.05rem;"
            "padding:.85rem;border-radius:.7rem;border:0;background:#2f7fd6;"
            "color:#fff;font-weight:600'>Anmelden</button>"
            "</form></body></html>"
        )

    def _anmeldung_annehmen(self) -> None:
        """Nimmt das Losungswort aus dem Formular entgegen."""

        from urllib.parse import parse_qs

        if not self._ist_eigener_rechner():
            self._klopfen_vermerken()

        laenge = int(self.headers.get("Content-Length", "0") or "0")
        roh = self.rfile.read(laenge).decode("utf-8", "replace") if laenge > 0 else ""
        # Getippt wird oft mit Leerzeichen oder in Grossbuchstaben. Beides
        # ist kein Grund, jemanden auszusperren.
        angeboten = parse_qs(roh).get("wort", [""])[0].strip().lower()

        if self._stimmt(angeboten):
            self._anmelden_und_weiterleiten("/")
            return

        logger.warning(
            "Falsches Losungswort von %s.",
            self.client_address[0] if self.client_address else "unbekannt",
        )
        self._send_html(401, self._anmeldeseite("Das war nicht das richtige Wort."))


    def _abweisen(self) -> None:
        """Fragt ein fremdes Geraet nach dem Losungswort."""

        if self.zugangstoken:
            self._send_html(401, self._anmeldeseite())
            return

        self._send_html(
            401,
            "<!DOCTYPE html><html lang='de'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'>"
            "<title>AI-Orb</title></head>"
            "<body style='font-family:system-ui,sans-serif;background:#03152d;"
            "color:#dce8f7;display:flex;align-items:center;justify-content:center;"
            "min-height:100vh;margin:0;padding:1.5rem'><div style='max-width:24rem;"
            "text-align:center;line-height:1.6'><h1 style='font-size:1.3rem'>"
            "Kein Zugang</h1><p>Der Fernzugang ist auf dem Rechner noch nicht "
            "eingerichtet. Dort einmal IPAD-EINRICHTEN.bat ausf&uuml;hren.</p>"
            "</div></body></html>",
        )

    #: Adressen, von denen schon ein Klopfen vermerkt wurde.
    _GESEHEN: set[str] = set()

    def _klopfen_vermerken(self) -> None:
        """Haelt fest, dass ein fremdes Geraet den Server erreicht hat.

        Wenn auf einem iPad "nichts angezeigt" wird, gibt es genau zwei
        Moeglichkeiten, und sie erfordern verschiedene Antworten: Die
        Anfrage kam nie an (Firewall, falsches Netz, falsche Adresse),
        oder sie kam an und wurde abgewiesen. Ohne diese Zeile im
        Protokoll ist das von aussen nicht zu unterscheiden - man raet.

        Vermerkt wird jede Adresse nur einmal; ein Browser fragt pro
        Seite dutzendfach.
        """

        adresse = self.client_address[0] if self.client_address else "unbekannt"
        if adresse in self._GESEHEN:
            return
        self._GESEHEN.add(adresse)
        logger.info("Ein Gerät aus dem Netz hat den Orb erreicht: %s", adresse)

    #: Das Netz, das Tailscale an seine Geraete vergibt (100.64.0.0/10).
    _TAILNETZ = ipaddress.ip_network("100.64.0.0/10")

    def _aus_privatem_netz(self) -> bool:
        """Ob die Anfrage aus dem eigenen Netz oder dem Tailnet kommt.

        Hinter ``tailscale serve`` meldet sich die Verbindung von 127.0.0.1;
        die wahre Herkunft steht dann in ``X-Forwarded-For``. Gilt nur, wenn
        ein Absender erkennbar ist - im Zweifel wird abgewiesen. Adressen aus
        dem oeffentlichen Internet kommen nie herein.
        """

        roh = self.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        if not roh and self.client_address:
            roh = self.client_address[0]
        try:
            adresse = ipaddress.ip_address(roh.split("%")[0])
        except ValueError:
            return False
        if getattr(adresse, "ipv4_mapped", None):
            adresse = adresse.ipv4_mapped
        return bool(
            adresse.is_loopback
            or adresse.is_private
            or (adresse.version == 4 and adresse in self._TAILNETZ)
        )

    def _zugang_pruefen(self, query: str = "") -> bool:
        """Laesst herein, wer hereingehoert - und schreibt sonst 401.

        Rueckgabe ``False`` heisst: Es wurde bereits geantwortet.
        """

        if self._ist_eigener_rechner():
            return True

        self._klopfen_vermerken()

        if self.zugang_offen and self._aus_privatem_netz():
            return True

        if self._stimmt(self._keks_lesen(self.ZUGANG_KEKS)):
            return True

        # Das Losungswort darf einmal in der Adresse stehen. Danach zieht
        # der Keks um - die Adresse bleibt sauber, auch wenn sie als
        # Lesezeichen oder App-Symbol auf dem Startbildschirm landet.
        from urllib.parse import parse_qs

        angeboten = parse_qs(query).get("token", [""])[0]
        if self._stimmt(angeboten):
            self._anmelden_und_weiterleiten()
            return False

        self._abweisen()
        return False

    def _anmelden_und_weiterleiten(self, ziel: str | None = None) -> None:
        """Merkt das Losungswort im Browser und schickt zur sauberen Adresse."""

        if ziel is None:
            ziel = urlparse(self.path).path or "/"
        # Hinter einem Tunnel laeuft die Verbindung verschluesselt. Dann
        # darf der Keks das Haus nur verschluesselt verlassen.
        sicher = self.headers.get("X-Forwarded-Proto", "").lower() == "https"
        keks = (
            f"{self.ZUGANG_KEKS}={self.zugangstoken}; Path=/; Max-Age=31536000; "
            "HttpOnly; SameSite=Lax"
        )
        if sicher:
            keks += "; Secure"
        try:
            self.send_response(303)
            self.send_header("Location", ziel)
            self.send_header("Set-Cookie", keks)
            self.send_header("Content-Length", "0")
            self.end_headers()
        except self.CLIENT_GONE:
            pass

    def do_OPTIONS(self) -> None:  # noqa: N802 - von BaseHTTPRequestHandler vorgegeben
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _send_html(self, status: int, html: str) -> bool:
        """Schickt eine Seite fuer einen Menschen statt JSON fuer ein Programm.

        Gebraucht wird das genau an einer Stelle: der Rueckkehr von der
        Google-Anmeldung. Dort sitzt kein Frontend vor dem Ergebnis,
        sondern der Benutzer in seinem Browser - und der soll einen Satz
        lesen, kein JSON.
        """

        try:
            body = html.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return True
        except self.CLIENT_GONE:
            return False

    #: Welche Dateiendung als was gilt. Windows fuehrt in der Registry
    #: erstaunlich oft ``text/plain`` fuer ``.js`` - dann verweigert jeder
    #: Browser das Skript. Diese Tabelle steht deshalb ueber
    #: ``mimetypes`` und macht die Auslieferung auf jedem Rechner gleich.
    MEDIENTYPEN = {
        ".html": "text/html; charset=utf-8",
        ".js": "text/javascript; charset=utf-8",
        ".mjs": "text/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".json": "application/json; charset=utf-8",
        ".webmanifest": "application/manifest+json; charset=utf-8",
        ".svg": "image/svg+xml",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".ico": "image/x-icon",
        ".woff2": "font/woff2",
        ".wav": "audio/wav",
        ".mp3": "audio/mpeg",
        ".glsl": "text/plain; charset=utf-8",
    }

    def _aufloesen(self, pfad: str) -> Path | None:
        """Findet die Datei zu einer Adresse - oder gibt ``None`` zurueck.

        Sicherheit steckt in genau einer Zeile: Nach dem Aufloesen muss
        die Datei unterhalb des Wurzelverzeichnisses liegen. Damit laufen
        ``..``-Ketten, absolute Pfade und Symlinks nach draussen alle ins
        Leere - unabhaengig davon, wie geschickt sie geschrieben sind.
        """

        wurzel = self.static_root
        if wurzel is None:
            return None

        name = unquote(pfad).lstrip("/")
        if name in ("", "/"):
            name = "index.html"

        try:
            ziel = (wurzel / name).resolve()
        except OSError:
            return None

        if wurzel not in ziel.parents and ziel != wurzel:
            logger.warning("Abgewiesener Pfad ausserhalb der Oberflaeche: %s", pfad)
            return None
        if not ziel.is_file():
            return None
        return ziel

    def _send_datei(self, ziel: Path) -> bool:
        """Schickt eine Datei der Oberflaeche."""

        endung = ziel.suffix.lower()
        typ = self.MEDIENTYPEN.get(endung)
        if typ is None:
            geraten, _ = mimetypes.guess_type(ziel.name)
            typ = geraten or "application/octet-stream"

        try:
            inhalt = ziel.read_bytes()
        except OSError as fehler:
            logger.warning("Datei nicht lesbar: %s (%s)", ziel, fehler)
            return self._send_json(500, {"error": "datei_nicht_lesbar"})

        try:
            self.send_response(200)
            self.send_header("Content-Type", typ)
            self.send_header("Content-Length", str(len(inhalt)))
            # Die Oberflaeche aendert sich mit jedem Bauen. Ein Browser,
            # der eine alte Fassung aus dem Zwischenspeicher zeigt, waere
            # der schwerste aller Fehler: Man aendert etwas und sieht es
            # nicht. Er darf zwischenspeichern - aber nur nach Rueckfrage.
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(inhalt)
            return True
        except self.CLIENT_GONE:
            return False

    @staticmethod
    def _bereich_lesen(kopf: str, gesamt: int) -> tuple[int, int] | None:
        """Zerlegt einen ``Range``-Kopf in Anfang und Ende.

        Unterstuetzt ``bytes=0-``, ``bytes=100-200`` und ``bytes=-500``
        (die letzten 500 Bytes). Alles andere gilt als nicht verstanden -
        dann wird die ganze Datei geschickt, was erlaubt ist.
        """

        if not kopf.startswith("bytes=") or gesamt <= 0:
            return None

        spanne = kopf[len("bytes=") :].split(",")[0].strip()
        anfang_text, _, ende_text = spanne.partition("-")

        try:
            if not anfang_text:
                if not ende_text:
                    return None
                laenge = int(ende_text)
                if laenge <= 0:
                    return None
                anfang = max(0, gesamt - laenge)
                ende = gesamt - 1
            else:
                anfang = int(anfang_text)
                ende = int(ende_text) if ende_text else gesamt - 1
        except ValueError:
            return None

        if anfang < 0 or anfang >= gesamt:
            return None
        ende = min(ende, gesamt - 1)
        if ende < anfang:
            return None
        return anfang, ende

    def _send_bytes(self, status: int, daten: bytes, typ: str) -> bool:
        """Schickt Daten, die kein Text sind - und beherrscht Teilstuecke.

        Safari auf iPhone und iPad fragt Ton- und Videodateien nie am
        Stueck ab. Es schickt zuerst ``Range: bytes=0-1``, um zu sehen,
        ob der Server Teilstuecke beherrscht, und spielt erst dann ab.
        Ein Server, der darauf mit der ganzen Datei und ``200`` antwortet,
        gilt ihm als ungeeignet - und zwar lautlos: Die Wiedergabe
        beginnt einfach nie, ohne Fehlermeldung, ohne Eintrag irgendwo.
        Auf jedem anderen Browser laeuft dieselbe Datei einwandfrei.

        Genau das war der Grund, warum die Antwort auf dem iPad stumm
        blieb, obwohl sie erzeugt, ausgeliefert und richtig war.
        """

        gesamt = len(daten)
        bereich = None
        if status == 200:
            bereich = self._bereich_lesen(self.headers.get("Range", ""), gesamt)

        try:
            if bereich is not None:
                anfang, ende = bereich
                stueck = daten[anfang : ende + 1]
                self.send_response(206)
                self.send_header("Content-Type", typ)
                self.send_header("Content-Length", str(len(stueck)))
                self.send_header("Content-Range", f"bytes {anfang}-{ende}/{gesamt}")
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(stueck)
                return True

            self.send_response(status)
            self.send_header("Content-Type", typ)
            self.send_header("Content-Length", str(gesamt))
            # Diese Zeile ist die Einladung: Sie sagt dem Browser, dass
            # er Teilstuecke anfordern darf. Ohne sie fragt Safari gar
            # nicht erst.
            self.send_header("Accept-Ranges", "bytes")
            # Eine gesprochene Antwort gilt genau einmal. Ein
            # Zwischenspeicher wuerde beim naechsten Mal die vorige
            # Antwort abspielen - und das faellt niemandem sofort auf.
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(daten)
            return True
        except self.CLIENT_GONE:
            return False

    def do_GET(self) -> None:  # noqa: N802
        zerlegt = urlparse(self.path)
        path = zerlegt.path

        if not self._zugang_pruefen(zerlegt.query):
            return

        if path == self.sse_path:
            self._stream_events()
            return

        handler = self.router.resolve("GET", path)
        if handler is None:
            # Keine API-Route: Dann ist die Adresse vielleicht die
            # Oberflaeche selbst. Die API hat immer Vorrang, damit eine
            # zufaellig gleich benannte Datei niemals einen Endpunkt
            # verdecken kann.
            ziel = self._aufloesen(path)
            if ziel is not None:
                self._send_datei(ziel)
                return
            self._send_json(404, {"error": "not_found", "path": path})
            return

        # Die Abfrageparameter mitgeben. Google haengt den Anmeldecode als
        # ?code=... an - ohne diesen Schritt kaeme er hier an und
        # verschwaende ungelesen.
        from urllib.parse import parse_qs

        params = {
            name: werte[0]
            for name, werte in parse_qs(zerlegt.query).items()
            if werte
        }

        # Erst rechnen, dann senden – und beides getrennt.
        #
        # Vorher stand der Versand mit im try des Handlers. Brach die
        # Verbindung beim Schreiben ab, landete man im except und
        # versuchte dort, eine 500 über genau dieselbe tote Leitung zu
        # schicken. Die zweite Ausnahme fing niemand mehr; sie stieg bis
        # in den socketserver auf und riss den Kern mit.
        try:
            payload = handler(params)
        except TimeoutError:
            # Der Kern hat den Auftrag schon abgebrochen und protokolliert.
            # Eine volle Rueckverfolgung braucht hier niemand mehr - der
            # Anfragende bekommt eine ehrliche Antwort statt "internal_error".
            logger.warning("%s %s hat das Zeitlimit ueberschritten.", self.command, path)
            self._send_json(504, {
                "error": "timeout",
                "detail": "Der Auftrag dauerte zu lange und wurde abgebrochen.",
            })
            return
        except Exception as exc:  # noqa: BLE001 - kein Request darf den Server beenden.
            logger.exception("Fehler in GET %s", path)
            self._send_json(500, {"error": "internal_error", "detail": str(exc)})
            return

        if isinstance(payload, dict) and "_html" in payload:
            self._send_html(int(payload.get("_status", 200)), str(payload["_html"]))
            return
        # Nicht alles, was ein Endpunkt herausgibt, ist Text. Eine
        # gesprochene Antwort ist eine Tondatei; sie als Zeichenkette zu
        # verpacken waere ein Umweg, den der Browser wieder rueckgaengig
        # machen muesste.
        if isinstance(payload, dict) and "_bytes" in payload:
            status = int(payload.get("_status", 200))
            if status != 200:
                self._send_json(status, {"error": payload.get("error", "fehler")})
                return
            self._send_bytes(
                status,
                bytes(payload["_bytes"]),
                str(payload.get("_type", "application/octet-stream")),
            )
            return
        self._send_json(200, payload)

    def do_POST(self) -> None:  # noqa: N802
        # Die Anmeldung selbst braucht keine Anmeldung - sonst koennte
        # sich nie ein Geraet zum ersten Mal vorstellen.
        if urlparse(self.path).path == self.ZUGANG_PFAD:
            self._anmeldung_annehmen()
            return

        if not self._zugang_pruefen():
            return

        path = urlparse(self.path).path

        roh_handler = self.router.resolve_raw(path)
        if roh_handler is not None:
            self._roh_verarbeiten(path, roh_handler)
            return

        handler = self.router.resolve("POST", path)
        if handler is None:
            self._send_json(404, {"error": "not_found", "path": path})
            return

        try:
            body = self._read_json_body()
        except self.CLIENT_GONE:
            return

        try:
            payload = handler(body)
        except TimeoutError:
            # Der Kern hat den Auftrag schon abgebrochen und protokolliert.
            # Eine volle Rueckverfolgung braucht hier niemand mehr - der
            # Anfragende bekommt eine ehrliche Antwort statt "internal_error".
            logger.warning("%s %s hat das Zeitlimit ueberschritten.", self.command, path)
            self._send_json(504, {
                "error": "timeout",
                "detail": "Der Auftrag dauerte zu lange und wurde abgebrochen.",
            })
            return
        except Exception as exc:  # noqa: BLE001
            logger.exception("Fehler in POST %s", path)
            self._send_json(500, {"error": "internal_error", "detail": str(exc)})
            return

        self._send_json(200, payload)

    #: Wieviel eine einzelne Aufnahme hoechstens wiegen darf.
    #:
    #: Zwei Minuten Ton in 16 kHz, 16 Bit, einkanalig sind knapp vier
    #: Megabyte. Wer mehr schickt, will keine Frage stellen. Ohne Grenze
    #: koennte eine einzige Anfrage den Arbeitsspeicher fuellen.
    ROHDATEN_GRENZE = 12 * 1024 * 1024

    #: Wieviel beim Abweisen hoechstens noch angehoert wird.
    VERWERF_GRENZE = 64 * 1024 * 1024

    def _roh_verwerfen(self, laenge: int) -> None:
        """Liest eine abgewiesene Sendung weg, ohne sie zu behalten."""

        rest = min(laenge, self.VERWERF_GRENZE)
        try:
            while rest > 0:
                stueck = self.rfile.read(min(64 * 1024, rest))
                if not stueck:
                    break
                rest -= len(stueck)
        except self.CLIENT_GONE:
            pass

    def _roh_verarbeiten(self, path: str, handler: "RawRouteHandler") -> None:
        """Nimmt unveraenderte Daten entgegen und reicht sie weiter."""

        laenge = int(self.headers.get("Content-Length", "0") or "0")
        if laenge <= 0:
            self._send_json(400, {"error": "keine_daten"})
            return
        if laenge > self.ROHDATEN_GRENZE:
            # Erst zuhoeren, dann nein sagen.
            #
            # Wer eine Absage schickt, waehrend die Gegenseite noch sendet,
            # bekommt keine Absage zugestellt, sondern einen Abbruch: Der
            # Browser meldet dann "Verbindung fehlgeschlagen" statt "zu
            # gross", und der Mensch davor sucht den Fehler im Netz.
            #
            # Die Daten werden dabei in Haeppchen gelesen und sofort
            # verworfen - der Arbeitsspeicher bleibt leer, es kostet nur
            # Uebertragung. Nach oben ist auch das begrenzt, sonst waere
            # das Zuhoeren selbst die Schwachstelle.
            self._roh_verwerfen(laenge)
            self._send_json(413, {"error": "zu_gross", "grenze": self.ROHDATEN_GRENZE})
            self.close_connection = True
            return

        try:
            daten = self.rfile.read(laenge)
        except self.CLIENT_GONE:
            return

        try:
            ergebnis = handler(daten, dict(self.headers))
        except TimeoutError:
            # Der Kern hat den Auftrag schon abgebrochen und protokolliert.
            # Eine volle Rueckverfolgung braucht hier niemand mehr - der
            # Anfragende bekommt eine ehrliche Antwort statt "internal_error".
            logger.warning("%s %s hat das Zeitlimit ueberschritten.", self.command, path)
            self._send_json(504, {
                "error": "timeout",
                "detail": "Der Auftrag dauerte zu lange und wurde abgebrochen.",
            })
            return
        except Exception as exc:  # noqa: BLE001 - kein Request darf den Server beenden.
            logger.exception("Fehler in POST %s", path)
            self._send_json(500, {"error": "internal_error", "detail": str(exc)})
            return

        self._send_json(200, ergebnis)

    # --- Server-Sent Events ----------------------------------------------

    def _stream_events(self) -> None:
        """Hält die Verbindung offen und streamt Events an das Frontend."""

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        # Sofortige SSE-Daten bestaetigen den Kanal; der kurze Keep-alive-
        # Takt verhindert, dass Windows oder Chromium eine ruhige lokale
        # Verbindung irrtuemlich als inaktiv schliesst.
        self.wfile.write(b"retry: 1000\n: connected\n\n")
        self.wfile.flush()

        client = self.broker.register()
        try:
            while True:
                try:
                    message = client.queue.get(timeout=5.0)
                except queue.Empty:
                    # Keep-Alive-Kommentar, damit Proxys/Clients die
                    # Verbindung nicht wegen Inaktivität schließen.
                    self.wfile.write(b": keep-alive\n\n")
                    self.wfile.flush()
                    continue

                self.wfile.write(f"data: {message}\n\n".encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            self.broker.unregister(client)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        """Leitet HTTP-Zugriffslogs in das AI-Orb-Logging um."""

        logger.debug("HTTP %s", format % args)

    def handle_one_request(self) -> None:
        """Behandelt eine Anfrage und übersteht einen Abbruch.

        Letzte Absicherung. Selbst wenn irgendwo tiefer noch auf eine
        geschlossene Verbindung geschrieben wird, darf das den Kern nicht
        mitreißen – die Oberfläche fragt im Sekundentakt, und jede Frage
        hat eine Frist.
        """

        try:
            super().handle_one_request()
        except self.CLIENT_GONE:
            self.close_connection = True

    def handle_error(self, *args: Any) -> None:
        """Meldet Fehler, ohne die Konsole zu fluten.

        ``socketserver`` schreibt sonst jede Ausnahme als Rückverfolgung
        auf die Fehlerausgabe. Bei einem Verbindungsabbruch pro Sekunde
        wird daraus ein Wasserfall, in dem die eine Meldung untergeht, auf
        die es ankäme.
        """

        logger.debug("Verbindung abgebrochen.", exc_info=True)


class LocalApiServer:
    """Startet und verwaltet den lokalen HTTP-/SSE-Server in einem eigenen
    Thread."""

    def __init__(
        self,
        host: str,
        port: int,
        router: ApiRouter,
        broker: SseBroker,
        sse_path: str = "/events",
        static_root: Path | None = None,
        zugangstoken: str | None = None,
        zugang_offen: bool | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._router = router
        self._broker = broker
        self._sse_path = sse_path
        self._static_root = static_root
        self._zugangstoken = zugangstoken or os.environ.get("AI_ORB_WEB_TOKEN") or None
        # Die Config (backend.ohne_losungswort) entscheidet; ohne Eintrag gilt
        # der Schalter AI_ORB_ZUGANG_OFFEN aus der .env.
        if zugang_offen is None:
            zugang_offen = os.environ.get("AI_ORB_ZUGANG_OFFEN", "").strip().lower() in {
                "1", "ja", "true", "an",
            }
        self._zugang_offen = bool(zugang_offen)
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Startet den Server im Hintergrund (nicht blockierend)."""

        handler_class = type(
            "AiOrbRequestHandler",
            (_RequestHandler,),
            {
                "router": self._router,
                "broker": self._broker,
                "sse_path": self._sse_path,
                "static_root": self._static_root,
                "zugangstoken": self._zugangstoken,
                "zugang_offen": self._zugang_offen,
            },
        )

        self._httpd = ThreadingHTTPServer((self._host, self._port), handler_class)
        self._httpd.daemon_threads = True
        self._thread = threading.Thread(
            target=self._httpd.serve_forever,
            name="ai-orb-http",
            daemon=True,
        )
        self._thread.start()
        logger.info("Lokaler API-Server läuft auf http://%s:%s", self._host, self._port)
        self._erreichbarkeit_herstellen()
        if self._host not in ("127.0.0.1", "localhost", "::1"):
            if self._zugang_offen:
                logger.warning(
                    "Fernzugang OHNE Losungswort (AI_ORB_ZUGANG_OFFEN): Geraete aus "
                    "dem eigenen Netz und dem Tailnet kommen ohne Passwort herein, "
                    "das oeffentliche Internet nicht."
                )
            elif self._zugangstoken:
                logger.info(
                    "Fernzugang ist offen (%s) und durch ein Losungswort geschützt.",
                    self._host,
                )
            else:
                logger.warning(
                    "Der Server lauscht auf %s, es ist aber kein Losungswort "
                    "gesetzt (AI_ORB_WEB_TOKEN in .env). Fremde Geräte werden "
                    "abgewiesen.",
                    self._host,
                )
        if self._static_root is not None:
            logger.info("Oberfläche wird ausgeliefert aus %s", self._static_root)
        else:
            logger.info(
                "Keine gebaute Oberfläche gefunden - der Server antwortet nur "
                "auf API-Anfragen. Mit 'npm run build' entsteht sie."
            )

    def _eigene_netzadresse(self) -> str:
        """Die Adresse dieses Rechners im eigenen Netz - oder leer.

        ``0.0.0.0`` steht für "auf allen Netzwerkkarten" und ist deshalb
        keine Adresse, die man auf einem iPad eintippen könnte. Welche es
        wäre, weiß nur dieser Rechner - und niemand sucht sie gern in den
        Windows-Einstellungen.
        """

        if self._host not in ("0.0.0.0", "::"):
            return ""

        import socket

        verbindung = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            # Kein Byte geht hinaus: Das Betriebssystem verrät beim
            # Auswählen der Route, welche Karte es nähme - und damit
            # deren Adresse.
            verbindung.connect(("192.0.2.1", 9))
            return str(verbindung.getsockname()[0])
        except OSError:
            logger.warning("Die eigene Adresse im Netz war nicht zu ermitteln.")
            return ""
        finally:
            verbindung.close()

    def _erreichbarkeit_herstellen(self) -> None:
        """Sorgt dafür, dass andere Geräte hereinkommen - und sagt wie.

        Zwei Wege, und sie sind unabhängig voneinander:

        Der eine führt durchs eigene WLAN und setzt voraus, dass der
        Server auf allen Netzwerkkarten lauscht.

        Der andere führt über Tailscale und braucht das *nicht*: Die
        Weiterleitung verbindet sich von diesem Rechner aus mit
        ``127.0.0.1``. Deshalb wird sie auch dann eingerichtet, wenn der
        Server nur mit sich selbst spricht - sonst hinge der Weg, der
        unterwegs trägt und das Mikrofon freigibt, an einer Einstellung,
        die mit ihm nichts zu tun hat.
        """

        adresse = self._eigene_netzadresse()
        if adresse:
            logger.info(
                "Von anderen Geräten im selben Netz erreichbar unter http://%s:%s",
                adresse,
                self.port,
            )

        # Und jetzt der Weg, der auch unterwegs trägt: die verschlüsselte
        # Adresse über Tailscale. Sie wird beim Start eingerichtet, damit
        # niemand vorher eine Datei anklicken muss - im Hintergrund,
        # damit ein hängendes fremdes Programm den Orb nicht aufhält.
        try:
            from backend.system.ipad_verbindung import im_hintergrund_einrichten

            im_hintergrund_einrichten(self.port, adresse)
        except Exception:  # noqa: BLE001 - der Start hängt nicht daran.
            logger.exception("Die iPad-Verbindung konnte nicht angestoßen werden.")

    def stop(self) -> None:
        """Beendet den Server geordnet."""

        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
            logger.info("Lokaler API-Server beendet.")

    @property
    def port(self) -> int:
        """Der tatsächlich gebundene Port (relevant, wenn Port 0 genutzt wird)."""

        if self._httpd is None:
            return self._port
        return int(self._httpd.server_address[1])
