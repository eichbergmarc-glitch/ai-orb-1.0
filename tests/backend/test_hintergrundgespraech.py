"""Bin ich gemeint? - Anrede gegen Hintergrundgespräch.

Der Anlass steht im Protokoll vom 17.08.2026. Nach einer Antwort hört der
Orb 45 Sekunden weiter zu, ohne dass man ihn erneut weckt - und in diesem
Fenster galt bisher ALLES als Anweisung::

    13:40:12  "Ihr seid, wenn ihr sich etwas spürtzuschreifen ..."
    13:40:51  "Vielen Dank."
    13:41:12  "Die Kirchenweine und Schachtwäsche."
    13:42:07  "Ja, und in Spannung von dem Ding, was wir haben, was wir
               haben, was wir haben ..."

Nichts davon war an den Orb gerichtet: ein Gespräch im Raum, ein
Fernseher, seine eigene Lautsprecherstimme. Diese Tests halten fest, dass
er so etwas erkennt und schweigt - und dass er umgekehrt keinen echten
Auftrag verschluckt. Die Sätze unten sind echte Protokollzeilen, keine
erfundenen Beispiele.
"""

from __future__ import annotations

import pytest

from backend.voice.gespraechsrichtung import einschaetzen


def test_tagebucheintrag_ist_auch_ohne_weckwort_ein_eindeutiger_befehl():
    urteil = einschaetzen("Tagebucheintrag", sicherheit=0.9)

    assert urteil.antworten
    assert urteil.art == "an_mich"


def test_tagebuchbild_ist_auch_ohne_weckwort_ein_eindeutiger_befehl():
    assert einschaetzen("Bild ins Tagebuch", sicherheit=0.9).antworten


def test_reale_whisper_fehlform_bleibt_ein_tagebuchauftrag():
    urteil = einschaetzen(
        "Alle Orte bestellen einen neuen Tagebucheintrag.", sicherheit=0.93
    )

    assert urteil.antworten


# --- Was NICHT an den Orb gerichtet war (echte Protokollzeilen) -------------


@pytest.mark.parametrize(
    "satz, sicherheit",
    [
        ("Vielen Dank.", 0.77),
        ("Die Kirchenweine und Schachtwäsche.", 0.82),
        ("Ihr seid, wenn ihr sich etwas spürtzuschreifen wie Spurgegenteil", 0.80),
        ("Das heißt, wir machen das, was wir tun, was wir tun, was wir tun, "
         "was wir tun.", 0.81),
        ("Ja, und in Spannung von dem Ding, was wir haben, ist eine Weine. "
         "Und dann war es nicht so, was wir haben. Und dann war es nicht so, "
         "was wir haben.", 0.82),
        ("Sollte.", 0.79),
        ("Ja genau", 0.9),
        ("Ach so", 0.88),
    ],
)
def test_hintergrundgespraech_wird_erkannt(satz, sicherheit):
    urteil = einschaetzen(satz, sicherheit=sicherheit)
    assert not urteil.antworten, f"haette schweigen muessen: {urteil.grund}"


# --- Was sehr wohl an den Orb gerichtet war --------------------------------


@pytest.mark.parametrize(
    "satz",
    [
        "Hallo Orb, gib mir die News des Tages zusammengefasst",
        "Was machst du gerade?",
        "Wie geht es dir gerade?",
        "Kannst du mich jetzt verstehen?",
        "Suche einmal nach dem Philosophen Markus Gabriel",
        "Trag mir morgen um 14 Uhr den Zahnarzt ein",
        "Erklär mir bitte die Julikrise",
        "Eigne dir das Wissen über Emmy Noether an",
        "Lies mir die Nachrichten vor",
        "Stopp",
        "Weiter",
        "Fahre fort mit der Vorlesung",
        "Mache weiter mit der Vorlesung über Mesopotamien",
        "Halte mir eine Vorlesung über Sprachwissenschaft",
        "Was steht heute an?",
    ],
)
def test_eine_echte_anrede_kommt_durch(satz):
    urteil = einschaetzen(satz, sicherheit=0.9)
    assert urteil.antworten, f"haette antworten muessen: {urteil.grund}"


