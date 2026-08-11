"""Tests des Merkens und der Zustandsklaenge.

Der Orb beobachtete schon immer, wie er benutzt wird, und das
Langzeitgedaechtnis kennt "Vorliebe" und "Gewohnheit" seit Anfang an. Was
fehlte, war beides: Er konnte nichts ausdruecklich hinterlegen, wenn jemand
es ihm sagte - und das Gemerkte kam beim Denken nie an.

Der wichtigste Test hier ist deshalb nicht, dass etwas gespeichert wird,
sondern dass es im Kontext ankommt, mit dem gedacht wird. Gelernt zu haben
und nichts damit zu tun sieht von aussen wie Gleichgueltigkeit aus.
"""

from __future__ import annotations

import asyncio
import wave
from pathlib import Path

from backend.audio.sounds import Klaenge
from backend.tools.memory_tools import (
    ForgetPreferenceTool,
    RememberPreferenceTool,
    ShowPreferencesTool,
)


def _fuehre_aus(werkzeug, **argumente):
    return asyncio.run(werkzeug.execute(argumente))


class _Eintrag:
    def __init__(self, kennung: str, inhalt: str):
        self.id = kennung
        self.content = inhalt


class _Langzeit:
    """Ein Langzeitgedaechtnis, das nur im Arbeitsspeicher lebt."""

    def __init__(self):
        self.eintraege: dict[str, list[_Eintrag]] = {}
        self._zaehler = 0

    def store(self, kategorie, inhalt, *, project_id=None, source=None, certainty="fakt"):
        self._zaehler += 1
        eintrag = _Eintrag(f"e{self._zaehler}", inhalt)
        self.eintraege.setdefault(kategorie, []).append(eintrag)
        return eintrag

    def by_category(self, kategorie, project_id=None):
        return list(self.eintraege.get(kategorie, []))

    def delete(self, kennung):
        for liste in self.eintraege.values():
            for eintrag in list(liste):
                if eintrag.id == kennung:
                    liste.remove(eintrag)
                    return True
        return False


# --- Merken -------------------------------------------------------------------


def test_eine_vorliebe_wird_gemerkt():
    langzeit = _Langzeit()
    ergebnis = _fuehre_aus(
        RememberPreferenceTool(langzeit), art="vorliebe", inhalt="Mag knappe Antworten"
    )

    assert ergebnis.ok, ergebnis.error
    assert langzeit.by_category("vorliebe")[0].content == "Mag knappe Antworten"


def test_gewohnheit_und_vorliebe_bleiben_getrennt():
    """Was jemand moechte, ist etwas anderes als was jemand tut."""

    langzeit = _Langzeit()
    _fuehre_aus(RememberPreferenceTool(langzeit), art="vorliebe", inhalt="Mag Schweizer Quellen")
    _fuehre_aus(
        RememberPreferenceTool(langzeit), art="gewohnheit", inhalt="Recherchiert meist abends"
    )

    assert len(langzeit.by_category("vorliebe")) == 1
    assert len(langzeit.by_category("gewohnheit")) == 1


def test_unbekannte_art_wird_abgewiesen():
    ergebnis = _fuehre_aus(
        RememberPreferenceTool(_Langzeit()), art="laune", inhalt="irgendwas"
    )
    assert not ergebnis.ok
    assert "vorliebe" in ergebnis.error


def test_zu_wenig_gesagt_wird_nicht_gemerkt():
    ergebnis = _fuehre_aus(RememberPreferenceTool(_Langzeit()), art="vorliebe", inhalt="ja")
    assert not ergebnis.ok


def test_gemerktes_wird_aufgezaehlt():
    langzeit = _Langzeit()
    langzeit.store("vorliebe", "Mag knappe Antworten")
    langzeit.store("gewohnheit", "Arbeitet frueh am Morgen")

    ergebnis = _fuehre_aus(ShowPreferencesTool(langzeit))

    assert ergebnis.ok
    assert "knappe Antworten" in ergebnis.output
    assert "frueh am Morgen" in ergebnis.output


