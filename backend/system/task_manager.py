"""Zentrale Verwaltung langlebiger asyncio-Hintergrundaufgaben."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

from backend.system.logging_setup import get_logger

logger = get_logger(__name__)


class BackgroundTaskManager:
    """Registriert Aufgaben, protokolliert Fehler und beendet sie geordnet."""

    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task[Any]] = {}
        self._closing = False
        #: Die Loop, auf der zuletzt eine Aufgabe angelegt wurde - um einen
        #: Aufruf aus einem fremden Faden von einem harmlosen Aufruf vor
        #: dem Start der Loop unterscheiden zu können.
        self._loop: asyncio.AbstractEventLoop | None = None

    def create(self, name: str, coroutine: Coroutine[Any, Any, Any]) -> asyncio.Task[Any]:
        if self._closing:
            coroutine.close()
            raise RuntimeError("Der Task-Manager wird bereits beendet.")
        existing = self._tasks.get(name)
        if existing is not None and not existing.done():
            coroutine.close()
            raise RuntimeError(f"Hintergrundaufgabe '{name}' laeuft bereits.")
        # `Runtime.start` registriert den Boot-Task unmittelbar bevor die
        # neue Event-Loop mit run_forever anläuft. get_event_loop kann in
        # genau diesem erlaubten Zwischenzustand bereits Tasks anlegen.
        #
        # Aus einem FREMDEN Faden heraus geht das dagegen grundsätzlich
        # nicht - eine Loop ist nicht fadenfest. Genau das ist im Betrieb
        # passiert: Der HTTP-Server rief von seinen Anfrage-Fäden aus hier
        # herein und bekam das kryptische "There is no current event loop
        # in thread 'Thread-3842'", dutzendfach im Protokoll, ohne dass
        # jemand wusste, wohin damit. Wer von außerhalb der Kern-Loop
        # kommt, bekommt jetzt eine Antwort, die den richtigen Weg nennt.
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is None:
            merker = self._loop
            if merker is not None and merker.is_running():
                coroutine.close()
                raise RuntimeError(
                    "BackgroundTaskManager.create wurde aus einem fremden "
                    "Faden gerufen. Von dort führt der Weg über "
                    "asyncio.run_coroutine_threadsafe(..., loop) - wie in "
                    "Runtime._stueck_anstossen."
                )
            loop = asyncio.get_event_loop()
        self._loop = loop
        task = loop.create_task(coroutine, name=name)
        self._tasks[name] = task
        task.add_done_callback(lambda done, key=name: self._finished(key, done))
        return task

    def _finished(self, name: str, task: asyncio.Task[Any]) -> None:
        if self._tasks.get(name) is task:
            self._tasks.pop(name, None)
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            logger.error(
                "Hintergrundaufgabe '%s' ist fehlgeschlagen: %s",
                name,
                error,
                exc_info=(type(error), error, error.__traceback__),
            )

    def snapshot(self) -> list[dict[str, Any]]:
        # Done-Callbacks laufen im nächsten Loop-Durchgang. Für eine
        # Diagnose darf ein bereits fertiger Task nicht bis dahin als aktiv
        # erscheinen.
        for name, task in list(self._tasks.items()):
            if task.done():
                self._finished(name, task)
        return [
            {"name": name, "done": task.done(), "cancelled": task.cancelled()}
            for name, task in sorted(self._tasks.items())
        ]

    async def shutdown(self, timeout: float = 8.0) -> None:
        self._closing = True
        tasks = [task for task in self._tasks.values() if not task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True), timeout=timeout
                )
            except asyncio.TimeoutError:
                logger.warning("%d Hintergrundaufgaben reagierten nicht rechtzeitig.", len(tasks))
        self._tasks.clear()
