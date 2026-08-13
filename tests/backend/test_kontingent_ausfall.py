"""Der Orb bleibt am Leben, wenn das Claude-Guthaben aufgebraucht ist.

Der Ausfall, den der Benutzer meldete („der Orb läuft nicht mehr, wenn das
Claude-Guthaben aufgebraucht ist"), hatte im Protokoll zwei Ursachen, die
zusammen den Betrieb lahmlegten:

1. Die Befehlszeile meldete wörtlich „You've hit your session limit ·
   resets 2:20pm". Keiner der bisherigen Marker passte darauf - die
   Abkühlpause griff nie, und der Orb lief bei JEDER Frage erneut in
   dieselbe Wand (75 s Zeitlimit, neuer Prozess, dieselbe Meldung).
2. Der lokale Ausweg antwortete mit „HTTP 500 - timed out waiting for
   llama-server to start": ein KALTSTART, kein Ausfall. Damit war beides
   weg und der Orb stumm.

Diese Tests sichern beide Reparaturen.
"""

from __future__ import annotations

import asyncio

from backend.orchestrator.providers.base_provider import ProviderError
from backend.orchestrator.providers.claude_code_provider import _LIMIT_MARKERS
from backend.orchestrator.providers.ollama_provider import OllamaProvider

#: Das echte Warten wird in den Tests uebersprungen - aber ueber eine
#: gemerkte Urspruenglich-Funktion, sonst ruft der Ersatz sich selbst auf.
_echtes_sleep = asyncio.sleep


def _ohne_warten(monkeypatch):
    async def _sofort(_sekunden):
        await _echtes_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", _sofort)


# --- 1. Die Kontingent-Meldung wird erkannt --------------------------------


def test_session_limit_ist_ein_bekannter_marker():
    echte_meldung = "You've hit your session limit · resets 2:20pm (Etc/GMT-1)"
    knapp = echte_meldung.lower()
    assert any(marker in knapp for marker in _LIMIT_MARKERS), (
        "die echte Meldung der Befehlszeile wird nicht als Kontingentende erkannt"
    )


def test_weitere_grenzmeldungen_werden_erkannt():
    meldungen = [
        "You've hit your usage limit",
        "Rate limit exceeded",
        "Your credit balance is too low",
        "insufficient credits remaining",
        "429 Too Many Requests",
        "Nutzungsgrenze erreicht",
    ]
    for meldung in meldungen:
        knapp = meldung.lower()
        assert any(m in knapp for m in _LIMIT_MARKERS), meldung


def test_gewoehnliche_fehler_gelten_nicht_als_kontingentende():
    # Sonst legte ein harmloser Fehler Claude für eine halbe Stunde still.
    harmlos = [
        "claude_code: Zeitlimit von 75 s überschritten.",
        "connection refused",
        "Die Datei wurde nicht gefunden.",
    ]
    for meldung in harmlos:
        knapp = meldung.lower()
        assert not any(m in knapp for m in _LIMIT_MARKERS), meldung


# --- 2. Der Kaltstart des lokalen Modells wird ausgesessen ------------------


def _provider() -> OllamaProvider:
    return OllamaProvider({"model": "llama3.1:8b", "timeout": 5})


def test_kaltstart_wird_wiederholt_und_gelingt(monkeypatch):
    versuche: list[int] = []

    async def _antwort(url, *, payload=None, **kwargs):
        versuche.append(1)
        if len(versuche) < 2:
            raise ProviderError(
                'ollama: HTTP 500 – {"error":"timed out waiting for '
                'llama-server to start - "}'
            )
        return {"message": {"content": "Hallo!"}}

    p = _provider()
    monkeypatch.setattr(p, "_request_json", _antwort)
    _ohne_warten(monkeypatch)

    daten = asyncio.run(p._mit_ladegeduld("http://x/api/chat", {}))
    assert daten["message"]["content"] == "Hallo!"
    assert len(versuche) == 2, "der zweite Anlauf hat nicht stattgefunden"


def test_kaltstart_gibt_nach_mehreren_versuchen_klartext(monkeypatch):
    async def _immer_kalt(url, *, payload=None, **kwargs):
        raise ProviderError(
            'ollama: HTTP 500 – {"error":"timed out waiting for llama-server to start"}'
        )

    p = _provider()
    monkeypatch.setattr(p, "_request_json", _immer_kalt)
    _ohne_warten(monkeypatch)

    try:
        asyncio.run(p._mit_ladegeduld("http://x/api/chat", {}, versuche=2))
    except ProviderError as fehler:
        text = str(fehler)
        assert "ollama run" in text, "der Hinweis zur Selbsthilfe fehlt"
        assert "llama3.1:8b" in text
    else:
        raise AssertionError("es hätte ein Fehler kommen müssen")


def test_echte_fehler_werden_nicht_wiederholt(monkeypatch):
    # Ein Modell, das es nicht gibt, wird durch Warten nicht besser.
    versuche: list[int] = []

    async def _echter_fehler(url, *, payload=None, **kwargs):
        versuche.append(1)
        raise ProviderError('ollama: HTTP 404 – {"error":"model not found"}')

    p = _provider()
    monkeypatch.setattr(p, "_request_json", _echter_fehler)

    try:
        asyncio.run(p._mit_ladegeduld("http://x/api/chat", {}))
    except ProviderError:
        pass
    assert len(versuche) == 1, "ein echter Fehler wurde unnötig wiederholt"


def test_waermen_meldet_misserfolg_ohne_zu_reissen(monkeypatch):
    async def _kalt(url, *, payload=None, **kwargs):
        raise ProviderError("ollama: HTTP 500 – timed out waiting for llama-server")

    p = _provider()
    monkeypatch.setattr(p, "_request_json", _kalt)
    _ohne_warten(monkeypatch)

    assert asyncio.run(p.waermen()) is False  # kein Absturz, nur ein Nein
