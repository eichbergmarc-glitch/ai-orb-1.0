"""Verteilung der Subagenten auf OpenRouter, xAI und OpenAI."""

from __future__ import annotations

from backend.ai.provider_factory import ProviderFactory
from backend.ai.provider_registry import ProviderRegistry
from backend.orchestrator.provider_health import ProviderHealth
from backend.orchestrator.provider_manager import ProviderManager
from backend.orchestrator.providers import PROVIDER_TYPES
from backend.orchestrator.providers.base_provider import ProviderError
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
        for name in ("claude_code", "ollama", "openrouter", "grok", "openai")
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


def test_subagent_falls_back_across_external_providers_before_claude():
    manager = _manager()

    assert manager._provider_order("grok") == [
        "grok",
        "openrouter",
        "openai",
        "ollama",
        "claude_code",
    ]


def test_normal_dialog_still_starts_with_active_main_provider():
    manager = _manager()

    assert manager._provider_order()[:2] == ["claude_code", "ollama"]


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
