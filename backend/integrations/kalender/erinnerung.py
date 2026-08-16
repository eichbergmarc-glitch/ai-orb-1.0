"""Erinnert von sich aus an anstehende Termine.

Ein Dienst, der im Hintergrund läuft, regelmäßig in den Kalender sieht und
Bescheid sagt, bevor etwas ansteht - ohne dass man fragen muss.

## Warum nicht über den vorhandenen Hinweis-Mechanismus

Die Präsenzschicht kennt ``suggest()`` für Dinge, die der Orb von sich aus
sagen möchte. Sie ist hier absichtlich nicht der Weg: Diese Hinweise
sammeln sich in einer Schlange und dürfen höchstens alle paar Minuten
heraus. Für eine Terminerinnerung ist das falsch herum. "In zehn Minuten
beginnt dein Zahnarzttermin" ist zwanzig Minuten später keine
abgeschwächte Erinnerung mehr, sondern eine falsche.

Deshalb spricht dieser Dienst direkt. Was er von der Präsenzschicht
übernimmt, ist die eine Regel, die auch für Termine gilt: Wenn der Benutzer
ausdrücklich um Ruhe gebeten hat, schweigt der Orb.

## Warum jede Erinnerung nur einmal kommt

Es wird alle paar Minuten nachgesehen, aber ein Termin steht dabei mehrmals
hintereinander in der Liste. Ohne Gedächtnis würde derselbe Satz bei jedem
Durchlauf wieder gesagt. Gemerkt wird deshalb je Termin und je Vorlaufzeit,
was schon gesagt wurde - und beim Neustart des Orbs wird nichts nachgeholt,
was inzwischen längst begonnen hat.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta

from backend.integrations.kalender.client import KalenderClient, KalenderFehler, Termin
from backend.system.logging_setup import get_logger

logger = get_logger(__name__)

#: Wie weit voraus gesucht wird. Mehr braucht es nicht - die Vorlaufzeiten
#: liegen im Bereich von Minuten bis Stunden.
_VORAUSSCHAU_STUNDEN = 30


def _satz(termin: Termin, minuten: int, jetzt: datetime) -> str:
    """Formuliert die Erinnerung so, wie man sie sagen würde."""

    wovon = termin.titel or "Ein Termin"
    ort = f" - {termin.ort}" if termin.ort else ""

    if minuten <= 0:
        return f"{wovon} beginnt jetzt{ort}."
    if minuten < 60:
        return f"In {minuten} Minuten: {wovon}{ort}."
    if minuten < 120:
        return f"In einer Stunde: {wovon}{ort}."
    if minuten < 24 * 60:
        stunden = round(minuten / 60)
        return f"In {stunden} Stunden: {wovon}{ort}."

    if termin.beginn is not None and (termin.beginn.date() - jetzt.date()).days == 1:
        if termin.ganztags:
            return f"Morgen: {wovon}{ort}."
        uhr = termin.beginn.minute
        zeit = f"{termin.beginn.hour} Uhr" + (f" {uhr}" if uhr else "")
        return f"Morgen um {zeit}: {wovon}{ort}."
    return f"Bald: {wovon}{ort}."


class Terminerinnerung:
    """Sieht regelmäßig im Kalender nach und erinnert rechtzeitig."""

    def __init__(
        self,
        client: KalenderClient,
        ansagen: Callable[[str], Awaitable[bool]],
        *,
        vorlaufzeiten: list[int] | None = None,
        takt_sekunden: int = 180,
        darf_sprechen: Callable[[], bool] | None = None,
    ) -> None:
        """
        Args:
            client: Der Kalender.
            ansagen: Wie gesprochen wird - bekommt den fertigen Satz.
            vorlaufzeiten: Wie viele Minuten vorher erinnert wird. Mehrere
                Werte ergeben mehrere Erinnerungen je Termin.
            takt_sekunden: Wie oft nachgesehen wird.
            darf_sprechen: Wird vor jeder Ansage gefragt. ``False`` heißt:
                der Benutzer hat um Ruhe gebeten.
        """

        self._client = client
        self._ansagen = ansagen
        self._vorlaufzeiten = sorted(
            {max(0, int(m)) for m in (vorlaufzeiten or [60, 10])}, reverse=True
        )
        self._takt = max(30, int(takt_sekunden))
        self._darf_sprechen = darf_sprechen
        #: (Termin-Kennung, Vorlaufzeit) -> schon gesagt.
        self._gesagt: set[tuple[str, int]] = set()
        self._aufgabe: asyncio.Task | None = None
        self._laeuft = False

    # --- Steuerung ------------------------------------------------------------

    def starten(self) -> None:
        """Startet die Überwachung im Hintergrund."""

        if self._aufgabe is not None and not self._aufgabe.done():
            return
        self._laeuft = True
        self._aufgabe = asyncio.create_task(self._schleife(), name="terminerinnerung")
        logger.info(
            "Terminerinnerung läuft (Vorlauf: %s Minuten, alle %d Sekunden).",
            ", ".join(str(m) for m in self._vorlaufzeiten), self._takt,
        )

    async def anhalten(self) -> None:
        """Beendet die Überwachung."""

        self._laeuft = False
        if self._aufgabe is None:
            return
        self._aufgabe.cancel()
        try:
            await self._aufgabe
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
        self._aufgabe = None

    # --- Der Durchlauf --------------------------------------------------------

    async def _schleife(self) -> None:
        while self._laeuft:
            try:
                await self.einmal_nachsehen()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - ein Fehler darf die Schleife nicht beenden.
                logger.exception("Der Terminblick ist fehlgeschlagen.")
            await asyncio.sleep(self._takt)

    async def einmal_nachsehen(self) -> list[str]:
        """Sieht einmal nach und sagt an, was fällig ist.

        Returns:
            Die gesagten Sätze - für Protokoll und Test.
        """

        if not self._client.ist_bereit:
            return []

        jetzt = datetime.now().astimezone()
        try:
            termine = await asyncio.to_thread(
                self._client.termine,
                von=jetzt,
                bis=jetzt + timedelta(hours=_VORAUSSCHAU_STUNDEN),
                limit=50,
            )
        except KalenderFehler as fehler:
            # Kein Netz, keine Anmeldung: still bleiben und beim nächsten Mal
            # wieder versuchen. Eine Fehlermeldung alle drei Minuten
            # vorzulesen wäre schlimmer als keine Erinnerung.
            logger.info("Kalender gerade nicht lesbar: %s", fehler)
            return []

        gesagt: list[str] = []
        for termin in termine:
            if termin.beginn is None or termin.ganztags:
                continue
            verbleibend = (termin.beginn - jetzt).total_seconds() / 60.0
            if verbleibend < 0:
                continue

            for vorlauf in self._vorlaufzeiten:
                schluessel = (termin.id, vorlauf)
                if schluessel in self._gesagt:
                    continue
                if verbleibend > vorlauf:
                    continue
                # Nichts nachholen, was beim Start längst vorbei war: Wer den
                # Orb um kurz vor dem Termin startet, soll die
                # Stunden-vorher-Erinnerung nicht mehr hören.
                if vorlauf - verbleibend > self._takt / 60.0 + 5:
                    self._gesagt.add(schluessel)
                    continue

                self._gesagt.add(schluessel)
                if self._darf_sprechen is not None and not self._darf_sprechen():
                    logger.info("Erinnerung unterdrückt (Ruhe): %s", termin.titel)
                    break

                satz = _satz(termin, int(round(verbleibend)), jetzt)
                try:
                    await self._ansagen(satz)
                except Exception:  # noqa: BLE001
                    logger.exception("Die Erinnerung liess sich nicht ansagen.")
                    break
                logger.info("Erinnert: %s", satz)
                gesagt.append(satz)
                # Nur EINE Ansage je Durchlauf und Termin. Sonst käme bei
                # einem Termin in fünf Minuten die Stunden- und die
                # Zehn-Minuten-Erinnerung unmittelbar hintereinander.
                break

        self._aufraeumen(termine)
        return gesagt

    def _aufraeumen(self, termine: list[Termin]) -> None:
        """Vergisst Termine, die vorbei sind - sonst wächst die Menge ewig."""

        if len(self._gesagt) < 200:
            return
        lebendig = {t.id for t in termine}
        self._gesagt = {
            eintrag for eintrag in self._gesagt if eintrag[0] in lebendig
        }
