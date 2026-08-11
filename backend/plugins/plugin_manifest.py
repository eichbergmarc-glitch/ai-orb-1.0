"""Das Manifest eines Plugins.

Jedes Plugin liegt in einem eigenen Ordner und enthält eine Datei
``plugin.yaml``. Darin steht, was das Plugin ist, wer es geschrieben hat,
welche Berechtigungen es verlangt und welche Datei geladen werden soll.

Das Manifest ist die einzige Stelle, an der ein Plugin Berechtigungen
anmelden kann. Es kann sich zur Laufzeit keine weiteren beschaffen: Die
Werkzeuge, die es anmeldet, werden gegen diese Liste geprüft, und was nicht
im Manifest steht, wird abgewiesen.

Ein Manifest wird streng gelesen. Fehlt ein Pflichtfeld, ist die Fassung
unsinnig oder verlangt es eine unbekannte Berechtigung, wird das Plugin gar
nicht erst geladen – und der Grund im Klartext genannt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.security.permissions import get_permission
from backend.system.logging_setup import get_logger

logger = get_logger(__name__)

#: Erlaubte Pluginnamen: Kleinbuchstaben, Ziffern, Bindestrich, Unterstrich.
NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{1,48}$")

#: Fassungsangabe nach dem Muster 1.2.3
VERSION_PATTERN = re.compile(r"^\d+\.\d+(\.\d+)?$")

#: Der Dateiname des Manifests.
MANIFEST_FILENAME = "plugin.yaml"


@dataclass
class PluginManifest:
    """Was ein Plugin über sich selbst angibt."""

    name: str
    version: str
    description: str
    author: str = ""
    #: Die Python-Datei im Pluginordner, die geladen wird.
    entry_point: str = "plugin.py"
    #: Die verlangten Berechtigungen.
    permissions: list[str] = field(default_factory=list)
    #: Ob das Plugin beim Start geladen wird.
    enabled: bool = False
    #: Der Ordner, in dem es liegt.
    directory: Path | None = None
    #: Kürzeste Fassung von AI-Orb, mit der es läuft.
    requires_version: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "entry_point": self.entry_point,
            "permissions": list(self.permissions),
            "enabled": self.enabled,
            "directory": str(self.directory) if self.directory else "",
            "requires_version": self.requires_version,
        }


@dataclass
class ManifestProblem:
    """Warum ein Manifest abgelehnt wurde."""

    field_name: str
    message: str

    def __str__(self) -> str:
        return f"{self.field_name}: {self.message}"


def parse_manifest(directory: Path) -> tuple[PluginManifest | None, list[ManifestProblem]]:
    """Liest und prüft das Manifest eines Pluginordners.

    Args:
        directory: Der Ordner, in dem ``plugin.yaml`` liegt.

    Returns:
        Das Manifest und eine Liste der Beanstandungen. Ist die Liste nicht
        leer, ist das Manifest ``None``.
    """

    problems: list[ManifestProblem] = []
    path = directory / MANIFEST_FILENAME

    if not path.is_file():
        return None, [ManifestProblem(MANIFEST_FILENAME, "Die Datei fehlt.")]

    try:
        import yaml

        with path.open("r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle)
    except Exception as error:  # noqa: BLE001
        return None, [ManifestProblem(MANIFEST_FILENAME, f"Nicht lesbar: {error}")]

    if not isinstance(raw, dict):
        return None, [ManifestProblem(MANIFEST_FILENAME, "Der Inhalt ist kein Verzeichnis von Werten.")]

    name = str(raw.get("name", "")).strip().lower()
    if not name:
        problems.append(ManifestProblem("name", "Fehlt."))
    elif not NAME_PATTERN.match(name):
        problems.append(
            ManifestProblem(
                "name",
                "Erlaubt sind Kleinbuchstaben, Ziffern, Bindestrich und "
                "Unterstrich; er muss mit einem Buchstaben beginnen.",
            )
        )

    version = str(raw.get("version", "")).strip()
    if not version:
        problems.append(ManifestProblem("version", "Fehlt."))
    elif not VERSION_PATTERN.match(version):
        problems.append(ManifestProblem("version", "Erwartet wird etwas wie 1.0 oder 1.0.3."))

    description = str(raw.get("description", "")).strip()
    if len(description) < 10:
        problems.append(
            ManifestProblem(
                "description",
                "Fehlt oder ist zu knapp. Der Benutzer muss vor der Freigabe "
                "verstehen, was das Plugin tut.",
            )
        )

    entry_point = str(raw.get("entry_point", "plugin.py")).strip()
    if not entry_point.endswith(".py"):
        problems.append(ManifestProblem("entry_point", "Muss eine .py-Datei sein."))
    elif "/" in entry_point or "\\" in entry_point or ".." in entry_point:
        # Ein Einstiegspunkt darf nicht aus dem Pluginordner herausführen.
        problems.append(
            ManifestProblem(
                "entry_point",
                "Muss eine Datei direkt im Pluginordner sein, ohne Pfadangabe.",
            )
        )
    elif not (directory / entry_point).is_file():
        problems.append(ManifestProblem("entry_point", f"Die Datei '{entry_point}' fehlt."))

    raw_permissions = raw.get("permissions", []) or []
    permissions: list[str] = []
    if not isinstance(raw_permissions, list):
        problems.append(ManifestProblem("permissions", "Muss eine Liste sein."))
    else:
        for item in raw_permissions:
            permission_name = str(item).strip().lower()
            if not permission_name:
                continue
            if get_permission(permission_name) is None:
                problems.append(
                    ManifestProblem(
                        "permissions",
                        f"'{permission_name}' ist keine bekannte Berechtigung.",
                    )
                )
            else:
                permissions.append(permission_name)

    if problems:
        return None, problems

    return (
        PluginManifest(
            name=name,
            version=version,
            description=description,
            author=str(raw.get("author", "")).strip(),
            entry_point=entry_point,
            permissions=permissions,
            enabled=bool(raw.get("enabled", False)),
            directory=directory,
            requires_version=str(raw.get("requires_version", "")).strip(),
        ),
        [],
    )
