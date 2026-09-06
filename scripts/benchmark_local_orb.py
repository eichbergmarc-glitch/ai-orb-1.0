"""Realer Geschwindigkeits- und Werkzeugtest des lokalen AI-Orb-Modells.

Der Test spricht den in ``ai.fallback`` konfigurierten Ollama-Provider an.
Er misst das erste Textstueck und die Gesamtzeit mehrerer kurzer Antworten
und laesst das Modell anschliessend die echte Werkzeugschleife mit dem
ungefaehrlichen Rechenwerkzeug durchlaufen. Das Ergebnis wird als JSON unter
``logs/local_model_benchmark.json`` gespeichert.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

# Diagnosedaten duerfen nicht in das echte Gedaechtnis oder Benutzerprofil.
BENCHMARK_DATA = PROJECT_ROOT / ".pytest_cache" / "local-model-benchmark"
os.environ.setdefault("AI_ORB_DATA_DIR", str(BENCHMARK_DATA))

from backend.events.event_bus import EventBus  # noqa: E402
from backend.orchestrator.providers.base_provider import ChatMessage  # noqa: E402
from backend.orchestrator.providers.ollama_provider import OllamaProvider  # noqa: E402
from backend.security.security_engine import SecurityEngine  # noqa: E402
from backend.tools.registry import ToolRegistry  # noqa: E402
from backend.tools.standard_tools import CalculateTool  # noqa: E402
from backend.tools.tool_engine import ToolEngine  # noqa: E402


PROMPTS = (
    "Antworte in genau einem kurzen deutschen Satz: Was ist Aufmerksamkeit?",
    "Antworte kurz: Warum erscheint der Himmel am Tag blau?",
    "Nenne in einem Satz eine ruhige Idee fuer eine zweiminutige Pause.",
)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--turns", type=int, default=3)
    parser.add_argument("--first-token-target", type=float, default=12.0)
    parser.add_argument("--completion-target", type=float, default=60.0)
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--skip-tool", action="store_true")
    parser.add_argument(
        "--provider",
        choices=("main", "fast"),
        default="main",
        help="Lokales Haupt- oder Schnellmodell aus config.yaml testen.",
    )
    return parser.parse_args()


def _settings(provider: str = "main") -> dict[str, Any]:
    config = yaml.safe_load((PROJECT_ROOT / "config.yaml").read_text(encoding="utf-8"))
    if provider == "fast":
        return dict(config["ai"]["additional"]["ollama_fast"])
    return dict(config["ai"]["fallback"])


async def _speed_turn(
    provider: OllamaProvider,
    prompt: str,
    *,
    max_tokens: int,
    first_target: float,
    completion_target: float,
) -> dict[str, Any]:
    started = time.perf_counter()
    first: float | None = None
    pieces: list[str] = []
    try:
        async for piece in provider.chat_stream(
            [ChatMessage(role="user", content=prompt)],
            max_tokens=max_tokens,
        ):
            if first is None:
                first = time.perf_counter() - started
            pieces.append(piece)
    except Exception as error:  # noqa: BLE001 - der Pruefstand muss weiter berichten.
        completed = time.perf_counter() - started
        return {
            "prompt": prompt,
            "first_token_seconds": None,
            "completed_seconds": round(completed, 3),
            "characters": 0,
            "answer_preview": "",
            "passed": False,
            "error": f"{type(error).__name__}: {error}",
        }
    completed = time.perf_counter() - started
    answer = "".join(pieces).strip()
    first_seconds = first if first is not None else completed
    return {
        "prompt": prompt,
        "first_token_seconds": round(first_seconds, 3),
        "completed_seconds": round(completed, 3),
        "characters": len(answer),
        "answer_preview": answer[:160],
        "passed": bool(answer)
        and first_seconds <= first_target
        and completed <= completion_target,
    }


class _LocalCompletion:
    """Minimaler Adapter fuer die echte Werkzeugschleife."""

    def __init__(self, provider: OllamaProvider, max_tokens: int) -> None:
        self.provider = provider
        self.max_tokens = max_tokens

    async def complete(self, prompt: str, *, system_prompt: str = "") -> str:
        messages = []
        if system_prompt:
            messages.append(ChatMessage(role="system", content=system_prompt))
        messages.append(ChatMessage(role="user", content=prompt))
        response = await self.provider.chat(messages, max_tokens=self.max_tokens)
        return response.text


async def _tool_test(provider: OllamaProvider, max_tokens: int) -> dict[str, Any]:
    registry = ToolRegistry()
    registry.register(CalculateTool())
    security = SecurityEngine(EventBus())
    engine = ToolEngine(
        registry=registry,
        security=security,
        provider_manager=_LocalCompletion(provider, max(128, max_tokens)),
    )
    started = time.perf_counter()
    outcome = await engine.run(
        "Berechne 17 * 23 + 4. Benutze dafuer zwingend das Werkzeug rechnen.",
        system_prompt="Antworte auf Deutsch und befolge das Werkzeugformat exakt.",
        actor="lokaler_pruefstand",
    )
    elapsed = time.perf_counter() - started
    successful_runs = [run for run in outcome.runs if run.result.ok]
    final_answer_available = bool(outcome.answer.strip()) and not outcome.answer.startswith(
        "Das Sprachmodell hat nicht geantwortet:"
    )
    return {
        "passed": bool(successful_runs)
        and successful_runs[0].tool == "rechnen"
        and "395" in successful_runs[0].result.output
        and final_answer_available,
        "final_answer_available": final_answer_available,
        "seconds": round(elapsed, 3),
        "rounds": outcome.rounds,
        "tools_called": [run.tool for run in outcome.runs],
        "tool_outputs": [run.result.output for run in outcome.runs],
        "answer_preview": outcome.answer[:160],
        "stopped_because": outcome.stopped_because,
    }


async def _main(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    settings = _settings(args.provider)
    provider = OllamaProvider(settings)
    available = await provider.is_available()
    report: dict[str, Any] = {
        "model": settings.get("model"),
        "temperature": settings.get("temperature"),
        "context_window": settings.get("context_window"),
        "available": available,
    }
    if not available:
        report["passed"] = False
        report["error"] = "Ollama oder das konfigurierte Modell ist nicht verfuegbar."
        return 2, report

    warm_started = time.perf_counter()
    warmed = await provider.waermen()
    report["warmup"] = {
        "passed": warmed,
        "seconds": round(time.perf_counter() - warm_started, 3),
    }

    turns = max(1, min(args.turns, len(PROMPTS)))
    speed = []
    for prompt in PROMPTS[:turns]:
        speed.append(
            await _speed_turn(
                provider,
                prompt,
                max_tokens=max(16, args.max_tokens),
                first_target=max(0.1, args.first_token_target),
                completion_target=max(1.0, args.completion_target),
            )
        )
    report["speed"] = speed
    first_values = [
        float(item["first_token_seconds"])
        for item in speed
        if item["first_token_seconds"] is not None
    ]
    report["speed_summary"] = {
        "passed": all(item["passed"] for item in speed),
        "first_token_median": (
            round(statistics.median(first_values), 3) if first_values else None
        ),
        "completion_median": round(
            statistics.median(float(item["completed_seconds"]) for item in speed), 3
        ),
    }

    if args.skip_tool:
        report["tool"] = {"passed": True, "skipped": True}
    else:
        report["tool"] = await _tool_test(provider, args.max_tokens)

    report["passed"] = bool(
        report["warmup"]["passed"]
        and report["speed_summary"]["passed"]
        and report["tool"]["passed"]
    )
    return (0 if report["passed"] else 1), report


def main() -> int:
    code, report = asyncio.run(_main(_arguments()))
    destination = PROJECT_ROOT / "logs" / "local_model_benchmark.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\nBericht: {destination}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
