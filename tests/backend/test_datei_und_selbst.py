"""Tests der neuen Werkzeuge: schreiben, sich selbst aendern, neu starten.

Der Orb konnte Dateien lesen, auflisten und suchen - aber keine einzige
schreiben. "Schreib mir das in eine Textdatei" endete deshalb damit, dass
er den Text vorlas und die Datei nirgends entstand.

Und er konnte nicht an sich selbst arbeiten. Die Maschinerie dafuer gab es
laengst (backend/evolution), sie war nur nie als Werkzeug angeschlossen.

Geprueft wird hier vor allem das, was schiefgehen koennte: dass nichts
ungefragt ueberschrieben wird, dass ein Syntaxfehler die Datei gar nicht
erst erreicht, und dass ein Neustart nicht angestossen wird, wenn der Weg
zurueck fehlt.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from backend.events.event_bus import EventBus
from backend.security.security_engine import SecurityEngine
from backend.system.restart import Neustarter, finde_startweg, helferskript
from backend.tools.file_tools import CreateDirectoryTool, WriteFileTool
from backend.tools.self_tools import (
    ChangeOwnCodeTool,
    ReadOwnCodeTool,
    RestartTool,
    UndoOwnChangeTool,
)


def _fuehre_aus(werkzeug, **argumente):
    return asyncio.run(werkzeug.execute(argumente))


def _security() -> SecurityEngine:
    return SecurityEngine(EventBus())


# --- Dateien schreiben --------------------------------------------------------


def test_datei_wird_angelegt(tmp_path: Path):
    ziel = tmp_path / "notiz.txt"
    ergebnis = _fuehre_aus(
        WriteFileTool(_security()), pfad=str(ziel), inhalt="Hallo Welt"
    )

    assert ergebnis.ok, ergebnis.error
    assert ziel.read_text(encoding="utf-8") == "Hallo Welt"


def test_fehlende_ordner_entstehen_mit(tmp_path: Path):
    ziel = tmp_path / "a" / "b" / "c" / "notiz.txt"
    ergebnis = _fuehre_aus(WriteFileTool(_security()), pfad=str(ziel), inhalt="Tief")

    assert ergebnis.ok, ergebnis.error
    assert ziel.read_text(encoding="utf-8") == "Tief"


def test_bestehende_datei_wird_nicht_ungefragt_ueberschrieben(tmp_path: Path):
    """Ein vertippter Dateiname darf keine Arbeit vernichten."""

    ziel = tmp_path / "wichtig.txt"
    ziel.write_text("Monatelange Arbeit", encoding="utf-8")

    ergebnis = _fuehre_aus(WriteFileTool(_security()), pfad=str(ziel), inhalt="weg")

    assert not ergebnis.ok
    assert "gibt es bereits" in ergebnis.error
    assert ziel.read_text(encoding="utf-8") == "Monatelange Arbeit"


def test_mit_ausdruecklicher_erlaubnis_wird_ersetzt(tmp_path: Path):
    ziel = tmp_path / "wichtig.txt"
    ziel.write_text("alt", encoding="utf-8")

    ergebnis = _fuehre_aus(
        WriteFileTool(_security()), pfad=str(ziel), inhalt="neu", ueberschreiben=True
    )

    assert ergebnis.ok, ergebnis.error
    assert ziel.read_text(encoding="utf-8") == "neu"


def test_anhaengen_haengt_unten_an(tmp_path: Path):
    ziel = tmp_path / "liste.txt"
    ziel.write_text("Erster Punkt", encoding="utf-8")

    ergebnis = _fuehre_aus(
        WriteFileTool(_security()), pfad=str(ziel), inhalt="Zweiter Punkt", anhaengen=True
    )

    assert ergebnis.ok, ergebnis.error
    assert ziel.read_text(encoding="utf-8") == "Erster Punkt\nZweiter Punkt"


def test_auf_einen_ordner_wird_nicht_geschrieben(tmp_path: Path):
    ergebnis = _fuehre_aus(
        WriteFileTool(_security()), pfad=str(tmp_path), inhalt="egal", ueberschreiben=True
    )

    assert not ergebnis.ok
    assert "Ordner" in ergebnis.error


def test_ordner_anlegen(tmp_path: Path):
    ziel = tmp_path / "neu" / "tiefer"
    ergebnis = _fuehre_aus(CreateDirectoryTool(_security()), pfad=str(ziel))

    assert ergebnis.ok, ergebnis.error
    assert ziel.is_dir()

    # Zweimal ist kein Fehler.
    nochmal = _fuehre_aus(CreateDirectoryTool(_security()), pfad=str(ziel))
    assert nochmal.ok


# --- Den eigenen Code lesen ---------------------------------------------------


def test_eigener_code_wird_mit_zeilennummern_gelesen():
    ergebnis = _fuehre_aus(
        ReadOwnCodeTool(), pfad="backend/__init__.py", von_zeile=1, zeilen=5
    )

    assert ergebnis.ok, ergebnis.error
    assert "backend/__init__.py" in ergebnis.output
    assert "    1  " in ergebnis.output


def test_fremde_pfade_sind_kein_eigener_code(tmp_path: Path):
    ergebnis = _fuehre_aus(ReadOwnCodeTool(), pfad=str(tmp_path / "fremd.py"))

    assert not ergebnis.ok
    assert "nicht im Programmordner" in ergebnis.error


def test_die_sicherheitsschicht_ist_ausgenommen():
    """Ein Fehler dort liesse sich nicht mehr zuruecknehmen."""

    ergebnis = _fuehre_aus(ReadOwnCodeTool(), pfad="backend/security/permissions.py")

    assert not ergebnis.ok
    assert "ausgenommen" in ergebnis.error


# --- Den eigenen Code aendern -------------------------------------------------


class _Rollback:
    """Ein Wiederherstellungsverwalter, der sich alles merkt."""

    def __init__(self, wurzel: Path):
        self.wurzel = wurzel
        self.punkte: list[tuple[str, str]] = []

    def create_point(self, *, patch_id, title, description, branch, commit, version, files, test_summary=""):
        for relativ in files:
            quelle = self.wurzel / relativ
            if quelle.exists():
                self.punkte.append((relativ, quelle.read_text(encoding="utf-8")))

        class _Punkt:
            id = f"punkt-{len(self.punkte)}"

        return _Punkt()

    def undo_last(self):
        if not self.punkte:
            return {"restored": False, "message": "Nichts zurueckzunehmen."}
        relativ, inhalt = self.punkte.pop()
        (self.wurzel / relativ).write_text(inhalt, encoding="utf-8")
        return {"restored": True, "restored_files": [relativ], "message": "Zurueckgesetzt."}


def _mit_probedatei(tmp_path: Path, monkeypatch, inhalt: str) -> tuple[Path, _Rollback]:
    """Legt eine Probedatei an und laesst sie als 'eigener Code' gelten."""

    import backend.tools.self_tools as selbst

    wurzel = tmp_path / "programm"
    (wurzel / "backend").mkdir(parents=True)
    datei = wurzel / "backend" / "probe.py"
    datei.write_text(inhalt, encoding="utf-8")

    monkeypatch.setattr(selbst, "get_project_root", lambda: wurzel)
    return datei, _Rollback(wurzel)


def test_aenderung_wird_geschrieben(tmp_path: Path, monkeypatch):
    datei, rollback = _mit_probedatei(tmp_path, monkeypatch, "wert = 1\n")

    ergebnis = _fuehre_aus(
        ChangeOwnCodeTool(rollback),
        pfad="backend/probe.py",
        inhalt="wert = 2\n",
        begruendung="Zwei ist besser",
    )

    assert ergebnis.ok, ergebnis.error
    assert datei.read_text(encoding="utf-8") == "wert = 2\n"
    assert ergebnis.context["needs_restart"] is True
    assert "Neustart" in ergebnis.output


def test_syntaxfehler_erreicht_die_datei_gar_nicht(tmp_path: Path, monkeypatch):
    """Der wichtigste Test dieser Datei.

    Ein Syntaxfehler in einer Kerndatei hiesse: Der Orb kommt beim naechsten
    Start nicht mehr hoch - und dann waere niemand mehr da, der ihn
    zuruecksetzen koennte.
    """

    datei, rollback = _mit_probedatei(tmp_path, monkeypatch, "wert = 1\n")

    ergebnis = _fuehre_aus(
        ChangeOwnCodeTool(rollback),
        pfad="backend/probe.py",
        inhalt="def kaputt(\n",
        begruendung="Versehen",
    )

    assert not ergebnis.ok
    assert "nicht geschrieben" in ergebnis.error
    assert datei.read_text(encoding="utf-8") == "wert = 1\n", "die Datei wurde angefasst"


def test_ohne_sicherung_wird_nichts_geaendert(tmp_path: Path, monkeypatch):
    """Ein Netz, das nach dem Sprung gespannt wird, ist keines."""

    datei, _ = _mit_probedatei(tmp_path, monkeypatch, "wert = 1\n")

    class _Kaputt:
        def create_point(self, **kw):
            raise OSError("Platte voll")

    ergebnis = _fuehre_aus(
        ChangeOwnCodeTool(_Kaputt()),
        pfad="backend/probe.py",
        inhalt="wert = 99\n",
        begruendung="egal",
    )

    assert not ergebnis.ok
    assert "keine Sicherung" in ergebnis.error
    assert datei.read_text(encoding="utf-8") == "wert = 1\n"


def test_zuruecknehmen_holt_die_alte_fassung(tmp_path: Path, monkeypatch):
    datei, rollback = _mit_probedatei(tmp_path, monkeypatch, "wert = 1\n")

    _fuehre_aus(
        ChangeOwnCodeTool(rollback),
        pfad="backend/probe.py",
        inhalt="wert = 2\n",
        begruendung="Versuch",
    )
    assert datei.read_text(encoding="utf-8") == "wert = 2\n"

    ergebnis = _fuehre_aus(UndoOwnChangeTool(rollback))

    assert ergebnis.ok, ergebnis.error
    assert datei.read_text(encoding="utf-8") == "wert = 1\n"
    assert ergebnis.context["needs_restart"] is True


# --- Neu starten ---------------------------------------------------------------


def test_ohne_startweg_wird_nicht_neu_gestartet():
    """Lieber laufen bleiben als nicht wiederkommen."""

    neustarter = Neustarter(startweg=None)
    neustarter._startweg = None
    neustarter.startweg = lambda: None  # type: ignore[method-assign]

    ok, meldung = neustarter.anfordern("Probe")

    assert ok is False
    assert "finde meinen eigenen Startweg nicht" in meldung
    assert neustarter.laeuft is False


def test_neustart_wird_angestossen(tmp_path: Path, monkeypatch):
    weg = tmp_path / "ORB-STARTEN.bat"
    weg.write_text("echo start", encoding="utf-8")

    gestartet: list[Path] = []
    neustarter = Neustarter(startweg=weg, warten=1)
    monkeypatch.setattr(neustarter, "_starte_helfer", lambda helfer: gestartet.append(helfer))

    ok, meldung = neustarter.anfordern("nach einer Aenderung")

    assert ok is True
    assert "starte mich" in meldung
    assert len(gestartet) == 1
    assert gestartet[0].exists(), "der Helfer wurde nicht geschrieben"
    assert str(weg) in gestartet[0].read_text(encoding="utf-8", errors="replace")


def test_zweimal_anfordern_startet_nur_einen_helfer(tmp_path: Path, monkeypatch):
    """Zwei Helfer waeren kein doppelter Neustart, sondern ein Wettlauf."""

    weg = tmp_path / "ORB-STARTEN.bat"
    weg.write_text("echo start", encoding="utf-8")

    gestartet: list[Path] = []
    neustarter = Neustarter(startweg=weg, warten=1)
    monkeypatch.setattr(neustarter, "_starte_helfer", lambda helfer: gestartet.append(helfer))

    neustarter.anfordern("erst")
    ok, _ = neustarter.anfordern("dann")

    assert ok is True
    assert len(gestartet) == 1


def test_helferskript_wartet_beendet_und_startet(tmp_path: Path):
    """Die Reihenfolge ist der ganze Sinn des Helfers."""

    weg = tmp_path / "AI-Orb.exe"
    text = helferskript(weg, warten=6, eltern_pid=4242)

    assert "6" in text
    assert str(weg) in text
    # Erst warten, dann beenden, dann starten.
    reihenfolge = [
        text.find("6"),
        max(text.find("taskkill"), text.find("kill")),
        max(text.find("start"), text.find("exec")),
    ]
    assert reihenfolge == sorted(reihenfolge), f"falsche Reihenfolge: {text}"


def test_beendet_wird_ueber_die_prozessnummer(tmp_path: Path):
    """Nicht ueber den Programmnamen - der trifft bei der Arbeitsfassung
    'electron.exe', und davon laufen gern mehrere, die nichts miteinander
    zu tun haben."""

    text = helferskript(tmp_path / "start.bat", warten=2, eltern_pid=4242)

    assert "4242" in text
    assert "electron" not in text.lower()
    assert "AI-Orb.exe" not in text, "es wurde doch ueber den Namen beendet"


def test_ohne_prozessnummer_bleibt_der_name(tmp_path: Path):
    """Ungenauer, aber besser als gar nicht."""

    text = helferskript(tmp_path / "start.bat", warten=2, eltern_pid=0)

    assert "AI-Orb" in text or "pkill" in text


def test_startweg_wird_neben_dem_programm_gefunden(tmp_path: Path):
    wurzel = tmp_path / "AI-Orb"
    wurzel.mkdir()
    (wurzel / "ORB-STARTEN.bat").write_text("echo", encoding="utf-8")

    assert finde_startweg(wurzel) == wurzel / "ORB-STARTEN.bat"


def test_installierte_fassung_wird_gefunden(tmp_path: Path):
    """Bei der Installation liegt die Exe zwei Ebenen ueber dem Code."""

    programm = tmp_path / "AI-Orb"
    (programm / "resources" / "app").mkdir(parents=True)
    exe = programm / "AI-Orb.exe"
    exe.write_text("", encoding="utf-8")

    assert finde_startweg(programm / "resources" / "app") == exe


def test_werkzeug_meldet_den_neustart_verstaendlich(tmp_path: Path, monkeypatch):
    weg = tmp_path / "ORB-STARTEN.bat"
    weg.write_text("echo", encoding="utf-8")
    neustarter = Neustarter(startweg=weg, warten=2)
    monkeypatch.setattr(neustarter, "_starte_helfer", lambda helfer: None)

    ergebnis = _fuehre_aus(RestartTool(neustarter), grund="nach einer Aenderung")

    assert ergebnis.ok, ergebnis.error
    assert ergebnis.context["restarting"] is True
    assert "kommt von selbst zurück" in ergebnis.output
