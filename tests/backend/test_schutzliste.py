"""Der Orb darf sich nicht selbst unbrauchbar schreiben.

Am 19.08.2026 um 13:34 war ``config.yaml`` plötzlich 172 Bytes gross - sie
hatte 83 Kilobyte. An ihrer Stelle stand ein einziger Satz, den der Orb
sich offenbar als Merkregel notieren wollte::

    "anstatt zu raten, dass ich Informationen aus dem Gedächtnis habe,
     rufe ich bei Fragen nach dem Wissensstand meines Gedächtnisses
     zuerst nach, bevor ich eine Antwort gebe."

Das Werkzeug ``datei_schreiben`` hat das erlaubt: Es prüft die Textlänge
und ob der Pfad freigegeben ist. Im Sicherheitsmodus "offen" ist alles
freigegeben - auch die eigene Konfiguration, auch ``.env``, auch das
Gedächtnis.

Diese Tests halten beides fest: dass die unersetzlichen Dateien gesperrt
sind, und dass von allen übrigen vor dem Ersetzen eine Kopie bleibt.
"""

from __future__ import annotations

import pytest

from backend.tools.schutzliste import sichern, sperrgrund


@pytest.mark.parametrize(
    "name",
    [
        "config.yaml", "config.yml", ".env", "memory.json",
        "stimmprofil.json", "user_profile.json", "requirements.txt",
        "CONFIG.YAML",  # Gross- und Kleinschreibung darf nichts aendern.
    ],
)
def test_die_unersetzlichen_dateien_sind_gesperrt(tmp_path, name):
    grund = sperrgrund(tmp_path / name)
    assert grund, name
    # Die Begruendung muss brauchbar sein - "nicht erlaubt" hilft niemandem.
    assert len(grund) > 30, grund


def test_die_begruendung_bei_der_konfiguration_nennt_den_richtigen_weg():
    grund = sperrgrund("config.yaml") or ""
    assert "einstellung_setzen" in grund


@pytest.mark.parametrize("ordner", [".git", "node_modules", "__pycache__"])
def test_verwaltungsordner_sind_gesperrt(tmp_path, ordner):
    assert sperrgrund(tmp_path / ordner / "irgendwas.txt")


@pytest.mark.parametrize(
    "name",
    ["bericht.md", "notizen.txt", "auswertung.xlsx", "backend/voice/pipeline.py"],
)
def test_gewoehnliche_dateien_bleiben_frei(tmp_path, name):
    # Der Orb soll seinen eigenen Quelltext veraendern koennen - das ist
    # eine seiner Faehigkeiten und kein Versehen.
    assert sperrgrund(tmp_path / name) is None, name


# --- Die Sicherung ---------------------------------------------------------


def test_die_alte_fassung_bleibt_erhalten(tmp_path):
    datei = tmp_path / "bericht.md"
    datei.write_text("Der wichtige alte Inhalt", encoding="utf-8")

    kopie = sichern(datei, wurzel=tmp_path)

    assert kopie is not None
    assert kopie.read_text(encoding="utf-8") == "Der wichtige alte Inhalt"
    assert kopie.parent.name == "datei_sicherungen"


def test_eine_leere_datei_wird_nicht_gesichert(tmp_path):
    leer = tmp_path / "leer.txt"
    leer.write_text("", encoding="utf-8")
    assert sichern(leer, wurzel=tmp_path) is None


def test_eine_fehlende_datei_wird_nicht_gesichert(tmp_path):
    assert sichern(tmp_path / "gibtsnicht.txt", wurzel=tmp_path) is None


def test_es_bleiben_hoechstens_fuenf_sicherungen(tmp_path):
    # Eine Sicherung, die den Datentraeger fuellt, ist selbst ein Schaden.
    datei = tmp_path / "protokoll.txt"
    for lauf in range(8):
        datei.write_text(f"Fassung {lauf}", encoding="utf-8")
        sichern(datei, wurzel=tmp_path)

    kopien = list((tmp_path / "data" / "datei_sicherungen").glob("protokoll.txt.*.bak"))
    assert len(kopien) == 5, [k.name for k in kopien]
    # Und es sind die juengsten.
    inhalte = {k.read_text(encoding="utf-8") for k in kopien}
    assert "Fassung 7" in inhalte
    assert "Fassung 0" not in inhalte


def test_eine_misslungene_sicherung_verhindert_nichts(tmp_path, monkeypatch):
    # Die Vorsichtsmassnahme darf nicht selbst zum Ausfallgrund werden.
    import backend.tools.schutzliste as modul

    datei = tmp_path / "bericht.md"
    datei.write_text("Inhalt", encoding="utf-8")

    def _geht_nicht(*_a, **_k):
        raise OSError("Datenträger voll")

    monkeypatch.setattr(modul.shutil, "copy2", _geht_nicht)
    assert sichern(datei, wurzel=tmp_path) is None


# --- Und der Anschluss ans Werkzeug ---------------------------------------


def test_das_schreibwerkzeug_holt_die_pruefung_wirklich_ein():
    from pathlib import Path

    quelle = Path("backend/tools/file_tools.py").read_text(encoding="utf-8")
    assert "sperrgrund(pfad)" in quelle
    assert "sichern(pfad)" in quelle
    # Die Sperre muss vor dem Schreiben stehen, nicht danach.
    assert quelle.index("sperrgrund(pfad)") < quelle.index("pfad.write_text")
