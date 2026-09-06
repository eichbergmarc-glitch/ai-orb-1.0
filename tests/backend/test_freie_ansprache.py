"""Freie Ansprache und Gaststimmen - auf wen der Orb ohne Weckwort hoert.

Der Benutzer hat es so bestellt: "wenn ich mit dem orb in einem gespraech
bin will ich nicht jedes mal 'hallo Orb' sagen muessen [...] er sollte
mich ja immer erkennen weil er ja meine stimme kennt" - und weiter: der
Orb soll auf Zuruf AUCH auf eine andere Stimme hoeren, "jedoch nur
solange bis ich ihm sage, 'hoer nur auf mich'".

Drei Dinge sichern diese Tests:

* Die Gaststimme steht NEBEN der Benutzerstimme, nie an ihrer Stelle -
  der Benutzer bleibt immer erkannt, und nur er verwaltet die Stimmen.
* Der Widerruf wirkt: Nach "hoer nur auf mich" ist die Gaststimme wieder
  eine fremde Stimme.
* Die freie Ansprache haengt an der GEPRUEFTEN Erkennung. Ohne
  hinterlegte Stimme weckt nichts ausser dem Weckwort - sonst hoerte der
  Orb wieder auf jeden, und genau davor schuetzt die Stimmpruefung.

Was hier nicht geprueft werden kann: das Zusammenspiel mit Mikrofon und
Lautsprecher. Das prueft der Pruefstand auf dem Rechner des Benutzers.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import backend.utils.paths as paths
from backend.voice.speaker_id import Stimmerkennung, Urteil
from backend.voice.voice_pipeline import VoicePipeline

# Die kuenstlichen Sprecher aus den Stimmerkennungs-Tests: zwei
# Vokaltrakte, verschieden in den Formanten wie zwei Menschen.
from tests.backend.test_stimmerkennung import SPRECHER_A, SPRECHER_B, _stimme


def _erkennung(tmp_path: Path) -> Stimmerkennung:
    return Stimmerkennung(profil_pfad=tmp_path / "profil.json")


def _benutzer_lernen(erkennung: Stimmerkennung, tmp_path: Path) -> None:
    proben = [
        _stimme(tmp_path / f"ich{i}.wav", SPRECHER_A, grundton=118.0 + i * 3, versatz=i)
        for i in range(3)
    ]
    geklappt, meldung = erkennung.lernen(proben)
    assert geklappt, meldung


def _gastproben(tmp_path: Path) -> list[Path]:
    return [
        _stimme(
            tmp_path / f"gast{i}.wav", SPRECHER_B, grundton=200.0 + i * 4, versatz=40 + i
        )
        for i in range(3)
    ]


# --- Die Gaststimme in der Erkennung ---------------------------------------------


def test_gast_braucht_zuerst_den_benutzer(tmp_path: Path):
    """Ohne Hausherr kein Gast - sonst liesse sich nichts auseinanderhalten."""

    erkennung = _erkennung(tmp_path)
    geklappt, meldung = erkennung.gast_lernen(_gastproben(tmp_path))

    assert geklappt is False
    assert "lerne" in meldung.lower()
    assert erkennung.gaeste == 0


def test_gaststimme_wird_zugelassen_und_unterschieden(tmp_path: Path):
    """Der Kern: Benutzer bleibt Benutzer, Gast wird Gast, Dritte bleiben draussen."""

    erkennung = _erkennung(tmp_path)
    _benutzer_lernen(erkennung, tmp_path)
    geklappt, meldung = erkennung.gast_lernen(_gastproben(tmp_path))
    assert geklappt, meldung
    assert "hör nur auf mich" in meldung

    ich = erkennung.pruefen(
        _stimme(tmp_path / "ich-spaeter.wav", SPRECHER_A, grundton=124.0, versatz=77)
    )
    assert ich.akzeptiert and ich.wer == "benutzer"

    gast = erkennung.pruefen(
        _stimme(tmp_path / "gast-spaeter.wav", SPRECHER_B, grundton=208.0, versatz=91)
    )
    assert gast.akzeptiert, (
        f"die zugelassene Gaststimme wurde abgewiesen "
        f"({gast.aehnlichkeit:.2f} gegen {gast.schwelle:.2f})"
    )
    assert gast.wer == "gast"

    # Ein Dritter - andere Formanten als beide - bleibt draussen.
    dritter_formant = [(550.0, 70.0, 1.0), (1650.0, 95.0, 0.55), (2800.0, 130.0, 0.3)]
    dritter = erkennung.pruefen(
        _stimme(tmp_path / "dritter.wav", dritter_formant, grundton=160.0, versatz=13)
    )
    assert dritter.akzeptiert is False, "ein Dritter kam als Gast durch"


def test_hoer_nur_auf_mich_widerruft_die_gaeste(tmp_path: Path):
    erkennung = _erkennung(tmp_path)
    _benutzer_lernen(erkennung, tmp_path)
    erkennung.gast_lernen(_gastproben(tmp_path))
    assert erkennung.gaeste == 1

    meldung = erkennung.gaeste_vergessen()

    assert "nur noch auf dich" in meldung
    assert erkennung.gaeste == 0
    wieder = erkennung.pruefen(
        _stimme(tmp_path / "gast-danach.wav", SPRECHER_B, grundton=208.0, versatz=91)
    )
    assert wieder.akzeptiert is False, "die widerrufene Gaststimme kam noch durch"
    # Der Benutzer selbst bleibt selbstverstaendlich erkannt.
    ich = erkennung.pruefen(
        _stimme(tmp_path / "ich-danach.wav", SPRECHER_A, grundton=121.0, versatz=55)
    )
    assert ich.akzeptiert and ich.wer == "benutzer"


def test_widerruf_ohne_gaeste_ist_eine_auskunft(tmp_path: Path):
    erkennung = _erkennung(tmp_path)
    _benutzer_lernen(erkennung, tmp_path)

    meldung = erkennung.gaeste_vergessen()

    assert "keine gaststimme" in meldung.lower()


def test_gaeste_ueberleben_den_neustart(tmp_path: Path):
    """Der Benutzer widerruft - nicht der Neustart."""

    erste = _erkennung(tmp_path)
    _benutzer_lernen(erste, tmp_path)
    erste.gast_lernen(_gastproben(tmp_path))

    zweite = _erkennung(tmp_path)
    assert zweite.gaeste == 1
    gast = zweite.pruefen(
        _stimme(tmp_path / "gast-neustart.wav", SPRECHER_B, grundton=205.0, versatz=71)
    )
    assert gast.akzeptiert and gast.wer == "gast"


def test_vergessen_der_eigenen_stimme_nimmt_die_gaeste_mit(tmp_path: Path):
    """Sonst wachte ein zurueckgelassener Gast beim naechsten Einlernen
    als stiller Mithoerer wieder auf."""

    erkennung = _erkennung(tmp_path)
    _benutzer_lernen(erkennung, tmp_path)
    erkennung.gast_lernen(_gastproben(tmp_path))

    erkennung.vergessen()

    assert erkennung.gaeste == 0
    wieder = _erkennung(tmp_path)
    assert wieder.gaeste == 0


def test_altes_profil_ohne_gaeste_schluessel_laedt(tmp_path: Path):
    """Bestandsdateien kennen 'gaeste' nicht - das ist kein Fehler."""

    erste = _erkennung(tmp_path)
    _benutzer_lernen(erste, tmp_path)
    daten = json.loads((tmp_path / "profil.json").read_text(encoding="utf-8"))
    daten.pop("gaeste", None)
    (tmp_path / "profil.json").write_text(
        json.dumps(daten, ensure_ascii=False), encoding="utf-8"
    )

    zweite = _erkennung(tmp_path)
    assert zweite.gelernt is True
    assert zweite.gaeste == 0
    assert zweite.status()["gaeste"] == 0


def test_der_gast_zieht_den_sprechrhythmus_nicht_um(tmp_path: Path):
    """Das Urteil traegt, WER erkannt wurde - daran haengt in der Pipeline,
    dass nur der Benutzer den Sprechrhythmus des Orbs praegt."""

    erkennung = _erkennung(tmp_path)
    _benutzer_lernen(erkennung, tmp_path)
    erkennung.gast_lernen(_gastproben(tmp_path))

    gast = erkennung.pruefen(
        _stimme(tmp_path / "gast-rhythmus.wav", SPRECHER_B, grundton=207.0, versatz=81)
    )
    assert gast.wer == "gast"
    assert gast.to_dict()["wer"] == "gast"

    quelle = Path("backend/voice/voice_pipeline.py").read_text(encoding="utf-8")
    assert 'urteil.wer != "gast"' in quelle, (
        "die Pipeline schuetzt den Sprechrhythmus nicht mehr vor Gaesten"
    )


# --- Die Befehle in der Pipeline ---------------------------------------------------


class _Harness:
    """Ein minimal aufgebautes Pipeline-Objekt, nur fuer die Stimme."""

    def __init__(self, tmp: Path):
        self.p = VoicePipeline.__new__(VoicePipeline)
        self.p._stimme = Stimmerkennung(profil_pfad=tmp / "stimme.json")
        self.p._stimme_anzahl = 3
        self.p._stimme_lernt = None
        self.p._stimme_lernt_gast = False
        self.p._stimme_rueckweisungen = 0
        self.p._letztes_urteil = None
        self.gesagt: list[str] = []

        async def _say(text, **kw):
            self.gesagt.append(text)
            return True

        self.p._say = _say

        def _kein_stil() -> None:
            raise AssertionError(
                "Der Sprechstil wurde uebernommen, obwohl ein Gast lernte."
            )

        self.p._apply_learned_speech_style = _kein_stil

        class _Bus:
            async def publish(self, *a, **k):
                return None

        self.p._event_bus = _Bus()


def test_hoer_auf_diese_stimme_startet_das_gastsammeln(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "get_data_dir", lambda: tmp_path)
    h = _Harness(tmp_path)
    _benutzer_lernen(h.p._stimme, tmp_path)
    h.p._letztes_urteil = Urteil(True, 0.9, 0.6, "Bekannte Stimme.", True, "benutzer")

    behandelt = asyncio.run(h.p._stimme_befehl("Hör auf diese Stimme."))

    assert behandelt
    assert h.p._stimme_lernt == []
    assert h.p._stimme_lernt_gast is True
    assert any("hör nur auf mich" in s for s in h.gesagt)


def test_gastsammeln_lernt_ein_gastprofil(tmp_path, monkeypatch):
    """Der ganze Weg: Befehl, drei vorgespielte Saetze, Gast zugelassen."""

    monkeypatch.setattr(paths, "get_data_dir", lambda: tmp_path)
    h = _Harness(tmp_path)
    _benutzer_lernen(h.p._stimme, tmp_path)
    h.p._stimme_lernt = []
    h.p._stimme_lernt_gast = True

    for probe in _gastproben(tmp_path):
        asyncio.run(h.p._stimme_sammeln(probe))

    assert h.p._stimme.gaeste == 1, "aus den Proben wurde kein Gastprofil"
    assert h.p._stimme_lernt is None, "das Sammeln wurde nicht abgeschlossen"
    assert h.p._stimme_lernt_gast is False
    # Das Benutzerprofil ist unangetastet.
    ich = h.p._stimme.pruefen(
        _stimme(tmp_path / "ich-nachher.wav", SPRECHER_A, grundton=122.0, versatz=66)
    )
    assert ich.akzeptiert and ich.wer == "benutzer"


def test_ein_gast_darf_die_stimmen_nicht_verwalten(tmp_path, monkeypatch):
    """Sonst koennte ein Gast den Hausherrn aussperren."""

    monkeypatch.setattr(paths, "get_data_dir", lambda: tmp_path)
    h = _Harness(tmp_path)
    _benutzer_lernen(h.p._stimme, tmp_path)
    h.p._stimme.gast_lernen(_gastproben(tmp_path))
    h.p._letztes_urteil = Urteil(True, 0.8, 0.6, "Zugelassene Gaststimme.", True, "gast")

    for satz in (
        "Vergiss meine Stimme.",
        "Hör auf diese Stimme.",
        "Hör nur auf mich.",
        "Lern meine Stimme neu.",
    ):
        h.gesagt.clear()
        behandelt = asyncio.run(h.p._stimme_befehl(satz))
        assert behandelt, f"{satz!r} wurde nicht behandelt"
        assert any("Gast" in s for s in h.gesagt), f"{satz!r} wurde nicht verweigert"

    assert h.p._stimme.gelernt is True, "ein Gast hat das Benutzerprofil geloescht"
    assert h.p._stimme.gaeste == 1, "ein Gast hat an den Gaststimmen geruehrt"
    assert h.p._stimme_lernt is None, "ein Gast hat ein Sammeln gestartet"


def test_hoer_nur_auf_mich_als_befehl(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "get_data_dir", lambda: tmp_path)
    h = _Harness(tmp_path)
    _benutzer_lernen(h.p._stimme, tmp_path)
    h.p._stimme.gast_lernen(_gastproben(tmp_path))
    h.p._letztes_urteil = Urteil(True, 0.9, 0.6, "Bekannte Stimme.", True, "benutzer")

    behandelt = asyncio.run(h.p._stimme_befehl("Hör nur auf mich!"))

    assert behandelt
    assert h.p._stimme.gaeste == 0
    assert any("nur noch auf dich" in s for s in h.gesagt)


def test_kurzes_unklares_urteil_sperrt_den_benutzer_nicht_aus(tmp_path, monkeypatch):
    """Im Zweifel wird nicht ausgesperrt - ein zu kurzer Satz macht den
    Benutzer nicht zum Gast."""

    monkeypatch.setattr(paths, "get_data_dir", lambda: tmp_path)
    h = _Harness(tmp_path)
    _benutzer_lernen(h.p._stimme, tmp_path)
    h.p._letztes_urteil = Urteil(True, grund="Zu kurz.", geprueft=False)

    assert h.p._stimmrecht() is True


def test_verifizierter_benutzer_braucht_auch_im_wachfenster_keine_anrede(
    tmp_path, monkeypatch
):
    """Die Stimme selbst ist die Anrede; der Richtungsfilter darf einen
    normalen Aussagesatz des Benutzers nicht mehr verwerfen."""

    monkeypatch.setattr(paths, "get_data_dir", lambda: tmp_path)
    h = _Harness(tmp_path)
    h.p._freie_ansprache = True
    h.p._ruhe = False
    h.p._letztes_urteil = Urteil(
        True, 0.91, 0.55, "Bekannte Stimme.", True, "benutzer"
    )

    assert h.p._freie_benutzeransprache_aktiv() is True


def test_gaststimme_bleibt_trotz_freier_ansprache_im_richtungsfilter(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(paths, "get_data_dir", lambda: tmp_path)
    h = _Harness(tmp_path)
    h.p._freie_ansprache = True
    h.p._ruhe = False
    h.p._letztes_urteil = Urteil(
        True, 0.86, 0.55, "Zugelassene Gaststimme.", True, "gast"
    )

    assert h.p._freie_benutzeransprache_aktiv() is False


# --- Die freie Ansprache (Verdrahtung) --------------------------------------------


def _quelle() -> str:
    return Path("backend/voice/voice_pipeline.py").read_text(encoding="utf-8")


def test_erkannte_stimme_weckt_ohne_weckwort():
    """Die Verdrahtung im Aeusserungsweg: geprueft erkannte Stimme -> wach.

    Der Block muss VOR der Schlafpruefung stehen und an drei Bedingungen
    haengen: freie Ansprache an, keine Ruhe, Urteil wirklich geprueft.
    """

    quelle = _quelle()
    stelle = quelle.find("Freie Ansprache: Die nachweislich erkannte Stimme")
    assert stelle > 0, "der Block der freien Ansprache fehlt"
    block = quelle[stelle : stelle + 1200]
    for bedingung in (
        '"_freie_ansprache"',
        '"_ruhe"',
        "urteil.geprueft",
        "self._is_asleep()",
        "self._wake()",
        "VoiceState.LISTENING",
    ):
        assert bedingung in block, f"in der freien Ansprache fehlt: {bedingung}"
    # Und sie steht vor der Schlaf-Vorpruefung mit dem kleinen Modell.
    assert stelle < quelle.find("if self._is_asleep():", stelle + len(block) - 600) or (
        "_stop_transcriber" in quelle[stelle:]
    )


def test_wegschicken_schaltet_in_ruhe_und_weckwort_hebt_sie_auf():
    quelle = _quelle()

    wegschicken = quelle.find("if self._is_dismissal(text):")
    assert wegschicken > 0
    assert "self._ruhe = True" in quelle[wegschicken : wegschicken + 800], (
        "das Wegschicken schaltet nicht in Ruhe - bei freier Ansprache "
        "weckte der naechste eigene Satz den Orb sofort wieder"
    )

    weckwort = quelle.find('logger.info("Weckwort erkannt')
    assert weckwort > 0
    umfeld = quelle[max(0, weckwort - 400) : weckwort + 400]
    assert "self._ruhe = False" in umfeld, "das Weckwort hebt die Ruhe nicht auf"


def test_die_einstellung_steht_in_der_konfiguration():
    inhalt = Path("config.yaml").read_text(encoding="utf-8", errors="replace")
    assert "freie_ansprache: true" in inhalt