def test_ohne_gemerktes_kommt_eine_einladung():
    ergebnis = _fuehre_aus(ShowPreferencesTool(_Langzeit()))
    assert ergebnis.ok
    assert "nichts über dich gemerkt" in ergebnis.output


def test_vergessen_trifft_den_richtigen():
    langzeit = _Langzeit()
    langzeit.store("vorliebe", "Mag knappe Antworten")
    langzeit.store("gewohnheit", "Arbeitet frueh am Morgen")

    ergebnis = _fuehre_aus(ForgetPreferenceTool(langzeit), stichwort="morgen")

    assert ergebnis.ok, ergebnis.error
    assert langzeit.by_category("gewohnheit") == []
    assert len(langzeit.by_category("vorliebe")) == 1


def test_bei_mehreren_treffern_wird_nachgefragt():
    """Gemerktes ist mit der Zeit entstanden und laesst sich nicht zurueckholen."""

    langzeit = _Langzeit()
    langzeit.store("vorliebe", "Mag kurze Antworten")
    langzeit.store("vorliebe", "Mag kurze Wege")

    ergebnis = _fuehre_aus(ForgetPreferenceTool(langzeit), stichwort="kurze")

    assert not ergebnis.ok
    assert "mehrere" in ergebnis.error
    assert len(langzeit.by_category("vorliebe")) == 2, "es wurde doch geloescht"


# --- Und der eigentliche Punkt: Es muss beim Denken ankommen -------------------


class _Vorlieben:
    def __init__(self, text: str = ""):
        self._text = text

    def guidance(self) -> str:
        return self._text


def test_gemerktes_geht_in_den_denkkontext_ein():
    """Der wichtigste Test: Gelerntes muss wirken, nicht bloss existieren."""

    from backend.cognitive.cognitive_core import CognitiveCore

    kern = CognitiveCore.__new__(CognitiveCore)
    langzeit = _Langzeit()
    langzeit.store("vorliebe", "Mag knappe Antworten")
    langzeit.store("gewohnheit", "Arbeitet frueh am Morgen")
    kern.long_term_memory = langzeit

    text = kern._gemerktes()

    assert "Mag knappe Antworten" in text
    assert "Arbeitet frueh am Morgen" in text
    assert "Richte dich danach" in text


def test_ohne_gemerktes_bleibt_der_kontext_leer():
    """Ein Systemprompt soll nicht mit Leerformeln aufgeblaeht werden."""

    from backend.cognitive.cognitive_core import CognitiveCore

    kern = CognitiveCore.__new__(CognitiveCore)
    kern.long_term_memory = _Langzeit()

    assert kern._gemerktes() == ""


def test_ein_kaputtes_gedaechtnis_blockiert_den_weg_nicht():
    from backend.cognitive.cognitive_core import CognitiveCore

    class _Kaputt:
        def by_category(self, kategorie, project_id=None):
            raise RuntimeError("Platte weg")

    kern = CognitiveCore.__new__(CognitiveCore)
    kern.long_term_memory = _Kaputt()

    assert kern._gemerktes() == ""


# --- Die Zustandsklaenge -------------------------------------------------------


def _klang(pfad: Path) -> Path:
    with wave.open(str(pfad), "wb") as datei:
        datei.setnchannels(1)
        datei.setsampwidth(2)
        datei.setframerate(16000)
        datei.writeframes(b"\x00\x00" * 1600)
    return pfad


def test_klaenge_werden_gefunden(tmp_path: Path, monkeypatch):
    import backend.audio.sounds as klangmodul

    (tmp_path / "audio").mkdir()
    _klang(tmp_path / "audio" / "denken.wav")
    monkeypatch.setattr(klangmodul, "get_project_root", lambda: tmp_path)
    monkeypatch.setattr(klangmodul, "get_data_dir", lambda: tmp_path / "daten")

    klaenge = Klaenge(denk_klang="audio/denken.wav")

    assert klaenge.denk_klang is not None
    assert klaenge.denk_klang.name == "denken.wav"


