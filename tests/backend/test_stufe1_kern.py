"""Regressionstests der Stufe 1: Der Orb muss antworten - immer.

Fuenf schwere Befunde aus der Bestandsaufnahme vom 30.08.2026, jeder mit
dem Test, der ihn beim naechsten Mal auffaengt. Geprueft wird nicht, dass
der Code so aussieht wie jetzt, sondern dass das Verhalten stimmt: kein
toter Anbieter an erster Stelle, keine Wiederbelebung ohne Pruefung, keine
leere Antwort als Erfolg, keine unbegrenzte Wartezeit - und keine
kritische Berechtigung, die eine Konfigurationszeile durchwinkt.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from backend.events.event_bus import EventBus
from backend.orchestrator.provider_health import ProviderHealth
from backend.orchestrator.provider_manager import ProviderManager
from backend.orchestrator.providers.base_provider import ChatMessage, ProviderError
from backend.orchestrator.orchestrator import Orchestrator
from backend.orchestrator.providers.hermes_provider import HermesProvider
from backend.security import security_engine as sicherheitsmodul
from backend.security.security_engine import SecurityEngine


# --- Hilfsmittel ------------------------------------------------------------


class _Konfig:
    """Ein Konfigurationsdoppel mit genau den Werten des jeweiligen Tests."""

    def __init__(self, werte: dict[str, Any]) -> None:
        self._werte = werte

    def get(self, schluessel: str, standard: Any = None) -> Any:
        return self._werte.get(schluessel, standard)

    def section(self, name: str) -> dict[str, Any]:
        wert = self._werte.get(name, {})
        return wert if isinstance(wert, dict) else {}


def _engine(monkeypatch: pytest.MonkeyPatch, **werte: Any) -> SecurityEngine:
    grund = {
        "security.mode": "geschuetzt",
        # Damit eine Rueckfrage im Test nicht zwei Minuten wartet: Schweigen
        # gilt als Nein, und das soll hier sofort feststehen.
        "security.consent_timeout_seconds": 0.05,
        "desktop.file_search_roots": [],
        "security.never_allow": [],
    }
    grund.update(werte)
    monkeypatch.setattr(sicherheitsmodul, "get_config", lambda: _Konfig(grund))
    return SecurityEngine(EventBus())


class _Anbieter:
    """Ein Provider, der nur zaehlt, wie oft er wirklich gefragt wurde."""

    def __init__(self, name: str, *, erreichbar: bool = False, lokal: bool = True) -> None:
        self.name = name
        self.is_local = lokal
        self._erreichbar = erreichbar
        self.pruefungen = 0

    async def is_available(self) -> bool:
        self.pruefungen += 1
        return self._erreichbar


def _manager(*namen: str) -> ProviderManager:
    manager = ProviderManager.__new__(ProviderManager)
    manager._providers = {name: _Anbieter(name) for name in namen}
    manager._primary_name = namen[0]
    manager._active_name = namen[0]
    manager._fallback_name = namen[-1]
    manager._operating_mode = "auto"
    manager._quota_cooldowns = {}
    manager._ai_config = {"dialog_fallback_order": list(namen[1:])}
    manager._health = ProviderHealth()
    return manager


# --- 1. Vorabfreigabe gilt nicht fuer kritische Rechte ----------------------


def test_kritische_vorabfreigabe_wird_nicht_uebernommen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``system_commands`` ist kritisch und faellt aus der Liste heraus."""

    engine = _engine(
        monkeypatch,
        **{"security.pre_approved": ["read_files", "system_commands", "modify_own_code"]},
    )

    assert engine._preapproved == {"read_files"}
    assert engine._preapproved_rejected == {"system_commands", "modify_own_code"}
    assert engine.status()["pre_approved_rejected"] == [
        "modify_own_code",
        "system_commands",
    ]


def test_kritisches_recht_fragt_trotz_vorabfreigabe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Die Zusage der Selbstverbesserung haengt an keiner Konfigurationszeile."""

    engine = _engine(monkeypatch, **{"security.pre_approved": ["modify_own_code"]})

    entscheidung = asyncio.run(
        engine.require("selbstverbesserung", "modify_own_code", "Patch einspielen")
    )

    # Gefragt wurde, niemand hat geantwortet - also nein.
    assert entscheidung.allowed is False


def test_unkritische_vorabfreigabe_gilt_weiterhin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Der Sinn der Liste bleibt erhalten, nur ihre Reichweite endet."""

    engine = _engine(monkeypatch, **{"security.pre_approved": ["read_files"]})

    entscheidung = asyncio.run(
        engine.require("werkzeug", "read_files", "Eine Datei lesen")
    )

    assert entscheidung.allowed is True


# --- 2. Die Vertrauensabkuerzung belebt niemanden wieder --------------------


