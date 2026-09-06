"""Integrationstests der Anfrageverarbeitung - die Tore 4, 5 und 6.

Warum es diese Datei gibt: Am 31.08.2026 waren 1826 Tests grün, und der Orb
hatte trotzdem keine Websuche, keinen Browser und keine Karteikarten. Alle
drei Löcher lagen zwischen den Bausteinen, nicht in ihnen - und jeder
einzelne Baustein war getestet. Die Tests hier prüfen deshalb den
ZUSAMMENBAU: den echten Werkzeugaufbau, die echten Entscheidungen an den
Toren, den echten Zug durch den Orchestrator.

Die Tore, in der Reihenfolge, in der eine Anfrage sie passiert:

* Tor 4 - der Router: Beendet eine lokale Zuordnung den Zug?
* Tor 5 - der Professor: Übernimmt der Fachmodus?
* Tor 6 - der Orchestrator: Bekommt das Modell Werkzeuge?
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import pytest

from backend.orchestrator.faehigkeiten import entscheiden
from backend.orchestrator.intent_classifier import IntentResult
from backend.orchestrator.task_router import (
    STATUS_LOKAL,
    STATUS_UNSICHER,
    RouteResult,
    TaskRouter,
)


def _intent(name: str = "aufgabe", score: float = 0.8) -> IntentResult:
    return IntentResult(
        intent=name, confidence="hoch", score=score, requires_llm=False
    )


# --- Der echte Zusammenbau -------------------------------------------------


def test_der_echte_runtime_meldet_alle_werkzeuge_an() -> None:
    """Kein Testdoppel: der wirkliche Aufbau, wie ihn der Orb startet.

    Genau hier fehlte der Nachweis. ``build_standard_tools`` lieferte
    'internet_suchen' brav aus, das Register wies es wegen der unbekannten
    Berechtigung 'internet' ab, und kein Test sah hin - die Prüfung schaute
    auf die gebaute Liste, nicht auf das Register.
    """

    from backend.runtime import Runtime

    orb = Runtime()

    assert orb.tools.abgewiesene() == [], (
        "Werkzeuge wurden beim Aufbau abgewiesen: "
        + str(orb.tools.abgewiesene())
    )
    assert "Werkzeuge" not in orb.startfehler
    for name in ("internet_suchen", "webseite_lesen", "webseite_erkunden"):
        assert name in orb.tools, f"'{name}' ist nicht angemeldet"
    assert len(orb.tools) > 30, "der Werkzeugkasten ist verdächtig leer"


def test_ein_falscher_berechtigungsname_laesst_die_startpruefung_scheitern(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Das Akzeptanzkriterium, wörtlich geprüft.

    Vorher war ein falscher Berechtigungsname eine Log-Warnung, und der
    Orb startete achtzehn Tage lang ohne Websuche weiter.
    """

    from backend.launcher import health_check as hc
    from backend.tools.base_tool import Tool, ToolResult

    class _Krummes(Tool):
        name = "krummes_werkzeug"
        description = "Ein Werkzeug mit einer Berechtigung, die es nicht gibt."
        permission = "internet"  # existiert nicht - richtig waere "network"

        async def execute(self, arguments: dict[str, Any]) -> ToolResult:
            return ToolResult.success("nie erreicht")

    from backend.tools import standard_tools

    # Das Original festhalten, BEVOR ersetzt wird - sonst ruft die
    # Ersatzfunktion sich selbst auf.
    echt = standard_tools.build_standard_tools

    def _mit_fehler(**kwargs: Any) -> list[Any]:
        return [*echt(**kwargs), _Krummes()]

    monkeypatch.setattr(standard_tools, "build_standard_tools", _mit_fehler)

    zustand, kurz, lang = hc.HealthCheck().check_werkzeuge()

    assert zustand is hc.CheckState.FAILED, (
        f"Ein falscher Berechtigungsname muss die Startpruefung rot machen, "
        f"war aber '{zustand}' ({kurz})"
    )
    assert "abgewiesen" in kurz
    assert "krummes_werkzeug" in lang
    assert "internet" in lang, "der falsche Berechtigungsname gehoert in den Bericht"


# --- Tor 4: der Router -----------------------------------------------------


def _router_mit(handler: Any, intent_name: str = "aufgabe") -> TaskRouter:
    router = TaskRouter()
    router.register(intent_name, handler)
    return router


