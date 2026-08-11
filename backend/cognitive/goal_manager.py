"""Goal Manager – Verwaltung kurz- und langfristiger Ziele.

Der Orb verwaltet Ziele für heute, diese Woche, für einzelne Projekte und
als langfristige Lernziele. Jedes Ziel besitzt Status, Priorität,
Fortschritt und nächste Schritte.

Ziele werden lokal in ``data/goals.json`` gespeichert.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from backend.system.logging_setup import get_logger
from backend.utils.store import JsonStore

logger = get_logger(__name__)

#: Zeithorizonte eines Ziels.
HORIZONS: tuple[str, ...] = ("heute", "woche", "projekt", "langfristig")

#: Zulässige Zielzustände.
GOAL_STATUSES: tuple[str, ...] = ("aktiv", "pausiert", "erreicht", "verworfen")


class GoalManager:
    """Verwaltet die Ziele des Benutzers."""

    def __init__(self, filename: str = "goals.json") -> None:
        self._store = JsonStore(filename, default={"goals": []})

    # --- Anlegen und Ändern -------------------------------------------------

    def add(
        self,
        title: str,
        *,
        horizon: str = "projekt",
        priority: str = "normal",
        project_id: str | None = None,
        next_steps: list[str] | None = None,
        description: str = "",
    ) -> dict[str, Any]:
        """Legt ein neues Ziel an.

        Args:
            title: Bezeichnung des Ziels (z. B. "Rust lernen").
            horizon: Zeithorizont aus :data:`HORIZONS`.
            priority: ``hoch``, ``normal`` oder ``niedrig``.
            project_id: Zugehöriges Projekt.
            next_steps: Konkrete nächste Schritte.
            description: Ausführlichere Beschreibung.

        Returns:
            Das angelegte Ziel als Dict.
        """

        goal: dict[str, Any] = {
            "id": uuid.uuid4().hex,
            "title": title.strip(),
            "description": description,
            "horizon": horizon if horizon in HORIZONS else "projekt",
            "priority": priority,
            "status": "aktiv",
            "progress": 0.0,
            "next_steps": list(next_steps or []),
            "project_id": project_id,
            "created_at": time.time(),
            "updated_at": time.time(),
        }
        goals = list(self._store.get("goals", []) or [])
        goals.append(goal)
        self._store.set("goals", goals)
        logger.info("Neues Ziel angelegt: %s (%s)", goal["title"], goal["horizon"])
        return goal

    def update(self, goal_id: str, **changes: Any) -> dict[str, Any] | None:
        """Aktualisiert ein Ziel.

        Erlaubte Felder: ``title``, ``description``, ``horizon``,
        ``priority``, ``status``, ``progress``, ``next_steps``,
        ``project_id``.
        """

        allowed = {
            "title",
            "description",
            "horizon",
            "priority",
            "status",
            "progress",
            "next_steps",
            "project_id",
        }
        goals = list(self._store.get("goals", []) or [])
        for goal in goals:
            if goal.get("id") != goal_id:
                continue
            for key, value in changes.items():
                if key in allowed:
                    goal[key] = value
            if goal.get("status") not in GOAL_STATUSES:
                goal["status"] = "aktiv"
            goal["progress"] = max(0.0, min(1.0, float(goal.get("progress", 0.0))))
            goal["updated_at"] = time.time()
            self._store.set("goals", goals)
            return goal
        return None

    def set_progress(self, goal_id: str, progress: float) -> dict[str, Any] | None:
        """Setzt den Fortschritt eines Ziels (0.0 bis 1.0).

        Erreicht der Fortschritt 1.0, wird das Ziel automatisch als
        erreicht markiert.
        """

        goal = self.update(goal_id, progress=progress)
        if goal is not None and goal["progress"] >= 1.0:
            self.update(goal_id, status="erreicht")
        return goal

    def add_next_step(self, goal_id: str, step: str) -> dict[str, Any] | None:
        """Ergänzt einen nächsten Schritt zu einem Ziel."""

        goals = list(self._store.get("goals", []) or [])
        for goal in goals:
            if goal.get("id") == goal_id:
                steps = list(goal.get("next_steps", []) or [])
                if step not in steps:
                    steps.append(step)
                goal["next_steps"] = steps
                goal["updated_at"] = time.time()
                self._store.set("goals", goals)
                return goal
        return None

    def delete(self, goal_id: str) -> bool:
        """Entfernt ein Ziel endgültig."""

        goals = list(self._store.get("goals", []) or [])
        remaining = [goal for goal in goals if goal.get("id") != goal_id]
        if len(remaining) == len(goals):
            return False
        self._store.set("goals", remaining)
        return True

    # --- Abfragen ---------------------------------------------------------------

    def list(
        self,
        *,
        horizon: str | None = None,
        status: str | None = "aktiv",
        project_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Listet Ziele, optional gefiltert."""

        goals = list(self._store.get("goals", []) or [])
        if horizon is not None:
            goals = [goal for goal in goals if goal.get("horizon") == horizon]
        if status is not None:
            goals = [goal for goal in goals if goal.get("status") == status]
        if project_id is not None:
            goals = [goal for goal in goals if goal.get("project_id") == project_id]

        priority_rank = {"hoch": 0, "normal": 1, "niedrig": 2}
        goals.sort(
            key=lambda goal: (
                priority_rank.get(str(goal.get("priority")), 1),
                -float(goal.get("progress", 0.0)),
                goal.get("created_at", 0.0),
            )
        )
        return goals

    def get(self, goal_id: str) -> dict[str, Any] | None:
        """Liest ein einzelnes Ziel."""

        for goal in self._store.get("goals", []) or []:
            if goal.get("id") == goal_id:
                return goal
        return None

    def current_focus(self, project_id: str | None = None) -> dict[str, Any] | None:
        """Ermittelt das Ziel, an dem aktuell am sinnvollsten gearbeitet wird."""

        for horizon in ("heute", "woche", "projekt", "langfristig"):
            candidates = self.list(horizon=horizon, project_id=project_id)
            if candidates:
                return candidates[0]
        return None

    def overview(self) -> dict[str, Any]:
        """Übersicht über alle Ziele.

        Beantwortet die Transparenzfrage "Welche Ziele verfolgst du?".
        """

        goals = list(self._store.get("goals", []) or [])
        by_horizon: dict[str, int] = {horizon: 0 for horizon in HORIZONS}
        by_status: dict[str, int] = {status: 0 for status in GOAL_STATUSES}
        for goal in goals:
            by_horizon[str(goal.get("horizon", "projekt"))] = (
                by_horizon.get(str(goal.get("horizon", "projekt")), 0) + 1
            )
            by_status[str(goal.get("status", "aktiv"))] = (
                by_status.get(str(goal.get("status", "aktiv")), 0) + 1
            )
        return {
            "total": len(goals),
            "by_horizon": by_horizon,
            "by_status": by_status,
            "active": self.list(status="aktiv"),
        }
