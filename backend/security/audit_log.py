"""Prüfprotokoll aller sicherheitsrelevanten Vorgänge.

Jede Anfrage nach einer Berechtigung, jede Zustimmung, jede Verweigerung und
jede tatsächlich ausgeführte heikle Aktion wird hier festgehalten. Der
Benutzer soll jederzeit nachlesen können, was AI-Orb getan hat und mit
wessen Erlaubnis.

Das Protokoll wird ausschließlich angehängt, nie verändert. Es liegt als
JSON-Lines-Datei in ``data/security/`` – eine Zeile je Eintrag, damit auch
ein abgebrochener Schreibvorgang nur die letzte Zeile beschädigt und nicht
die gesamte Datei.

Das Protokoll verlässt den Rechner nicht.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.system.logging_setup import get_logger
from backend.utils.paths import get_data_dir

logger = get_logger(__name__)


@dataclass
class AuditEntry:
    """Ein einzelner Eintrag im Prüfprotokoll."""

    #: Was geschehen ist, z. B. ``consent.granted`` oder ``action.executed``.
    event: str
    #: Wer die Aktion angefragt hat (Modul, Skill, Plugin, Agent).
    actor: str
    #: Welche Berechtigung betroffen war.
    permission: str = ""
    #: Klartextbeschreibung für die Anzeige.
    detail: str = ""
    #: Ob die Aktion zugelassen wurde.
    allowed: bool | None = None
    #: Zeitstempel (Unix-Sekunden).
    timestamp: float = field(default_factory=time.time)
    #: Beliebige Zusatzangaben.
    context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event": self.event,
            "actor": self.actor,
            "permission": self.permission,
            "detail": self.detail,
            "allowed": self.allowed,
            "timestamp": self.timestamp,
            "time": datetime.fromtimestamp(self.timestamp, tz=timezone.utc)
            .astimezone()
            .strftime("%Y-%m-%d %H:%M:%S"),
            "context": self.context,
        }


class AuditLog:
    """Anhängendes Protokoll sicherheitsrelevanter Vorgänge."""

    def __init__(self, filename: str = "security/audit.jsonl", *, max_entries: int = 5000) -> None:
        """
        Args:
            filename: Pfad relativ zum Datenverzeichnis.
            max_entries: Ab wie vielen Zeilen die ältesten entfernt werden.
                Verhindert, dass das Protokoll unbegrenzt wächst.
        """

        self._path: Path = get_data_dir() / filename
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._max_entries = max(100, max_entries)

    @property
    def path(self) -> Path:
        """Wo das Protokoll liegt."""

        return self._path

    def record(self, entry: AuditEntry) -> None:
        """Hängt einen Eintrag an.

        Ein Fehler beim Schreiben darf den laufenden Vorgang nicht abbrechen;
        er wird protokolliert und ansonsten hingenommen.
        """

        line = json.dumps(entry.to_dict(), ensure_ascii=False, default=str)
        with self._lock:
            try:
                with self._path.open("a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
            except OSError:
                logger.exception("Das Prüfprotokoll konnte nicht geschrieben werden.")
                return
            self._trim_if_needed()

    def _trim_if_needed(self) -> None:
        """Kürzt das Protokoll, wenn es zu lang geworden ist."""

        try:
            with self._path.open("r", encoding="utf-8") as handle:
                lines = handle.readlines()
        except OSError:
            return

        if len(lines) <= self._max_entries:
            return

        keep = lines[-self._max_entries :]
        temporary = self._path.with_suffix(".tmp")
        try:
            with temporary.open("w", encoding="utf-8") as handle:
                handle.writelines(keep)
            temporary.replace(self._path)
        except OSError:
            logger.exception("Das Prüfprotokoll konnte nicht gekürzt werden.")

    def recent(self, limit: int = 50, *, permission: str = "") -> list[dict[str, Any]]:
        """Liest die jüngsten Einträge.

        Args:
            limit: Höchstzahl zurückgegebener Einträge.
            permission: Wenn gesetzt, nur Einträge zu dieser Berechtigung.

        Returns:
            Die Einträge, neueste zuerst.
        """

        with self._lock:
            try:
                with self._path.open("r", encoding="utf-8") as handle:
                    lines = handle.readlines()
            except OSError:
                return []

        entries: list[dict[str, Any]] = []
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                # Eine beschädigte Zeile überspringen, statt alles zu verwerfen.
                continue
            if permission and entry.get("permission") != permission:
                continue
            entries.append(entry)
            if len(entries) >= limit:
                break
        return entries

    def summary(self) -> dict[str, Any]:
        """Kurzüberblick für die Transparenzansicht."""

        entries = self.recent(limit=500)
        granted = sum(1 for entry in entries if entry.get("allowed") is True)
        denied = sum(1 for entry in entries if entry.get("allowed") is False)
        return {
            "path": str(self._path),
            "entries_examined": len(entries),
            "granted": granted,
            "denied": denied,
            "last_event": entries[0].get("time") if entries else "",
        }
