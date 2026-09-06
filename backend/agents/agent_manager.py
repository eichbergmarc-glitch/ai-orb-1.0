"""Agent Manager – die zentrale Verwaltung des Agenten-Teams.

Der Manager registriert alle Standard-Agenten, prüft sie, verteilt Aufgaben
und stellt die Transparenzauskünfte bereit. Er ist die einzige
Schnittstelle, über die das Cognitive Core mit den Agenten spricht;
Agenten kommunizieren niemals direkt miteinander.

Nach außen bleibt AI-Orb eine einzige Persönlichkeit.
"""

from __future__ import annotations

from typing import Any

from backend.agents.agent_metrics import AgentMetrics
from backend.agents.agent_registry import AgentRegistry
from backend.agents.agent_router import AgentRouter
from backend.agents.agent_scheduler import AgentScheduler
from backend.agents.base_agent import BaseAgent
from backend.agents.capability_registry import CapabilityRegistry
from backend.agents.result_merger import ResultMerger
from backend.agents.history_agent.agent import HistoryProfessorAgent
from backend.agents.standard_agents import (
    CodingAgent,
    ConversationAgent,
    DesktopAgent,
    EvolutionAgent,
    MemoryAgent,
    ReasoningAgent,
    ResearchAgent,
    VisionAgent,
    VoiceAgent,
)
from backend.agents.task_dispatcher import DispatchResult, TaskDispatcher
from backend.cognitive.orchestrator import Distribution
from backend.config import get_config
from backend.system.logging_setup import get_logger

logger = get_logger(__name__)

#: Standardberechtigungen je Agent. Sie werden bei der Registrierung
#: erteilt und können vom Benutzer jederzeit geändert werden.
_DEFAULT_PERMISSIONS: dict[str, list[str]] = {
    "desktop": ["file_read", "system_commands"],
    "memory": ["file_read", "file_write", "database"],
    "research": ["internet"],
    "history": ["internet"],
    "coding": ["file_read"],
    "vision": ["screen_capture"],
    "voice": [],
    "conversation": [],
    "reasoning": [],
    "evolution": ["file_read", "file_write"],
}


