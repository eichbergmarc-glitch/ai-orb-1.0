"""Vorlesungsbilder muessen gross genug sein, um etwas zu zeigen.

Der Anlass: Der Benutzer nannte die Grafiken im Vorlesungsfenster
"ungenuegend und langweilig". In ``data/grafiken/fotos`` stand, warum.
Neben Aufnahmen mit 1600 Bildpunkten lagen dort

    16226 B  (211, 240)  hellenismus-3-...jpg
    13687 B  (197, 240)  hellenismus-1-...jpg
      442 B      -       tor-1-...jpg   (mehrfach)

Das Vorlesungsfenster ist mindestens 680 Punkte breit. Ein 197 Punkte
breites Bild wird darin auf das Dreifache aufgeblasen - es ist dann nicht
klein, sondern matschig. Und die 442-Byte-Dateien sind ueberhaupt keine
Aufnahmen, sondern Platzhalter, die als Bild durchgingen.
"""

from __future__ import annotations

import io

import pytest

from backend.grafik import bildquellen


def _bild_bytes(breite: int, hoehe: int) -> bytes:
    from PIL import Image

    puffer = io.BytesIO()
    Image.new("RGB", (breite, hoehe), (30, 70, 140)).save(puffer, format="JPEG", quality=90)
    return puffer.getvalue()


# --- Was gespeichert werden darf -------------------------------------------


def test_ein_vorschaubild_wird_verworfen(tmp_path):
    """197x240 ist genau die Groesse, die im Fenster matschig wird."""

    with pytest.raises(bildquellen.BildquelleFehler, match="zu klein"):
        bildquellen._sichern(_bild_bytes(197, 240), tmp_path / "klein.jpg")


def test_ein_platzhalter_von_442_byte_wird_verworfen(tmp_path):
    with pytest.raises(bildquellen.BildquelleFehler, match="zu klein"):
        bildquellen._sichern(b"x" * 442, tmp_path / "platzhalter.jpg")


def test_eine_richtige_aufnahme_wird_gespeichert(tmp_path):
    ziel = bildquellen._sichern(_bild_bytes(1478, 1600), tmp_path / "gut.jpg")
    assert ziel.exists() and ziel.stat().st_size > bildquellen._MINDESTBYTES


def test_die_lange_kante_zaehlt_nicht_die_kurze(tmp_path):
    """Ein Hochformat mit 500x1200 ist brauchbar, kein Vorschaubild."""

    ziel = bildquellen._sichern(_bild_bytes(500, 1200), tmp_path / "hoch.jpg")
    assert ziel.exists()


def test_bild_holen_meldet_ein_zu_kleines_bild_als_fehlschlag(tmp_path, monkeypatch):
    """Damit der naechste Treffer drankommt statt das schlechte zu landen."""

    monkeypatch.setattr(
        bildquellen, "_abrufen", lambda *a, **k: _bild_bytes(211, 240)
    )
    treffer = bildquellen.Bildtreffer(titel="Hellenismus", bild_url="https://example.org/x.jpg")
    assert bildquellen.bild_holen(treffer, tmp_path / "ziel.jpg") is None


# --- Was gar nicht erst geladen wird ---------------------------------------


def test_gemeldete_vorschaumasse_werden_vorher_aussortiert():
    assert bildquellen._gross_genug(1478, 1600) is True
    assert bildquellen._gross_genug(197, 240) is False
    assert bildquellen._gross_genug(439, 500) is False


def test_unbekannte_masse_duerfen_durch():
    """Nicht jede Quelle nennt die Groesse - gemessen wird spaetestens beim Speichern."""

    assert bildquellen._gross_genug(0, 0) is True


def test_openverse_ueberspringt_zu_kleine_treffer(monkeypatch):
    monkeypatch.setattr(
        bildquellen,
        "_json_abrufen",
        lambda *a, **k: {
            "results": [
                {"url": "https://example.org/klein.jpg", "title": "Vorschau",
                 "width": 197, "height": 240},
                {"url": "https://example.org/gross.jpg", "title": "Aufnahme",
                 "width": 1400, "height": 1600},
            ]
        },
    )
    treffer = bildquellen._openverse_suchen("hellenismus", 3, 10)
    assert [t.titel for t in treffer] == ["Aufnahme"]


def test_commons_fordert_die_ablagegroesse_an(monkeypatch):
    """Kleiner anzufordern verschenkt Schaerfe, die spaeter fehlt."""

    gesehen: list[str] = []

    def _merken(adresse, **kwargs):
        gesehen.append(adresse)
        return {"query": {"pages": []}}

    monkeypatch.setattr(bildquellen, "_json_abrufen", _merken)
    bildquellen._commons_suchen("platon", 2, 10)
    assert "iiurlwidth=1600" in gesehen[0]
