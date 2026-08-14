"""Verwaltung von Unterhaltungen, Sitzungen und Kontextfenster.

Der Conversation Manager hält den laufenden Gesprächsverlauf, begrenzt
dessen Umfang und komprimiert ältere Abschnitte automatisch zu
Zusammenfassungen. Der Verlauf ist providerunabhängig – bei einem Wechsel
zwischen Hermes und Ollama geht dadurch kein Kontext verloren.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from backend.config import get_config
from backend.memory.memory_engine import MemoryEngine
from backend.orchestrator.providers.base_provider import ChatMessage
from backend.system.logging_setup import get_logger

logger = get_logger(__name__)


@dataclass
class Conversation:
    """Eine laufende Unterhaltung."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    project_id: str | None = None
    messages: list[dict[str, Any]] = field(default_factory=list)
    summary: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def add(self, role: str, content: str) -> None:
        """Hängt eine Nachricht an den Verlauf an."""

        self.messages.append({"role": role, "content": content, "at": time.time()})
        self.updated_at = time.time()

    @property
    def message_count(self) -> int:
        return len(self.messages)

    def estimated_tokens(self) -> int:
        """Grobe Schätzung der Kontextlänge in Tokens.

        Es wird bewusst konservativ mit vier Zeichen pro Token gerechnet;
        die Schätzung dient ausschließlich der Entscheidung, wann
        komprimiert werden muss.
        """

        characters = sum(len(str(message.get("content", ""))) for message in self.messages)
        return characters // 4


