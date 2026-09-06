"""Der tägliche Nachrichtenlauf.

Die Vorgabe verlangt, dass AI-Orb sich von selbst über die Weltlage auf dem
Laufenden hält - Politik, Wirtschaft, was geschehen ist. Die Werkzeuge dafür
gab es längst: RSS holt die Schlagzeilen direkt bei den Zeitungen, GDELT
liefert die Meldungslage weltweit. Nur rief sie niemand. Beide Quellen waren
ausschliesslich über eine Frage des Benutzers erreichbar, und ein Assistent,
der erst nachsieht, wenn man ihn schickt, hält sich nicht auf dem Laufenden -
er beantwortet Fragen.

Was hier dazukommt, ist deshalb kein neues Können, sondern ein Wecker: einmal
am Tag zur eingestellten Zeit, die Schlagzeilen und je Thema die Meldungslage,
abgelegt im Gedächtnis mit Quelle und Datum.

Drei Regeln, die den Lauf höflich halten:

* Ein Fehlschlag ist kein Grund aufzuhören. Eine Quelle, die schweigt, fällt
  weg; die anderen tragen trotzdem bei.
* Gespeichert wird nur, was eine Quelle nennt. Eine Schlagzeile ohne Adresse
  ist im Gedächtnis nichts wert.
* Der Lauf sagt von sich aus nichts. Er legt ab; gefragt wird später.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta
from typing import Any, Callable

from backend.system.logging_setup import get_logger

logger = get_logger(__name__)

#: Worüber der Orb sich täglich kundig macht, wenn nichts anderes eingestellt ist.
STANDARD_THEMEN: tuple[str, ...] = ("Politik", "Wirtschaft", "Weltlage")

#: Wann, wenn nichts anderes eingestellt ist.
STANDARD_UHRZEIT = "07:30"


def _uhrzeit_lesen(roh: str) -> tuple[int, int]:
    """Macht aus ``"07:30"`` die Zahlen 7 und 30.

    Eine unlesbare Angabe ist kein Grund, den Lauf ausfallen zu lassen -
    dann gilt die Vorgabe.
    """

    text = str(roh or "").strip()
    teile = text.split(":")
    try:
        stunde = int(teile[0])
        minute = int(teile[1]) if len(teile) > 1 else 0
    except (ValueError, IndexError):
        logger.warning(
            "'%s' ist keine lesbare Uhrzeit für den Nachrichtenlauf; es gilt %s.",
            roh,
            STANDARD_UHRZEIT,
        )
        return (7, 30)
    if not (0 <= stunde <= 23 and 0 <= minute <= 59):
        return (7, 30)
    return stunde, minute


class Nachrichtenlauf:
    """Holt einmal am Tag die Weltlage und legt sie ins Gedächtnis."""

    def __init__(
        self,
        *,
        memory: Any,
        event_bus: Any | None = None,
        themen: list[str] | tuple[str, ...] | None = None,
        uhrzeit: str = STANDARD_UHRZEIT,
        hoechstens: int = 8,
        schlagzeilen: Callable[..., list[dict[str, str]]] | None = None,
        meldungslage: Callable[..., list[dict[str, str]]] | None = None,
    ) -> None:
        """
        Args:
            memory: Das Gedächtnis, in das die Meldungen wandern.
            event_bus: Optional; bekommt nach jedem Lauf eine Meldung.
            themen: Worüber sich der Orb kundig macht.
            uhrzeit: Wann, als ``HH:MM``.
            hoechstens: Wie viele Meldungen je Lauf höchstens abgelegt werden.
            schlagzeilen: Die RSS-Abfrage. Nur für Tests austauschbar.
            meldungslage: Die GDELT-Abfrage. Nur für Tests austauschbar.
        """

        self._memory = memory
        self._event_bus = event_bus
        self._themen = [
            str(t).strip() for t in (themen or STANDARD_THEMEN) if str(t).strip()
        ]
        self._stunde, self._minute = _uhrzeit_lesen(uhrzeit)
        self._hoechstens = max(1, int(hoechstens))
        self._letzter_lauf = 0.0

        if schlagzeilen is None or meldungslage is None:
            from backend.research import offene_quellen

            schlagzeilen = schlagzeilen or offene_quellen.schlagzeilen_suchen
            meldungslage = meldungslage or offene_quellen.gdelt_suchen
        self._schlagzeilen = schlagzeilen
        self._meldungslage = meldungslage

    # --- Der Lauf selbst ----------------------------------------------------

    async def einmal_laufen(self) -> dict[str, Any]:
        """Holt Schlagzeilen und Meldungslage und legt beides ab.

        Returns:
            Ein kurzer Bericht: wie viele Meldungen kamen, wie viele davon
            neu gespeichert wurden, und welche Quellen geschwiegen haben.
        """

        gefunden: list[dict[str, str]] = []
        stumm: list[str] = []

        # Zuerst die Titelseiten. Sie beantworten "was ist los" ohne jede
        # Suchmaschine und ohne dass der Orb vorgeben muss, wonach er sucht.
        try:
            treffer = await asyncio.to_thread(
                self._schlagzeilen, "", limit=self._hoechstens
            )
            gefunden.extend(treffer or [])
        except Exception as fehler:  # noqa: BLE001 - eine Quelle beendet den Lauf nicht.
            stumm.append("Schlagzeilen")
            logger.info("Die Schlagzeilen waren nicht zu holen (%s).", fehler)

        # Dann die Themen einzeln. Nacheinander und nicht gleichzeitig: Die
        # offenen Kataloge sind Gastfreundschaft, kein Dienstleister.
        for thema in self._themen:
            try:
                treffer = await asyncio.to_thread(
                    self._meldungslage, thema, limit=max(2, self._hoechstens // 3)
                )
                for eintrag in treffer or []:
                    eintrag = dict(eintrag)
                    eintrag["thema"] = thema
                    gefunden.append(eintrag)
            except Exception as fehler:  # noqa: BLE001
                stumm.append(thema)
                logger.info("Zum Thema '%s' kam nichts (%s).", thema, fehler)

        gespeichert = self._ablegen(gefunden)
        self._letzter_lauf = time.time()

        bericht = {
            "gefunden": len(gefunden),
            "gespeichert": gespeichert,
            "stumme_quellen": stumm,
            "themen": list(self._themen),
            "zeitpunkt": self._letzter_lauf,
        }

        if gefunden:
            logger.info(
                "Nachrichtenlauf: %d Meldungen gesichtet, %d neu abgelegt.",
                len(gefunden),
                gespeichert,
            )
        else:
            logger.warning(
                "Nachrichtenlauf ohne Ergebnis - keine Quelle hat geantwortet. "
                "Das ist fast immer die Netzverbindung."
            )

        if self._event_bus is not None:
            try:
                await self._event_bus.publish("nachrichten.gelesen", bericht)
            except Exception:  # noqa: BLE001 - eine Meldung darf nichts reissen.
                logger.debug("Die Nachrichtenmeldung ging nicht raus.", exc_info=True)

        return bericht

    def _ablegen(self, meldungen: list[dict[str, str]]) -> int:
        """Legt die Meldungen im Gedächtnis ab - mit Quelle, ohne Dubletten."""

        gespeichert = 0
        gesehen: set[str] = set()

        for meldung in meldungen[: self._hoechstens * 2]:
            titel = str(meldung.get("titel", "")).strip()
            adresse = str(meldung.get("url", "")).strip()
            # Eine Schlagzeile ohne Quelle ist im Gedaechtnis nichts wert:
            # Sie laesst sich weder nachlesen noch belegen.
            if not titel or not adresse or adresse in gesehen:
                continue
            gesehen.add(adresse)

            beschreibung = str(meldung.get("beschreibung", "")).strip()
            inhalt = f"{titel}\n{beschreibung}".strip()
            thema = str(meldung.get("thema", "")).strip()
            schlagworte = ["nachrichten", datetime.now().strftime("%Y-%m-%d")]
            if thema:
                schlagworte.append(thema.lower())

            try:
                eintrag = self._memory.remember(
                    inhalt,
                    kind="nachricht",
                    tags=schlagworte,
                    source=adresse,
                    certainty="fakt",
                    force=True,
                )
            except Exception:  # noqa: BLE001 - ein Eintrag beendet den Lauf nicht.
                logger.debug("Eine Meldung liess sich nicht ablegen.", exc_info=True)
                continue

            if eintrag is not None:
                gespeichert += 1

        return gespeichert

    # --- Der Wecker ---------------------------------------------------------

    def sekunden_bis_zum_lauf(self, jetzt: datetime | None = None) -> float:
        """Wie lange es bis zum nächsten Lauf dauert.

        Ist die Uhrzeit für heute schon vorbei, gilt morgen. Eine Minute
        Mindestabstand verhindert, dass ein Lauf, der genau auf die Sekunde
        fällt, sich selbst gleich noch einmal auslöst.
        """

        jetzt = jetzt or datetime.now()
        ziel = jetzt.replace(
            hour=self._stunde, minute=self._minute, second=0, microsecond=0
        )
        if ziel <= jetzt:
            ziel = ziel + timedelta(days=1)
        return max(60.0, (ziel - jetzt).total_seconds())

    async def schleife(self) -> None:
        """Wartet bis zur eingestellten Zeit und läuft dann - jeden Tag.

        Der Lauf selbst wirft nicht: Was schiefgeht, steht im Protokoll, und
        morgen wird es wieder versucht. Eine Nachrichtenschleife, die an
        einem Netzausfall stirbt, wäre schlimmer als gar keine - sie sähe
        aus, als liefe sie.
        """

        while True:
            await asyncio.sleep(self.sekunden_bis_zum_lauf())
            try:
                await self.einmal_laufen()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - morgen ist auch noch ein Tag.
                logger.exception("Der Nachrichtenlauf ist gescheitert.")

    def status(self) -> dict[str, Any]:
        """Auskunft für die Anzeige."""

        return {
            "themen": list(self._themen),
            "uhrzeit": f"{self._stunde:02d}:{self._minute:02d}",
            "letzter_lauf": self._letzter_lauf,
            "naechster_lauf_in_sekunden": round(self.sekunden_bis_zum_lauf(), 0),
        }


__all__ = ["Nachrichtenlauf", "STANDARD_THEMEN", "STANDARD_UHRZEIT"]
