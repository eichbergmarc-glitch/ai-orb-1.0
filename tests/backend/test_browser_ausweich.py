"""Browser-Befehle funktionieren auch OHNE eingerichtete Steuerung.

Der Befund aus dem Protokoll des Benutzers: 'browser_bedienen' scheiterte
seit Tagen mit "Die Browsersteuerung ist noch nicht eingerichtet", und
"öffne ein Browserfenster bei Google und führe eine Suche durch" löste
stattdessen acht leere Suchläufe mit dem wörtlichen Befehlssatz aus.

Diese Tests sichern die drei Reparaturen:

* "öffne ein Browserfenster (mit Google)" wird als Browser-Befehl erkannt -
  auch ohne Adresse mit Endung - und löst KEINE Vorabsuche aus.
* Ohne Playwright öffnet browser_bedienen den Standardbrowser (Ausweichweg)
  statt nur zu scheitern.
* "Wiederhole die Suche" wiederholt den letzten echten Suchbegriff, statt
  den Satz wörtlich zu suchen.
"""

from __future__ import annotations

import asyncio

from backend.orchestrator.orchestrator import (
    braucht_aktuelles,
    ist_browser_befehl,
    will_browser,
)


# --- Erkennung: Browserfenster ohne Adresse ---------------------------------


def test_browserfenster_mit_seitennamen_wird_erkannt():
    faelle = {
        "öffne ein browserfenster mit google": "https://www.google.de",
        "dann öffnet ein browserfenster bei google und führt eine suche durch":
            "https://www.google.de",
        "öffne den browser mit youtube": "https://www.youtube.com",
        "browser öffnen": "https://www.google.de",  # ohne Ziel: Startseite
    }
    for satz, erwartet in faelle.items():
        assert will_browser(satz) == erwartet, satz


def test_browserbefehl_loest_keine_vorabsuche_aus():
    satz = "dann öffnet ein browserfenster bei google und führt eine suche durch"
    # Das Suchwort im Satz würde die Vorabsuche zünden ...
    assert braucht_aktuelles(satz)
    # ... aber der Browser-Befehl hat Vorrang.
    assert ist_browser_befehl(satz)


def test_normale_suchfrage_bleibt_suchfrage():
    satz = "such mir die aktuellen Nachrichten aus der Schweiz"
    assert braucht_aktuelles(satz)
    assert not ist_browser_befehl(satz)


# --- Ausweichweg: Standardbrowser statt Fehlschlag --------------------------


class _KaputteSteuerung:
    """Steuerung, deren Start scheitert - wie ohne Playwright."""

    def __getattr__(self, name):
        async def _fehlt(*args, **kwargs):
            from backend.browser.steuerung import BrowserNichtBereit
            raise BrowserNichtBereit(
                "Die Browsersteuerung ist noch nicht eingerichtet. Fuehre "
                "einmal 'BROWSER-EINRICHTEN.bat' aus."
            )
        return _fehlt


def test_oeffnen_faellt_auf_standardbrowser_zurueck(monkeypatch):
    import webbrowser

    geoeffnet: list[str] = []
    monkeypatch.setattr(webbrowser, "open", lambda url: geoeffnet.append(url) or True)

    from backend.tools.browser_tools import BrowserBedienenTool

    tool = BrowserBedienenTool(_KaputteSteuerung())
    ergebnis = asyncio.run(tool.execute({"aktion": "oeffnen", "ziel": "www.google.de"}))

    assert ergebnis.ok, ergebnis.error
    assert geoeffnet == ["https://www.google.de"]
    assert "BROWSER-EINRICHTEN" in ergebnis.output  # sagt, was noch fehlt
    assert ergebnis.context.get("steuerung") is False


def test_klicken_ohne_steuerung_scheitert_ehrlich(monkeypatch):
    # Nur das Öffnen hat einen Ausweichweg - Klicken kann der
    # Standardbrowser nicht, und das muss als Fehler kommen.
    from backend.tools.browser_tools import BrowserBedienenTool

    tool = BrowserBedienenTool(_KaputteSteuerung())
    ergebnis = asyncio.run(tool.execute({"aktion": "klicken", "ziel": "3"}))
    assert not ergebnis.ok
    assert "BROWSER-EINRICHTEN" in ergebnis.error


# --- "Wiederhole die Suche" -------------------------------------------------


class _FakeResult:
    def __init__(self, ok=True, output="Treffer A", error=""):
        self.ok = ok
        self.output = output
        self.error = error


class _FakeRun:
    def __init__(self):
        self.result = _FakeResult()
        self.seconds = 0.1


class _SuchEngine:
    enabled = True

    def __init__(self):
        self.anfragen: list[str] = []

    async def direkt_ausfuehren(self, name, arguments, *, actor="vorab"):
        self.anfragen.append(str(arguments.get("suchbegriff", "")))
        return _FakeRun()


def _orchestrator_mit(engine):
    from backend.orchestrator.orchestrator import Orchestrator

    orch = Orchestrator.__new__(Orchestrator)
    orch._tool_engine = engine
    orch._letzter_suchbegriff = ""

    class _Cfg:
        def get(self, key, default=None):
            # Mehrquellen aus, damit der einfache Weg getestet wird.
            if key == "recherche.mehrquellen":
                return False
            return default

    orch._config = _Cfg()
    return orch


def test_wiederholung_nutzt_letzten_begriff():
    engine = _SuchEngine()
    orch = _orchestrator_mit(engine)

    asyncio.run(orch._vorab_suchen("such die neuesten Nachrichten zu Meta"))
    erste = engine.anfragen[-1]
    assert "meta" in erste.lower() or "nachrichten" in erste.lower()

    asyncio.run(orch._vorab_suchen("Wiederhole die Suche, sie muss funktionieren."))
    zweite = engine.anfragen[-1]

    # Nicht der Wiederhol-Satz, sondern der alte Begriff.
    assert "wiederhole" not in zweite.lower()
    assert zweite == erste


def test_ohne_vorherige_suche_bleibt_der_satz():
    engine = _SuchEngine()
    orch = _orchestrator_mit(engine)
    asyncio.run(orch._vorab_suchen("Wiederhole die Suche bitte"))
    # Kein letzter Begriff da - dann wird eben der bereinigte Satz gesucht;
    # Hauptsache, es stürzt nicht und es WIRD gesucht.
    assert engine.anfragen
