"""Das Stop-Wort muss den Orb anhalten.

Der Anlass: Der Benutzer meldete am 19.08.2026, dass das Stop-Wort den
Orb nicht mehr unterbricht. Im Protokoll steht der Befund - seit dem
15.08. griff es bei rund tausend Äusserungen genau EINMAL, während die
beiden anderen Abbruchwege (Stimmähnlichkeit, fremde Worte) regelmässig
ansprachen.

Die Prüfung selbst war nicht schuld: Sie verlangte Buchstabengleichheit
mit "stop", "stopp" oder "halt", und die echten Protokollzeilen unten
erfüllen das. Sie war nur zu eng für das, was ein kleines Modell aus
einem Fenster macht, in dem gleichzeitig der eigene Lautsprecher läuft.

Alle "so schreibt es die Erkennung"-Beispiele hier sind echte Zeilen aus
``backend_voice_voice_pipeline.log``.
"""

from __future__ import annotations

import pytest

from backend.voice.stopwort import _abstand_eins, stopwort_finden


# --- Was die Erkennung wirklich geliefert hat ------------------------------


@pytest.mark.parametrize(
    "gehoert",
    [
        "Stopp.",                                   # 14.08. 19:38
        "Stopp, Sourcesing.",                       # 14.08. 13:36
        "Denoeidung, stopp.",                       # 16.08. 14:59
        "Nein, stopp, stopp, stopp, ich hab das",   # 17.08. 21:23
    ],
)
def test_echte_protokollzeilen_werden_erkannt(gehoert):
    assert stopwort_finden(gehoert) is not None, gehoert


# --- Und was sie sonst noch daraus macht -----------------------------------


@pytest.mark.parametrize(
    "gehoert",
    [
        # Befehlsformen
        "stoppe", "Stoppe!", "Halt!", "Halt bitte",
        # Verhoerer des kleinen Modells auf einem lauten Fenster
        "stopt", "stoppp", "schtopp", "stopps",
        # Und mit dem Ruf zusammen - er steht vorn, wie ein Zwischenruf.
        "Stopp jetzt bitte",
        # Wendungen
        "hör auf", "Hör auf bitte", "sei still", "Es reicht.",
        "Sei ruhig", "das reicht",
        # Weitere Abbruchworte
        "abbrechen", "Aufhören", "Halt stopp",
    ],
)
def test_die_gaengigen_abbrueche_greifen(gehoert):
    assert stopwort_finden(gehoert) is not None, gehoert


# --- Und was ausdrücklich NICHT abbrechen darf -----------------------------


@pytest.mark.parametrize(
    "gehoert",
    [
        # "halt" steckt in vielen Woertern - geprueft wird auf GANZE.
        "Das Gehalt ist gestiegen",
        "Seine Haltung war klar",
        "Der Vertrag wurde eingehalten",
        "Wir haben das behalten",
        # Nachbarn von "halt", die eine unscharfe Pruefung faelschlich
        # traefe. Deshalb gilt fuer kurze Woerter nur Buchstabengleichheit.
        "Es ist kalt", "Das ist alt", "Er hält das Buch", "bald geht es los",
        # Echte Saetze aus dem Protokoll, die nie abbrechen durften
        "Erklär mir bitte die Julikrise",
        "Suche nach dem Philosophen Markus Gabriel",
        # Woerter, die nach Abbruch klingen, aber in gewoehnlicher Rede
        # staendig vorkommen. Eine Notbremse, die bei "zum Schluss" zieht,
        # waere schlimmer als gar keine.
        "Lies es dir in Ruhe durch",
        "Zum Schluss noch ein Gedanke",
        "Sei doch bitte einmal still gewesen",
        # Und ein Verhoerer, der zwei Buchstaben danebenliegt: "stobb"
        # greift bewusst NICHT. Zwei Buchstaben Abstand sind kein
        # Verhoerer mehr, sondern ein anderes Wort - und eine Notbremse,
        # die bei anderen Woertern zieht, ist keine.
        "stobb",
    ],
)
def test_aehnliche_woerter_brechen_nicht_ab(gehoert):
    assert stopwort_finden(gehoert) is None, gehoert


def test_halt_als_fuellwort_bricht_nichts_ab():
    # "halt" ist im deutschen Alltag vor allem ein Fuellwort. Alle vier
    # Zeilen unten stehen so im Protokoll - und alle vier haetten den Orb
    # mitten im Satz abgebrochen.
    for satz in ("Das ist halt so", "was wir halt erleben",
                 "es ist halt gelungen", "also denk halt nach"):
        assert stopwort_finden(satz) is None, satz

    # Als Zwischenruf steht es vorn, und dort zaehlt es.
    assert stopwort_finden("Halt, warte mal") == "halt"
    assert stopwort_finden("Nein, halt!") == "halt"


def test_beugungen_mitten_in_der_rede_zaehlen_nicht():
    # Alles echte Saetze aus der eigenen Antwort des Orb.
    for satz in ("ich muss das stoppen", "ich halte das für richtig",
                 "wo die Reihe aufhört", "das lässt sich nicht anhalten"):
        assert stopwort_finden(satz) is None, satz


