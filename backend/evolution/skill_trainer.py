"""Skill Trainer – erzeugt neue Fähigkeiten als Plugins.

Neue Fähigkeiten werden nicht in den Kern programmiert, sondern als Skills
entwickelt. Der Trainer erzeugt das vollständige Gerüst eines Skills mit
Beschreibung, Berechtigungen, Tests, Dokumentation und Versionierung.

Der erzeugte Skill wird in einem Entwurfsverzeichnis abgelegt und **nicht
automatisch installiert**: Der Benutzer entscheidet, ob er ihn übernimmt.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.config import get_config
from backend.system.logging_setup import get_logger
from backend.utils.paths import get_project_root

logger = get_logger(__name__)

#: Vorbereitete Skill-Entwürfe gemäß Architekturvorgabe.
SKILL_TEMPLATES: dict[str, dict[str, Any]] = {
    "zotero": {
        "description": "Literatur suchen, Einträge lesen, Metadaten importieren, Bibliografie erzeugen.",
        "capabilities": ["literatur_suchen", "metadaten_import", "bibliografie"],
        "permissions": ["file_read", "database"],
    },
    "libreoffice": {
        "description": "Dokumente und Tabellen öffnen, erstellen und exportieren.",
        "capabilities": ["dokument_öffnen", "dokument_erstellen"],
        "permissions": ["file_read", "file_write", "system_commands"],
    },
    "gimp": {
        "description": "Bilder öffnen und Bearbeitungsschritte anstoßen.",
        "capabilities": ["bildbearbeitung"],
        "permissions": ["file_read", "file_write", "system_commands"],
    },
    "blender": {
        "description": "3D-Projekte öffnen und Renderaufträge starten.",
        "capabilities": ["3d_projekt"],
        "permissions": ["file_read", "system_commands"],
    },
    "vscode": {
        "description": "Projekte und Dateien im Editor öffnen.",
        "capabilities": ["editor_öffnen", "workspace"],
        "permissions": ["file_read", "system_commands"],
    },
    "docker": {
        "description": "Container auflisten, starten und stoppen.",
        "capabilities": ["container_verwalten"],
        "permissions": ["system_commands"],
    },
    "git": {
        "description": "Repository-Status lesen, Verlauf anzeigen, Branches verwalten.",
        "capabilities": ["git_status", "git_verlauf"],
        "permissions": ["file_read", "system_commands"],
    },
    "home-assistant": {
        "description": "Geräte und Automatisierungen im Smart Home ansteuern.",
        "capabilities": ["smarthome"],
        "permissions": ["internet"],
    },
    "pdf-analyse": {
        "description": "PDFs auslesen, Textstellen finden und Exzerpte erzeugen.",
        "capabilities": ["pdf_lesen", "exzerpt"],
        "permissions": ["file_read"],
    },
}

_SKILL_SOURCE_TEMPLATE = '''"""{title} – Skill für AI-Orb.

{description}

Dieser Skill kommuniziert ausschließlich über die Skill-API mit AI-Orb.
Direkte Systemzugriffe finden nur im Rahmen der erteilten Berechtigungen
statt.
"""

from __future__ import annotations

from typing import Any


class {class_name}:
    """Stellt die Fähigkeiten dieses Skills bereit."""

    def __init__(self, api: Any) -> None:
        """
        Args:
            api: Die Skill-API von AI-Orb. Über sie erfolgen Protokollierung,
                Gedächtniszugriffe und Ereignismeldungen.
        """

        self.api = api

    def setup(self) -> None:
        """Wird beim Aktivieren des Skills aufgerufen."""

        self.api.log("{title} wurde aktiviert.")

    def teardown(self) -> None:
        """Wird beim Deaktivieren des Skills aufgerufen."""

        self.api.log("{title} wurde deaktiviert.")

{handlers}

def create_skill(api: Any) -> {class_name}:
    """Erzeugt die Skill-Instanz. AI-Orb ruft diese Funktion beim Laden auf."""

    return {class_name}(api)
'''

_HANDLER_TEMPLATE = '''    def handle_{capability}(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Bearbeitet die Fähigkeit „{capability}“.

        Args:
            payload: Die Eingabedaten der Anfrage.

        Returns:
            Das Ergebnis der Fähigkeit.
        """