class ConversationManager:
    """Verwaltet alle Unterhaltungen und deren Kontext."""

    def __init__(self, memory: MemoryEngine) -> None:
        config = get_config()
        conversation_config = config.section("conversation")

        self._memory = memory
        self._conversations: dict[str, Conversation] = {}
        self._active_id: str | None = None

        self._max_messages = int(conversation_config.get("max_messages", 30))
        self._max_tokens = int(conversation_config.get("max_context_tokens", 3000))
        self._keep_recent = int(conversation_config.get("keep_recent_messages", 8))
        self._system_prompt = str(
            conversation_config.get(
                "system_prompt",
                "Du bist AI-Orb, ein lokaler, hilfsbereiter Desktop-Assistent.",
            )
        )

    # --- Sitzungsverwaltung ---------------------------------------------------

    def start(self, project_id: str | None = None) -> Conversation:
        """Beginnt eine neue Unterhaltung und macht sie zur aktiven."""

        conversation = Conversation(project_id=project_id)
        self._conversations[conversation.id] = conversation
        self._active_id = conversation.id
        logger.info("Neue Unterhaltung gestartet (%s).", conversation.id)
        return conversation

    @property
    def active(self) -> Conversation:
        """Die aktive Unterhaltung; wird bei Bedarf automatisch erzeugt."""

        if self._active_id is None or self._active_id not in self._conversations:
            return self.start()
        return self._conversations[self._active_id]

    def switch_to(self, conversation_id: str) -> bool:
        """Wechselt zu einer bestehenden Unterhaltung."""

        if conversation_id not in self._conversations:
            return False
        self._active_id = conversation_id
        return True

    def set_project(self, project_id: str | None) -> None:
        """Ordnet die aktive Unterhaltung einem Projekt zu.

        Projektwissen bleibt dadurch sauber getrennt: Antworten und
        Erinnerungen dieser Unterhaltung werden ausschließlich diesem
        Projekt zugeordnet.
        """

        self.active.project_id = project_id

    # --- Nachrichten ------------------------------------------------------------

    def add_user_message(self, content: str) -> None:
        """Fügt eine Benutzernachricht hinzu."""

        self.active.add("user", content)

    def add_assistant_message(self, content: str) -> None:
        """Fügt eine Antwort des Orb hinzu."""

        self.active.add("assistant", content)

    def discard_unanswered_user_message(self, content: str) -> bool:
        """Remove the pending user turn when its task was cancelled."""

        conversation = self.active
        if not conversation.messages:
            return False
        last = conversation.messages[-1]
        if last.get("role") != "user" or str(last.get("content", "")) != content:
            return False
        conversation.messages.pop()
        conversation.updated_at = time.time()
        return True

    async def maybe_compress(self) -> bool:
        """Komprimiert den Verlauf, wenn er zu lang geworden ist.

        Ältere Nachrichten werden zu einer Zusammenfassung verdichtet; die
        jüngsten Nachrichten bleiben unverändert erhalten. Dadurch bleibt
        der Kontext erhalten, während der Speicherverbrauch sinkt.

        Returns:
            ``True``, wenn komprimiert wurde.
        """

        conversation = self.active
        too_many = conversation.message_count > self._max_messages
        too_long = conversation.estimated_tokens() > self._max_tokens
        if not (too_many or too_long):
            return False

        older = conversation.messages[: -self._keep_recent] if self._keep_recent else conversation.messages
        recent = conversation.messages[-self._keep_recent :] if self._keep_recent else []
        if not older:
            return False

        summary = await self._memory.summaries.summarize_conversation(
            [{"role": str(m.get("role")), "content": str(m.get("content"))} for m in older]
        )
        combined = f"{conversation.summary}\n{summary}".strip() if conversation.summary else summary
        conversation.summary = combined
        conversation.messages = recent

        logger.info(
            "Unterhaltung %s komprimiert (%d Nachrichten verdichtet).",
            conversation.id,
            len(older),
        )
        return True

    # --- Kontextaufbau ------------------------------------------------------------

    def build_messages(
        self,
        *,
        extra_context: str | None = None,
        system_prompt: str | None = None,
        recent_limit: int | None = None,
    ) -> list[ChatMessage]:
        """Baut die Nachrichtenliste für eine Modellanfrage auf.

        Reihenfolge: Systemprompt, gegebenenfalls verdichteter
        Gesprächsrückblick, zusätzlicher Kontext (Gedächtnis, Projekt),
        anschließend der jüngste Verlauf.
        """

        conversation = self.active
        messages: list[ChatMessage] = [
            ChatMessage(role="system", content=system_prompt or self._system_prompt)
        ]

        if conversation.summary:
            messages.append(
                ChatMessage(
                    role="system",
                    content=f"Bisheriger Gesprächsverlauf (zusammengefasst):\n{conversation.summary}",
                )
            )

        if extra_context:
            messages.append(ChatMessage(role="system", content=extra_context))

        history = conversation.messages
        if recent_limit is not None and recent_limit > 0:
            history = history[-recent_limit:]

        for message in history:
            role = str(message.get("role", "user"))
            if role not in ("user", "assistant", "system"):
                role = "user"
            messages.append(ChatMessage(role=role, content=str(message.get("content", ""))))

        return messages

    # --- Abschluss -------------------------------------------------------------------

    async def finish(self, conversation_id: str | None = None) -> str | None:
        """Beendet eine Unterhaltung und legt eine Zusammenfassung ab.

        Die Zusammenfassung wandert in das Conversation Memory, sodass der
        Orb sich in späteren Sitzungen an das Gespräch erinnern kann.

        Returns:
            Die erzeugte Zusammenfassung, oder ``None``, wenn nichts zu
            sichern war.
        """

        target_id = conversation_id or self._active_id
        if target_id is None:
            return None
        conversation = self._conversations.get(target_id)
        if conversation is None or not conversation.messages:
            return None

        summary = await self._memory.summaries.summarize_conversation(
            [{"role": str(m.get("role")), "content": str(m.get("content"))} for m in conversation.messages]
        )
        full_summary = f"{conversation.summary}\n{summary}".strip()

        if full_summary:
            self._memory.conversations.add_summary(
                full_summary,
                session_id=conversation.id,
                project_id=conversation.project_id,
                message_count=conversation.message_count,
            )

        if target_id == self._active_id:
            self._active_id = None
        return full_summary

    def history(self, limit: int = 20) -> list[dict[str, Any]]:
        """Gibt den Verlauf der aktiven Unterhaltung zurück."""

        return self.active.messages[-limit:]

    def status(self) -> dict[str, Any]:
        """Statusinformationen für die Transparenzansicht."""

        conversation = self.active
        return {
            "conversation_id": conversation.id,
            "project_id": conversation.project_id,
            "messages": conversation.message_count,
            "estimated_tokens": conversation.estimated_tokens(),
            "has_summary": bool(conversation.summary),
            "total_conversations": len(self._conversations),
        }
