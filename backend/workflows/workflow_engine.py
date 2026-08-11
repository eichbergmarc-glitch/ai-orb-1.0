"""Ausführung von Arbeitsabläufen (Phase 19).

Führt gespeicherte Workflows aus – anhaltbar, abbrechbar und mit einer
Regel für jeden Fehlschlag.

Der Ablauf eines Durchgangs:

1. Vor dem Start wird **einmal** für den ganzen Ablauf gefragt, sofern
   heikle Werkzeuge vorkommen. Der Benutzer sieht dabei, was der Ablauf
   berühren wird.
2. Jeder Schritt ersetzt seine Platzhalter aus den bisherigen Ergebnissen.
3. Trifft die Bedingung nicht zu, wird der Schritt übersprungen.
4. Der Werkzeugaufruf läuft über die Sicherheitsschicht – auch die
   Einzelfreigabe für kritische Aktionen bleibt bestehen. Ein Workflow
   umgeht sie nicht.
5. Bei einem Fehlschlag greift die Regel des Schritts.

Zwischen den Schritten wird auf Anhalten und Abbrechen geprüft. Das ist der
Grund, warum die Schleife nicht in einer einzigen Aufgabe steckt: Ein
laufender Ablauf muss sich stoppen lassen, ohne ihn abzuwürgen.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

from backend.config import get_config
from backend.security.permissions import RiskLevel, get_permission
from backend.security.security_engine import SecurityEngine
from backend.system.logging_setup import get_logger
from backend.tools.base_tool import ToolResult
from backend.tools.registry import ToolRegistry
from backend.utils.store import JsonStore
from backend.workflows.workflow import (
    OnError,
    RunState,
    StepResult,
    Workflow,
    WorkflowRun,
    WorkflowStep,
    evaluate_condition,
    resolve_placeholders,
)

logger = get_logger(__name__)


class WorkflowEngine:
    """Verwaltet und führt Arbeitsabläufe aus."""

    def __init__(
        self,
        *,
        registry: ToolRegistry,
        security: SecurityEngine,
        store_filename: str = "workflows/workflows.json",
    ) -> None:
        config = get_config()

        self._tools = registry
        self._security = security
        self._enabled = bool(config.get("workflows.enabled", True))
        self._max_steps = int(config.get("workflows.max_steps", 25))

        self._store = JsonStore(store_filename, default={"workflows": {}})
        self._workflows: dict[str, Workflow] = {}
        self._runs: dict[str, WorkflowRun] = {}
        self._control: dict[str, str] = {}

        self._load()

    def _load(self) -> None:
        for raw in (self._store.get("workflows", {}) or {}).values():
            workflow = Workflow.from_dict(raw)
            if workflow.workflow_id:
                self._workflows[workflow.workflow_id] = workflow

        if self._workflows:
            logger.info("Arbeitsabläufe geladen: %d.", len(self._workflows))

    def _save(self) -> None:
        self._store.set(
            "workflows",
            {workflow_id: workflow.to_dict() for workflow_id, workflow in self._workflows.items()},
        )

    @property
    def enabled(self) -> bool:
        """Ob Abläufe ausgeführt werden dürfen."""

        return self._enabled

    # --- Anlegen und Verwalten -------------------------------------------------------

    def create(
        self,
        name: str,
        steps: list[dict[str, Any]],
        *,
        description: str = "",
        triggers: list[str] | None = None,
    ) -> tuple[Workflow | None, str]:
        """Legt einen Ablauf an – nach Prüfung.

        Returns:
            Der Ablauf und eine Meldung im Klartext.
        """

        if len(steps) > self._max_steps:
            return None, (
                f"Ein Ablauf darf höchstens {self._max_steps} Schritte haben, "
                f"dieser hat {len(steps)}."
            )

        workflow = Workflow(
            workflow_id=uuid.uuid4().hex[:12],
            name=name.strip(),
            description=description.strip(),
            steps=[WorkflowStep.from_dict(item) for item in steps],
            triggers=[str(item).strip().lower() for item in (triggers or []) if str(item).strip()],
        )

        problems = workflow.validate(self._tools.names())
        if problems:
            return None, "Der Ablauf wurde nicht gespeichert:\n" + "\n".join(
                f"- {problem}" for problem in problems
            )

        self._workflows[workflow.workflow_id] = workflow
        self._save()

        return workflow, (
            f"Ablauf '{workflow.name}' gespeichert: {len(workflow.steps)} Schritte. "
            + (f"Auslöser: {', '.join(workflow.triggers)}." if workflow.triggers else "")
        )

    def remove(self, workflow_id: str) -> tuple[bool, str]:
        """Löscht einen Ablauf."""

        workflow = self._workflows.pop(workflow_id, None)
        if workflow is None:
            return False, "Diesen Ablauf gibt es nicht."
        self._save()
        return True, f"Ablauf '{workflow.name}' gelöscht."

    def find_by_trigger(self, text: str) -> Workflow | None:
        """Sucht den Ablauf, den ein Satz auslöst."""

        for workflow in self._workflows.values():
            if workflow.matches(text):
                return workflow
        return None

    def describe(self, workflow_id: str) -> dict[str, Any]:
        """Beschreibt einen Ablauf samt seiner Berechtigungen.

        Das ist, was der Benutzer vor dem ersten Start zu sehen bekommt.
        """

        workflow = self._workflows.get(workflow_id)
        if workflow is None:
            return {"found": False}

        permissions: dict[str, str] = {}
        highest = RiskLevel.SAFE
        order = [RiskLevel.SAFE, RiskLevel.MODERATE, RiskLevel.HIGH, RiskLevel.CRITICAL]

        for step in workflow.steps:
            tool = self._tools.get(step.tool)
            if tool is None:
                continue
            permission = get_permission(tool.permission)
            if permission is None:
                continue
            permissions[permission.name] = permission.description
            if order.index(permission.risk) > order.index(highest):
                highest = permission.risk

        return {
            "found": True,
            "workflow": workflow.to_dict(),
            "permissions": [
                {"name": name, "description": description}
                for name, description in sorted(permissions.items())
            ],
            "highest_risk": highest.value,
            "step_count": len(workflow.steps),
        }

    # --- Ausführen ---------------------------------------------------------------------

    async def run(
        self,
        workflow_id: str,
        *,
        input_text: str = "",
        actor: str = "workflow",
    ) -> WorkflowRun:
        """Führt einen Ablauf aus.

        Args:
            workflow_id: Welcher Ablauf.
            input_text: Was der Benutzer mitgegeben hat; als ``{{eingabe}}``
                in den Schritten verfügbar.
            actor: Wer ausführt – für das Prüfprotokoll.

        Returns:
            Das Protokoll des Durchlaufs.
        """

        workflow = self._workflows.get(workflow_id)
        if workflow is None:
            return WorkflowRun(
                run_id=uuid.uuid4().hex[:8],
                workflow_id=workflow_id,
                workflow_name="",
                state=RunState.FAILED,
                message="Diesen Ablauf gibt es nicht.",
                finished_at=time.time(),
            )

        run = WorkflowRun(
            run_id=uuid.uuid4().hex[:8],
            workflow_id=workflow.workflow_id,
            workflow_name=workflow.name,
            state=RunState.RUNNING,
        )
        self._runs[run.run_id] = run
        self._control[run.run_id] = "run"

        if not self._enabled:
            run.state = RunState.FAILED
            run.message = "Arbeitsabläufe sind in config.yaml ausgeschaltet."
            run.finished_at = time.time()
            return run

        # Einmal für den ganzen Ablauf fragen, wenn Heikles vorkommt.
        overview = self.describe(workflow.workflow_id)
        if overview.get("highest_risk") not in (RiskLevel.SAFE.value, None):
            listing = ", ".join(
                str(item["description"]) for item in overview.get("permissions", [])
            )
            decision = await self._security.require(
                f"{actor}:{workflow.name}",
                "read_files",
                f"Den Ablauf '{workflow.name}' mit {len(workflow.steps)} Schritten "
                f"ausführen. Dabei kommt vor: {listing}.",
                context={"workflow": workflow.name, "steps": len(workflow.steps)},
            )
            if not decision.allowed:
                run.state = RunState.CANCELLED
                run.message = decision.reason
                run.finished_at = time.time()
                return run

        context: dict[str, Any] = {"eingabe": input_text}

        for index, step in enumerate(workflow.steps):
            run.current_index = index

            # Zwischen den Schritten auf Anhalten und Abbrechen prüfen.
            control = await self._wait_if_paused(run)
            if control == "cancel":
                run.state = RunState.CANCELLED
                run.message = "Vom Benutzer abgebrochen."
                run.finished_at = time.time()
                return run

            result = await self._run_step(step, context, actor, workflow.name)
            run.results.append(result)

            if result.ok and not result.skipped:
                context[step.name] = result.output

            if not result.ok and not result.skipped:
                if step.on_error is OnError.ABORT:
                    run.state = RunState.FAILED
                    run.message = f"Schritt '{step.name}' fehlgeschlagen: {result.error}"
                    run.finished_at = time.time()
                    self._control.pop(run.run_id, None)
                    return run
                # Bei SKIP und erschöpftem RETRY geht es weiter.

        run.state = RunState.COMPLETED
        run.finished_at = time.time()
        run.current_index = len(workflow.steps)

        workflow.last_run = time.time()
        workflow.run_count += 1
        self._save()
        self._control.pop(run.run_id, None)

        logger.info("Ablauf '%s' abgeschlossen (%s).", workflow.name, run.summary())
        return run

    async def _run_step(
        self,
        step: WorkflowStep,
        context: dict[str, Any],
        actor: str,
        workflow_name: str,
    ) -> StepResult:
        """Führt einen einzelnen Schritt aus."""

        started = time.perf_counter()

        if not evaluate_condition(step.condition, context):
            return StepResult(
                step=step.name,
                tool=step.tool,
                ok=True,
                skipped=True,
                output=f"Übersprungen, weil die Bedingung nicht zutraf: {step.condition}",
                seconds=time.perf_counter() - started,
            )

        tool = self._tools.get(step.tool)
        if tool is None:
            return StepResult(
                step=step.name,
                tool=step.tool,
                ok=False,
                error=f"Das Werkzeug '{step.tool}' gibt es nicht.",
                seconds=time.perf_counter() - started,
            )

        arguments = {
            key: resolve_placeholders(value, context) for key, value in step.arguments.items()
        }

        valid, problem, cleaned = tool.validate(arguments)
        if not valid:
            return StepResult(
                step=step.name,
                tool=step.tool,
                ok=False,
                error=problem,
                seconds=time.perf_counter() - started,
            )

        attempts = 1 + (step.retries if step.on_error is OnError.RETRY else 0)
        last_error = ""

        for attempt in range(1, attempts + 1):
            decision = await self._security.require(
                f"{actor}:{workflow_name}",
                tool.permission,
                f"Schritt '{step.name}' des Ablaufs '{workflow_name}': "
                + (step.description or tool.description),
                context={"tool": tool.name, "arguments": cleaned},
            )

            if not decision.allowed:
                return StepResult(
                    step=step.name,
                    tool=step.tool,
                    ok=False,
                    error=f"Nicht ausgeführt: {decision.reason}",
                    attempts=attempt,
                    seconds=time.perf_counter() - started,
                )

            try:
                result: ToolResult = await asyncio.wait_for(
                    tool.execute(cleaned), timeout=step.timeout
                )
            except asyncio.TimeoutError:
                last_error = f"Zeitlimit von {step.timeout:.0f} Sekunden überschritten."
                logger.warning("Schritt '%s': %s", step.name, last_error)
                continue
            except Exception as error:  # noqa: BLE001 - ein Werkzeug darf nichts abbrechen.
                last_error = f"Das Werkzeug ist abgestürzt: {error}"
                logger.exception("Schritt '%s' ist abgestürzt.", step.name)
                continue

            self._security.record_action(
                f"{actor}:{workflow_name}",
                tool.permission,
                f"Schritt '{step.name}'",
                succeeded=result.ok,
            )

            if result.ok:
                return StepResult(
                    step=step.name,
                    tool=step.tool,
                    ok=True,
                    output=result.output,
                    attempts=attempt,
                    seconds=time.perf_counter() - started,
                )

            last_error = result.error

        skipped = step.on_error is OnError.SKIP
        return StepResult(
            step=step.name,
            tool=step.tool,
            ok=skipped,
            skipped=skipped,
            output=f"Übersprungen nach Fehlschlag: {last_error}" if skipped else "",
            error="" if skipped else last_error,
            attempts=attempts,
            seconds=time.perf_counter() - started,
        )

    async def _wait_if_paused(self, run: WorkflowRun) -> str:
        """Hält an, solange pausiert ist. Gibt die zuletzt gesetzte Anweisung zurück."""

        while self._control.get(run.run_id) == "pause":
            run.state = RunState.PAUSED
            await asyncio.sleep(0.4)

        control = self._control.get(run.run_id, "run")
        if control == "run" and run.state is RunState.PAUSED:
            run.state = RunState.RUNNING
        return control

    # --- Steuerung -----------------------------------------------------------------------

    def pause(self, run_id: str) -> bool:
        """Hält einen laufenden Ablauf nach dem aktuellen Schritt an."""

        if run_id not in self._control:
            return False
        self._control[run_id] = "pause"
        logger.info("Ablauf %s wird angehalten.", run_id)
        return True

    def resume(self, run_id: str) -> bool:
        """Setzt einen angehaltenen Ablauf fort."""

        if run_id not in self._control:
            return False
        self._control[run_id] = "run"
        logger.info("Ablauf %s wird fortgesetzt.", run_id)
        return True

    def cancel(self, run_id: str) -> bool:
        """Bricht einen Ablauf nach dem aktuellen Schritt ab.

        Bewusst nicht mitten im Schritt: Ein Werkzeugaufruf, der zur Hälfte
        abgebrochen wird, hinterlässt einen Zustand, den niemand versteht.
        """

        if run_id not in self._control:
            return False
        self._control[run_id] = "cancel"
        logger.info("Ablauf %s wird abgebrochen.", run_id)
        return True

    # --- Auskunft ---------------------------------------------------------------------------

    def workflows(self) -> list[dict[str, Any]]:
        """Alle gespeicherten Abläufe."""

        return [
            workflow.to_dict()
            for workflow in sorted(self._workflows.values(), key=lambda item: item.name.lower())
        ]

    def runs(self, limit: int = 20) -> list[dict[str, Any]]:
        """Die jüngsten Durchläufe."""

        recent = sorted(self._runs.values(), key=lambda item: item.started_at, reverse=True)
        return [run.to_dict() for run in recent[:limit]]

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        """Einen Durchlauf holen."""

        run = self._runs.get(run_id)
        return run.to_dict() if run else None

    def status(self) -> dict[str, Any]:
        """Statusangaben für die Transparenzansicht."""

        active = [
            run.to_dict()
            for run in self._runs.values()
            if run.state in (RunState.RUNNING, RunState.PAUSED)
        ]
        return {
            "enabled": self._enabled,
            "workflows": len(self._workflows),
            "names": [workflow.name for workflow in self._workflows.values()],
            "active_runs": active,
            "total_runs": len(self._runs),
            "max_steps": self._max_steps,
        }
