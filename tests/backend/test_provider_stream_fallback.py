"""Rueckfall des Antwortstroms, bevor der Benutzer Text erhalten hat."""

from __future__ import annotations

import pytest

from backend.orchestrator.provider_health import ProviderHealth
from backend.orchestrator.provider_manager import ProviderManager
from backend.orchestrator.providers.base_provider import BaseProvider, ChatMessage, ProviderError, ProviderResponse


class _Provider(BaseProvider):
    def __init__(self, name: str, pieces: list[str], *, fail: bool = False) -> None:
        super().__init__({"model": name})
        self.name = name
        self._pieces = pieces
        self._fail = fail

    async def is_available(self) -> bool:
        return True

    async def chat(self, messages, **kwargs) -> ProviderResponse:
        return ProviderResponse("".join(self._pieces), self.name, self.model)

    async def chat_stream(self, messages, **kwargs):
        for piece in self._pieces:
            yield piece
        if self._fail:
            raise ProviderError(f"{self.name}: Zeitlimit")


class _UnexpectedProvider(_Provider):
    async def chat(self, messages, **kwargs) -> ProviderResponse:
        raise OSError("Prozess abgebrochen")

    async def chat_stream(self, messages, **kwargs):
        raise OSError("Verbindung abgebrochen")
        yield  # pragma: no cover - macht die Methode zum Async-Generator.


def _manager(primary: _Provider, fallback: _Provider) -> ProviderManager:
    manager = ProviderManager.__new__(ProviderManager)
    manager._providers = {primary.name: primary, fallback.name: fallback}
    manager._primary_name = primary.name
    manager._fallback_name = fallback.name
    manager._active_name = primary.name
    manager._operating_mode = "auto"
    manager._health = ProviderHealth()
    manager._health.register(primary)
    manager._health.register(fallback)
    return manager


async def test_fallback_uebernimmt_wenn_vorher_noch_kein_text_kam():
    manager = _manager(
        _Provider("cloud", [], fail=True),
        _Provider("lokal", ["Schnelle lokale Antwort"]),
    )

    pieces = [
        piece
        async for piece in manager.chat_stream([ChatMessage("user", "Hallo")])
    ]

    assert pieces == ["Schnelle lokale Antwort"]


async def test_nach_dem_ersten_text_wird_nicht_mitten_im_satz_gewechselt():
    manager = _manager(
        _Provider("cloud", ["Begonnen"], fail=True),
        _Provider("lokal", ["Doppelt"]),
    )

    received: list[str] = []
    with pytest.raises(ProviderError):
        async for piece in manager.chat_stream([ChatMessage("user", "Hallo")]):
            received.append(piece)

    assert received == ["Begonnen"]


async def test_unerwarteter_prozessfehler_faellt_lokal_zurueck():
    manager = _manager(
        _UnexpectedProvider("cloud", []),
        _Provider("ollama", ["Lokale Antwort"]),
    )

    response = await manager.chat([ChatMessage("user", "Hallo")])

    assert response.text == "Lokale Antwort"
    assert response.provider == "ollama"


async def test_unerwarteter_streamfehler_faellt_vor_text_lokal_zurueck():
    manager = _manager(
        _UnexpectedProvider("cloud", []),
        _Provider("ollama", ["Lokaler Stream"]),
    )

    pieces = [
        piece
        async for piece in manager.chat_stream([ChatMessage("user", "Hallo")])
    ]

    assert pieces == ["Lokaler Stream"]
