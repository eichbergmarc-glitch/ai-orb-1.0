"""Tests des Unterbrechens.

Der Orb sprach weiter, wenn man ihn unterbrach. Der Grund war nicht, dass
die Unterbrechung nicht ankam - sie kam an und griff, aber nur fuer einen
Satz.

Seit die Antwort im Fluss gesprochen wird, ist jeder Satz ein eigener
Sprechvorgang. Und dieser Vorgang loeschte das Abbruchzeichen an seinem
Anfang und an seinem Ende. Wer den vierten Satz unterbrach, stoppte also
genau den vierten; der fuenfte kam als neuer Vorgang herein, fand ein
sauberes Zeichen vor und sprach weiter. Von aussen sah das aus, als sei
die Unterbrechung wirkungslos.

Der erste Test hier ist deshalb der wichtigste: Ein Abbruch muss die ganze
ANTWORT zum Schweigen bringen, nicht den Satz, der gerade lief. Genau das
liess sich vorher nicht sagen, weil niemand es geprueft hat.
"""

from __future__ import annotations

import re

from backend.utils.paths import get_project_root

QUELLE = get_project_root() / "backend" / "voice" / "voice_pipeline.py"


def _text() -> str:
    return QUELLE.read_text(encoding="utf-8")


def _code() -> str:
    """Der Quelltext ohne Kommentarzeilen.

    Noetig, weil an der Stelle, wo das Loeschen frueher stand, jetzt ein
    Kommentar steht, der erklaert, warum es dort NICHT mehr steht. Ein
    Test, der Kommentare mitzaehlt, schlaegt also genau wegen der
    Erklaerung der Behebung fehl - und das waere die duemmste Art, einen
    Test zu verlieren.
    """

    zeilen = [z for z in _text().splitlines() if not z.lstrip().startswith("#")]
    return "\n".join(zeilen)


# --- Der Abbruch ueberlebt den Satz ---------------------------------------------


def test_das_abbruchzeichen_wird_nur_an_einer_stelle_geloescht():
    """Zwei Stellen waren zwei zu viel."""

    treffer = re.findall(r"self\._interrupted\.clear\(\)", _code())
    assert len(treffer) == 1, (
        f"{len(treffer)} Stellen loeschen das Abbruchzeichen - "
        "wer mitten in einer Antwort unterbricht, wird ueberhoert"
    )


def test_geloescht_wird_nur_wenn_eine_neue_rede_beginnt():
    text = _code()
    start = text.index("def _neue_rede(self)")
    ende = text.index("async def say(", start)
    assert "self._interrupted.clear()" in text[start:ende]


def test_der_sprechvorgang_loescht_nichts_mehr():
    """Weder am Anfang eines Satzes noch an seinem Ende."""

    text = _code()
    start = text.index("async def _say_locked")
    ende = text.index("async def wait_until_warm")
    assert "self._interrupted.clear()" not in text[start:ende]


def test_eine_neue_anweisung_hebt_den_abbruch_auf():
    """Sonst bliebe der Orb nach einer Unterbrechung fuer immer stumm."""

    text = _code()
    start = text.index("async def _handle_utterance")
    ende = text.index("async def stimme_lernen_starten")
    assert "self._neue_rede()" in text[start:ende]


# --- Dazwischenreden ohne hinterlegte Stimme -------------------------------------


class _Halb:
    """Nur die zwei Methoden, um die es geht."""

    def __init__(self, gesagt: str):
        from backend.voice.voice_pipeline import VoicePipeline

        self.p = VoicePipeline.__new__(VoicePipeline)
        self.p._gesprochene_woerter = VoicePipeline._woerter(gesagt)

    def fremd(self, gehoert: str) -> bool:
        from backend.voice.voice_pipeline import VoicePipeline

        return VoicePipeline._ist_fremde_rede(self.p, gehoert)


def test_das_eigene_echo_unterbricht_nicht():
    """Der wichtigste Test hier.

    Waehrend der Orb spricht, hoert das Mikrofon vor allem ihn. Schlaegt
    sein eigenes Echo an, kaeme er nie ueber den ersten Satz hinaus.
    """

    halb = _Halb("Die Hauptstadt der Schweiz ist Bern und liegt an der Aare.")

    assert not halb.fremd("Die Hauptstadt der Schweiz ist Bern")
    assert not halb.fremd("liegt an der Aare")
    assert not halb.fremd("Bern")


def test_fremde_worte_unterbrechen():
    halb = _Halb("Die Hauptstadt der Schweiz ist Bern und liegt an der Aare.")

    assert halb.fremd("warte kurz erzaehl mir lieber etwas anderes")
    assert halb.fremd("nein das stimmt nicht")


def test_ein_einzelnes_kurzes_wort_genuegt_nicht():
    """Ein Orb, der bei jedem Knacken verstummt, ist schlimmer als einer,
    der einmal zu lange redet."""

    halb = _Halb("Die Hauptstadt der Schweiz ist Bern.")

    assert not halb.fremd("")
    assert not halb.fremd("aeh")
    assert not halb.fremd("Bern Wien")


