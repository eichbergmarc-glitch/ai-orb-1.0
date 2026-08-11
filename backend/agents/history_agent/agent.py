"""Der Professor als Agent (Abschnitt 33).

Dies ist die Stelle, an der die Engine an AI-Orb andockt. Sie ersetzt den
bisherigen einfachen ``history``-Agenten, der nichts weiter war als ein
Systemprompt mit guten Vorsätzen.

Der Unterschied liegt im Zustand. Ein Agent, der jede Aufgabe für sich
behandelt, kann keine Quellenanalyse führen – er wüsste beim dritten Zug nicht
mehr, dass eine läuft. Dieser Agent hält deshalb fest, was zwischen den
Zügen gilt: welcher Modus läuft, welche Quellenanalyse,
welches Projekt betreut wird.

Der Zustand liegt bewusst im Agenten und nicht im Gedächtnis: Er ist eine
Sache des laufenden Gesprächs. Was langfristig gilt, steht im Lernprofil,
und das schreibt sich auf die Platte.
"""

from __future__ import annotations

from typing import Any

from backend.agents.base_agent import AgentResult, AgentTask, BaseAgent
from backend.agents.history_agent import (
    debate_engine,
    professor_engine,
    research_question_engine,
    source_criticism,
)
from backend.agents.history_agent.learning_profile import LearningProfile
from backend.agents.history_agent.mentor_engine import MentorEngine, Project
from backend.orchestrator.providers.base_provider import ChatMessage, ProviderError
from backend.system.logging_setup import get_logger

logger = get_logger(__name__)


