"""Tests für die Claude-Provider.

Geprüft wird die Aufbereitung der Anfragen und die Fehlerübersetzung –
ohne echte Netz- oder Prozessaufrufe.
"""

from __future__ import annotations

import pytest

from backend.orchestrator.providers import PROVIDER_TYPES
from backend.orchestrator.providers.base_provider import ChatMessage
from backend.orchestrator.providers.claude_code_provider import ClaudeCodeProvider
from backend.orchestrator.providers.claude_provider import ClaudeProvider


@pytest.fixture(autouse=True)
def isolated_data(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.utils.store.get_data_dir", lambda: tmp_path)
    monkeypatch.setattr("backend.utils.paths.get_data_dir", lambda: tmp_path)
    yield tmp_path


# --- Registrierung -----------------------------------------------------------


def test_both_claude_providers_are_registered():
    assert "claude_code" in PROVIDER_TYPES
    assert "claude" in PROVIDER_TYPES


def test_previous_providers_remain_available():
    """Bestehende Provider dürfen nicht entfernt werden."""

    assert "ollama" in PROVIDER_TYPES
    assert "hermes" in PROVIDER_TYPES


# --- Claude über das Abonnement ----------------------------------------------


def test_claude_code_defaults_to_stable_model_alias():
    provider = ClaudeCodeProvider({})

    assert provider.model == "sonnet"


def test_claude_code_composes_single_question_without_scaffolding():
    prompt = ClaudeCodeProvider._compose_prompt(
        [ChatMessage(role="user", content="Was ist der Investiturstreit?")]
    )

    assert prompt == "Was ist der Investiturstreit?"


def test_claude_code_puts_system_prompt_first():
    prompt = ClaudeCodeProvider._compose_prompt(
        [
            ChatMessage(role="system", content="Du bist AI-Orb."),
            ChatMessage(role="user", content="Hallo"),
        ]
    )

    assert prompt.startswith("Du bist AI-Orb.")
    assert "Hallo" in prompt


def test_claude_code_extracts_text_from_json_output():
    output = '{"type":"result","subtype":"success","result":"Die Antwort."}'

    assert ClaudeCodeProvider._extract_text(output) == "Die Antwort."


def test_claude_code_extracts_text_from_content_blocks():
    output = '{"content":[{"type":"text","text":"Teil eins"},{"type":"text","text":"Teil zwei"}]}'

    result = ClaudeCodeProvider._extract_text(output)

    assert "Teil eins" in result
    assert "Teil zwei" in result


def test_claude_code_falls_back_to_raw_output():
    """Auch ohne JSON darf eine Antwort nicht verloren gehen."""

    assert ClaudeCodeProvider._extract_text("Einfacher Text") == "Einfacher Text"


def test_claude_code_ignores_error_results():
    output = '{"is_error":true,"result":"etwas ging schief"}'

    assert ClaudeCodeProvider._extract_text(output) == ""


def test_claude_code_explains_missing_login():
    # `_explain_failure` ist jetzt eine Instanzmethode (sie setzt bei einer
    # Nutzungsgrenze nebenbei die Sperrfrist), darum ueber eine Instanz.
    message = ClaudeCodeProvider({})._explain_failure("Error: not logged in")

    assert "angemeldet" in message
    assert "claude" in message


def test_claude_code_explains_usage_limit():
    provider = ClaudeCodeProvider({})
    message = provider._explain_failure("Usage limit reached")

    assert "Nutzungsgrenze" in message
    assert "lokale" in message
    # Die Grenzmeldung setzt zugleich die Sperrfrist.
    assert provider._limit_until > provider._now()


def test_claude_code_removes_api_key_from_environment(monkeypatch):
    """Ein gesetzter API-Schlüssel darf das Abonnement nicht überstimmen."""

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    provider = ClaudeCodeProvider({})

    environment = provider._build_environment()

    assert "ANTHROPIC_API_KEY" not in environment


async def test_claude_code_unavailable_without_executable(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    provider = ClaudeCodeProvider({"executable": "gibt-es-nicht"})
    monkeypatch.setattr(provider, "_find_executable", lambda: None)

    assert await provider.is_available() is False


# --- Claude über die API -------------------------------------------------------


def test_claude_api_splits_system_from_dialogue():
    system, dialogue = ClaudeProvider._split_messages(
        [
            ChatMessage(role="system", content="Systemtext"),
            ChatMessage(role="user", content="Frage"),
            ChatMessage(role="assistant", content="Antwort"),
            ChatMessage(role="user", content="Nachfrage"),
        ]
    )

    assert system == "Systemtext"
    assert [message["role"] for message in dialogue] == ["user", "assistant", "user"]


def test_claude_api_merges_consecutive_roles():
    """Die API erlaubt keine zwei gleichen Rollen hintereinander."""

    _, dialogue = ClaudeProvider._split_messages(
        [
            ChatMessage(role="user", content="Erster Teil"),
            ChatMessage(role="user", content="Zweiter Teil"),
        ]
    )

    assert len(dialogue) == 1
    assert "Erster Teil" in dialogue[0]["content"]
    assert "Zweiter Teil" in dialogue[0]["content"]


def test_claude_api_dialogue_starts_with_user():
    _, dialogue = ClaudeProvider._split_messages(
        [
            ChatMessage(role="assistant", content="Vorherige Antwort"),
            ChatMessage(role="user", content="Frage"),
        ]
    )

    assert dialogue[0]["role"] == "user"


def test_claude_api_handles_empty_dialogue():
    _, dialogue = ClaudeProvider._split_messages(
        [ChatMessage(role="system", content="Nur Systemtext")]
    )

    assert dialogue
    assert dialogue[0]["role"] == "user"


async def test_claude_api_unavailable_without_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    provider = ClaudeProvider({})

    assert await provider.is_available() is False


def test_claude_api_explains_rejected_key():
    message = ClaudeProvider._explain_failure("claude: HTTP 401 – unauthorized")

    assert "Abonnement" in message
    assert "console.anthropic.com" in message


def test_claude_api_explains_unknown_model():
    message = ClaudeProvider._explain_failure("claude: HTTP 404 – not found")

    assert "auto" in message
