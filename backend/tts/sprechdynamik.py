"""Sprechdynamik: Atem, Denkpause, Raeuspern, Schmunzeln - dort, wo sie hingehoeren.

Marc, 16.11.2026: Die Stimme soll menschlicher klingen - "Sprechpausen so
wie Atempausen", "sich auch mal raeuspern je nach Anfrage oder mal lachen",
aber "nicht kuenstlich oder aufgesetzt".

Wie das hier geloest ist
------------------------
Die Stimme (gpt-4o-mini-tts) nimmt zu jedem Satz eine Regieanweisung
entgegen. Bisher war das fuer jeden Satz dieselbe. Dieses Modul entscheidet
je Satz, ob eine kleine Zutat dazukommt - und meistens kommt keine dazu.
Genau das ist der Punkt: Ein Mensch raeuspert sich nicht in jedem Satz und
lacht nicht auf Kommando. Was in jedem Satz vorkommt, ist ein Tick; was
selten und an der richtigen Stelle vorkommt, faellt nicht auf und wirkt
deshalb echt.

Die Regeln, in der Reihenfolge ihrer Pruefung:

* Ernstes bleibt ernst. Bei Fehlern, Warnungen und Bedauern gibt es keine
  Zutat - ein Schmunzeln in einer Fehlermeldung waere daneben.
* Schmunzeln/Lachen nur, wenn der TEXT es traegt (ein Scherz, Ironie, ein
  "haha") oder die Frage danach verlangt hat ("erzaehl einen Witz") - und
  hoechstens einmal je Minute.
* Raeuspern nur vor dem ERSTEN Satz einer laengeren Ausfuehrung (Erklaerung,
  Vorlesung, Hintergrund), nicht bei jeder Antwort und mit langem Abstand.
* Atempause vor langen Saetzen und in langen Antworten alle paar Saetze -
  dort, wo auch ein Mensch Luft holt.
* Denkpause an einem Gedankenstrich oder nach einem einleitenden "Also,".

Ob eine Zutat faellt, haengt am Satz selbst und nicht am Zufall der Uhr:
Derselbe Satz klingt beim zweiten Mal gleich. Das haelt den Zwischenspeicher
der Stimme brauchbar und macht das Verhalten pruefbar.

Kein eigenes Sprachmodell fuer die Dynamik: Es muesste vor JEDEM Satz
gefragt werden und kostete jedes Mal eine halbe Sekunde vor der ersten
Silbe. Die Grundanforderung lautet, dass der Orb fluessig antwortet.
"""

from __future__ import annotations

import hashlib
import re
import threading
import time
from dataclasses import dataclass, field

#: Gefuehlslagen, in denen jede Zutat unpassend waere.
_ERNST = frozenset({"bedauernd", "dringlich"})

_HEITER_TEXT = re.compile(
    r"\bhaha\b|\bhihi\b|\bhehe\b|😄|😂|😉|🙂|\bscherz\w*|\bwitz\w*|\bspa(?:ss|ß)\b|\blustig\w*|"
    r"\bkomisch\w*|\bironi\w+|\baugenzwinker\w*|\bzugegeben\b|\bschmunzel\w*|\bverr[uü]ckt\w*|"
    r"\bausgerechnet\b|\bna\s+gut\b|\bnicht\s+ganz\s+ernst\b",
    re.IGNORECASE,
)
_HEITER_FRAGE = re.compile(
    r"\bwitz\w*|\bscherz\w*|\blustig\w*|\bzum\s+lachen\b|\bhumor\w*|\blach\w*", re.IGNORECASE
)
_AUSFUEHRLICH_FRAGE = re.compile(
    r"\berkl[aä]r\w*|\bvorlesung\w*|\berz[aä]hl\w*|\bhintergr[uü]nd\w*|\bwarum\b|\bwieso\b|"
    r"\bwie\s+funktioniert\b|\bfass\w*\s+.*zusammen\b|\b[uü]berblick\b|\bausf[uü]hrlich\w*",
    re.IGNORECASE,
)
_DENKANFANG = re.compile(r"^(?:also|nun|hm+|tja|na ja|gut|gute frage|ehrlich gesagt|wei(?:ss|ßt) du)\b[,.:]?", re.IGNORECASE)
_AUFZAEHLUNG = re.compile(r"^\s*(?:\d+[.)]|[-•*])\s")

ATEM = (
    "Hol vor diesem Satz kurz und leise Luft, wie jemand, der zum Sprechen ansetzt - "
    "kaum hoerbar, nicht betont."
)
ATEM_MITTE = (
    "Nimm vor diesem Satz einen ruhigen Atemzug; die Pause ist kurz und selbstverstaendlich."
)
DENKPAUSE = (
    "Lass an der Gedankenstelle eine kurze echte Denkpause, als suchtest du das treffende Wort."
)
RAEUSPERN = (
    "Raeuspere dich einmal ganz kurz und leise, bevor du beginnst - beilaeufig, wie vor einer "
    "laengeren Erklaerung, nicht als Geste."
)
SCHMUNZELN = (
    "Hier darf man ein Schmunzeln hoeren, an der passenden Stelle auch ein kurzes leises Lachen "
    "durch die Nase - nur angedeutet, nie ausgestellt."
)


