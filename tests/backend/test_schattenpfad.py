"""Der Schattenlauf im echten Pfad - und der Beweis, dass er nichts anfasst.

Diese Tests fahren den echten ``Orchestrator.handle`` und prüfen an seinem
Ergebnis, dass der Schattenlauf lief UND dass die Antwort des Benutzers
davon unberührt blieb - auch dann, wenn der Schatten scheitert, hängt oder
gar nicht erst gebaut werden kann.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from backend.lernen.schattenlauf import Schattenbuch
from backend.lernen.schattenpfad import Schattenwaechter, aufgabenmuster_bilden


# --- Doppel ---------------------------------------------------------------


class _Speicher:
    def __init__(self) -> None:
        self._daten: dict[str, Any] = {"lehren": []}

    def get(self, schluessel: str, standard: Any = None) -> Any:
        return self._daten.get(schluessel, standard)

    def set(self, schluessel: str, wert: Any, *, persist: bool = True) -> None:
        self._daten[schluessel] = wert


def _buch(*, aktiv: bool = True) -> Schattenbuch:
    buch = Schattenbuch(store=_Speicher())
    buch._aktiv = aktiv
    buch._je_stunde = 20
    return buch


class _Anbieter:
    """Ein Providerdoppel: der Lehrer antwortet, der Schatten fragt hier auch."""

    active_name = "test"

    def __init__(self, *, schattenantwort: str = "Kurz.", fehler: bool = False,
                 verzoegerung: float = 0.0) -> None:
        self.schattenantwort = schattenantwort
        self.fehler = fehler
        self.verzoegerung = verzoegerung
        self.anfragen: list[str] = []
        self.schattenanfragen = 0

    def begin_conversation(self) -> None:
        pass

    def status(self) -> dict[str, Any]:
        return {"mode": "auto", "active": "test"}

    async def chat(self, messages, **kw):
        from backend.orchestrator.providers.base_provider import ProviderResponse

        inhalt = getattr(messages[-1], "content", "")
        self.anfragen.append(str(inhalt))
        # Der Schattenlauf fragt ohne Verlauf und ohne Systemtext: genau
        # eine Nachricht mit dem Wortlaut der Anfrage.
        if len(messages) == 1 and kw.get("preferred") in (None, ""):
            self.schattenanfragen += 1
            if self.verzoegerung:
                await asyncio.sleep(self.verzoegerung)
            if self.fehler:
                raise RuntimeError("das lokale Modell antwortet nicht")
            return ProviderResponse(
                text=self.schattenantwort, provider="schatten", model="s",
                latency_seconds=0.0,
            )
        return ProviderResponse(
            text="Eine gewoehnliche Antwort des Lehrers.",
            provider="test", model="test", latency_seconds=0.0,
        )


def _orchestrator(anbieter: _Anbieter):
    from backend.memory.memory_engine import MemoryEngine
    from backend.orchestrator.orchestrator import Orchestrator

    return Orchestrator(memory=MemoryEngine(), provider_manager=anbieter)


def _mit_schatten(orch, waechter: Schattenwaechter) -> None:
    """Hängt einen Wächter ein, wie ihn ``_schattenwaechter`` bauen würde."""

    orch._schatten = waechter
    orch._schatten_geprueft = True


async def _handle_und_warten(orch, text: str):
    """Fährt einen Zug und wartet DANACH auf die Schattenaufgaben.

    Das Warten steht bewusst hier und nicht im Programm: Der Benutzerzug
    wartet nie auf den Schatten. Der Test tut es, weil er sonst nichts zu
    prüfen hätte.
    """

    ergebnis = await orch.handle(text)
    waechter = orch._schatten
    if waechter is not None:
        for aufgabe in list(waechter._laufend):
            await asyncio.wait_for(asyncio.shield(aufgabe), timeout=5.0)
    return ergebnis


# --- Der Regelfall --------------------------------------------------------


def test_live_und_schatten_laufen_beide_und_sind_belegt():
    anbieter = _Anbieter()
    waechter = Schattenwaechter(provider_manager=anbieter, buch=_buch())
    orch = _orchestrator(anbieter)
    _mit_schatten(orch, waechter)

    ergebnis = asyncio.run(_handle_und_warten(orch, "Erzähl mir etwas über Bern."))

    # Der Benutzer bekommt die Antwort des Lehrers - unverändert.
    assert "Lehrers" in ergebnis.response
    # Und beides ist im Zähler belegt, nicht bloss behauptet.
    zaehler = waechter.zaehler()
    assert zaehler["gestartet"] == 1
    assert zaehler["fertig"] == 1
    assert zaehler["eingetragen"] == 1
    assert anbieter.schattenanfragen == 1
    # Der Status des Orchestrators zeigt den Schattenlauf.
    assert orch.status()["schattenlauf"]["eingetragen"] == 1


def test_der_schatten_veraendert_die_antwort_nicht():
    """Derselbe Zug mit und ohne Schatten muss dasselbe ergeben."""

    ohne = _orchestrator(_Anbieter())
    ohne_ergebnis = asyncio.run(ohne.handle("Erzähl mir etwas über Bern."))

    anbieter = _Anbieter(schattenantwort="Etwas ganz anderes, viel länger.")
    mit = _orchestrator(anbieter)
    _mit_schatten(mit, Schattenwaechter(provider_manager=anbieter, buch=_buch()))
    mit_ergebnis = asyncio.run(_handle_und_warten(mit, "Erzähl mir etwas über Bern."))

    assert mit_ergebnis.response == ohne_ergebnis.response


# --- Die Eindämmung -------------------------------------------------------


def test_ein_gescheiterter_schatten_beruehrt_die_antwort_nicht():
    anbieter = _Anbieter(fehler=True)
    waechter = Schattenwaechter(provider_manager=anbieter, buch=_buch())
    orch = _orchestrator(anbieter)
    _mit_schatten(orch, waechter)

    ergebnis = asyncio.run(_handle_und_warten(orch, "Erzähl mir etwas über Bern."))

    assert "Lehrers" in ergebnis.response
    assert waechter.zaehler()["gescheitert"] == 1
    assert waechter.zaehler()["eingetragen"] == 0


def test_ein_haengender_schatten_wird_abgebrochen():
    anbieter = _Anbieter(verzoegerung=5.0)
    waechter = Schattenwaechter(provider_manager=anbieter, buch=_buch())
    waechter._zeitgrenze = 0.05
    orch = _orchestrator(anbieter)
    _mit_schatten(orch, waechter)

    ergebnis = asyncio.run(_handle_und_warten(orch, "Erzähl mir etwas über Bern."))

    assert "Lehrers" in ergebnis.response
    assert waechter.zaehler()["abgelaufen"] == 1
    assert waechter.zaehler()["eingetragen"] == 0


def test_ein_kaputter_waechter_verhindert_keine_antwort():
    class _Kaputt:
        def starten(self, **kw):
            raise RuntimeError("Waechter defekt")

        def status(self):
            return {}

    anbieter = _Anbieter()
    orch = _orchestrator(anbieter)
    orch._schatten = _Kaputt()
    orch._schatten_geprueft = True

    ergebnis = asyncio.run(orch.handle("Erzähl mir etwas über Bern."))

    assert "Lehrers" in ergebnis.response


def test_die_stundengrenze_haelt_den_schatten_an():
    anbieter = _Anbieter()
    buch = _buch()
    buch._je_stunde = 1
    waechter = Schattenwaechter(provider_manager=anbieter, buch=buch)
    orch = _orchestrator(anbieter)
    _mit_schatten(orch, waechter)

    async def zwei_zuege():
        await _handle_und_warten(orch, "Erste Frage.")
        await _handle_und_warten(orch, "Zweite Frage.")

    asyncio.run(zwei_zuege())

    assert waechter.zaehler()["gestartet"] == 1
    assert waechter.zaehler()["abgelehnt"] == 1


# --- Die Vorgabe: aus ------------------------------------------------------


def test_ohne_freischaltung_entsteht_kein_waechter():
    """Die ausgelieferte Konfiguration hat den Schattenlauf aus."""

    orch = _orchestrator(_Anbieter())

    assert orch._schattenwaechter() is None
    # Und die Pruefung passiert genau einmal.
    assert orch._schatten_geprueft is True
    assert orch._schattenwaechter() is None


def test_ohne_freischaltung_laeuft_kein_schatten():
    anbieter = _Anbieter()
    orch = _orchestrator(anbieter)

    ergebnis = asyncio.run(orch.handle("Erzähl mir etwas über Bern."))

    assert "Lehrers" in ergebnis.response
    assert anbieter.schattenanfragen == 0
    assert "schattenlauf" not in orch.status()


# --- Die Datenregeln -------------------------------------------------------


@pytest.mark.parametrize(
    "anfrage",
    [
        "Schreib eine Mail an marc@example.com über die Wohnung",
        "Mein Passwort ist sk-ABCDEFGHIJKLMNOPQRST",
        "Wie geht es dir?",
    ],
)
def test_das_aufgabenmuster_enthaelt_kein_wort_der_anfrage(anfrage: str):
    """Der Wortlaut bleibt im Gespräch - das Muster beschreibt nur die Form."""

    muster = aufgabenmuster_bilden(anfrage)
    for wort in anfrage.split():
        assert wort.lower() not in muster.lower()
    assert "woerter" in muster and "zeichen" in muster


def test_die_lehre_traegt_keinen_wortlaut():
    anbieter = _Anbieter()
    buch = _buch()
    waechter = Schattenwaechter(provider_manager=anbieter, buch=buch)
    orch = _orchestrator(anbieter)
    _mit_schatten(orch, waechter)

    geheim = "Meine Adresse ist Bahnhofstrasse 1 in Zürich"
    asyncio.run(_handle_und_warten(orch, geheim))

    lehren = buch._store.get("lehren", [])
    assert len(lehren) == 1
    abgelegt = str(lehren[0])
    for wort in ("Bahnhofstrasse", "Zürich", "Adresse"):
        assert wort not in abgelegt
