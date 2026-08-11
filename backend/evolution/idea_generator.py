"""Idea Generator – erzeugt begründete Verbesserungsvorschläge.

Erzeugt werden Vorschläge für Refactorings, neue Skills, allgemeine
Verbesserungen, Oberflächenideen, Automatisierungen und
Leistungsoptimierungen.

**Jede Idee wird begründet.** Vorschläge ohne nachvollziehbaren Anlass
werden nicht erzeugt.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from backend.system.logging_setup import get_logger

logger = get_logger(__name__)

#: Die Arten von Ideen gemäß Architekturvorgabe.
IDEA_TYPES: tuple[str, ...] = (
    "refactoring",
    "neuer_skill",
    "verbesserung",
    "ui",
    "automatisierung",
    "leistung",
)


@dataclass
class Idea:
    """Ein einzelner Verbesserungsvorschlag."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    type: str = "verbesserung"
    title: str = ""
    rationale: str = ""
    evidence: list[str] = field(default_factory=list)
    impact: str = "mittel"
    effort: str = "mittel"
    location: str = ""
    created_at: float = field(default_factory=time.time)

    @property
    def score(self) -> float:
        """Bewertung aus erwartetem Nutzen und Aufwand."""

        impact_value = {"hoch": 3.0, "mittel": 2.0, "gering": 1.0}.get(self.impact, 2.0)
        effort_value = {"gering": 1.0, "mittel": 2.0, "hoch": 3.0}.get(self.effort, 2.0)
        return impact_value / effort_value

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "title": self.title,
            "rationale": self.rationale,
            "evidence": self.evidence,
            "impact": self.impact,
            "effort": self.effort,
            "location": self.location,
            "score": round(self.score, 2),
            "created_at": self.created_at,
        }

    def describe(self) -> str:
        """Formuliert die Idee samt Begründung."""

        lines = [f"{self.title}", f"Begründung: {self.rationale}"]
        if self.evidence:
            lines.append("Grundlage: " + "; ".join(self.evidence[:3]))
        lines.append(f"Erwarteter Nutzen: {self.impact}, geschätzter Aufwand: {self.effort}.")
        return "\n".join(lines)


