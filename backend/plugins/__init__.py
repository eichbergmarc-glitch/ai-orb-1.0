"""Plugin-System von AI-Orb (v2 Phase 14).

Ein Plugin erweitert AI-Orb um eigene Werkzeuge, ohne dass am Kern etwas
geändert werden muss. Es liegt in einem Ordner unter ``plugins/`` und
besteht aus einem Manifest (``plugin.yaml``) und einer Python-Datei mit
einer Klasse namens ``Plugin``.

Ein Beispiel liegt unter ``plugins/beispiel/``.

Wichtig: Ein Plugin ist fremder Programmcode, der im selben Prozess läuft.
AI-Orb begrenzt, welche Werkzeuge es anmelden darf, und fragt vor dem Laden
um Erlaubnis – aber es kann fremden Code nicht wirklich einsperren. Wer ein
Plugin installiert, sollte seine Herkunft kennen.
"""

from backend.plugins.plugin_base import OrbPlugin, PluginContext
from backend.plugins.plugin_manager import LoadedPlugin, PluginManager
from backend.plugins.plugin_manifest import (
    MANIFEST_FILENAME,
    ManifestProblem,
    PluginManifest,
    parse_manifest,
)

__all__ = [
    "MANIFEST_FILENAME",
    "LoadedPlugin",
    "ManifestProblem",
    "OrbPlugin",
    "PluginContext",
    "PluginManager",
    "PluginManifest",
    "parse_manifest",
]
