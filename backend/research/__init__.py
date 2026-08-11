"""Forschungsassistent (Phase 11).

Unterstützt wissenschaftliches Arbeiten mit Schwerpunkt Geschichte:
Quellenkritik, Forschungsfragen, Thesenprüfung, Argumentationsprüfung,
Gliederungen.

Der Leitsatz: Der Orb schreibt keine Arbeiten. Er stellt Rückfragen, zeigt
Lücken und benennt Gegenpositionen.
"""

from backend.research.research_engine import ResearchEngine, ThesisReview
from backend.research.source_criticism import (
    EXTERNAL_QUESTIONS,
    INTERNAL_QUESTIONS,
    SECONDARY_QUESTIONS,
    SourceAssessment,
    SourceCriticism,
    SourceKind,
)

__all__ = [
    "EXTERNAL_QUESTIONS",
    "INTERNAL_QUESTIONS",
    "SECONDARY_QUESTIONS",
    "ResearchEngine",
    "SourceAssessment",
    "SourceCriticism",
    "SourceKind",
    "ThesisReview",
]