{permission_checks}
        # TODO_IMPLEMENTIERUNG entfernt: Dieser Entwurf meldet ausdrücklich,
        # dass die Umsetzung noch aussteht, statt stillschweigend nichts zu tun.
        return {{
            "success": False,
            "message": (
                "Die Fähigkeit „{capability}“ ist in diesem Entwurf noch nicht "
                "umgesetzt. Ergänze die Umsetzung in dieser Funktion."
            ),
            "payload": payload,
        }}

'''

_TEST_TEMPLATE = '''"""Tests für den Skill „{name}“."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from skill import create_skill


class _FakeApi:
    """Minimale Skill-API für Tests."""

    def __init__(self) -> None:
        self.messages: list[str] = []
        self.granted = {permissions!r}

    def log(self, message: str) -> None:
        self.messages.append(message)

    def has_permission(self, permission: str) -> bool:
        return permission in self.granted

    def require_permission(self, permission: str) -> None:
        if permission not in self.granted:
            raise PermissionError(permission)


def test_skill_can_be_created():
    skill = create_skill(_FakeApi())
    assert skill is not None


def test_setup_logs_activation():
    api = _FakeApi()
    skill = create_skill(api)
    skill.setup()
    assert api.messages


{capability_tests}'''

_CAPABILITY_TEST_TEMPLATE = '''def test_handle_{capability}_returns_result():
    skill = create_skill(_FakeApi())
    result = skill.handle_{capability}({{}})
    assert isinstance(result, dict)
    assert "success" in result

'''


@dataclass
class SkillDraft:
    """Der Entwurf eines neuen Skills."""

    name: str
    path: str
    capabilities: list[str] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "path": self.path,
            "capabilities": self.capabilities,
            "permissions": self.permissions,
            "created_at": self.created_at,
        }


class SkillTrainer:
    """Erzeugt vollständige Skill-Gerüste."""

    def __init__(self, root: Path | None = None) -> None:
        config = get_config()
        evolution_config = config.section("evolution")

        self._root = root or get_project_root()
        self._draft_dir = self._root / str(
            evolution_config.get("workspace_directory", "data/evolution")
        ) / "skill_drafts"
        self._draft_dir.mkdir(parents=True, exist_ok=True)

    @property
    def draft_directory(self) -> Path:
        """Verzeichnis, in dem Skill-Entwürfe abgelegt werden."""

        return self._draft_dir

    def available_templates(self) -> list[str]:
        """Namen aller vorbereiteten Skill-Vorlagen."""

        return sorted(SKILL_TEMPLATES)

    def create_draft(
        self,
        name: str,
        *,
        description: str = "",
        capabilities: list[str] | None = None,
        permissions: list[str] | None = None,
        author: str = "AI-Orb Evolution",
    ) -> SkillDraft:
        """Erzeugt das vollständige Gerüst eines Skills.

        Args:
            name: Name des Skills (Kleinbuchstaben, Bindestriche erlaubt).
            description: Beschreibung; fehlt sie, wird die Vorlage genutzt.
            capabilities: Fähigkeiten; fehlen sie, wird die Vorlage genutzt.
            permissions: Berechtigungen; fehlen sie, wird die Vorlage genutzt.
            author: Autor des Skills.

        Returns:
            Der erzeugte Entwurf. Er ist **nicht** installiert.
        """

        template = SKILL_TEMPLATES.get(name, {})
        description = description or str(template.get("description", f"Skill {name} für AI-Orb."))
        capability_list = capabilities or list(template.get("capabilities", ["ausführen"]))
        permission_list = permissions or list(template.get("permissions", []))

        target = self._draft_dir / name
        target.mkdir(parents=True, exist_ok=True)

        manifest = {
            "name": name,
            "version": "0.1.0",
            "description": description,
            "author": author,
            "permissions": permission_list,
            "dependencies": [],
            "capabilities": capability_list,
            "entrypoint": "skill.py",
            "min_orb_version": "0.1.0",
            "documentation": f"Siehe README.md im Verzeichnis des Skills „{name}“.",
            "configuration": {},
        }
        (target / "skill.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        (target / "skill.py").write_text(
            self._render_source(name, description, capability_list, permission_list),
            encoding="utf-8",
        )

        (target / "test_skill.py").write_text(
            self._render_tests(name, capability_list, permission_list), encoding="utf-8"
        )

        (target / "README.md").write_text(
            self._render_readme(name, description, capability_list, permission_list),
            encoding="utf-8",
        )

        (target / "CHANGELOG.md").write_text(
            f"# Changelog\n\n## 0.1.0\n\n- Erster Entwurf des Skills „{name}“.\n",
            encoding="utf-8",
        )

        logger.info("Skill-Entwurf erzeugt: %s (%s)", name, target)
        return SkillDraft(
            name=name,
            path=str(target),
            capabilities=capability_list,
            permissions=permission_list,
        )

    # --- Rendering -------------------------------------------------------------

    @staticmethod
    def _class_name(name: str) -> str:
        return "".join(part.capitalize() for part in name.replace("-", "_").split("_")) + "Skill"

    def _render_source(
        self, name: str, description: str, capabilities: list[str], permissions: list[str]
    ) -> str:
        handlers = ""
        for capability in capabilities:
            checks = "\n".join(
                f'        self.api.require_permission("{permission}")'
                for permission in permissions
            )
            handlers += _HANDLER_TEMPLATE.format(
                capability=self._safe(capability),
                permission_checks=checks or "        # Dieser Skill benötigt keine besonderen Rechte.",
            )

        return _SKILL_SOURCE_TEMPLATE.format(
            title=name,
            description=description,
            class_name=self._class_name(name),
            handlers=handlers,
        )

    def _render_tests(self, name: str, capabilities: list[str], permissions: list[str]) -> str:
        capability_tests = "".join(
            _CAPABILITY_TEST_TEMPLATE.format(capability=self._safe(capability))
            for capability in capabilities
        )
        return _TEST_TEMPLATE.format(
            name=name, permissions=permissions, capability_tests=capability_tests
        )

    @staticmethod
    def _render_readme(
        name: str, description: str, capabilities: list[str], permissions: list[str]
    ) -> str:
        lines = [
            f"# Skill: {name}",
            "",
            description,
            "",
            "## Fähigkeiten",
            "",
        ]
        lines.extend(f"- `{capability}`" for capability in capabilities)
        lines.extend(["", "## Berechtigungen", ""])
        if permissions:
            lines.extend(f"- `{permission}`" for permission in permissions)
        else:
            lines.append("Dieser Skill benötigt keine besonderen Rechte.")
        lines.extend(
            [
                "",
                "## Installation",
                "",
                "Dieser Entwurf ist noch nicht installiert. AI-Orb legt Entwürfe unter",
                "`data/evolution/skill_drafts/` ab. Prüfe den Code, ergänze die",
                "Umsetzung der Fähigkeiten und lasse den Skill anschließend von AI-Orb",
                "installieren.",
                "",
                "## Tests",
                "",
                "```",
                "pytest test_skill.py",
                "```",
            ]
        )
        return "\n".join(lines)

    @staticmethod
    def _safe(value: str) -> str:
        """Wandelt einen Fähigkeitsnamen in einen gültigen Bezeichner um."""

        cleaned = "".join(char if char.isalnum() else "_" for char in value)
        return cleaned if cleaned[:1].isalpha() or cleaned.startswith("_") else f"f_{cleaned}"

    def list_drafts(self) -> list[dict[str, Any]]:
        """Alle vorhandenen Skill-Entwürfe."""

        drafts: list[dict[str, Any]] = []
        for candidate in self._draft_dir.iterdir():
            manifest_file = candidate / "skill.json"
            if not candidate.is_dir() or not manifest_file.exists():
                continue
            try:
                manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            drafts.append({"path": str(candidate), **manifest})
        return drafts
