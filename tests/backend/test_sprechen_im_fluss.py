"""Tests des Sprechens im Fluss - reden, waehrend noch gedacht wird.

Der Orb wartete bisher die vollstaendige Antwort ab, bevor er ein Wort
sagte. Bei einer dreisaetzigen Antwort waren das mehrere Sekunden Stille,
obwohl der erste Satz laengst fertig war.

Jetzt spricht er jeden Satz, sobald er beisammen ist. Der Denkweg bleibt
dabei vollstaendig - mit Absicht, Gedaechtnis und Werkzeugen. Geprueft
wird genau das Heikle daran: dass ein Werkzeugaufruf nie vorgelesen wird
und dass keine Antwort zweimal kommt.
"""

from __future__ import annotations

import asyncio

from backend.memory.memory_engine import MemoryEngine
from backend.orchestrator.orchestrator import Orchestrator
from backend.orchestrator.providers.base_provider import ProviderResponse


class _Anbieter:
    """Ein Anbieter, der eine vorbereitete Antwort in Silben liefert."""

    def __init__(self, antworten: list[str]):
        self.antworten = list(antworten)
        self.gefragt = 0
        self.active_name = "test"
        self.local_provider_names: list[str] = []
        self.stream_kwargs: list[dict] = []

    def begin_conversation(self) -> None:
        pass

    def _naechste(self) -> str:
        text = self.antworten[min(self.gefragt, len(self.antworten) - 1)]
        self.gefragt += 1
        return text

    async def chat_stream(self, messages, **kw):
        self.stream_kwargs.append(dict(kw))
        for stueck in _silben(self._naechste()):
            await asyncio.sleep(0)
            yield stueck

    async def chat(self, messages, **kw):
        return ProviderResponse(
            text=self._naechste(), provider="test", model="test", latency_seconds=0.0
        )


def _silben(text: str, breite: int = 4) -> list[str]:
    return [text[i : i + breite] for i in range(0, len(text), breite)]


class _Werkzeuge:
    """Eine Werkzeugschleife, die so tut, als haette sie gearbeitet."""

    enabled = True

    def __init__(self, endantwort: str | None = None, laeufe: int = 0):
        self.endantwort = endantwort
        self.laeufe = laeufe

    def system_instructions(self) -> str:
        return "Werkzeuge: internet_suchen"

    async def continue_with_tools(
        self, messages, first_reply, *, actor="gespraech", preexecuted=None
    ):
        if self.endantwort is None:
            # Kein Werkzeug im Spiel: Die erste Antwort ist die endgueltige.
            return first_reply, []
        return self.endantwort, [object()] * self.laeufe


class _BildWerkzeug(_Werkzeuge):
    async def direkt_ausfuehren(self, name, arguments, *, actor="vorab"):
        class _Result:
            ok = True
            output = "Auf dem Bild ist eine goldene mittelalterliche Handschrift."
            error = ""

        class _Run:
            result = _Result()
            seconds = 0.1

        return _Run()


def _orchestrator(anbieter, werkzeuge=None) -> Orchestrator:
    orch = Orchestrator(
        memory=MemoryEngine(),
        provider_manager=anbieter,
    )
    if werkzeuge is not None:
        orch.attach_tool_engine(werkzeuge)
    return orch


def _lauf(orch, frage: str):
    """Stellt eine Frage und sammelt, was dabei gesprochen wurde."""

    gesagt: list[str] = []

    async def sprich(satz: str) -> bool:
        gesagt.append(satz)
        return True

    ergebnis = asyncio.run(orch.handle(frage, spoken=True, on_speech=sprich))
    return ergebnis, gesagt


def test_saetze_werden_einzeln_gesprochen():
    """Nicht ein Block am Ende, sondern Satz fuer Satz."""

    anbieter = _Anbieter(["Es ist kalt. Der Wind weht stark. Zieh dich warm an."])
    orch = _orchestrator(anbieter, _Werkzeuge())

    ergebnis, gesagt = _lauf(orch, "Wie ist das Wetter?")

    assert gesagt == [
        "Es ist kalt.",
        "Der Wind weht stark.",
        "Zieh dich warm an.",
    ]
    assert ergebnis.data["gesprochen"] is True


def test_einfache_sprachfrage_nimmt_sofort_das_lokale_modell():
    anbieter = _Anbieter(["Das ist eine kurze Antwort."])
    anbieter.local_provider_names = ["ollama"]
    orch = _orchestrator(anbieter, _Werkzeuge())

    _lauf(orch, "Kannst du mir deine neuen Funktionen erklaeren?")

    assert anbieter.stream_kwargs[-1]["preferred"] == "ollama"
    assert anbieter.stream_kwargs[-1]["max_tokens"] == 40


def test_aktuelle_sprachfrage_bleibt_beim_starken_provider():
    anbieter = _Anbieter(["Das ist eine aktuelle Antwort."])
    anbieter.local_provider_names = ["ollama"]
    orch = _orchestrator(anbieter, _Werkzeuge())

    _lauf(orch, "Was sind die aktuellen Nachrichten?")

    assert anbieter.stream_kwargs[-1]["preferred"] is None


def test_allgemeine_erklaerung_bleibt_im_schnellen_sprachweg():
    anbieter = _Anbieter(["Ein Regenbogen entsteht durch Lichtbrechung."])
    anbieter.local_provider_names = ["ollama"]
    orch = _orchestrator(anbieter, _Werkzeuge())

    _lauf(orch, "Erklaere mir in einem Satz, was ein Regenbogen ist.")

    assert anbieter.stream_kwargs[-1]["preferred"] == "ollama"


