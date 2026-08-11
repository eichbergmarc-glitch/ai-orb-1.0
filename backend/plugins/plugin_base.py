"""Die Schnittstelle, die ein Plugin erfüllen muss.

Ein Plugin ist eine Python-Datei, die eine Klasse namens ``Plugin`` enthält,
die von :class:`OrbPlugin` erbt. Mehr wird nicht verlangt: kein Framework,
keine Anmeldung, keine Konfigurationsdatei über das Manifest hinaus.

Das Plugin bekommt beim Laden einen :class:`PluginContext`. Darin steckt
alles, was es darf – und nichts weiter. Es bekommt insbesondere **keinen**
Zugriff auf die Sicherheitsschicht selbst, sondern nur auf die
Werkzeuganmeldung. Der Grund: Ein Plugin, das die Sicherheitsschicht in der
Hand hält, könnte sich selbst freigeben.

Die Lebensphasen sind bewusst wenige. ``setup`` beim Laden, ``teardown``
beim Entladen. Wer mehr braucht, meldet Werkzeuge an oder hört Ereignisse
ab.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from backend.tools.base_tool import Tool


@dataclass
class PluginContext:
    """Was ein Plugin von AI-Orb bekommt."""

    #: Der Name des Plugins, wie er im Manifest steht.
    name: str
    #: Der eigene Ordner. Dorthin darf das Plugin schreiben.
    directory: Path
    #: Ein eigener Datenordner unter ``data/plugins/<name>/``.
    data_directory: Path
    #: Die im Manifest angemeldeten Berechtigungen.
    permissions: list[str]
    #: Meldet ein Werkzeug an. Gibt zurück, ob es angenommen wurde.
    register_tool: Callable[[Tool], bool]
    #: Meldet einen Ereignishorcher an.
    subscribe: Callable[[str, Callable[..., Any]], None]
    #: Schreibt eine Zeile ins Protokoll des Plugins.
    log: Callable[[str], None]
    #: Die Fassung von AI-Orb.
    orb_version: str = ""

    def has_permission(self, name: str) -> bool:
        """Ob das Plugin diese Berechtigung angemeldet hat."""

        return name.strip().lower() in self.permissions


class OrbPlugin(abc.ABC):
    """Grundgerüst eines Plugins."""

    def __init__(self, context: PluginContext) -> None:
        self.context = context

    @abc.abstractmethod
    async def setup(self) -> None:
        """Wird beim Laden aufgerufen.

        Hier meldet das Plugin seine Werkzeuge und Ereignishorcher an. Wirft
        die Methode einen Fehler, gilt das Plugin als nicht geladen und wird
        wieder entfernt.
        """

    async def teardown(self) -> None:
        """Wird beim Entladen aufgerufen.

        Hier räumt das Plugin auf: offene Dateien schließen, Hintergrund-
        aufgaben beenden. Die Standardfassung tut nichts.
        """

        return None

    def info(self) -> dict[str, Any]:
        """Zusätzliche Angaben für die Transparenzansicht."""

        return {}
