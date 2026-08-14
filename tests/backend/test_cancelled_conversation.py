"""A cancelled turn must not leak into the following model prompt."""

from __future__ import annotations

from backend.memory.memory_engine import MemoryEngine
from backend.orchestrator.conversation_manager import ConversationManager


def test_pending_user_message_can_be_rolled_back() -> None:
    conversations = ConversationManager(MemoryEngine())
    conversations.add_user_message("erste frage")

    assert conversations.discard_unanswered_user_message("erste frage") is True
    assert conversations.history() == []


def test_rollback_never_removes_an_answered_turn() -> None:
    conversations = ConversationManager(MemoryEngine())
    conversations.add_user_message("erste frage")
    conversations.add_assistant_message("erste antwort")

    assert conversations.discard_unanswered_user_message("erste frage") is False
    assert len(conversations.history()) == 2