def test_eine_unsichere_lokale_auskunft_beendet_den_zug_nicht() -> None:
    """Der Kern von P0: handled_locally ist eine Einschätzung, kein Urteil."""

    async def auskunft(text: str, intent: Any) -> RouteResult:
        return RouteResult(
            handled_locally=True,
            response="Aufgaben insgesamt: 0",
            module="tasks",
            konfidenz=0.15,
            rueckfall_erlaubt=True,
        )

    router = _router_mit(auskunft)
    ergebnis = asyncio.run(
        router.route(
            "Ich wiederhole die Aufgabe, suche nach einer Wohnung und zeige "
            "sie mir im Browser an.",
            _intent(),
        )
    )

    assert ergebnis.status == STATUS_UNSICHER
    assert ergebnis.ist_endgueltig is False
    assert ergebnis.requires_llm is True
    assert ergebnis.response == "", "die schwache Auskunft darf nicht die Antwort sein"
    assert ergebnis.data["verworfene_lokale_antwort"] == "Aufgaben insgesamt: 0"
    assert "Konfidenz" in ergebnis.begruendung


def test_eine_sichere_lokale_auskunft_bleibt_lokal() -> None:
    async def auskunft(text: str, intent: Any) -> RouteResult:
        return RouteResult(
            handled_locally=True,
            response="Aufgaben insgesamt: 3",
            module="tasks",
            konfidenz=0.95,
            rueckfall_erlaubt=True,
        )

    ergebnis = asyncio.run(
        _router_mit(auskunft).route("Welche Aufgaben sind offen?", _intent())
    )

    assert ergebnis.status == STATUS_LOKAL
    assert ergebnis.ist_endgueltig is True
    assert ergebnis.response == "Aufgaben insgesamt: 3"


def test_ein_handelndes_modul_faellt_nie_zurueck() -> None:
    """Ein gestartetes Programm startet man nicht ein zweites Mal."""

    async def handelnd(text: str, intent: Any) -> RouteResult:
        return RouteResult(
            handled_locally=True,
            response="Firefox wurde gestartet.",
            module="app_start",
            konfidenz=0.1,  # bewusst niedrig
        )

    ergebnis = asyncio.run(
        _router_mit(handelnd, "programm_starten").route(
            "starte firefox", _intent("programm_starten")
        )
    )

    assert ergebnis.ist_endgueltig is True
    assert ergebnis.response == "Firefox wurde gestartet."


def test_ohne_zustaendiges_modul_geht_es_ans_modell() -> None:
    ergebnis = asyncio.run(
        TaskRouter().route("Erzaehl mir etwas ueber Kant.", _intent("frage"))
    )

    assert ergebnis.handled_locally is False
    assert ergebnis.begruendung


# --- Tor 6: die Fähigkeitsentscheidung -------------------------------------


@pytest.mark.parametrize(
    "satz",
    [
        "Ich wiederhole die Aufgabe, suche nach einer Wohnung und zeige mir die "
        "Ergebnisse im Browser an.",
        "Kannst du mir einen Internet-Browser oeffnen und die News anzeigen?",
        "Lies mir bitte die Datei notizen.txt vor.",
    ],
)
def test_gesprochene_handlungsauftraege_bekommen_werkzeuge(satz: str) -> None:
    entscheidung = entscheiden(satz, gesprochen=True)

    assert entscheidung.werkzeuge is True
    assert entscheidung.handlungsauftrag is True
    assert entscheidung.konfidenz >= 0.45
    assert entscheidung.begruendung


def test_die_fortsetzung_eines_auftrags_verliert_die_werkzeuge_nicht() -> None:
    """Der Satz, an dem die Wohnungssuche zerbrach - ohne eigenes Verb."""

    entscheidung = entscheiden(
        "Gut, meine Vorlieben, es muss im ersten Stock sein oder im Parterre, "
        "sonst mit Lift, hoechstens 1100 Franken.",
        gesprochen=True,
    )

    assert entscheidung.werkzeuge is True
    assert "Zweifel" in entscheidung.begruendung


def test_eine_reine_wissensfrage_braucht_keine_werkzeuge() -> None:
    entscheidung = entscheiden("Was ist Existenz?", gesprochen=True)

    assert entscheidung.werkzeuge is False
    assert entscheidung.handlungsauftrag is False


def test_ein_vorlesungsabschnitt_behaelt_sein_verhalten() -> None:
    entscheidung = entscheiden(
        "Lies mir den naechsten Abschnitt vor.",
        gesprochen=True,
        vorlesungssegment=True,
    )

    assert entscheidung.werkzeuge is False
    assert "Vorlesungsabschnitt" in entscheidung.begruendung


