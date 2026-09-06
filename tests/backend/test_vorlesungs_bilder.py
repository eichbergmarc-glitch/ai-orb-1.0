"""Bildmaterial soll den Vortrag begleiten, aber nie seinen Ablauf blockieren."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.events.event_bus import EventBus
from backend.orchestrator.orchestrator import Orchestrator
from backend.studium.vorlesungs_bilder import (
    bild_passt,
    bild_treffer_bewerten,
    bildsuchbegriffe,
    folienpunkte_bereinigen,
    infografik_uebersicht,
    uebersichtsart,
    uebersichtskarten,
    vorlesungsfolie_titel,
    vorlesungsthema,
)


def test_suchbegriff_nimmt_schwerpunkt_und_vorlesungsthema() -> None:
    auftrag = "[VORLESUNG]\nThema: Frühe Menschheitsgeschichte"

    begriffe = bildsuchbegriffe(
        "Beginnen wir mit der Neolithischen Revolution und den ersten Siedlungen.",
        auftrag,
    )

    assert vorlesungsthema(auftrag) == "Frühe Menschheitsgeschichte"
    assert "Neolithischen Revolution" in begriffe[0]
    assert begriffe[-1] == "Frühe Menschheitsgeschichte"


def test_unspezifischer_auftakt_faellt_auf_thema_zurueck() -> None:
    assert bildsuchbegriffe(
        "Wir beginnen nun. Das ist der erste Abschnitt.",
        "Thema: Photosynthese",
    )[-1] == "Photosynthese"


def test_artname_ist_spezifischer_als_allgemeines_thema() -> None:
    begriffe = bildsuchbegriffe(
        "Vor rund 300.000 Jahren trat Homo sapiens in Afrika auf.",
        "Thema: Menschheitsgeschichte",
    )

    assert begriffe == ["Homo sapiens"]


def test_unpassender_bildtreffer_wird_verworfen() -> None:
    assert not bild_passt(
        "Menschheitsgeschichte",
        {
            "titel": "Kita Sonnenschein beim Sommerfest",
            "nachweis": "Kindergarten Musterstadt, CC BY-SA",
        },
    )
    assert bild_passt(
        "Homo sapiens",
        {"titel": "Homo sapiens skull reconstruction", "quelle": "Wikimedia Commons"},
    )


def test_regieeinwurf_wird_nicht_zum_fussballmotiv() -> None:
    begriffe = bildsuchbegriffe(
        "Kurzer Einwurf, bevor ich weitermache: Die Verwaltungstäfelchen aus "
        "Ur-III dokumentieren Viehbestände und Abgaben. Diese Keilschrifttafeln "
        "wurden von der assyriologischen Forschung ausgewertet.",
        "Thema: Geschichtswissenschaft",
    )

    assert begriffe
    assert all("Einwurf" not in begriff for begriff in begriffe)
    assert begriffe[0] == "cuneiform clay tablet"
    assert "cuneiform reed stylus clay tablet" in begriffe


def test_keilschrift_waehlt_sichtbares_objekt_statt_zeitwort() -> None:
    begriffe = bildsuchbegriffe(
        "Jahrhunderte später verstehen wir die Keilschrift durch erhaltene "
        "Tontafeln; geschrieben wurde mit einem Griffel aus Schilfrohr.",
        "Thema: Geschichtswissenschaft",
    )

    assert begriffe[:2] == [
        "cuneiform clay tablet",
        "cuneiform reed stylus clay tablet",
    ]
    assert all("Jahrhunderte" not in begriff for begriff in begriffe)


def test_abstrakter_satzanfang_wird_nicht_zum_bildmotiv() -> None:
    begriffe = bildsuchbegriffe(
        "Jahrhunderte prägen unser Verständnis. Die Quellenlage bleibt schwierig.",
        "Thema: Geschichtswissenschaft",
    )

    assert "Jahrhunderte" not in begriffe
    assert "Verständnis" not in begriffe


def test_fachvorlesungen_suchen_die_konkret_genannte_person() -> None:
    assert bildsuchbegriffe(
        "Kant unterscheidet Erscheinung und Ding an sich.",
        "Thema: Philosophie",
    )[0] == "Immanuel Kant portrait"
    assert bildsuchbegriffe(
        "Kafka gestaltet im Prozess eine undurchsichtige Institution.",
        "Thema: Germanistik",
    )[0] == "Franz Kafka portrait"


def test_vier_ursachen_bleiben_eine_vollstaendige_fachstruktur() -> None:
    abschnitt = (
        "Aristoteles unterscheidet vier Ursachen. Die Materialursache: "
        "Woraus etwas besteht. Die Formursache: Welche Gestalt es hat. "
        "Die Wirkursache: Der Bildhauer bringt die Veraenderung hervor."
    )

    karten = uebersichtskarten(abschnitt)

    assert [karte["title"] for karte in karten] == [
        "Materialursache",
        "Formursache",
        "Wirkursache",
        "Zweckursache",
    ]
    assert uebersichtsart(abschnitt) == "enumeration"
    assert vorlesungsfolie_titel(abschnitt) == "Aristoteles: Die vier Ursachen"
    assert bildsuchbegriffe(abschnitt, "Thema: Philosophie")[0] == (
        "Aristotle four causes diagram"
    )


def test_string_mit_folienpunkten_wird_nicht_zeichenweise_zerlegt() -> None:
    punkte = folienpunkte_bereinigen(
        "Aristoteles: Die vier Ursachen",
        "Materialursache: Stoff; Formursache: Gestalt; "
        "Wirkursache: Ausloeser; Zweckursache: Ziel",
    )

    assert len(punkte) == 4
    assert all(len(punkt) > 20 for punkt in punkte)
    assert punkte[0].startswith("Materialursache —")
    assert punkte[-1].startswith("Zweckursache —")


def test_bildranking_bevorzugt_fachbezug_und_praesentationsgroesse() -> None:
    passend = {
        "titel": "Aristotle four causes diagram",
        "quelle": "Wikimedia Commons",
        "breite": 1600,
        "hoehe": 1000,
    }
    beliebig = {
        "titel": "Aristotle portrait icon",
        "quelle": "Sonstige Quelle",
        "breite": 300,
        "hoehe": 300,
    }

    assert bild_treffer_bewerten("Aristotle four causes diagram", passend) > (
        bild_treffer_bewerten("Aristotle four causes diagram", beliebig)
    )


def test_linguistik_und_wirtschaft_bekommen_fachliche_visualisierungen() -> None:
    assert bildsuchbegriffe(
        "Die Phonetik beschreibt Sprachlaute.", "Thema: Linguistik"
    )[0] == "International Phonetic Alphabet chart"
    assert bildsuchbegriffe(
        "Die Zentralbank beeinflusst mit dem Leitzins die Inflation.",
        "Thema: Wirtschaft",
    )[0] in {"consumer price index inflation chart", "European Central Bank building"}


def test_deutsche_suchform_erkennt_englischen_commons_titel() -> None:
    assert bild_passt("Akkadische Reich", {"titel": "Empire akkad ancien"})
    assert bild_passt("Sargons Reich", {"titel": "Sargon of Akkad"})
    assert bild_passt(
        "Keilschrifttafeln",
        {"titel": "Cuneiform administrative tablet from Ur III"},
    )


def test_infografik_ist_uebersicht_und_nutzt_ziffern() -> None:
    inhalt = infografik_uebersicht(
        "Um etwa dreitausenddreihundert vor unserer Zeitrechnung entstand "
        "in Sumer die Keilschrift. Sie diente zunächst der Verwaltung von "
        "Vorräten und Abgaben. Städte wie Uruk entwickelten Tempel und eine "
        "komplexe Verwaltung. Erhaltene Tontafeln liefern dafür konkrete "
        "Belege. Diese Schrift veränderte Herrschaft und Erinnerung dauerhaft."
    )

    assert "## Leitidee" in inhalt
    assert "## Akteure & Raum" in inhalt
    # 26.08.2026 umbenannt in "Quellen & Belege": Die Ueberschriften der
    # Tafel richten sich seither nach dem Inhalt und decken mehrere
    # Faecher ab, nicht mehr nur die Alte Geschichte.
    assert "## Quellen & Belege" in inhalt
    # Ebenfalls umbenannt: "Bedeutung & Folge" heisst jetzt
    # "Wirkung & Nachleben" und gilt fachuebergreifend.
    assert "## Wirkung & Nachleben" in inhalt
    assert "3300 v. u. Z." in inhalt
    assert "dreitausenddreihundert" not in inhalt
    assert "dauerhaft" in inhalt
    karten = uebersichtskarten(
        "Um 3300 v. u. Z. entstand die Keilschrift. Städte wie Uruk "
        "entwickelten Tempel. Erhaltene Tontafeln liefern konkrete Belege."
    )
    assert 2 <= len(karten) <= 5
    assert len({karte["text"] for karte in karten}) == len(karten)


@pytest.mark.asyncio
async def test_bildfund_wird_mit_nachweis_an_lehrtafel_gemeldet(tmp_path) -> None:
    bildpfad = tmp_path / "curie.jpg"
    bildpfad.write_bytes(b"bild")

    class Werkzeuge:
        enabled = True

        async def direkt_ausfuehren(self, name, arguments, *, actor):  # noqa: ANN001
            assert name == "bild_suchen"
            assert arguments["anzahl"] == 3
            assert actor == "vorlesung-bild"
            result = SimpleNamespace(
                ok=True,
                context={
                    "bilder": [
                        {
                            "pfad": str(bildpfad),
                            "titel": "Marie Curie portrait",
                            "nachweis": "Marie Curie, Wikimedia Commons, CC BY-SA",
                        }
                    ]
                },
            )
            return SimpleNamespace(result=result)

    bus = EventBus()
    gesehen = []
    bus.subscribe("lecture.visual.changed", lambda event: gesehen.append(event.payload))

    orchestrator = Orchestrator.__new__(Orchestrator)
    orchestrator._tool_engine = Werkzeuge()
    orchestrator._event_bus = bus
    orchestrator._vorlesungsbild_cache = {}
    orchestrator._vorlesungsbild_generation = 1

    await orchestrator._vorlesungsbild_aktualisieren(
        "Marie Curie untersuchte die Radioaktivität.",
        "Thema: Geschichte der Radioaktivität",
        1,
    )

    assert len(gesehen) == 1
    assert gesehen[0]["path"] == str(bildpfad)
    assert "Wikimedia Commons" in gesehen[0]["caption"]
    assert gesehen[0]["topic"] == "Geschichte der Radioaktivität"
    assert gesehen[0]["layout"] == "overview"


@pytest.mark.asyncio
async def test_verspaeteter_abschnitt_ueberschreibt_neues_bild_nicht(tmp_path) -> None:
    class Werkzeuge:
        enabled = True

        async def direkt_ausfuehren(self, name, arguments, *, actor):  # noqa: ANN001, ARG002
            return SimpleNamespace(
                result=SimpleNamespace(
                    ok=True,
                    context={
                        "bilder": [
                            {
                                "pfad": str(tmp_path / "alt.jpg"),
                                "titel": "Roman Empire map",
                            }
                        ]
                    },
                )
            )

    bus = EventBus()
    gesehen = []
    bus.subscribe("lecture.visual.changed", lambda event: gesehen.append(event.payload))
    orchestrator = Orchestrator.__new__(Orchestrator)
    orchestrator._tool_engine = Werkzeuge()
    orchestrator._event_bus = bus
    orchestrator._vorlesungsbild_cache = {}
    orchestrator._vorlesungsbild_generation = 2

    await orchestrator._vorlesungsbild_aktualisieren(
        "Das Römische Reich expandierte.", "Thema: Antike", 1
    )

    assert gesehen == []


@pytest.mark.asyncio
async def test_unpassendes_foto_wird_durch_lesbare_uebersicht_ersetzt(tmp_path) -> None:

    class Werkzeuge:
        enabled = True

        async def direkt_ausfuehren(self, name, arguments, *, actor):  # noqa: ANN001
            if name == "bild_suchen":
                return SimpleNamespace(
                    result=SimpleNamespace(
                        ok=True,
                        context={
                            "bilder": [
                                {
                                    "pfad": str(tmp_path / "kita.jpg"),
                                    "titel": "Kita Sonnenschein beim Sommerfest",
                                }
                            ]
                        },
                    )
                )
            raise AssertionError("Ein Rasterbild darf das Foto nicht mehr ersetzen")

    bus = EventBus()
    gesehen = []
    bus.subscribe("lecture.visual.changed", lambda event: gesehen.append(event.payload))
    orchestrator = Orchestrator.__new__(Orchestrator)
    orchestrator._tool_engine = Werkzeuge()
    orchestrator._event_bus = bus
    orchestrator._vorlesungsbild_cache = {}
    orchestrator._vorlesungsbild_generation = 1

    await orchestrator._vorlesungsbild_aktualisieren(
        "Homo sapiens breitete sich von Afrika in weitere Weltregionen aus.",
        "Thema: Menschheitsgeschichte",
        1,
    )

    assert gesehen[0]["path"] == ""
    assert gesehen[0]["kind"] == "overview"
    assert gesehen[0]["summary"][0]["title"] == "Leitidee"
    assert "Homo sapiens" in gesehen[0]["summary"][0]["text"]
