"""Eine Seite, die nicht antwortet, darf den Dialogzug nicht aufhalten.

Aus der Auswertung der Anfrage vom 06.09.2026, 15:53:21 - "Haben wir alle
eine Plattform gefunden, auf der ich gratis Filme streamen kann?". Bis zum
ersten hoerbaren Wort vergingen 38,2 Sekunden. Davon:

    Werkzeug 'webseite_lesen' fehlgeschlagen (12.1 s):
    Die Seite meldete 403 fuer https://www.comparis.ch/telecom/

Zwoelf Sekunden fuer eine Absage - ein Drittel der Wartezeit. Die 12,1 s
sind exakt das Zeitlimit in ``_fetch``, und das gilt je Leseoperation, nicht
fuer den ganzen Vorgang. Eine Gesamtfrist gab es nicht.
"""

from __future__ import annotations

import time
import urllib.error

import backend.tools.web_tools as web_tools
from backend.tools.web_tools import ReadWebpageTool


class _Einstellungen:
    """Ein Konfigurations-Doppel mit knappen Fristen."""

    def __init__(self, verbindung: float, gesamt: float) -> None:
        self._werte = {
            "tools.webseite_lesen.verbindungsfrist_sekunden": verbindung,
            "tools.webseite_lesen.gesamtfrist_sekunden": gesamt,
        }

    def get(self, schluessel: str, vorgabe=None):
        return self._werte.get(schluessel, vorgabe)


def _knappe_fristen(monkeypatch, *, verbindung: float = 0.2, gesamt: float = 0.4) -> None:
    monkeypatch.setattr(
        web_tools, "get_config", lambda: _Einstellungen(verbindung, gesamt)
    )


async def test_eine_schweigende_seite_wird_aufgegeben(monkeypatch):
    _knappe_fristen(monkeypatch)

    def _haengt(url, *, data=None, timeout=12.0):
        time.sleep(5.0)
        return b"<html><main>zu spaet</main></html>"

    monkeypatch.setattr(web_tools, "_fetch", _haengt)

    begonnen = time.monotonic()
    ergebnis = await ReadWebpageTool().execute({"url": "https://beispiel.test/"})
    gedauert = time.monotonic() - begonnen

    assert not ergebnis.ok
    assert "nicht geantwortet" in ergebnis.error
    assert gedauert < 2.0, (
        f"es hat {gedauert:.1f} s gedauert - ohne Gesamtfrist wartet der "
        "Benutzer vor dem Lautsprecher"
    )


async def test_die_verbindungsfrist_wird_durchgereicht(monkeypatch):
    _knappe_fristen(monkeypatch, verbindung=3.0, gesamt=9.0)
    gesehen: dict[str, float] = {}

    def _merken(url, *, data=None, timeout=12.0):
        gesehen["timeout"] = timeout
        return b"<html><main>Text der Seite.</main></html>"

    monkeypatch.setattr(web_tools, "_fetch", _merken)

    ergebnis = await ReadWebpageTool().execute({"url": "https://beispiel.test/"})

    assert ergebnis.ok
    assert gesehen["timeout"] == 3.0, (
        "ohne eigene Verbindungsfrist gilt weiter die Vorgabe von 12 s je "
        "Leseoperation"
    )


async def test_eine_schnelle_seite_wird_normal_gelesen(monkeypatch):
    _knappe_fristen(monkeypatch)
    monkeypatch.setattr(
        web_tools,
        "_fetch",
        lambda url, *, data=None, timeout=12.0: (
            b"<html><main><p>Der eigentliche Inhalt.</p></main></html>"
        ),
    )

    ergebnis = await ReadWebpageTool().execute({"url": "https://beispiel.test/"})

    assert ergebnis.ok
    assert "Der eigentliche Inhalt." in ergebnis.output


async def test_ein_403_bleibt_ein_403(monkeypatch):
    """Die Frist ersetzt die vorhandenen Fehlerwege nicht."""

    _knappe_fristen(monkeypatch)

    def _abgewiesen(url, *, data=None, timeout=12.0):
        raise urllib.error.HTTPError(url, 403, "Forbidden", {}, None)

    monkeypatch.setattr(web_tools, "_fetch", _abgewiesen)

    ergebnis = await ReadWebpageTool().execute({"url": "https://beispiel.test/"})

    assert not ergebnis.ok
    assert "403" in ergebnis.error


async def test_ohne_eigene_einstellung_gelten_die_vorgaben(monkeypatch):
    """Ein fehlender Abschnitt in der config.yaml darf nichts reissen."""

    class _Leer:
        def get(self, schluessel, vorgabe=None):
            return vorgabe

    monkeypatch.setattr(web_tools, "get_config", lambda: _Leer())
    gesehen: dict[str, float] = {}

    def _merken(url, *, data=None, timeout=12.0):
        gesehen["timeout"] = timeout
        return b"<html><main>Da.</main></html>"

    monkeypatch.setattr(web_tools, "_fetch", _merken)

    ergebnis = await ReadWebpageTool().execute({"url": "https://beispiel.test/"})

    assert ergebnis.ok
    assert gesehen["timeout"] == 5.0
