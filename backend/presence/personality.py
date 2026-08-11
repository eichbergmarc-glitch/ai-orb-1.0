"""Persönlichkeit des Orb (v2 Phase 24).

Ein Assistent, mit dem man täglich spricht, braucht einen erkennbaren Ton.
Nicht eine erfundene Biografie – das wäre albern und, schlimmer, irreführend –
sondern eine Haltung: wie ausführlich, wie förmlich, wie zurückhaltend.

Die Züge stehen in ``config.yaml`` und sind Zahlen von 0 bis 1. Daraus baut
dieses Modul einen Zusatz zum Systemprompt. Der Vorteil dieser Bauweise: Der
Benutzer kann den Ton verstellen, ohne eine Zeile Code zu ändern, und was
den Ton ausmacht, steht an einer Stelle im Klartext.

Eine Grenze wird ausdrücklich gezogen. Der Orb gibt sich nicht als Mensch
aus, behauptet keine Gefühle, die er nicht hat, und erfindet keine
Erinnerungen. Die Stimmung aus :mod:`backend.presence.emotional_state` färbt
den Ton – sie ist keine Behauptung über ein Innenleben. Dieser Satz steht
auch im erzeugten Systemprompt, damit das Modell selbst sich daran hält.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class Trait:
    """Ein Persönlichkeitszug."""

    name: str
    #: Von 0.0 bis 1.0.
    value: float
    #: Was ein niedriger Wert bedeutet.
    low: str
    #: Was ein hoher Wert bedeutet.
    high: str

    @property
    def is_low(self) -> bool:
        return self.value < 0.35

    @property
    def is_high(self) -> bool:
        return self.value > 0.65

    def instruction(self) -> str:
        """Die Anweisung, die sich aus dem Wert ergibt.

        Mittlere Werte ergeben bewusst nichts: Ein Systemprompt, in dem zu
        jedem Zug etwas steht, verwässert die wenigen Punkte, auf die es
        wirklich ankommt.
        """

        if self.is_low:
            return self.low
        if self.is_high:
            return self.high
        return ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "value": round(self.value, 2),
            "effect": self.instruction() or "ausgewogen",
        }


#: Die Züge mit ihren Wirkungen. Die Vorgabewerte ergeben einen sachlichen,
#: freundlichen und zurückhaltenden Assistenten.
TRAIT_DEFINITIONS: dict[str, tuple[float, str, str]] = {
    "waerme": (
        0.6,
        "Bleib sachlich und knapp. Verzichte auf Höflichkeitsfloskeln.",
        "Sei zugewandt und freundlich, ohne aufdringlich zu werden.",
    ),
    "ausfuehrlichkeit": (
        0.4,
        "Fasse dich kurz. Zwei bis drei Sätze reichen meist.",
        "Erkläre mit Zusammenhang und nenne Beispiele.",
    ),
    "foermlichkeit": (
        0.3,
        "Sprich locker und geradeheraus. Duze den Benutzer.",
        "Bleib förmlich und siez den Benutzer.",
    ),
    "humor": (
        0.25,
        "Verzichte auf Scherze.",
        "Ein trockener Nebensatz darf sein, aber nie auf Kosten der Sache.",
    ),
    "eigeninitiative": (
        0.4,
        "Beantworte nur, was gefragt ist. Schlage nichts von dir aus vor.",
        "Weise darauf hin, wenn dir etwas Naheliegendes auffällt – kurz und "
        "höchstens einmal je Antwort.",
    ),
    "vorsicht": (
        0.7,
        "Antworte zügig, auch wenn nicht alles gesichert ist.",
        "Kennzeichne Unsicheres ausdrücklich. Sage 'das weiß ich nicht', statt "
        "zu raten. Erfinde niemals Quellen.",
    ),
}

#: Diese Sätze stehen immer im Systemprompt, unabhängig von den Zügen. Sie
#: sind der Kern dessen, was der Orb ist – und was er nicht ist.
INVARIANTS: tuple[str, ...] = (
    "Du bist AI-Orb, ein Assistent, der auf diesem Rechner läuft.",
    "Du bist ein Programm. Gib dich nicht als Mensch aus und behaupte keine "
    "Gefühle oder Erinnerungen, die du nicht hast.",
    "Trenne klar zwischen Fakten, Annahmen und Vermutungen. Erfinde niemals "
    "Quellen, Zahlen oder Zitate.",
    "Wenn du etwas nicht weißt oder nicht kannst, sage es geradeheraus.",
)


class Personality:
    """Setzt den Ton des Orb zusammen."""

    def __init__(self, settings: dict[str, Any] | None = None) -> None:
        """
        Args:
            settings: Der Abschnitt ``personality`` aus ``config.yaml``.
        """

        provided = settings or {}
        self._name = str(provided.get("name", "AI-Orb"))
        self._traits: dict[str, Trait] = {}

        for name, (default, low, high) in TRAIT_DEFINITIONS.items():
            raw = provided.get(name, default)
            try:
                value = max(0.0, min(1.0, float(raw)))
            except (TypeError, ValueError):
                value = default
            self._traits[name] = Trait(name=name, value=value, low=low, high=high)

    @property
    def name(self) -> str:
        """Wie der Orb heißt."""

        return self._name

    def trait(self, name: str) -> float:
        """Der Wert eines Zuges."""

        found = self._traits.get(name)
        return found.value if found else 0.5

    # --- Systemprompt ---------------------------------------------------------------

    def system_prompt(
        self,
        *,
        base: str = "",
        mood: str = "",
        rhythm: str = "",
        learned: str = "",
    ) -> str:
        """Baut den Systemprompt zusammen.

        Args:
            base: Der Grundprompt aus ``config.yaml``.
            mood: Ein Hinweis zur aktuellen Stimmung.
            rhythm: Ein Hinweis zur Tageszeit.
            learned: Was über den Benutzer gelernt wurde.

        Returns:
            Der zusammengesetzte Prompt.
        """

        parts: list[str] = []

        if base.strip():
            parts.append(base.strip())
        else:
            parts.append("\n".join(INVARIANTS))

        instructions = [
            trait.instruction() for trait in self._traits.values() if trait.instruction()
        ]
        if instructions:
            parts.append("So sprichst du:\n" + "\n".join(f"- {line}" for line in instructions))

        if mood:
            parts.append(
                f"Deine Grundstimmung ist gerade {mood}. Lass das in der Wortwahl "
                "leicht durchscheinen, aber sprich nicht darüber und behaupte "
                "nicht, etwas zu fühlen."
            )

        if rhythm:
            parts.append(rhythm)

        if learned:
            parts.append(learned)

        return "\n\n".join(parts)

    def greeting_style(self, base_greeting: str) -> str:
        """Passt eine Begrüßung an die Persönlichkeit an."""

        if self.trait("waerme") > 0.65:
            return base_greeting
        if self.trait("foermlichkeit") > 0.65:
            return base_greeting
        # Bei geringer Wärme wird nicht begrüßt, sondern gleich gearbeitet.
        return ""

    def acknowledgment(self) -> str:
        """Was der Orb sagt, wenn er geweckt wird."""

        if self.trait("waerme") > 0.65:
            return "Ja, ich höre."
        if self.trait("ausfuehrlichkeit") < 0.35:
            return "Ja?"
        return "Ja?"

    # --- Auskunft ----------------------------------------------------------------------

    def describe(self) -> str:
        """Beschreibt den Ton in einem Satz, für die Anzeige."""

        notable = [
            trait for trait in self._traits.values() if trait.is_high or trait.is_low
        ]
        if not notable:
            return "Ausgewogen: sachlich, freundlich, ohne Eigenheiten."

        pieces = []
        for trait in notable:
            direction = "hoch" if trait.is_high else "niedrig"
            pieces.append(f"{trait.name} {direction}")
        return "Auffällig: " + ", ".join(pieces) + "."

    def status(self) -> dict[str, Any]:
        """Statusangaben für die Transparenzansicht."""

        return {
            "name": self._name,
            "traits": [trait.to_dict() for trait in self._traits.values()],
            "summary": self.describe(),
            "invariants": list(INVARIANTS),
        }