def test_zusaetzliche_woerter_aus_der_konfiguration_gelten():
    assert stopwort_finden("Basta", frozenset({"basta"})) == "basta"
    assert stopwort_finden("Basta") is None


def test_leerer_text_ergibt_nichts():
    assert stopwort_finden("") is None
    assert stopwort_finden(None) is None  # type: ignore[arg-type]


def test_das_gefundene_wort_wird_zurueckgegeben():
    # Es steht danach im Protokoll. Ohne diese Angabe war am 19.08. nicht
    # zu klaeren, WORAN ein Abbruch haengt - oder warum keiner kam.
    assert stopwort_finden("Also stopp jetzt") == "stopp"
    assert stopwort_finden("hör auf") == "hör auf"


# --- Der Ein-Buchstaben-Abstand -------------------------------------------


@pytest.mark.parametrize(
    "a, b, erwartet",
    [
        ("stopp", "stopp", True),
        ("stobb", "stopp", False),   # zwei Buchstaben - kein Treffer
        ("stopt", "stopp", True),
        ("stoppp", "stopp", True),   # eingefuegt
        ("stop", "stopp", True),     # entfernt
        ("stoff", "stopp", False),
        ("halt", "kalt", True),      # deshalb kein unscharfer Vergleich
                                     # fuer kurze Woerter
    ],
)
def test_der_abstand_rechnet_richtig(a, b, erwartet):
    assert _abstand_eins(a, b) is erwartet


# --- Die Gegenprobe in der Pipeline ----------------------------------------
#
# Weit fassen darf die Prüfung nur, weil danach gefragt wird: Kam das Wort
# aus dem eigenen Lautsprecher? Der Orb weiss, was er gerade sagt.


class _Attrappe:
    """Nur die Teile der Pipeline, die für die Gegenprobe nötig sind.

    Bewusst kein ``VoicePipeline.__new__``: Dieses Vorgehen hat in
    früheren Tests reihenweise fehlende Attribute nachgezogen. Hier
    stehen genau die drei, die die geprüften Methoden anfassen.
    """

    def __init__(self, spricht_gerade: str = ""):
        from backend.voice.voice_pipeline import VoicePipeline

        self._stop_words = frozenset({"stop", "stopp", "halt"})
        self._gesprochene_woerter = {
            w.lower() for w in spricht_gerade.split()
        }
        self._treffer = VoicePipeline._stopwort_treffer.__get__(self)
        self._naehe_zum_eigenen = VoicePipeline._naehe_zum_eigenen.__get__(self)


def test_ein_stopp_greift_wenn_der_orb_etwas_anderes_sagt():
    orb = _Attrappe("Die Julikrise begann im Juli neunzehnhundertvierzehn")
    assert orb._treffer("stopp") == "stopp"


def test_das_eigene_echo_greift_nicht():
    # Sagt der Orb selbst "Ich stoppe die Suche", darf das aus dem
    # Lautsprecher zurueckkommende "stoppe" ihn nicht anhalten.
    orb = _Attrappe("Ich stoppe die Suche jetzt")
    assert orb._treffer("stoppe") is None


def test_ohne_eigene_rede_gilt_jeder_treffer():
    # Ausserhalb des Sprechens gibt es kein Echo, gegen das zu pruefen waere.
    orb = _Attrappe("")
    assert orb._treffer("Halt!") == "halt"


def test_der_spaeher_schreibt_seine_bilanz_ins_protokoll():
    # Ohne diese Zeile war am 19.08. nicht zu unterscheiden, ob das Wort
    # nie ankam oder ankam und verworfen wurde.
    from pathlib import Path

    quelle = Path("backend/voice/voice_pipeline.py").read_text(encoding="utf-8")
    assert "_spaeher_bilanz" in quelle
    assert "_spaeher_merken(transcript.text)" in quelle
    assert "Stop-Späher:" in quelle


def test_der_spaeher_bekommt_einen_eigenen_anker():
    # Der lange Anker des grossen Modells ("Historiografie",
    # "Bruttoinlandsprodukt") lenkt ein Achtelsekundenfenster von "Stopp"
    # weg statt darauf hin.
    from pathlib import Path

    quelle = Path("backend/voice/voice_pipeline.py").read_text(encoding="utf-8")
    anfang = quelle.index("self._stop_transcriber = Transcriber(")
    ende = quelle.index(")", quelle.index("anfangshinweis=", anfang))
    ausschnitt = quelle[anfang:ende]
    assert "voice.stop_initial_prompt" in ausschnitt
    assert "voice.input.initial_prompt" not in ausschnitt


def test_ein_echtes_wort_neben_der_stopp_familie_bricht_nicht_ab():
    # "Stopfen" liegt einen Buchstaben neben "stoppen" - und ist ein Wort,
    # das es gibt. Ein Wort, das es gibt, ist kein Verhoerer.
    for satz in ("der Stopfen", "sie hat das Loch gestopft",
                 "auf dem Feld standen Stoppeln", "aus welchem Stoff"):
        assert stopwort_finden(satz) is None, satz


