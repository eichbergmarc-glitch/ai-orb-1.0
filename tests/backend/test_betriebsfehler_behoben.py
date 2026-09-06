"""Tests für die direkt umgesetzten Behebungen der Betriebsfehler.

Jeder Fall hier stand als wiederkehrender Fehler in den Protokollen. Die
Tests halten die Behebungen fest - nicht als Sammlung von Kleinigkeiten,
sondern je Fehler genau der Punkt, an dem es vorher brach.
"""

from __future__ import annotations

import asyncio
import sys
import threading
import types

import pytest

from backend.system.task_manager import BackgroundTaskManager
from backend.tts.german_text import satzzeichen_sprechbar
from backend.tts.supertonic_engine import SupertonicEngine


# ================================================= Typografie und Supertonic
def test_typografische_zeichen_werden_einfach():
    """Supertonic brach an „ und › mitten im Satz ab."""

    assert satzzeichen_sprechbar("„Guten Morgen“ – sagte er … ›ja‹") == (
        '"Guten Morgen" - sagte er ... \'ja\''
    )


def test_umlaute_bleiben_unangetastet():
    assert satzzeichen_sprechbar("Größe, Fußweg, Übermut") == "Größe, Fußweg, Übermut"


def test_leerer_text_bleibt_leer():
    assert satzzeichen_sprechbar("") == ""


def test_supertonic_liest_unbekannte_zeichen_aus_der_meldung():
    fehler = ValueError("Found 2 unsupported character(s): ['„', '›']")
    assert SupertonicEngine._unbekannte_zeichen(fehler) == ["„", "›"]


def test_supertonic_verschleiert_andere_wertfehler_nicht():
    assert SupertonicEngine._unbekannte_zeichen(ValueError("ganz anderes")) == []


# ========================================================= Mikrofon-Anläufe
class _StreamAttrappe:
    """Ein Aufnahmestrom, der erst beim x-ten Anlauf gelingt."""

    fehlschlaege = 0
    geoeffnet_mit: list = []

    def __init__(self, *args, **kwargs):
        type(self).geoeffnet_mit.append(kwargs.get("device", "?"))
        if type(self).fehlschlaege > 0:
            type(self).fehlschlaege -= 1
            raise RuntimeError("Unanticipated host error [PaErrorCode -9999]")

    def start(self):
        pass

    def stop(self):
        pass

    def close(self):
        pass


@pytest.fixture()
def mikrofon(monkeypatch, tmp_path):
    """Eine AudioCapture mit Attrappen-Treiber und ohne Wartezeiten."""

    attrappe = types.ModuleType("sounddevice")
    attrappe.RawInputStream = _StreamAttrappe
    monkeypatch.setitem(sys.modules, "sounddevice", attrappe)

    import backend.audio.audio_capture as modul

    monkeypatch.setattr(modul.time, "sleep", lambda _s: None)
    _StreamAttrappe.fehlschlaege = 0
    _StreamAttrappe.geoeffnet_mit = []

    def bauen(geraet=None):
        capture = modul.AudioCapture(
            lambda *a, **k: None, device=geraet, output_directory=tmp_path
        )
        return capture

    return bauen


def test_mikrofon_gelingt_im_zweiten_anlauf(mikrofon):
    """Der 14-fache Betriebsfehler: einmal scheitern hiess vorher taub."""

    _StreamAttrappe.fehlschlaege = 1
    capture = mikrofon()
    assert capture.start() is True
    capture.stop()


def test_mikrofon_faellt_auf_das_standardgeraet_zurueck(mikrofon):
    """Ein eingestelltes Geraet, dessen Nummer ins Leere zeigt."""

    _StreamAttrappe.fehlschlaege = 2
    capture = mikrofon(geraet=7)
    assert capture.start() is True
    assert _StreamAttrappe.geoeffnet_mit == [7, 7, None]
    capture.stop()


def test_mikrofon_gibt_nach_allen_anlaeufen_auf(mikrofon):
    _StreamAttrappe.fehlschlaege = 99
    capture = mikrofon()
    assert capture.start() is False
    assert capture.is_running is False


# ==================================================== Task-Manager und Fäden
def test_task_manager_nennt_bei_fremdem_faden_den_richtigen_weg():
    """Vorher: kryptisches 'There is no current event loop in thread'."""

    manager = BackgroundTaskManager()

    async def _leer():
        pass

    async def _auf_der_loop():
        manager.create("probe", _leer())
        await asyncio.sleep(0)

    asyncio.run(_auf_der_loop())

    befund: dict = {}

    async def _lange():
        loop = asyncio.get_running_loop()

        def _fremder_faden():
            leer = _leer()
            try:
                manager.create("fremd", leer)
            except RuntimeError as fehler:
                befund["meldung"] = str(fehler)

        manager._loop = loop
        faden = threading.Thread(target=_fremder_faden)
        faden.start()
        await asyncio.to_thread(faden.join)

    asyncio.run(_lange())
    assert "run_coroutine_threadsafe" in befund.get("meldung", "")


# ==================================================== Kalender ohne Netz
def test_kalender_uebersetzt_anmeldefehler_in_kalenderfehler():
    """Vorher: alle drei Minuten eine volle Rückverfolgung im Protokoll."""

    from backend.integrations.gmail.oauth import GmailAuthError
    from backend.integrations.kalender.client import KalenderClient, KalenderFehler

    class _Konfig:
        is_configured = True

    class _Auth:
        config = _Konfig()
        is_authenticated = True

        @staticmethod
        def granted_scopes():
            return "https://www.googleapis.com/auth/calendar"

        @staticmethod
        def access_token():
            raise GmailAuthError("Token-Erneuerung fehlgeschlagen: getaddrinfo failed")

    client = KalenderClient(_Auth())
    with pytest.raises(KalenderFehler) as abgefangen:
        client.termine()
    assert "nicht erreichbar" in str(abgefangen.value)
