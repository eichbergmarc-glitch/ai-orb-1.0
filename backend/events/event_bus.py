"""Zentraler asynchroner Event Bus von AI-Orb.

Der Event Bus ist das ausschließliche Kommunikationsmittel zwischen
Backend-Modulen (vgl. Architekturvorgabe: "Alle Module kommunizieren
ausschließlich über Events"). Er ist bewusst einfach gehalten
(In-Memory-Publish/Subscribe auf Basis von ``asyncio``), damit er ohne
externe Abhängigkeiten (Message Broker) betrieben werden kann.

Beispiel:
    >>> bus = get_event_bus()
    >>> async def on_ready(event):
    ...     print("System bereit:", event.payload)
    >>> bus.subscribe("system.ready", on_ready)
    >>> await bus.publish("system.ready", {"version": "0.1.0"})
"""

from __future__ import annotations

import asyncio
import inspect
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Union

from backend.system.logging_setup import get_logger

logger = get_logger(__name__)

EventPayload = dict[str, Any]

# Wildcard-Subscription: erhält jedes veröffentlichte Event. Wird u. a. vom
# lokalen API-Server genutzt, um alle Events an das Electron-Frontend
# weiterzureichen, ohne jedes Event einzeln kennen zu müssen.
WILDCARD = "*"


@dataclass
class Event:
    """Repräsentiert ein einzelnes, über den Event Bus veröffentlichtes
    Ereignis."""

    name: str
    payload: EventPayload = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


SyncHandler = Callable[[Event], None]
AsyncHandler = Callable[[Event], Awaitable[None]]
EventHandler = Union[SyncHandler, AsyncHandler]


class EventBus:
    """Asynchroner Publish/Subscribe Event Bus.

    Thread-Sicherheit: Abonnements können aus einem beliebigen Thread
    hinzugefügt/entfernt werden. Das Veröffentlichen (:meth:`publish`) muss
    aus einer laufenden asyncio-Event-Loop heraus aufgerufen werden; für
    Aufrufe aus synchronem Code steht :meth:`publish_threadsafe` zur
    Verfügung.
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, list[EventHandler]] = {}
        self._lock = threading.RLock()
        self._history: list[Event] = []
        self._history_limit = 200

    def subscribe(self, event_name: str, handler: EventHandler) -> None:
        """Registriert ``handler`` für Events mit Namen ``event_name``.

        Args:
            event_name: Name des Events (siehe
                :mod:`backend.events.event_types`) oder :data:`WILDCARD`
                (``"*"``), um alle Events zu erhalten.
            handler: Synchrone oder asynchrone Callback-Funktion, die das
                Event-Payload (``dict``) als einzigen Parameter erhält.
        """

        with self._lock:
            self._subscribers.setdefault(event_name, []).append(handler)
        logger.debug("Neuer Subscriber für '%s': %s", event_name, handler)

    def unsubscribe(self, event_name: str, handler: EventHandler) -> None:
        """Entfernt einen zuvor registrierten Handler.

        Ein Aufruf für einen nicht registrierten Handler wird stillschweigend
        ignoriert, damit Abmeldungen während des Herunterfahrens nicht zu
        Fehlern führen.
        """

        with self._lock:
            handlers = self._subscribers.get(event_name, [])
            if handler in handlers:
                handlers.remove(handler)

    async def publish(self, event_name: str, payload: EventPayload | None = None) -> None:
        """Veröffentlicht ein Event an alle passenden Subscriber.

        Ruft zunächst alle spezifisch auf ``event_name`` registrierten
        Handler auf, danach alle Wildcard-Handler. Ausnahmen einzelner
        Handler werden geloggt, brechen die Verteilung an die übrigen
        Handler aber nicht ab (Fehlertoleranz).

        Args:
            event_name: Name des zu veröffentlichenden Events.
            payload: Nutzdaten des Events (Standard: leeres Dict).
        """

        event = Event(name=event_name, payload=payload or {})

        with self._lock:
            self._history.append(event)
            if len(self._history) > self._history_limit:
                self._history.pop(0)
            handlers = list(self._subscribers.get(event_name, []))
            wildcard_handlers = list(self._subscribers.get(WILDCARD, []))

        for handler in handlers + wildcard_handlers:
            await self._invoke(handler, event)

    def publish_threadsafe(
        self, loop: asyncio.AbstractEventLoop, event_name: str, payload: EventPayload | None = None
    ) -> None:
        """Veröffentlicht ein Event sicher aus einem anderen Thread heraus.

        Args:
            loop: Die asyncio-Event-Loop, auf der der Event Bus läuft
                (typischerweise die Loop des API-Servers).
            event_name: Name des zu veröffentlichenden Events.
            payload: Nutzdaten des Events.
        """

        asyncio.run_coroutine_threadsafe(self.publish(event_name, payload), loop)

    async def _invoke(self, handler: EventHandler, event: Event) -> None:
        try:
            result = handler(event)
            if inspect.isawaitable(result):
                await result
        except Exception:  # noqa: BLE001 - Handler-Fehler dürfen den Bus nicht stoppen.
            logger.exception(
                "Fehler in Event-Handler für '%s' (%s)", event.name, handler
            )

    def recent_history(self, limit: int = 50) -> list[Event]:
        """Gibt die zuletzt veröffentlichten Events zurück (neueste zuletzt).

        Nützlich für Diagnose-Endpunkte und für neu verbindende
        Frontend-Clients, die den letzten bekannten Zustand nachladen wollen.
        """

        with self._lock:
            return list(self._history[-limit:])


_instance_lock = threading.Lock()
_instance: EventBus | None = None


def get_event_bus() -> EventBus:
    """Gibt die prozessweite :class:`EventBus`-Singleton-Instanz zurück."""

    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = EventBus()
    return _instance
