"""Regressionstests der Stufe 4: die Vorgaben, die es noch nicht gab.

Vier Dinge standen in den Vorgaben und nicht im Code: der tägliche
Nachrichtenlauf (die Quellen gab es, den Aufrufer nicht), ein ehrlicher
Prüfstempel bei der Fachliteratur, Inhalt statt Titelzeile im Gedächtnis,
und PDF in der Wissensbasis.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

import pytest

from backend.knowledge.knowledge_base import (
    SUPPORTED_SUFFIXES,
    DokumentFehler,
    text_aus_datei,
)
from backend.research.nachrichtenlauf import Nachrichtenlauf


# --- 1. Der tägliche Nachrichtenlauf ---------------------------------------


class _Gedaechtnis:
    def __init__(self) -> None:
        self.eintraege: list[dict[str, Any]] = []

    def remember(self, inhalt: str, **rest: Any) -> object:
        self.eintraege.append({"inhalt": inhalt, **rest})
        return object()


def _lauf(
    *,
    schlagzeilen: Any = None,
    meldungslage: Any = None,
    gedaechtnis: _Gedaechtnis | None = None,
) -> tuple[Nachrichtenlauf, _Gedaechtnis]:
    gedaechtnis = gedaechtnis or _Gedaechtnis()
    lauf = Nachrichtenlauf(
        memory=gedaechtnis,
        themen=["Politik"],
        schlagzeilen=schlagzeilen or (lambda *_a, **_k: []),
        meldungslage=meldungslage or (lambda *_a, **_k: []),
    )
    return lauf, gedaechtnis


def test_der_lauf_legt_meldungen_mit_quelle_ab() -> None:
    lauf, gedaechtnis = _lauf(
        schlagzeilen=lambda *_a, **_k: [
            {"titel": "Etwas ist geschehen", "url": "https://zeitung.example/1",
             "beschreibung": "Und zwar dies."}
        ]
    )

    bericht = asyncio.run(lauf.einmal_laufen())

    assert bericht["gespeichert"] == 1
    eintrag = gedaechtnis.eintraege[0]
    assert "Etwas ist geschehen" in eintrag["inhalt"]
    assert eintrag["source"] == "https://zeitung.example/1"
    assert "nachrichten" in eintrag["tags"]


def test_eine_meldung_ohne_quelle_wird_nicht_gemerkt() -> None:
    """Was sich nicht nachlesen laesst, gehoert nicht ins Gedaechtnis."""

    lauf, gedaechtnis = _lauf(
        schlagzeilen=lambda *_a, **_k: [{"titel": "Ohne Adresse", "url": ""}]
    )

    bericht = asyncio.run(lauf.einmal_laufen())

    assert bericht["gespeichert"] == 0
    assert gedaechtnis.eintraege == []


def test_dieselbe_meldung_kommt_nur_einmal_an() -> None:
    doppelt = [
        {"titel": "Eins", "url": "https://a.example/1"},
        {"titel": "Eins, nochmal", "url": "https://a.example/1"},
    ]
    lauf, _ = _lauf(schlagzeilen=lambda *_a, **_k: doppelt)

    assert asyncio.run(lauf.einmal_laufen())["gespeichert"] == 1


def test_eine_schweigende_quelle_beendet_den_lauf_nicht() -> None:
    """Der Kern der Sache: Was noch antwortet, zaehlt trotzdem."""

    def _kaputt(*_a: Any, **_k: Any) -> list[dict[str, str]]:
        raise RuntimeError("kein Netz")

    lauf, gedaechtnis = _lauf(
        schlagzeilen=_kaputt,
        meldungslage=lambda *_a, **_k: [
            {"titel": "Aus der Meldungslage", "url": "https://b.example/2"}
        ],
    )

    bericht = asyncio.run(lauf.einmal_laufen())

    assert "Schlagzeilen" in bericht["stumme_quellen"]
    assert bericht["gespeichert"] == 1
    assert gedaechtnis.eintraege[0]["tags"][-1] == "politik"


def test_der_wecker_stellt_sich_auf_morgen_wenn_heute_vorbei_ist() -> None:
    from datetime import datetime

    lauf = Nachrichtenlauf(
        memory=_Gedaechtnis(),
        uhrzeit="07:30",
        schlagzeilen=lambda *_a, **_k: [],
        meldungslage=lambda *_a, **_k: [],
    )

    vormittags = lauf.sekunden_bis_zum_lauf(datetime(2026, 8, 31, 6, 0, 0))
    nachmittags = lauf.sekunden_bis_zum_lauf(datetime(2026, 8, 31, 12, 0, 0))

    assert vormittags == pytest.approx(90 * 60, abs=1)
    assert nachmittags == pytest.approx(19.5 * 3600, abs=1)


def test_eine_unlesbare_uhrzeit_faellt_auf_die_vorgabe_zurueck() -> None:
    lauf = Nachrichtenlauf(
        memory=_Gedaechtnis(),
        uhrzeit="viertel nach sieben",
        schlagzeilen=lambda *_a, **_k: [],
        meldungslage=lambda *_a, **_k: [],
    )

    assert lauf.status()["uhrzeit"] == "07:30"


# --- 2. Der Prüfstempel lügt nicht mehr ------------------------------------


def _aktualisierung(tmp_path: Path, quellen: list[Any]) -> Any:
    from backend.studium import aktualisierung as modul

    stand = modul.Aktualisierung.__new__(modul.Aktualisierung)
    stand._daten = {}
    stand._quellen = quellen
    stand._abstand = 0.0
    stand._merken = None
    stand._speichern = lambda: None
    return stand


def test_ein_fehlschlag_ruecke_den_pruefstand_nicht_vor(monkeypatch, tmp_path: Path) -> None:
    """Sonst entsteht ein dauerhaftes Loch in der Literaturliste.

    Alles, was waehrend einer Offline-Phase erschienen ist, wuerde nie
    wieder gesucht - und im Regal stehen ja Eintraege, also faellt es
    niemandem auf.
    """

    from backend.studium import aktualisierung as modul

    def _kaputt(*_a: Any, **_k: Any) -> list[dict[str, str]]:
        raise RuntimeError("kein Netz")

    stand = _aktualisierung(tmp_path, [_kaputt])

    class _Thema:
        kennung = "t"
        titel = "Ein Thema"

    class _Feld:
        def thema(self, _k: str) -> Any:
            return _Thema()

    monkeypatch.setattr(modul, "suchbegriff_fuer", lambda _t: "begriff")
    monkeypatch.setattr(
        "backend.studium.landkarte.feld", lambda _k: _Feld(), raising=False
    )

    ergebnis = stand.auffrischen("f", "t")

    schluessel = stand._schluessel("f", "t")
    assert ergebnis.fehler, "der Fehlschlag muss vermerkt sein"
    assert stand._daten[schluessel]["geprueft_am"] == 0.0, (
        "der Pruefstand darf bei einem Fehlschlag nicht vorruecken"
    )
    assert stand._daten[schluessel]["zuletzt_versucht_am"] > 0.0, (
        "der Versuch muss vermerkt sein, sonst haemmert der Kreislauf"
    )


def test_ein_gelungener_lauf_setzt_den_pruefstand(monkeypatch, tmp_path: Path) -> None:
    from backend.studium import aktualisierung as modul

    stand = _aktualisierung(
        tmp_path,
        [lambda *_a, **_k: [{"titel": "Neu", "url": "https://x.example/1"}]],
    )

    class _Thema:
        kennung = "t"
        titel = "Ein Thema"

    class _Feld:
        def thema(self, _k: str) -> Any:
            return _Thema()

    monkeypatch.setattr(modul, "suchbegriff_fuer", lambda _t: "begriff")
    monkeypatch.setattr(
        "backend.studium.landkarte.feld", lambda _k: _Feld(), raising=False
    )

    stand.auffrischen("f", "t")

    assert stand._daten[stand._schluessel("f", "t")]["geprueft_am"] > 0.0


# --- 3. Fachliteratur wird nicht mehr weggeräumt ---------------------------


def test_publikationen_unterliegen_nicht_dem_vergessen() -> None:
    """Eine Literaturliste, die sich selbst leert, ist keine."""

    import inspect

    from backend.memory.memory_engine import MemoryEngine

    quelle = inspect.getsource(MemoryEngine.apply_forgetting)

    assert '"publikation"' in quelle


# --- 4. PDF kommt in die Wissensbasis --------------------------------------


def test_pdf_und_word_sind_zugelassen() -> None:
    """Fachliteratur liegt praktisch immer als PDF vor."""

    assert ".pdf" in SUPPORTED_SUFFIXES
    assert ".docx" in SUPPORTED_SUFFIXES


def test_ein_fehlendes_paket_wird_im_klartext_gemeldet(tmp_path: Path, monkeypatch) -> None:
    """Kein Absturz, kein Schweigen - ein Satz, der sagt, was zu tun ist."""

    import builtins

    echt = builtins.__import__

    def _ohne_pypdf(name: str, *rest: Any, **kw: Any) -> Any:
        if name in {"pypdf", "PyPDF2"}:
            raise ImportError(name)
        return echt(name, *rest, **kw)

    monkeypatch.setattr(builtins, "__import__", _ohne_pypdf)
    pfad = tmp_path / "arbeit.pdf"
    pfad.write_bytes(b"%PDF-1.4")

    with pytest.raises(DokumentFehler) as fehler:
        text_aus_datei(pfad)

    assert "pypdf" in str(fehler.value)


def test_gewoehnlicher_text_geht_weiterhin_durch(tmp_path: Path) -> None:
    pfad = tmp_path / "notiz.md"
    pfad.write_text("# Überschrift\n\nInhalt.", encoding="utf-8")

    assert "Inhalt." in text_aus_datei(pfad)


# --- 5. Die Karteikarten sind angemeldet -----------------------------------


def test_die_karteikarten_sind_werkzeuge() -> None:
    """Was nicht in der Werkzeugliste steht, gibt es fuer das Modell nicht."""

    from backend.learning.flashcards import FlashcardDeck
    from backend.tools.karteikarten_tools import build_karteikarten_tools
    from backend.tools.registry import ToolRegistry

    register = ToolRegistry()
    aufgenommen = register.register_many(build_karteikarten_tools(FlashcardDeck()))

    assert aufgenommen == 4
    assert "karteikarte_anlegen" in register
    assert "karteikarten_abfragen" in register
    assert "karteikarte_bewerten" in register
    assert "karteikarten_stand" in register


def test_der_nachrichtenlauf_ist_im_start_verdrahtet() -> None:
    """Der Befund war genau dies: Es gab die Quellen, aber keinen Aufrufer."""

    import inspect

    from backend.runtime import Runtime

    quelle = inspect.getsource(Runtime._boot)

    assert "_nachrichtenschleife" in quelle
