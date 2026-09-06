"""Keine unnatuerlichen Luecken mitten im Satz.

Meldung des Benutzers vom 20.08.2026: "die sprachausgabe ist zu wenig
fluessig, keine unnatuerlichen luecken mitten in einem satz". Drei
Ursachen fanden sich, und diese Tests halten alle drei geschlossen:

* Der Punkt einer Ordnungszahl ("im 6. Jahrhundert") galt als Satzende -
  in DREI Zerlegern unabhaengig voneinander (Sprachpipeline,
  Antwortstrom, TTS-Abschnitte). Zwischen den Bruchstuecken entstand
  jedes Mal eine Sprechpause mitten im Gedanken.
* Der weiche Umbruch langer Saetze schnitt viel zu frueh am Komma. Die
  Fortsetzungsintonation plus Dateigrenze klang wie Unsicherheit. Jetzt
  trennt ein Semikolon zuerst; Komma und Leerzeichen sind spaete Notfaelle.
* Im Streaming ging jeder Satz einzeln in die Sprachausgabe, obwohl das
  Modell laengst mehrere Saetze voraus war - zwischen zwei Saetzen
  klaffte die Rechenzeit der naechsten Synthese. Fertige Saetze werden
  jetzt gesammelt und in einem Zug gesprochen.
"""

from __future__ import annotations

from backend.tts.tts_manager import _kein_satzende
from backend.voice.voice_pipeline import _gesprochene_kurzfassung, _take_complete_sentence


def test_tts_rueckfall_liest_keine_urls_und_ist_begrenzt():
    lang = "Eine belastbare Aussage. " * 80 + "https://example.org/sehr/lang"
    kurz = _gesprochene_kurzfassung(lang, max_zeichen=180)
    assert "http" not in kurz
    assert len(kurz) < 280
    assert kurz.endswith("Weitere Details fasse ich dir auf Wunsch kurz zusammen.")


# --- Die Ordnungszahl ist kein Satzende --------------------------------------


def test_ordnungszahlen_zerreissen_keinen_satz():
    satz = "Zwischen dem 6. und 8. Jahrhundert wanderten die Laute. "
    gefunden, rest = _take_complete_sentence(satz + "Danach kam Ruhe. ")
    assert gefunden == "Zwischen dem 6. und 8. Jahrhundert wanderten die Laute."
    assert rest.startswith("Danach")


def test_ein_datum_bleibt_beisammen():
    gefunden, _ = _take_complete_sentence(
        "Am 24. Dezember 1914 schwiegen die Waffen. Das ist belegt. "
    )
    assert gefunden == "Am 24. Dezember 1914 schwiegen die Waffen."


def test_eine_jahreszahl_darf_den_satz_beenden():
    gefunden, rest = _take_complete_sentence(
        "Der Wiener Kongress endete 1815. Danach kam die Restauration. "
    )
    assert gefunden == "Der Wiener Kongress endete 1815."
    assert rest.startswith("Danach")


def test_die_tts_abschnitte_heilen_die_ordnungszahl():
    """Auch der Abschnitts-Zerleger der Sprachausgabe (fuer lange Texte
    ohne Streaming) darf am Ordnungszahl-Punkt keine Pause setzen."""

    assert _kein_satzende("Zwischen dem 6.")
    assert _kein_satzende("also z. B.")
    assert not _kein_satzende("Der Kongress endete 1815.")
    assert not _kein_satzende("Das ist belegt.")


def test_lange_texte_zerfallen_nicht_an_der_ordnungszahl():
    from backend.tts.tts_manager import TtsManager

    satz = (
        "Zwischen dem 6. und 8. Jahrhundert verschob sich das Lautsystem, "
        "und zwar nicht auf einmal, sondern in Wellen. "
    )
    text = satz * 20  # weit ueber der Abschnittsgrenze
    chunks = TtsManager.split_into_chunks(
        TtsManager.__new__(TtsManager), text, max_characters=300
    )
    assert len(chunks) > 1, "Testaufbau: der Text soll zerlegt werden"
    for chunk in chunks:
        assert not chunk.rstrip().endswith(" 6."), chunk
        assert not chunk.rstrip().endswith(" 8."), chunk


# --- Der weiche Umbruch bricht nur, wo ein Mensch Luft holt -------------------


def test_ein_gewoehnlicher_langer_satz_bleibt_trotz_komma_ganz():
    lang = (
        "Die zweite Lautverschiebung erfasste die stimmlosen Verschlusslaute, "
        "und sie tat das je nach der Stellung im Wort auf sehr verschiedene "
        "Weise und mit deutlich unterschiedlicher Geschwindigkeit weiter"
    )
    assert len(lang) >= 160, "Testaufbau: der Satz soll lang sein"
    gefunden, rest = _take_complete_sentence(lang)
    assert gefunden == ""
    assert rest == lang


def test_komma_ist_nur_noch_die_spaete_notloesung():
    lang = ("Die Entwicklung verlief regional verschieden, " * 10).strip()
    assert len(lang) >= 400
    gefunden, rest = _take_complete_sentence(lang)
    assert gefunden.endswith(",")
    assert rest


def test_ohne_komma_wird_erst_spaet_und_dann_am_leerzeichen_gebrochen():
    ohne_komma = "wort " * 140  # 700 Zeichen, kein Komma weit und breit
    gefunden, _ = _take_complete_sentence(ohne_komma[:250])
    assert gefunden == "", "vor der Notgrenze darf ohne Komma nichts brechen"

    gefunden, rest = _take_complete_sentence(ohne_komma)
    assert gefunden, "irgendwann muss der Orb ins Reden kommen"
    assert not gefunden.endswith(" ")


def test_der_antwortstrom_zerreisst_keinen_gewoehnlichen_kommasatz():
    from backend.orchestrator.speech_stream import SpeechStream

    strom = SpeechStream()
    saetze = strom.feed(
        "Die Verschiebung erfasste die stimmlosen Verschlusslaute, "
        "und zwar nach Stellung im Wort auf ganz verschiedene Weise weiter"
    )
    assert saetze == []


def test_der_antwortstrom_nimmt_komma_nur_im_extremen_notfall():
    from backend.orchestrator.speech_stream import SpeechStream

    strom = SpeechStream()
    saetze = strom.feed(("Die Entwicklung verlief regional verschieden, " * 10).strip())
    assert saetze
    assert saetze[0].endswith(",")


def test_der_antwortstrom_laesst_die_ordnungszahl_beisammen():
    from backend.orchestrator.speech_stream import SpeechStream

    strom = SpeechStream()
    saetze = strom.feed("Zwischen dem 6. und 8. Jahrhundert. Gut. ")
    assert all(not s.rstrip().endswith(" 6.") for s in saetze), saetze


# --- Fertige Saetze gehen gesammelt in die Ausgabe ----------------------------


def test_bereitliegende_saetze_gehen_in_den_vorproduktionsstrom():
    """Der Streaming-Weg darf nicht auf jede fertige Wiedergabe warten."""

    from pathlib import Path

    quelle = Path("backend/voice/voice_pipeline.py").read_text(encoding="utf-8")
    anfang = quelle.index("async def _respond_streaming")
    ende = quelle.index("async def ", anfang + 10)
    ausschnitt = quelle[anfang:ende]
    assert "self._satzstrom_starten()" in ausschnitt
    assert "await self._sprich_satz(satz)" in ausschnitt
    sammel = ausschnitt.index("saetze.append(sentence)")
    sprechen = ausschnitt.index("await self._sprich_satz(satz)")
    assert sammel < sprechen
