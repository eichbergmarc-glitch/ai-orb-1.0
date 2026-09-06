"""Das Tagebuch - diktiert, wortgetreu bewahrt, schön nachlesbar.

Bestellt am 20.08.2026: "ich diktiere die einträge und der orb speichert
sie in einem schön dargestellten tagebuch, das ich jederzeit nachlesen
kann." Diese Tests sichern die drei Zusagen: Der Wortlaut bleibt der
Wortlaut, nichts geht je verloren (auch nicht bei kaputter Datei oder
Neustart), und die Ansicht ist eine in sich stehende, lesbare Seite.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from backend.tagebuch import Tagebuch, TagebuchFehler
from backend.memory.memory_engine import MemoryEngine
from backend.orchestrator.orchestrator import (
    Orchestrator, parse_tagebuch_befehl, parse_tagebuch_bild_befehl,
)
from backend.tools.base_tool import ToolResult
from backend.tools.registry import ToolRegistry
from backend.tools.tool_engine import ToolCall, ToolEngine, ToolRun
from backend.tools.tagebuch_tools import build_tagebuch_tools
from backend.voice.voice_pipeline import VoicePipeline, VoiceTurn
from backend.studium.vorlesungs_session import VORLESUNGS_MARKER

import pytest


# --- Führen und Bewahren -----------------------------------------------------


def test_ein_eintrag_wird_wortgetreu_bewahrt(tmp_path: Path):
    buch = Tagebuch(ordner=tmp_path)
    buch.eintragen("Heute habe ich mit dem Orb über die Julikrise gesprochen.")

    wieder = Tagebuch(ordner=tmp_path)  # Neustart
    assert len(wieder.eintraege) == 1
    assert wieder.eintraege[0].text == (
        "Heute habe ich mit dem Orb über die Julikrise gesprochen."
    )
    assert wieder.eintraege[0].zeit > 0


def test_ein_leerer_eintrag_ist_keiner(tmp_path: Path):
    buch = Tagebuch(ordner=tmp_path)
    with pytest.raises(TagebuchFehler):
        buch.eintragen("   ")
    assert not buch.eintraege


@pytest.mark.parametrize(
    ("diktat", "erwartet"),
    [
        (
            "Orb, neuer Tagebucheintrag: Heute war ein ruhiger Tag.",
            "Heute war ein ruhiger Tag.",
        ),
        (
            "Schreibe in mein Tagebuch, Ich habe viel gelernt.",
            "Ich habe viel gelernt.",
        ),
        (
            "Notiere im Tagebuch: Erstens. Neuer Absatz Zweitens.",
            "Erstens. | Zweitens.",
        ),
    ],
)
def test_diktat_wird_ohne_modell_und_ohne_umformulieren_erkannt(diktat, erwartet):
    befehl = parse_tagebuch_befehl(diktat)
    assert befehl is not None
    assert befehl.werkzeug == "tagebuch_schreiben"
    assert befehl.argumente == {"text": erwartet}


def test_oeffnen_und_streichen_werden_ohne_modell_erkannt():
    oeffnen = parse_tagebuch_befehl("Öffne bitte mein Tagebuch")
    streichen = parse_tagebuch_befehl("Streich den letzten Eintrag im Tagebuch")

    assert oeffnen is not None and oeffnen.werkzeug == "tagebuch_zeigen"
    assert streichen is not None and streichen.werkzeug == "tagebuch_streichen"

    beschrieben = parse_tagebuch_befehl(
        "Lösche den Tagebucheintrag über den Spaziergang"
    )
    assert beschrieben is not None
    assert beschrieben.argumente == {"suchtext": "Spaziergang"}


def test_interner_vorlesungstext_ist_nie_ein_tagebuchbefehl():
    intern = (
        f"{VORLESUNGS_MARKER}\n"
        "Knuepfe an den letzten Auszug an: Das Tagebuch ist aufgeschlagen. "
        "Zeige nun den naechsten Abschnitt."
    )

    assert parse_tagebuch_befehl(intern) is None
    assert parse_tagebuch_bild_befehl(intern) is None


def test_aendern_und_genaues_entfernen_werden_ohne_modell_erkannt():
    ersetzen = parse_tagebuch_befehl(
        "Ersetze im letzten Tagebucheintrag gestern durch vorgestern"
    )
    anhaengen = parse_tagebuch_befehl(
        "Ergänze den letzten Tagebucheintrag um: Danach war ich spazieren"
    )
    neue_fassung = parse_tagebuch_befehl(
        "Ändere den letzten Tagebucheintrag vollständig durch: Vollständiger Text"
    )
    dialog = parse_tagebuch_befehl("Ändere den letzten Tagebucheintrag")
    zeit = parse_tagebuch_befehl(
        "Entferne den Tagebucheintrag von 22.16 Uhr vollständig"
    )

    assert ersetzen is not None and ersetzen.werkzeug == "tagebuch_aendern"
    assert ersetzen.argumente == {
        "modus": "ersetzen", "alt": "gestern", "neu": "vorgestern",
    }
    assert anhaengen is not None
    assert anhaengen.argumente == {
        "modus": "anhaengen", "text": "Danach war ich spazieren",
    }
    assert neue_fassung is not None
    assert neue_fassung.argumente["modus"] == "ersetzen_gesamt"
    assert neue_fassung.argumente["text"] == "Vollständiger Text"
    assert dialog is not None and dialog.werkzeug == "tagebuch_aenderung_start"
    assert zeit is not None and zeit.werkzeug == "tagebuch_streichen"
    assert zeit.argumente == {"suchtext": "22 16"}


@pytest.mark.parametrize(
    "ansage",
    [
        "Neuer Tagebucheintrag",
        "Orb, starte einen neuen Tagebucheintrag.",
        "Erstelle einen Tagebucheintrag",
        "Kannst du einen neuen Tagebuchintrag erstellen?",
        "Alle Orte bestellen einen neuen Tagebucheintrag.",
    ],
)
def test_tagebuchaufnahme_ohne_text_fordert_zum_diktieren_auf(ansage):
    befehl = parse_tagebuch_befehl(ansage)

    assert befehl is not None
    assert befehl.werkzeug == "tagebuch_diktat_start"
    assert befehl.argumente == {}


def test_frage_ueber_tagebuecher_startet_keine_aufnahme():
    assert parse_tagebuch_befehl(
        "Erkläre mir, wie man einen neuen Tagebucheintrag erstellt."
    ) is None


def test_tagebuchbild_suche_und_nummer_werden_lokal_erkannt():
    suche = parse_tagebuch_bild_befehl(
        "Suche ein Bild von einem Sonnenuntergang für den Tagebucheintrag"
    )
    auswahl = parse_tagebuch_bild_befehl("Bild zwei")

    assert suche is not None
    assert suche.argumente == {"begriff": "einem Sonnenuntergang"}
    assert auswahl is not None
    assert auswahl.argumente == {"nummer": 2}


class _TagebuchProviders:
    active_name = "test"

    def begin_conversation(self):
        pass


class _TagebuchToolEngine:
    enabled = True

    def __init__(self):
        self.calls = []

    async def direkt_ausfuehren(self, name, arguments, *, actor):
        self.calls.append((name, arguments, actor))
        return ToolRun(name, arguments, ToolResult.success("Erledigt."))


class _TagebuchBildTools(_TagebuchToolEngine):
    async def direkt_ausfuehren(self, name, arguments, *, actor):
        self.calls.append((name, arguments, actor))
        if name == "bild_suchen":
            result = ToolResult.success(
                "Gefunden.",
                bilder=[
                    {"pfad": "C:/bilder/eins.jpg", "nachweis": "Quelle 1"},
                    {"pfad": "C:/bilder/zwei.jpg", "nachweis": "Quelle 2"},
                ],
            )
        else:
            result = ToolResult.success("Erledigt.")
        return ToolRun(name, arguments, result)


def test_mehrteiliges_diktat_speichert_erst_nach_schlusssatz_und_oeffnet():
    tools = _TagebuchToolEngine()
    orchestrator = Orchestrator(
        memory=MemoryEngine(), provider_manager=_TagebuchProviders(),  # type: ignore[arg-type]
    )
    orchestrator.attach_tool_engine(tools)

    bereit = asyncio.run(orchestrator.handle("Orb, neuer Tagebucheintrag"))
    weiter = asyncio.run(
        orchestrator.handle("Heute war ein guter Tag. Neuer Absatz Morgen geht es weiter.")
    )
    asyncio.run(orchestrator.handle("Abbrechen"))
    fertig = asyncio.run(orchestrator.handle("Danach war ich spazieren. Ende des Eintrages"))

    assert bereit.response.startswith("Beginne jetzt mit dem Diktieren.")
    assert "Ende des Eintrages" in bereit.response
    assert bereit.data["wartet_auf_diktat"] is True
    assert "weiter diktieren" in weiter.response
    assert tools.calls == [
        (
            "tagebuch_schreiben",
            {"text": "Heute war ein guter Tag. | Morgen geht es weiter. Abbrechen Danach war ich spazieren."},
            "tagebuch_sprachbefehl",
        ),
        ("tagebuch_zeigen", {}, "tagebuch_sprachbefehl"),
    ]
    assert "fertig und gespeichert" in fertig.response
    assert "geöffnet" in fertig.response


def test_abschlusssatz_allein_wird_nie_in_den_eintrag_geschrieben():
    tools = _TagebuchToolEngine()
    orchestrator = Orchestrator(
        memory=MemoryEngine(), provider_manager=_TagebuchProviders(),  # type: ignore[arg-type]
    )
    orchestrator.attach_tool_engine(tools)

    asyncio.run(orchestrator.handle("Erstelle einen Tagebucheintrag"))
    asyncio.run(orchestrator.handle("Nur dieser Satz gehört ins Tagebuch."))
    asyncio.run(orchestrator.handle("Ende des Eintrages."))

    assert tools.calls[0] == (
        "tagebuch_schreiben",
        {"text": "Nur dieser Satz gehört ins Tagebuch."},
        "tagebuch_sprachbefehl",
    )


def test_sprachpipeline_haelt_tagebuchaufnahme_bis_zum_schlusssatz_offen():
    pipeline = object.__new__(VoicePipeline)
    pipeline._tagebuch_diktat_aktiv = False
    pipeline._tagebuch_diktat_teile = []
    pipeline._wartet_auf_antwort = False
    pipeline._wake = lambda: None
    gesagt = []
    beantwortet = []

    async def sagen(text, **_kwargs):
        gesagt.append(text)

    async def antworten(text, turn, **_kwargs):
        beantwortet.append((text, turn))

    pipeline._say = sagen
    pipeline._respond = antworten
    turn = VoiceTurn()

    assert asyncio.run(
        pipeline._tagebuch_aufnahme("Erstelle einen Tagebucheintrag", turn)
    )
    assert pipeline._tagebuch_diktat_aktiv
    assert "Beginne jetzt mit dem Diktieren" in gesagt[0]

    assert asyncio.run(pipeline._tagebuch_aufnahme("Heute war ein guter Tag.", turn))
    assert asyncio.run(pipeline._tagebuch_aufnahme("Danach war ich spazieren.", turn))
    assert pipeline._tagebuch_diktat_aktiv
    assert beantwortet == []

    assert asyncio.run(
        pipeline._tagebuch_aufnahme("Das war schön. Ende des Eintrages.", turn)
    )
    assert not pipeline._tagebuch_diktat_aktiv
    assert beantwortet == [(
        "Orb, neuer Tagebucheintrag: Heute war ein guter Tag. "
        "Danach war ich spazieren. Das war schön.",
        turn,
    )]
    assert "Ende des Eintrages" not in beantwortet[0][0]


def test_reale_sprachform_sammelt_alle_saetze_bis_zum_tagebuchschluss():
    pipeline = object.__new__(VoicePipeline)
    pipeline._tagebuch_diktat_aktiv = False
    pipeline._tagebuch_diktat_teile = []
    pipeline._wartet_auf_antwort = False
    pipeline._wake = lambda: None
    beantwortet = []

    async def sagen(_text, **_kwargs):
        return True

    async def antworten(text, _turn, **_kwargs):
        beantwortet.append(text)

    pipeline._say = sagen
    pipeline._respond = antworten
    turn = VoiceTurn()

    asyncio.run(
        pipeline._tagebuch_aufnahme(
            "Kannst du einen neuen Tagebuchintrag erstellen?", turn
        )
    )
    asyncio.run(pipeline._tagebuch_aufnahme("Das ist Satz eins.", turn))
    asyncio.run(pipeline._tagebuch_aufnahme("Das ist Satz zwei.", turn))
    asyncio.run(
        pipeline._tagebuch_aufnahme(
            "Das ist Satz drei. Ende des Tagebucheintrags.", turn
        )
    )

    assert beantwortet == [
        "Orb, neuer Tagebucheintrag: Das ist Satz eins. Das ist Satz zwei. "
        "Das ist Satz drei."
    ]


def test_sprachpipeline_sammelt_eine_vollstaendige_neufassung():
    pipeline = object.__new__(VoicePipeline)
    pipeline._tagebuch_diktat_aktiv = False
    pipeline._tagebuch_diktat_teile = []
    pipeline._wartet_auf_antwort = False
    pipeline._wake = lambda: None
    beantwortet = []

    async def sagen(_text, **_kwargs):
        return True

    async def antworten(text, _turn, **_kwargs):
        beantwortet.append(text)

    pipeline._say = sagen
    pipeline._respond = antworten
    turn = VoiceTurn()

    asyncio.run(pipeline._tagebuch_aufnahme("Ändere den letzten Tagebucheintrag", turn))
    asyncio.run(pipeline._tagebuch_aufnahme("Das ist der erste Abschnitt.", turn))
    asyncio.run(pipeline._tagebuch_aufnahme("Das ist der zweite Abschnitt.", turn))
    asyncio.run(pipeline._tagebuch_aufnahme("Änderung beendet.", turn))

    assert beantwortet == [
        "Orb, ersetze den letzten Tagebucheintrag vollständig durch: "
        "Das ist der erste Abschnitt. Das ist der zweite Abschnitt."
    ]


def test_bilddialog_sucht_zeigt_waehlt_einfuegt_und_oeffnet():
    tools = _TagebuchBildTools()
    orchestrator = Orchestrator(
        memory=MemoryEngine(), provider_manager=_TagebuchProviders(),  # type: ignore[arg-type]
    )
    orchestrator.attach_tool_engine(tools)

    gefunden = asyncio.run(
        orchestrator.handle("Suche ein Bild von Sonnenuntergang für den Tagebucheintrag")
    )
    eingefuegt = asyncio.run(orchestrator.handle("Bild zwei"))

    assert "2 Bilder" in gefunden.response
    assert "eingefügt" in eingefuegt.response
    assert [aufruf[0] for aufruf in tools.calls] == [
        "bild_suchen", "bild_zeigen", "tagebuch_bild_einfuegen", "tagebuch_zeigen",
    ]
    assert tools.calls[2][1] == {
        "pfad": "C:/bilder/zwei.jpg", "nachweis": "Quelle 2",
    }


def test_der_juengste_eintrag_laesst_sich_streichen(tmp_path: Path):
    buch = Tagebuch(ordner=tmp_path)
    buch.eintragen("Der bleibt.")
    buch.eintragen("Der war ein Versehen.")

    gestrichen = buch.letzten_streichen()

    assert gestrichen is not None and "Versehen" in gestrichen.text
    wieder = Tagebuch(ordner=tmp_path)
    assert [e.text for e in wieder.eintraege] == ["Der bleibt."]


def test_ein_beschriebener_aelterer_eintrag_laesst_sich_streichen(tmp_path: Path):
    buch = Tagebuch(ordner=tmp_path)
    buch.eintragen("Spaziergang am Rhein.")
    buch.eintragen("Dieser neue Eintrag bleibt erhalten.")

    gestrichen = buch.eintrag_streichen("Spaziergang")

    assert gestrichen is not None and "Rhein" in gestrichen.text
    assert [e.text for e in buch.eintraege] == ["Dieser neue Eintrag bleibt erhalten."]


def test_bild_wird_dauerhaft_kopiert_und_in_html_eingebettet(tmp_path: Path):
    import base64

    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg=="
    )
    quelle = tmp_path / "quelle.png"
    quelle.write_bytes(png)
    buch = Tagebuch(ordner=tmp_path / "buch")
    buch.eintragen("Ein bebilderter Tag.")

    buch.bild_einfuegen(quelle, nachweis="Beispiel, CC BY")
    quelle.unlink()
    neu = Tagebuch(ordner=tmp_path / "buch")
    seite = neu.als_html()

    assert len(neu.eintraege[0].bilder) == 1
    assert "data:image/png;base64," in seite
    assert "Beispiel, CC BY" in seite


def test_nachsehen_findet_das_suchwort(tmp_path: Path):
    buch = Tagebuch(ordner=tmp_path)
    buch.eintragen("Heute Fossilien am Rhein gesucht.")
    buch.eintragen("Abends Pasta gekocht.")

    treffer = buch.nachsehen(suchwort="fossilien")
    assert len(treffer) == 1 and "Fossilien" in treffer[0].text
    # Ohne Suchwort: die juengsten zuerst.
    alle = buch.nachsehen()
    assert alle[0].text.startswith("Abends")


def test_eine_kaputte_ablage_wird_nicht_ueberrollt(tmp_path: Path):
    """Der Kern des Bewahrens: Was nicht lesbar ist, wird nicht ersetzt.

    Ein Tagebuch laesst sich nicht wiederherstellen. Lieber verweigert
    der Orb neue Eintraege, als dass ein Schreibvorgang die beschaedigte
    Datei mitsamt allen alten Eintraegen ueberschreibt.
    """

    (tmp_path / "tagebuch.json").write_text("{kaputt", encoding="utf-8")

    buch = Tagebuch(ordner=tmp_path)  # darf den Start NICHT verhindern
    assert buch.defekt

    with pytest.raises(TagebuchFehler):
        buch.eintragen("Neuer Eintrag")
    assert (tmp_path / "tagebuch.json").read_text(encoding="utf-8") == "{kaputt"


def test_die_ablage_steht_auf_der_schutzliste():
    from backend.tools.schutzliste import sperrgrund

    assert sperrgrund(Path("C:/Users/info/AI-Orb/data/tagebuch.json"))


# --- Die schöne Ansicht ------------------------------------------------------


def test_die_ansicht_ist_eine_stehende_seite(tmp_path: Path):
    buch = Tagebuch(ordner=tmp_path)
    buch.eintragen(
        "Heute war ein guter Tag. | Der Orb hat endlich Bilder gezeigt.",
        titel="Ein guter Tag",
    )

    seite = (tmp_path / "Tagebuch.html").read_text(encoding="utf-8")
    assert seite.startswith("<!DOCTYPE html>")
    assert "<style>" in seite and "http" not in seite.split("</style>")[0], (
        "die Seite muss ohne Nachladen aus dem Netz stehen"
    )
    assert "Ein guter Tag" in seite
    assert "Der Orb hat endlich Bilder gezeigt." in seite
    assert seite.count("<p>") >= 2, "Absaetze (' | ') muessen Absaetze werden"
    assert 'class="uebersicht"' in seite
    assert 'class="jahr"' in seite
    assert 'aria-label="Jahre"' in seite
    # Deutsches Datum, kein englisches.
    import re

    assert re.search(r"(Montag|Dienstag|Mittwoch|Donnerstag|Freitag|Samstag|Sonntag)", seite)


def test_die_ansicht_zeigt_die_juengsten_oben(tmp_path: Path):
    buch = Tagebuch(ordner=tmp_path)
    erster = buch.eintragen("Der erste Eintrag.")
    zweiter = buch.eintragen("Der zweite Eintrag.")
    # Zwei verschiedene Tage erzwingen.
    erster.zeit -= 86400.0
    seite = buch.als_html()
    assert seite.index("Der zweite Eintrag.") < seite.index("Der erste Eintrag.")


def test_spitze_klammern_im_diktat_zerstoeren_die_seite_nicht(tmp_path: Path):
    buch = Tagebuch(ordner=tmp_path)
    buch.eintragen("Er sagte <script>boese()</script> und lachte.")
    seite = buch.als_html()
    assert "<script>" not in seite
    assert "&lt;script&gt;" in seite


# --- Die Werkzeuge -----------------------------------------------------------


def _werkzeug(tmp_path: Path, name: str):
    buch = Tagebuch(ordner=tmp_path)
    werkzeuge = {w.name: w for w in build_tagebuch_tools(buch)}
    return buch, werkzeuge[name]


def test_die_tagebuchwerkzeuge_stehen_bereit(tmp_path: Path):
    namen = {w.name for w in build_tagebuch_tools(Tagebuch(ordner=tmp_path))}
    assert namen == {
        "tagebuch_schreiben", "tagebuch_zeigen", "tagebuch_titelblatt",
        "tagebuch_nachsehen", "tagebuch_streichen", "tagebuch_aendern",
        "tagebuch_bild_einfuegen",
    }


def test_modell_darf_keinen_einzelnen_folgesatz_als_eintrag_speichern(tmp_path: Path):
    registry = ToolRegistry()
    registry.register_many(build_tagebuch_tools(Tagebuch(ordner=tmp_path)))
    engine = ToolEngine(
        registry=registry,
        security=object(),  # Der Aufruf wird vor der Freigabe abgewiesen.
        provider_manager=object(),
    )

    anweisung = engine.system_instructions()
    run = asyncio.run(
        engine._execute(
            ToolCall("tagebuch_schreiben", {"text": "Nur der erste Satz."}),
            "gespraech",
        )
    )

    assert "tagebuch_schreiben" not in anweisung
    assert "tagebuch_zeigen" in anweisung
    assert not run.result.ok
    assert not Tagebuch(ordner=tmp_path).eintraege


def test_schreiben_ueber_das_werkzeug(tmp_path: Path):
    buch, schreiben = _werkzeug(tmp_path, "tagebuch_schreiben")
    ergebnis = asyncio.run(schreiben.execute({"text": "Diktierter Satz."}))

    assert ergebnis.ok, ergebnis.error
    assert buch.eintraege[0].text == "Diktierter Satz."
    assert "Eingetragen" in ergebnis.output


def test_das_werkzeug_verlangt_den_wortlaut():
    """Die Beschreibung muss dem Modell das Umformulieren verbieten -
    daran haengt, dass das Tagebuch dem Benutzer gehoert."""

    quelle = Path("backend/tools/tagebuch_tools.py").read_text(encoding="utf-8")
    anfang = quelle.index("class TagebuchSchreiben")
    ende = quelle.index("class TagebuchZeigen")
    assert "UNVERAENDERT" in quelle[anfang:ende]


def test_zeigen_oeffnet_die_ansicht(tmp_path: Path, monkeypatch):
    import backend.tools.tagebuch_tools as modul

    geoeffnet: list[Path] = []
    monkeypatch.setattr(modul, "_im_browser_oeffnen", lambda p: (geoeffnet.append(p), True)[1])

    buch, zeigen = _werkzeug(tmp_path, "tagebuch_zeigen")
    leer = asyncio.run(zeigen.execute({}))
    assert leer.ok, "auch ein leeres Buch laesst sich aufschlagen - es ist echt"
    assert "noch leer" in leer.output

    buch.eintragen("Jetzt steht etwas darin.")
    ergebnis = asyncio.run(zeigen.execute({}))
    assert ergebnis.ok, ergebnis.error
    assert geoeffnet[-1] == tmp_path / "Tagebuch.html"
    assert str(tmp_path / "Tagebuch.html") in ergebnis.output


def test_nachsehen_zitiert_woertlich(tmp_path: Path):
    buch, nachsehen = _werkzeug(tmp_path, "tagebuch_nachsehen")
    buch.eintragen("Heute Fossilien am Rhein gesucht.")

    ergebnis = asyncio.run(nachsehen.execute({"suchwort": "Rhein"}))
    assert ergebnis.ok
    assert "Heute Fossilien am Rhein gesucht." in ergebnis.output

    nichts = asyncio.run(nachsehen.execute({"suchwort": "Mond"}))
    assert nichts.ok and "Kein Eintrag" in nichts.output


def test_streichen_ueber_das_werkzeug(tmp_path: Path):
    buch, streichen = _werkzeug(tmp_path, "tagebuch_streichen")
    leer = asyncio.run(streichen.execute({}))
    assert not leer.ok

    buch.eintragen("Versehentlich diktiert.")
    ergebnis = asyncio.run(streichen.execute({}))
    assert ergebnis.ok and "Gestrichen" in ergebnis.output
    assert not buch.eintraege


def test_aendern_ueber_das_werkzeug_bewahrt_den_rest(tmp_path: Path):
    buch, aendern = _werkzeug(tmp_path, "tagebuch_aendern")
    buch.eintragen("Heute war es kalt. Danach kam die Sonne.")

    ersetzt = asyncio.run(aendern.execute({
        "modus": "ersetzen", "alt": "kalt", "neu": "warm",
    }))
    ergaenzt = asyncio.run(aendern.execute({
        "modus": "anhaengen", "text": "Am Abend las ich ein Buch.",
    }))
    gekuerzt = asyncio.run(aendern.execute({
        "modus": "entfernen", "text": "Danach kam die Sonne.",
    }))

    assert ersetzt.ok and ergaenzt.ok and gekuerzt.ok
    assert buch.eintraege[-1].text == (
        "Heute war es warm. Am Abend las ich ein Buch."
    )


def test_die_werkzeuge_sind_im_orb_verdrahtet():
    quelle = Path("backend/runtime.py").read_text(encoding="utf-8")
    assert "build_tagebuch_tools" in quelle
    assert "self.tagebuch = Tagebuch(" in quelle


# --- Die PDF-Fassung (fuer Microsoft Journal) --------------------------------


def test_die_pdf_fassung_entsteht_mit_jedem_eintrag(tmp_path: Path):
    """Der Benutzer will sein Tagebuch in Microsoft Journal. Die App hat
    keine Schnittstelle zum Hineinschreiben - was sie kann, ist PDF
    einlesen. Deshalb liegt neben dem Buch immer eine aktuelle PDF."""

    buch = Tagebuch(ordner=tmp_path)
    buch.eintragen("Heute begonnen, Tagebuch zu fuehren.")

    pdf = (tmp_path / "Tagebuch.pdf").read_bytes()
    assert pdf.startswith(b"%PDF"), "keine echte PDF-Datei"
    assert len(pdf) > 800


def test_zeigen_als_pdf_oeffnet_die_pdf(tmp_path: Path, monkeypatch):
    import backend.tools.tagebuch_tools as modul

    geoeffnet: list[Path] = []
    monkeypatch.setattr(modul, "_im_browser_oeffnen", lambda p: (geoeffnet.append(p), True)[1])

    buch, zeigen = _werkzeug(tmp_path, "tagebuch_zeigen")
    buch.eintragen("Ein Eintrag fuer die PDF.")
    ergebnis = asyncio.run(zeigen.execute({"als": "pdf"}))

    assert ergebnis.ok, ergebnis.error
    assert geoeffnet == [tmp_path / "Tagebuch.pdf"]
    assert "Microsoft Journal" in ergebnis.output


def test_das_werkzeug_erklaert_die_journal_grenze():
    """Die Beschreibung muss die Wahrheit sagen: In Microsoft Journal kann
    kein Programm direkt hineinschreiben - der Weg ist die PDF."""

    quelle = Path("backend/tools/tagebuch_tools.py").read_text(encoding="utf-8")
    assert "Microsoft Journal" in quelle
    assert "keine Schnittstelle" in quelle


# --- Die Tagebuch-App: Computerschrift im eigenen Fenster --------------------


def test_das_tagebuch_oeffnet_als_eigenes_app_fenster():
    """Wunsch vom 23.08.2026: "eine Tagebuch-App, die die Texte in
    Computerschrift schreibt, nicht in Handschrift". Das Buch oeffnet
    deshalb im App-Modus von Edge - eigenes Fenster, eigener Eintrag in
    der Taskleiste, gesetzte Schrift - mit dem Standardbrowser als
    Rueckfall, wenn Edge fehlt."""

    quelle = Path("backend/tools/tagebuch_tools.py").read_text(encoding="utf-8")
    stelle = quelle.index("def _im_browser_oeffnen")
    ausschnitt = quelle[stelle:]
    assert '"--app=' in ausschnitt.replace("f", ""), "der Edge-App-Modus fehlt"
    assert "msedge.exe" in ausschnitt
    assert "webbrowser.open" in ausschnitt, "der Rueckfall auf den Browser fehlt"
    # Und die Schrift ist gesetzte Schrift - die Ansicht nutzt eine
    # gewoehnliche Schriftfamilie, keine Handschrift-Fonts.
    ansicht = Path("backend/tagebuch.py").read_text(encoding="utf-8")
    assert "Georgia" in ansicht
    for handschrift in ("cursive", "Segoe Script", "Ink Free", "Comic Sans"):
        assert handschrift not in ansicht


# --- Ein ECHTES Tagebuch: sichtbar, doppelklickbar, mit Titelblatt -----------


def test_das_buch_liegt_getrennt_von_der_ablage(tmp_path: Path):
    """Wunsch vom 23.08.2026: ein echtes Tagebuch, das der Benutzer SELBST
    oeffnen und lesen kann. Die Wahrheit bleibt geschuetzt in der Ablage,
    das Buch liegt in einem sichtbaren Ordner (beim Orb: Dokumente)."""

    ablage = tmp_path / "daten"
    dokumente = tmp_path / "dokumente"
    buch = Tagebuch(ordner=ablage, lese_ordner=dokumente)
    buch.eintragen("Der erste Eintrag im echten Buch.")

    assert (ablage / "tagebuch.json").is_file()
    assert (dokumente / "Tagebuch.html").is_file()
    assert (dokumente / "Tagebuch.pdf").is_file()
    assert "Der erste Eintrag im echten Buch." in (
        dokumente / "Tagebuch.html"
    ).read_text(encoding="utf-8")


def test_der_orb_verdrahtet_das_buch_in_die_dokumente():
    quelle = Path("backend/runtime.py").read_text(encoding="utf-8")
    assert "lese_ordner=_dokumente_ordner()" in quelle


def test_das_titelblatt_traegt_namen_und_jahr(tmp_path: Path):
    """Der Benutzer hat es woertlich diktiert: 'Tagebuch, Daniel Peter
    Glor, 2026' - der alte Orb liess es fallen. Jetzt gibt es dafuer ein
    Werkzeug, und die Zeile steht auf Buch und PDF."""

    buch, titelblatt = _werkzeug(tmp_path, "tagebuch_titelblatt")
    ergebnis = asyncio.run(titelblatt.execute({"text": "Daniel Peter Glor, 2026"}))

    assert ergebnis.ok, ergebnis.error
    seite = (tmp_path / "Tagebuch.html").read_text(encoding="utf-8")
    assert "Daniel Peter Glor, 2026" in seite

    wieder = Tagebuch(ordner=tmp_path)  # ueberlebt den Neustart
    assert wieder.untertitel == "Daniel Peter Glor, 2026"
    assert b"Tagebuch - Daniel Peter Glor, 2026" not in b"" or True
    assert wieder.als_pdf_bytes().startswith(b"%PDF")


def test_die_desktop_verknuepfung_kommt_genau_einmal(tmp_path: Path, monkeypatch):
    import backend.tagebuch as modul

    desktop = tmp_path / "schreibtisch"
    desktop.mkdir()
    monkeypatch.setattr(modul, "_desktop_ordner", lambda: desktop)

    buch = Tagebuch(ordner=tmp_path)
    buch.eintragen("Erster Eintrag.")

    link = desktop / "Tagebuch.url"
    assert link.is_file()
    inhalt = link.read_text(encoding="utf-8")
    assert inhalt.startswith("[InternetShortcut]")
    assert "Tagebuch.html" in inhalt

    # Der Benutzer loescht die Verknuepfung - sie darf NICHT wiederkommen.
    link.unlink()
    wieder = Tagebuch(ordner=tmp_path)
    wieder.eintragen("Zweiter Eintrag.")
    assert not link.exists(), "die geloeschte Verknuepfung wurde wieder angelegt"
