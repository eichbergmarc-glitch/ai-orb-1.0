"""Release Manager – kontrollierte Übernahme geprüfter Änderungen.

Nur erfolgreich getestete Änderungen dürfen zur Übernahme vorgeschlagen
werden. Standardmäßig gilt: **Der Benutzer bestätigt vor der Integration.**

Optional lässt sich ein fortgeschrittener Modus einrichten, in dem
Änderungen mit geringem Risiko nach zuvor festgelegten Regeln automatisch
übernommen werden. Dieser Modus ist standardmäßig deaktiviert und muss
ausdrücklich eingeschaltet werden.
"""

from __future__ import annotations

import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend import __version__ as ORB_VERSION
from backend.config import get_config
from backend.evolution.benchmark_engine import BenchmarkComparison
from backend.evolution.patch_generator import Patch
from backend.evolution.review_engine import ReviewReport
from backend.evolution.rollback_manager import RollbackManager
from backend.evolution.testing_engine import TestReport
from backend.system.logging_setup import get_logger
from backend.utils.paths import get_project_root

logger = get_logger(__name__)


@dataclass
class ReleaseCandidate:
    """Ein zur Übernahme vorgeschlagener Patch."""

    patch: Patch
    tests: TestReport
    review: ReviewReport
    benchmark: BenchmarkComparison | None = None
    risk: str = "mittel"
    blockers: list[str] = field(default_factory=list)

    @property
    def is_proposable(self) -> bool:
        """Ob der Patch überhaupt vorgeschlagen werden darf."""

        return not self.blockers

    def to_dict(self) -> dict[str, Any]:
        return {
            "patch": self.patch.to_dict(),
            "tests": self.tests.to_dict(),
            "review": self.review.to_dict(),
            "benchmark": self.benchmark.to_dict() if self.benchmark else None,
            "risk": self.risk,
            "blockers": self.blockers,
            "proposable": self.is_proposable,
        }

    def describe(self) -> str:
        """Formuliert den Vorschlag für den Benutzer."""

        lines = [
            f"Änderungsvorschlag: {self.patch.title}",
            self.patch.description,
            "",
            f"Betroffene Dateien: {', '.join(self.patch.files_changed) or '–'}",
            f"Tests: {self.tests.summary}",
            f"Review: {'bestanden' if self.review.passed else 'nicht bestanden'}",
        ]
        if self.benchmark is not None:
            lines.append(f"Leistung: {self.benchmark.summary()}")
        lines.append(f"Eingeschätztes Risiko: {self.risk}")

        if self.review.uncertainties:
            lines.append("")
            lines.append("Punkte, die ich nicht sicher beurteilen kann:")
            lines.extend(f"  ? {comment.message}" for comment in self.review.uncertainties)

        if self.blockers:
            lines.append("")
            lines.append("Diese Änderung kann nicht übernommen werden:")
            lines.extend(f"  • {blocker}" for blocker in self.blockers)
        else:
            lines.append("")
            lines.append("Soll ich diese Änderung übernehmen?")
        return "\n".join(lines)


