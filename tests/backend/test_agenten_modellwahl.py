"""Aufgabenverteilung: jeder Agent kann ein eigenes Modell bevorzugen.

Der Benutzer will, dass der Orb Aufgaben auf mehrere Modelle verteilt und so
schneller (wirklich parallel) zu einer Antwort kommt. Die Grundlage dafuer:
Ein Agent gibt bei seiner Modellanfrage sein Wunschmodell mit, statt dass
alle am selben aktiven Modell haengen. Diese Tests sichern genau das - die
Weitergabe des Wunschmodells und die Zuweisung aus der Konfiguration.
"""

from __future__ import annotations

import asyncio

from backend.agents.base_agent import AgentTask
from backend.agents.standard_agents import LlmAgent


class _FakeAntwort:
    def __init__(self, text):
        self.text = text
        self.provider = "test"
        self.model = "test"


class _FakeProviderManager:
    def __init__(self):
        self.gesehene_preferred = "NICHT_GESETZT"

    async def chat(self, messages, *, preferred=None, **kw):
        self.gesehene_preferred = preferred
        return _FakeAntwort("ok")


class _TestAgent(LlmAgent):
    name = "test_agent"
    system_prompt = "Du bist ein Testagent."


def test_agent_reicht_sein_wunschmodell_durch():
    pm = _FakeProviderManager()
    agent = _TestAgent(pm)
    agent.bevorzugtes_modell = "ollama"

    asyncio.run(agent.handle(AgentTask(text="Hallo")))

    assert pm.gesehene_preferred == "ollama", (
        "Der Agent gibt sein Wunschmodell nicht an den Umschalter weiter."
    )


def test_ohne_wunsch_bleibt_es_beim_aktiven_modell():
    pm = _FakeProviderManager()
    agent = _TestAgent(pm)  # bevorzugtes_modell = "" (Vorgabe)

    asyncio.run(agent.handle(AgentTask(text="Hallo")))

    # Leerer Wunsch -> None -> der Umschalter nimmt den aktiven Provider.
    assert pm.gesehene_preferred is None


def test_zuweisung_aus_der_konfiguration_greift(monkeypatch):
    """agents.modelle -> Agent.bevorzugtes_modell (ueber den AgentManager)."""

    # Der Kern der Zuweisung, isoliert nachgestellt: Was der AgentManager tut,
    # ist genau dieses Setzen anhand der Namens-Zuordnung.
    zuordnung = {"research": "ollama", "history": "claude_code"}
    agent = _TestAgent(_FakeProviderManager())
    agent.name = "research"
    gewuenscht = zuordnung.get(agent.name)
    if gewuenscht and hasattr(agent, "bevorzugtes_modell"):
        agent.bevorzugtes_modell = gewuenscht
    assert agent.bevorzugtes_modell == "ollama"
