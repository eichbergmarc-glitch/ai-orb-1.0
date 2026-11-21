"""17.11.2026: Eine Beschwerde ist kein Bauauftrag.

"Du hast die Stimme umgeschaltet, dass sie klickt. Mach das rueckgaengig."
startete eine Codeaenderung am Orb - 40 s Wartezeit, eine Rueckfrage und
am Ende ein verworfener Patch.
"""

from __future__ import annotations

import pytest

from backend.evolution.live_development import parse_development_request


@pytest.mark.parametrize("satz", [
    "Du hast die Stimme umgeschaltet, dass sie angeht, damit klickt. Mach das Rückgierig.",
    "Du hast die Stimme verändert. Mach das rückgängig.",
    "Synapse, du hast die Animation geändert",
    "Stell die Stimme wieder wie vorher ein",
    "Die Stimme klingt komisch. Mach weiter.",
    "Nimm die Änderung an der Stimme zurück",
])
def test_beschwerden_und_ruecknahmen_sind_kein_bauauftrag(satz):
    assert parse_development_request(satz) is None


@pytest.mark.parametrize("satz", [
    "Mach die Animation der Ringe flüssiger",
    "Ändere die Farbe der Animation auf Blau",
    "Orb, implementiere eine Statusanzeige im Chatfenster",
    "Die Augen sind zu klein. Mach die Augen grösser.",
])
def test_echte_auftraege_bleiben_auftraege(satz):
    assert parse_development_request(satz) == satz