def test_der_eigene_name_schlaegt_alles():
    # Auch bei maessiger Erkennung und mitten im Satz: Wer "Orb" sagt,
    # meint den Orb.
    urteil = einschaetzen("also Orb das mit dem Ding da", sicherheit=0.55)
    assert urteil.antworten
    assert "Name" in urteil.grund


# --- Der Anschluss an eine eigene Rückfrage --------------------------------


def test_ein_ja_zaehlt_nur_nach_einer_rueckfrage():
    # "Ja" nach einer eigenen Rueckfrage des Orb ist die Antwort darauf.
    an_mich = einschaetzen("Ja, mach das", sicherheit=0.9, wurde_gefragt=True)
    assert an_mich.antworten

    # Dasselbe "Ja" ohne offene Rueckfrage ist Gespraech im Raum.
    im_raum = einschaetzen("Ja, mach das", sicherheit=0.9, wurde_gefragt=False)
    assert not im_raum.antworten
    assert "Rückfrage" in im_raum.grund


def test_andere_adressaten_schliessen_den_orb_aus():
    for satz in ("Ihr habt das doch gesehen", "Wir müssen dann los",
                 "Schatz, kommst du?"):
        urteil = einschaetzen(satz, sicherheit=0.95)
        assert not urteil.antworten, satz
        assert not urteil.antworten


# --- Die Grenzfälle --------------------------------------------------------


def test_wortschleifen_sind_nie_eine_anrede():
    from backend.voice.gespraechsrichtung import _ist_geplapper

    assert _ist_geplapper("das ist das, das ist das, das ist das, das ist das")
    assert not _ist_geplapper("Erklär mir bitte die Grundzüge der Quantenmechanik")


def test_im_zweifel_wird_geschwiegen_nicht_geraten():
    # Klar verstanden, aber ohne Anrede, Frage oder Auftrag: 'unklar' -
    # und 'unklar' heisst schweigen. Ein uebersehener Auftrag kostet eine
    # Wiederholung, eine Antwort auf ein fremdes Gespraech kostet
    # Vertrauen.
    urteil = einschaetzen("Der Zug fährt um zehn nach drei", sicherheit=0.95)
    assert urteil.art == "unklar"
    assert not urteil.antworten


def test_jedes_urteil_nennt_seinen_grund():
    # Der Grund steht im Protokoll. Ohne ihn waere spaeter nicht
    # nachvollziehbar, warum der Orb geschwiegen hat - und genau das
    # muesste man dann wieder muehsam suchen.
    for satz in ("Vielen Dank.", "Was machst du?", "Der Zug faehrt gleich"):
        urteil = einschaetzen(satz, sicherheit=0.9)
        assert urteil.grund and len(urteil.grund) > 8
        assert urteil.art in ("an_mich", "hintergrund", "unklar")


def test_die_pipeline_fragt_wirklich_nach_der_richtung():
    # Das Urteil nuetzt nichts, wenn es niemand einholt - genau so ist
    # frueher schon eine fertige Maschinerie unerreichbar geblieben.
    from pathlib import Path

    quelle = Path("backend/voice/voice_pipeline.py").read_text(encoding="utf-8")
    anfang = quelle.index("async def _handle_while_awake")
    ausschnitt = quelle[anfang:anfang + 4000]
    assert "gespraechsrichtung" in ausschnitt
    assert "richtung.antworten" in ausschnitt
    assert "_wartet_auf_antwort" in ausschnitt


# --- Die zwei Lücken vom 18.08.2026 ----------------------------------------
#
# An diesem Tag lief eine fremde Stimme mit. Zwei ihrer Sätze kamen durch,
# wurden beantwortet und blieben im Gesprächsverlauf stehen - und von da
# an bezog sich jede weitere Antwort auf sie. Der Benutzer beschrieb es
# als "hat angefangen zu halluzinieren und nicht mehr aufgehört".

