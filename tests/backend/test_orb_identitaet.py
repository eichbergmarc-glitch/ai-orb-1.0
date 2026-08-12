"""Der Orb bleibt AI-Orb - auch gegenueber Claude Codes Selbstauskunft.

Im Protokoll beharrte das Modell "Ich bin Claude Code im Repository
claude_workspace" und benutzte deshalb die Orb-Werkzeuge nicht. Die
Orb-Identitaet wird darum auf System-Ebene mitgegeben ('--append-system-
prompt'), sofern die CLI-Fassung den Schalter kennt.
"""

from __future__ import annotations

from backend.orchestrator.providers.claude_code_provider import (
    _IDENTITAET,
    ClaudeCodeProvider,
)


def _provider():
    return ClaudeCodeProvider({"engine": "claude_code", "warm_process": False})


def test_identitaet_wird_als_systemprompt_mitgegeben_wenn_moeglich():
    p = _provider()
    p._flags = frozenset({"--append-system-prompt"})
    flags = p._tempo_flags()
    assert "--append-system-prompt" in flags
    i = flags.index("--append-system-prompt")
    assert flags[i + 1] == _IDENTITAET


def test_ohne_den_schalter_wird_nichts_erzwungen():
    p = _provider()
    p._flags = frozenset()  # Fassung kennt den Schalter nicht
    assert "--append-system-prompt" not in p._tempo_flags()


def test_die_identitaet_verneint_claude_code_ausdruecklich():
    low = _IDENTITAET.lower()
    assert "ai-orb" in low
    assert "nicht claude code" in low or "nicht claude" in low
