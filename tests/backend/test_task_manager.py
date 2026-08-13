from __future__ import annotations

import asyncio

import pytest

from backend.system.task_manager import BackgroundTaskManager


def test_tasks_werden_registriert_und_entfernt():
    async def lauf():
        manager = BackgroundTaskManager()
        fertig = asyncio.Event()

        async def arbeit():
            await fertig.wait()

        manager.create("arbeit", arbeit())
        assert manager.snapshot()[0]["name"] == "arbeit"
        fertig.set()
        await asyncio.sleep(0)
        assert manager.snapshot() == []

    asyncio.run(lauf())


def test_shutdown_bricht_alle_tasks_ab():
    async def lauf():
        manager = BackgroundTaskManager()
        beendet = asyncio.Event()

        async def arbeit():
            try:
                await asyncio.Event().wait()
            finally:
                beendet.set()

        manager.create("arbeit", arbeit())
        await asyncio.sleep(0)
        await manager.shutdown()
        assert beendet.is_set()
        assert manager.snapshot() == []

    asyncio.run(lauf())


def test_doppelte_namen_werden_abgewiesen():
    async def lauf():
        manager = BackgroundTaskManager()
        manager.create("gleich", asyncio.sleep(10))
        with pytest.raises(RuntimeError):
            manager.create("gleich", asyncio.sleep(10))
        await manager.shutdown()

    asyncio.run(lauf())
