"""Patch Generator – erzeugt Änderungen in einer isolierten Umgebung.

Kernregel: **Die produktive Codebasis wird niemals direkt verändert.**

Für jede Änderung wird
* ein eigener Git-Branch angelegt,
* ein Patch erzeugt,
* eine Beschreibung geschrieben,
* eine Testvorbereitung getroffen.

Gearbeitet wird ausschließlich in einer Kopie des Projekts unterhalb von
``data/evolution``. Erst nach erfolgreichen Tests und ausdrücklicher
Bestätigung des Benutzers kann eine Änderung übernommen werden.
"""

from __future__ import annotations

import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.config import get_config
from backend.system.logging_setup import get_logger
from backend.utils.paths import get_project_root

logger = get_logger(__name__)


@dataclass
class Patch:
    """Ein vorbereiteter, noch nicht übernommener Änderungssatz."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    title: str = ""
    description: str = ""
    idea_id: str = ""
    branch: str = ""
    diff: str = ""
    files_changed: list[str] = field(default_factory=list)
    workspace: str = ""
    base_commit: str = ""
    test_status: str = "ausstehend"
    review_status: str = "ausstehend"
    benchmark_status: str = "ausstehend"
    created_at: float = field(default_factory=time.time)

    @property
    def is_ready(self) -> bool:
        """Ob der Patch zur Übernahme vorgeschlagen werden darf."""

        return (
            self.test_status == "bestanden"
            and self.review_status == "bestanden"
            and self.benchmark_status in ("bestanden", "übersprungen")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "idea_id": self.idea_id,
            "branch": self.branch,
            "files_changed": self.files_changed,
            "workspace": self.workspace,
            "base_commit": self.base_commit,
            "test_status": self.test_status,
            "review_status": self.review_status,
            "benchmark_status": self.benchmark_status,
            "ready": self.is_ready,
            "created_at": self.created_at,
            "diff_lines": len(self.diff.splitlines()),
        }


class PatchGenerator:
    """Erzeugt Patches in einer isolierten Arbeitskopie."""

    def __init__(self, root: Path | None = None) -> None:
        config = get_config()
        evolution_config = config.section("evolution")

        self._root = root or get_project_root()
        self._workspace_root = self._root / str(
            evolution_config.get("workspace_directory", "data/evolution")
        )
        self._workspace_root.mkdir(parents=True, exist_ok=True)

    @property
    def workspace_root(self) -> Path:
        """Wurzelverzeichnis aller Entwicklungs-Arbeitskopien."""

        return self._workspace_root

    # --- Arbeitskopie ---------------------------------------------------------

    def create_workspace(self, patch_id: str) -> Path:
        """Legt eine isolierte Arbeitskopie des Projekts an.

        Kopiert werden ausschließlich Quellcode und Konfiguration – keine
        Benutzerdaten, Logs oder Modelle.
        """

        workspace = self._workspace_root / patch_id
        if workspace.exists():
            shutil.rmtree(workspace)
        workspace.mkdir(parents=True)

        for name in ("backend", "tests", "desktop"):
            source = self._root / name
            if source.exists():
                shutil.copytree(
                    source,
                    workspace / name,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "dist", "node_modules"),
                )
        for name in ("config.yaml", "requirements.txt", "pytest.ini", "conftest.py"):
            source = self._root / name
            if source.exists():
                shutil.copy2(source, workspace / name)

        logger.info("Arbeitskopie angelegt: %s", workspace)
        return workspace

    # --- Git ------------------------------------------------------------------

    def _git(self, workspace: Path, *args: str) -> tuple[bool, str]:
        """Führt einen Git-Befehl in der Arbeitskopie aus."""

        try:
            result = subprocess.run(  # noqa: S603 - feste Argumentliste, kein Shell-Aufruf.
                ["git", *args],
                cwd=str(workspace),
                capture_output=True,
                text=True,
                timeout=60,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            return False, str(error)
        output = (result.stdout or "") + (result.stderr or "")
        return result.returncode == 0, output.strip()

    def _ensure_repository(self, workspace: Path) -> str:
        """Stellt sicher, dass die Arbeitskopie ein Git-Repository ist."""

        if not (workspace / ".git").exists():
            self._git(workspace, "init")
            self._git(workspace, "config", "user.email", "evolution@ai-orb.local")
            self._git(workspace, "config", "user.name", "AI-Orb Evolution")
            self._git(workspace, "add", ".")
            self._git(workspace, "commit", "-m", "Ausgangszustand")
        ok, commit = self._git(workspace, "rev-parse", "HEAD")
        return commit if ok else ""

    # --- Patch erzeugen ---------------------------------------------------------

    def create_patch(
        self,
        *,
        title: str,
        description: str,
        changes: dict[str, str],
        idea_id: str = "",
    ) -> Patch:
        """Erzeugt einen Patch aus einer Menge von Dateiänderungen.

        Args:
            title: Kurzbeschreibung der Änderung.
            description: Ausführliche Begründung.
            changes: Abbildung von relativem Dateipfad auf neuen Inhalt.
            idea_id: Die zugrunde liegende Idee.

        Returns:
            Der erzeugte Patch – noch **nicht** übernommen.
        """

        patch = Patch(title=title, description=description, idea_id=idea_id)
        patch.branch = f"evolution/{patch.id}"

        workspace = self.create_workspace(patch.id)
        patch.workspace = str(workspace)
        patch.base_commit = self._ensure_repository(workspace)

        self._git(workspace, "checkout", "-b", patch.branch)

        for relative_path, content in changes.items():
            target = workspace / relative_path
            if not target.resolve().is_relative_to(workspace.resolve()):
                logger.error("Patch versucht, außerhalb der Arbeitskopie zu schreiben: %s", relative_path)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            patch.files_changed.append(relative_path)

        self._git(workspace, "add", ".")
        ok, diff = self._git(workspace, "diff", "--cached")
        patch.diff = diff if ok else ""

        self._git(workspace, "commit", "-m", f"{title}\n\n{description}")

        logger.info(
            "Patch %s erzeugt (%d Datei(en), Branch %s).",
            patch.id,
            len(patch.files_changed),
            patch.branch,
        )
        return patch

    def discard(self, patch: Patch) -> bool:
        """Verwirft einen Patch samt Arbeitskopie."""

        workspace = Path(patch.workspace)
        if workspace.exists() and workspace.is_relative_to(self._workspace_root):
            shutil.rmtree(workspace, ignore_errors=True)
            logger.info("Patch %s verworfen.", patch.id)
            return True
        return False

    def diff_for(self, patch: Patch) -> str:
        """Gibt den vollständigen Diff eines Patches zurück."""

        return patch.diff or "(keine Änderungen)"
