"""Wissensbasis mit Quellenangabe (v2 Phase 20).

Eine lokale Ablage für Dokumente, aus denen AI-Orb belegte Antworten geben
kann. Der Unterschied zum Gedächtnis: Hier steht, woher etwas stammt – und
damit lässt sich prüfen, ob eine Behauptung trägt.
"""

from backend.knowledge.knowledge_base import (
    SUPPORTED_SUFFIXES,
    Document,
    Finding,
    KnowledgeBase,
    Passage,
    cosine,
    term_vector,
    tokenize,
)

__all__ = [
    "SUPPORTED_SUFFIXES",
    "Document",
    "Finding",
    "KnowledgeBase",
    "Passage",
    "cosine",
    "term_vector",
    "tokenize",
]
