"""Prueft Provider-Schluessel ueber /models, ohne eine Chat-Anfrage zu senden."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.config import load_env_file
from backend.orchestrator.providers.openai_compatible_provider import (
    OpenAICompatibleProvider,
)
from backend.orchestrator.providers.base_provider import ProviderError


async def main() -> None:
    load_env_file()
    specs = (("openrouter", "openrouter"), ("grok", "grok"), ("openai", "openai"))
    markers = ("free", "grok-4.3", "gpt-4.1-nano", "gpt-5.6-luna")
    for name, preset in specs:
        provider = OpenAICompatibleProvider(
            {"engine": name, "preset": preset, "model": "probe", "timeout": 12}
        )
        status = "ok"
        try:
            payload = await provider._request_json(  # noqa: SLF001 - Diagnosewerkzeug
                f"{provider._base_url}/models",  # noqa: SLF001
                method="GET",
                headers=provider._headers(),  # noqa: SLF001
                timeout=12,
            )
            models = [
                str(entry.get("id", ""))
                for entry in (payload.get("data") or [])
                if entry.get("id")
            ]
        except ProviderError as error:
            models = []
            cause = error.__cause__
            code = getattr(cause, "code", None)
            status = f"http-{code}" if code else type(cause).__name__
        candidates = [
            model
            for model in models
            if any(marker in model.lower() for marker in markers)
        ][:12]
        print(
            f"{name}: reachable={bool(models)} status={status} count={len(models)} "
            f"candidates={candidates}"
        )


if __name__ == "__main__":
    asyncio.run(main())
