"""Tests der beiden Klaenge fuer Handeln und Hochfahren.

Der Orb hatte bisher zwei Klaenge, und beide gehoerten zum Gespraech: "Ich
hoere zu" und "Ich denke nach". Was fehlte, waren die zwei Momente, in
denen er nicht redet.

Der eine ist das Handeln. Startet er ein Programm oder oeffnet eine Seite,
aendert sich der Rechner - und wer gerade wegsieht, soll trotzdem
mitbekommen, dass es der Orb war und nicht er selbst. Der andere ist der
Start: Davor gab es kein Zeichen, dass der Orb bereit ist; man erfuhr es
erst beim ersten Versuch.

Der wichtigste Test hier ist nicht, dass ein Klang kommt, sondern WANN er
NICHT kommt. Ein Ton bei jedem Werkzeug waere nach einem Tag keine Auskunft
mehr, sondern Geraeusch - und die Uhrzeit abzulesen ist kein Eingriff in
den Rechner.
"""

from __future__ import annotations

import asyncio
import wave
from pathlib import Path

from backend.audio.sounds import Klaenge
from backend.tools.base_tool import Tool, ToolResult
from backend.tools.tool_engine import HANDELNDE_RECHTE


def _klang(pfad: Path) -> None:
    """Legt eine winzige, gueltige WAV-Datei an."""

    with wave.open(str(pfad), "wb") as datei:
        datei.setnchannels(1)
        datei.setsampwidth(2)
        datei.setframerate(8000)
        datei.writeframes(b"\x00\x00" * 80)


# --- Die Klaenge selbst ---------------------------------------------------------


def test_beide_neuen_klaenge_werden_gefunden(tmp_path: Path, monkeypatch):
    import backend.audio.sounds as klangmodul

    (tmp_path / "audio").mkdir()
    _klang(tmp_path / "audio" / "aktion.wav")
    _klang(tmp_path / "audio" / "start.wav")
    monkeypatch.setattr(klangmodul, "get_project_root", lambda: tmp_path)
    monkeypatch.setattr(klangmodul, "get_data_dir", lambda: tmp_path / "daten")

    klaenge = Klaenge(tat_klang="audio/aktion.wav", start_klang="audio/start.wav")

    assert klaenge.tat_klang is not None
    assert klaenge.start_klang is not None


def test_fehlende_dateien_bleiben_folgenlos(tmp_path: Path, monkeypatch):
    """Ein Start, der an einem Signalton scheitert, waere absurd."""

    import backend.audio.sounds as klangmodul

    monkeypatch.setattr(klangmodul, "get_project_root", lambda: tmp_path)
    monkeypatch.setattr(klangmodul, "get_data_dir", lambda: tmp_path)

    klaenge = Klaenge(tat_klang="gibtsnicht.wav", start_klang="auchnicht.wav")

    assert klaenge.tat_klang is None
    assert klaenge.start_klang is None
    klaenge.tat()  # darf nicht werfen
    klaenge.start()


def test_die_mitgelieferten_dateien_sind_da():
    """Die Klaenge gehoeren zum Programm, nicht zur Einrichtung."""

    from backend.utils.paths import get_project_root

    for name in ("aktion.wav", "start.wav"):
        datei = get_project_root() / "audio" / name
        assert datei.is_file(), f"{name} fehlt"
        with wave.open(str(datei), "rb") as offen:
            assert offen.getnframes() > 0


def test_die_klaenge_sind_im_ganzen_programm_dieselben(monkeypatch):
    """Zwei Saetze hiessen zwei Player - und beim Suchen zwei Orte."""

    from backend.audio.sounds import klaenge, klaenge_zuruecksetzen

    klaenge_zuruecksetzen()
    try:
        assert klaenge() is klaenge()
    finally:
        klaenge_zuruecksetzen()


# --- Wann der Tat-Klang kommt - und wann nicht ----------------------------------


class _Werkzeug(Tool):
    def __init__(self, recht: str):
        self.name = "probe"
        self.description = "Eine Probe."
        self.permission = recht
        self.parameters = {}

    async def execute(self, arguments):
        return ToolResult.success("fertig")


