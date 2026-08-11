"""Verzeichnis der verfügbaren Werkzeuge.

Hält fest, welche Werkzeuge es gibt, und stellt sicher, dass jedes davon
brauchbar ist, bevor es dem Sprachmodell überhaupt angeboten wird. Geprüft
wird bei der Anmeldung, nicht beim Aufruf – ein Werkzeug mit einer
unbekannten Berechtigung soll gar nicht erst im Angebot erscheinen, statt
später an der Sicherheitsschicht zu scheitern.

Werkzeuge können auch von Plugins kommen. Damit ein Plugin nicht ein
vorhandenes Werkzeug überschreiben und so dessen Namen kapern kann, wird ein
doppelter Name abgewiesen.
"""

from __future__ import annotations

from typing import Any

from backend.security.permissions import get_permission
from backend.system.logging_setup import get_logger
from backend.tools.base_tool import Tool

logger = get_logger(__name__)


class ToolRegistry:
    """Verwaltet die angemeldeten Werkzeuge."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self._sources: dict[str, str] = {}

    # --- Anmeldung ---------------------------------------------------------------

    def register(self, tool: Tool, *, source: str = "eingebaut") -> bool:
        """Meldet ein Werkzeug an.

        Args:
            tool: Das Werkzeug.
            source: Woher es stammt – ``eingebaut``, ein Skill- oder
                Pluginname. Wird in der Transparenzansicht gezeigt.

        Returns:
            ``True``, wenn es aufgenommen wurde.
        """

        name = tool.name.strip().lower()

        if not name or name == "unbenannt":
            logger.warning("Ein Werkzeug ohne Namen wurde abgewiesen (%s).", source)
            return False

        if name in self._tools:
            logger.warning(
                "Das Werkzeug '%s' aus '%s' wurde abgewiesen: Der Name ist "
                "bereits von '%s' belegt.",
                name,
                source,
                self._sources.get(name, "unbekannt"),
            )
            return False

        if get_permission(tool.permission) is None:
            logger.warning(
                "Das Werkzeug '%s' aus '%s' wurde abgewiesen: Es verlangt die "
                "unbekannte Berechtigung '%s'.",
                name,
                source,
                tool.permission,
            )
            return False

        if not tool.description.strip():
            logger.warning(
                "Das Werkzeug '%s' aus '%s' wurde abgewiesen: Ohne Beschreibung "
                "kann das Sprachmodell nicht wissen, wozu es gut ist.",
                name,
                source,
            )
            return False

        self._tools[name] = tool
        self._sources[name] = source
        logger.debug("Werkzeug angemeldet: %s (%s)", name, source)
        return True

    def register_many(self, tools: list[Tool], *, source: str = "eingebaut") -> int:
        """Meldet mehrere Werkzeuge an.

        Returns:
            Wie viele aufgenommen wurden.
        """

        return sum(1 for tool in tools if self.register(tool, source=source))

    def unregister(self, name: str) -> bool:
        """Meldet ein Werkzeug ab. Wird beim Entladen eines Plugins gebraucht."""

        key = name.strip().lower()
        if key not in self._tools:
            return False
        self._tools.pop(key, None)
        self._sources.pop(key, None)
        logger.debug("Werkzeug abgemeldet: %s", key)
        return True

    def unregister_source(self, source: str) -> int:
        """Meldet alle Werkzeuge einer Herkunft ab.

        Returns:
            Wie viele abgemeldet wurden.
        """

        names = [name for name, origin in self._sources.items() if origin == source]
        for name in names:
            self.unregister(name)
        return len(names)

    # --- Zugriff -----------------------------------------------------------------

    def get(self, name: str) -> Tool | None:
        """Sucht ein Werkzeug."""

        return self._tools.get(name.strip().lower())

    def all(self) -> list[Tool]:
        """Alle angemeldeten Werkzeuge."""

        return list(self._tools.values())

    def names(self) -> list[str]:
        """Die Namen aller Werkzeuge."""

        return sorted(self._tools)

    def by_permission(self, permission: str) -> list[Tool]:
        """Alle Werkzeuge, die eine bestimmte Berechtigung verlangen."""

        return [tool for tool in self._tools.values() if tool.permission == permission]

    # --- Beschreibung -------------------------------------------------------------

    def describe_for_model(self) -> str:
        """Beschreibt alle Werkzeuge so, wie sie dem Sprachmodell gezeigt werden."""

        return "\n".join(tool.describe_for_model() for tool in self._tools.values())

    def catalog(self) -> list[dict[str, Any]]:
        """Alle Werkzeuge als Datensätze, für die Transparenzansicht."""

        entries = []
        for name, tool in sorted(self._tools.items()):
            entry = tool.to_dict()
            entry["source"] = self._sources.get(name, "")
            permission = get_permission(tool.permission)
            entry["risk"] = permission.risk.value if permission else "unbekannt"
            entries.append(entry)
        return entries

    def status(self) -> dict[str, Any]:
        """Statusangaben."""

        by_source: dict[str, int] = {}
        for source in self._sources.values():
            by_source[source] = by_source.get(source, 0) + 1
        return {"count": len(self._tools), "by_source": by_source, "names": self.names()}

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: object) -> bool:
        return str(name).strip().lower() in self._tools
