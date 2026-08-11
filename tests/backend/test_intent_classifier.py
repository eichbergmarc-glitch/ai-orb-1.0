"""Tests für die Intent-Klassifikation und den Task Router."""

from __future__ import annotations

import pytest

from backend.orchestrator import intent_classifier as intents
from backend.orchestrator.intent_classifier import IntentClassifier, IntentDefinition


@pytest.fixture()
def classifier() -> IntentClassifier:
    return IntentClassifier()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Öffne Firefox", intents.APP_START),
        ("Starte das Terminal", intents.APP_START),
        ("Suche report.pdf", intents.FILE_SEARCH),
        ("Woran arbeite ich gerade?", intents.TRANSPARENCY),
        ("Warum hast du dieses Modell gewählt?", intents.TRANSPARENCY),
        ("Fasse das Dokument zusammen", intents.DOCUMENT),
        ("Erkläre mir den Investiturstreit", intents.HISTORY),
        ("Recherchiere aktuelle Quellen zum Mittelalter", intents.RESEARCH),
        ("Schreibe eine Python Funktion für Primzahlen", intents.CODING),
        ("Welche Aufgaben sind offen?", intents.TASK),
        ("Hallo", intents.SMALL_TALK),
    ],
)
def test_classification(classifier: IntentClassifier, text: str, expected: str):
    assert classifier.classify(text).intent == expected


def test_local_intents_need_no_language_model(classifier: IntentClassifier):
    """Aufgaben wie 'Firefox starten' dürfen kein Sprachmodell benötigen."""

    result = classifier.classify("Öffne Firefox")

    assert result.requires_llm is False


def test_knowledge_question_needs_language_model(classifier: IntentClassifier):
    result = classifier.classify("Wie funktioniert eine Brennstoffzelle?")

    assert result.requires_llm is True


def test_entities_are_extracted(classifier: IntentClassifier):
    result = classifier.classify("Suche bericht.pdf und öffne firefox um 14:30")

    assert "bericht.pdf" in result.entities.get("files", [])
    assert "firefox" in result.entities.get("applications", [])
    assert "14:30" in result.entities.get("times", [])


def test_low_confidence_falls_back_to_language_model(classifier: IntentClassifier):
    result = classifier.classify("hm")

    assert result.confidence == "niedrig"
    assert result.requires_llm is True


def test_new_intents_can_be_added_without_core_changes(classifier: IntentClassifier):
    """Neue Intents müssen ohne Änderung am Kern ergänzbar sein."""

    classifier.register_intent(
        IntentDefinition(
            "smarthome",
            keywords=["licht", "heizung", "rollladen"],
            requires_llm=False,
            weight=2.0,
        )
    )

    result = classifier.classify("Schalte das Licht ein")

    assert result.intent == "smarthome"
    assert "smarthome" in classifier.intents
