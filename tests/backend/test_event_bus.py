"""Tests für backend.events.event_bus."""

from __future__ import annotations

import pytest

from backend.events.event_bus import Event, EventBus, WILDCARD


@pytest.fixture()
def bus() -> EventBus:
    return EventBus()


async def test_subscriber_receives_matching_event(bus: EventBus):
    received: list[Event] = []

    async def handler(event: Event) -> None:
        received.append(event)

    bus.subscribe("system.ready", handler)
    await bus.publish("system.ready", {"version": "0.1.0"})

    assert len(received) == 1
    assert received[0].name == "system.ready"
    assert received[0].payload == {"version": "0.1.0"}


async def test_subscriber_does_not_receive_other_events(bus: EventBus):
    received: list[Event] = []

    async def handler(event: Event) -> None:
        received.append(event)

    bus.subscribe("system.ready", handler)
    await bus.publish("system.shutdown", {})

    assert received == []


async def test_wildcard_subscriber_receives_all_events(bus: EventBus):
    received_names: list[str] = []

    async def handler(event: Event) -> None:
        received_names.append(event.name)

    bus.subscribe(WILDCARD, handler)
    await bus.publish("system.ready", {})
    await bus.publish("orb.state.changed", {"state": "listening"})

    assert received_names == ["system.ready", "orb.state.changed"]


def test_sync_handler_is_supported(bus: EventBus):
    import asyncio

    received: list[Event] = []

    def handler(event: Event) -> None:
        received.append(event)

    bus.subscribe("orb.activated", handler)
    asyncio.run(bus.publish("orb.activated", {}))

    assert len(received) == 1


async def test_unsubscribe_stops_further_notifications(bus: EventBus):
    received: list[Event] = []

    async def handler(event: Event) -> None:
        received.append(event)

    bus.subscribe("system.ready", handler)
    bus.unsubscribe("system.ready", handler)
    await bus.publish("system.ready", {})

    assert received == []


def test_unsubscribe_unknown_handler_does_not_raise(bus: EventBus):
    def handler(event: Event) -> None:
        pass

    bus.unsubscribe("never.subscribed", handler)


async def test_failing_handler_does_not_prevent_other_handlers(bus: EventBus):
    received: list[str] = []

    async def failing_handler(event: Event) -> None:
        raise RuntimeError("boom")

    async def working_handler(event: Event) -> None:
        received.append("ok")

    bus.subscribe("system.ready", failing_handler)
    bus.subscribe("system.ready", working_handler)

    await bus.publish("system.ready", {})

    assert received == ["ok"]


async def test_recent_history_tracks_published_events(bus: EventBus):
    await bus.publish("system.ready", {})
    await bus.publish("system.shutdown", {})

    history = bus.recent_history()
    names = [event.name for event in history]

    assert names == ["system.ready", "system.shutdown"]


async def test_recent_history_respects_limit_parameter(bus: EventBus):
    for i in range(5):
        await bus.publish("test.event", {"i": i})

    history = bus.recent_history(limit=2)

    assert len(history) == 2
    assert history[-1].payload == {"i": 4}
