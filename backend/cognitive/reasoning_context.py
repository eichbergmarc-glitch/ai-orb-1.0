"""Reasoning Context – strikte Trennung von Wissensarten.

Der Orb trennt klar zwischen Fakten, Annahmen, Vermutungen,
Benutzerinformationen, Projektwissen und externen Informationen. Unsichere
Informationen werden entsprechend gekennzeichnet – sowohl intern als auch
in der Antwort an den Benutzer.

Diese Trennung ist besonders für wissenschaftliches Arbeiten wesentlich:
Fakten, Interpretationen, Hypothesen, Quellen, Meinungen und
Forschungskontroversen dürfen nicht vermischt werden.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: Wissensarten in absteigender Verlässlichkeit.
CERTAINTY_LEVELS: tuple[str, ...] = (
    "fakt",
    "quelle",
    "benutzerangabe",
    "projektwissen",
    "extern",
    "interpretation",
    "annahme",
    "hypothese",
    "vermutung",
    "meinung",
    "kontrovers",
)

#: Kennzeichnung, die dem Benutzer gegenüber verwendet wird.
_LABELS: dict[str, str] = {
    "fakt": "gesichert",
    "quelle": "belegt durch Quelle",
    "benutzerangabe": "von dir angegeben",
    "projektwissen": "aus dem Projekt",
    "extern": "aus externer Quelle",
    "interpretation": "Interpretation",
    "annahme": "Annahme",
    "hypothese": "Hypothese",
    "vermutung": "unsicher",
    "meinung": "Meinung",
    "kontrovers": "in der Forschung umstritten",
}

#: Wissensarten, die dem Benutzer gegenüber ausdrücklich zu kennzeichnen sind.
UNCERTAIN_LEVELS: frozenset[str] = frozenset(
    {"interpretation", "annahme", "hypothese", "vermutung", "meinung", "kontrovers"}
)


@dataclass
class ContextItem:
    """Eine einzelne Information mit zugeordneter Wissensart."""

    content: str
    certainty: str = "fakt"
    source: str | None = None

    @property
    def is_uncertain(self) -> bool:
        """Ob diese Information als unsicher gekennzeichnet werden muss."""

        return self.certainty in UNCERTAIN_LEVELS

    def label(self) -> str:
        """Die dem Benutzer angezeigte Kennzeichnung."""

        return _LABELS.get(self.certainty, self.certainty)

    def to_dict(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "certainty": self.certainty,
            "label": self.label(),
            "source": self.source,
            "uncertain": self.is_uncertain,
        }


@dataclass
class ReasoningContext:
    """Sammelt alle Informationen, die in eine Antwort einfließen.

    Der Cognitive Core füllt den Kontext vor jeder Antwort; die
    Verification Engine prüft ihn anschließend auf Widersprüche.
    """

    items: list[ContextItem] = field(default_factory=list)

    def add(self, content: str, certainty: str = "fakt", source: str | None = None) -> ContextItem:
        """Nimmt eine Information mit ihrer Wissensart auf."""

        level = certainty if certainty in CERTAINTY_LEVELS else "annahme"
        item = ContextItem(content=content, certainty=level, source=source)
        self.items.append(item)
        return item

    def by_certainty(self, certainty: str) -> list[ContextItem]:
        """Alle Informationen einer bestimmten Wissensart."""

        return [item for item in self.items if item.certainty == certainty]

    @property
    def facts(self) -> list[ContextItem]:
        """Alle als gesichert eingestuften Informationen."""

        return [item for item in self.items if not item.is_uncertain]

    @property
    def uncertain(self) -> list[ContextItem]:
        """Alle unsicheren Informationen."""

        return [item for item in self.items if item.is_uncertain]

    def has_uncertainty(self) -> bool:
        """Ob überhaupt unsichere Informationen enthalten sind."""

        return bool(self.uncertain)

    def to_prompt(self) -> str:
        """Formt den Kontext in einen Text für die Modellanfrage um.

        Die Wissensarten bleiben dabei explizit erhalten, damit das Modell
        die Trennung in seiner Antwort übernehmen kann.
        """

        if not self.items:
            return ""

        lines = ["Verfügbare Informationen (nach Verlässlichkeit gekennzeichnet):"]
        for item in self.items:
            source = f" (Quelle: {item.source})" if item.source else ""
            lines.append(f"- [{item.label()}] {item.content}{source}")

        if self.has_uncertainty():
            lines.append(
                "Kennzeichne unsichere Aussagen in deiner Antwort ausdrücklich "
                "und trenne Fakten klar von Interpretationen und Hypothesen."
            )
        return "\n".join(lines)

    def uncertainty_notice(self) -> str:
        """Formuliert einen Hinweis auf enthaltene Unsicherheiten."""

        uncertain = self.uncertain
        if not uncertain:
            return ""
        kinds = sorted({item.label() for item in uncertain})
        return "Hinweis: Teile dieser Antwort beruhen auf " + ", ".join(kinds) + "."

    def to_dict(self) -> dict[str, Any]:
        """Serialisiert den Kontext für die Transparenzansicht."""

        return {
            "items": [item.to_dict() for item in self.items],
            "fact_count": len(self.facts),
            "uncertain_count": len(self.uncertain),
        }

    def clear(self) -> None:
        """Leert den Kontext."""

        self.items.clear()
