"""Evolution Engine – die kontrollierte Selbstverbesserung von AI-Orb.

Der Orb analysiert kontinuierlich seine Architektur, entwickelt
Verbesserungsvorschläge, erstellt getestete Patches, bewertet deren Qualität
und schlägt sie kontrolliert zur Übernahme vor.

Die Sicherheitsregeln sind fest eingebaut und nicht umgehbar:

* Keine automatische Änderung an produktiven Dateien.
* Keine automatische Installation von Abhängigkeiten.
* Keine Ausführung unbekannter Skripte ohne Freigabe.
* Keine Übertragung von Quellcode an externe Dienste ohne ausdrückliche
  Zustimmung des Benutzers.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.config import get_config
from backend.evolution.architecture_analyzer import ArchitectureAnalyzer
from backend.evolution.benchmark_engine import BenchmarkEngine
from backend.evolution.bug_detector import BugDetector
from backend.evolution.code_analyzer import CodeAnalyzer
from backend.evolution.idea_generator import Idea, IdeaGenerator
from backend.evolution.patch_generator import Patch, PatchGenerator
from backend.evolution.performance_analyzer import PerformanceAnalyzer
from backend.evolution.release_manager import ReleaseCandidate, ReleaseManager
from backend.evolution.review_engine import ReviewEngine
from backend.evolution.rollback_manager import RollbackManager
from backend.evolution.skill_trainer import SkillTrainer
from backend.evolution.testing_engine import TestingEngine
from backend.system.logging_setup import get_logger

logger = get_logger(__name__)


@dataclass
class EvolutionState:
    """Der aktuelle Stand der Selbstverbesserung."""

    last_analysis: float = 0.0
    ideas: list[Idea] = field(default_factory=list)
    patches: dict[str, Patch] = field(default_factory=dict)
    candidates: dict[str, ReleaseCandidate] = field(default_factory=dict)


class EvolutionEngine:
    """Zentrale Steuerung der Selbstverbesserung."""

    def __init__(self, root: Path | None = None) -> None:
        config = get_config()
        self._evolution_config = config.section("evolution")

        self.code = CodeAnalyzer(root)
        self.architecture = ArchitectureAnalyzer(root)
        self.performance = PerformanceAnalyzer(root)
        self.bugs = BugDetector()
        self.ideas = IdeaGenerator()
        self.patches = PatchGenerator(root)
        self.tests = TestingEngine()
        self.benchmarks = BenchmarkEngine()
        self.review = ReviewEngine()
        self.rollback = RollbackManager(root)
        self.releases = ReleaseManager(self.rollback, root)
        self.skills = SkillTrainer(root)

        self._state = EvolutionState()
        self._allow_external = bool(
            self._evolution_config.get("allow_external_code_transfer", False)
        )
        self._auto_install = bool(
            self._evolution_config.get("auto_install_dependencies", False)
        )

    # --- Analyse --------------------------------------------------------------

    def analyze(self, *, usage: dict[str, Any] | None = None) -> dict[str, Any]:
        """Führt die vollständige Selbstanalyse durch.

        Args:
            usage: Beobachtetes Nutzungsverhalten für Skill-Vorschläge.

        Returns:
            Ein Bericht mit allen Befunden und Verbesserungsideen.
        """

        started = time.perf_counter()

        code_report = self.code.analyze()
        architecture_report = self.architecture.analyze().to_dict()
        performance_report = self.performance.analyze()
        self.bugs.scan_logs()
        bug_summary = self.bugs.summary()

        ideas = self.ideas.generate(
            code_report=code_report,
            architecture_report=architecture_report,
            performance_report=performance_report,
            bug_summary=bug_summary,
            usage=usage,
        )
        self._state.ideas = ideas
        self._state.last_analysis = time.time()

        findings = (
            list(code_report.get("findings", []))
            + list(architecture_report.get("findings", []))
            + list(performance_report.get("findings", []))
        )

        logger.info(
            "Selbstanalyse in %.1f s abgeschlossen: %d Befunde, %d Ideen.",
            time.perf_counter() - started,
            len(findings),
            len(ideas),
        )

        return {
            "findings": findings,
            "ideas": [idea.to_dict() for idea in ideas],
            "code": {
                "modules": len(code_report.get("modules", [])),
                "lines": code_report.get("total_lines", 0),
                "documentation": code_report.get("average_documentation", 0.0),
            },
            "architecture": {
                "maintainability": architecture_report.get("maintainability", 0.0),
                "cycles": len(architecture_report.get("cycles", [])),
            },
            "performance": performance_report.get("suggestions", []),
            "bugs": bug_summary,
            "analyzed_at": self._state.last_analysis,
        }

    def top_ideas(self, limit: int = 5) -> list[dict[str, Any]]:
        """Die aussichtsreichsten Verbesserungsideen."""

        return [idea.to_dict() for idea in self._state.ideas[:limit]]

    # --- Patches ---------------------------------------------------------------

    def prepare_patch(
        self, *, title: str, description: str, changes: dict[str, str], idea_id: str = ""
    ) -> dict[str, Any]:
        """Erzeugt einen Patch in einer isolierten Arbeitskopie.

        Die produktive Codebasis bleibt dabei unverändert.
        """

        patch = self.patches.create_patch(
            title=title, description=description, changes=changes, idea_id=idea_id
        )
        self._state.patches[patch.id] = patch
        return patch.to_dict()

    def validate_patch(self, patch_id: str, *, run_benchmark: bool = True) -> dict[str, Any]:
        """Testet, prüft und bewertet einen Patch.

        Erst wenn alle Prüfungen bestanden sind, darf der Patch zur
        Übernahme vorgeschlagen werden.
        """

        patch = self._state.patches.get(patch_id)
        if patch is None:
            return {"validated": False, "message": "Unbekannter Patch."}

        workspace = Path(patch.workspace)
        test_report = self.tests.run_all(
            workspace, changed_files=patch.files_changed
        )
        review_report = self.review.review(patch)
        benchmark = self.benchmarks.compare(workspace) if run_benchmark else None

        candidate = self.releases.evaluate(patch, test_report, review_report, benchmark)
        self._state.candidates[patch.id] = candidate

        return {
            "validated": True,
            "proposable": candidate.is_proposable,
            "risk": candidate.risk,
            "summary": candidate.describe(),
            "details": candidate.to_dict(),
        }

    def pending_patches(self) -> list[dict[str, Any]]:
        """Alle geprüften, noch nicht übernommenen Patches."""

        return [
            {
                "id": candidate.patch.id,
                "title": candidate.patch.title,
                "branch": candidate.patch.branch,
                "risk": candidate.risk,
                "test_status": candidate.patch.test_status,
                "review_status": candidate.patch.review_status,
                "files": candidate.patch.files_changed,
            }
            for candidate in self.releases.pending()
        ]

    def apply_patch(self, patch_id: str, *, confirmed: bool = False) -> dict[str, Any]:
        """Übernimmt einen geprüften Patch – standardmäßig nur nach Bestätigung."""

        return self.releases.apply(patch_id, confirmed=confirmed)

    def discard_patch(self, patch_id: str) -> dict[str, Any]:
        """Verwirft einen Patch samt Arbeitskopie."""

        patch = self._state.patches.pop(patch_id, None)
        if patch is None:
            return {"discarded": False, "message": "Unbekannter Patch."}
        self.releases.reject(patch_id)
        self._state.candidates.pop(patch_id, None)
        self.patches.discard(patch)
        return {"discarded": True, "message": f"Patch {patch_id} wurde verworfen."}

    def undo_last_change(self) -> dict[str, Any]:
        """Macht die zuletzt übernommene Änderung rückgängig."""

        return self.rollback.undo_last()

    # --- Skills ------------------------------------------------------------------

    def propose_skill(self, name: str, reason: str = "") -> dict[str, Any]:
        """Schlägt einen neuen Skill vor und erzeugt dessen Entwurf.

        Der Entwurf wird nur erstellt, nicht installiert – der Benutzer
        entscheidet.
        """

        draft = self.skills.create_draft(name)
        return {
            "proposed": True,
            "draft": draft.to_dict(),
            "reason": reason,
            "message": (
                f"Ich habe einen Entwurf für den Skill „{name}“ vorbereitet "
                f"({draft.path}). Er ist noch nicht installiert – sieh ihn dir an "
                "und sag mir, ob ich ihn einrichten soll."
            ),
        }

    # --- Sicherheit ------------------------------------------------------------------

    def security_policy(self) -> dict[str, Any]:
        """Die geltenden Sicherheitsregeln der Evolution Engine."""

        return {
            "keine_automatische_änderung_produktiver_dateien": True,
            "automatische_abhängigkeitsinstallation": self._auto_install,
            "ausführung_unbekannter_skripte": False,
            "quellcode_an_externe_dienste": self._allow_external,
            "benutzerbestätigung_erforderlich": bool(
                self._evolution_config.get("require_user_approval", True)
            ),
            "arbeitsverzeichnis": str(self.patches.workspace_root),
        }

    # --- Transparenz ------------------------------------------------------------------

    def report(self) -> dict[str, Any]:
        """Beantwortet die Transparenzfragen zur Selbstverbesserung.

        Welche Verbesserungen wurden gefunden? Welche Patches sind bereit?
        Welche Tests wurden durchgeführt? Welche Risiken bestehen? Warum
        wird eine Änderung empfohlen?
        """

        candidates = self.releases.pending()
        return {
            "letzte_analyse": self._state.last_analysis,
            "gefundene_verbesserungen": [idea.to_dict() for idea in self._state.ideas[:10]],
            "bereite_patches": [
                {
                    "id": candidate.patch.id,
                    "titel": candidate.patch.title,
                    "begründung": candidate.patch.description,
                    "tests": candidate.tests.summary,
                    "review": "bestanden" if candidate.review.passed else "offen",
                    "risiko": candidate.risk,
                    "leistung": candidate.benchmark.summary() if candidate.benchmark else "nicht gemessen",
                    "unsicherheiten": [
                        comment.message for comment in candidate.review.uncertainties
                    ],
                }
                for candidate in candidates
            ],
            "bekannte_fehler": self.bugs.top_issues(),
            "wiederherstellungspunkte": self.rollback.list(limit=5),
            "sicherheitsregeln": self.security_policy(),
        }