def test_ein_einzelnes_langes_wort_genuegt_sehr_wohl():
    """Zwei unbekannte Woerter waren zu streng fuer den haeufigsten Fall.

    "Nein, warte" hat nur ein Wort ueber vier Zeichen. Ein Wort mit sieben
    Zeichen erfindet die Erkennung aber nicht aus einem Knacken - dafuer
    ist es zu lang. Die Laenge ersetzt hier die Anzahl.
    """

    halb = _Halb("Die Hauptstadt der Schweiz ist Bern.")

    assert halb.fremd("Moment")  is False, "sechs Zeichen sind noch zu kurz"
    assert halb.fremd("Augenblick"), "ein langes fremdes Wort muss reichen"


def test_kurze_woerter_zaehlen_nicht():
    """Fuellwoerter erkennt Whisper aus jedem Rauschen."""

    halb = _Halb("Die Hauptstadt der Schweiz ist Bern.")

    assert not halb.fremd("und ja am so ob")


def test_beide_pruefungen_laufen_nebeneinander():
    """Der Denkfehler, der das Hinterlegen der Stimme zum Nachteil machte.

    Vorher galt: Stimmerkennung, WENN eine Stimme hinterlegt ist - und der
    Wortvergleich nur sonst. Das Hoerfenster enthaelt waehrend des
    Sprechens aber vor allem den Orb selbst; eine kurze Zwischenbemerkung
    geht darin unter, die Aehnlichkeit bleibt unter der Schwelle - und der
    Wortvergleich kam gar nicht mehr zum Zug. Wer seine Stimme hinterlegte,
    konnte den Orb also SCHLECHTER unterbrechen als vorher.

    Beide beantworten dieselbe Frage auf verschiedenen Wegen. Ein Ja von
    einer reicht.
    """

    text = _code()
    stelle = text.index("_ist_fremde_rede(transcript.text)")
    umfeld = text[stelle - 400 : stelle + 60]
    assert "not self._stimme.aktiv" not in umfeld, (
        "der Wortvergleich ist weiterhin an das Fehlen einer Stimme geknuepft"
    )


# --- Der Orb unterbricht sich selbst -------------------------------------------------
#
# Der Benutzer meldete: "manchmal unterbricht der orb seine antworten ohne
# dass ich ihn unterbreche."
#
# Die Ursache lag im Wortvergleich. Er arbeitet nicht auf sauberer Sprache,
# sondern auf dem, was die Erkennung aus dem ECHO der eigenen Stimme macht -
# und das ist ein Text mit verhoerten Woertern. Verglichen wurde aber Zeichen
# fuer Zeichen: Was nicht woertlich im eigenen Satz stand, galt als fremd.
# Weil Deutsch lange Woerter hat, schlug schon ein einziger Verhoerer die
# Sieben-Zeichen-Regel und brach die Antwort ab.

from backend.voice.voice_pipeline import (
    AEHNLICH_GENUG,
    ECHO_SAETZE,
    FREMD_GENUG,
    VoicePipeline,
)


class _Pruefstand:
    """Nur die beiden Methoden, ohne Mikrofon und Sprachausgabe."""

    def __init__(self, gesprochen: str) -> None:
        self._woerter = VoicePipeline._woerter
        self._gesprochene_woerter = VoicePipeline._woerter(gesprochen)

    def _naehe_zum_eigenen(self, wort: str) -> float:
        return VoicePipeline._naehe_zum_eigenen(self, wort)

    def fremd(self, text: str) -> bool:
        return VoicePipeline._ist_fremde_rede(self, text)


_SATZ = (
    "Die Sprachausgabe wird beendet, sobald ich deine Stimme im "
    "Hörfenster verstanden habe."
)


def test_ein_verhoerer_der_eigenen_stimme_gilt_nicht_als_zwischenruf():
    """Genau der Fall, der die Antworten abbrach."""

    p = _Pruefstand(_SATZ)
    # Ein einzelnes langes Wort, leicht verhoert - frueher reichte das.
    assert not p.fremd("Sprachaufgabe"), (
        "Ein Verhoerer des eigenen Wortes gilt weiterhin als fremde Rede."
    )
    assert not p.fremd("die Sprachaufgabe wird beended")


def test_mehrere_verhoerer_gelten_immer_noch_nicht_als_zwischenruf():
    """So, wie die Erkennung den eigenen Satz tatsaechlich verhoert."""

    p = _Pruefstand(_SATZ)
    assert not p.fremd("Hörfenster verstehen Stimmen")


def test_ein_echter_zwischenruf_wird_erkannt():
    """Die Behebung darf das Unterbrechen nicht kaputtmachen."""

    p = _Pruefstand(_SATZ)
    assert p.fremd("nein warte einen Moment"), "Ein Zwischenruf wird ueberhoert."
    assert p.fremd("kannst du bitte kurz aufhören")


