"""Der ModelRouter (Master-Prompt Abschnitte 13–21, 65).

Der ModelRouter entscheidet, welcher Provider eine Aufgabe bekommt. Er ist
das Stück, das die Vielzahl der Provider für den Benutzer wieder zu einer
einzigen KI macht: Der Benutzer spricht mit dem Orb, und der Orb wählt im
Hintergrund.

## Die Leitregel (Abschnitt 65)

    Lokal und kostenlos, wann immer es reicht.
    Cloud, wenn nötig.
    Claude/OpenAI für anspruchsvolles Denken.

Daraus folgt die Reihenfolge der Prüfungen, und die Reihenfolge ist nicht
beliebig:

1. **Datenschutz zuerst.** Geht es um lokale, sensible Daten, bleibt die
   Aufgabe lokal – selbst wenn ein Cloud-Modell sie besser könnte. Das ist
   die einzige Regel, die andere überstimmt, weil ihr Bruch nicht
   rückgängig zu machen ist: Was einmal an einen fremden Server ging, ist
   dort gewesen.

2. **Offline.** Ist kein Internet da, kommen nur lokale Modelle in Frage –
   nicht als Notlösung, sondern als einzige Möglichkeit.

3. **Komplexität.** Eine einfache Zusammenfassung braucht kein
   Spitzenmodell; eine historische Quellenanalyse schon.

4. **Kosten.** Unter zwei Modellen, die beide taugen, gewinnt das
   günstigere – und lokal ist gratis.

## Warum das hier steht und nicht im ProviderManager

Der ProviderManager weiß, *welche* Provider es gibt und ob sie laufen. Der
Router weiß, *welcher* für *diese* Aufgabe passt. Das eine ist Verwaltung,
das andere ist Urteil – und Urteile ändert man häufiger als Verwaltung.
Sie zu trennen erspart es, beim Anpassen der Routing-Regeln in der
Providerverwaltung zu wühlen.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from backend.system.logging_setup import get_logger

logger = get_logger(__name__)


class Mode(str, Enum):
    """Die Betriebsart des Routers (Abschnitt 56)."""

    AUTO = "auto"
    PRIVACY = "privacy"
    QUALITY = "quality"
    SPEED = "speed"
    OFFLINE = "offline"
    CHEAPEST = "cheapest"


@dataclass(slots=True)
class TaskProfile:
    """Was über eine Aufgabe bekannt ist, bevor sie bearbeitet wird.

    Der Router urteilt nur so gut, wie diese Angaben stimmen. Sie werden
    teils aus dem Text geschätzt (:func:`profile_task`), teils vom
    aufrufenden Agenten gesetzt – ein Agent, der eine Datei vom Rechner
    liest, weiß, dass es um lokale Daten geht, und sagt es.
    """

    #: 0.0 (trivial) bis 1.0 (sehr anspruchsvoll).
    complexity: float = 0.5
    #: Ob lokale, womöglich sensible Daten im Spiel sind.
    sensitive: bool = False
    #: Ob ein Bild zu verarbeiten ist.
    needs_vision: bool = False
    #: Ob es um Programmieren geht.
    needs_coding: bool = False
    #: Ob Werkzeugaufrufe nötig sind.
    needs_tools: bool = False
    #: Wie lang der Kontext ungefähr ist (Zeichen).
    context_length: int = 0
    #: Woran die Einschätzung festgemacht wurde – fürs Protokoll.
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "komplexitaet": round(self.complexity, 2),
            "sensibel": self.sensitive,
            "vision": self.needs_vision,
            "coding": self.needs_coding,
            "werkzeuge": self.needs_tools,
            "kontextlaenge": self.context_length,
            "begruendung": self.reasons,
        }


@dataclass(slots=True)
class ProviderProfile:
    """Was ein Provider fürs Routing an Eigenschaften mitbringt.

    Diese Angaben stehen in der Konfiguration bei jedem Provider und nicht
    im Code: Welches Modell wie stark ist, ändert sich – der Router soll
    davon nichts wissen müssen (Abschnitt: Modelle nicht hart codieren).
    """

    name: str
    is_local: bool = False
    requires_internet: bool = True
    #: 0.0 bis 1.0 – wie leistungsfähig im Denken.
    reasoning: float = 0.5
    #: Relative Kosten: 0.0 gratis (lokal) bis 1.0 teuer.
    cost: float = 0.5
    #: Relative Geschwindigkeit: 0.0 langsam bis 1.0 schnell.
    speed: float = 0.5
    can_vision: bool = False
    can_tools: bool = False
    context_length: int = 8000

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "lokal": self.is_local,
            "reasoning": self.reasoning,
            "kosten": self.cost,
            "tempo": self.speed,
        }


#: Vernünftige Vorgaben, falls die Konfiguration zu einem Provider nichts
#: sagt. Sie bilden die grobe Wirklichkeit von Mitte 2025 ab und sind
#: bewusst konservativ – der Router soll im Zweifel nicht das teure Modell
#: für eine Kleinigkeit wählen.
DEFAULT_PROVIDER_PROFILES: dict[str, dict[str, Any]] = {
    "claude_code": {"is_local": False, "requires_internet": True, "reasoning": 0.95,
                    "cost": 0.2, "speed": 0.6, "can_tools": True, "context_length": 200000},
    "claude": {"is_local": False, "requires_internet": True, "reasoning": 0.95,
               "cost": 0.7, "speed": 0.6, "can_vision": True, "can_tools": True,
               "context_length": 200000},
    "openai": {"is_local": False, "requires_internet": True, "reasoning": 0.9,
               "cost": 0.65, "speed": 0.7, "can_vision": True, "can_tools": True,
               "context_length": 128000},
    "ollama_cloud": {"is_local": False, "requires_internet": True, "reasoning": 0.7,
                     "cost": 0.3, "speed": 0.6, "context_length": 32000},
    "ollama": {"is_local": True, "requires_internet": False, "reasoning": 0.55,
               "cost": 0.0, "speed": 0.5, "context_length": 8000},
    "lmstudio": {"is_local": True, "requires_internet": False, "reasoning": 0.55,
                 "cost": 0.0, "speed": 0.5, "context_length": 8000},
    "llamacpp": {"is_local": True, "requires_internet": False, "reasoning": 0.5,
                 "cost": 0.0, "speed": 0.45, "context_length": 8000},
    "hermes": {"is_local": False, "requires_internet": True, "reasoning": 0.75,
               "cost": 0.5, "speed": 0.6, "context_length": 32000},
}

#: Ab dieser Komplexität gilt eine Aufgabe als anspruchsvoll und verlangt
#: ein starkes Modell.
COMPLEXITY_THRESHOLD = 0.6

#: Reasoning, das ein lokales Modell mindestens haben muss, um eine
#: mittelschwere Aufgabe zu bekommen.
LOCAL_REASONING_FLOOR = 0.5


#: Wörter, die auf eine anspruchsvolle Aufgabe deuten.
_COMPLEX_MARKERS: tuple[str, ...] = (
    "analysiere", "analyse", "vergleiche", "bewerte", "kritik", "argumentier",
    "begründe", "begruende", "entwickle", "interpretier", "historiograph",
    "forschungsfrage", "these", "quellenkritik", "synthese", "erörter",
    "eroerter", "warum", "inwiefern", "beurteile", "widerlege",
)

#: Wörter, die auf eine einfache Aufgabe deuten.
_SIMPLE_MARKERS: tuple[str, ...] = (
    "fasse zusammen", "zusammenfassung", "übersetze", "uebersetze",
    "liste", "wie spät", "wie spaet", "rechne", "wandle um", "formatier",
    "korrigiere die rechtschreibung",
)

#: Wörter, die auf lokale, sensible Daten deuten (Abschnitt 18).
_SENSITIVE_MARKERS: tuple[str, ...] = (
    "meine datei", "dieses dokument", "meine notizen", "mein tagebuch",
    "meine mail", "meine e-mail", "passwort", "vertraulich", "privat",
    "persönliche daten", "persoenliche daten", "lokale datei",
)

#: Wörter, die auf Bildverarbeitung deuten.
_VISION_MARKERS: tuple[str, ...] = (
    "bild", "screenshot", "foto", "diagramm", "sieh dir an", "auf dem bildschirm",
)

#: Wörter, die auf Programmieren deuten.
_CODING_MARKERS: tuple[str, ...] = (
    "code", "funktion", "programmier", "debug", "fehler im code", "python",
    "javascript", "refactor", "kompilier",
)


def profile_task(text: str, *, hint: dict[str, Any] | None = None) -> TaskProfile:
    """Schätzt das Profil einer Aufgabe aus ihrem Text.

    Die Schätzung ist grob und darf es sein. Wo ein Agent es besser weiß,
    übergibt er ``hint`` und überschreibt einzelne Felder – die Textanalyse
    ist der Ausgangspunkt, nicht das letzte Wort.
    """

    lowered = text.lower()
    profile = TaskProfile(context_length=len(text))

    complex_hits = sum(1 for marker in _COMPLEX_MARKERS if marker in lowered)
    simple_hits = sum(1 for marker in _SIMPLE_MARKERS if marker in lowered)

    # Länge zählt mit: Ein langer Text ist selten trivial.
    length_factor = min(0.3, len(text) / 4000)

    profile.complexity = max(
        0.0,
        min(1.0, 0.45 + complex_hits * 0.18 - simple_hits * 0.25 + length_factor),
    )
    if complex_hits:
        profile.reasons.append(f"{complex_hits} Merkmal(e) für hohe Komplexität")
    if simple_hits:
        profile.reasons.append(f"{simple_hits} Merkmal(e) für eine einfache Aufgabe")

    profile.sensitive = any(marker in lowered for marker in _SENSITIVE_MARKERS)
    if profile.sensitive:
        profile.reasons.append("Hinweis auf lokale, sensible Daten")

    profile.needs_vision = any(marker in lowered for marker in _VISION_MARKERS)
    profile.needs_coding = any(marker in lowered for marker in _CODING_MARKERS)

    if hint:
        for key in ("complexity", "sensitive", "needs_vision", "needs_coding",
                    "needs_tools", "context_length"):
            if key in hint:
                setattr(profile, key, hint[key])
        profile.reasons.append("Vom Agenten präzisiert")

    return profile


@dataclass(slots=True)
class RoutingDecision:
    """Das Ergebnis einer Routing-Entscheidung."""

    provider: str
    reason: str
    ranked: list[str]
    task: TaskProfile

    def to_dict(self) -> dict[str, Any]:
        return {
            "gewaehlt": self.provider,
            "begruendung": self.reason,
            "reihenfolge": self.ranked,
            "aufgabe": self.task.to_dict(),
        }


class ModelRouter:
    """Wählt den Provider für eine Aufgabe."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or {}
        self._profiles: dict[str, ProviderProfile] = {}
        self._load_profiles()

    def _load_profiles(self) -> None:
        """Baut die Providerprofile aus Vorgaben und Konfiguration."""

        overrides = self._config.get("routing", {}).get("providers", {}) if self._config else {}

        for name, defaults in DEFAULT_PROVIDER_PROFILES.items():
            merged = {**defaults, **(overrides.get(name) or {})}
            self._profiles[name] = ProviderProfile(name=name, **{
                key: merged[key] for key in (
                    "is_local", "requires_internet", "reasoning", "cost",
                    "speed", "can_vision", "can_tools", "context_length",
                ) if key in merged
            })

    def profile_for(self, name: str) -> ProviderProfile:
        """Das Profil eines Providers, mit Rückfall auf neutrale Werte."""

        return self._profiles.get(name) or ProviderProfile(name=name)

    def route(
        self,
        task: TaskProfile,
        available: list[str],
        *,
        mode: Mode = Mode.AUTO,
        online: bool = True,
    ) -> RoutingDecision:
        """Wählt den Provider (Abschnitt 65).

        Args:
            task: Das Aufgabenprofil.
            available: Die gerade verfügbaren Provider (vom
                ProviderManager). Ein Provider, der nicht läuft, kommt
                nicht in Frage – deshalb ist diese Liste und nicht die
                Registry die Grundlage.
            mode: Die Betriebsart aus den Einstellungen.
            online: Ob Internet da ist.

        Returns:
            Die Entscheidung samt Begründung und der vollständigen
            Rangfolge – Letztere, damit ein Fallback ohne erneutes Rechnen
            weiß, wer als Nächstes drankäme.
        """

        if not available:
            return RoutingDecision("", "Kein Provider verfügbar.", [], task)

        candidates = [self.profile_for(name) for name in available]

        # --- 1. Datenschutz und Offline schließen aus -------------------------
        force_local = (
            mode in (Mode.PRIVACY, Mode.OFFLINE)
            or not online
            or (task.sensitive and mode == Mode.AUTO)
        )

        if force_local:
            local = [profile for profile in candidates if profile.is_local]
            if local:
                candidates = local
                grund_praefix = (
                    "Offline – nur lokale Modelle."
                    if not online
                    else "Sensible Daten bleiben lokal."
                    if task.sensitive
                    else "Betriebsart erzwingt lokal."
                )
            else:
                # Es gibt keinen lokalen Provider. Bei erzwungenem
                # Datenschutz ist das ein echtes Hindernis, das benannt
                # werden muss – nicht still umgangen.
                if not online:
                    return RoutingDecision(
                        "", "Offline, aber kein lokales Modell verfügbar.",
                        [], task,
                    )
                grund_praefix = "Kein lokales Modell – trotz Datenschutzwunsch Cloud."
        else:
            grund_praefix = ""

        # --- 2. Harte Anforderungen -------------------------------------------
        if task.needs_vision:
            with_vision = [p for p in candidates if p.can_vision]
            if with_vision:
                candidates = with_vision

        # --- 3. Bewerten -------------------------------------------------------
        scored = sorted(
            candidates,
            key=lambda profile: self._score(profile, task, mode),
            reverse=True,
        )

        chosen = scored[0]
        ranked = [profile.name for profile in scored]

        reason = grund_praefix or self._explain(chosen, task, mode)

        logger.info(
            "Routing: %s (%s) – Komplexität %.2f, Modus %s.",
            chosen.name, reason, task.complexity, mode.value,
        )

        return RoutingDecision(chosen.name, reason, ranked, task)

    def _score(self, profile: ProviderProfile, task: TaskProfile, mode: Mode) -> float:
        """Bewertet, wie gut ein Provider zu einer Aufgabe passt.

        Die Gewichte verschieben sich mit der Betriebsart: Im Sparmodus
        zählen Kosten am meisten, im Qualitätsmodus das Reasoning. Im
        AUTO-Modus – dem Regelfall – gilt die Leitregel: lokal bevorzugen,
        solange die Aufgabe es zulässt.
        """

        # Grundeignung: Kann der Provider die Komplexität überhaupt tragen?
        if task.complexity >= COMPLEXITY_THRESHOLD:
            competence = profile.reasoning
        else:
            # Bei einfachen Aufgaben ist mehr Reasoning kein Vorteil, der
            # Kosten wert wäre. Ein lokales Modell reicht.
            competence = min(1.0, profile.reasoning + 0.3)

        cheapness = 1.0 - profile.cost
        locality = 1.0 if profile.is_local else 0.0

        if mode == Mode.QUALITY:
            return competence * 1.0 + profile.speed * 0.1

        if mode == Mode.SPEED:
            return profile.speed * 1.0 + competence * 0.3

        if mode == Mode.CHEAPEST:
            return cheapness * 1.0 + competence * 0.2

        if mode in (Mode.PRIVACY, Mode.OFFLINE):
            return locality * 1.0 + competence * 0.3

        # AUTO: die Leitregel in Zahlen.
        #
        # Bei einfachen Aufgaben wiegt lokal/günstig schwer – ein
        # Spitzenmodell für eine Zusammenfassung ist Verschwendung. Bei
        # anspruchsvollen kippt das Gewicht zum Reasoning, weil hier ein
        # schwaches Modell die Aufgabe verfehlt, und das kostet am Ende
        # mehr als der Cloud-Aufruf.
        if task.complexity >= COMPLEXITY_THRESHOLD:
            return competence * 0.7 + cheapness * 0.2 + locality * 0.1
        return cheapness * 0.4 + locality * 0.35 + competence * 0.25

    def _explain(self, profile: ProviderProfile, task: TaskProfile, mode: Mode) -> str:
        """Formuliert, warum dieser Provider gewählt wurde."""

        if profile.is_local:
            if task.complexity < COMPLEXITY_THRESHOLD:
                return "Einfache Aufgabe – lokal und kostenlos genügt."
            return "Lokales Modell trägt die Aufgabe."
        if task.complexity >= COMPLEXITY_THRESHOLD:
            return "Anspruchsvolle Aufgabe – ein starkes Cloud-Modell lohnt sich."
        return "Kein geeignetes lokales Modell verfügbar."

    def needs_escalation(
        self, decision: RoutingDecision, quality: float, *, threshold: float = 0.55
    ) -> str | None:
        """Prüft, ob nach einer schwachen Antwort eskaliert werden soll (Abschnitt 15).

        Ein lokales Modell darf eine Aufgabe beginnen; reicht die Qualität
        nicht, übernimmt das nächststärkere. „Reicht nicht“ heißt hier: Die
        gemessene Qualität liegt unter der Schwelle UND es gibt in der
        Rangfolge noch jemanden mit deutlich mehr Reasoning.

        Args:
            decision: Die ursprüngliche Entscheidung.
            quality: Die bewertete Qualität der Antwort (0.0 bis 1.0).
            threshold: Ab wann eskaliert wird.

        Returns:
            Der Name des stärkeren Providers, oder ``None``.
        """

        if quality >= threshold:
            return None

        current = self.profile_for(decision.provider)
        for name in decision.ranked:
            if name == decision.provider:
                continue
            candidate = self.profile_for(name)
            if candidate.reasoning > current.reasoning + 0.15:
                logger.info(
                    "Eskalation: %s → %s (Qualität %.2f unter %.2f).",
                    decision.provider, name, quality, threshold,
                )
                return name

        return None

    def describe(self) -> dict[str, Any]:
        """Alle Providerprofile – für die Transparenzansicht."""

        return {name: profile.to_dict() for name, profile in self._profiles.items()}
