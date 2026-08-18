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

import json
import queue
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable
from urllib.parse import urlparse

from backend.system.logging_setup import get_logger

logger = get_logger(__name__)

# Typ einer Route-Funktion: erhält das geparste JSON-Body-Dict (bei POST)
# bzw. ein leeres Dict (bei GET) und gibt ein JSON-serialisierbares Ergebnis
# zurück.
RouteHandler = Callable[[dict[str, Any]], Any]


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
        with self._lock:
            clients = list(self._clients)
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

    def get(self, path: str, handler: RouteHandler) -> None:
        """Registriert einen GET-Endpunkt."""

        self._get_routes[path] = handler

    def post(self, path: str, handler: RouteHandler) -> None:
        """Registriert einen POST-Endpunkt."""

        self._post_routes[path] = handler

    def resolve(self, method: str, path: str) -> RouteHandler | None:
        table = self._get_routes if method == "GET" else self._post_routes
        return table.get(path)

    @property
    def routes(self) -> dict[str, list[str]]:
        """Gibt alle registrierten Routen zurück (für den Diagnose-Endpunkt)."""

        return {
            "GET": sorted(self._get_routes.keys()),
            "POST": sorted(self._post_routes.keys()),
        }


class _RequestHandler(BaseHTTPRequestHandler):
    """Interner HTTP-Request-Handler.

    Wird von :class:`LocalApiServer` erzeugt; ``router``, ``broker`` und
    ``sse_path`` werden als Klassenattribute injiziert.
    """

    router: ApiRouter
    broker: SseBroker
    sse_path: str
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

    def do_GET(self) -> None:  # noqa: N802
        zerlegt = urlparse(self.path)
        path = zerlegt.path

        if path == self.sse_path:
            self._stream_events()
            return

        handler = self.router.resolve("GET", path)
        if handler is None:
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
        except Exception as exc:  # noqa: BLE001 - kein Request darf den Server beenden.
            logger.exception("Fehler in GET %s", path)
            self._send_json(500, {"error": "internal_error", "detail": str(exc)})
            return

        if isinstance(payload, dict) and "_html" in payload:
            self._send_html(int(payload.get("_status", 200)), str(payload["_html"]))
            return
        self._send_json(200, payload)

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
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
        except Exception as exc:  # noqa: BLE001
            logger.exception("Fehler in POST %s", path)
            self._send_json(500, {"error": "internal_error", "detail": str(exc)})
            return

        self._send_json(200, payload)

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
    ) -> None:
        self._host = host
        self._port = port
        self._router = router
        self._broker = broker
        self._sse_path = sse_path
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
