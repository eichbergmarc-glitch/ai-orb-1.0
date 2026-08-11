"""Decision Tree – die Entscheidungslogik vor jeder Aktion.

Der Baum bildet die vorgegebene Logik unmittelbar ab:

* Kann ich sicher antworten? → ja → antworten
* Unsicherheit → recherchieren
* Nicht genügend Informationen → Rückfrage
* Hohe Risiken → Bestätigung verlangen

Jede Entscheidung dokumentiert den durchlaufenen Pfad, damit sie
nachvollziehbar erklärt werden kann.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.reasoning.confidence_estimator import ConfidenceResult
from backend.reasoning.task_analyzer import TaskProfile

#: Die möglichen Ergebnisse des Entscheidungsbaums.
ANSWER = "antworten"
RESEARCH = "recherchieren"
ASK_BACK = "rückfrage"
CONFIRM = "bestätigung_verlangen"
DECLINE = "ablehnen"


@dataclass
class TreeDecision:
    """Das Ergebnis eines Durchlaufs durch den Entscheidungsbaum."""

    action: str = ANSWER
    question: str = ""
    path: list[str] = field(default_factory=list)
    explanation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "question": self.question,
            "path": self.path,
            "explanation": self.explanation,
        }


class DecisionTree:
    """Durchläuft den Entscheidungsbaum vor jeder Aktion."""

    def evaluate(
        self,
        profile: TaskProfile,
        confidence: ConfidenceResult,
        *,
        has_sufficient_information: bool = True,
        internet_available: bool = True,
    ) -> TreeDecision:
        """Bestimmt die nächste Handlung.

        Args:
            profile: Das Task Profile der Aufgabe.
            confidence: Die ermittelte Sicherheit.
            has_sufficient_information: Ob genügend Informationen vorliegen.
            internet_available: Ob eine Recherche überhaupt möglich ist.

        Returns:
            Die getroffene Entscheidung mit dokumentiertem Pfad.
        """

        decision = TreeDecision()

        # 1. Risiko prüfen – hat immer Vorrang.
        decision.path.append("Risiko prüfen")
        if profile.risk == "hoch":
            decision.action = CONFIRM
            decision.question = (
                "Diese Aktion kann nicht rückgängig gemacht werden. Soll ich sie wirklich ausführen?"
            )
            decision.explanation = (
                "Die Aufgabe wurde als risikoreich eingestuft, daher hole ich vorher "
                "deine Bestätigung ein."
            )
            decision.path.append("Risiko hoch → Bestätigung verlangen")
            return decision
        decision.path.append("Risiko vertretbar")

        # 2. Informationslage prüfen.
        decision.path.append("Informationslage prüfen")
        if not has_sufficient_information:
            decision.action = ASK_BACK
            decision.question = (
                "Mir fehlen noch Angaben, um das zuverlässig zu beantworten. "
                "Kannst du mir mehr Kontext geben?"
            )
            decision.explanation = (
                "Es lagen nicht genügend Informationen vor, um verlässlich zu antworten."
            )
            decision.path.append("Informationen unzureichend → Rückfrage")
            return decision
        decision.path.append("Informationen ausreichend")

        # 3. Sicherheit prüfen.
        decision.path.append("Sicherheit prüfen")
        if confidence.is_low:
            if internet_available and "quellen" in profile.required_information:
                decision.action = RESEARCH
                decision.explanation = (
                    "Meine Sicherheit war zu niedrig, daher recherchiere ich zuerst "
                    "und belege die Antwort mit Quellen."
                )
                decision.path.append("Sicherheit niedrig → recherchieren")
                return decision

            decision.action = ANSWER
            decision.explanation = (
                "Meine Sicherheit ist niedrig und eine Recherche ist gerade nicht möglich. "
                "Ich antworte mit ausdrücklichem Hinweis auf die Unsicherheit."
            )
            decision.path.append("Sicherheit niedrig, Recherche nicht möglich → mit Hinweis antworten")
            return decision

        decision.path.append("Sicherheit ausreichend")
        decision.action = ANSWER
        decision.explanation = "Die Informationslage war ausreichend, um direkt zu antworten."
        return decision

    @staticmethod
    def explain(decision: TreeDecision) -> str:
        """Formuliert den Entscheidungsweg verständlich.

        Interne Zwischenwerte bleiben dabei bewusst außen vor; erklärt wird
        ausschließlich der nachvollziehbare Ablauf.
        """

        return decision.explanation or " → ".join(decision.path)
