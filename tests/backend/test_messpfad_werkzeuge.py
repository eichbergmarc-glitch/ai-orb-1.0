"""Nachweis: Die Kategorien 4 bis 6 sind wirklich messbar.

Der Befund vom 01.09.2026 lautete: Der Messlauf fragte das Modell direkt
und hielt bei Werkzeug-Prüfstücken fest, dass nichts lief. Damit waren
Werkzeugauswahl, Rechnerbedienung und Gedächtnis nicht messbar - man konnte
nur zusehen, wie sie durchfielen.

Diese Datei weist das Gegenteil nach, und zwar mit **echten Werkzeugen**:
``aktuelle_zeit``, ``ordner_auflisten`` und ``karteikarte_anlegen`` sind die
Werkzeuge des Orb, nicht Attrappen. Was hier ersetzt wird, ist allein das
Sprachmodell - es sagt im Test vorhersagbar, welches Werkzeug es will,
damit der Test ohne Netz und ohne Wartezeit reproduzierbar bleibt. Gemessen
wird der Ablauf danach: Lief das Werkzeug? Was gab es zurück? Wie viele
Runden? Warum endete die Schleife?
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from pathlib import Path
from typing import Any

import pytest

from backend.lernen.faehigkeitskatalog import katalog
from backend.lernen.messen import _einen_fall_messen, messen
from backend.lernen.messwerkzeuge import (
    ERLAUBTE_BERECHTIGUNGEN,
    alle_messwerkzeuge,
    messregister,
    messumgebung,
)


class _Modelldoppel:
    """Ein Sprachmodell, das genau die vorgegebenen Antworten gibt.

    Es ersetzt NUR das Modell. Register, Sicherheitsschicht, Werkzeuge und
    Werkzeugschleife sind die echten.
    """

    def __init__(self, antworten: list[str]) -> None:
        self._antworten = list(antworten)
        self.gefragt = 0

    async def complete(self, prompt: str, *, system_prompt: str = "", **_kw: Any) -> str:
        self.gefragt += 1
        if self._antworten:
            return self._antworten.pop(0)
        return "Fertig."

    async def chat(self, messages: Any, **_kw: Any) -> Any:
        class _Antwort:
            text = "Fertig."
            latency_seconds = 0.01

        self.gefragt += 1
        return _Antwort()


def _aufruf(werkzeug: str, **argumente: Any) -> str:
    return json.dumps({"werkzeug": werkzeug, "argumente": argumente}, ensure_ascii=False)


def _schleife(tmp_path: Path, antworten: list[str]) -> tuple[Any, Any, _Modelldoppel]:
    from backend.events.event_bus import EventBus
    from backend.security.security_engine import SecurityEngine
    from backend.tools.tool_engine import ToolEngine

    sicherheit = SecurityEngine(EventBus())
    register = messregister(alle_messwerkzeuge(sicherheit))
    modell = _Modelldoppel(antworten)
    schleife = ToolEngine(
        registry=register,
        security=sicherheit,
        provider_manager=modell,
        event_bus=None,
    )
    return schleife, register, modell


def _messen(stueck: Any, schleife: Any, modell: Any) -> Any:
    return asyncio.run(
        _einen_fall_messen(
            modell,
            stueck,
            modell="testmodell",
            lauf="T1",
            betriebsart="warm",
            werkzeugschleife=schleife,
        )
    )


def _stueck(kennung: str) -> Any:
    for s in katalog().stuecke:
        if s.kennung == kennung:
            return s
    raise AssertionError(f"Pruefstueck '{kennung}' fehlt im Katalog")


# --- Der Werkzeugkasten des Messlaufs ---------------------------------------


def test_der_messkasten_enthaelt_nur_erlaubte_berechtigungen(tmp_path: Path) -> None:
    """Ein Messlauf darf nichts anrichten, was er nicht aufraeumen kann."""

    with messumgebung(tmp_path / "mess"):
        _schleife_, register, _ = _schleife(tmp_path, [])

        assert len(register) >= 10, "der Messkasten ist verdaechtig leer"
        for name in register.names():
            werkzeug = register.get(name)
            assert werkzeug.permission in ERLAUBTE_BERECHTIGUNGEN, (
                f"'{name}' verlangt '{werkzeug.permission}' und gehoert nicht "
                "in einen Messlauf"
            )
        for verboten in ("mail_senden", "terminal_befehl_ausfuehren", "termin_loeschen"):
            assert verboten not in register


def test_der_messlauf_schreibt_nicht_in_die_benutzerdaten(tmp_path: Path) -> None:
    """Die Karteikarte des Messlaufs darf nicht im echten Stapel landen."""

    import os

    from backend.utils.paths import DATA_DIRECTORY_ENVIRONMENT_VARIABLE, get_data_dir

    vorher = get_data_dir()
    with messumgebung(tmp_path / "mess") as ordner:
        assert os.environ[DATA_DIRECTORY_ENVIRONMENT_VARIABLE] == str(ordner)
        assert get_data_dir() != vorher
    assert get_data_dir() == vorher, "die Umgebung wurde nicht zurueckgesetzt"


# --- Kategorie 4: Werkzeugauswahl -------------------------------------------


def test_kategorie_werkzeugwahl_ist_messbar(tmp_path: Path) -> None:
    """``aktuelle_zeit`` laeuft wirklich - und steht in der Werkzeugspur."""

    with messumgebung(tmp_path / "mess"):
        schleife, _register, modell = _schleife(
            tmp_path, [_aufruf("aktuelle_zeit"), "Es ist jetzt soweit."]
        )
        messung = _messen(_stueck("werkzeug_02"), schleife, modell)

    assert messung.kategorie == "werkzeugwahl"
    assert messung.werkzeuge_gelaufen == ["aktuelle_zeit"]
    assert messung.werkzeuge_erfolgreich is True
    assert messung.erfolg is True
    assert messung.runden >= 1
    spur = messung.werkzeugspur[0]
    assert spur["werkzeug"] == "aktuelle_zeit"
    assert spur["erfolg"] is True
    assert spur["ausgabe_zeichen"] > 0, "das Werkzeug hat nichts zurueckgegeben"


def test_ein_nicht_gerufenes_werkzeug_faellt_durch(tmp_path: Path) -> None:
    """Der Gegenbeweis: Ohne Aufruf gibt es keinen Erfolg."""

    with messumgebung(tmp_path / "mess"):
        schleife, _register, modell = _schleife(
            tmp_path, ["Ich habe nachgesehen, es ist Mittag."]
        )
        messung = _messen(_stueck("werkzeug_02"), schleife, modell)

    assert messung.werkzeuge_gelaufen == []
    assert messung.werkzeuge_erfolgreich is False
    assert messung.erfolg is False
    assert messung.werkzeugspur == []


def test_ein_gescheitertes_werkzeug_steht_mit_fehler_in_der_spur(
    tmp_path: Path,
) -> None:
    """Nicht gerufen und gerufen-aber-gescheitert sind zwei Befunde."""

    with messumgebung(tmp_path / "mess"):
        schleife, _register, modell = _schleife(
            tmp_path,
            [_aufruf("ordner_auflisten", pfad="/gibt/es/nicht/12345"), "Fertig."],
        )
        messung = _messen(_stueck("rechner_01"), schleife, modell)

    assert messung.werkzeuge_gelaufen == ["ordner_auflisten"]
    assert messung.werkzeugspur[0]["erfolg"] is False
    assert messung.werkzeugspur[0]["fehler"], "der Fehlertext fehlt in der Spur"
    assert messung.erfolg is False


# --- Kategorie 5: Rechnerbedienung ------------------------------------------


def test_kategorie_rechnerbedienung_ist_messbar(tmp_path: Path) -> None:
    """``ordner_auflisten`` auf einem wirklich vorhandenen Ordner."""

    (tmp_path / "beispiel.txt").write_text("Inhalt", encoding="utf-8")

    with messumgebung(tmp_path / "mess"):
        schleife, _register, modell = _schleife(
            tmp_path,
            [_aufruf("ordner_auflisten", pfad=str(tmp_path)), "Da liegt eine Datei."],
        )
        messung = _messen(_stueck("rechner_01"), schleife, modell)

    assert messung.kategorie == "rechnerbedienung"
    assert messung.werkzeuge_gelaufen == ["ordner_auflisten"]
    assert messung.werkzeugspur[0]["erfolg"] is True
    assert messung.erfolg is True


# --- Kategorie 6: Gedaechtnis -----------------------------------------------


def test_kategorie_gedaechtnis_ist_messbar(tmp_path: Path) -> None:
    """``karteikarte_anlegen`` legt wirklich eine Karte an - im Messordner."""

    with messumgebung(tmp_path / "mess"):
        schleife, _register, modell = _schleife(
            tmp_path,
            [
                _aufruf(
                    "karteikarte_anlegen",
                    frage="Wer schrieb die Kritik der reinen Vernunft?",
                    antwort="Immanuel Kant",
                ),
                "Die Karte liegt im Stapel.",
            ],
        )
        messung = _messen(_stueck("gedaechtnis_02"), schleife, modell)

    assert messung.kategorie == "gedaechtnis"
    assert messung.werkzeuge_gelaufen == ["karteikarte_anlegen"]
    assert messung.werkzeugspur[0]["erfolg"] is True
    assert messung.erfolg is True


def test_die_vorliebe_wird_wirklich_gemerkt(tmp_path: Path) -> None:
    with messumgebung(tmp_path / "mess"):
        schleife, _register, modell = _schleife(
            tmp_path,
            [
                _aufruf(
                    "vorliebe_merken", art="vorliebe", inhalt="Kaffee ohne Zucker"
                ),
                "Gemerkt.",
            ],
        )
        messung = _messen(_stueck("gedaechtnis_01"), schleife, modell)

    assert messung.werkzeuge_gelaufen == ["vorliebe_merken"]
    assert messung.erfolg is True


# --- Der Ablauf, nicht nur die Antwort --------------------------------------


def test_mehrere_runden_werden_gezaehlt(tmp_path: Path) -> None:
    """Rueckkopplung gehoert zur Messung: zwei Werkzeuge, zwei Runden."""

    with messumgebung(tmp_path / "mess"):
        schleife, _register, modell = _schleife(
            tmp_path,
            [
                _aufruf("aktuelle_zeit"),
                _aufruf("rechnen", ausdruck="2+2"),
                "Beides erledigt.",
            ],
        )
        messung = _messen(_stueck("werkzeug_02"), schleife, modell)

    assert messung.runden >= 2
    assert [s["werkzeug"] for s in messung.werkzeugspur] == [
        "aktuelle_zeit",
        "rechnen",
    ]
    assert messung.abbruchgrund != "" or messung.runden >= 2


def test_ein_ungueltiger_aufruf_wird_nicht_ausgefuehrt(tmp_path: Path) -> None:
    """Das Schema aus der Werkzeugmaschine gilt auch im Messlauf."""

    with messumgebung(tmp_path / "mess"):
        schleife, _register, modell = _schleife(
            tmp_path,
            [
                '{"werkzeug": "aktuelle_zeit", "argumente": "keine"}',
                _aufruf("aktuelle_zeit"),
                "Jetzt richtig.",
            ],
        )
        messung = _messen(_stueck("werkzeug_02"), schleife, modell)

    # Der erste, ungueltige Aufruf wurde NICHT ausgefuehrt; der zweite schon.
    assert messung.werkzeugspur
    assert all(s["werkzeug"] == "aktuelle_zeit" for s in messung.werkzeugspur)
    assert modell.gefragt >= 2, "die Reparaturrunde hat nicht stattgefunden"


def test_ohne_werkzeugschleife_bleibt_die_alte_messung(tmp_path: Path) -> None:
    """Die Kategorien ohne Werkzeuge werden weiter an der Antwort gemessen."""

    with messumgebung(tmp_path / "mess"):
        modell = _Modelldoppel([])
        messung = asyncio.run(
            _einen_fall_messen(
                modell,
                _stueck("alltag_02"),
                modell="testmodell",
                lauf="T1",
                betriebsart="warm",
                werkzeugschleife=None,
            )
        )

    assert messung.werkzeugspur == []
    assert messung.kategorie == "alltagsdialog"


def test_jedes_modell_misst_in_seinem_eigenen_ordner(monkeypatch, tmp_path: Path) -> None:
    """Gleiche Bedingungen heisst: jeder faengt bei derselben Ausgangslage an.

    Beim ersten echten Messlauf am 01.09.2026 teilten sich Claude und Ollama
    ein Messverzeichnis. Claude legte in ``gedaechtnis_02`` die Karteikarte
    an; Ollama bekam fuer dieselbe Aufgabe "Im Stapel 'allgemein' gibt es
    diese Frage bereits" und galt als gescheitert. Das ist kein Unterschied
    zwischen den Modellen, sondern einer zwischen der ersten und der zweiten
    Messung - und macht den Vergleich ungueltig.
    """

    from backend.lernen import messen as messmodul

    gesehen: list[Path] = []

    class _Umgebung:
        def __init__(self, ordner: Path) -> None:
            gesehen.append(Path(ordner))

        def __enter__(self):
            raise _Abbruch()

        def __exit__(self, *_a):
            return False

    class _Abbruch(Exception):
        pass

    monkeypatch.setattr(messmodul, "get_data_dir", lambda: tmp_path, raising=False)
    monkeypatch.setattr(
        "backend.lernen.messwerkzeuge.messumgebung", _Umgebung, raising=True
    )
    monkeypatch.setattr("backend.utils.paths.get_data_dir", lambda: tmp_path)

    for modell in ("claude_code", "ollama"):
        with contextlib.suppress(_Abbruch, Exception):
            asyncio.run(messen(modell=modell, lauf="L9", kategorie="gedaechtnis"))

    assert len(gesehen) == 2, f"Messumgebung nicht aufgerufen: {gesehen}"
    assert gesehen[0] != gesehen[1], "beide Modelle messen im selben Ordner"
    assert "claude_code" in gesehen[0].name and "L9" in gesehen[0].name
    assert "ollama" in gesehen[1].name
