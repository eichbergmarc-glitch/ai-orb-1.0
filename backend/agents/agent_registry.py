"""Agent Registry – Verzeichnis aller registrierten Agenten.

Neue Agenten (Mathematik, CAD, Musik, Video, Finanzen, medizinische
Information …) können jederzeit ergänzt werden. Jeder neue Agent muss
registriert und getestet werden, bevor er Aufgaben erhält.
"""

from __future__ import annotations

import threading
from typing import Any

from backend.agents.base_agent import AgentTask, BaseAgent
from backend.system.logging_setup import get_logger

logger = get_logger(__name__)


class AgentRegistry:
    """Verwaltet alle bekannten Agenten."""

    def __init__(self) -> None:
        self._agents: dict[str, BaseAgent] = {}
        self._tested: set[str] = set()
        self._lock = threading.RLock()

    def register(self, agent: BaseAgent) -> None:
        """Nimmt einen Agenten in das Verzeichnis auf."""

        with self._lock:
            self._agents[agent.name] = agent
        logger.info("Agent registriert: %s (%s)", agent.name, agent.description)

    def unregister(self, name: str) -> bool:
        """Entfernt einen Agenten."""

        with self._lock:
            removed = self._agents.pop(name, None) is not None
            self._tested.discard(name)
        return removed

    def get(self, name: str) -> BaseAgent | None:
        """Gibt einen Agenten zurück."""

        with self._lock:
            return self._agents.get(name)

    def all(self) -> list[BaseAgent]:
        """Alle registrierten Agenten."""

        with self._lock:
            return list(self._agents.values())

    def names(self) -> list[str]:
        """Namen aller registrierten Agenten."""

        with self._lock:
            return sorted(self._agents)

    async def self_test(self, name: str) -> dict[str, Any]:
        """Prüft einen Agenten mit einer harmlosen Testaufgabe.

        Ein Agent gilt erst dann als einsatzbereit, wenn dieser Test
        durchgelaufen ist. Der Test verändert keinen Systemzustand.

        Returns:
            Ein Bericht über den Testlauf.
        """

        agent = self.get(name)
        if agent is None:
            return {"agent": name, "passed": False, "message": "Agent ist nicht registriert."}

        # Agenten, die ein Sprachmodell benötigen, werden ohne Netzanfrage
        # geprüft: Es wird lediglich die Schnittstelle validiert.
        if agent.requires_llm:
            passed = bool(agent.system_prompt) and bool(agent.capabilities)
            message = (
                "Schnittstelle und Prompt sind vollständig."
                if passed
                else "Prompt oder Fähigkeiten fehlen."
            )
        else:
            result = await agent.run(AgentTask(text="selbsttest", metadata={"selftest": True}))
            passed = result.agent == agent.name
            message = "Der Agent hat auf eine Testaufgabe geantwortet."

        if passed:
            with self._lock:
                self._tested.add(name)

        return {"agent": name, "passed": passed, "message": message}

    def is_tested(self, name: str) -> bool:
        """Ob ein Agent den Selbsttest bestanden hat."""

        with self._lock:
            return name in self._tested

    def describe_all(self) -> list[dict[str, Any]]:
        """Beschreibt alle Agenten für die Transparenzansicht."""

        return [
            {**agent.describe(), "tested": self.is_tested(agent.name)} for agent in self.all()
        ]