_FREMDE_STIMME_1 = (
    "Nachwägung, Konkunft, Sekundism. Ja, ja, das ist aber eine Unwahrung, "
    "die Konflikation, die wir als Bewusstsein stattfinden, etwas, was die "
    "meisten Menschen, dann würden wir als Reparativen sagen. Ich kann ja "
    "nicht erklären, wie das funktioniert, aber die Unwahrung gegen das "
    "Patienten ist eine solche Form der Konflikation. Das ist vorallem wie "
    "ein Bergungsantrag."
)

_FREMDE_STIMME_2 = (
    "Das ist unverteidigbar, wenn ein Schwierigem was ähnlich ist, weil sie "
    "sich nicht nur umgegnenen, sie sich abschärben und auch den Antrags "
    "vorbachen. Wie das funktioniert, oder was genau dahinter steht, weiß "
    "ich selbst. Und ich finde, dass ich auch immer wieder, wie ich als "
    "Südpaulinsist, Hallo Orb!"
)


def test_infinitiv_mitten_im_satz_ist_kein_befehl():
    # Der erste Satz galt als "Befehlsform", weil die Prüfung nach der
    # Zeichenkette " erklär" suchte - die steckt auch in "erklären".
    urteil = einschaetzen(_FREMDE_STIMME_1, sicherheit=0.81)
    assert not urteil.antworten, urteil.grund


@pytest.mark.parametrize(
    "satz",
    [
        "Ich kann ja nicht erklären, wie das funktioniert",
        "Wir müssten das nochmal zusammenfassen und dann sehen",
        "Da wollte er noch die Unterlagen suchen",
        "Und nun kommt ein besonderes Problem, das ist das Ding",
        "Die Zahlen sagen etwas anderes",
    ],
)
def test_ein_verb_ohne_befehlsstellung_zaehlt_nicht(satz):
    assert not einschaetzen(satz, sicherheit=0.9).antworten, satz


def test_der_name_ganz_am_ende_einer_langen_fremden_rede_zaehlt_nicht():
    # Whisper hängt vertraute Wendungen an, wenn der Ton am Schluss
    # zerfällt - "Hallo Orb" ist die vertrauteste, die dieses Mikrofon
    # kennt. Fünfzig Wörter fremde Rede werden dadurch keine Anrede.
    urteil = einschaetzen(_FREMDE_STIMME_2, sicherheit=0.82)
    assert not urteil.antworten
    assert "Ende" in urteil.grund


def test_der_name_am_ende_einer_kurzen_aeusserung_zaehlt_sehr_wohl():
    for satz in ("Hallo Orb!", "Zeig mir bitte die Nachrichten, Orb",
                 "Kurze Frage an dich, Orb"):
        assert einschaetzen(satz, sicherheit=0.9).antworten, satz


@pytest.mark.parametrize(
    "satz",
    [
        # Echte Aufträge aus demselben Protokoll, die vorher fälschlich
        # als Hintergrund galten.
        "Erweitere dein Wissen über Markus Gabriel.",
        "Optimiere deine Funktionsweise und deine Leistung.",
        "Führe eine Fehleranalyse durch, warum deine Funktionen nicht laufen.",
        "Wechsel auf das Modell Ollama.",
        "Du wolltest mir noch die Bilder zeigen von der humanoiden KI.",
        "Ich warte immer noch auf die Bilder, von denen du mir erzählt hast.",
        "Ich möchte vor allem Bilder zu den Weltbränden.",
        "Ich brauche kein PrintScreen, sondern die Lösung der Aufgabe.",
        "Versuche es erneut, finde den Fehler.",
    ],
)
def test_echte_auftraege_aus_dem_protokoll_kommen_durch(satz):
    urteil = einschaetzen(satz, sicherheit=0.93)
    assert urteil.antworten, f"haette antworten muessen: {urteil.grund}"


