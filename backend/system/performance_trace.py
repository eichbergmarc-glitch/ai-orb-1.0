"""End-to-end timing for one user interaction.

Partial provider timings are useful, but they cannot explain a voice turn that
feels stuck. This module follows one turn across ASR, routing, model streaming,
TTS and playback and writes one compact, machine-readable summary at the end.
"""

from __future__ import annotations

import contextvars
import json
import threading
import time
import uuid
from dataclasses import dataclass, field

from backend.system.logging_setup import get_logger

logger = get_logger(__name__)


@dataclass
class TurnTrace:
    """Monotonic milestones belonging to one voice or chat turn."""

    turn_id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    started_at: float = field(default_factory=time.perf_counter)
    stages: dict[str, float] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def mark(self, stage: str, *, replace: bool = False) -> float:
        """Record a stage once and return seconds since the turn began."""

        elapsed = max(0.0, time.perf_counter() - self.started_at)
        with self._lock:
            if replace or stage not in self.stages:
                self.stages[stage] = elapsed
            return self.stages[stage]

    def snapshot(self) -> dict[str, float | str]:
        with self._lock:
            stages = {name: round(value, 3) for name, value in self.stages.items()}
        return {"turn_id": self.turn_id, **stages}

    def finish(self, *, outcome: str) -> dict[str, float | str]:
        self.mark("completed")
        summary = {**self.snapshot(), "outcome": outcome}
        logger.info(
            "TURN_LATENCY %s",
            json.dumps(summary, ensure_ascii=False, sort_keys=True),
        )
        return summary


_current_trace: contextvars.ContextVar[TurnTrace | None] = contextvars.ContextVar(
    "ai_orb_turn_trace", default=None
)


def start_turn_trace() -> tuple[TurnTrace, contextvars.Token[TurnTrace | None]]:
    trace = TurnTrace()
    return trace, _current_trace.set(trace)


def current_turn_trace() -> TurnTrace | None:
    return _current_trace.get()


def mark_stage(stage: str, *, replace: bool = False) -> float | None:
    trace = current_turn_trace()
    return trace.mark(stage, replace=replace) if trace is not None else None


def reset_turn_trace(token: contextvars.Token[TurnTrace | None]) -> None:
    _current_trace.reset(token)
