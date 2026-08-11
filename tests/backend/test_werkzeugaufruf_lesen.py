"""Tests des Lesers fuer Werkzeugaufrufe.

Der Benutzer meldete: "orb kann nicht auf das suchwerkzeug zugreifen."

Im Protokoll war zu sehen, dass das Werkzeug angemeldet ist, im
Systemprompt steht und die Werkzeugschleife laeuft - und dass trotzdem nie
eines aufgerufen wurde. Das legt den Verdacht auf die Stelle, an der die
Antwort des Modells GELESEN wird.

Dort stand:

    r"```(?:werkzeug|tool)\\s*\\n(.*?)\\n```"

Diese Zeile verlangt dreierlei zugleich: Die Zaeunung muss genau
``werkzeug`` oder ``tool`` heissen, danach muss ein Zeilenumbruch stehen,
und vor der schliessenden Zaeunung ebenfalls. Fehlt eines davon, findet
das Muster nichts. Der Aufruf wird verworfen - ohne Meldung, ohne
Fehlerbild. Von aussen sieht das aus, als benutze der Orb seine Werkzeuge
nicht.

Alle drei Abweichungen sind alltaeglich. Genau sie werden hier geprueft.
"""

from __future__ import annotations

from backend.tools.tool_engine import parse_tool_calls, strip_tool_calls


_AUFRUF = '{"werkzeug": "internet_suchen", "argumente": {"suchbegriff": "Iran"}}'


def _erster(text: str):
    aufrufe = parse_tool_calls(text)
    assert aufrufe, "Kein Aufruf erkannt."
    return aufrufe[0]


# --- Die Formen, die frueher verworfen wurden ---------------------------------------


def test_der_erwartete_fall_geht_weiterhin():
    aufruf = _erster("Ich sehe nach.\n\n```werkzeug\n" + _AUFRUF + "\n```")
    assert aufruf.tool == "internet_suchen"
    assert aufruf.arguments["suchbegriff"] == "Iran"


def test_json_als_beschriftung():
    """Die haeufigste Abweichung ueberhaupt."""

    assert _erster("```json\n" + _AUFRUF + "\n```").tool == "internet_suchen"


def test_ohne_beschriftung():
    assert _erster("```\n" + _AUFRUF + "\n```").tool == "internet_suchen"


def test_ohne_umbruch_vor_der_schliessenden_zaeunung():
    """Ein einziges fehlendes Zeilenende kostete den ganzen Aufruf."""

    assert _erster("```werkzeug\n" + _AUFRUF + "```").tool == "internet_suchen"


def test_ganz_ohne_zaeunung():
    assert _erster("Ich schaue kurz nach. " + _AUFRUF).tool == "internet_suchen"


def test_mit_vorangestelltem_wort():
    assert _erster("WERKZEUG: " + _AUFRUF).tool == "internet_suchen"


def test_verschachtelte_argumente_bleiben_heil():
    """Ein Klammernzaehler statt eines regulaeren Ausdrucks."""

    text = ('{"werkzeug": "wissen_uebernehmen", "argumente": '
            '{"thema": "Iran", "aussage": {"text": "a", "quelle": "b"}}}')
    aufruf = _erster(text)
    assert aufruf.tool == "wissen_uebernehmen"
    assert aufruf.arguments["aussage"]["quelle"] == "b"


def test_mehrere_aufrufe_in_einer_antwort():
    text = ("```werkzeug\n" + _AUFRUF + "\n```\n\n```json\n"
            '{"werkzeug": "aktuelle_zeit", "argumente": {}}\n```')
    namen = [a.tool for a in parse_tool_calls(text)]
    assert namen == ["internet_suchen", "aktuelle_zeit"]


def test_derselbe_aufruf_zaehlt_nur_einmal():
    """Der ungezaeunte Weg liest ueber den ganzen Text, also auch ueber
    das, was der gezaeunte schon gefunden hat."""

    text = "```werkzeug\n" + _AUFRUF + "\n```"
    assert len(parse_tool_calls(text)) == 1


# --- Und was KEIN Aufruf ist ---------------------------------------------------------


def test_ein_beispiel_json_startet_kein_werkzeug():
    """Die Beschriftung darf jetzt beliebig sein - der Inhalt nicht."""

    assert not parse_tool_calls('```json\n{"name": "Marc", "alter": 40}\n```')
    assert not parse_tool_calls('Die Antwort ist {"ergebnis": 42}.')


def test_ein_satz_ueber_werkzeuge_ist_kein_aufruf():
    assert not parse_tool_calls("Ich koennte dafuer ein Werkzeug benutzen.")


# --- Was der Benutzer zu sehen bekommt ------------------------------------------------


def test_der_aufruf_verschwindet_aus_der_antwort():
    text = "Einen Moment.\n\n```werkzeug\n" + _AUFRUF + "\n```"
    assert "werkzeug" not in strip_tool_calls(text).lower()
    assert strip_tool_calls(text).startswith("Einen Moment")