def test_auch_der_weckruf_wird_auf_die_richtung_geprueft():
    # Sonst weckt ein "Hallo Orb" am Ende fremder Rede den Orb - und
    # danach steht das Nachfragefenster 45 Sekunden offen.
    from pathlib import Path

    quelle = Path("backend/voice/voice_pipeline.py").read_text(encoding="utf-8")
    anfang = quelle.index("async def _handle_while_asleep")
    ausschnitt = quelle[anfang:anfang + 2500]
    assert "gespraechsrichtung" in ausschnitt
    assert "richtung.antworten" in ausschnitt


# --- Die Lücke vom 19.08.2026: der abgeschnittene Name ---------------------
#
# Im wachen Zustand wird ein erneutes Weckwort abgeschnitten, bevor die
# Frage an die KI geht. Die Richtungsprüfung bekam dadurch einen Text, aus
# dem die Anrede gerade entfernt worden war - und schwieg. Fünfmal
# hintereinander, bei fünfmal demselben Auftrag.


@pytest.mark.parametrize(
    "satz",
    [
        # Genau die Sätze aus dem Protokoll, jeweils OHNE das
        # abgeschnittene "Hallo Orb" - so, wie die Prüfung sie sah.
        "genau dieses dokument sollst du einlesen bitte",
        "Genau dieses Dokument und dem Ordner Downloads sollst du einlesen, bitte.",
        "die aufgabe ist klar an dich gerichtet dieses dokument sollst du einlesen",
        "auftrag an dich dieses dokument und dem ordnetownloads einlesen",
        "Hörst du einlesen, genau dieses Dokument hörst du einlesen bitte.",
    ],
)
def test_die_auftraege_vom_19_08_kommen_durch(satz):
    urteil = einschaetzen(satz, sicherheit=0.94)
    assert urteil.antworten, f"haette antworten muessen: {urteil.grund}"


def test_die_zweite_person_zaehlt_in_beiden_stellungen():
    from backend.voice.gespraechsrichtung import _du_in_aussagestellung

    # Gerade Stellung ...
    assert _du_in_aussagestellung(" du hast mir das erzählt ")
    # ... und Umkehrung.
    assert _du_in_aussagestellung(" das sollst du einlesen ")
    assert _du_in_aussagestellung(" hörst du mir zu ")
    # Ein Hauptwort auf -st ist keine Verbform.
    assert not _du_in_aussagestellung(" du und der rest ist egal ")


def test_ein_gefallenes_weckwort_hebelt_die_pruefung_aus():
    # Wer den Orb beim Namen ruft, meint ihn - und der Name steht nach dem
    # Abschneiden nicht mehr im Text, den die Pruefung sieht.
    from pathlib import Path

    quelle = Path("backend/voice/voice_pipeline.py").read_text(encoding="utf-8")
    anfang = quelle.index("async def _handle_while_awake")
    ausschnitt = quelle[anfang:anfang + 4500]
    assert "weckwort_gefallen" in ausschnitt
    assert "not weckwort_gefallen" in ausschnitt
    # Und die Ermittlung muss VOR dem Abschneiden stehen.
    assert ausschnitt.index("weckwort_gefallen =") < ausschnitt.index("strip_wake_word")


# --- Die vierte Luecke: die Antwort auf die eigene Frage (20.08.2026) --------
#
# Der Benutzer meldete wiederkehrend verschluckte Saetze im Wachfenster.
# Das Protokoll bestaetigte es - die Stimme kam durch (Erkennung 0.91),
# verworfen hat die Richtungspruefung. Die Saetze unten sind die echten
# Protokollzeilen vom 20.08., 03:12 bis 04:35.


@pytest.mark.parametrize(
    "satz",
    [
        "Ja, bitte, tu das.",                                   # 04:35:36
        "Ja, wenn das reicht, bin ich genau die Danke.",        # 04:27:11
        "Vielen Dank, das passt so.",
    ],
)
def test_nach_eigener_frage_zaehlt_die_antwort(satz):
    urteil = einschaetzen(satz, sicherheit=0.91, wurde_gefragt=True)
    assert urteil.antworten, f"Antwort auf die eigene Frage verworfen: {urteil.grund}"


