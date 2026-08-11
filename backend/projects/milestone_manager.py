"""Milestone Manager – Projektphasen, Zwischenziele und Deadlines.

Verwaltet Projektphasen, Zwischenziele, Fristen, Fortschritt, Risiken und
erledigte Schritte.

Der Orb erinnert **nur dann** an Fristen, wenn der Benutzer die Erinnerung
für den jeweiligen Meilenstein ausdrücklich aktiviert hat.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from backend.system.logging_setup import get_logger
from backend.utils.store import JsonStore

logger = get_logger(__name__)

#: Zustände eines Meilensteins.
MILESTONE_STATUSES: tuple[str, ...] = ("geplant", "laufend", "erreicht", "verschoben", "verworfen")


class MilestoneManager:
    """Verwaltet Meilensteine aller Projekte."""

    def __init__(self, filename: str = "milestones.json") -> None:
        self._store = JsonStore(filename, default={"milestones": []})

    def add(
        self,
        project_id: str,
        title: str,
        *,
        due: float | None = None,
        phase: str = "",
        remind: bool = False,
        risks: list[str] | None = None,
    ) -> dict[str, Any]:
        """Legt einen Meilenstein an.

        Args:
            project_id: Zugehöriges Projekt.
            title: Bezeichnung des Meilensteins.
            due: Frist als Unix-Zeitstempel.
            phase: Zugehörige Projektphase.
            remind: Ob der Orb an diese Frist erinnern darf. Standard ist
                ``False`` – ohne ausdrückliche Aktivierung erinnert der Orb
                nicht.
            risks: Bekannte Risiken.
        """

        milestone: dict[str, Any] = {
            "id": uuid.uuid4().hex,
            "project_id": project_id,
            "title": title.strip(),
            "phase": phase,
            "status": "geplant",
            "progress": 0.0,
            "due": due,
            "remind": bool(remind),
            "risks": list(risks or []),
            "completed_steps": [],
            "created_at": time.time(),
            "updated_at": time.time(),
        }
        milestones = list(self._store.get("milestones", []) or [])
        milestones.append(milestone)
        self._store.set("milestones", milestones)
        logger.info("Meilenstein angelegt: %s", title)
        return milestone

    def update(self, milestone_id: str, **changes: Any) -> dict[str, Any] | None:
        """Aktualisiert einen Meilenstein."""

        allowed = {"title", "phase", "status", "progress", "due", "remind", "risks"}
        milestones = list(self._store.get("milestones", []) or [])
        for milestone in milestones:
            if milestone.get("id") != milestone_id:
                continue
            for key, value in changes.items():
                if key in allowed:
                    milestone[key] = value
            if milestone.get("status") not in MILESTONE_STATUSES:
                milestone["status"] = "geplant"
            milestone["progress"] = max(0.0, min(1.0, float(milestone.get("progress", 0.0))))
            milestone["updated_at"] = time.time()
            self._store.set("milestones", milestones)
            return milestone
        return None

    def complete_step(self, milestone_id: str, step: str) -> dict[str, Any] | None:
        """Vermerkt einen erledigten Teilschritt."""

        milestones = list(self._store.get("milestones", []) or [])
        for milestone in milestones:
            if milestone.get("id") == milestone_id:
                steps = list(milestone.get("completed_steps", []) or [])
                steps.append({"step": step, "at": time.time()})
                milestone["completed_steps"] = steps
                milestone["updated_at"] = time.time()
                self._store.set("milestones", milestones)
                return milestone
        return None

    def add_risk(self, milestone_id: str, risk: str) -> dict[str, Any] | None:
        """Ergänzt ein Risiko."""

        milestone = self.get(milestone_id)
        if milestone is None:
            return None
        risks = list(milestone.get("risks", []) or [])
        if risk not in risks:
            risks.append(risk)
        return self.update(milestone_id, risks=risks)

    def get(self, milestone_id: str) -> dict[str, Any] | None:
        """Liest einen Meilenstein."""

        for milestone in self._store.get("milestones", []) or []:
            if milestone.get("id") == milestone_id:
                return milestone
        return None

    def list(self, project_id: str | None = None, *, status: str | None = None) -> list[dict[str, Any]]:
        """Listet Meilensteine, nach Frist sortiert."""

        milestones = list(self._store.get("milestones", []) or [])
        if project_id is not None:
            milestones = [m for m in milestones if m.get("project_id") == project_id]
        if status is not None:
            milestones = [m for m in milestones if m.get("status") == status]
        milestones.sort(
            key=lambda m: float(m["due"]) if isinstance(m.get("due"), (int, float)) else float("inf")
        )
        return milestones

    def due_reminders(self, *, within_days: float = 7.0) -> list[dict[str, Any]]:
        """Gibt fällige Erinnerungen zurück.

        Es werden ausschließlich Meilensteine berücksichtigt, für die der
        Benutzer die Erinnerung aktiviert hat (``remind: true``).
        """

        now = time.time()
        horizon = now + within_days * 86400.0
        reminders: list[dict[str, Any]] = []
        for milestone in self.list():
            if not milestone.get("remind"):
                continue
            if milestone.get("status") in ("erreicht", "verworfen"):
                continue
            due = milestone.get("due")
            if isinstance(due, (int, float)) and due <= horizon:
                reminders.append(
                    {
                        **milestone,
                        "days_remaining": round((float(due) - now) / 86400.0, 1),
                        "overdue": float(due) < now,
                    }
                )
        return reminders

    def progress(self, project_id: str) -> dict[str, Any]:
        """Berechnet den Gesamtfortschritt eines Projekts über alle Meilensteine."""

        milestones = self.list(project_id)
        if not milestones:
            return {"milestones": 0, "progress": 0.0, "reached": 0, "risks": []}

        reached = sum(1 for m in milestones if m.get("status") == "erreicht")
        overall = sum(float(m.get("progress", 0.0)) for m in milestones) / len(milestones)
        risks = [risk for m in milestones for risk in (m.get("risks", []) or [])]

        return {
            "milestones": len(milestones),
            "reached": reached,
            "progress": round(overall, 3),
            "risks": risks,
            "next": milestones[0] if milestones else None,
        }

    def delete(self, milestone_id: str) -> bool:
        """Entfernt einen Meilenstein."""

        milestones = list(self._store.get("milestones", []) or [])
        remaining = [m for m in milestones if m.get("id") != milestone_id]
        if len(remaining) == len(milestones):
            return False
        self._store.set("milestones", remaining)
        return True
