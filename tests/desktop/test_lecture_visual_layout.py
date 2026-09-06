"""Die Lehrtafel bleibt kompakt und zeigt Foto plus Übersicht ohne Scrollen."""

from pathlib import Path


QUELLE = Path("desktop/electron/lecture_visual.ts").read_text(encoding="utf-8")


def test_lehrtafel_hat_keine_innere_scrollflaeche() -> None:
    assert "body { margin: 0; height: 100vh; overflow: hidden" in QUELLE
    assert "aside { min-height: 0; overflow: hidden" in QUELLE
    assert "overflow: auto" not in QUELLE


def test_lehrtafel_begrenzt_uebersicht_auf_vier_karten() -> None:
    assert ".slice(0, 4)" in QUELLE


def test_lehrtafel_bleibt_auf_kleinem_bildschirm_kompakt() -> None:
    assert "display.workArea.width * 0.72" in QUELLE
    assert "display.workArea.height * 0.78" in QUELLE


def test_explizite_aufzaehlung_bekommt_ein_semantisches_kartenlayout() -> None:
    # Die Pruefung haengt bewusst nicht mehr am genauen Wortlaut der
    # Bedingung: Seit dem 26.08.2026 werden mehrere Arten zugelassen, statt
    # alles ausser "enumeration" plattzumachen.
    assert '"enumeration"' in QUELLE
    assert '"Die vollständige Fachstruktur"' in QUELLE
    assert ".visual.has-photo.structured" in QUELLE
    assert ".structured aside" in QUELLE


def test_die_tafel_kennt_zeitleiste_und_gegenueberstellung() -> None:
    """Eine Jahresabfolge und zwei Positionen brauchen eigene Formen.

    In einer nummerierten Liste geht genau das verloren, was sie
    ausmacht: die Reihenfolge und das Nebeneinander.
    """

    assert '"timeline"' in QUELLE and '"comparison"' in QUELLE
    assert ".zeitleiste .strang::before" in QUELLE, "die Zeitachse selbst"
    assert ".vergleich aside" in QUELLE
    assert "grid-template-columns: repeat(2, minmax(0,1fr))" in QUELLE


def test_die_darstellungsart_erreicht_das_fenster_ueberhaupt() -> None:
    """Sie fiel auf dem Weg vom Backend ins Fenster heraus.

    Das Backend schickte ``layout`` seit jeher mit. Renderer und Bruecke
    reichten das Feld aber nicht weiter - die Tafel sah deshalb IMMER die
    Voreinstellung, und jede Gliederung im Backend war wirkungslos.
    """

    bruecke = Path("desktop/electron/preload.ts").read_text(encoding="utf-8")
    renderer = Path("desktop/renderer/main.ts").read_text(encoding="utf-8")
    assert "layout?: string;" in bruecke
    assert "layout: String(event.payload.layout" in renderer
