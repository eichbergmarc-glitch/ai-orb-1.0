"""Der per Sprache schaltbare, strikt lokale Modellbetrieb."""

from __future__ import annotations

import asyncio

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
        ("Bist du im Offlinebetrieb?", "status"),
        ("Bist du gerade online?", "status"),
        ("Erklaere mir, was ein lokales Modell ist", ""),
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
    manager._engines = [_Engine("elevenlabs"), _Engine("piper"), _Engine("sapi")]
    manager._active = manager._engines[0]
    manager._offline_mode = False

    manager.set_offline_mode(True)

    assert manager._active is None
    assert [engine.name for engine in manager.available_engines()] == ["piper", "sapi"]
