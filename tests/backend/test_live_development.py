from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.evolution.live_development import (
    LiveDevelopmentService,
    _extract_diff,
    _json_object,
    parse_development_request,
)
from backend.evolution.patch_generator import PatchGenerator


@pytest.mark.parametrize(
    "text",
    [
        "Orb, implementiere eine Statusanzeige im Chatfenster",
        "Ändere deinen Code, damit die Augen dem Mauszeiger folgen",
        "Mach die Animation der Ringe flüssiger",
        "Setze den Offline-Schalter im Programm um",
        "Ich möchte, dass der Orb im Chat einen Fortschritt anzeigt",
        "Der Orb soll eine neue Timer-Funktion erhalten",
    ],
)
def test_explicit_development_requests_are_recognized(text: str) -> None:
    assert parse_development_request(text) == text


@pytest.mark.parametrize(
    "text",
    [
        "Wie funktioniert dein Code?",
        "Öffne PowerShell",
        "Die Farbe ändert sich nicht.",
        "Kannst du programmieren?",
    ],
)
def test_reports_and_questions_do_not_modify_code(text: str) -> None:
    assert parse_development_request(text) is None


def test_model_wrappers_are_parsed_without_commentary() -> None:
    assert _json_object('```json\n{"files": []}\n```') == {"files": []}
    diff = "diff --git a/backend/a.py b/backend/a.py\n--- a/backend/a.py\n+++ b/backend/a.py\n"
    assert _extract_diff(f"```diff\n{diff}```") == diff


def test_generated_diff_is_applied_only_in_isolated_workspace(tmp_path: Path) -> None:
    source = tmp_path / "backend" / "sample.py"
    source.parent.mkdir(parents=True)
    source.write_text("value = 1\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "desktop").mkdir()

    evolution = SimpleNamespace(patches=PatchGenerator(root=tmp_path))
    service = LiveDevelopmentService(
        providers=SimpleNamespace(active_provider=SimpleNamespace(is_local=True)),
        evolution=evolution,
        event_bus=SimpleNamespace(),
        neustart=SimpleNamespace(),
        root=tmp_path,
    )
    diff = (
        "diff --git a/backend/sample.py b/backend/sample.py\n"
        "index 0a979d4..ab6e40a 100644\n"
        "--- a/backend/sample.py\n"
        "+++ b/backend/sample.py\n"
        "@@ -1 +1 @@\n"
        "-value = 1\n"
        "+value = 2\n"
    )

    changes = service._materialize_diff(diff)

    assert changes == {"backend/sample.py": "value = 2\n"}
    assert source.read_text(encoding="utf-8") == "value = 1\n"


def test_protected_paths_are_rejected(tmp_path: Path) -> None:
    service = LiveDevelopmentService(
        providers=SimpleNamespace(active_provider=SimpleNamespace(is_local=True)),
        evolution=SimpleNamespace(),
        event_bus=SimpleNamespace(),
        neustart=SimpleNamespace(),
        root=tmp_path,
    )
    with pytest.raises(ValueError, match="Geschützte Datei"):
        service._validate_relative("backend/security/security_engine.py")
