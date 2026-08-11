"""Task Manager des Cognitive Core.

Verwaltet alle Aufgaben in den Zuständen ``offen``, ``in_bearbeitung``,
``blockiert`` und ``erledigt``. Der Orb kann Aufgaben eigenständig
strukturieren (in Teilaufgaben zerlegen) und sinnvolle nächste Schritte
vorschlagen.

Die Persistenz liegt ausschließlich in der Memory Engine
(:class:`~backend.memory.task_memory.TaskMemory`); der Task Manager greift
über die Memory API darauf zu und hält selbst keinen eigenen Speicher.
"""

from __future__ import annotations

from typing import Any

from backend.memory.memory_engine import MemoryEngine
from backend.memory.memory_store import MemoryRecord
from backend.system.logging_setup import get_logger

logger = get_logger(__name__)

#: Typische Zerlegungsmuster für wiederkehrende Aufgabenarten. Sie
#: ermöglichen eine sinnvolle Strukturierung auch ohne Sprachmodell.
_DECOMPOSITION_TEMPLATES: dict[tuple[str, ...], list[str]] = {
    ("hausarbeit", "seminararbeit", "essay", "aufsatz"): [
        "Thema eingrenzen",
        "Literatur sammeln",
        "Fragestellung entwickeln",
        "Gliederung erstellen",
        "Recherche durchführen",
        "Rohfassung schreiben",
        "Überarbeiten",
        "Zitation prüfen",
    ],
    ("recherche", "quellen", "literatur"): [
        "Suchbegriffe festlegen",
        "Kataloge und Datenbanken durchsuchen",
        "Treffer sichten und bewerten",
        "Relevante Titel exzerpieren",
        "Ergebnisse zusammenführen",
    ],
    ("programm", "software", "feature", "modul", "skript"): [
        "Anforderungen klären",
        "Architektur entwerfen",
        "Implementieren",
        "Tests schreiben",
        "Fehler beheben",
        "Dokumentation ergänzen",
    ],
    ("lernen", "vorbereiten", "prüfung", "klausur"): [
        "Stoffumfang festlegen",
        "Zeitplan erstellen",
        "Grundlagen erarbeiten",
        "Vertiefen und üben",
        "Wiederholen",
        "Selbsttest durchführen",
    ],
}


class TaskManager:
    """Strukturiert und verwaltet Aufgaben."""

    def __init__(self, memory: MemoryEngine) -> None:
        self._memory = memory

    # --- Grundoperationen ---------------------------------------------------

    def add(
        self,
        title: str,
        *,
        project_id: str | None = None,
        priority: str = "normal",
        due: float | None = None,
        parent_id: str | None = None,
        notes: str = "",
    ) -> MemoryRecord:
        """Legt eine Aufgabe an."""

        record = self._memory.tasks.add(
            title,
            project_id=project_id,
            priority=priority,
            due=due,
            parent_id=parent_id,
            notes=notes,
        )
        logger.info("Aufgabe angelegt: %s", title)
        return record

    def set_status(self, task_id: str, status: str, *, reason: str | None = None) -> bool:
        """Ändert den Status einer Aufgabe."""

        return self._memory.tasks.set_status(task_id, status, reason=reason)

    def list(self, *, status: str | None = None, project_id: str | None = None) -> list[MemoryRecord]:
        """Listet Aufgaben."""

        return self._memory.tasks.list(status=status, project_id=project_id)

    def open_tasks(self, project_id: str | None = None) -> list[MemoryRecord]:
        """Alle nicht erledigten Aufgaben."""

        return self._memory.tasks.open_tasks(project_id=project_id)

    # --- Strukturierung -----------------------------------------------------

    def decompose(self, title: str, *, project_id: str | None = None) -> list[MemoryRecord]:
        """Zerlegt eine komplexe Aufgabe in sinnvolle Teilaufgaben.

        Passt eines der bekannten Muster (Hausarbeit, Recherche,
        Software, Lernen), wird dieses verwendet. Andernfalls wird die
        Aufgabe als einzelne Aufgabe angelegt – der Orb erfindet keine
        künstliche Struktur.

        Args:
            title: Beschreibung der Gesamtaufgabe.
            project_id: Zugehöriges Projekt.

        Returns:
            Die angelegte Hauptaufgabe gefolgt von ihren Teilaufgaben.
        """

        parent = self.add(title, project_id=project_id, priority="hoch")
        steps = self.suggest_steps(title)

        created: list[MemoryRecord] = [parent]
        for step in steps:
            created.append(
                self.add(step, project_id=project_id, parent_id=parent.id)
            )

        if len(created) > 1:
            logger.info("Aufgabe '%s' in %d Teilschritte zerlegt.", title, len(created) - 1)
        return created

    @staticmethod
    def suggest_steps(title: str) -> list[str]:
        """Schlägt Teilschritte für eine Aufgabe vor (ohne Sprachmodell)."""

        lowered = title.lower()
        for keywords, steps in _DECOMPOSITION_TEMPLATES.items():
            if any(keyword in lowered for keyword in keywords):
                return list(steps)
        return []

    def next_step(self, project_id: str | None = None) -> MemoryRecord | None:
        """Ermittelt den sinnvollsten nächsten Schritt."""

        return self._memory.tasks.next_step(project_id=project_id)

    def suggest_next_action(self, project_id: str | None = None) -> str:
        """Formuliert einen konkreten Vorschlag für den nächsten Schritt."""

        task = self.next_step(project_id=project_id)
        if task is None:
            return "Es sind derzeit keine offenen Aufgaben verzeichnet."

        subtasks = self._memory.tasks.subtasks(task.id)
        open_subtasks = [
            sub for sub in subtasks if sub.metadata.get("status") != "erledigt"
        ]
        if open_subtasks:
            return (
                f"Nächster Schritt: „{open_subtasks[0].content}“ "
                f"(Teil von „{task.content}“)."
            )
        return f"Nächster Schritt: „{task.content}“."

    def blocked(self, project_id: str | None = None) -> list[MemoryRecord]:
        """Alle blockierten Aufgaben samt Begründung."""

        return [
            task
            for task in self.list(project_id=project_id)
            if task.metadata.get("status") == "blockiert"
        ]

    def overview(self, project_id: str | None = None) -> dict[str, Any]:
        """Aufgabenübersicht für die Transparenzansicht."""

        overview = self._memory.tasks.as_overview(project_id=project_id)
        next_task = self.next_step(project_id=project_id)
        overview["next_step"] = next_task.content if next_task else None
        overview["blocked"] = [
            {"title": task.content, "reason": task.metadata.get("blocked_reason")}
            for task in self.blocked(project_id=project_id)
        ]
        return overview
