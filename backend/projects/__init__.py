"""Project Intelligence Engine von AI-Orb (v3 Phase 3).

Der Orb arbeitet projektbasiert statt chatbasiert: Jedes Projekt besitzt
ein eigenes Gedächtnis mit Dokumenten, Literatur, Zielen, Aufgaben,
Entscheidungen und offenen Fragen. Projektwissen bleibt strikt getrennt.

Alle Projektdaten werden ausschließlich lokal gespeichert.
"""

from backend.projects.dependency_graph import DependencyGraph, GraphEdge, GraphNode
from backend.projects.document_tracker import DocumentTracker
from backend.projects.milestone_manager import MilestoneManager
from backend.projects.project_context import ProjectContext, ProjectContextData
from backend.projects.project_detector import DetectionResult, ProjectDetector
from backend.projects.project_engine import ProjectEngine
from backend.projects.project_memory import ProjectMemory
from backend.projects.project_summary import ProjectSummary
from backend.projects.session_manager import SessionManager
from backend.projects.workspace_manager import WorkspaceManager

__all__ = [
    "DependencyGraph",
    "DetectionResult",
    "DocumentTracker",
    "GraphEdge",
    "GraphNode",
    "MilestoneManager",
    "ProjectContext",
    "ProjectContextData",
    "ProjectDetector",
    "ProjectEngine",
    "ProjectMemory",
    "ProjectSummary",
    "SessionManager",
    "WorkspaceManager",
]
