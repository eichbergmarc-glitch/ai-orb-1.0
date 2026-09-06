"""Der Kalender-Testadapter und die Trennung von Modell- und Umgebungsfehler.

`rechner_02` mass bis zum 1. September 2026 zwei Dinge auf einmal: ob das
Modell den Kalender bedienen kann, und ob auf diesem Rechner jemand bei
Google angemeldet ist. Diese Tests halten fest, dass das jetzt getrennt
ist - und dass der Probekalender dabei nicht heimlich zu einem anderen
Werkzeug geworden ist.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any

import pytest

from backend.integrations.kalender.client import KalenderFehler
from backend.lernen.faehigkeitskatalog import Pruefstueck, katalog
from backend.lernen.kalenderprobe import (
    PROBE_STICHWORTE,
    PROBETERMINE,
    Probekalender,
    probekalender_werkzeuge,
)
from backend.lernen.messen import fehlerklasse_einordnen


def _werkzeug(name: str = "termine_ansehen", **kw: Any):
    return {w.name: w for w in probekalender_werkzeuge(**kw)}[name]


def _ausfuehren(werkzeug, argumente: dict[str, Any]):
    return asyncio.run(werkzeug.execute(argumente))


# --- Das Werkzeug ist das echte -------------------------------------------


def test_der_probekalender_baut_das_echte_werkzeug():
    """Kein Nachbau: derselbe Name, dieselben Parameter, dieselbe Erlaubnis."""

    from backend.tools.kalender_tools import TermineAnsehenTool

    werkzeug = _werkzeug()

    assert isinstance(werkzeug, TermineAnsehenTool)
    assert werkzeug.name == "termine_ansehen"
    assert werkzeug.permission == "read_calendar"
    assert [p.name for p in werkzeug.parameters] == ["zeitraum", "suche", "anzahl"]


def test_der_zeitraum_woche_liefert_alle_probetermine():
    ergebnis = _ausfuehren(_werkzeug(), {"zeitraum": "woche"})

    assert ergebnis.ok, ergebnis.error
    for stichwort in PROBE_STICHWORTE:
        assert stichwort in str(ergebnis.output)


def test_die_suche_wirkt_wie_im_echten_werkzeug():
    ergebnis = _ausfuehren(_werkzeug(), {"zeitraum": "woche", "suche": "Zahnarzt"})

    assert ergebnis.ok
    assert "Zahnarzt" in str(ergebnis.output)
    assert "Elternabend" not in str(ergebnis.output)


def test_das_ergebnis_haengt_nicht_vom_wochentag_ab():
    """Sonst haette derselbe Pruefstueck je nach Tag ein anderes Ergebnis."""

    for versatz in range(7):
        tag = datetime(2026, 9, 7) + timedelta(days=versatz)
        kalender = Probekalender(heute=tag)
        titel = {t.titel for t in kalender.termine(limit=50)}
        assert titel == set(PROBE_STICHWORTE), f"Wochentag {versatz}: {titel}"


def test_beide_modelle_bekommen_dieselben_termine():
    erste = [t.to_dict() for t in Probekalender(heute=datetime(2026, 9, 8)).termine()]
    zweite = [t.to_dict() for t in Probekalender(heute=datetime(2026, 9, 8)).termine()]

    assert erste == zweite
    assert len(erste) == len(PROBETERMINE)


def test_ein_gestoerter_kalender_meldet_einen_werkzeugfehler():
    """Das Fehlerverhalten bleibt das echte: KalenderFehler wird zu ok=False."""

    ergebnis = _ausfuehren(
        _werkzeug(gestoert="Nicht angemeldet: Zugangsdaten fehlen."), {"zeitraum": "woche"}
    )

    assert ergebnis.ok is False
    assert "angemeldet" in str(ergebnis.error).lower()


def test_der_gestoerte_kalender_wirft_den_echten_fehlertyp():
    with pytest.raises(KalenderFehler):
        Probekalender(gestoert="kaputt").termine()


# --- Der Prüfling bekommt die Lösung nicht geschenkt ----------------------


def test_die_loesung_steht_nicht_in_der_aufgabe():
    stueck = [s for s in katalog().stuecke if s.kennung == "rechner_02"][0]

    assert stueck.erwartet == ("Zahnarzt",)
    assert stueck.werkzeuge == ("termine_ansehen",)
    for erwartet in stueck.erwartet:
        assert erwartet.lower() not in stueck.aufgabe.lower()


def test_rechner_02_ist_jetzt_offline_loesbar():
    """Ohne Google-Konto und ohne Netz - das war der ganze Punkt."""

    stueck = [s for s in katalog().stuecke if s.kennung == "rechner_02"][0]

    assert stueck.offline_loesbar is True


# --- Die Fehlerklassen -----------------------------------------------------


def _stueck(werkzeuge: tuple[str, ...] = ("termine_ansehen",)) -> Pruefstueck:
    return Pruefstueck(
        kennung="rechner_02",
        kategorie="rechnerbedienung",
        aufgabe="Was steht diese Woche in meinem Kalender?",
        art="werkzeug",
        werkzeuge=werkzeuge,
    )


def test_ein_nicht_angemeldetes_werkzeug_ist_ein_umgebungsfehler():
    """Der historische Fall: kein Modell konnte bestehen."""

    klasse, messbar = fehlerklasse_einordnen(
        _stueck(),
        angemeldete_werkzeuge={"aktuelle_zeit", "rechnen"},
        gelaufen=[],
        werkzeugspur=[],
        erfolg=False,
        hinweis="",
    )

    assert klasse == "umgebung"
    assert messbar is False


def test_ein_anmeldefehler_ist_kein_modellfehler():
    klasse, messbar = fehlerklasse_einordnen(
        _stueck(),
        angemeldete_werkzeuge={"termine_ansehen"},
        gelaufen=["termine_ansehen"],
        werkzeugspur=[
            {"werkzeug": "termine_ansehen", "erfolg": False,
             "fehler": "401 Unauthorized: Zugangsdaten abgelehnt"}
        ],
        erfolg=False,
        hinweis="",
    )

    assert klasse == "authentifizierung"
    assert messbar is False


def test_ein_netzfehler_ist_kein_modellfehler():
    klasse, messbar = fehlerklasse_einordnen(
        _stueck(),
        angemeldete_werkzeuge={"termine_ansehen"},
        gelaufen=["termine_ansehen"],
        werkzeugspur=[
            {"werkzeug": "termine_ansehen", "erfolg": False,
             "fehler": "Der Dienst ist nicht erreichbar (timeout)"}
        ],
        erfolg=False,
        hinweis="",
    )

    assert klasse == "umgebung"
    assert messbar is False


def test_kein_werkzeug_gerufen_ist_ein_werkzeugauswahlfehler():
    klasse, messbar = fehlerklasse_einordnen(
        _stueck(),
        angemeldete_werkzeuge={"termine_ansehen"},
        gelaufen=[],
        werkzeugspur=[],
        erfolg=False,
        hinweis="",
    )

    assert klasse == "werkzeugauswahl"
    assert messbar is True


def test_das_falsche_werkzeug_ist_ein_werkzeugauswahlfehler():
    klasse, messbar = fehlerklasse_einordnen(
        _stueck(),
        angemeldete_werkzeuge={"termine_ansehen", "aktuelle_zeit"},
        gelaufen=["aktuelle_zeit"],
        werkzeugspur=[{"werkzeug": "aktuelle_zeit", "erfolg": True, "fehler": ""}],
        erfolg=False,
        hinweis="",
    )

    assert klasse == "werkzeugauswahl"
    assert messbar is True


def test_ein_fachlich_gescheitertes_werkzeug_ist_ein_ausfuehrungsfehler():
    klasse, messbar = fehlerklasse_einordnen(
        _stueck(),
        angemeldete_werkzeuge={"termine_ansehen"},
        gelaufen=["termine_ansehen"],
        werkzeugspur=[
            {"werkzeug": "termine_ansehen", "erfolg": False,
             "fehler": "Der Zeitraum 'uebermorgen' ist unbekannt."}
        ],
        erfolg=False,
        hinweis="",
    )

    assert klasse == "werkzeugausfuehrung"
    assert messbar is True


def test_richtiges_werkzeug_falsche_antwort_ist_ein_modellfehler():
    """Das Werkzeug lief, die Antwort stimmt trotzdem nicht - das zaehlt."""

    klasse, messbar = fehlerklasse_einordnen(
        _stueck(),
        angemeldete_werkzeuge={"termine_ansehen"},
        gelaufen=["termine_ansehen"],
        werkzeugspur=[{"werkzeug": "termine_ansehen", "erfolg": True, "fehler": ""}],
        erfolg=False,
        hinweis="",
    )

    assert klasse == "modell"
    assert messbar is True


def test_ein_erfolg_hat_keine_fehlerklasse():
    klasse, messbar = fehlerklasse_einordnen(
        _stueck(),
        angemeldete_werkzeuge={"termine_ansehen"},
        gelaufen=["termine_ansehen"],
        werkzeugspur=[{"werkzeug": "termine_ansehen", "erfolg": True, "fehler": ""}],
        erfolg=True,
        hinweis="",
    )

    assert klasse == "keiner"
    assert messbar is True


def test_nicht_messbare_faelle_druecken_die_erfolgsquote_nicht():
    from backend.lernen.messwerte import Messung, zusammenfassen

    def _messung(erfolg: bool, messbar: bool, klasse: str) -> Messung:
        return Messung(
            katalog_version="1.2.0", katalog_pruefsumme="x", lauf="T", kategorie="k",
            fall="f", modell="m", erfolg=erfolg, messbar=messbar, fehlerklasse=klasse,
        )

    werte = zusammenfassen(
        [
            _messung(True, True, "keiner"),
            _messung(True, True, "keiner"),
            _messung(False, False, "umgebung"),
        ]
    )

    assert werte["anzahl"] == 3
    assert werte["messbar"] == 2
    assert werte["nicht_messbar"] == 1
    assert werte["erfolgsquote"] == 1.0
    assert werte["fehlerklassen"]["umgebung"] == 1
