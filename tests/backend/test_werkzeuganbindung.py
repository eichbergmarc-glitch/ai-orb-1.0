"""Prueft, ob die Werkzeuge wirklich angeschlossen sind.

Der Benutzer bat darum, alle Werkzeuganbindungen zu ueberpruefen. Der
Anlass war die Internetsuche, aber die Frage dahinter ist allgemeiner:
Welche Werkzeuge gibt es, und funktionieren sie auch?

Dass ein Werkzeug im Quelltext steht, heisst wenig. Es kann eine Klasse
haben, einen Namen tragen, eine schoene Beschreibung mitbringen - und
trotzdem nirgends angemeldet sein, nicht im Systemprompt stehen, oder beim
ersten Aufruf in eine Methode greifen, die es gar nicht gibt.

Genau der letzte Fall lag vor. ``gedaechtnis_durchsuchen`` rief
``MemoryEngine.search(...)`` auf - eine Methode, die diese Klasse nie
hatte. Das Werkzeug war von Anfang an tot. Aufgefallen ist es niemandem,
und der Grund dafuer ist das Lehrreiche daran: Der Fehler wurde
abgefangen und zu "Die Suche im Gedaechtnis ging schief" gemacht. Von
aussen sah das aus wie ein leeres Gedaechtnis.

Diese Tests fuehren die harmlosen Werkzeuge deshalb WIRKLICH AUS, statt
ihren Quelltext zu lesen.
"""

from __future__ import annotations

import asyncio
import inspect
import re

from backend.events.event_bus import EventBus
from backend.memory.memory_engine import MemoryEngine
from backend.security.security_engine import SecurityEngine
from backend.tools.registry import ToolRegistry
from backend.tools.standard_tools import MemorySearchTool, build_standard_tools


#: Rechte, unter denen ein Werkzeug nur liest oder rechnet. Nur diese
#: werden ausgefuehrt - ein Test, der `programm_starten` probiert, oeffnet
#: Fenster, und einer, der `neu_starten` probiert, beendet sich selbst.
LESENDE_RECHTE = frozenset({
    "read_time", "compute", "read_memory", "read_files",
    "list_directory", "search_files", "read_bookmarks",
})

#: Woran ein INNERER Defekt zu erkennen ist - im Unterschied zu einer
#: sauberen Absage wie "Es fehlt der Suchbegriff".
_DEFEKT = re.compile(
    r"AttributeError|TypeError|KeyError|IndexError|NameError|"
    r"has no attribute|not callable|object is not|coroutine",
    re.I,
)


def _platzhalter(parameter) -> object:
    """Ein harmloser Wert, der zum angegebenen Typ passt."""

    if parameter.type == "integer":
        return 1
    if parameter.type == "number":
        return 1.0
    if parameter.type == "boolean":
        return False
    if parameter.type == "array":
        return []
    if parameter.type == "object":
        return {}
    # Etwas, das als Suchbegriff, Pfad und Ausdruck gleichermassen
    # ungefaehrlich ist.
    return "1"


def _lesende_werkzeuge():
    registry = ToolRegistry()
    registry.register_many(
        build_standard_tools(
            security=SecurityEngine(event_bus=EventBus()),
            memory=MemoryEngine(),
            desktop=None,
        )
    )
    return [t for t in registry.all() if t.permission in LESENDE_RECHTE]


def test_es_gibt_ueberhaupt_lesende_werkzeuge():
    assert _lesende_werkzeuge(), "Die Werkzeugliste ist leer - dann prueft dieser Test nichts."


def test_kein_werkzeug_antwortet_mit_einem_inneren_fehler():
    """Der Test, der den toten Gedaechtnis-Zugriff gefunden haette.

    Ein Werkzeug darf absagen - "Es fehlt der Suchbegriff", "Kein Ordner
    freigegeben", "Gmail ist nicht eingerichtet" sind saubere Antworten.
    Was es nicht darf, ist einen Programmierfehler als Absage ausgeben:
    Das sieht fuer den Benutzer aus wie ein leeres Ergebnis, und niemand
    kommt darauf, dass etwas kaputt ist.
    """

    schlecht: list[str] = []
    for werkzeug in _lesende_werkzeuge():
        args = {p.name: _platzhalter(p) for p in werkzeug.parameters if p.required}
        try:
            ergebnis = asyncio.run(asyncio.wait_for(werkzeug.execute(args), timeout=30))
        except Exception as fehler:  # noqa: BLE001
            schlecht.append(f"{werkzeug.name}: abgestuerzt ({type(fehler).__name__}: {fehler})")
            continue
        if not ergebnis.ok and _DEFEKT.search(ergebnis.error or ""):
            schlecht.append(f"{werkzeug.name}: innerer Fehler als Absage ({ergebnis.error[:90]})")
    assert not schlecht, "\n".join(schlecht)


