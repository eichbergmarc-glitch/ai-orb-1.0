"""Tests der vier Verbesserungen, die der Benutzer ausgewaehlt hat.

Anlass war die Frage, was sich noch verbessern laesst. Die Antwort kam
nicht aus einer Wunschliste, sondern aus seinem Protokoll:

  - Von vierzehn erkannten Aeusserungen lagen ACHT unter 0.90 Sicherheit,
    mehrere waren Kauderwelsch. Der Orb antwortete darauf.
  - Zweimal suchte er, dreimal nicht - dieselbe Sitzung, dieselbe Frage.
  - Beim Start scheiterte das Schreiben von 'data\\bugs.json' mit
    PermissionError, weil OneDrive die Datei festhielt.
  - Das Werkzeugverzeichnis mass 14 500 Zeichen bei JEDER Anfrage.
"""

from __future__ import annotations

import os
import threading

from backend.orchestrator.orchestrator import braucht_aktuelles
from backend.voice.voice_pipeline import _ist_geplapper


# --- 1. Wann gesucht werden MUSS -------------------------------------------------


def test_fragen_nach_dem_jetzt_werden_erkannt():
    for frage in (
        "Gib mir die aktuellen Entwicklungen im Iran-Krieg",
        "Gib mir die News aus dem Iran Krieg, bitte",
        "Was ist heute passiert?",
        "Wie steht es um die Verhandlungen?",
        "Was gibt es Neues aus Bern?",
    ):
        assert braucht_aktuelles(frage), frage


def test_ein_ausdruecklicher_suchauftrag_zaehlt_immer():
    """'Such mal' ist eine Anweisung und keine Gespraechsfloskel."""

    for frage in (
        "Suche nach aktuellen Informationen ueber den Iran-Krieg",
        "Schau nach, was der Bitcoin kostet",
        "Recherchier das bitte im Internet",
    ):
        assert braucht_aktuelles(frage), frage


def test_geschichtsfragen_loesen_keine_suche_aus():
    """Sonst suchte der Orb bei einem Geschichtsprofessor dauernd.

    Ausdruecklich NICHT dabei ist die blosse Jahreszahl: "Was geschah
    1789?" braucht keine Suche, und eine Regel, die auf Jahreszahlen
    anspringt, feuerte bei jeder zweiten Frage.
    """

    for frage in (
        "Was geschah 1789 in Frankreich?",
        "Erklaer mir den Investiturstreit",
        "Welche Ursachen hatte der Erste Weltkrieg?",
        "Oeffne den Browser",
    ):
        assert not braucht_aktuelles(frage), frage


def test_persoenliche_gegenwartsfragen_suchen_nicht_im_internet():
    for frage in (
        "Wie geht es dir heute?",
        "Was machst du gerade?",
        "Woran arbeitest du momentan?",
    ):
        assert not braucht_aktuelles(frage), frage


def test_die_vorabsuche_haengt_am_werkzeug_und_nicht_am_zureden():
    """Was festverdrahtet werden kann, soll nicht ueberredet werden."""

    import inspect
    from backend.orchestrator.orchestrator import Orchestrator

    quelle = inspect.getsource(Orchestrator._vorab_suchen)
    assert "internet_suchen" in quelle
    assert "direkt_ausfuehren" in quelle


def test_eine_gescheiterte_vorabsuche_wird_dem_modell_gesagt():
    """Sonst erfindet es an ihrer Stelle etwas Plausibles."""

    import inspect
    from backend.orchestrator.orchestrator import Orchestrator

    quelle = inspect.getsource(Orchestrator._vorab_suchen)
    assert "nicht geklappt" in quelle or "nicht geht" in quelle


# --- 2. Kauderwelsch ---------------------------------------------------------------


def test_wortwiederholungen_werden_verworfen():
    """Woertlich aus dem Protokoll des Benutzers."""

    assert _ist_geplapper(
        "Ja ruhig ruhig ruhig ruhig ruhig ruhig ruhig Genau voila"
    )


def test_ein_gewoehnlicher_satz_bleibt_stehen():
    for satz in (
        "Gib mir bitte die aktuellen Nachrichten aus dem Iran",
        "Was sagt der Iran dazu?",
        "Ja ja, das stimmt schon",
    ):
        assert not _ist_geplapper(satz), satz


def test_bei_unsicherer_erkennung_wird_nachgefragt():
    """Ein Mensch fragt nach, statt auf etwas zu antworten, das nie fiel."""

    from backend.utils.paths import get_project_root

    quelle = (
        get_project_root() / "backend" / "voice" / "voice_pipeline.py"
    ).read_text(encoding="utf-8")
    assert "_rueckfrage_unter" in quelle
    assert "es wird nachgefragt statt geantwortet" in quelle


# --- 3. Die Ablage, die OneDrive festhaelt ------------------------------------------


