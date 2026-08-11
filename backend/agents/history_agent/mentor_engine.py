"""Betreuung wissenschaftlicher Arbeiten (Abschnitte 15, 16, 29).

Der Unterschied zwischen einem Korrektor und einem Betreuer ist die Zeit.
Ein Korrektor sieht einen Text; ein Betreuer sieht ein Vorhaben über
Monate und erinnert sich, dass die Fragestellung dreimal gewechselt hat
und warum.

Deshalb ist ein Projekt hier ein dauerhafter Gegenstand: Fragestellung,
These, Gliederung, Quellen, Literatur, offene Probleme, nächste Schritte.
Er liegt beim Benutzer als lesbares JSON, damit er ihn selbst einsehen und
ändern kann.

Die Prüfungen sind bewusst formal – ob eine These gut ist, entscheidet
kein Programm. Ob eine These überhaupt vorhanden ist, ob eine Gliederung
einen roten Faden hat, ob Quellen genannt sind: das schon.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.system.logging_setup import get_logger
from backend.utils.paths import get_data_dir

logger = get_logger(__name__)

#: Die Fragen, die ein Forschungsbetreuer stellt (Abschnitt 29).
SUPERVISOR_QUESTIONS: tuple[str, ...] = (
    "Was ist deine zentrale These?",
    "Welche Forschungslücke bearbeitest du?",
    "Welche Quellenbasis hast du – und ist sie dir zugänglich?",
    "Welche Gegenposition gibt es in der Forschung?",
    "Welche Methode verwendest du?",
    "Warum ist diese Methode für diese Frage geeignet?",
    "Was würde deine These widerlegen?",
    "Welche Grenzen hat deine Untersuchung?",
)

#: Was ein Projekt an Angaben führt.
PROJECT_FIELDS: tuple[str, ...] = (
    "thema", "forschungsfrage", "these", "gliederung", "methode",
    "quellen", "literatur", "notizen", "offene_probleme", "naechste_schritte",
)


@dataclass(slots=True)
class Project:
    """Eine betreute Arbeit."""

    name: str
    fields: dict[str, str] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    history: list[dict[str, Any]] = field(default_factory=list)

    def set(self, key: str, value: str) -> None:
        """Trägt eine Angabe ein und merkt sich die vorherige.

        Die Vorgeschichte ist kein Beiwerk: Dass eine Fragestellung sich
        dreimal geändert hat, ist selbst ein Befund – meist der, dass das
        Thema noch nicht steht.
        """

        old = self.fields.get(key, "")
        if old and old != value:
            self.history.append(
                {"zeitpunkt": time.time(), "feld": key, "vorher": old}
            )
        self.fields[key] = value
        self.updated_at = time.time()

    @property
    def missing(self) -> list[str]:
        return [key for key in PROJECT_FIELDS if not self.fields.get(key, "").strip()]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "felder": self.fields,
            "angelegt": self.created_at,
            "geaendert": self.updated_at,
            "verlauf": self.history[-30:],
            "fehlt": self.missing,
        }


class MentorEngine:
    """Verwaltet betreute Arbeiten."""

    def __init__(self, directory: Path | None = None) -> None:
        self.directory = directory or (get_data_dir() / "professor" / "projekte")
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, name: str) -> Path:
        safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in name).strip()
        return self.directory / f"{safe.lower().replace(' ', '_')}.json"

    def load(self, name: str) -> Project | None:
        path = self._path(name)
        if not path.is_file():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            logger.warning("Projekt %s nicht lesbar: %s", name, error)
            return None
        return Project(
            name=str(raw.get("name", name)),
            fields={k: str(v) for k, v in (raw.get("felder") or {}).items()},
            created_at=float(raw.get("angelegt", time.time())),
            updated_at=float(raw.get("geaendert", time.time())),
            history=list(raw.get("verlauf") or []),
        )

    def save(self, project: Project) -> bool:
        try:
            self._path(project.name).write_text(
                json.dumps(project.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return True
        except OSError as error:
            logger.error("Projekt %s nicht speicherbar: %s", project.name, error)
            return False

    def create(self, name: str) -> Project:
        project = self.load(name) or Project(name=name.strip())
        self.save(project)
        logger.info("Projekt betreut: %s", project.name)
        return project

    def list_projects(self) -> list[str]:
        return sorted(
            path.stem.replace("_", " ") for path in self.directory.glob("*.json")
        )

    def context(self, project: Project) -> str:
        """Das Projekt als knapper Kontext für den Systemprompt."""

        parts = [f"Betreute Arbeit: {project.name}."]
        for key in ("forschungsfrage", "these", "methode"):
            value = project.fields.get(key, "").strip()
            if value:
                parts.append(f"{key.capitalize()}: {value[:200]}")

        offen = project.fields.get("offene_probleme", "").strip()
        if offen:
            parts.append(f"Offen: {offen[:200]}")

        if project.missing:
            parts.append("Noch nicht festgelegt: " + ", ".join(project.missing) + ".")

        # Häufige Wechsel der Fragestellung sind ein eigener Befund.
        wechsel = sum(1 for e in project.history if e.get("feld") == "forschungsfrage")
        if wechsel >= 2:
            parts.append(
                f"Die Fragestellung wurde bereits {wechsel}-mal geändert – "
                "das Thema steht möglicherweise noch nicht."
            )

        return " ".join(parts)

    def next_question(self, project: Project) -> str:
        """Die nächste Betreuerfrage.

        Gefragt wird nach dem, was fehlt – in der Reihenfolge, in der es
        gebraucht wird. Nach der Methode zu fragen, bevor die Frage steht,
        wäre verfrüht.
        """

        reihenfolge = (
            ("forschungsfrage", "Wie lautet deine Forschungsfrage – in einem Satz?"),
            ("these", "Was ist deine zentrale These? Welche Antwort erwartest du?"),
            ("quellen", "Welche Quellenbasis hast du, und ist sie dir zugänglich?"),
            ("methode", "Welche Methode verwendest du, und warum ist sie geeignet?"),
            ("gliederung", "Wie ist die Arbeit gegliedert?"),
            ("literatur", "Welche Forschungsliteratur hast du gesichtet?"),
        )

        for key, frage in reihenfolge:
            if not project.fields.get(key, "").strip():
                return frage

        return "Was würde deine These widerlegen?"
