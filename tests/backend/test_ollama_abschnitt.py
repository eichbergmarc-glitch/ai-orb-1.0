"""Tests dafür, wo der Starter sein Offline-Modell sucht.

Der Fall, den sie festhalten: Nach der Umstellung auf Offline-Betrieb steht
Ollama unter ``ai.primary`` und der Netzanbieter unter ``ai.fallback``. Der
Starter sah aber fest unter ``ai.fallback`` nach, fragte Ollama dort nach
``sonnet``, fand es nicht - und meldete beim Hochfahren eine Einschränkung,
die es nicht gab: das lokale Modell müsse erst geladen werden, mehrere
Gigabyte. Es lag längst da.

Eine Meldung, die eine gesunde Anlage für krank erklärt, ist schlimmer als
gar keine: Sie lässt einen an der falschen Stelle suchen.
"""

from __future__ import annotations

import pytest

from backend.launcher.ollama_service import OllamaService


class _Konfiguration:
    """Eine Konfiguration, die nur den ai-Abschnitt kennt."""

    def __init__(self, ai: dict) -> None:
        self._ai = ai

    def get(self, pfad: str, standard=None):
        wert = {"ai": self._ai}
        for teil in pfad.split("."):
            if not isinstance(wert, dict):
                return standard
            wert = wert.get(teil)
        return standard if wert is None else wert


@pytest.fixture()
def konfiguration(monkeypatch):
    def stellen(ai: dict):
        import backend.config as konf

        monkeypatch.setattr(konf, "get_config", lambda: _Konfiguration(ai))
    return stellen


OLLAMA = {"engine": "ollama", "model": "lfm2.5:8b",
          "base_url": "http://127.0.0.1:11434"}
CLAUDE = {"engine": "claude_code", "model": "sonnet"}


def test_offline_betrieb_ollama_steht_vorn(konfiguration):
    """Der Regressionsfall: getauschte Abschnitte."""

    konfiguration({"primary": OLLAMA, "fallback": CLAUDE})
    assert OllamaService().configured_model() == "lfm2.5:8b"


def test_online_betrieb_ollama_steht_hinten(konfiguration):
    konfiguration({"primary": CLAUDE, "fallback": OLLAMA})
    assert OllamaService().configured_model() == "lfm2.5:8b"


def test_adresse_kommt_aus_demselben_abschnitt(konfiguration):
    konfiguration({"primary": dict(OLLAMA, base_url="http://127.0.0.1:9999"),
                   "fallback": CLAUDE})
    assert OllamaService().base_url() == "http://127.0.0.1:9999"


def test_nennt_kein_abschnitt_ollama_bleibt_die_vorgabe(konfiguration):
    konfiguration({"primary": CLAUDE, "fallback": {"engine": "openai", "model": "gpt"}})
    assert OllamaService().configured_model() == "gpt"


def test_ausdrueckliche_angabe_schlaegt_die_konfiguration(konfiguration):
    konfiguration({"primary": OLLAMA, "fallback": CLAUDE})
    assert OllamaService(model="gemma2:2b").configured_model() == "gemma2:2b"
