"""Die Netzsperre - und der Test, der sie beim Nichtstun ertappt.

Der wichtigste Test ist ``test_ein_gewoehnlicher_netzfehler_gilt_nicht_als_beweis``:
Ohne ihn würde eine Abnahme auf einem Rechner ohne Anschluss als bestanden
gelten, obwohl die Sperre gar nichts getan hat. Genau dieser Irrtum ist die
Art von "Erfolg", die der Auftrag ausschliesst.
"""

from __future__ import annotations

import socket
from typing import Any

import pytest

from backend.lernen import netzsperre
from backend.lernen.netzsperre import NetzGesperrt


@pytest.fixture(autouse=True)
def _sperrzustand_wiederherstellen():
    """Jeder Test gibt den Sperrzustand zurück, den er vorgefunden hat.

    Nicht einfach ``entsperren()``: Diese Datei läuft auch INNERHALB der
    Offlineabnahme, und dort ist die Sperre vorher an. Ein Test, der sie
    danach abschaltet, würde die Abnahme entwerten - und das würde von
    ``scripts/offline_abnahme.py`` zu Recht als Fehlschlag gemeldet.
    Genau das ist beim ersten Lauf passiert.
    """

    vorher = netzsperre.ist_aktiv()
    rueckschleife = netzsperre._loopback_erlaubt
    yield
    netzsperre.entsperren()
    if vorher:
        netzsperre.sperren(loopback_erlaubt=rueckschleife)


# --- Die Sperre greift ----------------------------------------------------


def test_ohne_sperre_ist_nichts_ersetzt():
    netzsperre.entsperren()

    assert netzsperre.ist_aktiv() is False
    # Der Beweis kann hier nicht "gesperrt" sagen - egal, ob der Rechner
    # Netz hat oder nicht.
    assert netzsperre.beweis()["gesperrt"] is False


def test_mit_sperre_scheitert_jede_verbindung_nach_draussen():
    netzsperre.sperren()

    with pytest.raises(NetzGesperrt):
        socket.create_connection(("1.1.1.1", 443), timeout=1.0)
    with pytest.raises(NetzGesperrt):
        socket.socket().connect(("93.184.216.34", 80))


def test_mit_sperre_scheitert_der_namensdienst():
    netzsperre.sperren()

    with pytest.raises(NetzGesperrt):
        socket.getaddrinfo("example.com", 443)
    with pytest.raises(NetzGesperrt):
        socket.gethostbyname("example.com")


def test_die_rueckschleife_bleibt_offen():
    """Sonst liefe kein lokales Modell - und genau das soll offline laufen."""

    netzsperre.sperren()

    # Kein Verbindungsversuch, sondern die Entscheidung der Sperre: Die
    # Rueckschleife wird durchgelassen (ob dort jemand horcht, ist eine
    # andere Frage und nicht die der Sperre).
    with pytest.raises(OSError) as ausnahme:
        socket.create_connection(("127.0.0.1", 9), timeout=0.5)
    assert not isinstance(ausnahme.value, NetzGesperrt)

    assert socket.getaddrinfo("127.0.0.1", 80)


def test_auch_die_rueckschleife_laesst_sich_sperren():
    netzsperre.sperren(loopback_erlaubt=False)

    with pytest.raises(NetzGesperrt):
        socket.create_connection(("127.0.0.1", 9), timeout=0.5)


def test_entsperren_stellt_die_originale_wieder_her():
    # Erst den Ausgangszustand herstellen: Innerhalb der Offlineabnahme
    # ist die Sperre beim Eintritt bereits aktiv.
    netzsperre.entsperren()
    original = socket.getaddrinfo
    netzsperre.sperren()
    assert socket.getaddrinfo is not original
    netzsperre.entsperren()
    assert socket.getaddrinfo is original
    assert netzsperre.ist_aktiv() is False


def test_mehrfaches_sperren_schadet_nicht():
    netzsperre.sperren()
    ersetzt = socket.getaddrinfo
    netzsperre.sperren()
    assert socket.getaddrinfo is ersetzt
    netzsperre.entsperren()
    netzsperre.entsperren()


