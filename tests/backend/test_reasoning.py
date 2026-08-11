"""Tests für Reasoning, Entscheidungen und Verifikation."""

from __future__ import annotations

import pytest

from backend.cognitive.reasoning_context import ReasoningContext
from backend.orchestrator.intent_classifier import IntentClassifier
from backend.reasoning.confidence_estimator import ConfidenceEstimator
from backend.reasoning.decision_tree import ANSWER, ASK_BACK, CONFIRM, DecisionTree
from backend.reasoning.task_analyzer import TaskAnalyzer
from backend.reasoning.verification_engine import VerificationEngine


@pytest.fixture()
def classifier() -> IntentClassifier:
    return IntentClassifier()


@pytest.fixture()
def analyzer() -> TaskAnalyzer:
    return TaskAnalyzer()


def test_simple_task_is_not_overcomplicated(classifier, analyzer):
    """Einfache Aufgaben dürfen keinen aufwendigen Plan auslösen."""

    intent = classifier.classify("Hallo")
    profile = analyzer.analyze("Hallo", intent)

    assert profile.complexity == "einfach"
    assert profile.needs_plan is False


def test_complex_task_requires_plan(classifier, analyzer):
    text = "Analysiere die Forschungskontroverse zum Investiturstreit und entwickle eine Fragestellung für meine Hausarbeit"
    intent = classifier.classify(text)
    profile = analyzer.analyze(text, intent)

    assert profile.complexity in ("mittel", "komplex")
    assert profile.needs_plan is True


def test_risky_task_is_detected(classifier, analyzer):
    text = "Lösche alle Dateien im Downloads-Ordner"
    profile = analyzer.analyze(text, classifier.classify(text))

    assert profile.risk == "hoch"


def test_urgency_is_detected(classifier, analyzer):
    text = "Ich brauche das dringend bis heute Abend"
    profile = analyzer.analyze(text, classifier.classify(text))

    assert profile.urgency == "hoch"


def test_decision_tree_requires_confirmation_for_risk(classifier, analyzer):
    text = "Lösche das gesamte Verzeichnis"
    profile = analyzer.analyze(text, classifier.classify(text))
    confidence = ConfidenceEstimator().estimate(memory_hits=3, sources=2)

    decision = DecisionTree().evaluate(profile, confidence)

    assert decision.action == CONFIRM
    assert decision.question


def test_decision_tree_asks_back_without_information(classifier, analyzer):
    text = "Mach das"
    profile = analyzer.analyze(text, classifier.classify(text))
    confidence = ConfidenceEstimator().estimate()

    decision = DecisionTree().evaluate(profile, confidence, has_sufficient_information=False)

    assert decision.action == ASK_BACK


def test_decision_tree_answers_when_confident(classifier, analyzer):
    text = "Erkläre mir kurz den Unterschied zwischen Quelle und Darstellung"
    profile = analyzer.analyze(text, classifier.classify(text))
    confidence = ConfidenceEstimator().estimate(memory_hits=5, sources=3)

    decision = DecisionTree().evaluate(profile, confidence)

    assert decision.action == ANSWER


def test_confidence_drops_with_uncertainty():
    context = ReasoningContext()
    context.add("Das ist gesichert.", "fakt")
    context.add("Das ist nur eine Vermutung.", "vermutung")
    context.add("Auch das ist unsicher.", "hypothese")

    result = ConfidenceEstimator().estimate(context=context, provider_available=False)

    assert result.level in ("niedrig", "mittel")
    assert result.reasons


def test_confidence_is_never_a_percentage():
    """Die Sicherheit darf niemals als Prozentwert nach außen gelangen."""

    result = ConfidenceEstimator().estimate(memory_hits=2)
    serialized = result.to_dict()

    assert set(serialized.keys()) == {"level", "reasons"}
    assert result.level in ("hoch", "mittel", "niedrig")


def test_verification_detects_negation_contradiction():
    context = ReasoningContext()
    context.add("Der Investiturstreit endete mit dem Wormser Konkordat.", "fakt")
    context.add("Der Investiturstreit endete nicht mit dem Wormser Konkordat.", "fakt")

    report = VerificationEngine().verify(context)

    assert report.consistent is False
    assert report.contradictions


def test_verification_reports_sources():
    context = ReasoningContext()
    context.add("Eine belegte Aussage.", "quelle", source="https://example.org/quelle")

    report = VerificationEngine().verify(context)

    assert report.sources
    assert report.sources[0]["url"] == "https://example.org/quelle"


def test_reasoning_context_marks_uncertainty():
    context = ReasoningContext()
    context.add("Gesichert", "fakt")
    context.add("Angenommen", "annahme")

    assert context.has_uncertainty() is True
    assert "Annahme" in context.uncertainty_notice()
    assert len(context.facts) == 1