def test_eigene_datei_sticht_die_mitgelieferte(tmp_path: Path, monkeypatch):
    """Wer eine eigene Datei hinterlegt, will sie hoeren."""

    import backend.audio.sounds as klangmodul

    (tmp_path / "audio").mkdir()
    (tmp_path / "daten" / "audio").mkdir(parents=True)
    _klang(tmp_path / "audio" / "denken.wav")
    _klang(tmp_path / "daten" / "audio" / "denken.wav")
    monkeypatch.setattr(klangmodul, "get_project_root", lambda: tmp_path)
    monkeypatch.setattr(klangmodul, "get_data_dir", lambda: tmp_path / "daten")

    klaenge = Klaenge(denk_klang="audio/denken.wav")

    assert klaenge.denk_klang is not None
    assert "daten" in str(klaenge.denk_klang)


def test_fehlende_datei_bleibt_folgenlos(tmp_path: Path, monkeypatch):
    """Ein Assistent, der wegen eines Signaltons nicht antwortet, waere absurd."""

    import backend.audio.sounds as klangmodul

    monkeypatch.setattr(klangmodul, "get_project_root", lambda: tmp_path)
    monkeypatch.setattr(klangmodul, "get_data_dir", lambda: tmp_path)

    klaenge = Klaenge(denk_klang="gibtsnicht.wav", hoer_klang="auchnicht.wav")

    assert klaenge.denk_klang is None
    klaenge.denken()  # darf nicht werfen
    klaenge.zuhoeren()


def test_abgeschaltet_bleibt_still(tmp_path: Path, monkeypatch):
    import backend.audio.sounds as klangmodul

    (tmp_path / "audio").mkdir()
    _klang(tmp_path / "audio" / "denken.wav")
    monkeypatch.setattr(klangmodul, "get_project_root", lambda: tmp_path)
    monkeypatch.setattr(klangmodul, "get_data_dir", lambda: tmp_path)

    gespielt: list[Path] = []
    klaenge = Klaenge(denk_klang="audio/denken.wav", aktiv=False)
    monkeypatch.setattr(klaenge, "_abspielen", lambda pfad: gespielt.append(pfad))

    klaenge.denken()
    assert gespielt == []


# --- Wann die Klaenge kommen ---------------------------------------------------


class _Klangzaehler:
    def __init__(self):
        self.gedacht = 0
        self.gehoert = 0

    def denken(self):
        self.gedacht += 1

    def zuhoeren(self):
        self.gehoert += 1


class _Zustand:
    """Nur der Zustandswechsel der Sprachschicht, ohne Geraete."""

    def __init__(self):
        from backend.voice.voice_pipeline import VoicePipeline, VoiceState

        self.pipeline = VoicePipeline.__new__(VoicePipeline)
        self.pipeline._state = VoiceState.SLEEPING
        self.pipeline._klaenge = _Klangzaehler()
        self.pipeline._publish_state = self._nichts
        self.State = VoiceState

    async def _nichts(self):
        return None

    def wechsel(self, state):
        asyncio.run(self.pipeline._set_state(state))


def test_der_denk_klang_kommt_beim_nachdenken():
    z = _Zustand()
    z.wechsel(z.State.THINKING)
    assert z.pipeline._klaenge.gedacht == 1


def test_der_denk_klang_kommt_nur_einmal():
    """Der Zustand wird waehrend einer Anweisung mehrfach gesetzt."""

    z = _Zustand()
    z.wechsel(z.State.THINKING)
    z.wechsel(z.State.THINKING)
    assert z.pipeline._klaenge.gedacht == 1


def test_der_hoer_klang_kommt_beim_aufwachen():
    z = _Zustand()
    z.wechsel(z.State.LISTENING)
    assert z.pipeline._klaenge.gehoert == 1


def test_nach_der_antwort_kommt_kein_hoer_klang():
    """Das ist kein Anfang, sondern das Ende der Antwort.

    Sonst ertoente er nach jedem einzelnen Satz.
    """

    z = _Zustand()
    z.wechsel(z.State.LISTENING)
    z.wechsel(z.State.THINKING)
    z.wechsel(z.State.SPEAKING)
    z.wechsel(z.State.LISTENING)

    assert z.pipeline._klaenge.gehoert == 1, "der Hoer-Klang kam ein zweites Mal"
