"""Der Orb hakt nach, wenn das Modell die Werkzeuge nicht anfasst.

Die wiederkehrende Klage war "die Werkzeuge gehen nicht". Das Protokoll
zeigte etwas anderes: Sie GINGEN - im selben Lauf liefen Suche und Browser -,
aber auf manche Bitten (vor allem "schau dir den Bildschirm/das Video an")
antwortete das Modell in Prosa, es KOENNE nicht, statt das passende Werkzeug
zu rufen. Der Tool-Engine erkennt das jetzt und hakt GENAU EINMAL nach: Er
fordert das Modell auf, das Werkzeug wirklich zu rufen. Kommt dann ein
Aufruf, wird er ausgefuehrt.
"""

from __future__ import annotations

import asyncio

from backend.events.event_bus import EventBus
from backend.security.security_engine import SecurityEngine
from backend.tools.base_tool import Tool, ToolResult
from backend.tools.registry import ToolRegistry
from backend.tools.tool_engine import ToolEngine, _klingt_nach_ausrede
from backend.orchestrator.providers.base_provider import ChatMessage


class _MerkTool(Tool):
    name = "bildschirm_ansehen"
    description = "Macht ein Standbild und wertet es aus (Test)."
    permission = "screen_capture"
    parameters = ()

    def __init__(self) -> None:
        super().__init__()
        self.gerufen = 0

    async def execute(self, arguments):  # noqa: ANN001, D401
        self.gerufen += 1
        return ToolResult.success("Auf dem Bild ist ein Video zu sehen.")


class _FakeProvider:
    """Liefert der Reihe nach vorgegebene Antworten auf chat()."""

    def __init__(self, antworten):
        self._antworten = list(antworten)
        self.aufrufe = 0

    async def chat(self, history):  # noqa: ANN001
        self.aufrufe += 1
        text = self._antworten.pop(0) if self._antworten else ""

        class _R:
            pass

        r = _R()
        r.text = text
        return r


_AUFRUF = '```werkzeug\n{"werkzeug": "bildschirm_ansehen", "argumente": {}}\n```'


def _engine(provider):
    reg = ToolRegistry()
    tool = _MerkTool()
    reg.register(tool)
    eng = ToolEngine(
        registry=reg,
        security=SecurityEngine(event_bus=EventBus()),
        provider_manager=provider,
    )
    return eng, tool


def test_die_ausrede_wird_erkannt():
    assert _klingt_nach_ausrede("Ich kann das Video leider nicht anschauen.")
    assert _klingt_nach_ausrede("Ich habe keinen Zugriff auf die Konfiguration.")
    assert not _klingt_nach_ausrede("Klar, hier ist die Antwort.")


def test_nachhaken_erzwingt_den_werkzeugaufruf():
    """Erste Antwort ist eine Ausrede; nach dem Nachhaken kommt der Aufruf."""

    provider = _FakeProvider([_AUFRUF, "Auf dem Video laufen KI-Nachrichten."])
    eng, tool = _engine(provider)

    ausrede = "Ich kann kein Video wirklich anschauen, nur reden."
    antwort, runs = asyncio.run(
        eng.continue_with_tools(messages=[], first_reply=ausrede, actor="test")
    )

    assert tool.gerufen == 1, "Das Werkzeug wurde nach dem Nachhaken nicht gerufen."
    assert provider.aufrufe >= 1, "Es wurde gar nicht nachgehakt."
    assert "Video" in antwort


def test_ohne_ausrede_wird_nicht_nachgehakt():
    """Eine normale Antwort ohne Werkzeug bleibt, wie sie ist - kein Nachhaken."""

    provider = _FakeProvider(["sollte nicht gebraucht werden"])
    eng, tool = _engine(provider)

    antwort, runs = asyncio.run(
        eng.continue_with_tools(
            messages=[], first_reply="Die Hauptstadt von Frankreich ist Paris.",
            actor="test",
        )
    )
    assert provider.aufrufe == 0, "Ohne Ausrede darf nicht nachgehakt werden."
    assert tool.gerufen == 0
    assert "Paris" in antwort


def test_nachhaken_geschieht_nur_einmal():
    """Bleibt das Modell bei der Ausrede, endet es - keine Schleife."""

    provider = _FakeProvider([
        "Ich kann das leider nicht anschauen.",   # Antwort auf das Nachhaken
        "und immer noch nicht",                    # duerfte gar nicht gebraucht werden
    ])
    eng, tool = _engine(provider)

    antwort, runs = asyncio.run(
        eng.continue_with_tools(
            messages=[], first_reply="Ich kann kein Video anschauen.", actor="test",
        )
    )
    assert provider.aufrufe == 1, "Es darf nur EINMAL nachgehakt werden."
    assert tool.gerufen == 0


def test_nachhaken_auch_wenn_werkzeug_nur_benannt_wird():
    """Der Fall aus dem Protokoll: Das Modell NENNT das Werkzeug, ruft es
    aber nicht - dann muss der Orb ebenfalls nachhaken."""

    provider = _FakeProvider([_AUFRUF, "Auf dem Bild ist ein Dokument."])
    eng, tool = _engine(provider)

    # Keine klassische Ausrede - das Modell redet nur ueber das Werkzeug.
    benannt = "Ich koennte dafuer eigentlich bildschirm_ansehen benutzen."
    antwort, runs = asyncio.run(
        eng.continue_with_tools(messages=[], first_reply=benannt, actor="test")
    )

    assert tool.gerufen == 1, "Wird ein Werkzeug nur benannt, muss der Orb nachhaken."
    assert provider.aufrufe >= 1


def test_ausdruecklich_verlangtes_werkzeug_wird_nicht_still_ignoriert():
    provider = _FakeProvider([_AUFRUF, "Auf dem Bild ist ein Dokument."])
    eng, tool = _engine(provider)
    messages = [
        ChatMessage(
            role="user",
            content="Benutze bitte ausdrücklich das Werkzeug bildschirm_ansehen.",
        )
    ]

    antwort, runs = asyncio.run(
        eng.continue_with_tools(
            messages=messages,
            first_reply="Gern, ich beschreibe dir einfach allgemein den Bildschirm.",
            actor="test",
        )
    )

    assert tool.gerufen == 1
    assert runs and runs[0].result.ok
    assert "Dokument" in antwort


def test_vorab_ausgefuehrte_bildanalyse_wird_nicht_wiederholt():
    """Ein erzwungener Screenshot ist schon das Werkzeugergebnis.

    Fordert das Modell denselben Aufruf trotzdem noch einmal, darf daraus
    kein zweiter Screenshot samt zweiter Modellanalyse werden.
    """

    provider = _FakeProvider(["sollte nicht gebraucht werden"])
    eng, tool = _engine(provider)

    antwort, runs = asyncio.run(
        eng.continue_with_tools(
            messages=[],
            first_reply=_AUFRUF,
            actor="test",
            preexecuted={
                "bildschirm_ansehen": "Auf dem Bild ist eine Handschrift zu sehen."
            },
        )
    )

    assert tool.gerufen == 0
    assert provider.aufrufe == 0
    assert runs == []
    assert "Handschrift" in antwort
