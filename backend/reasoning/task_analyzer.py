"""Task Analyzer – erstellt vor jeder Aufgabe ein Task Profile.

Analysiert werden Art, Komplexität, Dringlichkeit, Risiko, benötigte
Informationen, benötigte Module und der erwartete Zeitaufwand.

Die Analyse arbeitet vollständig lokal und ist damit auch offline
verfügbar.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from backend.orchestrator import intent_classifier as intents
from backend.orchestrator.intent_classifier import IntentResult
from backend.utils.text import tokenize

#: Begriffe, die auf Dringlichkeit hindeuten.
_URGENCY_MARKERS: tuple[str, ...] = (
    "sofort",
    "dringend",
    "schnell",
    "eilig",
    "jetzt",
    "asap",
    "heute noch",
    "deadline",
    "frist",
)

#: Begriffe, die auf hohes Risiko hindeuten.
_RISK_MARKERS: tuple[str, ...] = (
    "lösche",
    "löschen",
    "entferne",
    "formatiere",
    "überschreibe",
    "beende",
    "kill",
    "deinstalliere",
    "zurücksetzen",
    "reset",
)

#: Begriffe, die auf hohe Komplexität hindeuten.
_COMPLEXITY_MARKERS: tuple[str, ...] = (
    "hausarbeit",
    "projekt",
    "architektur",
    "konzept",
    "strategie",
    "vergleiche",
    "analysiere",
    "entwickle",
    "plane",
    "recherchiere",
    "implementiere",
)


@dataclass
class TaskProfile:
    """Das Ergebnis der Aufgabenanalyse."""

    text: str
    kind: str = "frage"
    complexity: str = "einfach"
    urgency: str = "normal"
    risk: str = "gering"
    required_information: list[str] = field(default_factory=list)
    required_modules: list[str] = field(default_factory=list)
    estimated_seconds: float = 5.0
    needs_plan: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "kind": self.kind,
            "complexity": self.complexity,
            "urgency": self.urgency,
            "risk": self.risk,
            "required_information": self.required_information,
            "required_modules": self.required_modules,
            "estimated_seconds": self.estimated_seconds,
            "needs_plan": self.needs_plan,
        }


class TaskAnalyzer:
    """Erstellt Task Profiles für eingehende Aufgaben."""

    def analyze(self, text: str, intent: IntentResult) -> TaskProfile:
        """Analysiert eine Aufgabe vollständig.

        Args:
            text: Die Benutzereingabe.
            intent: Das Ergebnis der Intent-Klassifikation.

        Returns:
            Das Task Profile.
        """

        lowered = text.lower()
        tokens = tokenize(text)
        profile = TaskProfile(text=text, kind=intent.intent)

        # --- Komplexität ---------------------------------------------------
        complexity_score = 0
        if len(tokens) > 25:
            complexity_score += 2
        elif len(tokens) > 12:
            complexity_score += 1
        if any(marker in lowered for marker in _COMPLEXITY_MARKERS):
            complexity_score += 2
        if len(re.findall(r"\?", text)) > 1:
            complexity_score += 1
        if intent.intent in (intents.RESEARCH, intents.CODING, intents.HISTORY):
            complexity_score += 1

        if complexity_score >= 4:
            profile.complexity = "komplex"
        elif complexity_score >= 2:
            profile.complexity = "mittel"
        else:
            profile.complexity = "einfach"

        # --- Dringlichkeit --------------------------------------------------
        if any(marker in lowered for marker in _URGENCY_MARKERS):
            profile.urgency = "hoch"

        # --- Risiko ----------------------------------------------------------
        if any(marker in lowered for marker in _RISK_MARKERS):
            profile.risk = "hoch"
        elif intent.intent in (intents.APP_START, intents.DESKTOP_CONTROL, intents.TERMINAL):
            profile.risk = "mittel"

        # --- Benötigte Informationen -------------------------------------------
        information: list[str] = []
        if intent.intent in (intents.RESEARCH, intents.HISTORY):
            information.append("quellen")
        if intent.intent in (intents.PROJECT, intents.TASK, intents.DOCUMENT):
            information.append("projektkontext")
        if intent.intent in (intents.APP_START, intents.APP_CLOSE, intents.FILE_SEARCH):
            information.append("systemzustand")
        if not information:
            information.append("gedächtnis")
        profile.required_information = information

        # --- Benötigte Module ---------------------------------------------------
        modules = ["cognitive"]
        if intent.requires_llm:
            modules.append("ai_provider")
        if "projektkontext" in information:
            modules.append("projects")
        if "systemzustand" in information:
            modules.append("desktop")
        if "quellen" in information:
            modules.append("research")
        modules.append("memory")
        profile.required_modules = modules

        # --- Zeitaufwand ---------------------------------------------------------
        base = {"einfach": 3.0, "mittel": 12.0, "komplex": 45.0}[profile.complexity]
        if intent.requires_llm:
            base *= 2.0
        profile.estimated_seconds = round(base, 1)

        # --- Planbedarf -----------------------------------------------------------
        profile.needs_plan = profile.complexity != "einfach"

        return profile
