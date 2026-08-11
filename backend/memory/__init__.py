"""Memory Engine von AI-Orb.

Trennt Working Memory (Cognitive Core), Conversation Memory, User Memory,
Knowledge Memory und Task Memory. Alle Module greifen ausschließlich über
:class:`~backend.memory.memory_engine.MemoryEngine` (die Memory API) auf
Erinnerungen zu; direkte Datenbankzugriffe sind nicht erlaubt.

Alle Daten werden ausschließlich lokal im Verzeichnis ``data/`` gespeichert.
"""

from backend.memory.conversation_memory import ConversationMemory
from backend.memory.knowledge_memory import KnowledgeMemory
from backend.memory.memory_engine import MemoryEngine
from backend.memory.memory_index import MemoryIndex
from backend.memory.memory_search import MemorySearch, SearchResult
from backend.memory.memory_store import MemoryRecord, MemoryStore
from backend.memory.summary_engine import SummaryEngine
from backend.memory.task_memory import TaskMemory
from backend.memory.user_memory import UserMemory

__all__ = [
    "ConversationMemory",
    "KnowledgeMemory",
    "MemoryEngine",
    "MemoryIndex",
    "MemoryRecord",
    "MemorySearch",
    "MemoryStore",
    "SearchResult",
    "SummaryEngine",
    "TaskMemory",
    "UserMemory",
]
