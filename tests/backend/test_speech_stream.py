"""Tests des Satzstroms - was der Orb sprechen darf, waehrend er noch denkt.

Der Orb bekommt seine Antwort stueckweise. Damit kann er reden, bevor der
letzte Satz gedacht ist. Zwei Dinge duerfen dabei nie passieren:

Er darf nicht mitten im Wort anfangen (die Stuecke sind Silben, keine
Saetze) - und er darf unter keinen Umstaenden einen Werkzeugaufruf
vorlesen. Der steht als eingezaeunter Block in der Antwort, ist
Maschinensprache und dauerte vorgelesen laenger als die Antwort selbst.
"""

from __future__ import annotations

from backend.orchestrator.speech_stream import SpeechStream, remaining_after


def _durchlauf(stuecke: list[str]) -> tuple[list[str], SpeechStream]:
    strom = SpeechStream()
    gesagt: list[str] = []
    for stueck in stuecke:
        gesagt.extend(strom.feed(stueck))
    gesagt.extend(strom.finish())
    return gesagt, strom


def _silben(text: str, breite: int = 3) -> list[str]:
    """Zerhackt einen Text so, wie ein Sprachmodell ihn liefert."""

    return [text[i : i + breite] for i in range(0, len(text), breite)]


def test_saetze_kommen_ganz_oder_gar_nicht():
    gesagt, _ = _durchlauf(_silben("Es ist kalt. Der Wind weht stark. Zieh dich warm an."))
    assert gesagt == [
        "Es ist kalt.",
        "Der Wind weht stark.",
        "Zieh dich warm an.",
    ]


def test_ein_halber_satz_wird_nicht_gesprochen():
    strom = SpeechStream()
    assert strom.feed("Es ist heute ") == []
    assert strom.feed("ziemlich ") == []
    assert strom.feed("kalt") == []
    assert strom.feed(". Und morgen auch") == ["Es ist heute ziemlich kalt."]
    assert strom.finish() == ["Und morgen auch"]


def test_werkzeugblock_wird_nie_gesprochen():
    """Der wichtigste Test der Datei."""

    antwort = (
        "Ich schaue kurz nach.\n"
        "```werkzeug\n"
        '{"werkzeug": "internet_suchen", "argumente": {"frage": "Wetter Bern"}}\n'
        "```\n"
        "Einen Moment noch."
    )
    gesagt, strom = _durchlauf(_silben(antwort))

    zusammen = " ".join(gesagt)
    assert "```" not in zusammen
    assert "werkzeug" not in zusammen
    assert "internet_suchen" not in zusammen
    assert "{" not in zusammen
    assert strom.had_tool_call is True
    assert gesagt == ["Ich schaue kurz nach.", "Einen Moment noch."]


def test_offener_zaun_am_ende_bleibt_stumm():
    """Bricht die Antwort mitten im Block ab, darf nichts davon herausfallen."""

    antwort = 'Ich sehe nach.\n```werkzeug\n{"werkzeug": "bildschirm_lesen"'
    gesagt, strom = _durchlauf(_silben(antwort))

    assert gesagt == ["Ich sehe nach."]
    assert strom.had_tool_call is True


def test_drei_backticks_werden_nie_stueckweise_verraten():
    """Ein einzelner Backtick am Stueckende darf nichts durchlassen.

    Die Stuecke koennen mitten im Zaun enden - "``" im einen, "`" im
    naechsten. Wer da nicht abwartet, liest Backticks vor.
    """

    strom = SpeechStream()
    gesagt: list[str] = []
    for stueck in ["Moment. ", "`", "`", "`", "werkzeug\n{}\n", "`", "`", "`", " Fertig."]:
        gesagt.extend(strom.feed(stueck))
    gesagt.extend(strom.finish())

    assert "`" not in " ".join(gesagt)
    assert gesagt == ["Moment.", "Fertig."]


def test_abkuerzungen_zerreissen_den_satz_nicht():
    gesagt, _ = _durchlauf(
        _silben("Der Kongress von 1815 bzw. die Neuordnung Europas war entscheidend.")
    )
    assert gesagt == [
        "Der Kongress von 1815 bzw. die Neuordnung Europas war entscheidend."
    ]


def test_fragen_und_ausrufe_zaehlen_als_satzende():
    gesagt, _ = _durchlauf(_silben("Wirklich? Ja! Sicher."))
    assert gesagt == ["Wirklich?", "Ja!", "Sicher."]


def test_gesprochenes_wird_mitgeschrieben():
    _, strom = _durchlauf(_silben("Erstens dies. Zweitens das."))
    assert strom.spoken == "Erstens dies. Zweitens das."


def test_leerer_strom_bleibt_still():
    gesagt, strom = _durchlauf([])
    assert gesagt == []
    assert strom.had_tool_call is False


# --- Was nach dem Werkzeug noch zu sprechen ist ------------------------------


def test_rest_nach_gleichem_anfang():
    ganz = "Es ist kalt. Der Wind weht. Zieh dich warm an."
    assert remaining_after("Es ist kalt. Der Wind weht.", ganz) == "Zieh dich warm an."


def test_rest_bei_voellig_neuer_antwort():
    """Nach einem Werkzeugaufruf entsteht meist eine ganz neue Antwort."""

    ganz = "In Bern sind es zwoelf Grad."
    assert remaining_after("Ich schaue kurz nach.", ganz) == ganz


def test_nichts_mehr_uebrig():
    ganz = "Es ist kalt."
    assert remaining_after("Es ist kalt.", ganz) == ""


def test_umbrueche_verschieben_den_vergleich_nicht():
    ganz = "Erster Satz.\n\nZweiter Satz.   Dritter Satz."
    assert remaining_after("Erster Satz. Zweiter Satz.", ganz) == "Dritter Satz."


def test_ohne_gesprochenes_bleibt_alles():
    assert remaining_after("", "Alles hier.") == "Alles hier."