# --- Der Beweis ist strenger als der Erfolg -------------------------------


def test_der_beweis_erkennt_die_aktive_sperre():
    netzsperre.sperren()

    verbindung = netzsperre.beweis()
    namen = netzsperre.namensbeweis()

    assert verbindung["gesperrt"] is True
    assert verbindung["art"] == "NetzGesperrt"
    assert namen["gesperrt"] is True


def test_ein_gewoehnlicher_netzfehler_gilt_nicht_als_beweis(monkeypatch):
    """Ein Rechner ohne Anschluss darf keine bestandene Abnahme ergeben."""

    def _kein_netz(*_a, **_kw):
        raise OSError(101, "Network is unreachable")

    monkeypatch.setattr(socket, "create_connection", _kein_netz)
    monkeypatch.setattr(socket, "getaddrinfo", _kein_netz)

    verbindung = netzsperre.beweis()
    namen = netzsperre.namensbeweis()

    assert verbindung["gesperrt"] is False
    assert "kein Beweis" in verbindung["fehler"]
    assert namen["gesperrt"] is False


def test_eine_gelungene_verbindung_gilt_erst_recht_nicht(monkeypatch):
    class _Verbindung:
        def close(self) -> None:
            pass

    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: _Verbindung())

    verbindung = netzsperre.beweis()

    assert verbindung["gesperrt"] is False
    assert "NICHT aktiv" in verbindung["fehler"]


# --- Die Abnahme selbst ---------------------------------------------------


def test_ohne_nachweisbare_sperre_laufen_gar_keine_tests(monkeypatch):
    """Der entscheidende Riegel: kein Testlauf, dessen Ergebnis nichts belegt."""

    from scripts import offline_abnahme

    monkeypatch.setattr(
        offline_abnahme.netzsperre,
        "beweis",
        lambda **_kw: {"gesperrt": False, "art": "OSError", "fehler": "kein Beweis", "ziel": "x"},
    )
    gelaufen: list[Any] = []
    monkeypatch.setattr(
        "pytest.main", lambda *a, **k: gelaufen.append(a) or 0
    )

    bericht = offline_abnahme.abnahme(["tests/backend/test_netzsperre.py"])

    assert bericht["bestanden"] is False
    assert bericht["pytest_rueckgabe"] is None
    assert gelaufen == []
    assert "KEINE" in bericht["grund"]


def test_eine_nach_dem_lauf_aufgehobene_sperre_faellt_auf(monkeypatch):
    from scripts import offline_abnahme

    zustaende = iter([True, True, False, False])

    def _beweis(**_kw):
        gesperrt = next(zustaende)
        return {"gesperrt": gesperrt, "art": "x", "fehler": "", "ziel": "x"}

    monkeypatch.setattr(offline_abnahme.netzsperre, "beweis", _beweis)
    monkeypatch.setattr(offline_abnahme.netzsperre, "namensbeweis", _beweis)
    monkeypatch.setattr("pytest.main", lambda *a, **k: 0)

    bericht = offline_abnahme.abnahme(["tests/backend/test_netzsperre.py"])

    assert bericht["bestanden"] is False
    assert "nicht mehr aktiv" in bericht["grund"]


def test_rote_tests_ergeben_keine_bestandene_abnahme(monkeypatch):
    from scripts import offline_abnahme

    monkeypatch.setattr(
        offline_abnahme.netzsperre,
        "beweis",
        lambda **_kw: {"gesperrt": True, "art": "NetzGesperrt", "fehler": "", "ziel": "x"},
    )
    monkeypatch.setattr(
        offline_abnahme.netzsperre,
        "namensbeweis",
        lambda **_kw: {"gesperrt": True, "art": "NetzGesperrt", "fehler": "", "ziel": "x"},
    )
    monkeypatch.setattr("pytest.main", lambda *a, **k: 1)

    bericht = offline_abnahme.abnahme(["tests/backend/test_netzsperre.py"])

    assert bericht["bestanden"] is False
    assert "pytest endete mit 1" in bericht["grund"]
