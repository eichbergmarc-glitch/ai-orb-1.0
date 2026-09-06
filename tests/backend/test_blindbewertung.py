"""Prüft die Blindbewertung - vor allem darauf, dass sie wirklich blind ist.

Der wichtigste Test ist ``test_die_sicht_verraet_die_herkunft_nicht``: Er
nimmt zwei Antworten, die absichtlich voller Hinweise stecken, und belegt
an genau dem Text, den der Bewerter zu sehen bekommt, dass nichts davon
übrig bleibt. Alles andere wäre eine Prüfung der Absicht statt der
Umsetzung.
"""

from __future__ import annotations

import pytest

from backend.lernen.blindbewertung import (
    MASKE,
    UNMOEGLICH,
    auswertbare,
    URTEILSANWEISUNG,
    Befangen,
    Vergleichsfall,
    modellurteiler,
    vergleichsreihe,
    Blindurteil,
    Kandidat,
    blind_bewerten,
    gleichwertigkeitsquote,
    lecks_finden,
    maskieren,
    vorlage_bauen,
)


def _lehrer(text: str) -> Kandidat:
    return Kandidat(herkunft="lehrer", text=text, werkzeuge=("suchen",))


def _schueler(text: str) -> Kandidat:
    return Kandidat(herkunft="schueler", text=text, werkzeuge=())


# --- Die Leckprüfung ------------------------------------------------------


def test_die_sicht_verraet_die_herkunft_nicht():
    """Der zentrale Nachweis: was der Bewerter sieht, ist leckfrei."""

    verraeterisch_lehrer = (
        "Ich bin Claude, ein grosses Sprachmodell von Anthropic (Sonnet). "
        "Ich wurde von Anthropic trainiert. Mein Wissensstand endet im Mai. "
        "Die Antwort lautet: Bern ist die Bundesstadt."
    )
    verraeterisch_schueler = (
        "Als KI-Assistent, laufend auf Ollama mit einem Llama-Modell im "
        "AI-Orb, sage ich: Bern ist die Bundesstadt. Modellversion 3.1."
    )

    vorlage = vorlage_bauen(
        kennung="vergleich-1",
        aufgabe="Was ist die Bundesstadt der Schweiz?",
        erster=_lehrer(verraeterisch_lehrer),
        zweiter=_schueler(verraeterisch_schueler),
    )

    sicht = vorlage.sicht()

    # Die Prüfung am Text selbst, nicht am Versprechen.
    assert lecks_finden(sicht) == [], f"Leck in der Sicht: {lecks_finden(sicht)}"
    # Und stichprobenartig die auffälligsten Wörter direkt.
    for wort in ("claude", "anthropic", "sonnet", "ollama", "llama", "ai-orb"):
        assert wort not in sicht.lower()
    # Die Sache selbst muss stehen bleiben, sonst maskiert man die Antwort weg.
    assert "Bundesstadt" in sicht
    assert MASKE in sicht


def test_die_sicht_zeigt_keine_werkzeuginformation():
    """An der Werkzeugliste liesse sich der Schüler erkennen."""

    vorlage = vorlage_bauen(
        kennung="vergleich-werkzeug",
        aufgabe="Wie spät ist es?",
        erster=Kandidat("lehrer", "Es ist 14 Uhr.", ("aktuelle_zeit", "rechnen")),
        zweiter=Kandidat("schueler", "Es ist 14 Uhr.", ()),
    )
    sicht = vorlage.sicht()
    assert "aktuelle_zeit" not in sicht
    assert "rechnen" not in sicht
    assert "werkzeug" not in sicht.lower()


def test_die_sicht_nennt_weder_herkunft_noch_reihenfolge():
    """Weder das Feld ``herkunft`` noch ``a_war_erster`` darf durchsickern."""

    vorlage = vorlage_bauen(
        kennung="vergleich-2",
        aufgabe="Nenne eine Primzahl.",
        erster=_lehrer("Sieben."),
        zweiter=_schueler("Elf."),
    )
    sicht = vorlage.sicht()
    assert "lehrer" not in sicht.lower()
    assert "schueler" not in sicht.lower()
    assert "erster" not in sicht.lower()
    assert "kennung" not in sicht.lower()
    assert "vergleich-2" not in sicht


def test_der_bewerter_bekommt_ausschliesslich_die_sicht():
    """Der Aufrufvertrag: ein Argument, und das ist der maskierte Text."""

    gesehen: list[str] = []

    def urteiler(text: str) -> tuple[str, str]:
        gesehen.append(text)
        return "A", "A ist knapper."

    vorlage = vorlage_bauen(
        kennung="vergleich-3",
        aufgabe="Erkläre Photosynthese.",
        erster=_lehrer("Pflanzen wandeln Licht in Zucker um. Claude erklärt das gern."),
        zweiter=_schueler("Licht wird zu Zucker."),
    )
    blind_bewerten(vorlage, urteiler)

    assert len(gesehen) == 1
    assert gesehen[0] == vorlage.sicht()
    assert lecks_finden(gesehen[0]) == []