def test_ohne_offene_frage_bleibt_die_zustimmung_hintergrund():
    """Das Gegenstueck: Dieselben Worte ohne offene Frage sind weiter
    Zustimmung in einem Gespraech, das dem Orb nicht galt."""

    urteil = einschaetzen("Ja, wenn das reicht, bin ich genau die Danke.",
                          sicherheit=0.91, wurde_gefragt=False)
    assert not urteil.antworten


def test_auch_nach_eigener_frage_zaehlt_fremde_rede_nicht():
    """Die offene Frage hebelt die Adressaten- und Schleifenpruefung
    NICHT aus - ein Gespraech mit Dritten bleibt Hintergrund."""

    mit_dritten = einschaetzen("Ja, aber ihr habt das doch gestern besprochen.",
                               sicherheit=0.9, wurde_gefragt=True)
    assert not mit_dritten.antworten

    schleife = einschaetzen("was wir haben, was wir haben, was wir haben, "
                            "was wir haben, was wir haben",
                            sicherheit=0.9, wurde_gefragt=True)
    assert not schleife.antworten


def test_unsicheres_bleibt_auch_nach_eigener_frage_draussen():
    urteil = einschaetzen("Ja, und in Spannung von dem Ding.",
                          sicherheit=0.45, wurde_gefragt=True)
    assert not urteil.antworten


@pytest.mark.parametrize(
    "satz",
    [
        "Erzählen wir etwas über den neuen Realismus nach Markus Gabriel.",  # 04:24:58
        "Erzählen wir das über den neuen Realismus.",                        # 03:12:29
        "Machen wir weiter.",
        "Fangen wir mit der Julikrise an.",
        "Schauen wir uns die Gesteine an.",
    ],
)
def test_der_wir_imperativ_ist_ein_auftrag(satz):
    urteil = einschaetzen(satz, sicherheit=0.9)
    assert urteil.antworten, f"Wir-Imperativ verworfen: {urteil.grund}"


@pytest.mark.parametrize(
    "satz",
    [
        "Das heißt, wir machen das schon seit Jahren.",
        "Und dann haben wir das besprochen.",
        "Ja, und in Spannung von dem Ding, was wir haben.",
    ],
)
def test_wir_in_aussagestellung_bleibt_hintergrund(satz):
    urteil = einschaetzen(satz, sicherheit=0.85)
    assert not urteil.antworten, f"Aussage mit 'wir' galt als Auftrag: {urteil.grund}"


def test_tu_das_ist_ein_befehl_auch_ohne_offene_frage():
    urteil = einschaetzen("Tu das bitte gleich.", sicherheit=0.9)
    assert urteil.antworten


def test_ja_bitte_zaehlt_trotz_kommas_als_anschluss():
    """Whisper setzt Kommas nach Laune: 'Ja, bitte' und 'ja bitte' sind
    dieselbe Antwort und muessen gleich behandelt werden."""

    urteil = einschaetzen("Ja, bitte.", sicherheit=0.9, wurde_gefragt=True)
    assert urteil.antworten
    assert "Rückfrage" in urteil.grund or "Frage" in urteil.grund


def test_die_eigene_frage_setzt_das_wartezeichen():
    """Die Verdrahtung: Endet die eigene Rede mit '?', wartet der Orb auf
    die Antwort - endet sie ohne, faellt das Zeichen zurueck."""

    from pathlib import Path

    quelle = Path("backend/voice/voice_pipeline.py").read_text(encoding="utf-8")
    stelle = quelle.find("gesprochen = await self._say_locked")
    assert stelle > 0, "die Sprechsperre um _say_locked fehlt"
    danach = quelle[stelle : stelle + 900]
    assert "_wartet_auf_antwort" in danach, (
        "die eigene Rede setzt das Wartezeichen nicht mehr"
    )
    assert 'endswith("?")' in danach
