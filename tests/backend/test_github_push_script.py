from __future__ import annotations

from backend.utils.paths import get_project_root


def _push() -> str:
    return (get_project_root() / "GITHUB-PUSH.bat").read_text(encoding="utf-8")


def test_push_verwendet_skriptordner_und_aktuelle_version():
    text = _push()
    assert "%~dp0" in text
    assert "ConvertFrom-Json).version" in text
    assert "0.26.4" not in text
    assert "*.bat text eol=crlf" in (
        get_project_root() / ".gitattributes"
    ).read_text(encoding="utf-8")


def test_push_erzwingt_nichts_und_verifiziert_github_commit():
    text = _push()
    assert "--force" not in text
    assert "git ls-remote origin refs/heads/main" in text
    assert "REMOTE_COMMIT" in text and "LOKALER_COMMIT" in text
    assert "if defined NUR_PRUEFEN" in text
    assert "Das Git-Remote origin fehlt" in text


def test_push_prueft_commit_und_sensible_dateien():
    text = _push()
    assert "git commit" in text and "|| goto :gitfehler" in text
    assert "$_ -eq '.env'" in text
    assert "50MB" in text


def test_diagnose_ist_wirklich_schreibfrei():
    text = (get_project_root() / "GITHUB-DIAGNOSE.bat").read_text(encoding="utf-8")
    commands = "\n".join(
        line.strip().lower()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().lower().startswith("rem ")
    )
    for forbidden in ("git add", "git commit", "git push -u", "git remote set-url"):
        assert forbidden not in commands
    assert "git push --dry-run" in text
