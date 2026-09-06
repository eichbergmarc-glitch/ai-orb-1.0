"""Aus einem gesprochenen Satz wird ein brauchbarer Suchbegriff.

Der mitgeschnittene Beweis: Der Orb suchte woertlich mit „wann ist diese
zeit wo ich die frage mit urkunden abgleichen kann startpunkt und endpunkt
bitte site:semanticscholar.org". Darauf gibt keine Suchmaschine etwas
zurueck. Diese Tests sichern, dass das Frage-Geruest wegfaellt, die
tragenden Woerter bleiben und ``site:`` erhalten bleibt.
"""

from __future__ import annotations

from backend.tools.web_tools import _relevante_treffer, _suchwoerter, suchbegriff_aus


def test_der_redesatz_wird_zu_stichworten():
    roh = ("wann ist diese zeit wo ich die frage mit urkunden abgleichen kann "
           "startpunkt und endpunkt bitte")
    begriff = suchbegriff_aus(roh)
    assert len(begriff) < len(roh)
    # Tragende Woerter bleiben ...
    for wort in ("urkunden", "startpunkt", "endpunkt"):
        assert wort in begriff
    # ... Fuellwoerter und Hoeflichkeit fallen weg.
    for weg in (" ich ", " die ", " kann ", "bitte"):
        assert weg.strip() not in begriff.split()


def test_site_filter_bleibt_erhalten():
    begriff = suchbegriff_aus("erklär mir die Quellenkritik bei Luther site:semanticscholar.org")
    assert "site:semanticscholar.org" in begriff
    assert "quellenkritik" in begriff
    assert "luther" in begriff


def test_kurze_frage_bleibt_brauchbar():
    begriff = suchbegriff_aus("Wer war Karl der Große?")
    assert "karl" in begriff
    assert "große" in begriff or "grosse" in begriff
    assert "der" not in begriff.split()


def test_leere_oder_reine_fuellfrage_faellt_nicht_auf_null():
    # Selbst wenn fast alles Fuellwort ist, kommt etwas Nutzbares zurueck.
    begriff = suchbegriff_aus("kannst du mir das mal sagen bitte")
    assert begriff  # nicht leer


def test_whisper_neu_kai_modelle_wird_zu_ki_modellen():
    begriff = suchbegriff_aus(
        "Ja, ich bitte darum, suche nach einem Magazin nach Neuigkeiten "
        "zu Neu-Kai-Modellen."
    )
    assert "ki" in begriff.split()
    assert "modelle" in begriff.split()
    assert "kai" not in begriff
    assert "darum" not in begriff.split()
    assert "neuigkeiten" not in begriff.split()
    assert "ki" in _suchwoerter(begriff)


def test_ki_relevanz_laesst_keine_beliebigen_magazinmeldungen_durch():
    treffer = [
        {
            "titel": "Das Magazin Bravo im Wandel",
            "url": "https://example.org/bravo",
            "beschreibung": "Ein Rueckblick auf die Jugendzeitschrift.",
        },
        {
            "titel": "Neue KI-Modelle im Vergleich",
            "url": "https://example.org/ki",
            "beschreibung": "Neue Modelle fuer kuenstliche Intelligenz.",
        },
        {
            "titel": "Kinder lernen mit Modellen",
            "url": "https://example.org/kinder",
            "beschreibung": "Ein Schulprojekt.",
        },
    ]
    relevant = _relevante_treffer("magazin ki modelle", treffer)
    assert [item["url"] for item in relevant] == ["https://example.org/ki"]
