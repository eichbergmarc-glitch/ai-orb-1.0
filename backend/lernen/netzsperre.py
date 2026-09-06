"""Die Netzsperre: Offline behaupten genügt nicht, es muss verhindert sein.

Eine Offlineabnahme, bei der man das Netzkabel "hätte ziehen sollen", ist
keine Abnahme. Sie beweist nur, dass niemand hingesehen hat. Diese Datei
zieht das Kabel im Programm: Nach ``sperren()`` scheitert jeder Versuch,
eine Verbindung nach draussen aufzubauen, mit ``NetzGesperrt`` - und zwar
bevor ein Paket den Rechner verlässt.

Wie gesperrt wird

Unter dem eigentlichen Netzverkehr liegen wenige Engpässe, und die werden
alle ersetzt: ``socket.socket.connect`` und ``connect_ex`` (auch für rohe
IP-Adressen), ``socket.create_connection``, ``socket.getaddrinfo`` und
``socket.gethostbyname`` (der Namensdienst) sowie
``socket.socket.sendto`` (verbindungslose Pakete). Wer darunter noch
durchkäme, müsste am Betriebssystem vorbei arbeiten.

Was erlaubt bleibt

Die Rückschleife (``127.0.0.1``, ``::1``, Unix-Sockets). Ohne sie liefe
kein lokales Modell und kein lokaler Dienst - und genau die sollen im
Offlinebetrieb ja arbeiten. Wer auch die sperren will, ruft
``sperren(loopback_erlaubt=False)``.

Der Beweis

``beweis()`` versucht wirklich, nach draussen zu greifen. Schlägt der
Versuch NICHT fehl, ist die Sperre nicht aktiv - und dann darf keine
Abnahme als bestanden gelten. Diese Umkehrung ist der Punkt der ganzen
Datei: Nicht die Sperre wird geglaubt, sondern ihr Scheitern gemessen.
"""

from __future__ import annotations

import ipaddress
import socket
from typing import Any, Callable

from backend.system.logging_setup import get_logger

logger = get_logger(__name__)


class NetzGesperrt(OSError):
    """Ein Verbindungsversuch wurde von der Netzsperre abgewiesen."""


#: Die Adresse, an der der Beweis geführt wird. Sie wird nie erreicht -
#: der Versuch soll scheitern. Bewusst eine Adresse ohne Namensauflösung,
#: damit der Beweis auch dann greift, wenn nur der Namensdienst kaputt ist.
BEWEISZIEL: tuple[str, int] = ("1.1.1.1", 443)

_originale: dict[str, Callable[..., Any]] = {}
_aktiv = False
_loopback_erlaubt = True


def _ist_loopback(host: Any) -> bool:
    """Ob eine Adresse auf dem eigenen Rechner bleibt."""

    text = str(host or "").strip().strip("[]")
    if not text or text in {"localhost", "localhost.localdomain"}:
        return True
    try:
        return ipaddress.ip_address(text).is_loopback
    except ValueError:
        return False


def _pruefen(ziel: Any) -> None:
    """Wirft, wenn das Ziel draussen liegt."""

    host: Any = ziel
    if isinstance(ziel, (tuple, list)) and ziel:
        host = ziel[0]
    if _loopback_erlaubt and _ist_loopback(host):
        return
    raise NetzGesperrt(
        f"Die Netzsperre ist aktiv; '{host}' ist von hier aus nicht erreichbar."
    )


