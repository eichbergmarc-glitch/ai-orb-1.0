"""Verteilung der Subagenten auf OpenRouter, xAI und OpenAI."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from backend.ai.provider_factory import ProviderFactory
from backend.ai.provider_registry import ProviderRegistry
from backend.orchestrator.provider_health import ProviderHealth
from backend.orchestrator.provider_manager import ProviderManager
from backend.orchestrator.providers import PROVIDER_TYPES
from backend.orchestrator.providers.base_provider import ChatMessage, ProviderError
from backend.orchestrator.providers.openai_compatible_provider import (
    OpenAICompatibleProvider,
    PRESETS,
)


def _manager() -> ProviderManager:
    manager = ProviderManager.__new__(ProviderManager)
    manager._providers = {
        name: OpenAICompatibleProvider(
            {"engine": name, "preset": "openai", "model": "test"}
        )
        for name in (
            "claude_code", "ollama_fast", "ollama", "openrouter", "grok", "openai"
        )
    }
    manager._primary_name = "claude_code"
    manager._fallback_name = "ollama"
    manager._active_name = "claude_code"
    manager._operating_mode = "auto"
    manager._quota_cooldowns = {}
    manager._ai_config = {
        "subagent_fallback_order": [
            "openrouter",
            "grok",
            "openai",
            "ollama",
            "claude_code",
        ],
        "dialog_fallback_order": [
            "ollama_fast", "ollama", "openrouter", "openai"
        ],
        "capable_fallback_order": ["ollama"],
        "fast_dialog_max_tokens": 160,
        "quota_cooldown_seconds": 300,
    }
    manager._health = ProviderHealth()
    return manager


def test_cloud_provider_are_registered_in_both_registries():
    assert {"openrouter", "grok", "openai"} <= set(PROVIDER_TYPES)
    assert {"openrouter", "grok", "openai"} <= set(ProviderRegistry().names())


def test_presets_use_separate_key_variables_and_official_endpoints():
    assert PRESETS["openrouter"]["api_key_env"] == "OPENROUTER_API_KEY"
    assert PRESETS["grok"]["api_key_env"] == "XAI_API_KEY"
    assert PRESETS["openai"]["api_key_env"] == "OPENAI_API_KEY"
    assert PRESETS["openrouter"]["base_url"] == "https://openrouter.ai/api/v1"
    assert PRESETS["grok"]["base_url"] == "https://api.x.ai/v1"


def test_compatible_provider_instances_keep_distinct_names():
    providers = [
        OpenAICompatibleProvider(
            {"engine": name, "preset": name, "model": "test"}
        )
        for name in ("openrouter", "grok", "openai")
    ]
    assert [provider.name for provider in providers] == [
        "openrouter",
        "grok",
        "openai",
    ]


def test_two_openai_tiers_keep_distinct_instance_names():
    luna = OpenAICompatibleProvider(
        {
            "engine": "openai",
            "instance_name": "openai",
            "preset": "openai",
            "model": "gpt-5.6-luna",
        }
    )
    terra = OpenAICompatibleProvider(
        {
            "engine": "openai",
            "instance_name": "openai_terra",
            "preset": "openai",
            "model": "gpt-5.6-terra",
        }
    )

    assert luna.name == "openai"
    assert terra.name == "openai_terra"


def test_subagent_falls_back_across_external_providers_before_claude():
    manager = _manager()

    assert manager._provider_order("grok") == [
        "grok",
        "openrouter",
        "openai",
        "ollama",
        "claude_code",
        "ollama_fast",
    ]


def test_normal_dialog_still_starts_with_active_main_provider():
    manager = _manager()

    assert manager._provider_order()[:3] == [
        "claude_code", "ollama", "ollama_fast"
    ]


def test_short_spoken_dialog_uses_fast_local_fallback_first():
    manager = _manager()

    assert manager._provider_order(fast_dialog=True)[:3] == [
        "claude_code", "ollama_fast", "ollama"
    ]


def test_fast_provider_receives_only_compact_recent_context():
    provider = OpenAICompatibleProvider(
        {
            "engine": "ollama_fast",
            "preset": "openai",
            "model": "test",
            "compact_system_prompt": "Du bist AI-Orb.",
            "recent_messages": 2,
            "max_input_characters": 1000,
        }
    )
    messages = [
        ChatMessage("system", "Sehr langer Claude-Systemprompt"),
        ChatMessage("user", "alte Frage"),
        ChatMessage("assistant", "alte Antwort"),
        ChatMessage("user", "neue Frage"),
    ]

    compact = ProviderManager._messages_for_provider(provider, messages)

    assert [(message.role, message.content) for message in compact] == [
        ("system", "Du bist AI-Orb."),
        ("assistant", "alte Antwort"),
        ("user", "neue Frage"),
    ]


def test_missing_credits_put_provider_into_long_cooldown():
    manager = _manager()

    manager._note_provider_error(
        "openai",
        ProviderError("openai: HTTP 429 - insufficient_quota: no credits remaining"),
    )

    assert "openai" not in manager._provider_order()


def test_openai_uses_responses_api_and_extracts_output_text():
    provider = OpenAICompatibleProvider(
        {
            "engine": "openai",
            "preset": "openai",
            "model": "gpt-5.6-luna",
            "effort": "low",
        }
    )
    request: dict[str, object] = {}

    async def fake_request(url: str, **kwargs):
        request["url"] = url
        request["payload"] = kwargs.get("payload")
        return {
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "Guten Tag."}],
                }
            ],
        }

    provider._request_json = fake_request  # type: ignore[method-assign]
    answer = asyncio.run(
        provider.chat(
            [ChatMessage(role="user", content="Hallo")],
            temperature=0.7,
            max_tokens=40,
        )
    )

    assert str(request["url"]).endswith("/responses")
    payload = request["payload"]
    assert isinstance(payload, dict)
    # 40 gewuenschte Tokens plus Reserve fuers Denken.
    #
    # Hier stand die 40 unveraendert - und genau daran ist der Orb am
    # 31.08.2026 verstummt: Bei einem Reasoning-Modell begrenzt
    # max_output_tokens Denken UND Antwort zusammen. Die 40 Tokens einer
    # gesprochenen Antwort verbrauchte das Modell im Denken, die Antwort
    # kam als 'incomplete' zurueck, ohne ein sichtbares Wort, und der Orb
    # meldete "Keine Modellantwort moeglich".
    assert payload["max_output_tokens"] == 40 + 512
    assert payload["reasoning"] == {"effort": "low"}
    assert "temperature" not in payload
    assert answer.text == "Guten Tag."


def test_openai_sends_images_through_responses_api():
    provider = OpenAICompatibleProvider(
        {
            "engine": "openai",
            "preset": "openai",
            "api_style": "responses",
            "model": "gpt-5.6-luna",
            "effort": "low",
        }
    )
    request: dict[str, object] = {}

    async def fake_request(url: str, **kwargs):
        request["url"] = url
        request["payload"] = kwargs.get("payload")
        return {"status": "completed", "output_text": "Ein blauer Kreis."}

    provider._request_json = fake_request  # type: ignore[method-assign]
    answer = asyncio.run(
        provider.complete_with_images(
            "Was ist zu sehen?",
            system_prompt="Beschreibe das Bild.",
            images=[{"media_type": "image/png", "data": "AAAA"}],
            max_tokens=40,
        )
    )

    assert provider.supports_images
    assert str(request["url"]).endswith("/responses")
    payload = request["payload"]
    assert isinstance(payload, dict)
    assert payload["max_output_tokens"] == 40 + 512
    input_items = payload["input"]
    assert isinstance(input_items, list)
    assert input_items[0] == {"role": "system", "content": "Beschreibe das Bild."}
    user_content = input_items[1]["content"]
    assert user_content[0] == {"type": "input_text", "text": "Was ist zu sehen?"}
    assert user_content[1] == {
        "type": "input_image",
        "image_url": "data:image/png;base64,AAAA",
    }
    assert answer.text == "Ein blauer Kreis."


def test_openai_streams_responses_text_deltas(monkeypatch):
    provider = OpenAICompatibleProvider(
        {
            "engine": "openai",
            "preset": "openai",
            "api_style": "responses",
            "model": "gpt-5.6-luna",
            "effort": "low",
        }
    )

    class FakeResponse:
        status_code = 200

        async def aiter_lines(self) -> AsyncIterator[str]:
            for line in (
                "event: response.output_text.delta",
                'data: {"type":"response.output_text.delta","delta":"Guten "}',
                "",
                'data: {"type":"response.output_text.delta","delta":"Tag."}',
                "",
                'data: {"type":"response.completed","response":{"status":"completed"}}',
            ):
                yield line

        async def aread(self) -> bytes:
            return b""

        async def aclose(self) -> None:
            return None

    class FakeClient:
        def __init__(self, **kwargs):
            self.request: dict[str, object] | None = None

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        def build_request(self, method: str, url: str, **kwargs):
            self.request = {"method": method, "url": url, **kwargs}
            return self.request

        async def send(self, request, *, stream: bool):
            assert stream is True
            assert request["json"]["stream"] is True
            return FakeResponse()

    monkeypatch.setattr(
        "backend.orchestrator.providers.openai_compatible_provider.httpx.AsyncClient",
        FakeClient,
    )

    async def collect() -> list[str]:
        return [
            piece
            async for piece in provider.chat_stream(
                [ChatMessage(role="user", content="Hallo")], max_tokens=40
            )
        ]

    assert asyncio.run(collect()) == ["Guten ", "Tag."]


def test_quota_error_temporarily_removes_provider_from_order():
    manager = _manager()

    manager._note_provider_error("grok", ProviderError("grok: HTTP 429 - rate limit"))

    assert "grok" not in manager._provider_order("grok")


def test_disabled_paid_additional_providers_are_not_built():
    config = {
        "additional": {
            "free": {"engine": "ollama", "model": "local"},
            "paid": {
                "enabled": False,
                "engine": "openai",
                "model": "paid-model",
                "api_key_env": "OPENAI_API_KEY",
            },
        }
    }

    results = ProviderFactory().build_all(config)

    assert "additional:free" in results
    assert "additional:paid" not in results


def test_ein_denkmodell_bekommt_platz_zum_denken() -> None:
    """Die Regel hinter dem Verstummen vom 31.08.2026.

    ``max_output_tokens`` ist bei einem Reasoning-Modell kein Antwortmass,
    sondern die Summe aus Denken und Antwort. Wer dort die gewuenschte
    Antwortlaenge einsetzt, bekommt keine kurze Antwort - er bekommt gar
    keine.
    """

    denkend = OpenAICompatibleProvider(
        {"engine": "openai", "preset": "openai", "api_style": "responses",
         "model": "gpt-5.6-luna", "effort": "low"}
    )
    schlicht = OpenAICompatibleProvider(
        {"engine": "openai", "preset": "openai", "api_style": "responses",
         "model": "gpt-4o-mini"}
    )

    assert denkend._ausgabegrenze(40) == 552
    assert denkend._ausgabegrenze(1) >= 256, "eine Untergrenze muss es geben"
    # Ein Modell ohne Denkschritt bekommt weiterhin genau, was verlangt ist.
    assert schlicht._ausgabegrenze(40) == 40