class HistoryProfessorAgent(BaseAgent):
    """Persönlicher akademischer Mentor für Geschichtswissenschaft."""

    name = "history"
    description = (
        "Geschichtsprofessor und Mentor: sokratisches Lehren, Quellenkritik, "
        "Forschungsfragen, Arbeitsbetreuung, Debatte"
    )
    capabilities = (
        "geschichtswissenschaft",
        "quellenkritik",
        "methodik",
        "forschungskontroversen",
        "historische_einordnung",
        "lehren",
        "pruefen",
        "arbeitsbetreuung",
        "internet",
    )
    system_prompt = professor_engine.PERSONA

    def __init__(self, provider_manager: Any) -> None:
        super().__init__()
        self._providers = provider_manager

        self.profile = LearningProfile()
        self.mentor = MentorEngine()

        #: Der laufende Modus. Ohne ihn spränge der Professor bei jedem
        #: Satz in eine andere Rolle.
        self._mode = ""

        #: Zustände laufender Vorgänge.
        self._source: source_criticism.SourceAnalysis | None = None
        self._debate: debate_engine.DebateSession | None = None
        self._project: Project | None = None
        self._workshop: dict[str, str] = {}

        #: Wie oft der Benutzer an derselben Stelle schon versucht hat, selbst
        #: weiterzukommen. Steuert, wann Hilfe angebracht ist.
        self._attempts = 0
        self._last_question = ""

    # --- Aufgabenbearbeitung --------------------------------------------------

    async def handle(self, task: AgentTask) -> AgentResult:
        """Bearbeitet einen Gesprächszug als Professor."""

        text = task.text.strip()

        # Versuche zählen: Wiederholt sich die Frage, ist der Benutzer noch
        # an derselben Stelle und kommt nicht weiter.
        if self._similar_to_last(text):
            self._attempts += 1
        else:
            self._attempts = 0
        self._last_question = text

        self._prepare_state(text)

        turn = professor_engine.build_prompt(
            text,
            profile=self.profile,
            project=self._project,
            source=self._source,
            debate=self._debate,
            workshop=self._workshop if self._mode == "forschungsfrage" else None,
            attempts=self._attempts,
            presence=task.metadata.get("presence") if task.metadata else None,
            current_mode=self._mode,
        )

        self._mode = turn.mode

        messages = [ChatMessage(role="system", content=turn.system_prompt)]
        if task.context:
            messages.append(ChatMessage(role="system", content=task.context))
        messages.append(ChatMessage(role="user", content=text))

        try:
            response = await self._providers.chat(messages)
        except ProviderError as error:
            return AgentResult(
                agent=self.name,
                success=False,
                error=str(error),
                response="",
                confidence="niedrig",
            )

        self._after_turn(text, turn, response.text)

        return AgentResult(
            agent=self.name,
            response=response.text,
            data={
                "provider": response.provider,
                "model": response.model,
                "professor": turn.to_dict(),
                "niveau": self.profile.level,
            },
        )

    # --- Zustandspflege --------------------------------------------------------

    def _similar_to_last(self, text: str) -> bool:
        """Ob im Kern dasselbe noch einmal gefragt wird.

        Absichtlich grob über die Wortmenge. Wer dieselbe Frage anders
        formuliert, ist immer noch an derselben Stelle – und genau darum
        geht es: Nach zwei Anläufen ist eine weitere Gegenfrage keine
        Anregung mehr.
        """

        if not self._last_question or not text:
            return False

        alt = set(self._last_question.lower().split())
        neu = set(text.lower().split())
        if not alt or not neu:
            return False

        gemeinsam = len(alt & neu)
        return gemeinsam / max(len(alt), len(neu)) > 0.55

    def _prepare_state(self, text: str) -> None:
        """Legt an, was der erkannte Modus braucht."""

        mode, _ = professor_engine.detect_mode(text, current=self._mode)
        lowered = text.lower()

        if mode == "quellenkritik" and self._source is None:
            self._source = source_criticism.SourceAnalysis(description=text[:200])

        elif mode == "debatte" and self._debate is None:
            self._debate = debate_engine.DebateSession(
                topic=professor_engine.extract_topic(text) or "offen",
                user_position=text[:300],
            )

        elif mode == "arbeitsbetreuung" and self._project is None:
            vorhanden = self.mentor.list_projects()
            name = vorhanden[0] if vorhanden else f"Arbeit: {professor_engine.extract_topic(text) or 'unbenannt'}"
            self._project = self.mentor.create(name)

        # Ein ausdrücklicher Abbruch beendet jeden laufenden Vorgang.
        if any(wort in lowered for wort in ("abbrechen", "beenden", "aufhören", "aufhoeren", "stopp")):
            self._reset_state()

    def _reset_state(self) -> None:
        """Beendet alle laufenden Vorgänge."""


        self._source = None
        self._debate = None
        self._workshop = {}
        self._mode = ""
        logger.info("Laufende Vorgänge beendet.")

    def _after_turn(self, text: str, turn: professor_engine.ProfessorTurn, answer: str) -> None:
        """Schreibt fort, was sich aus diesem Zug ergibt."""

        topic = professor_engine.extract_topic(text)

        if turn.mode == "debatte" and self._debate is not None:
            self._debate.rounds.append(debate_engine.DebateRound(user_argument=text, counter=answer))

        elif turn.mode == "forschungsfrage":
            step = research_question_engine.next_workshop_step(self._workshop)
            if step is not None:
                # Die Antwort auf den vorigen Schritt festhalten. Beim ersten
                # Zug gibt es noch keine – dann passiert hier nichts.
                erledigt = [k for k, _ in research_question_engine.WORKSHOP_STEPS
                            if self._workshop.get(k, "").strip()]
                if erledigt or len(text) > 20:
                    self._workshop[step[0]] = text

        elif turn.mode == "arbeitsbetreuung" and self._project is not None:
            self.mentor.save(self._project)

        # Themenkontakt vermerken. Die Beherrschung wird hier neutral
        # angesetzt: Was der Benutzer wirklich kann, zeigt die Arbeit,
        # nicht ein Gespräch.
        if topic:
            self.profile.record_topic(topic, 0.5)
            self.profile.save()

    # --- Auskunft ---------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        """Woran gerade gearbeitet wird – für die Transparenzansicht."""

        return {
            "modus": self._mode or "—",
            "profil": self.profile.summary(),
            "quellenanalyse": self._source.to_dict() if self._source else None,
            "projekt": self._project.name if self._project else None,
            "werkstatt": research_question_engine.workshop_progress(self._workshop)
            if self._workshop
            else None,
            "projekte": self.mentor.list_projects(),
        }
