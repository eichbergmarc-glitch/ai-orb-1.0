"""Animation per Sprache wechseln (13.11.2026)."""

from backend.tools.animation_tools import darstellung_aus, darstellung_schreiben


def test_namen():
    assert darstellung_aus("wechsle zur Kugel-Animation") == "drei_kugeln"
    assert darstellung_aus("die drei Bälle bitte") == "drei_kugeln"
    assert darstellung_aus("zeig wieder das Gehirn") == "synaptix"
    assert darstellung_aus("Energie-Orb") == "energie"
    assert darstellung_aus("irgendwas") == ""


def test_schreiben(tmp_path):
    pfad = tmp_path / "config.yaml"
    pfad.write_text("# Kopf\norb:\n  energie: true  # Kommentar\n  synaptix: true\nvoice:\n  x: 1\n", encoding="utf-8")
    darstellung_schreiben(pfad, "drei_kugeln")
    text = pfad.read_text(encoding="utf-8")
    assert "orb:\n  darstellung: drei_kugeln\n  energie: true  # Kommentar" in text
    darstellung_schreiben(pfad, "synaptix")
    assert text.count("darstellung") == 1
    assert "  darstellung: synaptix\n" in pfad.read_text(encoding="utf-8")