def test_ohne_angemeldete_werkzeuge_gibt_es_keine() -> None:
    entscheidung = entscheiden(
        "Suche im Internet nach dem Wetter.",
        gesprochen=True,
        werkzeuge_vorhanden=False,
    )

    assert entscheidung.werkzeuge is False


def test_ein_geschriebener_zug_war_nie_eingeschraenkt() -> None:
    entscheidung = entscheiden("Was ist Existenz?", gesprochen=False)

    assert entscheidung.werkzeuge is True


# --- Tor 5: der Professor --------------------------------------------------


def _bruecke() -> Any:
    from backend.agents.history_agent.bridge import ProfessorSession

    return ProfessorSession()


def test_eine_fachliche_folgefrage_bleibt_beim_professor() -> None:
    bruecke = _bruecke()
    bruecke._fach = "geschichte"
    bruecke._mode = "quellenkritik"
    bruecke._letzte_fachaeusserung = time.time()

    assert bruecke.should_engage("Und wie steht es um die Quellenkritik dabei?")


def test_ein_fachfremder_handlungsauftrag_verlaesst_den_fachmodus() -> None:
    """Der Professor durchsuchte die Vatikanische Bibliothek nach Mietwohnungen."""

    bruecke = _bruecke()
    bruecke._fach = "geschichte"
    bruecke._mode = "quellenkritik"
    bruecke._letzte_fachaeusserung = time.time()

    assert bruecke.should_engage(
        "Suche mir bitte eine Wohnung in Solothurn und zeig sie im Browser."
    ) is False
    zustand = bruecke.zustand()
    assert zustand["aktiv"] is False
    assert zustand["zuletzt_verlassen_wegen"] == "fachfremder Handlungsauftrag"


def test_der_fachmodus_laeuft_ab() -> None:
    bruecke = _bruecke()
    bruecke._fach = "geschichte"
    bruecke._mode = "quellenkritik"
    bruecke._zeitablauf_sekunden = 60.0
    bruecke._letzte_fachaeusserung = time.time() - 3600.0

    assert bruecke.busy() is False
    assert bruecke.zustand()["zuletzt_verlassen_wegen"] == "Zeitablauf"


def test_ein_abgeschalteter_zeitablauf_laeuft_nicht_ab() -> None:
    bruecke = _bruecke()
    bruecke._fach = "geschichte"
    bruecke._mode = "quellenkritik"
    bruecke._zeitablauf_sekunden = 0.0
    bruecke._letzte_fachaeusserung = time.time() - 99999.0

    assert bruecke.busy() is True


# --- Werkzeugaufrufe: Schema und Fehlerpfad --------------------------------


@pytest.mark.parametrize(
    "roh",
    [
        '{"werkzeug": "internet_suchen", "argumente": "suchbegriff=Wetter"}',
        '{"werkzeug": "internet_suchen", "argumente": ["Wetter"]}',
        '{"werkzeug": "internet_suchen", "argumente": 5}',
    ],
)
def test_ein_ungueltiger_aufruf_wird_nicht_ausgefuehrt(roh: str) -> None:
    """Vorher wurde stillschweigend ein leeres Argumentobjekt eingesetzt."""

    from backend.tools.tool_engine import parse_tool_calls_mit_fehlern

    calls, fehler = parse_tool_calls_mit_fehlern(roh)

    assert calls == []
    assert len(fehler) == 1
    assert "argumente" in fehler[0].grund


def test_ein_gueltiger_aufruf_geht_durch() -> None:
    from backend.tools.tool_engine import parse_tool_calls_mit_fehlern

    calls, fehler = parse_tool_calls_mit_fehlern(
        '{"werkzeug": "internet_suchen", "argumente": {"suchbegriff": "Wetter"}}'
    )

    assert fehler == []
    assert calls[0].tool == "internet_suchen"
    assert calls[0].arguments == {"suchbegriff": "Wetter"}


def test_argumente_als_json_zeichenkette_werden_einmal_nachgelesen() -> None:
    """Ein haeufiger und harmloser Modellfehler - kein Grund abzubrechen."""

    from backend.tools.tool_engine import parse_tool_calls_mit_fehlern

    calls, fehler = parse_tool_calls_mit_fehlern(
        '{"werkzeug": "internet_suchen", "argumente": "{\\"suchbegriff\\": \\"Wetter\\"}"}'
    )

    assert fehler == []
    assert calls[0].arguments == {"suchbegriff": "Wetter"}


