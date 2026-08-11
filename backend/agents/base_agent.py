"""Basisklasse aller spezialisierten Agenten.

Jeder Agent besitzt eine klar definierte Aufgabe, eine eindeutige API,
einen eigenen Arbeitskontext sowie klare Ein- und Ausgaben. Agenten
kommunizieren **niemals direkt miteinander** – jede Koordination läuft über
den Agent Manager und damit über das Cognitive Core.

Nach außen bleibt der Orb eine einzige Persönlichkeit; die Aufteilung in
Agenten ist ein interner Umsetzungsdetail.
"""

from __future__ import annotations

import abc
import time
from dataclasses import dataclass, field
from typing import Any

from backend.system.logging_setup import get_logger

logger = get_logger(__name__)


@dataclass
class AgentTask:
    """Die Eingabe eines Agenten."""

    text: str
    context: str = ""
    project_id: str | None = None
    order: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentResult:
    """Die Ausgabe eines Agenten."""

    agent: str
    response: str = ""
    success: bool = True
    order: int = 0
    confidence: str = "mittel"
    sources: list[dict[str, str]] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    duration_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "response": self.response,
            "success": self.success,
            "order": self.order,
            "confidence": self.confidence,
            "sources": self.sources,
            "data": self.data,
            "error": self.error,
            "duration_seconds": round(self.duration_seconds, 3),
        }


class BaseAgent(abc.ABC):
    """Abstrakte Basisklasse für alle Agenten."""

    #: Eindeutiger Name des Agenten.
    name: str = "base"

    #: Kurzbeschreibung der Zuständigkeit (für die Transparenzansicht).
    description: str = ""

    #: Fähigkeiten, die dieser Agent bereitstellt (Capability Registry).
    capabilities: tuple[str, ...] = ()

    #: Der agenteneigene Systemprompt. Jeder Agent besitzt eigene Regeln.
    system_prompt: str = "Du bist ein spezialisierter Teil von AI-Orb."

    #: Ob dieser Agent ein Sprachmodell benötigt.
    requires_llm: bool = True

    def __init__(self) -> None:
        self._started = False

    async def start(self) -> None:
        """Startet den Agenten (wird nur bei Bedarf aufgerufen)."""

        self._started = True

    async def stop(self) -> None:
        """Beendet den Agenten und gibt Ressourcen frei."""

        self._started = False

    @property
    def is_started(self) -> bool:
        """Ob der Agent aktiv ist."""

        return self._started

    @abc.abstractmethod
    async def handle(self, task: AgentTask) -> AgentResult:
        """Bearbeitet eine Aufgabe.

        Args:
            task: Die zu bearbeitende Aufgabe.

        Returns:
            Das Ergebnis des Agenten.
        """

    async def run(self, task: AgentTask) -> AgentResult:
        """Führt :meth:`handle` mit Zeitmessung und Fehlerbehandlung aus.

        Fehler eines Agenten führen niemals zu einem stillen Abbruch: Sie
        werden protokolliert und als fehlgeschlagenes Ergebnis
        zurückgegeben, damit der Result Merger eine Teilantwort erzeugen
        kann.
        """

        if not self._started:
            await self.start()

        started = time.perf_counter()
        try:
            result = await self.handle(task)
        except Exception as error:  # noqa: BLE001 - kein Agent darf den Orb stoppen.
            logger.exception("Agent '%s' fehlgeschlagen.", self.name)
            result = AgentResult(
                agent=self.name,
                success=False,
                error=str(error),
                response="",
                order=task.order,
            )
        result.order = task.order
        result.duration_seconds = time.perf_counter() - started
        return result

    def describe(self) -> dict[str, Any]:
        """Beschreibt den Agenten für die Transparenzansicht."""

        return {
            "name": self.name,
            "description": self.description,
            "capabilities": list(self.capabilities),
            "requires_llm": self.requires_llm,
            "started": self._started,
        }