def sperren(*, loopback_erlaubt: bool = True) -> None:
    """Schaltet die Sperre ein. Mehrfaches Aufrufen schadet nicht."""

    global _aktiv, _loopback_erlaubt
    _loopback_erlaubt = loopback_erlaubt
    if _aktiv:
        return

    _originale["connect"] = socket.socket.connect
    _originale["connect_ex"] = socket.socket.connect_ex
    _originale["create_connection"] = socket.create_connection
    _originale["getaddrinfo"] = socket.getaddrinfo
    _originale["gethostbyname"] = socket.gethostbyname
    _originale["sendto"] = socket.socket.sendto

    def _connect(selbst: Any, ziel: Any, *rest: Any) -> Any:
        _pruefen(ziel)
        return _originale["connect"](selbst, ziel, *rest)

    def _connect_ex(selbst: Any, ziel: Any, *rest: Any) -> Any:
        _pruefen(ziel)
        return _originale["connect_ex"](selbst, ziel, *rest)

    def _create_connection(adresse: Any, *rest: Any, **kw: Any) -> Any:
        _pruefen(adresse)
        return _originale["create_connection"](adresse, *rest, **kw)

    def _getaddrinfo(host: Any, port: Any, *rest: Any, **kw: Any) -> Any:
        _pruefen(host)
        return _originale["getaddrinfo"](host, port, *rest, **kw)

    def _gethostbyname(host: Any) -> Any:
        _pruefen(host)
        return _originale["gethostbyname"](host)

    def _sendto(selbst: Any, daten: Any, *rest: Any) -> Any:
        if rest:
            _pruefen(rest[-1])
        return _originale["sendto"](selbst, daten, *rest)

    socket.socket.connect = _connect  # type: ignore[method-assign]
    socket.socket.connect_ex = _connect_ex  # type: ignore[method-assign]
    socket.create_connection = _create_connection  # type: ignore[assignment]
    socket.getaddrinfo = _getaddrinfo  # type: ignore[assignment]
    socket.gethostbyname = _gethostbyname  # type: ignore[assignment]
    socket.socket.sendto = _sendto  # type: ignore[method-assign]
    _aktiv = True
    logger.info(
        "Netzsperre aktiv (Rueckschleife %s).",
        "erlaubt" if loopback_erlaubt else "gesperrt",
    )


def entsperren() -> None:
    """Nimmt die Sperre zurück - für Tests, die sie ein- und ausschalten."""

    global _aktiv
    if not _aktiv:
        return
    socket.socket.connect = _originale["connect"]  # type: ignore[method-assign]
    socket.socket.connect_ex = _originale["connect_ex"]  # type: ignore[method-assign]
    socket.create_connection = _originale["create_connection"]  # type: ignore[assignment]
    socket.getaddrinfo = _originale["getaddrinfo"]  # type: ignore[assignment]
    socket.gethostbyname = _originale["gethostbyname"]  # type: ignore[assignment]
    socket.socket.sendto = _originale["sendto"]  # type: ignore[method-assign]
    _originale.clear()
    _aktiv = False
    logger.info("Netzsperre aufgehoben.")


def ist_aktiv() -> bool:
    return _aktiv


def beweis(*, ziel: tuple[str, int] = BEWEISZIEL) -> dict[str, Any]:
    """Versucht wirklich hinauszukommen und berichtet, was passierte.

    Returns:
        ``{"gesperrt": bool, "ziel": str, "fehler": str, "art": str}``.
        ``gesperrt`` ist nur dann ``True``, wenn der Versuch mit
        ``NetzGesperrt`` endete - ein gewöhnlicher Netzfehler zählt
        ausdrücklich NICHT als Beweis, denn er könnte auch von einem
        vorübergehend gestörten Anschluss kommen.
    """

    bericht: dict[str, Any] = {
        "ziel": f"{ziel[0]}:{ziel[1]}",
        "gesperrt": False,
        "art": "",
        "fehler": "",
    }
    try:
        verbindung = socket.create_connection(ziel, timeout=3.0)
    except NetzGesperrt as fehler:
        bericht["gesperrt"] = True
        bericht["art"] = "NetzGesperrt"
        bericht["fehler"] = str(fehler)
        return bericht
    except Exception as fehler:  # noqa: BLE001
        bericht["art"] = type(fehler).__name__
        bericht["fehler"] = (
            f"{fehler} - das ist ein gewoehnlicher Netzfehler, kein Beweis "
            "fuer eine aktive Sperre."
        )
        return bericht
    verbindung.close()
    bericht["art"] = "verbunden"
    bericht["fehler"] = "Die Verbindung kam zustande; die Sperre ist NICHT aktiv."
    return bericht


def namensbeweis(*, name: str = "example.com") -> dict[str, Any]:
    """Derselbe Beweis für den Namensdienst."""

    bericht: dict[str, Any] = {"ziel": name, "gesperrt": False, "art": "", "fehler": ""}
    try:
        socket.getaddrinfo(name, 443)
    except NetzGesperrt as fehler:
        bericht.update(gesperrt=True, art="NetzGesperrt", fehler=str(fehler))
        return bericht
    except Exception as fehler:  # noqa: BLE001
        bericht.update(
            art=type(fehler).__name__,
            fehler=f"{fehler} - gewoehnlicher Aufloesungsfehler, kein Beweis.",
        )
        return bericht
    bericht.update(art="aufgeloest", fehler="Der Name wurde aufgeloest; keine Sperre.")
    return bericht


__all__ = [
    "BEWEISZIEL",
    "NetzGesperrt",
    "beweis",
    "entsperren",
    "ist_aktiv",
    "namensbeweis",
    "sperren",
]
