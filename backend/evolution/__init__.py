"""Evolution Engine von AI-Orb (v3 Phase 4).

Der Orb verbessert seine eigenen Fähigkeiten kontrolliert weiter: Er
analysiert Code, Architektur, Leistung und Fehler, entwickelt begründete
Verbesserungsideen, erzeugt getestete Patches in einer isolierten
Entwicklungsumgebung, bewertet sie und schlägt sie zur Übernahme vor.

Die produktive Codebasis wird niemals automatisch verändert. Jede Änderung
ist nachvollziehbar, testbar, reproduzierbar und vollständig rückgängig zu
machen.
"""

from backend.evolution.architecture_analyzer import ArchitectureAnalyzer, ArchitectureReport
from backend.evolution.benchmark_engine import BenchmarkComparison, BenchmarkEngine
from backend.evolution.bug_detector import BugDetector, BugGroup
from backend.evolution.code_analyzer import CodeAnalyzer, Finding, ModuleReport
from backend.evolution.evolution_engine import EvolutionEngine
from backend.evolution.idea_generator import Idea, IdeaGenerator
from backend.evolution.patch_generator import Patch, PatchGenerator
from backend.evolution.performance_analyzer import PerformanceAnalyzer
from backend.evolution.release_manager import ReleaseCandidate, ReleaseManager
from backend.evolution.review_engine import ReviewEngine, ReviewReport
from backend.evolution.rollback_manager import RestorePoint, RollbackManager
from backend.evolution.skill_trainer import SkillDraft, SkillTrainer
from backend.evolution.testing_engine import TestingEngine, TestReport

__all__ = [
    "ArchitectureAnalyzer",
    "ArchitectureReport",
    "BenchmarkComparison",
    "BenchmarkEngine",
    "BugDetector",
    "BugGroup",
    "CodeAnalyzer",
    "EvolutionEngine",
    "Finding",
    "Idea",
    "IdeaGenerator",
    "ModuleReport",
    "Patch",
    "PatchGenerator",
    "PerformanceAnalyzer",
    "ReleaseCandidate",
    "ReleaseManager",
    "RestorePoint",
    "ReviewEngine",
    "ReviewReport",
    "RollbackManager",
    "SkillDraft",
    "SkillTrainer",
    "TestReport",
    "TestingEngine",
]