class IdeaGenerator:
    """Leitet Verbesserungsvorschläge aus den Analyseergebnissen ab."""

    def generate(
        self,
        *,
        code_report: dict[str, Any] | None = None,
        architecture_report: dict[str, Any] | None = None,
        performance_report: dict[str, Any] | None = None,
        bug_summary: dict[str, Any] | None = None,
        usage: dict[str, Any] | None = None,
    ) -> list[Idea]:
        """Erzeugt Ideen aus allen vorliegenden Analysen.

        Args:
            code_report: Ergebnis des Code Analyzers.
            architecture_report: Ergebnis des Architecture Analyzers.
            performance_report: Ergebnis des Performance Analyzers.
            bug_summary: Zusammenfassung des Bug Detectors.
            usage: Beobachtete Nutzung (z. B. häufige Dateitypen),
                Grundlage für Skill-Vorschläge.

        Returns:
            Nach Nutzen-Aufwand-Verhältnis sortierte Ideen.
        """

        ideas: list[Idea] = []
        ideas.extend(self._from_code(code_report or {}))
        ideas.extend(self._from_architecture(architecture_report or {}))
        ideas.extend(self._from_performance(performance_report or {}))
        ideas.extend(self._from_bugs(bug_summary or {}))
        ideas.extend(self._from_usage(usage or {}))

        ideas.sort(key=lambda idea: idea.score, reverse=True)
        logger.info("Idea Generator: %d Vorschläge erzeugt.", len(ideas))
        return ideas

    # --- Ableitungen ----------------------------------------------------------

    @staticmethod
    def _from_code(report: dict[str, Any]) -> list[Idea]:
        ideas: list[Idea] = []
        findings = report.get("findings", []) or []

        long_functions = [f for f in findings if f.get("category") == "funktionslänge"]
        if len(long_functions) >= 3:
            ideas.append(
                Idea(
                    type="refactoring",
                    title=f"{len(long_functions)} überlange Funktionen aufteilen",
                    rationale=(
                        "Lange Funktionen sind schwerer zu testen und zu ändern; "
                        "kleinere Einheiten senken das Fehlerrisiko."
                    ),
                    evidence=[f["location"] for f in long_functions[:3]],
                    impact="mittel",
                    effort="mittel",
                    location=long_functions[0]["location"],
                )
            )

        undocumented = [f for f in findings if f.get("category") == "dokumentation"]
        documentation = float(report.get("average_documentation", 1.0))
        if documentation < 0.9 and undocumented:
            ideas.append(
                Idea(
                    type="verbesserung",
                    title="Fehlende Dokumentation ergänzen",
                    rationale=(
                        f"Nur {int(documentation * 100)} % der Funktionen sind dokumentiert. "
                        "Vollständige Docstrings erleichtern spätere Änderungen erheblich."
                    ),
                    evidence=[f["location"] for f in undocumented[:3]],
                    impact="mittel",
                    effort="gering",
                )
            )

        missing_tests = [f for f in findings if f.get("category") == "tests"]
        if missing_tests:
            ideas.append(
                Idea(
                    type="verbesserung",
                    title="Testabdeckung erweitern",
                    rationale=(
                        "Ohne Tests kann nicht sicher festgestellt werden, ob eine "
                        "Änderung bestehende Funktionen beeinträchtigt."
                    ),
                    evidence=[f["message"] for f in missing_tests[:2]],
                    impact="hoch",
                    effort="mittel",
                )
            )

        duplicates = [f for f in findings if f.get("category") == "duplikat"]
        if duplicates:
            ideas.append(
                Idea(
                    type="refactoring",
                    title="Wiederholte Strukturen zusammenfassen",
                    rationale=(
                        "Mehrfach vorkommende Abläufe müssen bei Änderungen an "
                        "mehreren Stellen gepflegt werden."
                    ),
                    evidence=[f["location"] for f in duplicates[:2]],
                    impact="gering",
                    effort="mittel",
                )
            )

        return ideas

    @staticmethod
    def _from_architecture(report: dict[str, Any]) -> list[Idea]:
        ideas: list[Idea] = []
        cycles = report.get("cycles", []) or []

        if cycles:
            ideas.append(
                Idea(
                    type="refactoring",
                    title=f"{len(cycles)} zyklische Abhängigkeit(en) auflösen",
                    rationale=(
                        "Zyklen erschweren Tests und Wiederverwendung und können zu "
                        "Importfehlern führen."
                    ),
                    evidence=[" → ".join(cycle) for cycle in cycles[:2]],
                    impact="hoch",
                    effort="hoch",
                )
            )

        maintainability = float(report.get("maintainability", 1.0))
        if maintainability < 0.7:
            ideas.append(
                Idea(
                    type="refactoring",
                    title="Wartbarkeit der Architektur verbessern",
                    rationale=(
                        f"Die Wartbarkeitskennzahl liegt bei {maintainability:.2f}. "
                        "Klarere Schnittstellen senken den Änderungsaufwand."
                    ),
                    impact="hoch",
                    effort="hoch",
                )
            )
        return ideas

    @staticmethod
    def _from_performance(report: dict[str, Any]) -> list[Idea]:
        ideas: list[Idea] = []
        findings = report.get("findings", []) or []

        blocking = [f for f in findings if f.get("category") == "blockierend"]
        if blocking:
            ideas.append(
                Idea(
                    type="leistung",
                    title="Blockierende Aufrufe auslagern",
                    rationale=(
                        "Blockierende Aufrufe in asynchronem Code lassen die "
                        "Oberfläche stocken."
                    ),
                    evidence=[f["location"] for f in blocking[:3]],
                    impact="hoch",
                    effort="gering",
                    location=blocking[0]["location"],
                )
            )

        background = [f for f in findings if f.get("category") == "hintergrundlast"]
        if background:
            ideas.append(
                Idea(
                    type="leistung",
                    title="Unnötige Hintergrundlast vermeiden",
                    rationale="Dauerlast ohne Wartepunkt verbraucht spürbar CPU-Zeit.",
                    evidence=[f["location"] for f in background[:2]],
                    impact="hoch",
                    effort="gering",
                )
            )
        return ideas

    @staticmethod
    def _from_bugs(summary: dict[str, Any]) -> list[Idea]:
        ideas: list[Idea] = []
        for issue in (summary.get("top", []) or [])[:3]:
            if issue.get("priority") == "gering":
                continue
            ideas.append(
                Idea(
                    type="verbesserung",
                    title=f"Wiederkehrenden Fehler beheben: {issue.get('message', '')[:60]}",
                    rationale=(
                        f"Dieser Fehler ist bereits {issue.get('count', 0)}-mal aufgetreten "
                        f"(Priorität {issue.get('priority')})."
                    ),
                    evidence=issue.get("samples", [])[:2],
                    impact="hoch" if issue.get("priority") == "hoch" else "mittel",
                    effort="mittel",
                    location=str(issue.get("module", "")),
                )
            )
        return ideas

    @staticmethod
    def _from_usage(usage: dict[str, Any]) -> list[Idea]:
        """Leitet Skill-Vorschläge aus dem beobachteten Arbeitsverhalten ab.

        Beispiel aus der Vorgabe: Arbeitet der Benutzer häufig mit PDFs und
        fehlt eine PDF-Verarbeitung, schlägt der Orb einen entsprechenden
        Skill vor.
        """

        ideas: list[Idea] = []
        file_types = usage.get("file_types", {}) or {}
        missing_capabilities = set(usage.get("missing_capabilities", []) or [])

        suggestions = {
            "pdf": ("PDF-Analyse-Skill", "pdf_lesen"),
            "docx": ("Office-Skill", "dokument_erstellen"),
            "bib": ("Zotero-Skill", "literatur_suchen"),
            "py": ("Python-Werkzeug-Skill", "code_analyse"),
        }

        for suffix, (title, capability) in suggestions.items():
            count = int(file_types.get(suffix, 0))
            if count >= 5 and capability in missing_capabilities:
                ideas.append(
                    Idea(
                        type="neuer_skill",
                        title=f"{title} einrichten",
                        rationale=(
                            f"Du arbeitest häufig mit .{suffix}-Dateien ({count} erfasst), "
                            "aber dafür ist noch keine Fähigkeit installiert."
                        ),
                        evidence=[f"{count} Dateien vom Typ .{suffix}"],
                        impact="hoch",
                        effort="mittel",
                    )
                )

        for program, count in (usage.get("programs", {}) or {}).items():
            if int(count) >= 20:
                ideas.append(
                    Idea(
                        type="automatisierung",
                        title=f"Wiederkehrende Schritte in {program} automatisieren",
                        rationale=(
                            f"{program} wurde {count}-mal genutzt; wiederkehrende Abläufe "
                            "lassen sich als Skill zusammenfassen."
                        ),
                        evidence=[f"{count} Starts von {program}"],
                        impact="mittel",
                        effort="mittel",
                    )
                )
        return ideas