def test_lecks_finden_erkennt_was_maskieren_entfernt():
    """Prüfstein und Werkzeug müssen zueinander passen."""

    roh = "Ich bin ein Sprachmodell namens GPT von OpenAI."
    assert lecks_finden(roh), "der Prüfstein erkennt gar nichts"
    assert lecks_finden(maskieren(roh)) == []


def test_lecks_finden_meldet_keine_falschen_treffer():
    """Ein harmloser Satz darf nicht als Leck gelten."""

    assert lecks_finden("Bern ist die Bundesstadt der Schweiz.") == []
    assert maskieren("Bern ist die Bundesstadt.") == "Bern ist die Bundesstadt."


# --- Das Losverfahren -----------------------------------------------------


def test_dieselbe_kennung_ergibt_dieselbe_zuteilung():
    """Reproduzierbar: ein Nachprüfer kommt auf dieselbe Zuordnung."""

    def bauen():
        return vorlage_bauen(
            kennung="stets-gleich",
            aufgabe="Aufgabe",
            erster=_lehrer("L"),
            zweiter=_schueler("S"),
        )

    erste, zweite = bauen(), bauen()
    assert erste.a.herkunft == zweite.a.herkunft
    assert erste.a_war_erster == zweite.a_war_erster


def test_die_zuteilung_streut_ueber_die_kennungen():
    """Nicht ausrechenbar aus der Aufrufreihenfolge: beide Lagen kommen vor."""

    lagen = set()
    for nummer in range(200):
        vorlage = vorlage_bauen(
            kennung=f"vergleich-{nummer}",
            aufgabe="Aufgabe",
            erster=_lehrer("L"),
            zweiter=_schueler("S"),
        )
        lagen.add(vorlage.a.herkunft)
    assert lagen == {"lehrer", "schueler"}


def test_die_zuteilung_ist_ungefaehr_ausgeglichen():
    """Ein Los, das zu 90 % dasselbe zieht, wäre keines."""

    lehrer_auf_a = sum(
        1
        for nummer in range(400)
        if vorlage_bauen(
            kennung=f"lauf-{nummer}",
            aufgabe="Aufgabe",
            erster=_lehrer("L"),
            zweiter=_schueler("S"),
        ).a.herkunft
        == "lehrer"
    )
    assert 140 <= lehrer_auf_a <= 260, f"unausgeglichen: {lehrer_auf_a} von 400"


# --- Die Auflösung --------------------------------------------------------


def test_die_aufloesung_folgt_der_zuteilung():
    vorlage = vorlage_bauen(
        kennung="aufloesung",
        aufgabe="Aufgabe",
        erster=_lehrer("L"),
        zweiter=_schueler("S"),
    )
    assert vorlage.aufloesen("A") == vorlage.a.herkunft
    assert vorlage.aufloesen("B") == vorlage.b.herkunft
    assert vorlage.aufloesen("gleich") == ""


def test_das_urteil_traegt_die_herkunft_erst_nach_dem_etikett():
    """Der Bewerter nennt ein Etikett; die Herkunft setzt erst der Code."""

    vorlage = vorlage_bauen(
        kennung="urteil-1",
        aufgabe="Aufgabe",
        erster=_lehrer("L"),
        zweiter=_schueler("S"),
    )
    urteil = blind_bewerten(vorlage, lambda _text: ("B", "B ist genauer."))
    assert urteil.besser == "B"
    assert urteil.gewinner_herkunft == vorlage.b.herkunft
    assert urteil.gewinner_herkunft in {"lehrer", "schueler"}


def test_ein_ausgesprochener_gleichstand_zaehlt_als_gleichstand():
    for wort in ("gleich", "Gleichwertig", "unentschieden"):
        vorlage = vorlage_bauen(
            kennung="urteil-2", aufgabe="A", erster=_lehrer("L"), zweiter=_schueler("S")
        )
        urteil = blind_bewerten(vorlage, lambda _t, w=wort: (w, "kein Unterschied."))
        assert urteil.besser == "gleich", wort
        assert urteil.gewinner_herkunft == ""


def test_ein_unbrauchbares_etikett_ist_kein_gleichstand():
    """Das vierte Ergebnis: Der Bewerter hat geantwortet, aber nicht geurteilt.

    Es als Gleichstand zu zaehlen waere die bequeme Luege - ein Stapel
    unlesbarer Urteile duerfte sonst eine Uebergabe rechtfertigen.
    """

    vorlage = vorlage_bauen(
        kennung="urteil-2b", aufgabe="A", erster=_lehrer("L"), zweiter=_schueler("S")
    )
    urteil = blind_bewerten(vorlage, lambda _t: ("weiss nicht so recht", "hm"))

    assert urteil.besser == UNMOEGLICH
    assert urteil.gewinner_herkunft == ""


