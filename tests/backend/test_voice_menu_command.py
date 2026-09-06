"""Lokale Sprachbefehle fuer das Ringmenue."""

from __future__ import annotations

import asyncio

from backend.voice.voice_pipeline import VoicePipeline


class _Bus:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    async def publish(self, name: str, payload: dict) -> None:
        self.events.append((name, payload))


class _Pipeline(VoicePipeline):
    def __init__(self) -> None:
        self._event_bus = _Bus()


def test_menue_oeffnen_ist_ein_lokaler_sprachbefehl():
    pipeline = _Pipeline()
    assert asyncio.run(pipeline._menue_befehl("Zeig mir das Menü")) is True
    assert pipeline._event_bus.events == [("orb.menu.requested", {"action": "open"})]


def test_menue_schliessen_entsperrt_die_oberflaeche():
    pipeline = _Pipeline()
    assert asyncio.run(pipeline._menue_befehl("Menü schließen")) is True
    assert pipeline._event_bus.events == [("orb.menu.requested", {"action": "close"})]


def test_chat_oeffnen_ist_ein_lokaler_sprachbefehl():
    pipeline = _Pipeline()
    assert asyncio.run(pipeline._menue_befehl("Öffne den Chat")) is True
    assert pipeline._event_bus.events == [("orb.chat.requested", {"action": "open"})]


def test_orb_beenden_ist_unabhaengig_vom_chatfenster():
    pipeline = _Pipeline()
    assert asyncio.run(pipeline._menue_befehl("Beende den Orb")) is True
    assert pipeline._event_bus.events == [("orb.quit.requested", {"source": "voice"})]


def test_normale_frage_wird_nicht_als_menuebefehl_verschluckt():
    pipeline = _Pipeline()
    assert asyncio.run(pipeline._menue_befehl("Was steht heute auf dem Menü?")) is False
    assert pipeline._event_bus.events == []