def test_jedes_werkzeug_ist_vollstaendig_beschrieben():
    """Was das Modell nicht versteht, ruft es nicht auf."""

    maengel: list[str] = []
    for werkzeug in _lesende_werkzeuge():
        if not (werkzeug.description or "").strip():
            maengel.append(f"{werkzeug.name}: keine Beschreibung")
        if not inspect.iscoroutinefunction(werkzeug.execute):
            maengel.append(f"{werkzeug.name}: execute ist nicht async")
        for p in werkzeug.parameters:
            if p.type not in ("string", "integer", "number", "boolean", "array", "object"):
                maengel.append(f"{werkzeug.name}: Parameter '{p.name}' hat Typ '{p.type}'")
    assert not maengel, "\n".join(maengel)


def test_die_angebotenen_parameter_werden_auch_gelesen():
    """Die zweite stille Bruchstelle.

    Das Modell ruft mit den Namen auf, die in der Beschreibung stehen.
    Sieht ``execute`` unter anderen Namen nach, kommt kein Fehler, sondern
    ein leeres Feld - und das Werkzeug meldet hoeflich, es fehle die
    Angabe. Ein Fehler, der wie eine Benutzereingabe aussieht.
    """

    gelesen_muster = re.compile(
        r"""arguments(?:\.get\(|\[)\s*["']([A-Za-z_][A-Za-z0-9_]*)["']"""
    )
    maengel: list[str] = []
    for werkzeug in _lesende_werkzeuge():
        pflicht = {p.name for p in werkzeug.parameters if p.required}
        if not pflicht:
            continue
        try:
            quelle = inspect.getsource(type(werkzeug).execute)
        except (OSError, TypeError):
            continue
        gelesen = set(gelesen_muster.findall(quelle))
        fehlend = pflicht - gelesen
        if fehlend:
            maengel.append(f"{werkzeug.name}: {sorted(fehlend)} wird angeboten, aber nie gelesen")
    assert not maengel, "\n".join(maengel)


# --- Der konkrete Fall ----------------------------------------------------------------


def test_die_gedaechtnissuche_findet_wirklich_etwas():
    """Sie rief eine Methode auf, die es nicht gibt - ein Jahr lang unbemerkt."""

    gedaechtnis = MemoryEngine()
    gedaechtnis.remember(
        "Marc arbeitet an einem Desktop-Assistenten namens AI-Orb.", kind="fakt"
    )
    ergebnis = asyncio.run(MemorySearchTool(gedaechtnis).execute({"suchbegriff": "AI-Orb"}))
    assert ergebnis.ok, ergebnis.error
    assert "AI-Orb" in ergebnis.output, (
        "Die Gedaechtnissuche liefert nichts, obwohl etwas gespeichert ist."
    )


def test_die_gedaechtnissuche_benutzt_die_methode_die_es_gibt():
    """Damit der alte Aufruf nicht zurueckkommt."""

    # Ohne die Kommentarzeilen: An der Stelle, wo der alte Aufruf stand,
    # steht jetzt die Erklaerung, warum er dort NICHT mehr steht. Ein Test,
    # der Kommentare mitzaehlt, schluege also genau wegen der Behebung fehl.
    quelle = "\n".join(
        z for z in inspect.getsource(MemorySearchTool.execute).splitlines()
        if not z.lstrip().startswith("#")
    )
    assert "recall" in quelle
    assert "_memory.search(" not in quelle, (
        "MemoryEngine hat keine Methode 'search' - das Werkzeug waere wieder tot."
    )


def test_eine_leere_anfrage_wird_sauber_abgelehnt():
    ergebnis = asyncio.run(MemorySearchTool(MemoryEngine()).execute({}))
    assert not ergebnis.ok
    assert "Suchbegriff" in ergebnis.error
