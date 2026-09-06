"""Cognitive Core – das zentrale Gehirn von AI-Orb.

Alle Module kommunizieren ausschließlich über das Cognitive Core. Direkte
Kommunikation zwischen Fachmodulen findet nicht statt.

Das Cognitive Core entscheidet:

* welche Informationen relevant sind,
* welche Module beteiligt werden,
* welcher Kontext aktiv ist,
* welches KI-Modell verwendet wird,
* welche Aktionen geplant werden.

Der Orb arbeitet dadurch nicht wie ein Chatbot, sondern wie ein
strukturierter Assistent: Er verwaltet Projekte, Aufgaben, Ziele, Kontexte
und Wissen getrennt voneinander und begründet seine Entscheidungen
nachvollziehbar.

Alle Module arbeiten asynchron; die Oberfläche wird niemals blockiert.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from backend.cognitive.context_manager import ContextManager
from backend.cognitive.decision_engine import Decision, DecisionEngine
from backend.cognitive.goal_manager import GoalManager
from backend.cognitive.long_term_memory import LongTermMemory
from backend.cognitive.orchestrator import CognitiveOrchestrator, Distribution
from backend.cognitive.planner import Planner
from backend.cognitive.project_manager import ProjectManager
from backend.cognitive.reasoning_context import ReasoningContext
from backend.cognitive.reflection_engine import ReflectionEngine
from backend.cognitive.task_manager import TaskManager
from backend.cognitive.working_memory import WorkingMemory
from backend.config import get_config
from backend.events.event_bus import EventBus
from backend.memory.memory_engine import MemoryEngine
from backend.orchestrator import intent_classifier as intent_names
from backend.orchestrator.intent_classifier import IntentResult
from backend.orchestrator.orchestrator import Orchestrator
from backend.orchestrator.provider_manager import ProviderManager
from backend.projects.project_engine import ProjectEngine
from backend.reasoning.reasoning_engine import ReasoningEngine, ReasoningResult
from backend.system.logging_setup import get_logger
from backend.studium.vorlesungs_session import ist_vorlesungssegment

logger = get_logger(__name__)


def kognitiver_prueftext(text: str) -> str:
    """Entfernt technische Regie aus der Risikoanalyse einer Vorlesung.

    Der vollstaendige interne Auftrag muss spaeter beim Sprachmodell ankommen.
    Fuer die vorgeschaltete Aktions- und Risikoanalyse ist er jedoch der
    falsche Text: Wo dort etwa ``beende nur diesen Abschnitt`` steht, erkannte
    der allgemeine Aufgabenanalysator eine irreversible Systemaktion. Der
    neutrale Prueftext beschreibt dieselbe kognitive Aufgabe ohne Imperative.
    """

    if ist_vorlesungssegment(text):
        return "Inhaltliche Fortsetzung einer laufenden gesprochenen Vorlesung."
    return text


@dataclass
class CognitiveResponse:
    """Die vollständige Antwort des Cognitive Core."""

    response: str
    intent: str = ""
    used_llm: bool = False
    provider: str | None = None
    model: str | None = None
    confidence: str = "mittel"
    strategy: str = ""
    requires_confirmation: bool = False
    question: str = ""
    notices: list[str] = field(default_factory=list)
    engines: list[str] = field(default_factory=list)
    project_id: str | None = None
    duration_seconds: float = 0.0
    #: Ob die Antwort im Fluss bereits gesprochen wurde.
    #:
    #: Der Orb spricht jeden fertigen Satz, waehrend er den Rest noch
    #: denkt. Ohne diesen Vermerk laese die Sprachschicht die vollstaendige
    #: Antwort danach ein zweites Mal vor.
    already_spoken: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "response": self.response,
            "intent": self.intent,
            "used_llm": self.used_llm,
            "provider": self.provider,
            "model": self.model,
            "confidence": self.confidence,
            "strategy": self.strategy,
            "requires_confirmation": self.requires_confirmation,
            "question": self.question,
            "notices": self.notices,
            "engines": self.engines,
            "project_id": self.project_id,
            "duration_seconds": round(self.duration_seconds, 3),
        }


class CognitiveCore:
    """Das zentrale Gehirn, über das alle Module kommunizieren."""

    def __init__(
        self,
        *,
        memory: MemoryEngine,
        provider_manager: ProviderManager,
        orchestrator: Orchestrator,
        event_bus: EventBus | None = None,
        preferences: Any | None = None,
    ) -> None:
        config = get_config()
        cognitive_config = config.section("cognitive")

        self._event_bus = event_bus
        self._memory = memory
        #: Das Themenwissen. Wird nachgereicht (siehe attach_topics).
        self._topics: Any | None = None
        self._providers = provider_manager
        self._orchestrator = orchestrator

        # Der Professor als Blickwinkel auf den Hauptweg.
        #
        # Er ersetzt den Antwortweg nicht, er färbt ihn: Bei einem
        # wissenschaftlichen oder historischen Anliegen liefert er den
        # Systemprompt, mit dem gedacht wird. Alles Übrige – Werkzeuge,
        # Gedächtnis, Gesprächsverlauf – bleibt unberührt. Vorher war er
        # vollständig gebaut, wurde aber nie gefragt.
        from backend.agents.history_agent.bridge import ProfessorSession

        self.professor = ProfessorSession()

        # Gedächtnisebenen.
        self.working_memory = WorkingMemory(
            ttl_seconds=float(cognitive_config.get("working_memory_ttl", 3600)),
            max_items_per_slot=int(cognitive_config.get("working_memory_max_items", 50)),
        )
        self.long_term_memory = LongTermMemory(memory)

        # Was der Orb ueber den Benutzer gelernt hat.
        #
        # Das gab es schon: Der Lerner beobachtete jede Unterhaltung, und
        # das Langzeitgedaechtnis kennt die Kategorien "vorliebe" und
        # "gewohnheit" seit Anfang an. Nur kam beides beim Denken nie an -
        # der Orb merkte sich also Vorlieben und ging dann nicht darauf
        # ein. Gelernt zu haben und nichts damit zu tun ist schlimmer als
        # nicht gelernt zu haben: Es sieht von aussen wie Gleichgueltigkeit
        # aus.
        # Ausdrücklich der ÜBERGEBENE Lerner und kein eigener.
        #
        # Kurzzeitig standen hier zwei: einer in der Laufzeitschicht, der
        # beobachtete, und einer hier, der las. Beide luden ihre Datei beim
        # Erzeugen und arbeiteten danach im Arbeitsspeicher – der lesende
        # sah also nie, was der schreibende in dieser Sitzung gelernt
        # hatte. Erst nach einem Neustart wäre etwas angekommen. Zwei
        # Instanzen desselben Gedächtnisses sind kein Gedächtnis.
        from backend.learning.preference_learner import PreferenceLearner

        self.preferences = preferences if preferences is not None else PreferenceLearner()

        # Kontexte, Ziele, Aufgaben, Projekte.
        self.contexts = ContextManager()
        self.goals = GoalManager()
        self.tasks = TaskManager(memory)
        self.project_engine = ProjectEngine(memory, self.tasks)
        self.projects = ProjectManager(self.project_engine)

        # Denken, Entscheiden, Planen, Reflektieren.
        self.reflection = ReflectionEngine(memory)
        self.reasoning = ReasoningEngine(self.reflection)
        self.decisions = DecisionEngine()
        self.planner = Planner()
        self.cognitive_orchestrator = CognitiveOrchestrator(orchestrator.classifier)

        #: Der zuletzt durchgeführte Denkvorgang (für die Transparenzansicht).
        self._last_reasoning: ReasoningResult | None = None
        self._last_decision: Decision | None = None
        self._last_distribution: Distribution | None = None

        self._register_transparency_handlers()
        logger.info("Cognitive Core initialisiert.")

    # --- Hauptablauf --------------------------------------------------------

    async def process(
        self,
        text: str,
        *,
        spoken: bool = False,
        on_speech: Callable[[str], Awaitable[bool]] | None = None,
    ) -> CognitiveResponse:
        """Verarbeitet eine Benutzereingabe vollständig.

        Ablauf: Kontext bestimmen → Absicht erkennen → entscheiden →
        denken (analysieren, Strategie wählen, planen) → ausführen →
        prüfen → reflektieren.

        Args:
            text: Die Benutzereingabe.

        Returns:
            Die Antwort inklusive aller nachvollziehbaren Zusatzangaben.
        """

        started = time.perf_counter()
        self.working_memory.append("conversation", {"role": "user", "text": text})

        # Tagebuchbefehle sind Datentransaktionen, keine Denkaufgaben. Der
        # Wortlaut eines Diktats darf weder zerlegt noch zusammengefasst oder
        # von einem Provider neu formuliert werden. Dieser Schnellweg fuehrt
        # direkt zum lokalen Orchestrator und seinen Tagebuchwerkzeugen.
        from backend.orchestrator.orchestrator import parse_tagebuch_befehl

        tagebuch_befehl = parse_tagebuch_befehl(text)
        tagebuch_fortsetzung = bool(
            getattr(self._orchestrator, "_tagebuch_diktat_ausstehend", False)
        )
        if (
            tagebuch_fortsetzung
            or (
                tagebuch_befehl is not None
                and tagebuch_befehl.werkzeug != "tagebuch_aenderung_start"
            )
        ):
            result = await self._orchestrator.handle(
                text, spoken=spoken, on_speech=on_speech
            )
            self.working_memory.append(
                "conversation", {"role": "assistant", "text": result.response}
            )
            response = CognitiveResponse(
                response=result.response,
                intent=result.intent or "tagebuch",
                used_llm=False,
                provider=result.provider,
                model=result.model,
                engines=["tagebuch"],
                duration_seconds=time.perf_counter() - started,
                already_spoken=bool((result.data or {}).get("gesprochen")),
            )
            await self._publish("cognitive.response", response.to_dict())
            return response

        project_id = self.projects.active_id()
        if project_id:
            active_project = self.project_engine.active_project() or {}
            self.contexts.set(
                "projekt",
                str(active_project.get("name") or project_id),
                {"project_id": project_id},
            )

        # 1. Absicht erkennen.
        #
        # Ein Vorlesungsabschnitt ist ein interner Modellauftrag, keine neue
        # Benutzeraktion. Seine Regieanweisung enthaelt zwangsläufig Woerter
        # wie "beende", "rufe auf" oder "ausfuehren". Der allgemeine
        # Klassifikator hielt das zeitweise fuer eine riskante Desktop-Aktion
        # und beantwortete den Vortrag mit einer Sicherheitsrueckfrage. Der
        # automatische Folgezeitgeber wiederholte diese Rueckfrage anschliessend
        # immer wieder. Interne Vorlesungssegmente werden deshalb vor jeder
        # heuristischen Klassifikation eindeutig als inhaltliche Antwort
        # gekennzeichnet.
        vorlesungssegment = ist_vorlesungssegment(text)
        prueftext = kognitiver_prueftext(text)
        if vorlesungssegment:
            intent = IntentResult(
                intent=intent_names.QUESTION,
                confidence="hoch",
                score=1.0,
                requires_llm=True,
                matched_keywords=["interner_vorlesungsabschnitt"],
            )
        else:
            intent = self._orchestrator.classifier.classify(text)

        # 2. Aufgabenverteilung bestimmen.
        distribution = self.cognitive_orchestrator.distribute(text, intent)
        self._last_distribution = distribution

        # 3. Vorentscheidung treffen.
        provider_available = self._providers.active_provider is not None
        decision = self.decisions.decide(
            prueftext,
            intent,
            has_context=bool(project_id),
            provider_available=provider_available,
        )
        self._last_decision = decision

        if decision.needs_clarification:
            response = CognitiveResponse(
                response=decision.clarification_question,
                intent=intent.intent,
                question=decision.clarification_question,
                engines=distribution.engines,
                project_id=project_id,
                duration_seconds=time.perf_counter() - started,
            )
            await self._publish("cognitive.clarification", response.to_dict())
            return response

        # 4. Reasoning Context aufbauen.
        context = self._build_reasoning_context(text, project_id)

        # 5. Denken.
        reasoning = self.reasoning.prepare(
            prueftext,
            intent,
            context=context,
            has_project=bool(project_id),
            internet_available=decision.needs_internet is False or provider_available,
            provider_available=provider_available,
            memory_hits=len(context.items),
        )
        self._last_reasoning = reasoning

        if (
            reasoning.decision.action == "bestätigung_verlangen"
            and not vorlesungssegment
        ):
            response = CognitiveResponse(
                response=reasoning.decision.question,
                intent=intent.intent,
                confidence=reasoning.confidence.level,
                strategy=reasoning.strategy.primary,
                requires_confirmation=True,
                question=reasoning.decision.question,
                engines=distribution.engines,
                project_id=project_id,
                duration_seconds=time.perf_counter() - started,
            )
            await self._publish("cognitive.confirmation_required", response.to_dict())
            self.reasoning.finish(reasoning, successful=True)
            return response

        # 6. Ausführen (über den v2-Orchestrator, der Modul oder Modell wählt).
        extra_context = self._compose_extra_context(context)

        # Den Professor fragen, ob er übernimmt. Tut er es, steht sein
        # Systemprompt VOR dem übrigen Kontext – er bestimmt die Haltung,
        # der Rest liefert die Einzelheiten.
        professor_prompt = self.professor.prompt_for(text)
        professor_status = self.professor.status()
        await self._publish(
            "orb.professor.changed",
            {
                "active": bool(professor_prompt),
                "mode": (
                    str(professor_status.get("modus", ""))
                    if professor_prompt
                    else ""
                ),
            },
        )
        if professor_prompt:
            extra_context = "\n\n".join(
                part for part in (professor_prompt, extra_context) if part
            )

        result = await self._orchestrator.handle(
            text,
            project_id=project_id,
            extra_context=extra_context,
            spoken=spoken,
            on_speech=on_speech,
        )

        if professor_prompt:
            # Lernen: Themenkontakt, Prüfungsstand, Debattenverlauf.
            self.professor.after_turn(text, result.response)

        if not result.used_llm and not result.response:
            self.reasoning.note_error(reasoning, "Keine Antwort erzeugt.")

        # 7. Prüfen.
        verification = self.reasoning.verify_answer(reasoning, result.response)

        # 8. Reflektieren.
        self.reasoning.finish(reasoning, successful=bool(result.response))

        notices = reasoning.user_notices()
        if verification.notes:
            notices.extend(verification.notes)

        self.working_memory.append(
            "conversation", {"role": "assistant", "text": result.response}
        )

        # Wann gearbeitet wird, gehört ins Benutzergedächtnis.
        #
        # Das war der zweite Fund der Durchsicht: Die Klasse war fertig,
        # zwei Prompt-Abschnitte lasen daraus – und geschrieben hat sie nie
        # jemand. Beide Abschnitte blieben deshalb dauerhaft leer. Die
        # Uhrzeit ist die einfachste Angabe, die sich von selbst ergibt:
        # Wer über Wochen morgens fragt, arbeitet morgens.
        try:
            self._memory.user.record_activity(int(time.strftime("%H")))
        except Exception:  # noqa: BLE001 - eine Notiz darf nie eine Antwort kosten.
            logger.debug("Die Aktivität ließ sich nicht vermerken.", exc_info=True)

        # Aus dem Austausch lernen – hier und nicht in der Sprachschicht.
        #
        # Vorher geschah das nur auf dem gesprochenen Weg. Der getippte
        # lernte nichts, und weil dabei fest „per Sprache" vermerkt wurde,
        # konnte der Orb gar nicht anders, als jeden Benutzer für einen
        # reinen Sprachbenutzer zu halten.
        try:
            self.preferences.observe_interaction(
                question=text,
                answer=result.response,
                via_voice=spoken,
                topics=[intent.intent] if intent.intent else None,
            )
        except Exception:  # noqa: BLE001 - Lernen darf nie eine Antwort kosten.
            logger.debug("Der Austausch ließ sich nicht auswerten.", exc_info=True)

        response = CognitiveResponse(
            response=result.response,
            intent=result.intent,
            used_llm=result.used_llm,
            provider=result.provider,
            model=result.model,
            confidence=reasoning.confidence.level,
            strategy=reasoning.strategy.primary,
            requires_confirmation=result.requires_confirmation,
            notices=[notice for notice in notices if notice],
            engines=distribution.engines,
            project_id=project_id,
            duration_seconds=time.perf_counter() - started,
            # Wurde im Fluss schon gesprochen, darf die Sprachschicht die
            # Antwort nicht ein zweites Mal vorlesen.
            already_spoken=bool((result.data or {}).get("gesprochen")),
        )
        await self._publish("cognitive.response", response.to_dict())
        return response

    def attach_topics(self, speicher: Any) -> None:
        """Reicht das Themenwissen nach.

        Nachgereicht und nicht im Konstruktor uebergeben, weil der
        Themenspeicher spaeter entsteht - er haengt am Provider, der zum
        Zeitpunkt dieser Schicht noch nicht steht. Ein Anschluss, den man
        vergisst, ist der haeufigste Weg, wie eine fertig gebaute
        Faehigkeit unerreichbar bleibt; deshalb steht er hier und nicht in
        einer Aufrufreihe irgendwo.
        """

        self._topics = speicher

    # --- Kontextaufbau ------------------------------------------------------

    def _build_reasoning_context(self, text: str, project_id: str | None) -> ReasoningContext:
        """Sammelt alle relevanten Informationen mit ihrer Wissensart."""

        context = ReasoningContext()

        for result in self._memory.recall(text, limit=5, project_id=project_id):
            record = result.record
            certainty = str(record.metadata.get("certainty", "fakt"))
            context.add(record.content, certainty, source=record.metadata.get("source"))

        for fact in self._memory.user.top_facts(limit=4):
            context.add(str(fact.get("text", "")), "benutzerangabe")

        # Das Themenwissen.
        #
        # Die Erinnerungssuche oben findet zwar auch Gelerntes, aber nur
        # ueber Wortgleichheit und vermischt mit allem anderen. Wer sich in
        # ein Gebiet eingearbeitet hat, soll bei einer Frage aus diesem
        # Gebiet SEIN Wissen dazu vor sich haben - zusammenhaengend und
        # als solches erkennbar, nicht als fuenf zufaellige Treffer.
        #
        # Gelernt zu haben und im Gespraech nicht darauf zu kommen, sieht
        # von aussen wie Gleichgueltigkeit aus.
        if self._topics is not None:
            try:
                for thema in self._topics.passend(text, limit=2):
                    kurz = thema.kurz()
                    if kurz:
                        context.add(kurz, "eingearbeitet")
            except Exception:  # noqa: BLE001 - fehlendes Wissen darf keine
                # Antwort verhindern.
                logger.debug("Das Themenwissen war nicht abrufbar.", exc_info=True)

        if project_id:
            project_context = self.project_engine.context_for(project_id)
            if project_context is not None:
                context.add(project_context.to_prompt(), "projektwissen")

        return context

    def _compose_extra_context(self, context: ReasoningContext) -> str:
        """Fügt Reasoning Context, Kontexte und Gelerntes zu einem Prompt zusammen."""

        parts = [context.to_prompt(), self.contexts.summary_text()]
        goal = self.goals.current_focus(self.projects.active_id())
        if goal:
            parts.append(f"Aktuelles Ziel des Benutzers: {goal['title']}")

        # Was über den Benutzer bekannt ist, geht mit – sonst wäre das
        # Lernen folgenlos.
        parts.append(self.preferences.guidance())
        parts.append(self._gemerktes())

        return "\n".join(part for part in parts if part)

    def _gemerktes(self) -> str:
        """Die gemerkten Vorlieben und Gewohnheiten als Prompt-Abschnitt.

        Bewusst knapp gehalten und begrenzt: Ein Systemprompt, der mit
        jeder Woche länger wird, verwässert irgendwann alles andere darin.
        Die jüngsten Einträge stehen zuletzt und wiegen damit am
        schwersten – wer seine Meinung ändert, soll nicht von seiner
        früheren überstimmt werden.
        """

        zeilen: list[str] = []
        for kategorie, ueberschrift in (
            ("vorliebe", "Vorlieben"),
            ("gewohnheit", "Gewohnheiten"),
        ):
            try:
                eintraege = self.long_term_memory.by_category(kategorie)
            except Exception:  # noqa: BLE001 - Gedächtnis darf nie den Weg blockieren.
                continue
            texte = [
                str(eintrag.content).strip()
                for eintrag in eintraege[-8:]
                if str(eintrag.content).strip()
            ]
            if texte:
                zeilen.append(f"{ueberschrift} des Benutzers:")
                zeilen.extend(f"- {text}" for text in texte)

        if not zeilen:
            return ""

        return (
            "\n".join(zeilen)
            + "\nRichte dich danach, ohne es eigens zu erwähnen."
        )

    # --- Transparenz --------------------------------------------------------

    @staticmethod
    def _auskunft_konfidenz(text: str, intent: Any) -> float:
        """Wie sicher eine rein auskunftgebende Zuordnung sein darf.

        Die Frage ist nicht, ob das Schlüsselwort im Satz steht - das steht
        es, sonst wäre der Handler nicht aufgerufen worden. Die Frage ist,
        ob der Satz daneben noch etwas verlangt, das dieses Modul gar nicht
        leisten kann. Ist das so, ist die Zuordnung schwach, und der Router
        reicht sie weiter.
        """

        from backend.orchestrator.faehigkeiten import entscheiden

        entscheidung = entscheiden(text, gesprochen=False, werkzeuge_vorhanden=True)
        if entscheidung.handlungsauftrag:
            # Bewusst deutlich unter der Rueckfallschwelle: Hier verlangt
            # jemand eine Handlung, und eine Statistik ist keine.
            return 0.15
        basis = float(getattr(intent, "score", 0.0) or 0.0)
        return min(1.0, max(0.6, basis))

    def _register_transparency_handlers(self) -> None:
        """Registriert die lokalen Antworten auf Transparenzfragen.

        Damit werden Fragen wie "Woran arbeite ich gerade?" oder "Warum hast
        du dieses Modell gewählt?" ohne Sprachmodell beantwortet.
        """

        async def handle_transparency(text: str, intent: Any) -> Any:
            from backend.orchestrator.task_router import RouteResult

            return RouteResult(
                handled_locally=True,
                response=self.answer_transparency_question(text),
                module="transparenz",
                konfidenz=self._auskunft_konfidenz(text, intent),
                rueckfall_erlaubt=True,
            )

        self._orchestrator.router.register(intent_names.TRANSPARENCY, handle_transparency)

        async def handle_project(text: str, intent: Any) -> Any:
            from backend.orchestrator.task_router import RouteResult

            return RouteResult(
                handled_locally=True,
                response=self.projects.summary_text(),
                module="projects",
                konfidenz=self._auskunft_konfidenz(text, intent),
                rueckfall_erlaubt=True,
            )

        self._orchestrator.router.register(intent_names.PROJECT, handle_project)

        #: Wendungen, mit denen wirklich nach der Aufgabenliste gefragt
        #: wird. Sie sind bewusst KEIN Tor mehr, sondern nur noch das
        #: Fachwissen dieses einen Handlers ueber seine eigene Zustaendigkeit:
        #: Sie erhoehen die Konfidenz, sie entscheiden nichts.
        liste_gemeint = (
            "welche aufgabe", "welche aufgaben", "meine aufgaben",
            "offene aufgabe", "offene aufgaben", "aufgabenliste",
            "aufgaben liste", "todo", "to-do", "was steht an",
            "was ist offen", "wie viele aufgaben", "stand der aufgaben",
            "naechster schritt", "nächster schritt", "erledigt",
        )

        async def handle_task(text: str, intent: Any) -> Any:
            from backend.orchestrator.task_router import RouteResult

            # Das Wort "Aufgabe" in einem Satz bedeutet nicht, dass die
            # Aufgabenliste gemeint ist.
            #
            # Am 31.08.2026 lautete der Satz: "Ich wiederhole die AUFGABE,
            # suche nach einer Wohnung maximal 1100 Fr. in der Region
            # Solothurn und zeige mir die Ergebnisse im Browser an." Ein
            # einziges Wort machte daraus den Intent 'aufgabe', der Router
            # beantwortete ihn lokal - und der Benutzer bekam die Statistik
            # seiner Aufgabenliste vorgelesen: "Aufgaben insgesamt: 0".
            # Kein Modell, kein Werkzeug, keine Suche, kein Browser.
            #
            # Dieser Handler entscheidet das jetzt nicht mehr selbst. Er
            # sagt nur noch, wie sicher er sich ist; ueber den Rueckfall
            # entscheidet der Router an einer Stelle fuer alle Module.
            gesagt = " ".join(str(text or "").lower().split())
            nach_liste_gefragt = any(wendung in gesagt for wendung in liste_gemeint)

            overview = self.tasks.overview(self.projects.active_id())
            lines = [
                f"Aufgaben insgesamt: {overview['total']}",
                "  offen: {offen}, in Bearbeitung: {in_bearbeitung}, "
                "blockiert: {blockiert}, erledigt: {erledigt}".format(**overview["by_status"]),
            ]
            if overview.get("next_step"):
                lines.append(f"Nächster Schritt: {overview['next_step']}")
            for blocked in overview.get("blocked", []):
                lines.append(f"Blockiert: {blocked['title']} – {blocked['reason'] or 'ohne Angabe'}")
            return RouteResult(
                handled_locally=True,
                response="\n".join(lines),
                module="tasks",
                konfidenz=(
                    0.95
                    if nach_liste_gefragt
                    else self._auskunft_konfidenz(text, intent)
                ),
                rueckfall_erlaubt=True,
                begruendung=(
                    "es wurde ausdruecklich nach der Aufgabenliste gefragt"
                    if nach_liste_gefragt
                    else "das Wort 'Aufgabe' allein belegt nicht, dass die Liste gemeint ist"
                ),
            )

        self._orchestrator.router.register(intent_names.TASK, handle_task)

    def answer_transparency_question(self, text: str) -> str:
        """Beantwortet eine Transparenzfrage nachvollziehbar.

        Erklärt werden ausschließlich nachvollziehbare Abläufe – keine
        internen Gedankengänge und keine vertraulichen Ableitungen.
        """

        lowered = text.lower()

        if "woran arbeite" in lowered or "projekt" in lowered:
            return self.projects.summary_text()

        if "kontext" in lowered:
            contexts = self.contexts.describe()
            active = [
                f"{kind}: {data['name']}" for kind, data in contexts.items() if data
            ]
            return "Aktive Kontexte – " + ("; ".join(active) if active else "keine")

        if "ziel" in lowered:
            overview = self.goals.overview()
            if not overview["active"]:
                return "Es sind derzeit keine aktiven Ziele hinterlegt."
            lines = ["Aktive Ziele:"]
            lines.extend(
                f"  • {goal['title']} ({goal['horizon']}, "
                f"{int(float(goal['progress']) * 100)} % erreicht)"
                for goal in overview["active"][:8]
            )
            return "\n".join(lines)

        if "modell" in lowered or "provider" in lowered or "ki" in lowered:
            status = self._providers.status()
            health = status["health"].get(str(status["active"]), {})
            reason = (
                "Er ist erreichbar und als primärer Provider konfiguriert."
                if status["active"] == status["primary"]
                else "Der primäre Provider war nicht erreichbar, daher nutze ich den Fallback."
            )
            return (
                f"Ich verwende aktuell „{status['active']}“ mit dem Modell "
                f"„{status['active_model']}“. {reason} "
                f"Durchschnittliche Antwortzeit: {health.get('average_latency', 0)} s."
            )

        if "aufgabe" in lowered:
            return self.tasks.suggest_next_action(self.projects.active_id())

        if "agent" in lowered or "modul" in lowered:
            if self._last_distribution is None:
                return "Bisher wurde noch keine Anfrage bearbeitet."
            engines = ", ".join(self._last_distribution.engines)
            return (
                f"Für die letzte Anfrage waren folgende Bereiche zuständig: {engines}. "
                + self.cognitive_orchestrator.merge_results([])
            ).strip()

        if "warum" in lowered or "strategie" in lowered or "entschieden" in lowered:
            if self._last_reasoning is None:
                return "Es liegt noch keine Entscheidung vor, die ich erklären könnte."
            explanation = self.reasoning.explain(self._last_reasoning)
            lines = [
                f"Aufgabenart: {explanation['aufgabenart']} "
                f"(Komplexität: {explanation['komplexität']}, Risiko: {explanation['risiko']})",
                explanation["begründung_strategie"],
                explanation["begründung_entscheidung"],
                f"Meine Sicherheit dabei: {explanation['sicherheit']}.",
            ]
            if explanation.get("plan"):
                lines.append("Geplante Schritte: " + " → ".join(explanation["plan"]))
            return "\n".join(lines)

        if "information" in lowered or "gedächtnis" in lowered:
            statistics = self._memory.statistics()
            return (
                f"Mein Gedächtnis enthält {statistics['total']} Einträge "
                f"({statistics['by_kind']}). Alles liegt ausschließlich lokal auf "
                f"deinem Rechner unter {statistics['storage_path']}."
            )

        return (
            "Ich kann dir erklären: woran du gerade arbeitest, welcher Kontext aktiv ist, "
            "welche Ziele hinterlegt sind, welches Modell ich nutze, warum ich so "
            "entschieden habe und welche Informationen ich verwende."
        )

    def status(self) -> dict[str, Any]:
        """Gesamtstatus des Cognitive Core."""

        return {
            "contexts": self.contexts.describe(),
            "goals": self.goals.overview(),
            "tasks": self.tasks.overview(self.projects.active_id()),
            "active_project": self.project_engine.active_project(),
            "working_memory": {
                slot: len(entries) for slot, entries in self.working_memory.snapshot().items()
            },
            "memory": self._memory.statistics(),
            "providers": self._providers.status(),
            "last_decision": self._last_decision.to_dict() if self._last_decision else None,
            "last_reasoning": (
                self.reasoning.explain(self._last_reasoning) if self._last_reasoning else None
            ),
        }

    async def maintenance(self) -> dict[str, Any]:
        """Führt regelmäßige Pflegearbeiten aus (Vergessen, Ablauf)."""

        expired = self.working_memory.expire()
        forgotten = self.long_term_memory.maintenance()
        return {"expired_working_items": expired, "forgotten_memories": forgotten}

    async def _publish(self, event_name: str, payload: dict[str, Any]) -> None:
        if self._event_bus is not None:
            await self._event_bus.publish(event_name, payload)