def test_ein_gesperrtes_ziel_wird_nicht_gleich_aufgegeben(tmp_path, monkeypatch):
    """Der Fall aus dem Startprotokoll: WinError 5 auf data\\bugs.json."""

    from backend.utils import store as store_modul

    ablage = store_modul.JsonStore(tmp_path / "sachen.json")

    versuche = {"n": 0}
    echt = os.replace

    def _zickig(quelle, ziel):
        versuche["n"] += 1
        if versuche["n"] < 3:
            raise PermissionError(5, "Zugriff verweigert")
        return echt(quelle, ziel)

    monkeypatch.setattr(store_modul.os, "replace", _zickig)
    ablage.set("wert", 42)

    assert versuche["n"] == 3, "Es wurde nicht wiederholt."
    assert store_modul.JsonStore(tmp_path / "sachen.json").get("wert") == 42


def test_dauerhaft_gesperrt_wird_gemeldet_und_nicht_verschwiegen(tmp_path, monkeypatch):
    """Stilles Verlieren von Daten waere schlimmer als ein Fehler."""

    from backend.utils import store as store_modul

    ablage = store_modul.JsonStore(tmp_path / "sachen.json")
    monkeypatch.setattr(
        store_modul.os,
        "replace",
        lambda *_: (_ for _ in ()).throw(PermissionError(5, "Zugriff verweigert")),
    )
    try:
        ablage.set("wert", 1)
    except PermissionError:
        pass
    else:
        raise AssertionError("Der Fehler wurde verschluckt.")


def test_keine_zeitdatei_bleibt_liegen(tmp_path, monkeypatch):
    """Sonst fuellt sich der Datenordner mit tmp-Resten."""

    from backend.utils import store as store_modul

    ablage = store_modul.JsonStore(tmp_path / "sachen.json")
    monkeypatch.setattr(
        store_modul.os,
        "replace",
        lambda *_: (_ for _ in ()).throw(PermissionError(5, "gesperrt")),
    )
    try:
        ablage.set("wert", 1)
    except PermissionError:
        pass
    reste = [p for p in tmp_path.iterdir() if p.name.startswith("tmp")]
    assert not reste, f"Zeitdateien liegen geblieben: {reste}"


# --- 4. Die Groesse des Werkzeugverzeichnisses --------------------------------------


def test_das_verzeichnis_bleibt_knapp():
    """3 600 Token Verzeichnis bei jeder Anfrage waren zu viel.

    Zum Vergleich: Fuer den gesamten Gespraechsverlauf standen 3 000 zur
    Verfuegung. Das Verzeichnis war also groesser als das Gedaechtnis.
    """

    from backend.events.event_bus import EventBus
    from backend.memory.memory_engine import MemoryEngine
    from backend.security.security_engine import SecurityEngine
    from backend.tools.registry import ToolRegistry
    from backend.tools.standard_tools import build_standard_tools

    registry = ToolRegistry()
    registry.register_many(
        build_standard_tools(
            security=SecurityEngine(event_bus=EventBus()),
            memory=MemoryEngine(),
            desktop=None,
        )
    )
    je_werkzeug = len(registry.describe_for_model()) / max(1, len(registry.all()))
    assert je_werkzeug < 260, (
        f"{je_werkzeug:.0f} Zeichen je Werkzeug - bei vierzig Werkzeugen sind "
        "das wieder ueber zehntausend Zeichen in jeder einzelnen Anfrage."
    )


def test_pflichtangaben_stehen_weiterhin_da():
    """Kuerzen darf nicht heissen, dass ein Aufruf nicht mehr moeglich ist."""

    from backend.tools.web_tools import WebSearchTool

    text = WebSearchTool().describe_for_model()
    assert "internet_suchen" in text
    assert "suchbegriff" in text and "Pflicht" in text


def test_aufzaehlbare_werte_bleiben_vollstaendig():
    """Sie sind keine Erlaeuterung, sondern Teil der Schnittstelle."""

    from backend.tools.base_tool import Tool, ToolParameter, ToolResult

    class _Probe(Tool):
        name = "probe"
        description = (
            "Legt eine Sache an und meldet zurueck, ob es geklappt hat, damit "
            "man es nicht selbst nachsehen muss. "
            "Diese zweite Erlaeuterung darf wegfallen, sie wiederholt nur."
        )
        permission = "compute"
        parameters = (
            ToolParameter("art", "string", "Welche Art.", choices=("a", "b")),
        )

        async def execute(self, arguments):  # noqa: D102
            return ToolResult.success("")

    text = _Probe().describe_for_model()
    assert "a|b" in text, "Die erlaubten Werte fehlen - dann ruft das Modell falsch auf."
    assert "wiederholt nur" not in text, "Die Beschreibung wurde nicht gekuerzt."


def test_eine_sehr_kurze_beschreibung_wird_nicht_noch_kuerzer():
    """Kuerzen ist kein Selbstzweck.

    Manche Beschreibungen beginnen mit einem Dreiwortsatz. Von dem allein
    bleibt zu wenig uebrig, als dass ein Modell das Werkzeug noch waehlen
    koennte - dort kommt der naechste Satz dazu.
    """

    from backend.tools.base_tool import Tool, ToolParameter, ToolResult

    class _Knapp(Tool):
        name = "knapp"
        description = "Sucht etwas. Und zwar in der Ablage des Benutzers."
        permission = "compute"
        parameters = ()

        async def execute(self, arguments):  # noqa: D102
            return ToolResult.success("")

    assert "Ablage" in _Knapp().describe_for_model()
