"""Kein Werkzeug darf still am Register scheitern.

``internet_suchen``, ``webseite_lesen`` und ``webseite_erkunden`` verlangten
die Berechtigung ``internet``. Die gibt es nicht - sie heisst ``network``.
Das Register wies die drei deshalb bei jedem Start ab, mit einer Warnung im
Protokoll und ohne dass sonst etwas geschah: Der Orb hatte schlicht kein
Werkzeug fuer eine Websuche, und im Gespraech sah das aus wie Unwilligkeit.

Der zweite Test hier ist der wichtigere. Er prueft nicht diesen einen
Tippfehler, sondern die ganze Klasse: Jedes Werkzeug im Quelltext muss eine
Berechtigung verlangen, die es wirklich gibt.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil

import backend.tools
from backend.security.permissions import get_permission
from backend.tools.base_tool import Tool
from backend.tools.registry import ToolRegistry
from backend.tools.web_tools import (
    ReadWebpageTool,
    WebSearchTool,
    WebseiteErkundenTool,
)


def test_die_internetwerkzeuge_werden_wirklich_angemeldet() -> None:
    register = ToolRegistry()

    aufgenommen = register.register_many(
        [WebSearchTool(), ReadWebpageTool(), WebseiteErkundenTool()]
    )

    assert aufgenommen == 3
    assert "internet_suchen" in register
    assert "webseite_lesen" in register
    assert "webseite_erkunden" in register


def test_kein_werkzeug_verlangt_eine_unbekannte_berechtigung() -> None:
    """Die Regel, nicht der Einzelfall."""

    fehler: list[str] = []

    for modul_info in pkgutil.iter_modules(backend.tools.__path__):
        modul = importlib.import_module(f"backend.tools.{modul_info.name}")
        for _name, klasse in inspect.getmembers(modul, inspect.isclass):
            if not issubclass(klasse, Tool) or klasse is Tool:
                continue
            if inspect.isabstract(klasse):
                continue
            berechtigung = getattr(klasse, "permission", None)
            if not isinstance(berechtigung, str) or not berechtigung:
                continue
            if get_permission(berechtigung) is None:
                fehler.append(
                    f"{modul_info.name}.{klasse.__name__} verlangt "
                    f"'{berechtigung}'"
                )

    assert not fehler, "Werkzeuge mit unbekannter Berechtigung: " + ", ".join(fehler)
