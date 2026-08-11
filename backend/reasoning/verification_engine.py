"""Verification Engine – Prüfung vor wichtigen Antworten.

Geprüft werden interne Konsistenz, widersprüchliche Informationen und –
sofern Quellen vorliegen – deren Übereinstimmung. Wird das Internet
genutzt, werden alle Quellen nachvollziehbar dokumentiert.

Die Prüfung arbeitet lokal und benötigt kein Sprachmodell.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from backend.cognitive.reasoning_context import ContextItem, ReasoningContext
from backend.system.logging_setup import get_logger
from backend.utils.text import cosine_similarity, tokenize

logger = get_logger(__name__)

#: Gegensatzpaare, die auf einen Widerspruch hindeuten.
_OPPOSITES: tuple[tuple[str, str], ...] = (
    ("immer", "nie"),
    ("alle", "keine"),
    ("möglich", "unmöglich"),
    ("bestätigt", "widerlegt"),
    ("erfolgreich", "gescheitert"),
    ("vorhanden", "fehlt"),
    ("ja", "nein"),
)

_NEGATION_PATTERN = re.compile(r"\b(nicht|kein|keine|keinen|niemals|nie)\b", re.IGNORECASE)
_NUMBER_PATTERN = re.compile(r"\b(\d{1,4}(?:[.,]\d+)?)\b")


@dataclass
class Contradiction:
    """Ein erkannter Widerspruch zwischen zwei Aussagen."""

    first: str
    second: str
    kind: str
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "first": self.first,
            "second": self.second,
            "kind": self.kind,
            "detail": self.detail,
        }


@dataclass
class VerificationReport:
    """Das Ergebnis der Überprüfung."""

    consistent: bool = True
    contradictions: list[Contradiction] = field(default_factory=list)
    sources: list[dict[str, str]] = field(default_factory=list)
    unsupported_claims: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "consistent": self.consistent,
            "contradictions": [item.to_dict() for item in self.contradictions],
            "sources": self.sources,
            "unsupported_claims": self.unsupported_claims,
            "notes": self.notes,
        }

    def as_text(self) -> str:
        """Formuliert das Prüfergebnis für den Benutzer."""

        lines: list[str] = []
        if self.contradictions:
            lines.append("Ich habe widersprüchliche Angaben gefunden:")
            for item in self.contradictions:
                lines.append(f"  • {item.detail or item.kind}: „{item.first}“ vs. „{item.second}“")
        if self.sources:
            lines.append("Verwendete Quellen:")
            lines.extend(
                f"  • {source.get('title') or source.get('url')}" for source in self.sources
            )
        lines.extend(self.notes)
        return "\n".join(lines)


class VerificationEngine:
    """Prüft Antworten auf Konsistenz und Belegbarkeit."""

    def verify(
        self,
        context: ReasoningContext,
        *,
        answer: str = "",
        require_sources: bool = False,
    ) -> VerificationReport:
        """Prüft den Reasoning Context und optional die Antwort.

        Args:
            context: Der Kontext mit allen herangezogenen Informationen.
            answer: Die geplante Antwort (optional).
            require_sources: Ob Aussagen belegt sein müssen (z. B. bei
                wissenschaftlichen Fragen oder nach Internetnutzung).

        Returns:
            Der Prüfbericht.
        """

        report = VerificationReport()

        report.contradictions = self._find_contradictions(context.items)
        report.consistent = not report.contradictions

        report.sources = [
            {"title": item.content[:80], "url": item.source or ""}
            for item in context.items
            if item.source
        ]

        if require_sources and not report.sources:
            report.notes.append(
                "Für diese Antwort liegen mir keine belegten Quellen vor; "
                "die Angaben beruhen auf allgemeinem Wissen."
            )

        if answer:
            report.unsupported_claims = self._find_unsupported_claims(answer, context)

        if context.has_uncertainty():
            report.notes.append(context.uncertainty_notice())

        if report.contradictions:
            logger.warning(
                "Verifikation: %d Widerspruch/Widersprüche gefunden.",
                len(report.contradictions),
            )

        return report

    # --- Interne Prüfungen ----------------------------------------------------

    @staticmethod
    def _find_contradictions(items: list[ContextItem]) -> list[Contradiction]:
        """Sucht Widersprüche zwischen den vorliegenden Aussagen."""

        contradictions: list[Contradiction] = []

        for index, first in enumerate(items):
            for second in items[index + 1 :]:
                similarity = cosine_similarity(first.content, second.content)
                if similarity < 0.45:
                    continue

                first_negated = bool(_NEGATION_PATTERN.search(first.content))
                second_negated = bool(_NEGATION_PATTERN.search(second.content))
                if first_negated != second_negated:
                    contradictions.append(
                        Contradiction(
                            first=first.content,
                            second=second.content,
                            kind="negation",
                            detail="Eine Aussage verneint, was die andere bejaht",
                        )
                    )
                    continue

                first_tokens = set(tokenize(first.content, apply_stemming=False))
                second_tokens = set(tokenize(second.content, apply_stemming=False))
                for left, right in _OPPOSITES:
                    if (left in first_tokens and right in second_tokens) or (
                        right in first_tokens and left in second_tokens
                    ):
                        contradictions.append(
                            Contradiction(
                                first=first.content,
                                second=second.content,
                                kind="gegensatz",
                                detail=f"Gegensätzliche Angaben ({left}/{right})",
                            )
                        )
                        break
                else:
                    first_numbers = set(_NUMBER_PATTERN.findall(first.content))
                    second_numbers = set(_NUMBER_PATTERN.findall(second.content))
                    if (
                        first_numbers
                        and second_numbers
                        and not (first_numbers & second_numbers)
                        and similarity > 0.65
                    ):
                        contradictions.append(
                            Contradiction(
                                first=first.content,
                                second=second.content,
                                kind="zahlenabweichung",
                                detail="Abweichende Zahlenangaben zum selben Sachverhalt",
                            )
                        )

        return contradictions

    @staticmethod
    def _find_unsupported_claims(answer: str, context: ReasoningContext) -> list[str]:
        """Sucht Aussagen in der Antwort, die im Kontext keine Stütze haben.

        Es werden ausschließlich Sätze mit konkreten Zahlen- oder
        Jahresangaben geprüft, da gerade diese besonders fehleranfällig
        sind.
        """

        if not context.items:
            return []

        sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", answer) if part.strip()]
        combined = " ".join(item.content for item in context.items)
        unsupported: list[str] = []

        for sentence in sentences:
            numbers = _NUMBER_PATTERN.findall(sentence)
            if not numbers:
                continue
            if any(number in combined for number in numbers):
                continue
            if cosine_similarity(sentence, combined) < 0.2:
                unsupported.append(sentence)

        return unsupported[:5]
