"""Measure real AI-Orb response latency without touching user data.

The benchmark starts the complete runtime (except microphone autostart), waits
for ``system.ready`` and sends ordinary spoken conversation turns through the
Cognitive Core. Results are JSON lines so regressions can be compared across
runs instead of being judged by feel.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import threading
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

# Keep memory, preferences and logs produced by this diagnostic out of the
# user's real profile. This must be configured before importing the backend.
BENCHMARK_ROOT = PROJECT_ROOT / ".pytest_cache" / "latency-benchmark" / str(os.getpid())
os.environ.setdefault("AI_ORB_DATA_DIR", str(BENCHMARK_ROOT))

from backend.events import event_types  # noqa: E402
from backend.runtime import Runtime  # noqa: E402
from backend.system.performance_trace import (  # noqa: E402
    mark_stage,
    reset_turn_trace,
    start_turn_trace,
)


DEFAULT_PROMPTS = (
    "Wie geht es dir?",
    "Was ist zwei plus zwei?",
    "Erkläre mir in einem Satz, was ein Regenbogen ist.",
    "Nenne mir eine ruhige Idee für eine kurze Pause.",
    "Was bedeutet das Wort aufmerksam?",
    "Warum ist der Himmel meistens blau?",
    "Gib mir einen kurzen motivierenden Satz.",
    "Was ist der Unterschied zwischen warm und heiß?",
    "Nenne ein Tier, das nachts aktiv ist.",
    "Fasse den heutigen Test in einem Satz zusammen.",
)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--turns", type=int, default=10)
    parser.add_argument("--ready-timeout", type=float, default=90.0)
    parser.add_argument("--turn-timeout", type=float, default=20.0)
    parser.add_argument("--first-speech-target", type=float, default=5.0)
    parser.add_argument("--model", default="")
    parser.add_argument("--prompt", default="")
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    runtime = Runtime()

    if args.model:
        local = runtime.providers._providers.get("ollama")  # noqa: SLF001
        if local is None:
            print(json.dumps({"error": "ollama_not_configured"}))
            return 2
        local._model = args.model  # noqa: SLF001 - diagnostic override only.

    # The benchmark exercises spoken routing but never opens the microphone.
    voice = runtime.config.section("voice")
    voice["autostart"] = False

    ready = threading.Event()
    runtime.event_bus.subscribe(event_types.SYSTEM_READY, lambda _event: ready.set())

    startup_started = time.perf_counter()
    runtime.start()
    if not ready.wait(timeout=max(1.0, args.ready_timeout)):
        runtime.stop()
        print(json.dumps({"error": "system_ready_timeout"}))
        return 2

    startup_seconds = time.perf_counter() - startup_started
    records: list[dict[str, object]] = []

    try:
        prompts = (args.prompt,) if args.prompt else DEFAULT_PROMPTS
        turns = max(1, min(args.turns, len(prompts)))
        for index, prompt in enumerate(prompts[:turns], start=1):
            trace, token = start_turn_trace()

            async def on_speech(_sentence: str) -> bool:
                mark_stage("speech_callback")
                return True

            outcome = "answered"
            response_text = ""
            try:
                response = runtime.run(
                    runtime.cognitive.process(
                        prompt,
                        spoken=True,
                        on_speech=on_speech,
                    ),
                    timeout=max(1.0, args.turn_timeout),
                )
                response_text = response.response
            except Exception as error:  # noqa: BLE001 - report the failed turn.
                outcome = f"error:{type(error).__name__}"
            finally:
                snapshot = trace.finish(outcome=outcome)
                reset_turn_trace(token)

            first = float(snapshot.get("speech_callback", 9999.0))
            completed = float(snapshot.get("completed", 9999.0))
            record: dict[str, object] = {
                "turn": index,
                "prompt": prompt,
                "first_speech_seconds": first,
                "completed_seconds": completed,
                "passed": (
                    outcome == "answered"
                    and bool(response_text.strip())
                    and first <= args.first_speech_target
                    and completed <= args.turn_timeout
                ),
                "outcome": outcome,
                "response_preview": response_text[:100],
                "timings": snapshot,
            }
            records.append(record)
            print(json.dumps(record, ensure_ascii=False), flush=True)
    finally:
        runtime.stop()

    first_values = [float(item["first_speech_seconds"]) for item in records]
    completion_values = [float(item["completed_seconds"]) for item in records]
    passed = sum(bool(item["passed"]) for item in records)
    summary = {
        "startup_seconds": round(startup_seconds, 3),
        "turns": len(records),
        "passed": passed,
        "first_speech_median": round(statistics.median(first_values), 3),
        "first_speech_max": round(max(first_values), 3),
        "completed_median": round(statistics.median(completion_values), 3),
        "completed_max": round(max(completion_values), 3),
    }
    print(json.dumps({"summary": summary}, ensure_ascii=False), flush=True)
    return 0 if passed == len(records) else 1


if __name__ == "__main__":
    raise SystemExit(main())
