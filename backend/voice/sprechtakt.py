"""Sprechtakt: wie lange zwischen zwei Saetzen Stille ist.

Marc, 17.11.2026: "Die Dynamik sitzt oft weniger im Synthesizer als im
Timing drumherum." Das stimmt - und es kostet kein Modell.

Bisher stand zwischen zwei Saetzen am PC immer dieselbe Pause: 60 ms im
gewoehnlichen Weg, gar keine im Satzstrom (nur der 70-ms-Rand der Datei).
Ein Mensch spricht so nicht. Er macht nach einer Frage eine laengere Pause
als nach einer Aufzaehlung, holt nach einem langen Satz mehr Luft als nach
einem kurzen, und vor einem neuen Gedanken (Absatz, "Aber", "Also") laenger
als mitten im Gedanken. Und nie zweimal exakt gleich lang - eine Pause, die
auf die Millisekunde wiederkehrt, hoert man als Metronom.

Die Werte sind bewusst knapp. Lange Pausen wirken nicht nachdenklich,
sondern so, als sei die Verbindung abgerissen.

Kein Zufall im eigentlichen Sinn: Die Schwankung haengt am Satz selbst.
Derselbe Satz bekommt dieselbe Pause; das macht das Verhalten pruefbar.
"""

from __future__ import annotations

import hashlib
import re

#: Gedankenwechsel am Anfang des naechsten Satzes - davor holt man Luft.
_NEUER_GEDANKE = re.compile(
    r"^(?:aber|also|allerdings|trotzdem|dennoch|andererseits|zum\s+anderen|"
    r"zweitens|drittens|schliesslich|schließlich|zuletzt|kurz\s+gesagt|"
    r"anders\s+gesagt|wichtig\s+ist|das\s+heisst|das\s+heißt|übrigens|uebrigens)\b",
    re.IGNORECASE,
)
_AUFZAEHLUNG = re.compile(r"^\s*(?:\d+[.)]|[-•*])\s")

#: Grenzen, zwischen denen jede Pause bleibt (Sekunden).
KUERZESTE = 0.05
LAENGSTE = 0.60


def _schwankung(text: str) -> float:
    """Faktor 0.85 bis 1.15 - fest an den Satz gebunden."""

    zahl = int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:6], 16)
    return 0.85 + (zahl % 301) / 1000.0


def pause_nach(satz: str, naechster: str = "") -> float:
    """Die Stille nach ``satz`` in Sekunden, bevor ``naechster`` beginnt."""

    satz = " ".join(str(satz or "").split())
    naechster = " ".join(str(naechster or "").split())
    if not satz:
        return KUERZESTE

    ende = satz.rstrip("\"'»«“”)]")[-1:] if satz.rstrip("\"'»«“”)]") else ""
    woerter = len(satz.split())

    if _AUFZAEHLUNG.match(satz) and _AUFZAEHLUNG.match(naechster or ""):
        grund = 0.14            # Listenpunkt zu Listenpunkt: im Fluss
    elif ende == "?":
        grund = 0.34            # Nach einer Frage laesst man sie wirken
    elif ende == "!":
        grund = 0.24
    elif ende in (":", ";"):
        grund = 0.12            # Es geht gleich weiter
    elif ende == ",":
        grund = 0.07            # Satzteil, kein Satzende
    elif ende in ("…",) or satz.endswith("..."):
        grund = 0.38            # Bewusst gesetzte Denkpause
    else:
        # Satzende: Je laenger der Satz, desto mehr Luft danach.
        grund = 0.16 + min(woerter, 30) * 0.004

    if naechster and _NEUER_GEDANKE.match(naechster):
        grund += 0.10

    return round(max(KUERZESTE, min(LAENGSTE, grund * _schwankung(satz))), 3)
