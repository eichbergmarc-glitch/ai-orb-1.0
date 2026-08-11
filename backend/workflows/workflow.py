"""Aufbau eines Arbeitsablaufs (Phase 19).

Ein Workflow ist eine gespeicherte Folge von Schritten, die der Benutzer
später mit einem Satz auslöst: „Starte meine Recherche."

Jeder Schritt ruft ein Werkzeug auf. Das ist die entscheidende
Einschränkung: Ein Workflow kann nichts, was ein Werkzeug nicht kann, und
jeder Werkzeugaufruf läuft über die Sicherheitsschicht. Damit lässt sich
über einen Workflow nichts an der Zustimmung vorbeischmuggeln – auch nicht
dadurch, dass man ihn oft genug ausführt.

Zwei Dinge machen Workflows in der Praxis brauchbar:

**Ergebnisse fließen weiter.** Was ein Schritt liefert, steht den folgenden
als ``{{schritt.name}}`` zur Verfügung. Ohne das wäre jeder Schritt eine
Insel und der Ablauf nur eine Liste.

**Fehler haben eine Regel.** Für jeden Schritt ist festgelegt, was bei einem
Fehlschlag geschieht: abbrechen, überspringen oder wiederholen. Ein Workflow,
der bei jedem Stolperstein stehen bleibt, wird nicht benutzt; einer, der über
alles hinweggeht, richtet Schaden an.
"""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

#: Platzhalter der Form {{name}} oder {{name.feld}}.
PLACEHOLDER = re.compile(r"\{\{\s*([\w.]+)\s*\}\}")


class OnError(Enum):
    """Was geschieht, wenn ein Schritt fehlschlägt."""

    #: Den ganzen Ablauf abbrechen.
    ABORT = "abbrechen"
    #: Den Schritt überspringen und weitermachen.
    SKIP = "ueberspringen"
    #: Den Schritt wiederholen, dann abbrechen.
    RETRY = "wiederholen"

    @classmethod
    def parse(cls, value: Any) -> "OnError":
        text = str(value).strip().lower()
        for member in cls:
            if member.value == text or member.name.lower() == text:
                return member
        return cls.ABORT


class RunState(Enum):
    """Der Zustand eines Ablaufs."""

    PENDING = "wartend"
    RUNNING = "laeuft"
    PAUSED = "angehalten"
    COMPLETED = "fertig"
    FAILED = "fehlgeschlagen"
    CANCELLED = "abgebrochen"


@dataclass
class WorkflowStep:
    """Ein einzelner Schritt."""

    #: Kurzname, unter dem das Ergebnis später ansprechbar ist.
    name: str
    #: Das aufzurufende Werkzeug.
    tool: str
    #: Die Argumente. Werte dürfen Platzhalter enthalten.
    arguments: dict[str, Any] = field(default_factory=dict)
    #: Beschreibung für die Anzeige.
    description: str = ""
    #: Bedingung: Der Schritt läuft nur, wenn dieser Ausdruck zutrifft.
    condition: str = ""
    on_error: OnError = OnError.ABORT
    #: Wie oft wiederholt wird, wenn ``on_error`` auf Wiederholen steht.
    retries: int = 1
    #: Zeitlimit in Sekunden.
    timeout: float = 60.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "tool": self.tool,
            "arguments": self.arguments,
            "description": self.description,
            "condition": self.condition,
            "on_error": self.on_error.value,
            "retries": self.retries,
            "timeout": self.timeout,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "WorkflowStep":
        return cls(
            name=str(raw.get("name", "")).strip(),
            tool=str(raw.get("tool", "")).strip(),
            arguments=dict(raw.get("arguments", {}) or {}),
            description=str(raw.get("description", "")),
            condition=str(raw.get("condition", "")),
            on_error=OnError.parse(raw.get("on_error", "abbrechen")),
            retries=max(0, min(5, int(raw.get("retries", 1)))),
            timeout=max(1.0, min(600.0, float(raw.get("timeout", 60.0)))),
        )


@dataclass
class Workflow:
    """Ein gespeicherter Arbeitsablauf."""

    workflow_id: str
    name: str
    description: str = ""
    steps: list[WorkflowStep] = field(default_factory=list)
    #: Sätze, mit denen der Ablauf ausgelöst werden kann.
    triggers: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    last_run: float = 0.0
    run_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "name": self.name,
            "description": self.description,
            "steps": [step.to_dict() for step in self.steps],
            "triggers": list(self.triggers),
            "created_at": self.created_at,
            "last_run": self.last_run,
            "run_count": self.run_count,
            "permissions": [],
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Workflow":
        return cls(
            workflow_id=str(raw.get("workflow_id", uuid.uuid4().hex[:12])),
            name=str(raw.get("name", "")),
            description=str(raw.get("description", "")),
            steps=[WorkflowStep.from_dict(item) for item in (raw.get("steps", []) or [])],
            triggers=[str(item).strip().lower() for item in (raw.get("triggers", []) or [])],
            created_at=float(raw.get("created_at", time.time())),
            last_run=float(raw.get("last_run", 0.0)),
            run_count=int(raw.get("run_count", 0)),
        )

    def validate(self, known_tools: list[str]) -> list[str]:
        """Prüft den Ablauf auf Fehler.

        Geprüft wird vor dem Speichern, nicht erst beim Ausführen. Ein
        Workflow, der in der Mitte auf ein nicht vorhandenes Werkzeug läuft,
        hinterlässt einen halb erledigten Zustand – und das ist schlimmer,
        als gar nicht erst zu starten.
        """

        problems: list[str] = []

        if not self.name.strip():
            problems.append("Der Ablauf hat keinen Namen.")

        if not self.steps:
            problems.append("Der Ablauf hat keine Schritte.")

        seen: set[str] = set()
        for index, step in enumerate(self.steps, start=1):
            if not step.name:
                problems.append(f"Schritt {index} hat keinen Namen.")
            elif step.name in seen:
                problems.append(f"Der Schrittname '{step.name}' kommt mehrfach vor.")
            else:
                seen.add(step.name)

            if not step.tool:
                problems.append(f"Schritt '{step.name or index}' nennt kein Werkzeug.")
            elif step.tool not in known_tools:
                problems.append(
                    f"Schritt '{step.name or index}' verlangt das Werkzeug "
                    f"'{step.tool}', das es nicht gibt. Vorhanden sind: "
                    + ", ".join(known_tools)
                )

            # Platzhalter dürfen sich nur auf vorherige Schritte beziehen.
            for value in step.arguments.values():
                for match in PLACEHOLDER.finditer(str(value)):
                    reference = match.group(1).split(".")[0]
                    if reference not in seen and reference != "eingabe":
                        problems.append(
                            f"Schritt '{step.name or index}' verweist auf "
                            f"'{reference}', das vorher nicht vorkommt."
                        )

        return problems

    def matches(self, text: str) -> bool:
        """Ob ein Satz diesen Ablauf auslöst."""

        lowered = text.strip().lower()
        if not lowered:
            return False
        if lowered == self.name.lower():
            return True
        return any(trigger and trigger in lowered for trigger in self.triggers)


