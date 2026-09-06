"""Regressionstests der Stufe 3: Start, Neustart, Wächter.

Drei Befunde, die zusammen einen stillen Totalausfall ergaben: Ein
Startschritt riss, der Rest des Hochfahrens fand nicht mehr statt, der
Faden lebte weiter und meldete „gesund". Bemerkte der Wächter doch etwas,
lief sein Neustart ins Leere - und danach wurde der Dienst nie wieder
angesehen.
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Any

from backend.launcher.supervisor import Service, ServiceState, Supervisor
from backend.runtime import Runtime


# --- 1. Ein gescheiterter Startschritt reisst nicht alles mit --------------


class _Kern(Runtime):
    """Nur die Startlogik, ohne den vollen Aufbau."""

    def __init__(self, *, reisst: str | None = None) -> None:
        # Bewusst kein super().__init__ - der volle Aufbau baut den halben Orb.
        self._boot_fertig = False
        self.startfehler: dict[str, str] = {}
        self._gelaufen: list[str] = []
        self._reisst = reisst
        self.event_bus = self._EventBus(self)
        self.providers = self._Teil(self, "Anbieter")
        self.agents = self._Teil(self, "Agenten")
        self.skills = self._Teil(self, "Fertigkeiten")
        self.plugins = self._Teil(self, "Erweiterungen")
        self.veroeffentlicht: list[dict[str, Any]] = []
        self.terminerinnerung = None
        self.hintergrund: list[str] = []
        self.background_tasks = type(
            "_B",
            (),
            {"create": lambda _s, name, coro: (coro.close(), self.hintergrund.append(name))},
        )()
        # Nichts einschalten, was der halbe Kern nicht bedienen kann.
        self.config = type("_C", (), {"get": staticmethod(lambda _k, standard=None: False)})()

    class _EventBus:
        def __init__(self, kern: "_Kern") -> None:
            self._kern = kern

        async def publish(self, name: str, payload: dict[str, Any]) -> None:
            self._kern.veroeffentlicht.append(payload)

    class _Teil:
        def __init__(self, kern: "_Kern", name: str) -> None:
            self._kern = kern
            self._name = name
            self.active_name = "test"
            self.registry = type("_R", (), {"names": staticmethod(lambda: [])})()

        async def _tun(self) -> None:
            if self._kern._reisst == self._name:
                raise RuntimeError(f"{self._name} kaputt")
            self._kern._gelaufen.append(self._name)

        start = test_all = load_active = load_enabled = _tun

    def names(self) -> list[str]:  # für die SYSTEM_READY-Nutzlast
        return []


def _kern(reisst: str | None = None) -> _Kern:
    kern = _Kern(reisst=reisst)
    kern.tools = type("_T", (), {"names": staticmethod(lambda: [])})()
    return kern


def test_ohne_fehler_laeuft_alles_durch() -> None:
    kern = _kern()

    asyncio.run(kern._boot())

    assert kern._gelaufen == ["Anbieter", "Agenten", "Fertigkeiten", "Erweiterungen"]
    assert kern.startfehler == {}
    assert kern._boot_fertig is True


def test_ein_gescheiterter_schritt_stoppt_den_start_nicht() -> None:
    """Der Kern der Sache: Nach dem Riss geht es weiter."""

    kern = _kern(reisst="Agenten")

    asyncio.run(kern._boot())

    assert kern._gelaufen == ["Anbieter", "Fertigkeiten", "Erweiterungen"]
    assert "Agenten" in kern.startfehler
    assert kern._boot_fertig is True, "SYSTEM_READY muss trotzdem kommen"
    assert kern.veroeffentlicht[-1]["startfehler"] == kern.startfehler


def test_der_fehler_steht_in_der_bereitmeldung() -> None:
    """Ehrlich statt beruhigend - wer nachsieht, erfährt es."""

    kern = _kern(reisst="Erweiterungen")

    asyncio.run(kern._boot())

    nutzlast = kern.veroeffentlicht[-1]
    assert "Erweiterungen" in nutzlast["startfehler"]


# --- 2. Ein halb hochgefahrener Kern gilt nicht als gesund -----------------


class _Halbstart(Runtime):
    def __init__(self, *, fertig: bool, alter: float) -> None:
        self._boot_fertig = fertig
        self._started_at = time.time() - alter
        self.config = type("_C", (), {"get": staticmethod(lambda *_a: 300)})()

    def is_running(self) -> bool:
        return True


def test_ein_frischer_start_bekommt_seine_schonfrist() -> None:
    """Sonst schoesse der Waechter jeden normalen Start ab."""

    assert _Halbstart(fertig=False, alter=5.0).kern_gesund() is True


def test_ein_start_der_nie_endet_ist_ein_ausfall() -> None:
    assert _Halbstart(fertig=False, alter=600.0).kern_gesund() is False


def test_ein_fertiger_kern_bleibt_gesund() -> None:
    assert _Halbstart(fertig=True, alter=99999.0).kern_gesund() is True


# --- 3. Nach dem Beenden startet der Kern wieder ---------------------------


def test_beenden_raeumt_faden_und_schleife_weg() -> None:
    """Ohne dieses Aufräumen ist der Neustart des Wächters eine Attrappe.

    ``start()`` kehrt sofort zurück, solange ``_thread`` gesetzt ist, und
    ``get_runtime()`` gibt dieselbe Instanz zurück. Der Wächter rief also
    stop(), rief start(), bekam ein wortloses Nichts - und gab nach drei
    Versuchen auf.
    """

    kern = Runtime.__new__(Runtime)
    kern._ready = threading.Event()
    kern._ready.set()
    kern._boot_fertig = True
    schleife = asyncio.new_event_loop()
    try:
        kern._loop = schleife
        kern._thread = None
        kern.run = lambda coro, timeout=15.0: coro.close()  # type: ignore[assignment]
        kern.voice = type("_V", (), {"stop": staticmethod(lambda: None)})()

        kern.stop()

        assert kern._loop is None, "die Schleife blieb stehen"
        assert kern._thread is None, "der Faden blieb stehen"
        assert kern._ready.is_set() is False
        assert kern._boot_fertig is False
    finally:
        schleife.close()


# --- 4. Ein misslungener Neustart bleibt nicht liegen ---------------------


def _waechter(lebt: list[bool], starts: list[bool]) -> tuple[Supervisor, Service]:
    waechter = Supervisor(check_interval=1.0)
    dienst = Service(
        name="Kern",
        start=lambda: starts.pop(0) if starts else False,
        is_alive=lambda: lebt[0],
        required=True,
        max_restarts=2,
    )
    waechter.register(dienst)
    dienst.state = ServiceState.RUNNING
    dienst.last_started = time.time()
    return waechter, dienst


def test_nach_misslungenem_neustart_wird_weiter_versucht() -> None:
    """Vorher blieb der Dienst in RECOVERING liegen - für immer."""

    lebt = [False]
    waechter, dienst = _waechter(lebt, starts=[False, False, False])

    waechter.check_once()
    assert dienst.state is ServiceState.RECOVERING
    assert dienst.restarts == 1

    # Genau hier hörte die Überwachung bisher auf.
    waechter.check_once()
    assert dienst.restarts == 2

    waechter.check_once()
    assert dienst.state is ServiceState.FAILED, "der Ausfall muss benannt werden"


def test_ein_spaeter_gelungener_neustart_wird_bemerkt() -> None:
    lebt = [False]

    def _startet() -> bool:
        lebt[0] = True
        return True

    waechter = Supervisor(check_interval=1.0)
    dienst = Service(
        name="Kern", start=_startet, is_alive=lambda: lebt[0], required=True, max_restarts=3
    )
    waechter.register(dienst)
    dienst.state = ServiceState.RECOVERING
    dienst.restarts = 1

    waechter.check_once()

    assert dienst.state is ServiceState.RUNNING
