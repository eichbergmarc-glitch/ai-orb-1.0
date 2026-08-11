"""Tests des Themenwissens.

Es gab schon ein Werkzeug namens `wissen_aneignen`, und es war
angeschlossen. Was es tat, war trotzdem kein Lernen: Es las die Quellen,
gab den gelesenen Text in die eine Antwort - und legte im Gedaechtnis nur
die Trefferzeile der Suchmaschine ab. Titel, ein Satz, ein Link.

Der erste Test hier haelt genau das fest: Gespeichert wird die SUBSTANZ.
Er ist der wichtigste, weil ein Werkzeug, das etwas Falsches speichert,
von aussen aussieht wie eines, das funktioniert - man merkt es erst eine
Woche spaeter, wenn man nachfragt und eine Linkliste bekommt.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from backend.learning.themenlerner import Themenlerner, _json_aus
from backend.learning.themenwissen import Aussage, Thema, Themenspeicher


class _Anbieter:
    """Ein Anbieter, der eine vorbereitete Antwort liefert."""

    def __init__(self, antwort: str):
        self.antwort = antwort
        self.gefragt: list[str] = []
        self.systemprompts: list[str] = []

    async def complete(self, prompt, *, system_prompt="", **kw):
        self.gefragt.append(prompt)
        self.systemprompts.append(system_prompt)
        return self.antwort


class _Gedaechtnis:
    def __init__(self):
        self.eintraege: list[dict] = []

    def remember(self, inhalt, *, kind="knowledge", tags=None, source=None,
                 certainty="fakt", **kw):
        self.eintraege.append(
            {"inhalt": inhalt, "kind": kind, "tags": tags, "source": source}
        )
        return True


def _antwort(aussagen, fragen=None):
    return json.dumps(
        {"aussagen": aussagen, "offene_fragen": fragen or []}, ensure_ascii=False
    )


def _lerner(tmp_path, antwort, gedaechtnis=None):
    speicher = Themenspeicher(tmp_path / "themen")
    return (
        Themenlerner(
            speicher=speicher,
            provider_manager=_Anbieter(antwort),
            memory=gedaechtnis,
        ),
        speicher,
    )


# --- Was gespeichert wird ---------------------------------------------------------


def test_gespeichert_wird_die_substanz_und_nicht_der_fundort(tmp_path: Path):
    """Der Test, der gefehlt hat.

    Vorher landete im Gedaechtnis: "Thema: Titel - Kurzbeschreibung
    (Quelle: URL)". Das ist ein Lesezeichen. Jetzt muss die Aussage selbst
    darin stehen.
    """

    gedaechtnis = _Gedaechtnis()
    lerner, speicher = _lerner(
        tmp_path,
        _antwort([
            {
                "text": "Der Westfaelische Friede von 1648 beendete den "
                        "Dreissigjaehrigen Krieg.",
                "quelle": "https://beispiel.org/a",
                "sicherheit": "fakt",
            }
        ]),
        gedaechtnis,
    )

    thema = Thema(name="Dreissigjaehriger Krieg")
    asyncio.run(lerner._einarbeiten(thema, [("https://beispiel.org/a", "x" * 400)]))

    gespeichert = speicher.laden("Dreissigjaehriger Krieg")
    assert len(gespeichert.aussagen) == 1
    assert "1648" in gespeichert.aussagen[0].text
    assert gespeichert.aussagen[0].quelle == "https://beispiel.org/a"

    # Und dasselbe im Langzeitgedaechtnis - sonst faende es die
    # Erinnerungssuche nie.
    assert gedaechtnis.eintraege, "nichts ins Gedaechtnis uebernommen"
    assert "1648" in gedaechtnis.eintraege[0]["inhalt"]


def test_bruchstuecke_werden_abgewiesen(tmp_path: Path):
    """"1945" oder "siehe oben" spaeter wieder herauszusuchen kostet mehr,
    als sie einbringen."""

    lerner, speicher = _lerner(
        tmp_path,
        _antwort([
            {"text": "1648", "quelle": "u"},
            {"text": "siehe oben", "quelle": "u"},
            {"text": "Der Krieg dauerte von 1618 bis 1648 an.", "quelle": "u"},
        ]),
    )

    thema = Thema(name="Krieg")
    asyncio.run(lerner._einarbeiten(thema, [("u", "x" * 400)]))

    gespeichert = speicher.laden("Krieg")
    assert len(gespeichert.aussagen) == 1
    assert "1618" in gespeichert.aussagen[0].text


def test_bei_unbrauchbarer_antwort_wird_nichts_gespeichert(tmp_path: Path):
    """Ein Thema mit Bruchstuecken sieht gefuellt aus und ist wertlos."""

    lerner, speicher = _lerner(tmp_path, "Tut mir leid, das kann ich nicht.")

    thema = Thema(name="Irgendwas")
    ergebnis = asyncio.run(lerner._einarbeiten(thema, [("u", "x" * 400)]))

    assert not ergebnis.ok
    assert speicher.laden("Irgendwas").aussagen == []


def test_json_wird_auch_aus_geschwaetz_geholt():
    """Modelle stellen gern eine Zeile davor oder packen es in einen Block."""

    assert _json_aus('Hier ist das Ergebnis:\n```json\n{"aussagen": []}\n```') == {
        "aussagen": []
    }
    assert _json_aus("kein JSON weit und breit") is None


# --- Offene Fragen und Vertiefen ---------------------------------------------------


def test_offene_fragen_werden_festgehalten(tmp_path: Path):
    """Aus ihnen speist sich das Vertiefen."""

    lerner, speicher = _lerner(
        tmp_path,
        _antwort(
            [{"text": "Eine hinreichend lange Aussage ueber das Thema.", "quelle": "u"}],
            ["Welche Rolle spielte Frankreich dabei?"],
        ),
    )

    asyncio.run(lerner._einarbeiten(Thema(name="T"), [("u", "x" * 400)]))
    assert speicher.laden("T").offene_fragen == ["Welche Rolle spielte Frankreich dabei?"]


def test_die_bearbeitete_frage_faellt_weg(tmp_path: Path):
    """Bliebe sie stehen, arbeitete der Orb sie immer wieder ab."""

    lerner, speicher = _lerner(
        tmp_path,
        _antwort([{"text": "Eine hinreichend lange neue Aussage dazu.", "quelle": "u"}]),
    )

    thema = Thema(name="T", offene_fragen=["Welche Rolle spielte Frankreich?"])
    asyncio.run(
        lerner._einarbeiten(
            thema, [("u", "x" * 400)], frage="Welche Rolle spielte Frankreich?"
        )
    )

    assert speicher.laden("T").offene_fragen == []


def test_gelesene_quellen_werden_vermerkt(tmp_path: Path):
    """Ohne dieses Gedaechtnis laese er beim Vertiefen dieselben Seiten."""

    lerner, speicher = _lerner(
        tmp_path,
        _antwort([{"text": "Eine hinreichend lange Aussage zum Thema.", "quelle": "u"}]),
    )

    asyncio.run(lerner._einarbeiten(Thema(name="T"), [("https://a.org/x", "y" * 400)]))
    assert speicher.laden("T").gelesen == ["https://a.org/x"]


def test_bekanntes_wird_dem_modell_mitgegeben(tmp_path: Path):
    """Sonst destilliert es beim Vertiefen dieselben Grundlagen noch einmal."""

    anbieter = _Anbieter(_antwort([]))
    speicher = Themenspeicher(tmp_path / "themen")
    lerner = Themenlerner(speicher=speicher, provider_manager=anbieter)

    thema = Thema(name="T", aussagen=[Aussage(text="Das ist bereits bekannt.")])
    asyncio.run(lerner._einarbeiten(thema, [("u", "x" * 400)]))

    assert "Das ist bereits bekannt." in anbieter.gefragt[0]


def test_die_anweisung_verbietet_das_erfinden(tmp_path: Path):
    """Ein Wissensspeicher, dem man nicht trauen kann, ist schlimmer als keiner."""

    anbieter = _Anbieter(_antwort([]))
    lerner = Themenlerner(
        speicher=Themenspeicher(tmp_path / "t"), provider_manager=anbieter
    )
    asyncio.run(lerner._einarbeiten(Thema(name="T"), [("u", "x" * 400)]))

    anweisung = anbieter.systemprompts[0]
    assert "Erfinde NICHTS" in anweisung
    assert "FUER SICH verstaendlich" in anweisung


# --- Aus dem Gespraech -------------------------------------------------------------


def test_was_der_benutzer_erklaert_wird_woertlich_uebernommen(tmp_path: Path):
    """Es umzuformulieren hiesse, seine Genauigkeit gegen die eigene zu
    tauschen - und er weiss ueber sein Fach mehr als der Orb."""

    gedaechtnis = _Gedaechtnis()
    lerner, speicher = _lerner(tmp_path, "", gedaechtnis)

    satz = "Die Quellenlage zu 1618 ist durch Parteinahme verzerrt."
    ergebnis = lerner.aus_gespraech("Krieg", satz)

    assert ergebnis.ok
    gespeichert = speicher.laden("Krieg")
    assert gespeichert.aussagen[0].text == satz
    assert "Benutzer" in gespeichert.aussagen[0].quelle
    assert gespeichert.aussagen[0].sicherheit == "fakt"


def test_dasselbe_zweimal_wird_nicht_doppelt_abgelegt(tmp_path: Path):
    lerner, speicher = _lerner(tmp_path, "")
    lerner.aus_gespraech("T", "Eine Feststellung ueber das Thema.")
    lerner.aus_gespraech("T", "Eine Feststellung ueber das Thema.")

    assert len(speicher.laden("T").aussagen) == 1


# --- Der Speicher -------------------------------------------------------------------


def test_gross_und_kleinschreibung_ergeben_dasselbe_thema(tmp_path: Path):
    """Sonst wuesste der Orb von jedem die Haelfte."""

    speicher = Themenspeicher(tmp_path / "themen")
    thema = Thema(name="Kalter Krieg", aussagen=[Aussage(text="Eine Aussage dazu.")])
    speicher.speichern(thema)

    assert len(speicher.laden("kalter krieg").aussagen) == 1
    assert len(speicher.laden("KALTER KRIEG").aussagen) == 1


def test_ein_unlesbares_thema_haelt_nichts_auf(tmp_path: Path):
    ordner = tmp_path / "themen"
    ordner.mkdir(parents=True)
    (ordner / "kaputt.json").write_text("{das ist kein json", encoding="utf-8")

    speicher = Themenspeicher(ordner)
    assert speicher.alle() == []
    assert speicher.laden("kaputt").aussagen == []


def test_ein_thema_wird_im_satz_wiedererkannt(tmp_path: Path):
    """Sonst kaeme der Orb im Gespraech nie auf sein eigenes Wissen."""

    speicher = Themenspeicher(tmp_path / "themen")
    speicher.speichern(Thema(name="Kalter Krieg", aussagen=[Aussage(text="Etwas.")]))

    treffer = speicher.passend("Was weisst du eigentlich ueber den Kalten Krieg?")
    assert [t.name for t in treffer] == ["Kalter Krieg"]

    assert speicher.passend("Wie ist das Wetter morgen?") == []


def test_das_genauere_thema_kommt_zuerst(tmp_path: Path):
    """Wer beides gespeichert hat, will das genauere."""

    speicher = Themenspeicher(tmp_path / "themen")
    speicher.speichern(Thema(name="Krieg", aussagen=[Aussage(text="Etwas.")]))
    speicher.speichern(Thema(name="Zweiter Weltkrieg", aussagen=[Aussage(text="Etwas.")]))

    treffer = speicher.passend("Erzaehl mir vom Zweiten Weltkrieg und vom Krieg.")
    assert treffer[0].name == "Zweiter Weltkrieg"


def test_der_kurzbericht_bleibt_kurz(tmp_path: Path):
    """Ein vollstaendiges Dossier verdraengte im Denk-Kontext alles andere,
    einschliesslich der Frage selbst."""

    thema = Thema(
        name="T",
        aussagen=[Aussage(text=f"Aussage Nummer {i} mit etwas Text darin.") for i in range(40)],
    )
    assert thema.kurz().count("\n") <= 9


# --- Das selbststaendige Weiterarbeiten ---------------------------------------------


def test_die_naechste_luecke_ist_die_aelteste(tmp_path: Path):
    """Sonst bliebe alles Aeltere liegen, sobald ein neues Thema dazukommt."""

    speicher = Themenspeicher(tmp_path / "themen")
    alt = Thema(name="Alt", offene_fragen=["Was ist mit A?"])
    alt.zuletzt = 1000.0
    neu = Thema(name="Neu", offene_fragen=["Was ist mit B?"])
    neu.zuletzt = 9000.0
    # Direkt schreiben, damit speichern() den Zeitstempel nicht ueberschreibt.
    for t in (alt, neu):
        (speicher.ordner / f"{t.name.lower()}.json").write_text(
            json.dumps(t.to_dict(), ensure_ascii=False), encoding="utf-8"
        )

    lerner = Themenlerner(speicher=speicher, provider_manager=None)
    assert lerner.naechste_luecke() == ("Alt", "Was ist mit A?")


def test_ohne_offene_fragen_gibt_es_nichts_zu_tun(tmp_path: Path):
    speicher = Themenspeicher(tmp_path / "themen")
    speicher.speichern(Thema(name="T", aussagen=[Aussage(text="Fertig.")]))

    lerner = Themenlerner(speicher=speicher, provider_manager=None)
    assert lerner.naechste_luecke() is None
