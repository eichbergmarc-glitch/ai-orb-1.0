"""Projekterkennung – erkennt Projekte anhand von Ordnern und Dateien.

Der Detektor untersucht ein Verzeichnis und erkennt daran, worum es sich
handelt: Git-Repository, VS-Code-Workspace, Dokumentensammlung,
PDF-/Literaturordner, Schreibprojekt oder Forschungsprojekt.

Ist die automatische Erkennung unsicher, wird dies ausdrücklich vermerkt,
damit der Orb nachfragen oder eine manuelle Zuordnung anbieten kann statt
zu raten.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.system.logging_setup import get_logger

logger = get_logger(__name__)

#: Dateiendungen je Projektart.
_CODE_EXTENSIONS = {".py", ".ts", ".js", ".rs", ".go", ".java", ".c", ".cpp", ".cs", ".rb"}
_DOCUMENT_EXTENSIONS = {".docx", ".doc", ".odt", ".md", ".txt", ".rtf", ".tex"}
_LITERATURE_EXTENSIONS = {".pdf", ".epub", ".bib", ".ris"}


@dataclass
class DetectionResult:
    """Das Ergebnis einer Projekterkennung."""

    path: str
    detected: bool
    kind: str = "unbekannt"
    name: str = ""
    confidence: str = "niedrig"
    signals: list[str] = field(default_factory=list)
    file_counts: dict[str, int] = field(default_factory=dict)

    @property
    def needs_confirmation(self) -> bool:
        """Ob der Orb nachfragen sollte, statt automatisch zuzuordnen."""

        return self.confidence != "hoch"

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "detected": self.detected,
            "kind": self.kind,
            "name": self.name,
            "confidence": self.confidence,
            "signals": self.signals,
            "file_counts": self.file_counts,
            "needs_confirmation": self.needs_confirmation,
        }


class ProjectDetector:
    """Erkennt Projekte anhand ihres Verzeichnisinhalts."""

    def __init__(self, max_files: int = 2000) -> None:
        self._max_files = max_files

    def detect(self, path: str | Path) -> DetectionResult:
        """Untersucht ein Verzeichnis und bestimmt die Projektart.

        Args:
            path: Zu untersuchendes Verzeichnis.

        Returns:
            Das Erkennungsergebnis. Bei niedriger Sicherheit sollte der Orb
            nachfragen (siehe :attr:`DetectionResult.needs_confirmation`).
        """

        root = Path(path).expanduser().resolve()
        result = DetectionResult(path=str(root), detected=False, name=root.name)

        if not root.exists() or not root.is_dir():
            result.signals.append("Verzeichnis existiert nicht.")
            return result

        counts = {"code": 0, "document": 0, "literature": 0, "other": 0}
        signals: list[str] = []

        if (root / ".git").exists():
            signals.append("Git-Repository")
        if any(root.glob("*.code-workspace")):
            signals.append("VS-Code-Workspace")
        if (root / ".vscode").exists():
            signals.append("VS-Code-Konfiguration")
        for marker in ("package.json", "pyproject.toml", "requirements.txt", "Cargo.toml", "go.mod"):
            if (root / marker).exists():
                signals.append(f"Projektdatei {marker}")
        if any(root.glob("*.tex")):
            signals.append("LaTeX-Dokument")
        if (root / "Zotero").exists() or any(root.glob("*.bib")):
            signals.append("Literaturverwaltung")

        scanned = 0
        try:
            for candidate in root.rglob("*"):
                if scanned >= self._max_files:
                    signals.append("Verzeichnis sehr groß – nur teilweise untersucht.")
                    break
                if not candidate.is_file():
                    continue
                if any(part.startswith(".") for part in candidate.parts):
                    continue
                scanned += 1
                suffix = candidate.suffix.lower()
                if suffix in _CODE_EXTENSIONS:
                    counts["code"] += 1
                elif suffix in _DOCUMENT_EXTENSIONS:
                    counts["document"] += 1
                elif suffix in _LITERATURE_EXTENSIONS:
                    counts["literature"] += 1
                else:
                    counts["other"] += 1
        except (PermissionError, OSError) as error:
            signals.append(f"Verzeichnis nur teilweise lesbar ({error.__class__.__name__}).")

        result.file_counts = counts
        result.signals = signals

        kind, confidence = self._classify(counts, signals)
        result.kind = kind
        result.confidence = confidence
        result.detected = kind != "unbekannt"

        logger.info(
            "Projekterkennung für %s: %s (%s)", root, result.kind, result.confidence
        )
        return result

    @staticmethod
    def _classify(counts: dict[str, int], signals: list[str]) -> tuple[str, str]:
        """Leitet Projektart und Sicherheit aus Signalen und Dateizahlen ab."""

        has_repo = any("Git" in signal or "Projektdatei" in signal for signal in signals)
        code = counts["code"]
        documents = counts["document"]
        literature = counts["literature"]

        if has_repo and code >= 3:
            return "software", "hoch"
        if code >= 10 and code > documents + literature:
            return "software", "mittel"
        if literature >= 8 and literature > documents:
            return "forschung", "hoch" if literature >= 20 else "mittel"
        if documents >= 5 and documents >= literature:
            return "schreibprojekt", "hoch" if documents >= 15 else "mittel"
        if literature >= 3 or documents >= 2:
            return "dokumentensammlung", "niedrig"
        if has_repo:
            return "software", "niedrig"
        return "unbekannt", "niedrig"

    def suggest_name(self, path: str | Path) -> str:
        """Schlägt einen Projektnamen anhand des Ordnernamens vor."""

        return Path(path).expanduser().name.replace("_", " ").replace("-", " ").strip()
