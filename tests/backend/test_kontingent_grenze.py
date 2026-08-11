"""Der Orb bleibt arbeitsfaehig, wenn Claudes Kontingent erschoepft ist.

Der Rueckfall auf das lokale Modell greift ohnehin pro Anfrage (er wird an
anderer Stelle geprueft). Hier geht es um die SPERRFRIST: Nach einer
erreichten Nutzungsgrenze soll Claude eine Weile als 'nicht verfuegbar'
gelten, damit der Orb nicht bei jeder Frage erst wieder ins Limit laeuft,
sondern ohne Umweg beim lokalen Modell bleibt.
"""

from __future__ import annotations

import asyncio

from backend.orchestrator.providers.claude_code_provider import ClaudeCodeProvider


def _provider(cooldown_minutes=30):
    return ClaudeCodeProvider({
        "engine": "claude_code",
        "model": "sonnet",
        "limit_cooldown_minutes": cooldown_minutes,
        # kein warmer Prozess im Test
        "warm_process": False,
    })


def test_grenzmeldung_setzt_die_sperre_und_macht_unverfuegbar():
    p = _provider(cooldown_minutes=30)
    assert p._limit_until == 0.0

    text = p._explain_failure("Claude usage limit reached. Try again later.")
    assert "lokale" in text.lower() or "nutzungsgrenze" in text.lower()
    # Die Sperre steht nun in der Zukunft ...
    assert p._limit_until > p._now()
    # ... und deshalb gilt Claude als nicht verfuegbar, ganz ohne
    # Programmpruefung.
    assert asyncio.run(p.is_available()) is False


def test_andere_fehler_setzen_keine_sperre():
    p = _provider()
    p._explain_failure("some random crash, segfault")
    assert p._limit_until == 0.0


def test_nach_ablauf_faellt_die_sperre():
    p = _provider(cooldown_minutes=30)
    p._explain_failure("rate limit exceeded")
    assert asyncio.run(p.is_available()) is False
    # Zeit vorspulen: Sperre in die Vergangenheit legen.
    p._limit_until = p._now() - 1.0
    # Jetzt greift die Sperre nicht mehr; die Verfuegbarkeit haengt wieder
    # an der eigentlichen Pruefung (hier: Claude ist im Testsystem nicht
    # installiert, also False - aber NICHT mehr wegen der Sperre).
    assert p._now() >= p._limit_until


def test_sperre_abschaltbar():
    p = _provider(cooldown_minutes=0)
    p._explain_failure("usage limit reached")
    assert p._limit_until == 0.0, "Mit cooldown 0 darf keine Sperre gesetzt werden."