# --- Das Zeichen, dass er zuhört -------------------------------------------


def test_der_orb_gibt_sofort_ein_zeichen():
    # Gemessen am 19.08.2026: 5,8 s bis der Satz erkannt ist, weitere 6,4 s
    # bis zum ersten Wort. Zwoelf Sekunden Stille - ohne Auskunft darueber,
    # ob er ueberhaupt zuhoert.
    from pathlib import Path

    quelle = Path("backend/voice/voice_pipeline.py").read_text(encoding="utf-8")
    anfang = quelle.index("async def _handle_while_awake")
    ende = quelle.index("async def ", anfang + 10)
    ausschnitt = quelle[anfang:ende]
    # Der Zustandswechsel (und damit der Denk-Klang) muss VOR der
    # Antwortschleife stehen, nicht erst in ihr.
    assert "VoiceState.THINKING" in ausschnitt
    assert ausschnitt.index("VoiceState.THINKING") < ausschnitt.index("_respond")


def test_der_denkklang_ist_hinterlegt():
    # Ohne Datei bleibt es still, und der Zustandswechsel nuetzt nichts.
    from pathlib import Path

    import yaml

    daten = yaml.safe_load(Path("config.yaml").read_text(encoding="utf-8"))
    pfad = daten["voice"]["output"]["thinking_sound"]
    assert pfad, "kein Denk-Klang eingetragen"
    assert Path(pfad).is_file(), f"{pfad} fehlt"


# --- Und warum der Orb sich damit selbst zerriss ---------------------------
#
# Am 19.08.2026, kurz nach dem Aufspielen: "jetzt unterbricht der orb seine
# sätze ständig". Zwei Fehler von mir, beide in derselben Richtung.


def test_ein_langes_fenster_ist_die_eigene_rede():
    # Wer einen sprechenden Orb unterbricht, ruft EIN Wort dazwischen. Was
    # das Mikrofon sonst aufnimmt, ist der Orb. Je mehr Woerter im Fenster
    # stehen, desto sicherer ist es seine Rede.
    lang = "und deshalb war die Julikrise auch für Russland ein stopp Problem"
    assert stopwort_finden(lang) is None


def test_ein_abbruchwort_ganz_hinten_zaehlt_nicht():
    # Ein Zwischenruf beginnt das Fenster, er beschliesst es nicht.
    assert stopwort_finden("das war die Antwort dazu stopp") is None
    assert stopwort_finden("stopp das war die Antwort") == "stopp"


def test_die_unscharfe_pruefung_ist_eng_genug():
    # Vorher gingen 2883 Woerter als "Stopp" durch - gegen neun Formen
    # geprueft, von "astoppen" bis "bchtop". Jetzt nur noch gegen zwei.
    import string

    from backend.voice.stopwort import (
        _KEIN_STOPP,
        _UNSCHARF_BIS,
        _UNSCHARF_GEGEN,
        _UNSCHARF_VON,
        _abstand_eins,
    )

    ziel = set()
    for form in _UNSCHARF_GEGEN:
        for i in range(len(form) + 1):
            for c in string.ascii_lowercase + "äöüß":
                ziel.add(form[:i] + c + form[i:])
                if i < len(form):
                    ziel.add(form[:i] + c + form[i + 1:])
            if i < len(form):
                ziel.add(form[:i] + form[i + 1:])
    ziel = {
        w for w in ziel
        if _UNSCHARF_VON <= len(w) <= _UNSCHARF_BIS and w not in _KEIN_STOPP
    }
    assert len(ziel) < 800, f"zu weit gefasst: {len(ziel)} Woerter"
    assert _abstand_eins("stopt", "stopp")


def test_der_anker_soufflierte_das_abbruchwort():
    # Whisper setzt fort, was im Anker steht. Wer dem Modell "Stopp." als
    # vorangehenden Text vorlegt, bekommt auf jedem undeutlichen Schnipsel
    # ein "Stopp." zurueck - und der Orb zerreisst seinen eigenen Satz.
    from pathlib import Path

    import yaml

    daten = yaml.safe_load(Path("config.yaml").read_text(encoding="utf-8"))
    anker = str(daten["voice"]["stop_initial_prompt"]).lower()
    assert "orb" in anker, "das Weckwort gehoert hinein"
    for verboten in ("stopp", "stop", "halt", "aufhör", "warte", "reicht"):
        assert verboten not in anker, f"{verboten!r} darf nicht im Anker stehen"


def test_ein_unsicheres_fenster_bricht_nichts_ab():
    from pathlib import Path

    quelle = Path("backend/voice/voice_pipeline.py").read_text(encoding="utf-8")
    anfang = quelle.index("async def _check_stop_window")
    ausschnitt = quelle[anfang:quelle.index("def _on_utterance", anfang)]
    assert "_fremd_mindestsicherheit" in ausschnitt
    assert ausschnitt.index("_fremd_mindestsicherheit") < ausschnitt.index(
        "Stop-Wort %r erkannt"
    )