@dataclass
class StepResult:
    """Was bei einem Schritt herauskam."""

    step: str
    tool: str
    ok: bool
    output: str = ""
    error: str = ""
    skipped: bool = False
    attempts: int = 1
    seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "step": self.step,
            "tool": self.tool,
            "ok": self.ok,
            "output": self.output[:1000],
            "error": self.error,
            "skipped": self.skipped,
            "attempts": self.attempts,
            "seconds": round(self.seconds, 3),
        }


@dataclass
class WorkflowRun:
    """Ein Durchlauf."""

    run_id: str
    workflow_id: str
    workflow_name: str
    state: RunState = RunState.PENDING
    results: list[StepResult] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    finished_at: float = 0.0
    #: Wo der Ablauf steht – für das Fortsetzen nach einer Pause.
    current_index: int = 0
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "workflow_id": self.workflow_id,
            "workflow_name": self.workflow_name,
            "state": self.state.value,
            "results": [result.to_dict() for result in self.results],
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "seconds": round((self.finished_at or time.time()) - self.started_at, 2),
            "current_index": self.current_index,
            "message": self.message,
            "succeeded": self.state is RunState.COMPLETED,
        }

    def summary(self) -> str:
        """Der Durchlauf in einem lesbaren Absatz."""

        done = sum(1 for result in self.results if result.ok and not result.skipped)
        skipped = sum(1 for result in self.results if result.skipped)
        failed = sum(1 for result in self.results if not result.ok and not result.skipped)

        parts = [f"'{self.workflow_name}': {self.state.value}"]
        parts.append(f"{done} Schritte erledigt")
        if skipped:
            parts.append(f"{skipped} übersprungen")
        if failed:
            parts.append(f"{failed} fehlgeschlagen")
        if self.message:
            parts.append(self.message)
        return ", ".join(parts) + "."


def resolve_placeholders(value: Any, context: dict[str, Any]) -> Any:
    """Ersetzt Platzhalter durch Ergebnisse vorheriger Schritte.

    Ein Platzhalter, für den es keinen Wert gibt, bleibt unverändert stehen.
    Das ist Absicht: Ein leerer Wert an dieser Stelle würde stillschweigend
    etwas Falsches tun, ein stehen gebliebener Platzhalter fällt auf.
    """

    if not isinstance(value, str):
        return value

    def replace(match: re.Match[str]) -> str:
        path = match.group(1).split(".")
        current: Any = context
        for part in path:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return match.group(0)
        return str(current)

    return PLACEHOLDER.sub(replace, value)


def evaluate_condition(condition: str, context: dict[str, Any]) -> bool:
    """Wertet die Bedingung eines Schritts aus.

    Bewusst eine sehr kleine Sprache, kein ``eval``: Unterstützt werden
    ``<name> vorhanden``, ``<name> leer``, ``<name> enthaelt <text>`` und
    ``<name> == <text>``. Mehr braucht ein Ablauf selten, und alles darüber
    hinaus wäre eine Einfallstelle für Code aus einer Modellantwort.
    """

    expression = condition.strip()
    if not expression:
        return True

    resolved = str(resolve_placeholders(expression, context))
    lowered = resolved.lower()

    if lowered.endswith(" vorhanden"):
        return bool(resolved[: -len(" vorhanden")].strip())

    if lowered.endswith(" leer"):
        return not resolved[: -len(" leer")].strip()

    if " enthaelt " in lowered or " enthält " in lowered:
        separator = " enthaelt " if " enthaelt " in lowered else " enthält "
        left, _, right = resolved.partition(separator)
        return right.strip().lower() in left.strip().lower()

    if "==" in resolved:
        left, _, right = resolved.partition("==")
        return left.strip().lower() == right.strip().lower()

    if "!=" in resolved:
        left, _, right = resolved.partition("!=")
        return left.strip().lower() != right.strip().lower()

    # Ein Ausdruck, der nichts davon ist, gilt als erfüllt, wenn er nicht
    # leer ist.
    return bool(resolved.strip())
