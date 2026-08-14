"""Automatische Zusammenfassung langer Gespräche und Texte.

Lange Unterhaltungen werden komprimiert, damit der Kontext erhalten bleibt,
der Speicherverbrauch aber sinkt. Die Engine arbeitet zweistufig:

1. Ist ein Sprachmodell verfügbar (Provider Manager), wird dieses für eine
   qualitativ hochwertige Zusammenfassung genutzt.
2. Ist kein Modell erreichbar (Offline-Betrieb), wird auf das rein lokale,
   extraktive Verfahren aus :func:`backend.utils.text.summarize`
   zurückgegriffen.

Dadurch funktioniert die Memory Engine unabhängig vom verwendeten
KI-Modell, wie in der Architekturvorgabe gefordert.
"""

from __future__ import annotations

from typing import Any, Protocol

from backend.system.logging_setup import get_logger
from backend.utils.text import summarize, truncate

logger = get_logger(__name__)


class SummarizerBackend(Protocol):
    """Minimale Schnittstelle, die ein Sprachmodell-Provider erfüllen muss,
    damit er für Zusammenfassungen genutzt werden kann."""

    async def complete(self, prompt: str, **kwargs: Any) -> str:
        ...


class SummaryEngine:
    """Erzeugt Zusammenfassungen von Gesprächen und Dokumenten."""

    def __init__(self, provider_manager: Any | None = None) -> None:
        self._provider_manager = provider_manager

    async def summarize_text(self, text: str, *, max_sentences: int = 3) -> str:
        """Fasst einen beliebigen Text zusammen.

        Args:
            text: Der zu verdichtende Text.
            max_sentences: Zielumfang der lokalen Kurzfassung.

        Returns:
            Die Zusammenfassung. Bei sehr kurzen Texten wird der Text
            unverändert zurückgegeben.
        """

        stripped = text.strip()
        if len(stripped) < 400:
            return stripped

        # A short conversation must not launch another full model request
        # while the app is closing. That shutdown summary regularly consumed
        # the complete 15 s shutdown budget. The local extractive summary is
        # immediate and sufficient until there is substantial material.
        if len(stripped) < 2000:
            return summarize(stripped, max_sentences=max_sentences)

        if self._provider_manager is not None:
            try:
                prompt = (
                    "Fasse den folgenden Text sachlich und knapp zusammen. "
                    "Erfinde nichts hinzu. Antworte in derselben Sprache wie "
                    "der Text.\n\n"
                    f"{truncate(stripped, 6000)}"
                )
                result = await self._provider_manager.complete(prompt)
                if result and result.strip():
                    return result.strip()
            except Exception:  # noqa: BLE001 - Fallback muss immer greifen.
                logger.warning(
                    "Zusammenfassung über Sprachmodell fehlgeschlagen, "
                    "nutze lokales Verfahren.",
                    exc_info=True,
                )

        return summarize(stripped, max_sentences=max_sentences)

    async def summarize_conversation(self, messages: list[dict[str, str]]) -> str:
        """Fasst einen Gesprächsverlauf zusammen.

        Args:
            messages: Liste von Nachrichten der Form
                ``{"role": "user"|"assistant", "content": "..."}``.

        Returns:
            Eine Zusammenfassung des Gesprächsverlaufs.
        """

        if not messages:
            return ""

        transcript = "\n".join(
            f"{message.get('role', 'user')}: {message.get('content', '')}"
            for message in messages
        )
        return await self.summarize_text(transcript, max_sentences=4)
