"""Tests der Bildauswertung.

Der Orb konnte nichts auf dem Bildschirm sehen. Im Protokoll stand bei
jedem Versuch derselbe Satz:

    TypeError: ProviderManager.chat() got an unexpected keyword argument
    'system_prompt'

Die Bildauswertung ruft `complete(prompt, system_prompt=...)` auf, und
`complete` reichte alle weiteren Angaben unbesehen an `chat` weiter - die
weder `system_prompt` noch `images` kennt. Nach aussen kam davon nichts an,
nur "die Auswertung ist fehlgeschlagen".

Dahinter lag ein zweiter Fehler, den der erste verdeckte: Claude Code liest
nur innerhalb seines Arbeitsverzeichnisses, und das ist hier bewusst ein
leerer eigener Ordner. Die Aufnahme liegt daneben. Der Pfad wurde also
genannt, die Datei existierte, und die CLI durfte trotzdem nicht hinsehen -
das haette man erst nach der Behebung des ersten Fehlers gemerkt.
"""

from __future__ import annotations

import asyncio
import inspect

from backend.orchestrator.provider_manager import ProviderManager
from backend.orchestrator.providers.base_provider import (
    ChatMessage,
    ProviderError,
    ProviderResponse,
)
from backend.orchestrator.providers.openai_compatible_provider import (
    OpenAICompatibleProvider,
)


class _Anbieter:
    """Ein Anbieter, der sich merkt, was bei ihm ankommt."""

    supports_images = False
    reads_local_files = True

    def __init__(self):
        self.empfangen: list[ChatMessage] = []

    async def chat(self, messages, **kw):
        self.empfangen = list(messages)
        return ProviderResponse(
            text="Ein Fenster mit einer Tabelle.",
            provider="test",
            model="test",
            latency_seconds=0.0,
        )


def _verwalter(anbieter):
    verwalter = ProviderManager.__new__(ProviderManager)
    verwalter._active_name = "test"
    verwalter._providers = {"test": anbieter}

    async def _chat(messages, **kw):
        return await anbieter.chat(messages, **kw)

    verwalter.chat = _chat
    return verwalter


def test_ein_systemprompt_laesst_die_anfrage_nicht_mehr_platzen():
    """Der Fehler, wegen dem der Orb nichts sehen konnte."""

    anbieter = _Anbieter()
    antwort = asyncio.run(
        ProviderManager.complete(
            _verwalter(anbieter),
            "Was ist auf dem Bild?",
            system_prompt="Du beschreibst Bildschirmbilder sachlich.",
        )
    )

    assert antwort == "Ein Fenster mit einer Tabelle."


def test_der_systemprompt_kommt_auch_wirklich_an():
    """Ihn stillschweigend zu schlucken waere kaum besser als der Absturz."""

    anbieter = _Anbieter()
    asyncio.run(
        ProviderManager.complete(
            _verwalter(anbieter),
            "Was ist auf dem Bild?",
            system_prompt="Sachlich und knapp.",
        )
    )

    rollen = [m.role for m in anbieter.empfangen]
    assert rollen == ["system", "user"], rollen
    assert anbieter.empfangen[0].content == "Sachlich und knapp."


def test_ohne_systemprompt_bleibt_es_bei_einer_nachricht():
    anbieter = _Anbieter()
    asyncio.run(ProviderManager.complete(_verwalter(anbieter), "Hallo"))

    assert [m.role for m in anbieter.empfangen] == ["user"]


def test_bilddaten_werden_nicht_stillschweigend_verschluckt():
    """Sie fallen zu lassen waere schlimmer als der alte Fehler.

    Kein Anbieter hier kann Bilddaten im Verlauf entgegennehmen. Wer sie
    mitgibt, bekommt deshalb eine deutliche Auskunft - und kann auf den
    Weg ausweichen, den es wirklich gibt: den Pfad nennen.
    """

    anbieter = _Anbieter()
    try:
        asyncio.run(
            ProviderManager.complete(
                _verwalter(anbieter),
                "Was ist da?",
                images=[{"media_type": "image/png", "data": "AAAA"}],
            )
        )
    except ProviderError as fehler:
        assert "keine Bilddaten" in str(fehler)
    else:
        raise AssertionError("Bilddaten wurden stillschweigend verworfen")


def test_complete_nimmt_die_angaben_ausdruecklich_entgegen():
    """Ein blosses **kwargs war die Ursache - es darf nicht zurueckkommen."""

    unterschrift = inspect.signature(ProviderManager.complete)
    assert "system_prompt" in unterschrift.parameters
    assert "images" in unterschrift.parameters


# --- Und der Ordner, in dem die Aufnahme liegt ----------------------------------


def test_der_bildordner_wird_der_cli_freigegeben():
    """Sonst nennt man einen Pfad, den die CLI nicht oeffnen darf."""

    from backend.utils.paths import get_project_root

    quelle = (
        get_project_root()
        / "backend"
        / "orchestrator"
        / "providers"
        / "claude_code_provider.py"
    ).read_text(encoding="utf-8")

    assert "--add-dir" in quelle, "der Bildordner wird nicht freigegeben"
    assert "self._bildordner" in quelle


def test_freigegeben_wird_nur_der_bildordner():
    """Im Datenordner darueber liegen Konfiguration und Stimmprofil.

    Die gehen einer Bildbeschreibung nichts an - und eine Freigabe, die
    weiter reicht als noetig, faellt niemandem auf, solange sie
    funktioniert.
    """

    from backend.utils.paths import get_project_root

    quelle = (
        get_project_root()
        / "backend"
        / "orchestrator"
        / "providers"
        / "claude_code_provider.py"
    ).read_text(encoding="utf-8")

    stelle = quelle.index("self._bildordner: Path =")
    zeile = quelle[stelle : quelle.index("\n", stelle)]
    assert '"vision"' in zeile, f"freigegeben wird etwas anderes: {zeile}"


def test_der_aktive_hauptprovider_kann_bildschirmbilder_sehen():
    """Wer auch immer vorne steht - er muss den Bildschirm ansehen koennen.

    Der Test hing frueher am Namen "openai" fest und war nach jedem Wechsel
    des Hauptmodells rot, ohne dass etwas kaputt war. Gemeint war nie der
    Name, sondern die Faehigkeit - und die gibt es auf zwei Wegen, genau wie
    in ``vision_engine.describe``:

    * ``supports_images``: Das Bild geht als Datenstrom mit (OpenAI).
    * ``reads_local_files``: Der Anbieter bekommt den PFAD und oeffnet die
      Datei selbst (Claude Code).

    Einer von beiden muss zutreffen. Trifft keiner zu, landet der Orb beim
    Rueckfall auf Texterkennung und meldet, er koenne keine Bilder ansehen.
    """

    from backend.ai.provider_factory import build_provider
    from backend.config import get_config

    einstellungen = dict(get_config().section("ai").get("primary") or {})
    gebaut = build_provider(einstellungen)
    provider = getattr(gebaut, "provider", gebaut)

    kann_bilder = bool(getattr(provider, "supports_images", False))
    liest_dateien = bool(getattr(provider, "reads_local_files", False))

    assert kann_bilder or liest_dateien, (
        f"Der Hauptprovider '{provider.name}' kann Bildschirmbilder weder "
        "als Daten annehmen noch selbst von der Platte lesen."
    )