@dataclass
class Sprechdynamik:
    """Entscheidet je Satz, ob eine Zutat zur Regie kommt.

    Der Zustand gehoert zu einer Rede: Satznummer, die Frage davor, und wann
    zuletzt geraeuspert oder gelacht wurde.
    """

    eingeschaltet: bool = True
    atem: bool = True
    raeuspern: bool = True
    lachen: bool = True
    #: Fruehestens nach so vielen Sekunden wieder ein Raeuspern.
    raeuspern_abstand: float = 600.0
    #: Fruehestens nach so vielen Sekunden wieder ein Schmunzeln.
    lachen_abstand: float = 60.0

    _frage: str = ""
    _satz: int = 0
    _letztes_raeuspern: float = -1e9
    _letztes_lachen: float = -1e9
    _letzte_zutat_satz: int = -10
    _sperre: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def neue_rede(self, frage: str = "") -> None:
        """Eine neue Antwort beginnt - die Satzzaehlung faengt von vorn an."""

        with self._sperre:
            self._frage = " ".join(str(frage or "").split())
            self._satz = 0
            self._letzte_zutat_satz = -10

    @staticmethod
    def _los(text: str, teiler: int) -> int:
        """Eine feste Zahl 0..teiler-1 aus dem Satz - Ersatz fuer den Zufall."""

        return int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:8], 16) % max(1, teiler)

    def regie(self, text: str, emotion: str = "", *, jetzt: float | None = None) -> str:
        """Die Zutat fuer diesen Satz - meistens die leere Zeichenkette."""

        satz = " ".join(str(text or "").split())
        with self._sperre:
            nummer = self._satz
            self._satz += 1
            if not self.eingeschaltet or not satz:
                return ""
            if str(emotion or "").strip().lower() in _ERNST:
                return ""
            if _AUFZAEHLUNG.match(satz):
                return ""

            jetzt = time.monotonic() if jetzt is None else jetzt
            woerter = len(satz.split())
            zutat = ""

            heiter = bool(_HEITER_TEXT.search(satz)) or (
                bool(_HEITER_FRAGE.search(self._frage)) and nummer >= 1 and woerter >= 5
            )
            if self.lachen and heiter and jetzt - self._letztes_lachen >= self.lachen_abstand:
                self._letztes_lachen = jetzt
                zutat = SCHMUNZELN
            elif (
                self.raeuspern
                and nummer == 0
                and woerter >= 8
                and _AUSFUEHRLICH_FRAGE.search(self._frage)
                and jetzt - self._letztes_raeuspern >= self.raeuspern_abstand
                # Nicht vor jeder Erklaerung - etwa vor jeder dritten.
                and self._los(self._frage + satz, 3) == 0
            ):
                self._letztes_raeuspern = jetzt
                zutat = RAEUSPERN
            elif nummer - self._letzte_zutat_satz < 2:
                # Zwei Zutaten in Folge waeren schon ein Muster.
                zutat = ""
            elif _DENKANFANG.match(satz) or (" – " in satz or " - " in satz) and woerter >= 10:
                zutat = DENKPAUSE
            elif self.atem and woerter >= 22:
                zutat = ATEM
            elif self.atem and nummer >= 3 and nummer % 3 == 0 and woerter >= 9:
                zutat = ATEM_MITTE
            elif self.atem and nummer == 0 and len(self._frage.split()) >= 14 and woerter >= 8:
                zutat = ATEM

            if zutat:
                self._letzte_zutat_satz = nummer
            return zutat


_aktuell = Sprechdynamik()
_eingerichtet = False


def aktuelle() -> Sprechdynamik:
    """Die eine Sprechdynamik des laufenden Orb - beim ersten Zugriff eingerichtet."""

    global _eingerichtet
    if not _eingerichtet:
        _eingerichtet = True
        try:
            from backend.config import get_config

            config = get_config()
            basis = "voice.output.sprechdynamik."
            _aktuell.eingeschaltet = bool(config.get(basis + "enabled", True))
            _aktuell.atem = bool(config.get(basis + "atempausen", True))
            _aktuell.raeuspern = bool(config.get(basis + "raeuspern", True))
            _aktuell.lachen = bool(config.get(basis + "lachen", True))
            _aktuell.raeuspern_abstand = float(
                config.get(basis + "raeuspern_abstand_sekunden", 600) or 600
            )
            _aktuell.lachen_abstand = float(
                config.get(basis + "lachen_abstand_sekunden", 60) or 60
            )
        except Exception:  # noqa: BLE001 - ohne Konfiguration gelten die Vorgaben.
            pass
    return _aktuell


def neue_rede(frage: str = "") -> None:
    """Meldet der Sprechdynamik, dass eine neue Antwort beginnt."""

    try:
        aktuelle().neue_rede(frage)
    except Exception:  # noqa: BLE001 - darf nie eine Antwort stoeren.
        pass
