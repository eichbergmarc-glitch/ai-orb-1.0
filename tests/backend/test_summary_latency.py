"""Short shutdown summaries must not start another language-model turn."""

from __future__ import annotations

import asyncio

from backend.memory.summary_engine import SummaryEngine


class _Provider:
    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, prompt: str, **kwargs) -> str:
        self.calls += 1
        return "model summary"


def test_short_conversation_is_summarized_locally() -> None:
    provider = _Provider()
    engine = SummaryEngine(provider)
    messages = [
        {"role": "user", "content": "Wie geht es dir?"},
        {"role": "assistant", "content": "Mir geht es gut. " * 30},
    ]

    summary = asyncio.run(engine.summarize_conversation(messages))

    assert summary
    assert provider.calls == 0