# --- Die Korrelations-Kennung ----------------------------------------------


def test_die_kennung_erscheint_an_den_toren(caplog: pytest.LogCaptureFixture) -> None:
    """Ein Zug muss sich im Protokoll von Anfang bis Ende verfolgen lassen."""

    from backend.system.performance_trace import reset_turn_trace, start_turn_trace

    spur, marke = start_turn_trace()
    try:
        with caplog.at_level(logging.INFO):
            async def auskunft(text: str, intent: Any) -> RouteResult:
                return RouteResult(
                    handled_locally=True,
                    response="x",
                    module="tasks",
                    konfidenz=0.9,
                    rueckfall_erlaubt=True,
                )

            asyncio.run(_router_mit(auskunft).route("Welche Aufgaben?", _intent()))

            bruecke = _bruecke()
            bruecke._fach = "geschichte"
            bruecke._mode = "quellenkritik"
            bruecke.should_engage("Oeffne bitte den Browser und suche eine Wohnung.")
    finally:
        reset_turn_trace(marke)

    zeilen = [satz.getMessage() for satz in caplog.records]
    mit_kennung = [zeile for zeile in zeilen if spur.turn_id in zeile]

    assert any("Tor 4" in zeile for zeile in mit_kennung), zeilen
    assert any("Tor 5" in zeile for zeile in mit_kennung), zeilen


# --- Werkzeugfehler und Anbieterausfall ------------------------------------


def test_ein_unbekanntes_werkzeug_meldet_einen_fehler() -> None:
    """Kein Absturz, keine erfundene Ausfuehrung - eine Fehlermeldung."""

    from backend.events.event_bus import EventBus
    from backend.security.security_engine import SecurityEngine
    from backend.tools.registry import ToolRegistry
    from backend.tools.tool_engine import ToolCall, ToolEngine

    engine = ToolEngine(
        registry=ToolRegistry(),
        security=SecurityEngine(EventBus()),
        provider_manager=None,
        event_bus=None,
    )

    lauf = asyncio.run(engine._execute(ToolCall(tool="gibtsnicht"), actor="test"))

    assert lauf.result.ok is False
    assert "gibtsnicht" in lauf.result.error


def test_bei_einem_anbieterausfall_uebernimmt_der_naechste() -> None:
    """Ein Wackler darf keine Antwort kosten."""

    from backend.orchestrator.provider_health import ProviderHealth
    from backend.orchestrator.provider_manager import ProviderManager
    from backend.orchestrator.providers.base_provider import (
        ChatMessage,
        ProviderError,
        ProviderResponse,
    )

    class _Anbieter:
        is_local = True

        def __init__(self, name: str, *, faellt_aus: bool) -> None:
            self.name = name
            self._faellt_aus = faellt_aus
            self.gefragt = 0
            # Der Manager liest die Einstellungen, um den Verlauf fuer
            # kleine lokale Modelle zu kuerzen.
            self.settings: dict[str, Any] = {}

        async def chat(self, messages: Any, **kwargs: Any) -> ProviderResponse:
            self.gefragt += 1
            if self._faellt_aus:
                raise ProviderError(f"{self.name}: gerade nicht erreichbar")
            return ProviderResponse(
                text="Guten Tag.", provider=self.name, model="test"
            )

    kaputt = _Anbieter("primaer", faellt_aus=True)
    heil = _Anbieter("ausweich", faellt_aus=False)

    manager = ProviderManager.__new__(ProviderManager)
    manager._providers = {"primaer": kaputt, "ausweich": heil}
    manager._primary_name = "primaer"
    manager._active_name = "primaer"
    manager._fallback_name = "ausweich"
    manager._operating_mode = "auto"
    manager._quota_cooldowns = {}
    manager._ai_config = {"dialog_fallback_order": ["ausweich"]}
    manager._health = ProviderHealth()
    manager._local_routing_config = {"sequential_only": False}
    manager._local_inference_lock = asyncio.Lock()

    async def _lauf() -> Any:
        return await manager.chat([ChatMessage(role="user", content="Hallo")])

    antwort = asyncio.run(_lauf())

    assert antwort.text == "Guten Tag."
    assert kaputt.gefragt == 1
    assert heil.gefragt == 1
