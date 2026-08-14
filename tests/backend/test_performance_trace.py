"""The latency trace remains monotonic and isolated per interaction."""

from __future__ import annotations

from backend.system.performance_trace import (
    current_turn_trace,
    mark_stage,
    reset_turn_trace,
    start_turn_trace,
)


def test_trace_records_each_milestone_only_once() -> None:
    trace, token = start_turn_trace()
    try:
        first = mark_stage("provider_first_text")
        second = mark_stage("provider_first_text")
        summary = trace.finish(outcome="answered")
    finally:
        reset_turn_trace(token)

    assert first == second
    assert summary["turn_id"] == trace.turn_id
    assert summary["provider_first_text"] <= summary["completed"]
    assert summary["outcome"] == "answered"
    assert current_turn_trace() is None


def test_nested_trace_restores_its_parent() -> None:
    parent, parent_token = start_turn_trace()
    child, child_token = start_turn_trace()
    try:
        assert current_turn_trace() is child
        reset_turn_trace(child_token)
        assert current_turn_trace() is parent
    finally:
        reset_turn_trace(parent_token)
