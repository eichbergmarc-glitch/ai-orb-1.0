"""Bug Detector – erkennt und gruppiert Fehler.

Analysiert werden Logs, Ausnahmen, Abstürze, Benutzerfeedback und
fehlgeschlagene Aktionen. Ähnliche Fehler werden zusammengefasst und nach
Häufigkeit und Schwere priorisiert.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.system.logging_setup import get_logger
from backend.utils.paths import get_logs_dir
from backend.utils.store import JsonStore
from backend.utils.text import cosine_similarity

logger = get_logger(__name__)

_LOG_LINE = re.compile(
    r"^(?P<time>[\d\-: ]{19})\s+\|\s+(?P<level>\w+)\s+\|\s+(?P<module>[\w.]+)\s+\|\s+(?P<message>.*)$"
)

#: Ab dieser Ähnlichkeit gelten zwei Fehlermeldungen als derselbe Fehler.
_GROUPING_THRESHOLD = 0.75


@dataclass
class BugGroup:
    """Eine Gruppe gleichartiger Fehler."""

    signature: str
    message: str
    module: str
    level: str
    count: int = 1
    first_seen: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    samples: list[str] = field(default_factory=list)
    user_reports: int = 0

    @property
    def priority(self) -> str:
        """Priorität aus Schwere und Häufigkeit."""

        score = self.count + self.user_reports * 3
        if self.level in ("CRITICAL", "ERROR") and score >= 5:
            return "hoch"
        if self.level in ("CRITICAL", "ERROR") or score >= 10:
            return "mittel"
        return "gering"

    def to_dict(self) -> dict[str, Any]:
        return {
            "signature": self.signature,
            "message": self.message,
            "module": self.module,
            "level": self.level,
            "count": self.count,
            "user_reports": self.user_reports,
            "priority": self.priority,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "samples": self.samples[:3],
        }


class BugDetector:
    """Sammelt, gruppiert und priorisiert Fehler."""

    def __init__(self, filename: str = "bugs.json") -> None:
        self._store = JsonStore(filename, default={"groups": [], "last_scan": 0.0})
        self._groups: list[BugGroup] = [
            BugGroup(**{key: value for key, value in data.items() if key in BugGroup.__dataclass_fields__})
            for data in (self._store.get("groups", []) or [])
            if isinstance(data, dict)
        ]

    # --- Erfassung ------------------------------------------------------------

    def scan_logs(self, *, max_lines: int = 5000) -> int:
        """Durchsucht die Log-Dateien nach Fehlern und Warnungen.

        Returns:
            Anzahl neu erfasster Fehlereinträge.
        """

        logs_dir = get_logs_dir()
        found = 0
        last_scan = float(self._store.get("last_scan", 0.0) or 0.0)

        for log_file in sorted(logs_dir.glob("*.log")):
            try:
                lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue

            for line in lines[-max_lines:]:
                match = _LOG_LINE.match(line)
                if match is None:
                    continue
                level = match.group("level").strip()
                if level not in ("ERROR", "CRITICAL", "WARNING"):
                    continue

                timestamp = self._parse_time(match.group("time").strip())
                if timestamp <= last_scan:
                    continue

                self.report(
                    message=match.group("message").strip(),
                    module=match.group("module").strip(),
                    level=level,
                    timestamp=timestamp,
                )
                found += 1

        self._store.set("last_scan", time.time())
        self._persist()
        if found:
            logger.info("Bug Detector: %d neue Fehlereinträge erfasst.", found)
        return found

    def report(
        self,
        *,
        message: str,
        module: str = "",
        level: str = "ERROR",
        timestamp: float | None = None,
        from_user: bool = False,
    ) -> BugGroup:
        """Erfasst einen einzelnen Fehler und gruppiert ihn.

        Args:
            message: Die Fehlermeldung.
            module: Das betroffene Modul.
            level: Schweregrad.
            timestamp: Zeitpunkt des Auftretens.
            from_user: Ob die Meldung vom Benutzer stammt (Feedback wiegt
                schwerer als ein reiner Logeintrag).
        """

        when = timestamp or time.time()
        normalized = self._normalize(message)

        for group in self._groups:
            if group.module == module and cosine_similarity(group.signature, normalized) >= _GROUPING_THRESHOLD:
                group.count += 1
                group.last_seen = when
                if from_user:
                    group.user_reports += 1
                if len(group.samples) < 5:
                    group.samples.append(message[:200])
                self._persist()
                return group

        group = BugGroup(
            signature=normalized,
            message=message[:200],
            module=module,
            level=level,
            first_seen=when,
            last_seen=when,
            samples=[message[:200]],
            user_reports=1 if from_user else 0,
        )
        self._groups.append(group)
        self._persist()
        return group

    def report_user_feedback(self, description: str) -> BugGroup:
        """Nimmt eine Fehlermeldung des Benutzers auf."""

        return self.report(message=description, module="benutzerfeedback", from_user=True)

    def report_failed_action(self, action: str, reason: str) -> BugGroup:
        """Erfasst eine fehlgeschlagene Aktion."""

        return self.report(message=f"Aktion '{action}' fehlgeschlagen: {reason}", module="aktion")

    # --- Auswertung ------------------------------------------------------------

    def groups(self, *, priority: str | None = None) -> list[BugGroup]:
        """Alle Fehlergruppen, nach Priorität und Häufigkeit sortiert."""

        rank = {"hoch": 0, "mittel": 1, "gering": 2}
        groups = list(self._groups)
        if priority is not None:
            groups = [group for group in groups if group.priority == priority]
        groups.sort(key=lambda group: (rank.get(group.priority, 3), -group.count))
        return groups

    def top_issues(self, limit: int = 5) -> list[dict[str, Any]]:
        """Die dringendsten Fehler."""

        return [group.to_dict() for group in self.groups()[:limit]]

    def resolve(self, signature: str) -> bool:
        """Markiert eine Fehlergruppe als behoben und entfernt sie."""

        before = len(self._groups)
        self._groups = [group for group in self._groups if group.signature != signature]
        changed = len(self._groups) != before
        if changed:
            self._persist()
        return changed

    def summary(self) -> dict[str, Any]:
        """Zusammenfassung für die Transparenzansicht."""

        groups = self.groups()
        return {
            "total_groups": len(groups),
            "by_priority": {
                priority: sum(1 for group in groups if group.priority == priority)
                for priority in ("hoch", "mittel", "gering")
            },
            "top": [group.to_dict() for group in groups[:5]],
        }

    # --- Hilfsfunktionen ----------------------------------------------------------

    def _persist(self) -> None:
        self._store.set("groups", [group.to_dict() for group in self._groups])

    @staticmethod
    def _normalize(message: str) -> str:
        """Entfernt variable Bestandteile, damit gleichartige Fehler zusammenfallen."""

        text = re.sub(r"0x[0-9a-fA-F]+", "<adresse>", message)
        text = re.sub(r"\b\d+\b", "<zahl>", text)
        text = re.sub(r"['\"][^'\"]{0,80}['\"]", "<wert>", text)
        text = re.sub(r"[A-Za-z]:\\[^\s]+|/[^\s]+/[^\s]+", "<pfad>", text)
        return text.strip()

    @staticmethod
    def _parse_time(value: str) -> float:
        try:
            return time.mktime(time.strptime(value, "%Y-%m-%d %H:%M:%S"))
        except (ValueError, OverflowError):
            return 0.0
