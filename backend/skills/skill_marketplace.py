"""Skill Marketplace – der lokale Skill-Katalog.

Der Marketplace ist bewusst **lokal**: Er verwaltet einen Katalog bekannter
Skills, die entweder bereits auf dem Rechner liegen oder aus einer vom
Benutzer eingetragenen Quelle stammen. Es findet **keine automatische
Verbindung zu einem externen Dienst** statt; Quellen werden ausschließlich
vom Benutzer hinzugefügt.

Der Katalog enthält von Beginn an die in der Architekturvorgabe genannten
vorbereiteten Skill-Bereiche (wissenschaftlich, Desktop, Programmierung),
damit der Benutzer sieht, was sich ergänzen lässt.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.system.logging_setup import get_logger
from backend.utils.store import JsonStore
from backend.utils.text import cosine_similarity

logger = get_logger(__name__)


@dataclass
class CatalogEntry:
    """Ein Eintrag im Skill-Katalog."""

    name: str
    title: str
    category: str
    description: str
    capabilities: list[str] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)
    source: str = ""
    installed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "category": self.category,
            "description": self.description,
            "capabilities": self.capabilities,
            "permissions": self.permissions,
            "source": self.source,
            "installed": self.installed,
        }


#: Vorbereitete Skill-Bereiche gemäß Architekturvorgabe. Es handelt sich um
#: Katalogeinträge, nicht um installierte Skills: Sie beschreiben, welche
#: Fähigkeiten sich ergänzen lassen.
_BUILTIN_CATALOG: tuple[CatalogEntry, ...] = (
    CatalogEntry(
        name="zotero",
        title="Zotero",
        category="wissenschaftlich",
        description="Literatur suchen, Einträge lesen, Metadaten importieren, Bibliografie erzeugen, Quellen verbinden.",
        capabilities=["literatur_suchen", "metadaten_import", "bibliografie", "quellen_verbinden"],
        permissions=["file_read", "database"],
    ),
    CatalogEntry(
        name="ocr",
        title="OCR / Texterkennung",
        category="wissenschaftlich",
        description="Text aus Scans und Bildern erkennen, damit Quellen durchsuchbar werden.",
        capabilities=["ocr", "texterkennung"],
        permissions=["file_read", "file_write"],
    ),
    CatalogEntry(
        name="archivsuche",
        title="Archivsuche",
        category="wissenschaftlich",
        description="Digitale Archive und Bestandsverzeichnisse durchsuchen.",
        capabilities=["archivsuche", "quellenanalyse"],
        permissions=["internet"],
    ),
    CatalogEntry(
        name="zitation",
        title="Zitatverwaltung",
        category="wissenschaftlich",
        description="Zitate verwalten, Zitierstile anwenden und Belege prüfen.",
        capabilities=["zitatverwaltung", "textanalyse"],
        permissions=["file_read"],
    ),
    CatalogEntry(
        name="libreoffice",
        title="LibreOffice",
        category="desktop",
        description="Dokumente und Tabellen erstellen, öffnen und exportieren.",
        capabilities=["dokument_erstellen", "dokument_öffnen"],
        permissions=["file_read", "file_write", "system_commands"],
    ),
    CatalogEntry(
        name="gimp",
        title="GIMP",
        category="desktop",
        description="Bilder öffnen und einfache Bearbeitungsschritte ausführen.",
        capabilities=["bildbearbeitung"],
        permissions=["file_read", "file_write", "system_commands"],
    ),
    CatalogEntry(
        name="blender",
        title="Blender",
        category="desktop",
        description="3D-Projekte öffnen und Renderaufträge starten.",
        capabilities=["3d_projekt"],
        permissions=["file_read", "system_commands"],
    ),
    CatalogEntry(
        name="vscode",
        title="Visual Studio Code",
        category="programmierung",
        description="Projekte und Dateien im Editor öffnen, Workspaces verwalten.",
        capabilities=["editor_öffnen", "workspace"],
        permissions=["file_read", "system_commands"],
    ),
    CatalogEntry(
        name="git",
        title="Git",
        category="programmierung",
        description="Repository-Status lesen, Verlauf anzeigen, Branches verwalten.",
        capabilities=["git_status", "git_verlauf"],
        permissions=["file_read", "system_commands"],
    ),
    CatalogEntry(
        name="docker",
        title="Docker",
        category="programmierung",
        description="Container auflisten, starten und stoppen.",
        capabilities=["container_verwalten"],
        permissions=["system_commands"],
    ),
    CatalogEntry(
        name="home-assistant",
        title="Home Assistant",
        category="automatisierung",
        description="Geräte und Automatisierungen im Smart Home ansteuern.",
        capabilities=["smarthome"],
        permissions=["internet"],
    ),
    CatalogEntry(
        name="pdf-analyse",
        title="PDF-Analyse",
        category="wissenschaftlich",
        description="PDFs auslesen, Textstellen finden, Exzerpte erzeugen.",
        capabilities=["pdf_lesen", "exzerpt"],
        permissions=["file_read"],
    ),
)


class SkillMarketplace:
    """Verwaltet den lokalen Skill-Katalog."""

    def __init__(self, filename: str = "skill_catalog.json") -> None:
        self._store = JsonStore(filename, default={"entries": [], "sources": []})
        if not self._store.get("entries"):
            self._store.set("entries", [entry.to_dict() for entry in _BUILTIN_CATALOG])

    def entries(self, *, category: str | None = None) -> list[CatalogEntry]:
        """Listet Katalogeinträge, optional nach Kategorie gefiltert."""

        raw = self._store.get("entries", []) or []
        results = [CatalogEntry(**data) for data in raw if isinstance(data, dict)]
        if category is not None:
            results = [entry for entry in results if entry.category == category]
        results.sort(key=lambda entry: (entry.category, entry.name))
        return results

    def categories(self) -> list[str]:
        """Alle Kategorien im Katalog."""

        return sorted({entry.category for entry in self.entries()})

    def search(self, query: str, limit: int = 5) -> list[CatalogEntry]:
        """Sucht passende Skills zu einer Beschreibung."""

        scored = [
            (entry, cosine_similarity(query, f"{entry.title} {entry.description} {' '.join(entry.capabilities)}"))
            for entry in self.entries()
        ]
        scored = [(entry, score) for entry, score in scored if score > 0.05]
        scored.sort(key=lambda item: item[1], reverse=True)
        return [entry for entry, _ in scored[:limit]]

    def get(self, name: str) -> CatalogEntry | None:
        """Liest einen Katalogeintrag."""

        for entry in self.entries():
            if entry.name == name:
                return entry
        return None

    def add_entry(self, entry: CatalogEntry) -> CatalogEntry:
        """Ergänzt einen eigenen Katalogeintrag."""

        raw = list(self._store.get("entries", []) or [])
        raw = [item for item in raw if item.get("name") != entry.name]
        raw.append(entry.to_dict())
        self._store.set("entries", raw)
        logger.info("Katalogeintrag ergänzt: %s", entry.name)
        return entry

    def mark_installed(self, name: str, installed: bool = True) -> bool:
        """Markiert einen Katalogeintrag als installiert."""

        raw = list(self._store.get("entries", []) or [])
        changed = False
        for item in raw:
            if item.get("name") == name:
                item["installed"] = installed
                changed = True
        if changed:
            self._store.set("entries", raw)
        return changed

    def add_source(self, path: str) -> list[str]:
        """Fügt eine lokale Quelle für Skills hinzu.

        Quellen werden ausschließlich vom Benutzer eingetragen; AI-Orb
        verbindet sich nicht selbstständig mit externen Diensten.
        """

        sources = list(self._store.get("sources", []) or [])
        if path not in sources:
            sources.append(path)
            self._store.set("sources", sources)
        return sources

    def sources(self) -> list[str]:
        """Alle eingetragenen Skill-Quellen."""

        return list(self._store.get("sources", []) or [])

    def suggest_for(self, activity: str, limit: int = 3) -> list[CatalogEntry]:
        """Schlägt Skills passend zu einer beobachteten Tätigkeit vor.

        Wird vom Evolution Agent genutzt: Arbeitet der Benutzer z. B.
        häufig mit PDFs, kann der Orb einen PDF-Analyse-Skill vorschlagen.
        """

        return [entry for entry in self.search(activity, limit=limit) if not entry.installed]
