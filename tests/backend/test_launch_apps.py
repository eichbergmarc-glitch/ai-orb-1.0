"""Tests des Programmstarts.

Der Orb tat nichts, wenn man "oeffne den text editor" sagte. Zwei Fehler
steckten dahinter, und beide werden hier festgehalten, damit sie nicht
zurueckkehren:

  1. Der Router suchte nur nach Programmnamen, nicht nach Aliasen -
     "Editor" (Alias von notepad) wurde nie gefunden.
  2. Das Werkzeug rief eine Methode, die es nicht gab (launch_application
     statt launch), und scheiterte still.
"""

from __future__ import annotations

import asyncio

from backend.system.desktop_control import DesktopControl


def _control() -> DesktopControl:
    return DesktopControl()


def test_alias_wird_gefunden():
    d = _control()
    assert d.find_in_text("oeffne den text editor") == ["notepad"]
    assert d.find_in_text("mach vs code auf") == ["vscode"]
    assert d.find_in_text("oeffne den dateimanager") == ["explorer"]


def test_laengster_treffer_gewinnt():
    """'windows terminal' darf nicht am bloszen 'terminal' haengenbleiben."""

    d = _control()
    treffer = d.find_in_text("starte windows terminal")
    assert treffer and treffer[0] == "terminal"


def test_kein_falscher_treffer_mitten_im_wort():
    d = _control()
    # 'code' steckt in 'decodieren', darf aber nicht anschlagen.
    assert "vscode" not in d.find_in_text("kannst du das decodieren")


def test_werkzeug_ruft_die_richtige_methode():
    """Das Werkzeug muss launch() aufrufen, nicht launch_application()."""

    from backend.tools.standard_tools import LaunchApplicationTool

    aufgerufen = {}

    class _FakeDesktop:
        def launch(self, name):
            aufgerufen["name"] = name

            class _R:
                success = True
                message = f"{name} gestartet"

            return _R()

    tool = LaunchApplicationTool(_FakeDesktop())
    ergebnis = asyncio.run(tool.execute({"programm": "notepad"}))

    assert aufgerufen.get("name") == "notepad", "launch() wurde nicht aufgerufen."
    assert ergebnis.ok


def test_werkzeug_meldet_misserfolg_klar():
    from backend.tools.standard_tools import LaunchApplicationTool

    class _FakeDesktop:
        def launch(self, name):
            class _R:
                success = False
                message = "nicht freigegeben"

            return _R()

    tool = LaunchApplicationTool(_FakeDesktop())
    ergebnis = asyncio.run(tool.execute({"programm": "irgendwas"}))
    assert not ergebnis.ok
    assert "nicht freigegeben" in ergebnis.error