class AgentManager:
    """Verwaltet das gesamte Agenten-Team."""

    def __init__(
        self,
        *,
        provider_manager: Any,
        memory: Any,
        project_engine: Any,
        execution_manager: Any,
        desktop_control: Any,
        evolution_engine: Any,
        skill_manager: Any | None = None,
        security: Any | None = None,
    ) -> None:
        config = get_config()
        self._security = security
        agents_config = config.section("agents")

        # Welcher Agent welches Modell bevorzugt (Aufgabenverteilung auf
        # mehrere Modelle). Leerer Eintrag oder fehlend = der aktive Provider.
        self._modell_zuordnung: dict[str, str] = {
            str(name): str(engine or "")
            for name, engine in (agents_config.get("modelle", {}) or {}).items()
        }
        self._lokale_modell_zuordnung: dict[str, str] = {
            str(name): str(engine or "")
            for name, engine in (agents_config.get("lokale_modelle", {}) or {}).items()
        }

        self.registry = AgentRegistry()
        self.capabilities = CapabilityRegistry()
        self.metrics = AgentMetrics()
        self.router = AgentRouter(self.capabilities)
        self.scheduler = AgentScheduler(
            self.registry,
            self.metrics,
            timeout_seconds=float(agents_config.get("timeout", 120)),
            lazy_start=bool(agents_config.get("lazy_start", True)),
        )
        self.merger = ResultMerger()
        self.dispatcher = TaskDispatcher(
            self.registry,
            self.router,
            self.scheduler,
            self.merger,
            self.metrics,
            max_parallel=int(agents_config.get("max_parallel", 4)),
        )

        self._register_standard_agents(
            provider_manager=provider_manager,
            memory=memory,
            project_engine=project_engine,
            execution_manager=execution_manager,
            desktop_control=desktop_control,
            evolution_engine=evolution_engine,
            skill_manager=skill_manager,
        )

    # --- Registrierung ------------------------------------------------------

    def _register_standard_agents(
        self,
        *,
        provider_manager: Any,
        memory: Any,
        project_engine: Any,
        execution_manager: Any,
        desktop_control: Any,
        evolution_engine: Any,
        skill_manager: Any | None,
    ) -> None:
        """Registriert alle Standard-Agenten."""

        agents: list[BaseAgent] = [
            ConversationAgent(provider_manager),
            ReasoningAgent(provider_manager),
            ResearchAgent(provider_manager),
            # Der Geschichtsagent ist die Historical Professor & Mentor
            # Engine: sokratisches Lehren, Quellenkritik, Forschungsfragen,
            # Arbeitsbetreuung, Prüfung, Debatte – mit langfristigem
            # Lernprofil. Er ersetzt den früheren Agenten, der nur ein
            # Systemprompt mit guten Vorsätzen war.
            HistoryProfessorAgent(provider_manager),
            CodingAgent(provider_manager),
            DesktopAgent(execution_manager, desktop_control),
            VisionAgent(),
            VoiceAgent(skill_manager),
            MemoryAgent(memory, project_engine),
            EvolutionAgent(evolution_engine),
        ]

        # Der Gmail-Agent braucht die Sicherheitsschicht, weil ueber sie das
        # Senden bestaetigt wird. Ohne sie waere die Sendesperre nicht
        # durchsetzbar - dann lieber gar kein Gmail-Agent.
        if self._security is not None:
            from backend.agents.gmail_agent import GmailAgent

            agents.append(GmailAgent(self._security))

        for agent in agents:
            # Aufgabenverteilung: Jedem Agenten, der ein Modell nutzt, das in
            # der Konfiguration gewuenschte zuweisen. So arbeiten mehrere
            # Agenten gleichzeitig auf verschiedenen Modellen (Claude UND
            # lokal) - der Kern der schnelleren, verteilten Beantwortung.
            gewuenscht = self._modell_zuordnung.get(agent.name)
            if gewuenscht and hasattr(agent, "bevorzugtes_modell"):
                agent.bevorzugtes_modell = gewuenscht
                logger.info(
                    "Agent '%s' nutzt bevorzugt das Modell '%s'.",
                    agent.name,
                    gewuenscht,
                )
            lokal = self._lokale_modell_zuordnung.get(agent.name)
            if lokal and hasattr(agent, "lokales_modell"):
                agent.lokales_modell = lokal
            self.add_agent(agent)

    def add_agent(self, agent: BaseAgent, permissions: list[str] | None = None) -> None:
        """Nimmt einen neuen Agenten in das Team auf.

        Neue Agenten (Mathematik, CAD, Musik, Video, Finanzen …) lassen sich
        so jederzeit ergänzen. Jeder Agent wird registriert; seine
        Fähigkeiten und Berechtigungen landen in der Capability Registry.
        """

        self.registry.register(agent)
        granted = permissions if permissions is not None else _DEFAULT_PERMISSIONS.get(agent.name, [])
        self.capabilities.register_agent(agent, granted)
        for permission in granted:
            self.capabilities.grant(agent.name, permission)

    async def test_all(self) -> list[dict[str, Any]]:
        """Prüft alle registrierten Agenten.

        Ein Agent gilt erst nach bestandenem Test als einsatzbereit.
        """

        reports = [await self.registry.self_test(name) for name in self.registry.names()]
        failed = [report["agent"] for report in reports if not report["passed"]]
        if failed:
            logger.warning("Agenten mit fehlgeschlagenem Selbsttest: %s", ", ".join(failed))
        else:
            logger.info("Alle %d Agenten haben den Selbsttest bestanden.", len(reports))
        return reports

    # --- Ausführung ----------------------------------------------------------

    async def handle(
        self,
        distribution: Distribution,
        *,
        text: str,
        context: str = "",
        project_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> DispatchResult:
        """Lässt das Agenten-Team eine Aufgabe bearbeiten."""

        return await self.dispatcher.dispatch(
            distribution,
            text=text,
            context=context,
            project_id=project_id,
            metadata=metadata,
        )

    async def shutdown(self) -> None:
        """Beendet alle Agenten."""

        await self.scheduler.shutdown()

    # --- Transparenz ----------------------------------------------------------

    def explain_last(self) -> dict[str, Any]:
        """Erklärt, welche Agenten zuletzt beteiligt waren und warum."""

        return self.dispatcher.explain_last()

    def status(self) -> dict[str, Any]:
        """Vollständiger Status des Agenten-Teams."""

        return {
            "agents": self.registry.describe_all(),
            "capabilities": self.capabilities.snapshot(),
            "metrics": self.metrics.snapshot(),
            "scheduler": self.scheduler.status(),
            "most_used": self.metrics.most_used(),
        }
