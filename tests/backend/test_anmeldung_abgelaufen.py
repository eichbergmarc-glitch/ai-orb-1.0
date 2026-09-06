"""Eine abgelaufene Anmeldung darf nur einmal kosten.

Belegt am laufenden Orb, Protokoll vom 06.09.2026:

    12:44:13  claude_code lieferte noch keinen Text
              (Failed to authenticate: OAuth session expired ...)
    12:46:05  claude_code lieferte noch keinen Text
              (dieselbe Meldung)

Zwei volle Fehlversuche, bevor der Anbieter nach hinten rueckte - und nach
jedem Neustart von vorn, weil der Fehlerzaehler bei null beginnt. Der
Ausgang des zweiten Versuchs stand von Anfang an fest.
"""

from __future__ import annotations

from backend.orchestrator.provider_health import ProviderHealth
from backend.orchestrator.provider_manager import ProviderManager
from backend.orchestrator.providers.base_provider import (
    BaseProvider,
    ProviderError,
    ProviderResponse,
)
from backend.orchestrator.providers.claude_code_provider import ClaudeCodeProvider


_ECHTE_MELDUNG = (
    "claude_code: Antwortstrom vor dem ersten Text gescheitert: claude_code: "
    "Failed to authenticate: OAuth session expired and could not be refreshed"
)


class _Provider(BaseProvider):
    def __init__(self, name: str) -> None:
        super().__init__({"model": name})
        self.name = name

    async def is_available(self) -> bool:
        return True

    async def chat(self, messages, **kwargs) -> ProviderResponse:
        return ProviderResponse("ok", self.name, self.model)

    async def chat_stream(self, messages, **kwargs):
        yield "ok"


def _manager() -> ProviderManager:
    cloud = _Provider("claude_code")
    lokal = _Provider("ollama")
    manager = ProviderManager.__new__(ProviderManager)
    manager._providers = {cloud.name: cloud, lokal.name: lokal}
    manager._primary_name = cloud.name
    manager._fallback_name = lokal.name
    manager._active_name = cloud.name
    manager._operating_mode = "auto"
    manager._health = ProviderHealth()
    manager._health.register(cloud)
    manager._health.register(lokal)
    # Ausgangslage wie im Protokoll: die Startpruefung hat beide als
    # verfuegbar gemeldet ("Provider-Verfuegbarkeit beim Start:
    # {'claude_code': True, 'ollama': True, ...}").
    for name in (cloud.name, lokal.name):
        manager._health.record(name).available = True
    return manager


def test_anmeldefehler_zaehlt_sofort_und_nicht_erst_beim_zweiten_mal():
    manager = _manager()

    manager._note_provider_error("claude_code", ProviderError(_ECHTE_MELDUNG))

    eintrag = manager._health.record("claude_code")
    assert eintrag.available is False, "ein belegter Anmeldefehler heilt nicht"
    assert eintrag.consecutive_failures == 1
    assert manager._ist_bekannt_gestoert("claude_code") is True


def test_der_angemeldete_anbieter_steht_danach_hinten():
    manager = _manager()

    assert manager._provider_order()[0] == "claude_code"

    manager._note_provider_error("claude_code", ProviderError(_ECHTE_MELDUNG))

    reihenfolge = manager._provider_order()
    assert reihenfolge[0] == "ollama"
    assert reihenfolge[-1] == "claude_code", "nicht raus, nur nach hinten"


def test_ein_einzelner_aussetzer_wirft_niemanden_aus_der_reihe():
    """Die Regel 'zwei Fehlschlaege' gilt fuer alles andere weiter."""

    manager = _manager()

    manager._note_provider_error(
        "claude_code", ProviderError("claude_code: Zeitlimit ueberschritten")
    )

    assert manager._health.record("claude_code").available is True
    assert manager._provider_order()[0] == "claude_code"


def _claude(tmp_path) -> ClaudeCodeProvider:
    return ClaudeCodeProvider({"model": "sonnet", "auth_cooldown_minutes": 15})


def test_die_echte_meldung_wird_als_anmeldefehler_erkannt(tmp_path):
    provider = _claude(tmp_path)

    klartext = provider._explain_failure(
        "Failed to authenticate: OAuth session expired and could not be refreshed"
    )

    assert "nicht angemeldet" in klartext
    assert "claude" in klartext.lower()


async def test_nach_dem_anmeldefehler_meldet_sich_claude_nicht_mehr_verfuegbar(tmp_path):
    provider = _claude(tmp_path)

    provider._explain_failure(
        "Failed to authenticate: OAuth session expired and could not be refreshed"
    )

    assert await provider.is_available() is False, (
        "'claude --version' antwortet auch ohne gueltige Anmeldung sauber - "
        "die Sperrfrist ist die einzige Stelle, an der es auffaellt"
    )


def test_die_originalmeldung_bleibt_im_protokoll(tmp_path, caplog) -> None:
    """Der Klartextsatz ist fuer den Benutzer, die Rohmeldung fuer die Suche.

    Am 06.09. meldete die Befehlszeile im Orb "nicht angemeldet", waehrend
    derselbe Aufruf im Terminal desselben Rechners anstandslos antwortete.
    Womit sich das haette klaeren lassen - der Originaltext und der Kontext
    des Unterprozesses -, hatte ``_explain_failure`` gerade ueberschrieben.
    """

    import logging

    provider = _claude(tmp_path)
    with caplog.at_level(logging.WARNING):
        provider._explain_failure(
            "Failed to authenticate: OAuth session expired and could not be refreshed"
        )

    protokoll = "\n".join(eintrag.getMessage() for eintrag in caplog.records)
    assert "OAuth session expired" in protokoll, "die Rohmeldung fehlt"
    assert "USERPROFILE" in protokoll, "der Kontext des Unterprozesses fehlt"
    assert "Arbeitsverzeichnis" in protokoll