def test_die_grenze_des_wortvergleichs_ist_bekannt():
    """Sehr kurze Zurufe faengt er nicht - und das ist Absicht.

    "hör auf damit" hat genau ein Wort ueber vier Zeichen. Das genuegt
    nicht, und die Regel abzusenken waere genau der Weg zurueck in den
    Fehler, um den es hier geht: Je kuerzer das verlangte Wort, desto
    eher erfindet die Erkennung es aus dem Echo.

    Fuer den kurzen Zuruf gibt es die beiden anderen Wege - das Stop-Wort
    und die Stimmerkennung. Dieser Test haelt fest, dass die Luecke
    bekannt ist und nicht aus Versehen entstand.
    """

    assert not _Pruefstand(_SATZ).fremd("hör auf damit")


def test_ein_einzelnes_langes_fremdwort_genuegt_weiterhin():
    """Fuer die kurze Zwischenbemerkung."""

    p = _Pruefstand(_SATZ)
    assert p.fremd("Zwischenbemerkung")


def test_leeres_hoerfenster_ist_kein_zwischenruf():
    assert not _Pruefstand(_SATZ).fremd("")


# --- Die Regeln, die das absichern ---------------------------------------------------


def test_der_wortvergleich_ist_kein_reiner_mengenabzug_mehr():
    """Der Mengenabzug WAR der Fehler - er darf nicht zurueckkommen."""

    text = _code()
    assert "_naehe_zum_eigenen" in text, "Die Aehnlichkeitspruefung fehlt."
    assert "SequenceMatcher" in text
    assert "self._woerter(text) - self._gesprochene_woerter" not in text, (
        "Der reine Mengenabzug ist zurueck - dann verhoert sich der Orb "
        "wieder selbst zum Fremden."
    )


def test_ein_einzelnes_fenster_bricht_nicht_mehr_ab():
    """Ein Verhoerer ist ein Ausrutscher, ein Zwischenruf dauert an."""

    text = _code()
    assert "_fremd_folge" in text, "Aufeinanderfolgende Fenster werden nicht gezaehlt."
    assert "self._fremd_folge >= self._fremd_fenster_noetig" in text
    assert "self._fremd_folge = 0" in text, "Die Zaehlung wird nie zurueckgesetzt."


def test_schlecht_erkannte_fenster_zaehlen_nicht():
    """Dort erfindet die Erkennung - und Erfundenes sah aus wie Rede."""

    assert "_fremd_mindestsicherheit" in _code()
    assert "transcript.confidence" in _code()


def test_die_stimmerkennung_unterbricht_weiterhin_sofort():
    """Der starke Weg darf nicht mitverzoegert werden.

    Erkennt die Stimmerkennung die hinterlegte Stimme, ist die Frage
    beantwortet - da braucht es keine zweite Bestaetigung. Wuerde auch
    dieser Weg zwei Fenster verlangen, waere die Behebung des einen
    Fehlers der naechste.
    """

    text = _code()
    # Der Stimm-Weg unterbricht weiterhin SOFORT (ohne Fensterzaehlung) -
    # jetzt aber erst ab einer hohen Aehnlichkeit, damit nicht das eigene
    # Echo abbricht.
    stelle = text.index("urteil.aehnlichkeit >= schwelle")
    ausschnitt = text[stelle : stelle + 700]
    assert "self.interrupt()" in ausschnitt
    assert "_fremd_folge" not in ausschnitt, (
        "Die Stimmerkennung wurde an die Fensterzaehlung gehaengt."
    )


def test_das_echo_gedaechtnis_reicht_ueber_mehrere_saetze():
    """Ein Satz Vorlauf reichte nicht - das Echo hinkt weiter nach."""

    assert ECHO_SAETZE >= 3, (
        f"{ECHO_SAETZE} Saetze Gedaechtnis: Faellt ein Hoerfenster auf einen "
        "aelteren Satz, haelt sich der Orb wieder selbst fuer einen Fremden."
    )
    assert "_letzte_saetze" in _code()


def test_die_aehnlichkeitsschwelle_bleibt_in_einem_sinnvollen_bereich():
    """Zu tief verschluckt Zwischenrufe, zu hoch bringt die Verhoerer zurueck."""

    assert 0.6 <= AEHNLICH_GENUG <= 0.85


def test_ein_einzelnes_wort_wird_strenger_geprueft_als_zwei():
    """Zwei verschiedene Fragen, zwei verschiedene Schwellen.

    Ob ein Wort ein Verhoerer ist, und ob EIN Wort genuegt, um eine
    laufende Antwort abzubrechen, ist nicht dasselbe. Die zweite
    Behauptung ist die groessere und braucht den groesseren Abstand.
    """

    assert FREMD_GENUG < AEHNLICH_GENUG


def test_die_verhoerte_endung_bricht_nicht_mehr_ab():
    """Der gemessene Anlass: "verstehen" statt des gesagten "verstanden".

    Aehnlichkeit 0.74 - knapp unter der Verhoerergrenze - und neun
    Zeichen lang. Nach der alten Regel brach dieses eine Wort die ganze
    Antwort ab. Die Erkennung verhoert sich an Endungen und nicht an
    Wortstaemmen, das ist also der haeufigste Fall ueberhaupt.
    """

    assert not _Pruefstand("Ich habe deine Stimme verstanden").fremd("verstehen")
