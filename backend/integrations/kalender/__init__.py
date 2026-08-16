"""Der Google-Kalender.

Baut auf derselben Google-Anmeldung auf wie Gmail: dieselbe Client-ID,
dasselbe Token, eine Zustimmungsseite für beides. Wer Gmail eingerichtet
hat, hat den Kalender damit fast schon eingerichtet - es fehlt nur eine
einmalige neue Anmeldung, weil das alte Token den Kalender noch nicht
einschliesst.
"""

from __future__ import annotations

from backend.integrations.kalender.client import (
    KalenderClient,
    KalenderFehler,
    Termin,
)
from backend.integrations.kalender.zeit import ZeitFehler, zeit_lesen

__all__ = [
    "KalenderClient",
    "KalenderFehler",
    "Termin",
    "ZeitFehler",
    "zeit_lesen",
]