def test_ein_ungezaeunter_aufruf_verschwindet_ebenfalls():
    """Sonst laese die Sprachausgabe geschweifte Klammern vor."""

    assert "{" not in strip_tool_calls("Ich sehe nach. " + _AUFRUF)


def test_ein_codeblock_bleibt_stehen():
    """Die Gegenprobe - und der Fehler, den die Erweiterung leicht macht.

    Seit die Beschriftung beliebig sein darf, wuerde ein pauschales
    Loeschen aller eingezaeunten Bloecke auch das Stueck Python
    wegwerfen, um das der Benutzer gerade gebeten hat.
    """

    text = "So geht das:\n\n```python\nprint('hallo')\n```"
    assert "print('hallo')" in strip_tool_calls(text)


def test_ein_beispiel_json_bleibt_stehen():
    text = 'Die Datei sieht so aus:\n\n```json\n{"name": "Marc"}\n```'
    assert '"name": "Marc"' in strip_tool_calls(text)


# --- Die Sprachausgabe ----------------------------------------------------------------


def test_ein_ungezaeunter_aufruf_wird_nicht_vorgelesen():
    from backend.orchestrator.speech_stream import SpeechStream

    strom = SpeechStream()
    gesprochen: list[str] = []
    gesprochen += strom.feed("Ich sehe kurz nach. ")
    gesprochen += strom.feed(_AUFRUF)
    gesprochen += strom.finish()

    zusammen = " ".join(gesprochen)
    assert "Ich sehe kurz nach" in zusammen
    assert "werkzeug" not in zusammen.lower(), (
        "Der Werkzeugaufruf wird vorgelesen - der Benutzer hoert geschweifte "
        "Klammern."
    )


# --- Wo die Anweisung steht ------------------------------------------------------------
#
# Der Benutzer meldete zweimal, der Orb komme nicht an seine Werkzeuge. Beim
# zweiten Mal zeigte das Protokoll, dass er es sehr wohl tat - aber nicht
# immer: Auf "Suche ueberall nach aktuellen Informationen und fasse mir die
# News zusammen" kamen 544 Zeichen aus dem Gedaechtnis und kein einziger
# Aufruf.
#
# Die Anweisung "benutze Werkzeuge" stand ganz oben, danach folgten
# vierzehntausend Zeichen alphabetisches Verzeichnis. Das Letzte, was das
# Modell vor der Frage las, war die Parameterbeschreibung des letzten
# Werkzeugs.


def _anweisung() -> str:
    from backend.events.event_bus import EventBus
    from backend.memory.memory_engine import MemoryEngine
    from backend.security.security_engine import SecurityEngine
    from backend.tools.registry import ToolRegistry
    from backend.tools.standard_tools import build_standard_tools
    from backend.tools.tool_engine import ToolEngine

    registry = ToolRegistry()
    registry.register_many(
        build_standard_tools(
            security=SecurityEngine(event_bus=EventBus()),
            memory=MemoryEngine(),
            desktop=None,
        )
    )
    return ToolEngine(
        registry=registry,
        security=SecurityEngine(event_bus=EventBus()),
        provider_manager=None,
    ).system_instructions()


def test_die_regel_steht_hinter_dem_verzeichnis():
    """Das Letzte vor der Frage muss die Regel sein, nicht Werkzeug Nummer 39."""

    from backend.tools.tool_engine import ToolEngine

    text = _anweisung()
    ort_regel = text.index("SO ENTSCHEIDEST DU")
    ort_liste = text.index("Diese Werkzeuge gibt es")
    assert ort_regel > ort_liste, (
        "Die verbindliche Regel steht vor dem Verzeichnis - dann liest das "
        "Modell zuletzt eine Parameterbeschreibung."
    )
    assert text.rstrip().endswith(ToolEngine.VERBINDLICHE_REGEL.rstrip()[-60:])


def test_die_regel_benennt_den_stichtag_und_die_suche():
    text = _anweisung()
    for satzteil in ("Stichtag", "internet_suchen", "webseite_lesen"):
        assert satzteil in text, f"'{satzteil}' fehlt in der Regel."


def test_die_regel_verbietet_die_ausrede():
    """Der Satz, den der Benutzer woertlich gemeldet hat."""

    assert "koenntest nicht ins Internet" in _anweisung()


def test_die_kuerze_gilt_nicht_fuer_den_werkzeugaufruf():
    """Der Widerspruch, der gesprochene Antworten von Werkzeugen abhielt.

    Gesprochenen Antworten wird vorgegeben, sich auf zwei bis vier Saetze
    zu beschraenken. Ein Werkzeugaufruf sieht wie ein Verstoss dagegen aus -
    bis jemand dazusagt, dass er keine Antwort ist, sondern der Weg zu einer.
    """

    text = _anweisung()
    assert "keine Antwort" in text and "Zwischenschritt" in text