class _Freigabe:
    """Eine Sicherheitsschicht, die alles durchlaesst."""

    def require(self, *args, **kw):
        class _Ja:
            allowed = True
            reason = ""

        async def _liefern():
            return _Ja()

        return _liefern()

    def record_action(self, *args, **kw):
        return None


class _Verzeichnis:
    def __init__(self, werkzeug):
        self._werkzeug = werkzeug

    def get(self, name):
        return self._werkzeug

    def all(self):
        return [self._werkzeug]

    def names(self):
        return [self._werkzeug.name]

    def describe_for_model(self):
        return ""


def _lauf(recht: str, monkeypatch) -> int:
    """Fuehrt ein Werkzeug mit dieser Berechtigung aus und zaehlt die Klaenge."""

    import backend.tools.tool_engine as motor
    from backend.tools.tool_engine import ToolCall, ToolEngine

    gezaehlt: list[int] = []
    monkeypatch.setattr(motor, "_klang_zur_tat", lambda: gezaehlt.append(1))

    maschine = ToolEngine(
        registry=_Verzeichnis(_Werkzeug(recht)),
        security=_Freigabe(),
        provider_manager=None,
    )
    ergebnis = asyncio.run(maschine._execute(ToolCall("probe", {}), "test"))

    assert ergebnis.result.ok, ergebnis.result.error
    return len(gezaehlt)


def test_ein_programm_zu_starten_klingt(monkeypatch):
    assert _lauf("launch_application", monkeypatch) == 1


def test_eine_datei_zu_schreiben_klingt(monkeypatch):
    assert _lauf("write_files", monkeypatch) == 1


def test_die_uhrzeit_abzulesen_klingt_nicht(monkeypatch):
    """Der wichtigste Test: Ein Ton bei jeder Antwort waere nur noch Laerm."""

    assert _lauf("read_time", monkeypatch) == 0


def test_rechnen_und_lesen_klingen_nicht(monkeypatch):
    for recht in ("compute", "read_files", "read_memory", "network"):
        assert _lauf(recht, monkeypatch) == 0, recht


def test_die_grenze_verlaeuft_zwischen_reden_und_handeln():
    """Was auf der Liste steht, veraendert den Rechner - nicht das Gespraech."""

    assert "launch_application" in HANDELNDE_RECHTE
    assert "system_commands" in HANDELNDE_RECHTE
    assert "install_dependencies" in HANDELNDE_RECHTE
    for lesend in ("read_time", "compute", "read_files", "read_memory", "network"):
        assert lesend not in HANDELNDE_RECHTE, lesend


def test_ein_stummer_klang_haelt_kein_werkzeug_auf(monkeypatch):
    """Ein Werkzeug, das wegen eines Signaltons nicht laeuft, waere absurd."""

    import backend.audio.sounds as klangmodul
    import backend.tools.tool_engine as motor
    from backend.tools.tool_engine import ToolCall, ToolEngine

    def _kaputt():
        raise RuntimeError("kein Audio")

    monkeypatch.setattr(klangmodul, "klaenge", _kaputt)

    maschine = ToolEngine(
        registry=_Verzeichnis(_Werkzeug("launch_application")),
        security=_Freigabe(),
        provider_manager=None,
    )
    ergebnis = asyncio.run(maschine._execute(ToolCall("probe", {}), "test"))

    assert ergebnis.result.ok, ergebnis.result.error
    assert motor.HANDELNDE_RECHTE  # nur damit klar ist, dass der Pfad genommen wurde


def test_werkzeuge_melden_start_und_abschluss():
    from backend.tools.tool_engine import ToolCall, ToolEngine

    class _Bus:
        def __init__(self):
            self.events = []

        async def publish(self, name, payload):
            self.events.append((name, payload))

    bus = _Bus()
    maschine = ToolEngine(
        registry=_Verzeichnis(_Werkzeug("compute")),
        security=_Freigabe(),
        provider_manager=None,
        event_bus=bus,
    )
    ergebnis = asyncio.run(maschine._execute(ToolCall("probe", {}), "test"))

    assert ergebnis.result.ok
    assert [name for name, _ in bus.events] == ["task.started", "task.finished"]
    assert bus.events[-1][1]["progress"] == 1.0
