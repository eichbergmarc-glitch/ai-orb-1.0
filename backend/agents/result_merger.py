"""Result Merger – führt Agentenergebnisse zu einer Antwort zusammen.

Aufgaben:

* Konflikte erkennen
* doppelte Informationen entfernen
* Prioritäten setzen
* eine einheitliche Antwort erzeugen

Nach außen bleibt der Orb dadurch eine einzige Persönlichkeit, auch wenn
intern mehrere Agenten beteiligt waren.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.agents.base_agent import AgentResult
from backend.system.logging_setup import get_logger
from backend.utils.text import cosine_similarity

logger = get_logger(__name__)

#: Priorität der Agenten bei widersprüchlichen Aussagen. Fachagenten
#: haben Vorrang vor der allgemeinen Gesprächsstimme.
_PRIORITY: dict[str, int] = {
    "desktop": 0,
    "memory": 1,
    "history": 2,
    "research": 2,
    "coding": 2,
    "evolution": 3,
    "reasoning": 4,
    "conversation": 5,
    "vision": 3,
    "voice": 6,
}


@dataclass
class MergedAnswer:
    """Die zusammengeführte Antwort."""

    text: str = ""
    agents_used: list[str] = field(default_factory=list)
    conflicts: list[dict[str, str]] = field(default_factory=list)
    sources: list[dict[str, str]] = field(default_factory=list)
    failed_agents: list[dict[str, str]] = field(default_factory=list)
    partial: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "agents_used": self.agents_used,
            "conflicts": self.conflicts,
            "sources": self.sources,
            "failed_agents": self.failed_agents,
            "partial": self.partial,
        }


class ResultMerger:
    """Führt die Ergebnisse mehrerer Agenten zusammen."""

    #: Ab dieser Ähnlichkeit gelten zwei Aussagen als inhaltlich gleich.
    DUPLICATE_THRESHOLD = 0.80

    def merge(self, results: list[AgentResult]) -> MergedAnswer:
        """Führt Agentenergebnisse zu einer einheitlichen Antwort zusammen.

        Args:
            results: Die Ergebnisse aller beteiligten Agenten.

        Returns:
            Die zusammengeführte Antwort inklusive erkannter Konflikte.
        """

        merged = MergedAnswer()

        successful = [result for result in results if result.success and result.response.strip()]
        failed = [result for result in results if not result.success]

        merged.failed_agents = [
            {"agent": result.agent, "error": result.error or "unbekannter Fehler"}
            for result in failed
        ]
        merged.partial = bool(failed) and bool(successful)

        if not successful:
            merged.text = self._format_total_failure(failed)
            return merged

        # Nach Aufgabenreihenfolge, dann nach Agentenpriorität sortieren.
        successful.sort(
            key=lambda result: (result.order, _PRIORITY.get(result.agent, 9))
        )

        kept: list[AgentResult] = []
        for result in successful:
            duplicate_of = self._find_duplicate(result, kept)
            if duplicate_of is not None:
                # Bei inhaltsgleichen Aussagen bleibt die des höher
                # priorisierten Agenten erhalten.
                if _PRIORITY.get(result.agent, 9) < _PRIORITY.get(duplicate_of.agent, 9):
                    kept[kept.index(duplicate_of)] = result
                continue
            kept.append(result)

        merged.conflicts = self._find_conflicts(kept)
        merged.agents_used = [result.agent for result in kept]
        merged.sources = [source for result in kept for source in result.sources]

        parts = [result.response.strip() for result in kept if result.response.strip()]
        merged.text = "\n\n".join(parts)

        if merged.conflicts:
            merged.text += "\n\nHinweis: Die beteiligten Bereiche kommen zu unterschiedlichen Einschätzungen. Ich habe beide Sichtweisen aufgeführt."

        if merged.partial:
            names = ", ".join(entry["agent"] for entry in merged.failed_agents)
            merged.text += (
                f"\n\nHinweis: Der Bereich {names} konnte nicht antworten. "
                "Diese Antwort ist daher unvollständig."
            )

        if len(kept) > 1:
            logger.info("Ergebnisse von %d Agenten zusammengeführt.", len(kept))
        return merged

    # --- Hilfsfunktionen -------------------------------------------------------

    def _find_duplicate(
        self, result: AgentResult, existing: list[AgentResult]
    ) -> AgentResult | None:
        """Sucht ein inhaltlich gleichwertiges bereits vorhandenes Ergebnis."""

        for other in existing:
            if cosine_similarity(result.response, other.response) >= self.DUPLICATE_THRESHOLD:
                return other
        return None

    @staticmethod
    def _find_conflicts(results: list[AgentResult]) -> list[dict[str, str]]:
        """Erkennt widersprüchliche Aussagen zwischen Agenten.

        Als Konflikt gilt, wenn zwei Agenten zum selben Thema (hohe
        Ähnlichkeit) mit stark abweichender Sicherheit antworten oder
        einander verneinen.
        """

        conflicts: list[dict[str, str]] = []
        for index, first in enumerate(results):
            for second in results[index + 1 :]:
                similarity = cosine_similarity(first.response, second.response)
                if similarity < 0.35 or similarity >= 0.80:
                    continue

                first_negated = any(
                    word in first.response.lower() for word in ("nicht", "kein", "nie")
                )
                second_negated = any(
                    word in second.response.lower() for word in ("nicht", "kein", "nie")
                )
                if first_negated != second_negated:
                    conflicts.append(
                        {
                            "agents": f"{first.agent} / {second.agent}",
                            "detail": "Die Einschätzungen widersprechen sich.",
                        }
                    )
        return conflicts

    @staticmethod
    def _format_total_failure(failed: list[AgentResult]) -> str:
        """Formuliert eine Antwort, wenn kein Agent liefern konnte.

        Stille Fehler gibt es nicht: Der Benutzer erfährt immer, was nicht
        funktioniert hat.
        """

        if not failed:
            return "Ich konnte zu dieser Anfrage nichts beitragen."

        lines = ["Ich konnte die Anfrage nicht bearbeiten:"]
        for result in failed:
            lines.append(f"  • {result.agent}: {result.error or 'unbekannter Fehler'}")
        lines.append("Sag mir gern, ob ich es anders versuchen soll.")
        return "\n".join(lines)
