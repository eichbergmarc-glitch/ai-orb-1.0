"""Messwerte: was gemessen wurde, unveränderlich abgelegt.

Eine Messung ist eine Tatsachenbehauptung über einen Lauf. Sie wird
angehängt, nie geändert - eine Datei, in der man rückwirkend bessere Zahlen
eintragen kann, ist keine Messung, sondern eine Meinung.

Erfasst wird pro Prüfstück und Modell:

* **fachlich**: Erfolg, schwere Halluzination, Sicherheitsfehler
* **Werkzeuge**: verlangt, gelaufen, erfolgreich
* **Zeit**: bis zum ersten Wort (TTFT), bis zum ersten hörbaren Ton (TTFA),
  Gesamtdauer, Tokens pro Sekunde
* **Kosten und Last**: geschätzte Kosten, Speicher, Rechenzeit
* **Betriebsart**: warm, kalt oder offline - drei verschiedene Welten, die
  man nicht miteinander verrechnen darf
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from backend.system.logging_setup import get_logger
from backend.utils.paths import get_data_dir

logger = get_logger(__name__)

#: Die drei Betriebsarten. Ein Kaltstart mit 12 Sekunden Ladezeit ist kein
#: schlechteres Modell, sondern ein anderer Messpunkt.
BETRIEBSARTEN: tuple[str, ...] = ("warm", "kalt", "offline")

#: Woran ein Fehlschlag lag. Die ersten drei sind Sache des Modells, die
#: letzten beiden Sache der Umgebung - und nur die ersten drei duerfen
#: seine Quote druecken.
FEHLERKLASSEN: tuple[str, ...] = (
    "keiner",
    "modell",             # inhaltlich falsch oder unvollstaendig
    "werkzeugauswahl",    # kein oder das falsche Werkzeug gewaehlt
    "werkzeugausfuehrung",  # richtiges Werkzeug, aber es scheiterte fachlich
    "authentifizierung",  # Zugangsdaten fehlen oder wurden abgelehnt
    "umgebung",           # Werkzeug nicht angemeldet, Dienst nicht erreichbar
)

#: Fehlerklassen, die NICHT dem Modell angelastet werden.
NICHT_MESSBAR: frozenset[str] = frozenset({"authentifizierung", "umgebung"})


@dataclass
class Messung:
    """Ein einzelner Lauf eines Prüfstücks mit einem Modell."""

    katalog_version: str
    katalog_pruefsumme: str
    lauf: str
    kategorie: str
    fall: str
    modell: str
    betriebsart: str = "warm"

    # --- fachlich ---
    erfolg: bool = False
    halluzination: bool = False
    sicherheitsfehler: bool = False
    punkte: float = 0.0
    hoechstpunkte: float = 0.0
    bewerter: str = ""

    # --- Werkzeuge ---
    werkzeuge_verlangt: list[str] = field(default_factory=list)
    werkzeuge_gelaufen: list[str] = field(default_factory=list)
    werkzeuge_erfolgreich: bool = False
    #: Der ganze Ablauf, nicht nur das Ergebnis: je Aufruf Name, Erfolg,
    #: Fehlertext und Dauer. Ohne das laesst sich hinterher nicht sagen, ob
    #: ein Werkzeug gar nicht gerufen wurde oder ob es gerufen wurde und
    #: scheiterte - zwei sehr verschiedene Befunde.
    werkzeugspur: list[dict[str, Any]] = field(default_factory=list)
    #: Wie viele Runden die Werkzeugschleife brauchte.
    runden: int = 0
    #: Warum die Schleife endete.
    abbruchgrund: str = ""
    #: Wie viele Aufrufe das Schema verletzt haben und abgewiesen wurden.
    aufrufe_ungueltig: int = 0

    # --- Zeit ---
    ttft_sekunden: float = 0.0
    ttfa_sekunden: float = 0.0
    dauer_sekunden: float = 0.0
    tokens: int = 0
    tokens_pro_sekunde: float = 0.0

    # --- Kosten und Last ---
    kosten_geschaetzt: float = 0.0
    speicher_mb: float = 0.0

    #: Woran ein Fehlschlag lag. Einer der Werte aus ``FEHLERKLASSEN``.
    #:
    #: Ohne diese Unterscheidung misst eine Erfolgsquote zwei Dinge auf
    #: einmal: das Modell und die Umgebung. Am 01.09.2026 stand rechner_02
    #: fuer beide Modelle auf "nicht bestanden", weil die Kalender-
    #: werkzeuge ohne Google-Anmeldung fehlten - das sagt ueber die
    #: Modelle nichts aus, floss aber in ihre Quote ein.
    fehlerklasse: str = ""
    #: Ob diese Messung ueberhaupt etwas ueber das MODELL aussagt.
    #:
    #: ``False`` bei Umgebungs- und Authentifizierungsfehlern. Solche
    #: Messungen werden weiterhin vollstaendig abgelegt - sie werden nur
    #: nicht mehr als Modellfehler gezaehlt.
    messbar: bool = True

    zeitpunkt: float = field(default_factory=time.time)
    hinweis: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, daten: dict[str, Any]) -> "Messung":
        bekannt = {feld for feld in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in daten.items() if k in bekannt})


class Messreihe:
    """Ein Messlauf, angehängt in eine JSONL-Datei unter ``data/lernen/``."""

    def __init__(self, lauf: str, *, verzeichnis: Path | None = None) -> None:
        self.lauf = lauf
        basis = verzeichnis or (get_data_dir() / "lernen")
        basis.mkdir(parents=True, exist_ok=True)
        self._pfad = basis / "messungen.jsonl"
        self._sperre = threading.Lock()

    @property
    def pfad(self) -> Path:
        return self._pfad

    def anhaengen(self, messung: Messung) -> None:
        """Schreibt eine Messung fort. Nur anhängen, nie ändern."""

        with self._sperre:
            try:
                with self._pfad.open("a", encoding="utf-8") as datei:
                    datei.write(
                        json.dumps(messung.to_dict(), ensure_ascii=False) + "\n"
                    )
            except OSError:
                logger.exception("Eine Messung liess sich nicht ablegen.")

    def alle(self) -> list[Messung]:
        if not self._pfad.exists():
            return []
        messungen: list[Messung] = []
        try:
            for zeile in self._pfad.read_text(encoding="utf-8").splitlines():
                zeile = zeile.strip()
                if not zeile:
                    continue
                try:
                    messungen.append(Messung.from_dict(json.loads(zeile)))
                except (json.JSONDecodeError, TypeError):
                    continue
        except OSError:
            logger.exception("Die Messreihe liess sich nicht lesen.")
        return messungen

    def laeufe(self) -> list[str]:
        return sorted({m.lauf for m in self.alle()})


def zusammenfassen(
    messungen: Iterable[Messung], *, kategorie: str = "", modell: str = ""
) -> dict[str, Any]:
    """Verdichtet Messungen zu den Zahlen, an denen die Übergabe hängt.

    Bewusst ohne Glättung und ohne Gewichtung: Wer eine Erfolgsquote
    schönrechnen will, soll das nicht hier tun können.
    """

    passend = [
        m
        for m in messungen
        if (not kategorie or m.kategorie == kategorie)
        and (not modell or m.modell == modell)
    ]
    if not passend:
        return {
            "anzahl": 0,
            "messbar": 0,
            "nicht_messbar": 0,
            "fehlerklassen": {},
            "erfolgsquote": 0.0,
            "halluzinationsquote": 0.0,
            "sicherheitsfehlerquote": 0.0,
            "werkzeugquote": 0.0,
            "ttft_median": 0.0,
            "ttfa_median": 0.0,
            "tokens_pro_sekunde_median": 0.0,
            "kosten_summe": 0.0,
        }

    def _median(werte: list[float]) -> float:
        gefiltert = sorted(w for w in werte if w > 0)
        if not gefiltert:
            return 0.0
        mitte = len(gefiltert) // 2
        if len(gefiltert) % 2:
            return gefiltert[mitte]
        return (gefiltert[mitte - 1] + gefiltert[mitte]) / 2

    mit_werkzeug = [m for m in passend if m.werkzeuge_verlangt]
    # Die Erfolgsquote zaehlt nur, was ueber das Modell etwas aussagt.
    # Umgebungs- und Anmeldefehler stehen daneben, nicht darin.
    messbar = [m for m in passend if m.messbar]
    nicht_messbar = [m for m in passend if not m.messbar]
    grundmenge = messbar or passend
    return {
        "anzahl": len(passend),
        "messbar": len(messbar),
        "nicht_messbar": len(nicht_messbar),
        "fehlerklassen": {
            klasse: sum(1 for m in passend if m.fehlerklasse == klasse)
            for klasse in sorted({m.fehlerklasse for m in passend if m.fehlerklasse})
        },
        "erfolgsquote": sum(1 for m in grundmenge if m.erfolg) / len(grundmenge),
        "halluzinationsquote": sum(1 for m in passend if m.halluzination)
        / len(passend),
        "sicherheitsfehlerquote": sum(1 for m in passend if m.sicherheitsfehler)
        / len(passend),
        "werkzeugquote": (
            sum(1 for m in mit_werkzeug if m.werkzeuge_erfolgreich)
            / len(mit_werkzeug)
            if mit_werkzeug
            else 1.0
        ),
        "ttft_median": _median([m.ttft_sekunden for m in passend]),
        "ttfa_median": _median([m.ttfa_sekunden for m in passend]),
        "tokens_pro_sekunde_median": _median(
            [m.tokens_pro_sekunde for m in passend]
        ),
        "kosten_summe": sum(m.kosten_geschaetzt for m in passend),
    }


__all__ = ["BETRIEBSARTEN", "Messreihe", "Messung", "zusammenfassen"]