def test_werkzeugaufruf_wird_nie_vorgelesen():
    """Der wichtigste Test: Maschinensprache darf nie zur Sprache werden."""

    erste = (
        "Ich schaue kurz nach.\n"
        "```werkzeug\n"
        '{"werkzeug": "internet_suchen", "argumente": {"frage": "Wetter Bern"}}\n'
        "```"
    )
    anbieter = _Anbieter([erste])
    werkzeuge = _Werkzeuge(endantwort="In Bern sind es zwoelf Grad.", laeufe=1)
    orch = _orchestrator(anbieter, werkzeuge)

    ergebnis, gesagt = _lauf(orch, "Wie ist das Wetter in Bern?")

    zusammen = " ".join(gesagt)
    assert "```" not in zusammen
    assert "internet_suchen" not in zusammen
    assert "{" not in zusammen
    # Erst die Ansage, dann - nach dem Werkzeug - die eigentliche Antwort.
    assert gesagt == ["Ich schaue kurz nach.", "In Bern sind es zwoelf Grad."]
    assert ergebnis.response == "In Bern sind es zwoelf Grad."
    assert ergebnis.data["werkzeugaufrufe"] == 1


def test_nichts_wird_zweimal_gesagt():
    """Ohne Werkzeug ist die gestreamte Antwort schon die endgueltige."""

    anbieter = _Anbieter(["Erstens dies. Zweitens das."])
    orch = _orchestrator(anbieter, _Werkzeuge())

    _, gesagt = _lauf(orch, "Sag etwas.")

    assert gesagt == ["Erstens dies.", "Zweitens das."]
    assert len(gesagt) == len(set(gesagt)), "ein Satz kam doppelt"


def test_letzter_satz_ohne_punkt_geht_nicht_verloren():
    anbieter = _Anbieter(["Alles klar. Und noch etwas ohne Punkt"])
    orch = _orchestrator(anbieter, _Werkzeuge())

    _, gesagt = _lauf(orch, "Sag etwas.")

    assert " ".join(gesagt).endswith("ohne Punkt")


def test_langer_einzelsatz_beginnt_vor_dem_schlusspunkt():
    text = (
        "Ein Regenbogen entsteht, wenn Sonnenlicht in vielen feinen "
        "Wassertropfen gebrochen, gespiegelt und in seine Farben zerlegt wird."
    )
    anbieter = _Anbieter([text])
    orch = _orchestrator(anbieter, _Werkzeuge())

    _, gesagt = _lauf(
        orch, "Erklaere mir in einem Satz, was ein Regenbogen ist."
    )

    assert len(gesagt) >= 2
    assert len(gesagt[0]) < len(text)
    assert " ".join(gesagt).replace("  ", " ") == text


def test_ohne_rueckruf_bleibt_alles_wie_bisher():
    """Der getippte Weg darf sich durch all das nicht veraendern."""

    anbieter = _Anbieter(["Eine ganz gewoehnliche Antwort."])
    orch = _orchestrator(anbieter, _Werkzeuge())

    ergebnis = asyncio.run(orch.handle("Wie geht es dir?"))

    assert ergebnis.response == "Eine ganz gewoehnliche Antwort."
    assert ergebnis.data.get("gesprochen") is False


def test_gesprochene_bildanalyse_wird_nicht_zweimal_vom_modell_bearbeitet():
    """Die Werkzeugantwort ist bereits die angeforderte Bildbeschreibung."""

    anbieter = _Anbieter(["Diese zweite Modellantwort darf nicht entstehen."])
    orch = _orchestrator(anbieter, _BildWerkzeug())

    ergebnis = asyncio.run(
        orch.handle(
            "Mach einen Printscreen und analysiere das Bild.",
            spoken=True,
        )
    )

    assert anbieter.gefragt == 0
    assert "Handschrift" in ergebnis.response
    assert ergebnis.data["direkte_bildantwort"] is True


# --- Und der Fehler, der den Orb verstummen liess ------------------------------


def test_stumme_sprachausgabe_gilt_nicht_als_gesprochen():
    """Der wichtigste Test dieser Datei.

    Vorher galt eine Antwort als gesprochen, sobald der Satz an die
    Sprachausgabe weitergegeben war. Schlug die still fehl, meldete der Weg
    trotzdem "schon gesagt" - und die Sprachschicht verzichtete darauf, sie
    noch einmal zu sprechen. Der Orb dachte, antwortete, hielt es fuer
    erledigt und blieb stumm.
    """

    anbieter = _Anbieter(["Es ist kalt. Zieh dich warm an."])
    orch = _orchestrator(anbieter, _Werkzeuge())

    versucht: list[str] = []

    async def stumm(satz: str) -> bool:
        versucht.append(satz)
        return False  # die Sprachausgabe bringt nichts heraus

    ergebnis = asyncio.run(orch.handle("Wie ist das Wetter?", spoken=True, on_speech=stumm))

    assert versucht, "es wurde nicht einmal versucht zu sprechen"
    assert ergebnis.data["gesprochen"] is False, (
        "eine stumme Ausgabe wurde als gesprochen gemeldet - der Orb bliebe stumm"
    )
    assert ergebnis.response


def test_teilweise_gesprochen_zaehlt_als_gesprochen():
    """Kam etwas heraus, darf die Antwort nicht ein zweites Mal kommen."""

    anbieter = _Anbieter(["Erstens dies. Zweitens das."])
    orch = _orchestrator(anbieter, _Werkzeuge())

    async def erster_satz_klappt(satz: str) -> bool:
        return satz.startswith("Erstens")

    ergebnis = asyncio.run(
        orch.handle("Sag etwas.", spoken=True, on_speech=erster_satz_klappt)
    )

    assert ergebnis.data["gesprochen"] is True