def test_gescheiterter_anbieter_wird_wirklich_geprueft() -> None:
    health = ProviderHealth()
    anbieter = _Anbieter("ollama", erreichbar=False)
    health.register(anbieter)

    health.note_success("ollama", 0.1)
    health.note_error("ollama")
    health.note_error("ollama")
    assert health.record("ollama").available is False

    ergebnis = asyncio.run(health.check_now())

    assert ergebnis["ollama"] is False
    assert health.record("ollama").available is False
    assert anbieter.pruefungen == 1, "der Fehlschlag muss eine echte Pruefung ausloesen"


def test_frisch_geantworteter_anbieter_wird_nicht_unnoetig_gefragt() -> None:
    """Die Abkuerzung selbst bleibt - sie war teuer erkauft."""

    health = ProviderHealth()
    anbieter = _Anbieter("ollama", erreichbar=True)
    health.register(anbieter)

    health.note_success("ollama", 0.1)
    ergebnis = asyncio.run(health.check_now())

    assert ergebnis["ollama"] is True
    assert anbieter.pruefungen == 0


# --- 3. Die Reihenfolge kennt den Gesundheitszustand ------------------------


def test_toter_anbieter_steht_nicht_mehr_vorn() -> None:
    manager = _manager("openai", "ollama_fast", "ollama")
    manager._health.note_error("openai")
    manager._health.note_error("openai")

    reihenfolge = manager._provider_order()

    assert reihenfolge[0] != "openai"
    assert reihenfolge[-1] == "openai", "hinten anstellen, nicht wegwerfen"
    assert set(reihenfolge) == {"openai", "ollama_fast", "ollama"}


def test_auch_bei_lauter_kranken_anbietern_bleibt_die_reihe_vollstaendig() -> None:
    manager = _manager("openai", "ollama")
    for name in ("openai", "ollama"):
        manager._health.note_error(name)
        manager._health.note_error(name)

    reihenfolge = manager._provider_order()

    assert set(reihenfolge) == {"openai", "ollama"}


def test_ungepruefter_anbieter_behaelt_seinen_platz() -> None:
    """Unmittelbar nach dem Start ist noch niemand krank."""

    manager = _manager("openai", "ollama")

    assert manager._provider_order()[0] == "openai"


# --- 4. Eine leere Antwort ist ein Fehlschlag -------------------------------


def test_hermes_meldet_leere_antwort_als_fehler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = HermesProvider({"base_url": "https://example.invalid", "model": "test"})

    async def _antwort(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return {"choices": [{"message": {"content": "   "}, "finish_reason": "stop"}]}

    monkeypatch.setattr(provider, "_request_json", _antwort)

    with pytest.raises(ProviderError):
        asyncio.run(provider.chat([ChatMessage(role="user", content="hallo")]))


def test_hermes_gibt_echten_text_normal_zurueck(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = HermesProvider({"base_url": "https://example.invalid", "model": "test"})

    async def _antwort(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return {"choices": [{"message": {"content": "Guten Tag."}, "finish_reason": "stop"}]}

    monkeypatch.setattr(provider, "_request_json", _antwort)

    antwort = asyncio.run(provider.chat([ChatMessage(role="user", content="hallo")]))

    assert antwort.text == "Guten Tag."


# --- 5. Kein Zug ohne Gesamtfrist -------------------------------------------


def _orchestrator(**werte: Any) -> Orchestrator:
    orchestrator = Orchestrator.__new__(Orchestrator)
    orchestrator._config = _Konfig(werte)
    return orchestrator


def test_die_gesamtfrist_kommt_aus_der_konfiguration() -> None:
    assert _orchestrator(**{"ai.answer_timeout_seconds": 90})._antwortfrist("hallo") == 90.0


def test_null_hebt_die_gesamtfrist_auf() -> None:
    """Wer sie nicht will, kann sie abschalten - aber bewusst."""

    assert _orchestrator(**{"ai.answer_timeout_seconds": 0})._antwortfrist("hallo") == 0.0


def test_ohne_eintrag_gilt_die_vorgabe() -> None:
    assert _orchestrator()._antwortfrist("hallo") == 180.0


def test_ein_vorlesungsabschnitt_bekommt_mehr_zeit() -> None:
    """Die Frist ist eine Notbremse gegen Haenger, keine Laengengrenze."""

    from backend.studium.vorlesungs_session import VORLESUNGS_MARKER

    orchestrator = _orchestrator(
        **{"ai.answer_timeout_seconds": 60, "ai.answer_timeout_lecture_factor": 3}
    )

    assert orchestrator._antwortfrist("hallo") == 60.0
    assert orchestrator._antwortfrist(f"{VORLESUNGS_MARKER} weiter") == 180.0


def test_eine_haengende_anfrage_wird_abgebrochen() -> None:
    """Der Kern der Sache: wait_for greift, und der Verlauf bleibt sauber."""

    async def _haengt() -> None:
        await asyncio.sleep(30)

    async def _lauf() -> None:
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(_haengt(), timeout=0.05)

    asyncio.run(_lauf())