def test_ein_gescheiterter_bewerter_reisst_nichts_und_gilt_als_unmoeglich():
    def kaputt(_text: str) -> tuple[str, str]:
        raise RuntimeError("Modell nicht erreichbar")

    vorlage = vorlage_bauen(
        kennung="urteil-3", aufgabe="A", erster=_lehrer("L"), zweiter=_schueler("S")
    )
    urteil = blind_bewerten(vorlage, kaputt)

    assert urteil.besser == UNMOEGLICH
    assert "gescheitert" in urteil.begruendung
    assert auswertbare([urteil]) == []


# --- Die Quote ------------------------------------------------------------


def test_gleichwertigkeitsquote_zaehlt_gleichstand_mit():
    urteile = [
        Blindurteil("1", "A", "", "schueler"),
        Blindurteil("2", "gleich", "", ""),
        Blindurteil("3", "B", "", "lehrer"),
        Blindurteil("4", "A", "", "lehrer"),
    ]
    assert gleichwertigkeitsquote(urteile, schueler="schueler") == pytest.approx(0.5)


def test_gleichwertigkeitsquote_ohne_urteile_ist_null():
    assert gleichwertigkeitsquote([], schueler="schueler") == 0.0


# --- Der Modellbewerter ---------------------------------------------------


def test_ein_teilnehmer_darf_nicht_bewerten():
    """Die Befangenheitsschranke ist ein Abbruch, keine Warnung."""

    with pytest.raises(Befangen):
        modellurteiler(
            lambda _text: "URTEIL: A\nGRUND: weil.",
            bewerter="ollama",
            teilnehmer=("claude_code", "ollama"),
        )


def test_ein_unbeteiligter_bewerter_ist_erlaubt():
    urteiler = modellurteiler(
        lambda _text: "URTEIL: B\nGRUND: B ist vollständiger.",
        bewerter="dritter",
        teilnehmer=("claude_code", "ollama"),
    )
    assert urteiler("irgendeine Sicht") == ("B", "B ist vollständiger.")


def test_der_modellbewerter_sieht_nur_anweisung_und_sicht():
    gesehen: list[str] = []

    def fragen(text: str) -> str:
        gesehen.append(text)
        return "URTEIL: gleich\nGRUND: kein Unterschied."

    urteiler = modellurteiler(
        fragen, bewerter="dritter", teilnehmer=("lehrer", "schueler")
    )
    vorlage = vorlage_bauen(
        kennung="modell-1",
        aufgabe="Nenne die Hauptstadt.",
        erster=_lehrer("Ich bin Claude. Bern."),
        zweiter=_schueler("Bern, sagt Ollama."),
    )
    urteil = blind_bewerten(vorlage, urteiler)

    assert urteil.besser == "gleich"
    assert len(gesehen) == 1
    assert gesehen[0].startswith(URTEILSANWEISUNG)
    assert lecks_finden(gesehen[0].replace(URTEILSANWEISUNG, "")) == []


def test_eine_unlesbare_bewerterantwort_ist_technisch_kein_urteil():
    urteiler = modellurteiler(
        lambda _t: "Ich finde beide gut.", bewerter="dritter", teilnehmer=("a", "b")
    )
    vorlage = vorlage_bauen(
        kennung="modell-2", aufgabe="A", erster=_lehrer("L"), zweiter=_schueler("S")
    )
    assert blind_bewerten(vorlage, urteiler).besser == UNMOEGLICH


def test_lauter_unmoegliche_urteile_ergeben_keine_gute_quote():
    """Der eigentliche Riegel: ein kaputter Bewerter darf nichts belegen."""

    urteile = [
        Blindurteil(f"u-{n}", UNMOEGLICH, "Bewerter gescheitert", "")
        for n in range(9)
    ] + [Blindurteil("u-9", "gleich", "gleichwertig", "")]

    assert gleichwertigkeitsquote(urteile, schueler="schueler") == pytest.approx(0.1)
    assert len(auswertbare(urteile)) == 1


def test_die_vergleichsreihe_liefert_die_quote_aus_einzelurteilen():
    faelle = [
        Vergleichsfall(f"fall-{n}", "Aufgabe", _lehrer("L"), _schueler("S"))
        for n in range(6)
    ]
    # Ein Bewerter, der stets das Etikett A waehlt. Weil die Zuteilung
    # streut, muss die Quote irgendwo dazwischen landen - haetten wir
    # nicht gelost, waere sie 0 oder 1.
    urteile, quote = vergleichsreihe(
        faelle, lambda _t: ("A", "A."), schueler="schueler"
    )
    assert len(urteile) == 6
    assert all(u.gewinner_herkunft in {"lehrer", "schueler"} for u in urteile)
    assert 0.0 < quote < 1.0


def test_die_vergleichsreihe_zaehlt_gleichstaende_als_gleichwertig():
    faelle = [
        Vergleichsfall(f"g-{n}", "Aufgabe", _lehrer("L"), _schueler("S"))
        for n in range(4)
    ]
    _urteile, quote = vergleichsreihe(
        faelle, lambda _t: ("gleich", "kein Unterschied."), schueler="schueler"
    )
    assert quote == 1.0
