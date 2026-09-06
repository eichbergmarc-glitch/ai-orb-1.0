"""Cognitive Orchestrator – die Aufgabenverteilung des Cognitive Core.

Nicht zu verwechseln mit :mod:`backend.orchestrator.orchestrator` (v2): Der
dortige Orchestrator entscheidet über Intent und Provider. Dieser
kognitive Orchestrator arbeitet eine Ebene darüber und verteilt Aufgaben an
die passenden Fach-Engines:

* Geschichtsfrage → History Engine
* Code schreiben → Coding Engine
* Browser öffnen → Desktop Engine
* Recherchieren → Research Engine
* Mehrere Aufgaben → mehrere Engines parallel, Ergebnisse zusammenführen

Der kognitive Orchestrator ruft keine Fachmodule direkt auf; er benennt
lediglich die Zuständigkeiten. Die tatsächliche Ausführung übernimmt das
Agenten-System (:mod:`backend.agents`), das über das Cognitive Core
angesteuert wird.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from backend.orchestrator import intent_classifier as intents
from backend.orchestrator.intent_classifier import IntentResult
from backend.studium.vorlesungs_session import ist_vorlesungssegment
from backend.system.logging_setup import get_logger

logger = get_logger(__name__)

#: Zuordnung von Intent zu zuständiger Engine bzw. zuständigem Agenten.
ENGINE_FOR_INTENT: dict[str, str] = {
    intents.HISTORY: "history",
    intents.CODING: "coding",
    intents.RESEARCH: "research",
    intents.APP_START: "desktop",
    intents.APP_CLOSE: "desktop",
    intents.TERMINAL: "desktop",
    intents.BROWSER: "desktop",
    intents.DESKTOP_CONTROL: "desktop",
    intents.FILE_SEARCH: "desktop",
    intents.SYSTEM_STATUS: "desktop",
    intents.PROJECT: "memory",
    intents.TASK: "memory",
    intents.DOCUMENT: "research",
    intents.PLUGIN: "evolution",
    intents.TRANSPARENCY: "conversation",
    intents.QUESTION: "conversation",
    intents.CHAT: "conversation",
    intents.SMALL_TALK: "conversation",
}

#: Trennwörter, an denen mehrteilige Anfragen zerlegt werden.
_SPLIT_PATTERN = re.compile(
    r"\s+(?:und danach|und dann|danach|anschließend|außerdem|sowie|und)\s+", re.IGNORECASE
)


@dataclass
class SubTask:
    """Eine Teilaufgabe innerhalb einer zusammengesetzten Anfrage."""

    text: str
    engine: str
    order: int = 0
    parallel_safe: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "engine": self.engine,
            "order": self.order,
            "parallel_safe": self.parallel_safe,
        }


@dataclass
class Distribution:
    """Das Ergebnis der Aufgabenverteilung."""

    subtasks: list[SubTask] = field(default_factory=list)
    engines: list[str] = field(default_factory=list)
    parallel: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "subtasks": [task.to_dict() for task in self.subtasks],
            "engines": self.engines,
            "parallel": self.parallel,
        }


class CognitiveOrchestrator:
    """Verteilt Aufgaben auf die zuständigen Engines."""

    def __init__(self, classifier: Any) -> None:
        """
        Args:
            classifier: Der Intent-Klassifikator, mit dem Teilaufgaben
                eingeordnet werden.
        """

        self._classifier = classifier

    def distribute(self, text: str, primary_intent: IntentResult | None = None) -> Distribution:
        """Zerlegt eine Anfrage und ordnet Teilaufgaben Engines zu.

        Args:
            text: Die Benutzereingabe.
            primary_intent: Bereits ermitteltes Hauptintent, falls
                vorhanden (spart eine erneute Klassifikation).

        Returns:
            Die Verteilung inklusive Angabe, ob parallel gearbeitet werden
            kann.
        """

        # Regieanweisungen eines laufenden Vortrags enthalten viele Bindewoerter
        # und Imperative. Sie sind trotzdem genau EINE inhaltliche Aufgabe.
        # Ohne diese Schranke wurden Teile wie "beende den Abschnitt" als
        # Desktop-Auftrag verteilt und loesten statt des Vortrags eine
        # Sicherheitsbestaetigung aus.
        if ist_vorlesungssegment(text):
            return Distribution(
                subtasks=[
                    SubTask(
                        text=text.strip(),
                        engine="conversation",
                        order=0,
                        parallel_safe=True,
                    )
                ],
                engines=["conversation"],
                parallel=False,
            )

        parts = [part.strip() for part in _SPLIT_PATTERN.split(text) if part.strip()]

        # Sehr kurze Fragmente sind meist keine eigenständigen Aufgaben.
        parts = [part for part in parts if len(part.split()) >= 2] or [text.strip()]

        subtasks: list[SubTask] = []
        for order, part in enumerate(parts):
            if len(parts) == 1 and primary_intent is not None:
                intent = primary_intent
            else:
                intent = self._classifier.classify(part)

            engine = ENGINE_FOR_INTENT.get(intent.intent, "conversation")
            # Desktop-Aktionen dürfen nicht beliebig parallel laufen, da sie
            # den Systemzustand verändern.
            parallel_safe = engine != "desktop"
            subtasks.append(
                SubTask(text=part, engine=engine, order=order, parallel_safe=parallel_safe)
            )

        engines: list[str] = []
        for task in subtasks:
            if task.engine not in engines:
                engines.append(task.engine)

        parallel = len(subtasks) > 1 and all(task.parallel_safe for task in subtasks)

        if len(subtasks) > 1:
            logger.info(
                "Anfrage in %d Teilaufgaben zerlegt (%s, parallel=%s).",
                len(subtasks),
                ", ".join(engines),
                parallel,
            )

        return Distribution(subtasks=subtasks, engines=engines, parallel=parallel)

    @staticmethod
    def merge_results(results: list[dict[str, Any]]) -> str:
        """Führt die Ergebnisse mehrerer Engines zu einer Antwort zusammen.

        Doppelte Inhalte werden entfernt und die Reihenfolge der
        Teilaufgaben bleibt erhalten. Die eigentliche Konfliktauflösung
        übernimmt der Result Merger des Agenten-Systems; diese Funktion
        liefert die einfache Zusammenführung für den Fall, dass kein
        Agenten-Team beteiligt war.
        """

        seen: set[str] = set()
        parts: list[str] = []
        for result in sorted(results, key=lambda item: int(item.get("order", 0))):
            text = str(result.get("response", "")).strip()
            if not text:
                continue
            normalized = text.lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            parts.append(text)
        return "\n\n".join(parts)
