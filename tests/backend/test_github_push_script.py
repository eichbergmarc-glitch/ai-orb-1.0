"""Das Sicherungsskript haelt seine Zusagen - geprueft am Text selbst.

Der Pruefstand auf dem Rechner des Benutzers hat am 20.08.2026 gezeigt,
dass diese Tests und das Skript auseinandergelaufen waren: Das Skript
war laengst umgebaut (Version aus backend/__init__.py statt aus der
package.json, Nachpruefung ueber HIER/FERN statt LOKALER_COMMIT), die
Tests prueften noch den alten Stand - und niemandem fiel es auf, weil
die Tests nur auf dem Geraet lagen. Jetzt pruefen sie den WIRKLICHEN
Vertrag, und sie liegen in beiden Umgebungen.

Der Vertrag in Kurzform:

* Die Versionsnummer kommt aus backend/__init__.py, nie fest verdrahtet.
* Die .env darf NIE hinaus - auch dann nicht, wenn die .gitignore fehlt.
  Deshalb wird der Index VOR dem Senden durchsucht, nicht die Packliste
  geglaubt.
* Kein stilles --force: Ersetzt wird nur nach ausdruecklichem JA des
  Benutzers, und die Frage steht VOR dem force im Skript.
* Nach dem Senden wird bei GitHub nachgesehen, ob dort wirklich dieser
  Stand liegt (ls-remote, HIER gegen FERN).
"""

from __future__ import annotations

from backend.utils.paths import get_project_root


def _push() -> str:
    return (get_project_root() / "GITHUB-PUSH.bat").read_text(encoding="utf-8")


def test_push_verwendet_skriptordner_und_aktuelle_version():
    text = _push()
    assert 'findstr /b "__version__"' in text, (
        "die Version muss aus backend/__init__.py gelesen werden"
    )
    # Nur die BEFEHLE zaehlen: In den REM-Zeilen darf die Geschichte des
    # Skripts erzaehlt werden ("vorher stand dort fest 0.26.4") - fest
    # verdrahtet waere die Nummer erst, wenn sie in einem Befehl steht.
    befehle = "\n".join(
        zeile
        for zeile in text.splitlines()
        if zeile.strip() and not zeile.lstrip().lower().startswith("rem")
    )
    import re

    assert not re.search(r'"AI-Orb 0\.\d', befehle), (
        "die Commit-Meldung traegt eine feste Versionsnummer"
    )
    assert "*.bat text eol=crlf" in (
        get_project_root() / ".gitattributes"
    ).read_text(encoding="utf-8")


def test_push_erzwingt_nichts_ohne_ausdrueckliches_ja():
    """--force gibt es nur hinter der Frage - nie davor, nie still."""

    text = _push()
    assert "git push origin HEAD:main\n" in text.replace("\r\n", "\n"), (
        "der erste Versuch muss OHNE force gehen"
    )
    frage = text.find('set /p ANTWORT="   Inhalt auf GitHub durch diesen Stand ersetzen?')
    force = text.find("--force")
    assert frage > 0, "die Rueckfrage vor dem Ersetzen fehlt"
    assert force > frage, "das --force steht vor der Rueckfrage des Benutzers"
    assert text.count("--force") == 1, "mehr als ein force im Skript"
    assert 'if /I not "%ANTWORT%"=="JA"' in text, "nur ein woertliches JA darf ersetzen"


def test_push_verifiziert_den_stand_auf_github():
    text = _push()
    assert "git ls-remote origin refs/heads/main" in text
    assert '"FERN=%%r"' in text and '"HIER=%%l"' in text
    assert 'if /I "%HIER%"=="%FERN%"' in text, "HIER und FERN werden nicht verglichen"
    assert "if defined NUR_PRUEFEN" in text, "der Probelauf (NUR_PRUEFEN) fehlt"
    assert "git push --dry-run origin HEAD:main" in text


def test_push_prueft_commit_und_sensible_dateien():
    text = _push()
    assert "git commit" in text and "|| goto :gitfehler" in text
    assert ":gitfehler" in text.replace("|| goto :gitfehler", ""), (
        "das Sprungziel :gitfehler fehlt"
    )
    # Die Wache schaut in den Karton (git diff --cached), nicht auf die
    # Packliste (.gitignore): Sie prueft die WIRKLICH gepackten Dateien.
    assert "git diff --cached --name-only" in text
    assert "$_ -eq '.env'" in text, "die .env-Wache fehlt"
    assert "50MB" in text, "die Groessenwache fehlt"


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
