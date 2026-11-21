"""17.11.2026: Der Takt zwischen den Saetzen - Timing statt Modell."""

from __future__ import annotations

from backend.voice.sprechtakt import LAENGSTE, KUERZESTE, pause_nach


def test_nach_einer_frage_laenger_als_nach_einem_komma():
    assert pause_nach("Soll ich weitersuchen?") > pause_nach("Erstens,") + 0.15


def test_vor_einem_neuen_gedanken_mehr_luft():
    satz = "Das klingt einfach."
    assert pause_nach(satz, "Aber es gibt einen Haken.") > pause_nach(satz, "Es gibt einen Haken.")


def test_lange_saetze_bekommen_mehr_luft_als_kurze():
    kurz = pause_nach("Ja.")
    lang = pause_nach(
        "Weltweit sind seit einigen Stunden verschiedene Dienste von Microsoft ausgefallen, "
        "darunter Outlook, Teams und Copilot, und betroffen sind Firmen wie Behörden."
    )
    assert lang / 1.15 > kurz / 0.85 - 0.05


def test_listen_bleiben_im_fluss():
    assert pause_nach("1. Brot", "2. Milch") < pause_nach("Das ist alles.")


def test_derselbe_satz_gleich_lange_pause_aber_nicht_alle_gleich():
    assert pause_nach("Das ist erledigt.") == pause_nach("Das ist erledigt.")
    pausen = {pause_nach(f"Satz Nummer {n} ist fertig.") for n in range(20)}
    assert len(pausen) > 5


def test_grenzen():
    for satz in ("", "?", "Also …", "x" * 500 + "."):
        assert KUERZESTE <= pause_nach(satz, "Aber gut.") <= LAENGSTE