class ReleaseManager:
    """Prüft, schlägt vor und übernimmt Änderungen."""

    def __init__(self, rollback: RollbackManager, root: Path | None = None) -> None:
        config = get_config()
        evolution_config = config.section("evolution")

        self._root = root or get_project_root()
        self._rollback = rollback
        self._require_approval = bool(evolution_config.get("require_user_approval", True))
        self._auto_rules = dict(evolution_config.get("auto_apply_rules", {}) or {})
        self._candidates: dict[str, ReleaseCandidate] = {}

    # --- Bewertung ------------------------------------------------------------

    def evaluate(
        self,
        patch: Patch,
        tests: TestReport,
        review: ReviewReport,
        benchmark: BenchmarkComparison | None = None,
    ) -> ReleaseCandidate:
        """Bewertet einen Patch und erstellt einen Übernahmevorschlag.

        Ein Patch wird nur dann vorgeschlagen, wenn Tests und Review
        bestanden wurden und keine Leistungsverschlechterung vorliegt.
        """

        candidate = ReleaseCandidate(patch=patch, tests=tests, review=review, benchmark=benchmark)

        if not tests.passed:
            candidate.blockers.append("Die Tests wurden nicht bestanden.")
        if not review.passed:
            candidate.blockers.append("Das Review hat blockierende Punkte ergeben.")
        if benchmark is not None and not benchmark.is_improvement:
            candidate.blockers.append(
                "Die Änderung verschlechtert die Leistung: " + benchmark.summary()
            )

        candidate.risk = self._assess_risk(patch, review)

        patch.test_status = "bestanden" if tests.passed else "fehlgeschlagen"
        patch.review_status = "bestanden" if review.passed else "fehlgeschlagen"
        patch.benchmark_status = (
            "übersprungen"
            if benchmark is None
            else ("bestanden" if benchmark.is_improvement else "fehlgeschlagen")
        )

        self._candidates[patch.id] = candidate
        logger.info(
            "Patch %s bewertet: %s (Risiko %s).",
            patch.id,
            "vorschlagbar" if candidate.is_proposable else "abgelehnt",
            candidate.risk,
        )
        return candidate

    @staticmethod
    def _assess_risk(patch: Patch, review: ReviewReport) -> str:
        """Schätzt das Risiko einer Änderung ein."""

        changed = len(patch.files_changed)
        diff_lines = len(patch.diff.splitlines())

        if not review.aspects.get("abwärtskompatibilität", True):
            return "hoch"
        if not review.aspects.get("sicherheit", True):
            return "hoch"
        if changed > 5 or diff_lines > 300:
            return "hoch"
        if changed > 2 or diff_lines > 80:
            return "mittel"
        return "gering"

    # --- Übernahme -------------------------------------------------------------

    def may_auto_apply(self, candidate: ReleaseCandidate) -> bool:
        """Prüft, ob eine Änderung nach den festgelegten Regeln automatisch
        übernommen werden darf.

        Standardmäßig ist dies deaktiviert. Der fortgeschrittene Modus muss
        in ``config.yaml`` unter ``evolution.auto_apply_rules`` ausdrücklich
        eingerichtet werden.
        """

        if self._require_approval:
            return False
        if not self._auto_rules.get("enabled", False):
            return False
        if not candidate.is_proposable:
            return False

        allowed_risk = str(self._auto_rules.get("max_risk", "gering"))
        rank = {"gering": 0, "mittel": 1, "hoch": 2}
        if rank.get(candidate.risk, 2) > rank.get(allowed_risk, 0):
            return False

        max_files = int(self._auto_rules.get("max_files", 1))
        if len(candidate.patch.files_changed) > max_files:
            return False

        allowed_categories = set(self._auto_rules.get("categories", []) or [])
        if allowed_categories and candidate.patch.idea_id:
            # Ohne bekannte Kategorie wird nicht automatisch übernommen.
            return False

        return True

    def apply(self, patch_id: str, *, confirmed: bool = False) -> dict[str, Any]:
        """Übernimmt eine geprüfte Änderung in die produktive Codebasis.

        Vor der Übernahme wird ein Wiederherstellungspunkt angelegt, sodass
        die Änderung jederzeit vollständig rückgängig gemacht werden kann.
        """

        candidate = self._candidates.get(patch_id)
        if candidate is None:
            return {"applied": False, "message": "Unbekannter Änderungsvorschlag."}

        if not candidate.is_proposable:
            return {
                "applied": False,
                "message": "Diese Änderung darf nicht übernommen werden.",
                "blockers": candidate.blockers,
            }

        if not confirmed and not self.may_auto_apply(candidate):
            return {
                "applied": False,
                "requires_confirmation": True,
                "message": candidate.describe(),
            }

        patch = candidate.patch
        point = self._rollback.create_point(
            patch_id=patch.id,
            title=patch.title,
            description=patch.description,
            branch=patch.branch,
            commit=patch.base_commit,
            version=ORB_VERSION,
            files=patch.files_changed,
            test_summary=candidate.tests.summary,
        )

        workspace = Path(patch.workspace)
        applied: list[str] = []
        failed: list[str] = []

        for relative in patch.files_changed:
            source = workspace / relative
            destination = self._root / relative
            if not source.exists():
                failed.append(relative)
                continue
            try:
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
                applied.append(relative)
            except OSError as error:
                logger.error("Übernahme von %s fehlgeschlagen: %s", relative, error)
                failed.append(relative)

        if failed and applied:
            logger.warning("Teilweise Übernahme – setze zurück.")
            self._rollback.rollback(point.id)
            return {
                "applied": False,
                "message": "Die Übernahme war unvollständig und wurde zurückgesetzt.",
                "failed_files": failed,
            }

        logger.info("Patch %s übernommen (%d Datei(en)).", patch.id, len(applied))
        return {
            "applied": True,
            "patch_id": patch.id,
            "restore_point": point.id,
            "applied_files": applied,
            "message": (
                f"Die Änderung „{patch.title}“ wurde übernommen. "
                f"Du kannst sie jederzeit mit dem Wiederherstellungspunkt {point.id} "
                "rückgängig machen. Ein Neustart von AI-Orb aktiviert die Änderung."
            ),
        }

    def pending(self) -> list[ReleaseCandidate]:
        """Alle bewerteten, noch nicht übernommenen Vorschläge."""

        return [candidate for candidate in self._candidates.values() if candidate.is_proposable]

    def reject(self, patch_id: str) -> bool:
        """Verwirft einen Vorschlag."""

        return self._candidates.pop(patch_id, None) is not None
