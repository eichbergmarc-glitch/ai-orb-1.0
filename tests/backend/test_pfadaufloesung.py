"""Die Auflösung von Ordnernamen - der Fall, an dem der Messlauf scheiterte.

Am 1. September 2026 rief das Modell ``ordner_auflisten`` mit dem blossen
Wort ``Dokumente`` auf. Ein blosser Name ist ein relativer Pfad, und der
wurde gegen das Arbeitsverzeichnis aufgelöst - also gegen den
Programmordner. Windows meldete
``WinError 3: ... 'C:\\Users\\info\\AI-Orb\\Dokumente'``.

Diese Tests halten beides fest: dass persönliche Ordner jetzt gefunden
werden, UND dass echte Projektpfade dabei nicht verlorengehen.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from backend.security.path_guard import (
    BEKANNTE_ORDNER,
    PathGuard,
    bekannten_ordner_finden,
)


@pytest.fixture
def heim(tmp_path: Path, monkeypatch) -> Path:
    """Ein Heimatordner zum Anfassen, mit einem echten Dokumente-Ordner."""

    zuhause = tmp_path / "heim"
    (zuhause / "Documents").mkdir(parents=True)
    (zuhause / "Downloads").mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: zuhause))
    monkeypatch.setattr(
        "backend.security.path_guard._windows_bekannter_ordner", lambda _guid: None
    )
    return zuhause


def _waechter() -> PathGuard:
    """Ein Wächter im offenen Modus - hier geht es um die Auflösung."""

    return PathGuard(unrestricted=True)


# --- Der Fall aus dem Messlauf --------------------------------------------


def test_dokumente_landet_im_persoenlichen_ordner(heim: Path, tmp_path: Path, monkeypatch):
    """Der WinError-3-Fall: 'Dokumente' darf nicht im Programmordner suchen."""

    arbeitsordner = tmp_path / "AI-Orb"
    arbeitsordner.mkdir()
    monkeypatch.chdir(arbeitsordner)

    entscheidung = _waechter().check_directory("Dokumente")

    assert entscheidung.allowed, entscheidung.reason
    assert entscheidung.path == (heim / "Documents").resolve()
    # Und ausdruecklich NICHT im Programmordner:
    assert arbeitsordner not in entscheidung.path.parents


def test_der_alte_fehlerfall_ist_kein_fehler_mehr(heim: Path, tmp_path: Path, monkeypatch):
    """Derselbe Aufruf, den Ollama im Lauf L2 gemacht hat."""

    import asyncio

    from backend.tools.standard_tools import ListDirectoryTool

    arbeitsordner = tmp_path / "AI-Orb"
    arbeitsordner.mkdir()
    monkeypatch.chdir(arbeitsordner)
    (heim / "Documents" / "brief.txt").write_text("Hallo", encoding="utf-8")

    class _Sicherheit:
        paths = _waechter()

    ergebnis = asyncio.run(ListDirectoryTool(_Sicherheit()).execute({"pfad": "Dokumente"}))

    assert ergebnis.ok, ergebnis.error
    assert "brief.txt" in str(ergebnis.output)
    assert "WinError" not in str(ergebnis.error or "")


def test_englischer_name_findet_denselben_ordner(heim: Path, monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    assert bekannten_ordner_finden("Documents") == heim / "Documents"
    assert bekannten_ordner_finden("dokumente") == heim / "Documents"
    assert bekannten_ordner_finden("DOKUMENTE") == heim / "Documents"


def test_ein_unterordner_des_persoenlichen_ordners(heim: Path, tmp_path: Path, monkeypatch):
    """'Dokumente/Rechnungen' muss ebenso ankommen wie 'Dokumente'."""

    monkeypatch.chdir(tmp_path)
    (heim / "Documents" / "Rechnungen").mkdir()

    entscheidung = _waechter().check_directory(os.path.join("Dokumente", "Rechnungen"))

    assert entscheidung.allowed
    assert entscheidung.path == (heim / "Documents" / "Rechnungen").resolve()


def test_onedrive_umleitung_wird_gefunden(tmp_path: Path, monkeypatch):
    """Unter OneDrive liegt 'Dokumente' nicht im Heimatordner selbst."""

    zuhause = tmp_path / "heim"
    ziel = zuhause / "OneDrive - Persoenlich" / "Dokumente"
    ziel.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: zuhause))
    monkeypatch.setattr(
        "backend.security.path_guard._windows_bekannter_ordner", lambda _guid: None
    )

    assert bekannten_ordner_finden("Dokumente") == ziel


def test_die_windows_auskunft_hat_vorrang(tmp_path: Path, monkeypatch):
    """Was Windows selbst sagt, schlaegt jede Vermutung ueber Ordnernamen."""

    zuhause = tmp_path / "heim"
    (zuhause / "Documents").mkdir(parents=True)
    umgeleitet = tmp_path / "woanders" / "Dokumente"
    umgeleitet.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: zuhause))
    monkeypatch.setattr(
        "backend.security.path_guard._windows_bekannter_ordner",
        lambda _guid: umgeleitet,
    )

    assert bekannten_ordner_finden("Dokumente") == umgeleitet


# --- Was NICHT passieren darf ---------------------------------------------


def test_ein_echter_projektpfad_bleibt_ein_projektpfad(heim: Path, tmp_path: Path, monkeypatch):
    """Gibt es den relativen Ordner wirklich, gewinnt er - immer."""

    arbeitsordner = tmp_path / "projekt"
    (arbeitsordner / "Dokumente").mkdir(parents=True)
    (arbeitsordner / "Dokumente" / "projektdatei.txt").write_text("x", encoding="utf-8")
    monkeypatch.chdir(arbeitsordner)

    entscheidung = _waechter().check_directory("Dokumente")

    assert entscheidung.path == (arbeitsordner / "Dokumente").resolve()
    assert entscheidung.path != (heim / "Documents").resolve()


def test_ein_gewoehnlicher_relativer_pfad_bleibt_unberuehrt(tmp_path: Path, monkeypatch):
    arbeitsordner = tmp_path / "projekt"
    (arbeitsordner / "backend" / "lernen").mkdir(parents=True)
    monkeypatch.chdir(arbeitsordner)

    entscheidung = _waechter().check_directory(os.path.join("backend", "lernen"))

    assert entscheidung.allowed
    assert entscheidung.path == (arbeitsordner / "backend" / "lernen").resolve()


def test_ein_absoluter_pfad_bleibt_absolut(tmp_path: Path, monkeypatch):
    ziel = tmp_path / "irgendwo" / "Dokumente"
    ziel.mkdir(parents=True)
    monkeypatch.chdir(tmp_path)

    entscheidung = _waechter().check_directory(str(ziel))

    assert entscheidung.allowed
    assert entscheidung.path == ziel.resolve()


def test_ein_nicht_vorhandener_pfad_wird_abgelehnt(heim: Path, tmp_path: Path, monkeypatch):
    """Im geschuetzten Modus - der offene sagt zu jedem Pfad ja."""

    monkeypatch.chdir(tmp_path)
    waechter = PathGuard([str(heim)])

    entscheidung = waechter.check_directory("gibtesnicht")

    assert not entscheidung.allowed
    assert entscheidung.reason


def test_ein_nicht_vorhandener_unterordner_wird_abgelehnt(
    heim: Path, tmp_path: Path, monkeypatch
):
    """Auch 'Dokumente/gibtesnicht' bleibt ein Fehlschlag - mit klarem Pfad."""

    monkeypatch.chdir(tmp_path)
    waechter = PathGuard([str(heim)])

    entscheidung = waechter.check_directory(os.path.join("Dokumente", "gibtesnicht"))

    assert not entscheidung.allowed
    assert entscheidung.path == (heim / "Documents" / "gibtesnicht").resolve()


def test_ein_unbekannter_name_wird_nicht_umgedeutet(heim: Path, tmp_path: Path, monkeypatch):
    """Nur die Liste zählt - 'Steuerkram' ist kein persönlicher Ordner."""

    monkeypatch.chdir(tmp_path)

    assert bekannten_ordner_finden("Steuerkram") is None


# --- Umlaute und Leerzeichen ----------------------------------------------


def test_umlaute_und_leerzeichen_im_pfad(tmp_path: Path, monkeypatch):
    ordner = tmp_path / "Meine Bücher" / "Größere Ordner"
    ordner.mkdir(parents=True)
    (ordner / "übersicht.txt").write_text("x", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    entscheidung = _waechter().check_directory(os.path.join("Meine Bücher", "Größere Ordner"))

    assert entscheidung.allowed, entscheidung.reason
    assert entscheidung.path == ordner.resolve()


def test_umlaute_unter_einem_persoenlichen_ordner(heim: Path, tmp_path: Path, monkeypatch):
    ziel = heim / "Documents" / "Persönliche Briefe"
    ziel.mkdir(parents=True)
    monkeypatch.chdir(tmp_path)

    entscheidung = _waechter().check_directory(os.path.join("Dokumente", "Persönliche Briefe"))

    assert entscheidung.allowed
    assert entscheidung.path == ziel.resolve()


def test_ein_pfad_in_anfuehrungszeichen(heim: Path, tmp_path: Path, monkeypatch):
    """Modelle setzen Pfade gern in Anführungszeichen."""

    monkeypatch.chdir(tmp_path)

    entscheidung = _waechter().check_directory('"Dokumente"')

    assert entscheidung.allowed
    assert entscheidung.path == (heim / "Documents").resolve()


# --- Die Liste selbst ------------------------------------------------------


def test_die_liste_kennt_deutsche_und_englische_namen():
    for name in ("dokumente", "documents", "downloads", "bilder", "pictures", "desktop"):
        assert name in BEKANNTE_ORDNER
    for guid, ordner in BEKANNTE_ORDNER.values():
        assert guid.startswith("{") and guid.endswith("}")
        assert ordner


def test_keine_fest_verdrahteten_benutzerpfade():
    """Kein Pfad eines bestimmten Menschen darf im Code stehen.

    Geprueft wird der Code, nicht die Erklaerung: Im Kommentar steht der
    historische Fehlerpfad aus dem Messlauf, und dort gehoert er auch hin.
    """

    zeilen = Path("backend/security/path_guard.py").read_text(encoding="utf-8").splitlines()
    anfaenge = ("#", '"""', "'''", "*", ":")
    code = [z for z in zeilen if not z.lstrip().startswith(anfaenge)]
    for verboten in ("C:\\Users\\", "/home/", "/Users/"):
        treffer = [z for z in code if verboten in z]
        assert not treffer, f"fester Benutzerpfad im Code: {treffer}"
