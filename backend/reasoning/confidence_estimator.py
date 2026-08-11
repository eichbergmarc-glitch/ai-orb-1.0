"""Confidence Estimator – interne Sicherheitsbewertung.

Der Orb berechnet vor jeder Antwort eine interne Sicherheit. Diese wird dem
Benutzer **niemals als Prozentwert** angezeigt, sondern ausschließlich als
Kategorie: hoch, mittel oder niedrig.

Ist die Sicherheit niedrig, wird die Unsicherheit klar kommuniziert. Es
werden in keinem Fall Fakten erfunden.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.cognitive.reasoning_context import ReasoningContext
from backend.orchestrator.intent_classifier import IntentResult


@dataclass
class ConfidenceResult:
    """Die ermittelte Sicherheit inklusive Begründung."""

    level: str = "mittel"
    reasons: list[str] = field(default_factory=list)
    #: Interner Zahlenwert, ausschließlich für Logging und Vergleiche.
    _score: float = 0.5

    @property
    def is_low(self) -> bool:
        """Ob die Sicherheit niedrig ist."""

        return self.level == "niedrig"

    def to_dict(self) -> dict[str, Any]:
        """Serialisiert die Bewertung – ohne den internen Zahlenwert."""

        return {"level": self.level, "reasons": self.reasons}

    def notice(self) -> str:
        """Formuliert einen Hinweis für den Benutzer, falls nötig."""

        if self.level == "niedrig":
            return (
                "Ich bin mir hier nicht sicher. Bitte prüfe diese Angaben nach, "
                "bevor du dich darauf verlässt."
            )
        if self.level == "mittel":
            return "Einzelne Angaben solltest du gegebenenfalls nachprüfen."
        return ""


class ConfidenceEstimator:
    """Berechnet die interne Sicherheit einer Antwort."""

    def estimate(
        self,
        *,
        intent: IntentResult | None = None,
        context: ReasoningContext | None = None,
        memory_hits: int = 0,
        sources: int = 0,
        provider_available: bool = True,
        contradictions: int = 0,
    ) -> ConfidenceResult:
        """Bewertet die Sicherheit einer geplanten Antwort.

        Args:
            intent: Ergebnis der Intent-Klassifikation.
            context: Der Reasoning Context mit Fakten und Unsicherheiten.
            memory_hits: Anzahl passender Gedächtniseinträge.
            sources: Anzahl belegter Quellen.
            provider_available: Ob ein Sprachmodell erreichbar war.
            contradictions: Anzahl erkannter Widersprüche.

        Returns:
            Die Sicherheitskategorie mit Begründungen.
        """

        score = 0.5
        reasons: list[str] = []

        if intent is not None:
            if intent.confidence == "hoch":
                score += 0.15
                reasons.append("Die Absicht der Anfrage war eindeutig erkennbar.")
            elif intent.confidence == "niedrig":
                score -= 0.20
                reasons.append("Die Absicht der Anfrage war nicht eindeutig.")

        if memory_hits > 0:
            score += min(0.15, memory_hits * 0.05)
            reasons.append(f"Es liegen {memory_hits} passende Einträge im Gedächtnis vor.")

        if sources > 0:
            score += min(0.20, sources * 0.07)
            reasons.append(f"Die Aussage ist durch {sources} Quelle(n) gestützt.")
        else:
            score -= 0.05

        if context is not None:
            if context.has_uncertainty():
                uncertain = len(context.uncertain)
                score -= min(0.25, uncertain * 0.08)
                reasons.append(
                    f"{uncertain} der herangezogenen Informationen sind Annahmen "
                    "oder Vermutungen."
                )
            if context.facts:
                score += min(0.10, len(context.facts) * 0.03)

        if contradictions > 0:
            score -= min(0.30, contradictions * 0.15)
            reasons.append(f"Es wurden {contradictions} widersprüchliche Angaben gefunden.")

        if not provider_available:
            score -= 0.10
            reasons.append("Es war kein Sprachmodell erreichbar; die Antwort ist eingeschränkt.")

        score = max(0.0, min(1.0, score))

        if score >= 0.70:
            level = "hoch"
        elif score >= 0.45:
            level = "mittel"
        else:
            level = "niedrig"

        return ConfidenceResult(level=level, reasons=reasons, _score=score)
