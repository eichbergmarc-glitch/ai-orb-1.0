"""Reasoning Engine – der Denkvorgang vor jeder Antwort.

Der Orb antwortet nicht sofort. Vor jeder Antwort durchläuft er:

Analyse → Strategiewahl → Planung → Entscheidung → Sicherheitsbewertung →
Ausführung → Prüfung → Nachbetrachtung

Einfache Aufgaben werden dabei bewusst nicht verkompliziert: Plan und
Verifikation entfallen, wenn das Task Profile sie nicht rechtfertigt.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from backend.cognitive.planner import Plan
from backend.cognitive.reasoning_context import ReasoningContext
from backend.cognitive.reflection_engine import ReflectionEngine
from backend.config import get_config
from backend.orchestrator.intent_classifier import IntentResult
from backend.reasoning.confidence_estimator import ConfidenceEstimator, ConfidenceResult
from backend.reasoning.decision_tree import DecisionTree, TreeDecision
from backend.reasoning.execution_manager import ExecutionManager
from backend.reasoning.plan_generator import PlanGenerator
from backend.reasoning.reflection_manager import ReflectionManager
from backend.reasoning.strategy_selector import StrategySelection, StrategySelector
from backend.reasoning.task_analyzer import TaskAnalyzer, TaskProfile
from backend.reasoning.verification_engine import VerificationEngine, VerificationReport
from backend.system.logging_setup import get_logger

logger = get_logger(__name__)


@dataclass
class ReasoningResult:
    """Das vollständige Ergebnis eines Denkvorgangs."""

    task_id: str
    profile: TaskProfile
    strategy: StrategySelection
    decision: TreeDecision
    confidence: ConfidenceResult
    plan: Plan | None = None
    verification: VerificationReport | None = None
    context: ReasoningContext = field(default_factory=ReasoningContext)
    duration_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "profile": self.profile.to_dict(),
            "strategy": self.strategy.to_dict(),
            "decision": self.decision.to_dict(),
            "confidence": self.confidence.to_dict(),
            "plan": self.plan.to_dict() if self.plan else None,
            "verification": self.verification.to_dict() if self.verification else None,
            "context": self.context.to_dict(),
            "duration_seconds": round(self.duration_seconds, 3),
        }

    def user_notices(self) -> list[str]:
        """Alle Hinweise, die dem Benutzer mitgeteilt werden sollten."""

        notices: list[str] = []
        notice = self.confidence.notice()
        if notice:
            notices.append(notice)
        if self.context.has_uncertainty():
            notices.append(self.context.uncertainty_notice())
        if self.verification and self.verification.contradictions:
            notices.append(
                "Achtung: Ich habe widersprüchliche Angaben gefunden – "
                "bitte prüfe diese Stelle besonders sorgfältig."
            )
        return [notice for notice in notices if notice]


class ReasoningEngine:
    """Führt den vollständigen Denkvorgang für eine Aufgabe aus."""

    def __init__(self, reflection_engine: ReflectionEngine) -> None:
        config = get_config()
        reasoning_config = config.section("reasoning")

        self.analyzer = TaskAnalyzer()
        self.strategies = StrategySelector(reflection_engine)
        self.plans = PlanGenerator()
        self.tree = DecisionTree()
        self.confidence = ConfidenceEstimator()
        self.verification = VerificationEngine()
        self.execution = ExecutionManager()
        self.reflection = ReflectionManager(reflection_engine)

        self._communicate_uncertainty = bool(
            reasoning_config.get("communicate_uncertainty", True)
        )
        self._confirm_risky = bool(reasoning_config.get("confirm_risky_actions", True))

    # --- Vorbereitung (vor der Antwort) ---------------------------------------

    def prepare(
        self,
        text: str,
        intent: IntentResult,
        *,
        context: ReasoningContext | None = None,
        has_project: bool = False,
        has_image: bool = False,
        internet_available: bool = True,
        provider_available: bool = True,
        memory_hits: int = 0,
    ) -> ReasoningResult:
        """Führt den Denkvorgang vor der Antwort aus.

        Args:
            text: Die Benutzereingabe.
            intent: Ergebnis der Intent-Klassifikation.
            context: Bereits gesammelter Reasoning Context.
            has_project: Ob ein Projekt aktiv ist.
            has_image: Ob ein Bild vorliegt.
            internet_available: Ob eine Recherche möglich ist.
            provider_available: Ob ein Sprachmodell erreichbar ist.
            memory_hits: Anzahl passender Gedächtniseinträge.

        Returns:
            Das Ergebnis mit Profil, Strategie, Plan, Entscheidung und
            Sicherheitsbewertung.
        """

        started = time.perf_counter()
        task_id = uuid.uuid4().hex
        reasoning_context = context or ReasoningContext()

        # 1. Aufgabe analysieren.
        profile = self.analyzer.analyze(text, intent)

        # 2. Strategie wählen.
        strategy = self.strategies.select(
            profile,
            has_project=has_project,
            has_image=has_image,
            internet_available=internet_available,
        )

        # 3. Plan erstellen (nur wenn die Komplexität es rechtfertigt).
        plan = self.plans.generate(profile, strategy) if self.plans.should_plan(profile) else None

        # 4. Sicherheit bewerten.
        if self._is_non_factual(profile):
            # Begrüßungen und Plauderei enthalten keine überprüfbaren
            # Sachaussagen; ein Unsicherheitshinweis wäre hier irreführend.
            confidence = ConfidenceResult(
                level="hoch",
                reasons=["Die Anfrage enthält keine überprüfbaren Sachaussagen."],
                _score=1.0,
            )
        else:
            confidence = self.confidence.estimate(
                intent=intent,
                context=reasoning_context,
                memory_hits=memory_hits,
                sources=len([item for item in reasoning_context.items if item.source]),
                provider_available=provider_available,
            )

        # 5. Entscheidung treffen.
        sufficient = memory_hits > 0 or provider_available or profile.kind != "unbekannt"
        decision = self.tree.evaluate(
            profile,
            confidence,
            has_sufficient_information=sufficient,
            internet_available=internet_available,
        )
        if not self._confirm_risky and decision.action == "bestätigung_verlangen":
            decision.action = "antworten"

        # 6. Nachbetrachtung vorbereiten.
        self.reflection.begin(task_id, profile, strategy)

        result = ReasoningResult(
            task_id=task_id,
            profile=profile,
            strategy=strategy,
            decision=decision,
            confidence=confidence,
            plan=plan,
            context=reasoning_context,
            duration_seconds=time.perf_counter() - started,
        )

        logger.info(
            "Denkvorgang abgeschlossen: %s / %s / Sicherheit %s",
            profile.complexity,
            strategy.primary,
            confidence.level,
        )
        return result

    @staticmethod
    def _is_non_factual(profile: TaskProfile) -> bool:
        """Ob die Aufgabe keine überprüfbaren Sachaussagen enthält.

        Für Begrüßungen, Plauderei und reine Desktop-Aktionen ist eine
        Unsicherheitsbewertung nicht sinnvoll.
        """

        from backend.orchestrator import intent_classifier as intent_names

        return profile.complexity == "einfach" and profile.kind in (
            intent_names.SMALL_TALK,
            intent_names.CHAT,
            intent_names.APP_START,
            intent_names.APP_CLOSE,
            intent_names.TERMINAL,
            intent_names.BROWSER,
            intent_names.SYSTEM_STATUS,
            intent_names.TRANSPARENCY,
        )

    # --- Nachbereitung (nach der Antwort) --------------------------------------

    def verify_answer(
        self, result: ReasoningResult, answer: str, *, require_sources: bool = False
    ) -> VerificationReport:
        """Prüft eine erzeugte Antwort auf Konsistenz und Belegbarkeit."""

        report = self.verification.verify(
            result.context,
            answer=answer,
            require_sources=require_sources or "quellen" in result.profile.required_information,
        )
        result.verification = report

        if report.contradictions:
            trace = self.reflection.trace(result.task_id)
            if trace is not None:
                trace.note_error(
                    f"{len(report.contradictions)} Widerspruch/Widersprüche in den Quellen"
                )
        return report

    def finish(self, result: ReasoningResult, *, successful: bool = True) -> None:
        """Schließt die Bearbeitung ab und stößt die Nachbetrachtung an."""

        self.reflection.finish(result.task_id, successful=successful, profile=result.profile)

    def note_error(self, result: ReasoningResult, message: str) -> None:
        """Vermerkt einen Fehler während der Bearbeitung."""

        trace = self.reflection.trace(result.task_id)
        if trace is not None:
            trace.note_error(message)

    # --- Transparenz ---------------------------------------------------------------

    def explain(self, result: ReasoningResult) -> dict[str, Any]:
        """Erklärt den Denkvorgang verständlich.

        Es werden ausschließlich nachvollziehbare Schritte offengelegt –
        keine internen Gedankengänge und keine vertraulichen Ableitungen.
        """

        explanation: dict[str, Any] = {
            "aufgabenart": result.profile.kind,
            "komplexität": result.profile.complexity,
            "dringlichkeit": result.profile.urgency,
            "risiko": result.profile.risk,
            "gewählte_strategie": result.strategy.primary,
            "begründung_strategie": result.strategy.reason,
            "entscheidung": result.decision.action,
            "begründung_entscheidung": self.tree.explain(result.decision),
            "sicherheit": result.confidence.level,
            "beteiligte_module": result.profile.required_modules,
        }
        if result.plan is not None:
            explanation["plan"] = [step.title for step in result.plan.steps]
        if result.verification is not None:
            explanation["quellen"] = result.verification.sources
            explanation["widersprüche"] = len(result.verification.contradictions)
        if self._communicate_uncertainty:
            explanation["hinweise"] = result.user_notices()
        return explanation
