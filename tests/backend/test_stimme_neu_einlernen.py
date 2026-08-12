"""Die Stimme lässt sich sauber neu einlernen.

Der Benutzer wollte die Stimme "sauber neu einlernen". Sauber heisst hier
dreierlei, und die Tests sichern alle drei:

* Ein "neu"-Befehl löscht das alte Profil zuerst und beginnt frisch - er
  darf nicht vom gewöhnlichen Lernbefehl gefangen werden.
* Jede Probe wird SOFORT geprüft; eine zu kurze oder zu leise wird nicht
  mitgezählt, sondern noch einmal erbeten.
* Nach einigen erfolglosen Versuchen gibt der Orb nach, statt endlos zu
  wiederholen.
"""

from __future__ import annotations

import asyncio
import wave
from pathlib import Path

import backend.utils.paths as paths
from backend.voice.speaker_id import Stimmerkennung
from backend.voice.voice_pipeline import VoicePipeline

from tests.backend.test_stimme_lernen import _stimme  # sprachähnliche Aufnahme


def _stille_wav(pfad: Path, sekunden: float = 1.5) -> Path:
    with wave.open(str(pfad), "wb") as datei:
        datei.setnchannels(1)
        datei.setsampwidth(2)
        datei.setframerate(16000)
        datei.writeframes(b"\x00\x00" * int(16000 * sekunden))
    return pfad


class _Harness:
    """Ein minimal aufgebautes Pipeline-Objekt, nur für die Stimme."""

    def __init__(self, tmp: Path):
        self.p = VoicePipeline.__new__(VoicePipeline)
        self.p._stimme = Stimmerkennung(profil_pfad=tmp / "stimme.json")
        self.p._stimme_anzahl = 3
        self.p._stimme_lernt = None
        self.p._stimme_rueckweisungen = 0
        self.gesagt: list[str] = []

        async def _say(text, **kw):
            self.gesagt.append(text)
            return True

        self.p._say = _say

        class _Bus:
            async def publish(self, *a, **k):
                return None

        self.p._event_bus = _Bus()


def test_neu_einlernen_vergisst_altes_profil_und_beginnt_frisch(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "get_data_dir", lambda: tmp_path)
    h = _Harness(tmp_path)

    # Erst ein Profil lernen.
    proben = [
        _stimme(tmp_path / "a.wav", [0.40, 0.09, 0.22, 0.06], saat=1),
        _stimme(tmp_path / "b.wav", [0.30, 0.12, 0.18, 0.08], saat=2),
        _stimme(tmp_path / "c.wav", [0.35, 0.10, 0.25, 0.07], saat=3),
    ]
    geklappt, _ = h.p._stimme.lernen(proben)
    assert geklappt and h.p._stimme.gelernt

    meldung = asyncio.run(h.p.stimme_neu_einlernen())

    assert not h.p._stimme.gelernt, "das alte Profil wurde nicht vergessen"
    assert h.p._stimme_lernt == [], "das frische Sammeln hat nicht begonnen"
    assert "von vorn" in meldung.lower()


def test_neu_befehl_wird_nicht_vom_lernbefehl_gefangen(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "get_data_dir", lambda: tmp_path)
    h = _Harness(tmp_path)

    gerufen: list[str] = []

    async def _neu():
        gerufen.append("neu")
        return "neu"

    async def _lernen():
        gerufen.append("lernen")
        return "lernen"

    h.p.stimme_neu_einlernen = _neu
    h.p.stimme_lernen_starten = _lernen

    for satz in ("lern meine stimme neu", "stimme neu einlernen", "stimme sauber neu"):
        gerufen.clear()
        behandelt = asyncio.run(h.p._stimme_befehl(satz))
        assert behandelt
        assert gerufen == ["neu"], f"{satz!r} landete bei {gerufen}"

    # Der gewöhnliche Befehl geht weiterhin ans gewöhnliche Lernen.
    gerufen.clear()
    asyncio.run(h.p._stimme_befehl("lerne meine stimme"))
    assert gerufen == ["lernen"]


def test_unbrauchbare_probe_wird_nicht_mitgezaehlt(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "get_data_dir", lambda: tmp_path)
    h = _Harness(tmp_path)
    h.p._stimme_lernt = []

    # Stille ergibt keinen Abdruck -> darf nicht zählen.
    stille = _stille_wav(tmp_path / "stille.wav")
    asyncio.run(h.p._stimme_sammeln(stille))

    assert h.p._stimme_lernt == [], "eine unbrauchbare Probe wurde mitgezählt"
    assert h.p._stimme_rueckweisungen == 1
    assert any("noch einmal" in s.lower() or "zu kurz" in s.lower() for s in h.gesagt)


def test_gute_probe_wird_gezaehlt(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "get_data_dir", lambda: tmp_path)
    h = _Harness(tmp_path)
    h.p._stimme_lernt = []

    gut = _stimme(tmp_path / "gut.wav", [0.40, 0.09, 0.22, 0.06], saat=1)
    asyncio.run(h.p._stimme_sammeln(gut))

    assert len(h.p._stimme_lernt) == 1
    assert h.p._stimme_rueckweisungen == 0


def test_nach_drei_fehlversuchen_wird_nachgegeben(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "get_data_dir", lambda: tmp_path)
    h = _Harness(tmp_path)
    h.p._stimme_lernt = []

    stille = _stille_wav(tmp_path / "s.wav")
    # Drei zu leise Proben nacheinander: die ersten beiden abgewiesen, die
    # dritte notgedrungen genommen, damit niemand endlos wiederholt.
    for _ in range(3):
        asyncio.run(h.p._stimme_sammeln(stille))

    assert len(h.p._stimme_lernt) == 1, "nach drei Versuchen wurde nicht nachgegeben"
