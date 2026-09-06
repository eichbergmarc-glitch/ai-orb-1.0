"""Der per Sprache schaltbare, strikt lokale Modellbetrieb."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from backend.memory.memory_engine import MemoryEngine
from backend.orchestrator.orchestrator import Orchestrator, provider_mode_command
from backend.orchestrator.providers.base_provider import (
    BaseProvider,
    ChatMessage,
    ProviderError,
    ProviderResponse,
)


class _ModeStore:
    def __init__(self, mode: str = "auto") -> None:
        self.mode = mode

    def get(self, key: str, default=None):
        return self.mode if key == "mode" else default

    def set(self, key: str, value: str) -> None:
        assert key == "mode"
        self.mode = value


class _Config:
    def section(self, name: str):
        if name != "ai":
            return {}
        return {
            "provider": "auto",
            "primary": {"engine": "test_cloud", "model": "cloud-model"},
            "fallback": {"engine": "test_local", "model": "local-model"},
        }

    def get(self, key: str, default=None):
        if key == "routing.mode":
            return "auto"
        return default


class _TestProvider(BaseProvider):
    available = True
    fail = False
    calls = 0
    health_calls = 0

    async def is_available(self) -> bool:
        type(self).health_calls += 1
        return self.available

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> ProviderResponse:
        type(self).calls += 1
        if self.fail:
            raise ProviderError(f"{self.name} ausgefallen")
        return ProviderResponse(
            text=f"Antwort von {self.name}",
            provider=self.name,
            model=self.model,
        )


class _CloudProvider(_TestProvider):
    name = "test_cloud"
    calls = 0


class _LocalProvider(_TestProvider):
    name = "test_local"
    calls = 0

    @property
    def is_local(self) -> bool:
        return True


def _manager(monkeypatch, store: _ModeStore | None = None):
    import backend.orchestrator.provider_manager as module

    monkeypatch.setattr(module, "get_config", lambda: _Config())
    monkeypatch.setitem(module.PROVIDER_TYPES, "test_cloud", _CloudProvider)
    monkeypatch.setitem(module.PROVIDER_TYPES, "test_local", _LocalProvider)
    return module.ProviderManager(mode_store=store or _ModeStore())


class _MultiLocalConfig(_Config):
    def section(self, name: str):
        if name != "ai":
            return {}
        return {
            "provider": "auto",
            "primary": {"engine": "test_cloud", "model": "cloud-model"},
            "fallback": {"engine": "test_slow", "model": "lfm-main"},
            "additional": {
                "test_fast": {
                    "engine": "test_slow",
                    "model": "llama-side",
                }
            },
            "local_routing": {
                "enabled": True,
                "main_provider": "test_slow",
                "fast_provider": "test_fast",
                "sequential_only": True,
            },
        }


class _SlowLocal(_TestProvider):
    name = "test_slow"
    active_calls = 0
    max_active_calls = 0

    @property
    def is_local(self) -> bool:
        return True

    async def chat(self, messages, *, temperature=None, max_tokens=None):
        type(self).active_calls += 1
        type(self).max_active_calls = max(
            type(self).max_active_calls, type(self).active_calls
        )
        try:
            await asyncio.sleep(0.03)
            return ProviderResponse(
                text=f"Antwort von {self.name}",
                provider=self.name,
                model=self.model,
            )
        finally:
            type(self).active_calls -= 1


def _multi_manager(monkeypatch):
    import backend.orchestrator.provider_manager as module

    monkeypatch.setattr(module, "get_config", lambda: _MultiLocalConfig())
    monkeypatch.setitem(module.PROVIDER_TYPES, "test_cloud", _CloudProvider)
    monkeypatch.setitem(module.PROVIDER_TYPES, "test_slow", _SlowLocal)
    return module.ProviderManager(mode_store=_ModeStore())


@pytest.mark.parametrize(
    ("sentence", "expected"),
    [
        ("Schalte bitte in den Offlinebetrieb", "offline"),
        ("Schalte auf offline", "offline"),
        ("Geh offline", "offline"),
        ("Nutze ab jetzt das lokale Modell", "offline"),
        ("Wechsle wieder in den Onlinebetrieb", "auto"),
        ("Schalte wieder online", "auto"),
        ("Schalte den Offline-Modus aus", "auto"),
        ("Beende den Offlinebetrieb", "auto"),
        ("Bist du im Offlinebetrieb?", "status"),
        ("Bist du gerade online?", "status"),
        ("Erklaere mir, was ein lokales Modell ist", ""),
        (
            "Im Offline-Modus läuft er mit Ollama. Aktuell verwende ich "
            "aber eine andere Stimme.",
            "",
        ),
        (
            "Orb, neuer Tagebucheintrag: Im Offline-Modus läuft mein Orb "
            "mit Ollama und aktuell verwende ich zwei Modelle.",
            "",
        ),
        ("Stell dir den Offlinebetrieb als Beispiel vor", ""),
        ("Nutzen wir offline als Beispiel", ""),
        ("Verwende in diesem Tagebucheintrag das Wort Offline", ""),
        (
            "Verwende für die folgende lange Erklärung einige Beispiele und "
            "beschreibe danach ausführlich den Offlinebetrieb des Orb",
            "",
        ),
    ],
)
def test_sprachbefehle_werden_ohne_modell_erkannt(sentence: str, expected: str):
    assert provider_mode_command(sentence) == expected


def test_offlinebetrieb_ist_persistent_und_ohne_cloud_fallback(monkeypatch):
    store = _ModeStore()
    manager = _manager(monkeypatch, store)

    switched = asyncio.run(manager.set_operating_mode("offline"))

    assert switched["success"] is True
    assert manager.offline_mode is True
    assert manager.active_name == "test_local"
    assert store.mode == "offline"

    _CloudProvider.calls = 0
    _LocalProvider.calls = 0
    _LocalProvider.fail = True
    with pytest.raises(ProviderError):
        asyncio.run(manager.chat([ChatMessage(role="user", content="Hallo")]))
    _LocalProvider.fail = False

    assert _LocalProvider.calls == 1
    assert _CloudProvider.calls == 0, "Offline darf niemals still in die Cloud fallen."


def test_bevorzugter_cloud_provider_wird_offline_ignoriert(monkeypatch):
    manager = _manager(monkeypatch)
    asyncio.run(manager.set_operating_mode("offline"))
    _CloudProvider.calls = 0
    _LocalProvider.calls = 0

    response = asyncio.run(
        manager.chat(
            [ChatMessage(role="user", content="Hallo")],
            preferred="test_cloud",
        )
    )

    assert response.provider == "test_local"
    assert _CloudProvider.calls == 0


def test_nebenmodell_wird_nur_im_lokalbetrieb_freigegeben(monkeypatch):
    manager = _multi_manager(monkeypatch)
    manager._active_name = "test_cloud"
    manager._health.note_success("test_cloud", 0.01)
    manager._health.note_success("test_slow", 0.01)

    assert manager.local_routing_active is False
    assert manager.local_provider_for("fast") is None

    asyncio.run(manager.set_operating_mode("offline"))

    assert manager.local_provider_for("main") == "test_slow"
    assert manager.local_provider_for("fast") == "test_fast"
    response = asyncio.run(
        manager.chat(
            [ChatMessage(role="user", content="Kurze Frage")],
            preferred="test_fast",
        )
    )
    assert response.provider == "test_fast"


def test_automatik_erkennt_den_lokalen_betrieb_bei_cloud_ausfall(monkeypatch):
    manager = _multi_manager(monkeypatch)
    manager._active_name = "test_cloud"
    manager._health.note_success("test_slow", 0.01)

    # Der Modusschalter steht noch auf Automatik, aber kein Cloud-Provider
    # gilt als erreichbar. Damit darf dieselbe lokale Verteilung greifen wie
    # nach dem ausdruecklichen Sprachbefehl.
    assert manager.offline_mode is False
    assert manager.local_routing_active is True
    assert manager.local_provider_for("fast") == "test_fast"


def test_status_unterscheidet_automatischen_ersatz_vom_offlinebetrieb(monkeypatch):
    manager = _multi_manager(monkeypatch)
    manager._active_name = "test_slow"

    status = manager.status()

    assert status["mode"] == "auto"
    assert status["offline"] is False
    assert status["temporary_local_fallback"] is True
    assert status["selection"] == "automatic_local_fallback"


def test_lokale_modelle_rechnen_nicht_parallel(monkeypatch):
    manager = _multi_manager(monkeypatch)
    _SlowLocal.active_calls = 0
    _SlowLocal.max_active_calls = 0
    asyncio.run(manager.set_operating_mode("offline"))

    async def scenario():
        await asyncio.gather(
            manager.chat(
                [ChatMessage(role="user", content="Hauptaufgabe")],
                preferred="test_slow",
            ),
            manager.chat(
                [ChatMessage(role="user", content="Nebenaufgabe")],
                preferred="test_fast",
            ),
        )

    asyncio.run(scenario())
    assert _SlowLocal.max_active_calls == 1


def test_gespeicherter_offlinebetrieb_prueft_beim_start_keine_cloud(monkeypatch):
    manager = _manager(monkeypatch, _ModeStore("offline"))
    _CloudProvider.health_calls = 0
    _LocalProvider.health_calls = 0

    async def scenario() -> None:
        await manager.start()
        await manager.stop()

    asyncio.run(scenario())

    assert manager.offline_mode is True
    assert manager.active_name == "test_local"
    assert _LocalProvider.health_calls >= 1
    assert _CloudProvider.health_calls == 0


def test_automatik_startet_ohne_internet_direkt_lokal(monkeypatch):
    import backend.orchestrator.provider_manager as module

    async def kein_internet(**_kwargs) -> bool:
        return False

    monkeypatch.setattr(module, "internet_reachable", kein_internet)
    manager = _manager(monkeypatch)
    _CloudProvider.health_calls = 0
    _LocalProvider.health_calls = 0

    async def scenario() -> None:
        await manager.start()
        await manager.stop()

    asyncio.run(scenario())

    assert manager.offline_mode is False
    assert manager.active_name == "test_local"
    assert manager.status()["temporary_local_fallback"] is True
    assert _CloudProvider.health_calls == 0


def test_netzausfall_vor_einer_frage_ueberspringt_cloud_sofort(monkeypatch):
    import backend.orchestrator.provider_manager as module

    async def kein_internet(**_kwargs) -> bool:
        return False

    monkeypatch.setattr(module, "internet_reachable", kein_internet)
    manager = _manager(monkeypatch)
    manager._active_name = "test_cloud"
    manager._health.note_success("test_cloud", 0.01)
    manager._health.note_success("test_local", 0.01)
    _CloudProvider.calls = 0
    _LocalProvider.calls = 0

    response = asyncio.run(
        manager.chat([ChatMessage(role="user", content="Hallo")])
    )

    assert response.provider == "test_local"
    assert manager.active_name == "test_local"
    assert _CloudProvider.calls == 0
    assert _LocalProvider.calls == 1


def test_automatischer_lokalersatz_schaltet_auch_die_stimme_lokal():
    from backend.runtime import Runtime

    class _Voice:
        offline = False

        def set_offline_mode(self, enabled: bool) -> None:
            self.offline = enabled

    runtime = Runtime.__new__(Runtime)
    runtime.voice = _Voice()

    asyncio.run(
        runtime._sync_provider_mode(
            SimpleNamespace(
                payload={"offline": False, "temporary_local_fallback": True}
            )
        )
    )

    assert runtime.voice.offline is True


class _CommandProviders:
    def __init__(self) -> None:
        self.active_name = "test_cloud"
        self.mode = "auto"
        self.switches: list[str] = []

    def begin_conversation(self) -> None:
        pass

    async def set_operating_mode(self, mode: str):
        self.switches.append(mode)
        self.mode = mode
        self.active_name = "test_local" if mode == "offline" else "test_cloud"
        return {
            "success": True,
            "mode": mode,
            "provider": self.active_name,
            "model": "local-model" if mode == "offline" else "cloud-model",
            "message": "Offlinebetrieb ist aktiv." if mode == "offline" else "Onlinebetrieb ist aktiv.",
        }

    def status(self):
        return {
            "mode": self.mode,
            "active": self.active_name,
            "active_model": "local-model" if self.mode == "offline" else "cloud-model",
        }


def test_orchestrator_schaltet_vor_jeder_modellanfrage():
    providers = _CommandProviders()
    orchestrator = Orchestrator(
        memory=MemoryEngine(),
        provider_manager=providers,  # type: ignore[arg-type]
    )

    result = asyncio.run(orchestrator.handle("Schalte bitte in den Offlinebetrieb", spoken=True))

    assert result.used_llm is False
    assert result.intent == "provider_modus"
    assert result.provider == "test_local"
    assert providers.switches == ["offline"]


def test_offline_stimme_filtert_cloud_engine_aus():
    from backend.tts.tts_manager import TtsManager

    class _Engine:
        def __init__(self, name: str) -> None:
            self.name = name

        def is_available(self) -> bool:
            return True

    manager = TtsManager.__new__(TtsManager)
    manager._engines = [
        _Engine("remote"),
        _Engine("elevenlabs"),
        _Engine("piper"),
        _Engine("chatterbox"),
        _Engine("sapi"),
    ]
    manager._offline_engine_names = ["chatterbox", "piper", "sapi"]
    manager._active = manager._engines[0]
    manager._offline_mode = False

    assert [engine.name for engine in manager.available_engines()] == [
        "remote", "elevenlabs", "piper", "chatterbox", "sapi",
    ]

    manager.set_offline_mode(True)

    assert manager._active is None
    assert [engine.name for engine in manager.available_engines()] == [
        "chatterbox", "piper", "sapi"
    ]


def test_offline_stimmenliste_ist_zulassungsliste_und_nicht_nur_sortierung():
    from backend.tts.tts_manager import TtsManager

    class _Engine:
        def __init__(self, name: str) -> None:
            self.name = name

        def is_available(self) -> bool:
            return True

    manager = TtsManager.__new__(TtsManager)
    manager._engines = [_Engine("chatterbox"), _Engine("piper"), _Engine("sapi")]
    manager._offline_engine_names = ["chatterbox"]
    manager._offline_mode = True

    assert [engine.name for engine in manager.available_engines()] == ["chatterbox"]


def test_tts_netzausfall_ueberspringt_weitere_cloud_stimmen(tmp_path):
    from backend.tts.base_engine import SpeechRequest, SpeechResult
    from backend.tts.tts_manager import TtsManager

    class _Engine:
        def __init__(self, name: str, *, network_error: bool = False) -> None:
            self.name = name
            self.network_error = network_error
            self.calls = 0

        def is_available(self) -> bool:
            return True

        def target_path(self, _request):
            return tmp_path / f"{self.name}.wav"

        def synthesize_blocking(self, _request, target):
            self.calls += 1
            if self.network_error:
                return SpeechResult(
                    engine=self.name,
                    error="Dienst ist nicht erreichbar: getaddrinfo failed",
                )
            target.write_bytes(b"RIFF" + b"\0" * 80)
            return SpeechResult(audio_path=target, engine=self.name)

    erste_cloud = _Engine("edge_neural", network_error=True)
    zweite_cloud = _Engine("openai_tts")
    klon = _Engine("openvoice_clone")
    manager = TtsManager.__new__(TtsManager)
    manager._engines = [erste_cloud, zweite_cloud, klon]
    manager._offline_engine_names = ["openvoice_clone"]
    manager._offline_mode = False
    manager._network_failed_until = 0.0
    manager._engine_failed_until = {}
    manager._engine_failure_reasons = {}
    manager._failure_cooldown_seconds = 90.0
    manager._cache_enabled = False
    manager._active = None

    result = asyncio.run(
        manager._synthesize_with_fallback(SpeechRequest(text="Hallo."))
    )

    assert result.engine == "openvoice_clone"
    assert erste_cloud.calls == 1
    assert zweite_cloud.calls == 0
    assert klon.calls == 1
    assert manager._network_failed_until > 0


def test_tts_behaelt_die_aktive_stimme_statt_zur_cloud_zurueckzuspringen():
    from backend.tts.tts_manager import TtsManager

    class _Engine:
        def __init__(self, name: str) -> None:
            self.name = name

        def is_available(self) -> bool:
            return True

    cloud = _Engine("edge_neural")
    klon = _Engine("openvoice_clone")
    manager = TtsManager.__new__(TtsManager)
    manager._engines = [cloud, klon]
    manager._offline_engine_names = ["openvoice_clone"]
    manager._offline_mode = False
    manager._network_failed_until = 0.0
    manager._engine_failed_until = {}
    manager._active = klon
    manager._consistent_voice = True

    assert [engine.name for engine in manager.available_engines()] == [
        "openvoice_clone", "edge_neural",
    ]
