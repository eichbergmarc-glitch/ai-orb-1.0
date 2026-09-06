"""Der lokale Rueckfall darf nicht daran scheitern, dass er kalt ist.

Protokoll vom 06.09.2026:

    12:45:13  ollama      - Keine Antwortverbindung innerhalb von 60 s
    12:47:05  ollama      - dasselbe noch einmal
    12:48:23  ollama_fast - Antwort da
    12:55:15  ollama_fast - Keine Antwortverbindung innerhalb von 10 s

Der Fehlschlag um 12:55 kam sieben Minuten nach dem Erfolg um 12:48 - also
nach Ablauf von ``keep_alive: 5m``. Das Modell war ausgeraeumt und lud neu.
Es war nie kaputt, nur kalt.
"""

from __future__ import annotations

import asyncio

import pytest

from backend.orchestrator.provider_manager import ProviderManager
from backend.orchestrator.providers.base_provider import BaseProvider, ProviderResponse
from backend.orchestrator.providers.ollama_provider import OllamaProvider


def _ollama(**mehr) -> OllamaProvider:
    settings = {
        "model": "lfm2.5:8b",
        "timeout": 120,
        "first_token_timeout": 60,
        "first_token_timeout_cold": 120,
        "keep_alive": "30m",
    }
    settings.update(mehr)
    return OllamaProvider(settings)


# --- Die Frist -------------------------------------------------------------


def test_keep_alive_wird_in_sekunden_uebersetzt():
    uebersetzen = OllamaProvider._keep_alive_in_sekunden
    assert uebersetzen("30m") == 1800.0
    assert uebersetzen("5m") == 300.0
    assert uebersetzen("45s") == 45.0
    assert uebersetzen("2h") == 7200.0
    assert uebersetzen("600") == 600.0
    assert uebersetzen("-1") == float("inf"), "negativ heisst: nie ausraeumen"
    assert uebersetzen("") == 0.0


def test_ohne_je_geantwortet_zu_haben_gilt_die_kalte_frist():
    provider = _ollama()

    assert provider._erste_frist() == 120.0


def test_direkt_nach_einer_antwort_gilt_die_knappe_frist():
    provider = _ollama()
    provider._erfolg_vermerken()

    assert provider._erste_frist() == 60.0


def test_nach_ablauf_von_keep_alive_gilt_wieder_die_kalte_frist():
    """Der Fall vom 12:55:15 - Erfolg um 12:48, keep_alive war 5 Minuten."""

    provider = _ollama(keep_alive="5m", first_token_timeout=10, first_token_timeout_cold=60)
    provider._erfolg_vermerken()
    # Sieben Minuten spaeter. Die Uhr des Providers laeuft in Sekunden.
    provider._letzter_erfolg -= 7 * 60

    assert provider._erste_frist() == 60.0, "ausgeraeumt heisst kalt, nicht kaputt"


def test_die_kalte_frist_bleibt_unter_dem_gesamtzeitlimit():
    """Eine Frist auf das erste Wort darf nie laenger sein als das Ganze."""

    provider = _ollama(timeout=30, first_token_timeout=10, first_token_timeout_cold=300)

    assert provider._erste_frist() == 30.0


def test_ohne_keep_alive_bleibt_es_bei_der_kalten_frist():
    """Wer das Modell nicht halten laesst, hat immer einen Kaltstart."""

    provider = _ollama(keep_alive="")
    provider._erfolg_vermerken()

    assert provider._erste_frist() == 120.0


# --- Das Vorwaermen --------------------------------------------------------


class _LokalerProvider(BaseProvider):
    is_local = True

    def __init__(self, name: str) -> None:
        super().__init__({"model": name})
        self.name = name
        self.gewaermt = 0

    async def is_available(self) -> bool:
        return True

    async def chat(self, messages, **kwargs) -> ProviderResponse:
        return ProviderResponse("ok", self.name, self.model)

    async def chat_stream(self, messages, **kwargs):
        yield "ok"

    async def waermen(self) -> bool:
        self.gewaermt += 1
        return True


class _CloudProvider(_LokalerProvider):
    is_local = False

    async def prewarm(self) -> bool:
        self.gewaermt += 1
        return True


def _manager(*, prewarm_local: bool = True) -> tuple[ProviderManager, dict[str, _LokalerProvider]]:
    cloud = _CloudProvider("claude_code")
    haupt = _LokalerProvider("ollama")
    schnell = _LokalerProvider("ollama_fast")
    richter = _LokalerProvider("ollama_richter")

    manager = ProviderManager.__new__(ProviderManager)
    manager._providers = {p.name: p for p in (cloud, haupt, schnell, richter)}
    manager._primary_name = cloud.name
    manager._fallback_name = haupt.name
    manager._active_name = cloud.name
    manager._operating_mode = "auto"
    manager._ai_config = {"prewarm_local": prewarm_local}
    manager._local_routing_config = {
        "main_provider": "ollama",
        "fast_provider": "ollama_fast",
        "sequential_only": True,
    }
    manager._local_inference_lock = asyncio.Lock()
    return manager, {p.name: p for p in (cloud, haupt, schnell, richter)}


async def test_prewarm_waermt_auch_die_lokalen_rueckfallmodelle():
    manager, provider = _manager()

    await manager.prewarm()
    await manager._lokal_waerme_task

    assert provider["claude_code"].gewaermt == 1, "der aktive Provider wie bisher"
    assert provider["ollama"].gewaermt == 1
    assert provider["ollama_fast"].gewaermt == 1


async def test_der_richter_der_messlaeufe_bleibt_kalt():
    """Er wird im Dialog nie gefragt und belegt sonst nur Speicher."""

    manager, provider = _manager()

    await manager.prewarm()
    await manager._lokal_waerme_task

    assert provider["ollama_richter"].gewaermt == 0


async def test_das_vorwaermen_laesst_sich_abschalten():
    manager, provider = _manager(prewarm_local=False)

    await manager.prewarm()

    assert getattr(manager, "_lokal_waerme_task", None) is None
    assert provider["ollama"].gewaermt == 0
    assert provider["claude_code"].gewaermt == 1, "der aktive Provider bleibt"


async def test_ein_gescheitertes_vorwaermen_reisst_nichts_mit():
    """Vorwaermen ist eine Beschleunigung, keine Bedingung."""

    manager, provider = _manager()

    async def _kaputt() -> bool:
        raise RuntimeError("Ollama antwortet nicht")

    provider["ollama"].waermen = _kaputt  # type: ignore[method-assign]

    await manager.prewarm()
    await manager._lokal_waerme_task

    assert provider["ollama_fast"].gewaermt == 1, "der naechste kommt trotzdem dran"


async def test_zweimal_prewarm_startet_nicht_zwei_laeufe():
    manager, provider = _manager()

    langsam = asyncio.Event()

    async def _wartet() -> bool:
        await langsam.wait()
        provider["ollama"].gewaermt += 1
        return True

    provider["ollama"].waermen = _wartet  # type: ignore[method-assign]

    await manager.prewarm()
    erster = manager._lokal_waerme_task
    await manager.prewarm()

    assert manager._lokal_waerme_task is erster

    langsam.set()
    await erster
    assert provider["ollama"].gewaermt == 1
