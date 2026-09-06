"""Überwachung der Verfügbarkeit aller KI-Provider.

Erfasst kontinuierlich Erreichbarkeit, Antwortzeit, Fehler und Timeouts
jedes Providers. Der Provider Manager entscheidet auf dieser Grundlage,
welcher Provider aktiv ist und wann automatisch umgeschaltet wird.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from dataclasses import dataclass, field
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from backend.orchestrator.providers.base_provider import BaseProvider
from backend.system.logging_setup import get_logger

logger = get_logger(__name__)


DEFAULT_CONNECTIVITY_HOSTS = (
    "api.anthropic.com",
    "api.openai.com",
    "speech.platform.bing.com",
)


async def internet_reachable(
    *,
    hosts: Sequence[str] = DEFAULT_CONNECTIVITY_HOSTS,
    timeout_seconds: float = 1.5,
) -> bool:
    """Prueft das Netz kurz, ohne einen Cloud-Modellaufruf zu verbrauchen.

    ``claude --version`` beweist nur, dass das Programm installiert ist. Es
    funktioniert auch bei gezogenem Netzwerkkabel. Ein kurzer TCP-Aufbau zu
    mehreren tatsaechlich verwendeten Cloud-Diensten unterscheidet diesen
    Fall, ohne Text oder Zugangsdaten zu uebertragen. Ein einzelner
    erreichbarer Host genuegt; gesperrte Hersteller-Domains werden dadurch
    nicht faelschlich als kompletter Internetausfall gewertet.
    """

    timeout = max(0.2, float(timeout_seconds))

    async def _probe(host: str) -> bool:
        writer: asyncio.StreamWriter | None = None
        try:
            _reader, writer = await asyncio.wait_for(
                asyncio.open_connection(str(host), 443),
                timeout=timeout,
            )
            return True
        except (OSError, asyncio.TimeoutError):
            return False
        finally:
            if writer is not None:
                writer.close()
                with contextlib.suppress(Exception):
                    await writer.wait_closed()

    if not hosts:
        return True
    results = await asyncio.gather(*(_probe(host) for host in hosts))
    return any(results)


@dataclass
class HealthRecord:
    """Gesundheitszustand eines einzelnen Providers."""

    name: str
    available: bool = False
    last_check: float = 0.0
    last_success: float = 0.0
    consecutive_failures: int = 0
    total_requests: int = 0
    total_errors: int = 0
    total_timeouts: int = 0
    latencies: list[float] = field(default_factory=list)

    @property
    def average_latency(self) -> float:
        """Durchschnittliche Antwortzeit der letzten Anfragen in Sekunden."""

        if not self.latencies:
            return 0.0
        return sum(self.latencies) / len(self.latencies)

    @property
    def error_rate(self) -> float:
        """Anteil fehlgeschlagener Anfragen (0.0 bis 1.0)."""

        if self.total_requests == 0:
            return 0.0
        return self.total_errors / self.total_requests

    def to_dict(self) -> dict[str, Any]:
        """Serialisiert den Zustand für die Transparenzansicht."""

        return {
            "name": self.name,
            "available": self.available,
            "last_check": self.last_check,
            "last_success": self.last_success,
            "consecutive_failures": self.consecutive_failures,
            "total_requests": self.total_requests,
            "total_errors": self.total_errors,
            "total_timeouts": self.total_timeouts,
            "average_latency": round(self.average_latency, 3),
            "error_rate": round(self.error_rate, 3),
        }


class ProviderHealth:
    """Führt periodische Gesundheitsprüfungen aller Provider durch."""

    #: Wie lange eine gelungene Antwort als Beweis der Erreichbarkeit gilt.
    #:
    #: Fuenf Minuten. Kuerzer braechte kaum etwas, laenger waere ein Risiko:
    #: Meldet sich der Anbieter zwischendurch ab, soll das nicht erst nach
    #: einer Viertelstunde auffallen.
    VERTRAUENSDAUER = 300.0

    #: Bis hierhin darf der Abstand zwischen zwei Pruefungen wachsen.
    MAX_INTERVAL = 900.0

    #: Ein bereits als nicht erreichbar bestaetigter Anbieter wird nicht
    #: jede Minute erneut als Prozess gestartet. Fuenf Minuten sind fuer die
    #: automatische Rueckkehr kurz genug, ohne lokale Antworten zu stoeren.
    UNAVAILABLE_RETRY_INTERVAL = 300.0

    def __init__(
        self,
        interval_seconds: float = 60.0,
        *,
        connectivity_check: Callable[[], bool | Awaitable[bool]] | None = None,
    ) -> None:
        self._interval = max(10.0, interval_seconds)
        self._vertrauensdauer = self.VERTRAUENSDAUER
        self._max_interval = max(self._interval, self.MAX_INTERVAL)
        self._records: dict[str, HealthRecord] = {}
        self._task: asyncio.Task[None] | None = None
        self._providers: dict[str, BaseProvider] = {}
        self._on_change: Any | None = None
        self._allowed_names: set[str] | None = None
        self._busy_check: Callable[[], bool] | None = None
        self._connectivity_check = connectivity_check
        self._network_available: bool | None = None

    def register(self, provider: BaseProvider) -> None:
        """Nimmt einen Provider in die Überwachung auf."""

        self._providers[provider.name] = provider
        self._records.setdefault(provider.name, HealthRecord(name=provider.name))

    def set_change_callback(self, callback: Any) -> None:
        """Registriert einen Callback, der bei Verfügbarkeitsänderungen läuft.

        Der Callback erhält ``(provider_name, available)`` und darf
        synchron oder asynchron sein.
        """

        self._on_change = callback

    def set_allowed_providers(self, names: list[str] | None) -> None:
        """Begrenzt aktive Pruefungen, etwa auf lokale Offline-Provider.

        ``None`` hebt die Begrenzung auf. Nicht erlaubte Provider werden
        weder kontaktiert noch als fehlgeschlagen markiert.
        """

        self._allowed_names = set(names) if names is not None else None

    def set_busy_check(self, callback: Callable[[], bool] | None) -> None:
        """Verschiebt Hintergrundpruefungen waehrend eines Dialogzugs.

        Die Pruefung eines nicht erreichbaren Kommandozeilen-Providers kann
        auf Windows mehrere Sekunden Rechenzeit und Prozessstarts kosten.
        Sie darf deshalb nie mit der eigentlichen Antwort konkurrieren.
        Erzwingbare Start- und Moduspruefungen (``force=True``) bleiben davon
        unberuehrt.
        """

        self._busy_check = callback

    def record(self, name: str) -> HealthRecord:
        """Gibt den Gesundheitseintrag eines Providers zurück."""

        return self._records.setdefault(name, HealthRecord(name=name))

    def note_success(self, name: str, latency: float) -> None:
        """Vermerkt eine erfolgreiche Anfrage."""

        entry = self.record(name)
        entry.total_requests += 1
        entry.consecutive_failures = 0
        entry.last_success = time.time()
        entry.available = True
        entry.latencies.append(latency)
        if len(entry.latencies) > 50:
            entry.latencies.pop(0)

    def note_error(
        self, name: str, *, timeout: bool = False, fatal: bool = False
    ) -> None:
        """Vermerkt eine fehlgeschlagene Anfrage.

        Args:
            timeout: Der Fehlschlag war ein Zeitlimit.
            fatal: Der Fehlschlag wiederholt sich mit Sicherheit. Eine
                abgelaufene Anmeldung oder ein ungueltiger Schluessel
                heilen nicht dadurch, dass man es gleich noch einmal
                versucht - anders als ein Aussetzer im Netz. Solche
                Fehler zaehlen deshalb sofort und nicht erst beim
                zweiten Mal.

        Die Regel "zwei Fehlschlaege" ist fuer Aussetzer richtig: ein
        einzelner Abbruch soll keinen funktionierenden Anbieter aus der
        Reihe werfen. Fuer einen belegten Dauerfehler ist sie falsch - sie
        kostet dem Benutzer einen zweiten vollen Fehlversuch, dessen
        Ausgang schon feststeht.
        """

        entry = self.record(name)
        entry.total_requests += 1
        entry.total_errors += 1
        entry.consecutive_failures += 1
        if timeout:
            entry.total_timeouts += 1
        if fatal:
            entry.available = False
            # Ein belegter Befund, keine Vermutung: ``_ist_bekannt_gestoert``
            # darf sich darauf stuetzen, ohne auf einen zweiten Fehlschlag
            # zu warten.
            entry.last_check = time.time()
            return
        if entry.consecutive_failures >= 2:
            entry.available = False

    def note_network_unavailable(self) -> None:
        """Markiert alle Cloud-Provider nach einem zentralen Netzausfall.

        Das ist kein einzelner Modellfehler und braucht deshalb nicht erst
        zwei Fehlschlaege. Lokale Provider bleiben unveraendert. Die naechste
        periodische Pruefung erkennt die Rueckkehr des Netzes und prueft die
        Cloud-Anbieter dann trotz ihrer normalen Sperrfrist sofort erneut.
        """

        self._network_available = False
        checked_at = time.time()
        for name, provider in self._providers.items():
            if provider.is_local:
                continue
            entry = self.record(name)
            entry.available = False
            entry.last_check = checked_at

    async def check_now(self, *, force: bool = False) -> dict[str, bool]:
        """Prüft alle registrierten Provider einmalig.

        Args:
            force: Auch dann wirklich nachfragen, wenn der Anbieter eben
                erst geantwortet hat. Für die Startprüfung, wo es noch
                keine Antwort gibt, an der man sich orientieren könnte.

        Returns:
            Mapping von Providernamen auf Verfügbarkeit.
        """

        results: dict[str, bool] = {}
        jetzt = time.time()

        if not force and self._busy_check is not None and self._busy_check():
            logger.debug("Provider-Pruefung verschoben: ein Dialogzug laeuft.")
            return {
                name: self.record(name).available
                for name in self._providers
                if self._allowed_names is None or name in self._allowed_names
            }

        # Cloud-CLIs koennen lokal voll funktionsfaehig aussehen, obwohl das
        # Netz fehlt. Vor deren teuren Prozess-/API-Pruefungen wird deshalb
        # einmal zentral und mit kurzer Frist die Verbindung geprueft.
        # Lokale Provider werden in jedem Fall normal geprueft.
        allowed_providers = [
            provider
            for name, provider in self._providers.items()
            if self._allowed_names is None or name in self._allowed_names
        ]
        network_available: bool | None = None
        network_recovered = False
        if (
            self._connectivity_check is not None
            and any(not provider.is_local for provider in allowed_providers)
        ):
            previous_network = self._network_available
            try:
                checked = self._connectivity_check()
                if asyncio.iscoroutine(checked):
                    checked = await checked
                network_available = bool(checked)
                self._network_available = network_available
                network_recovered = previous_network is False and network_available
            except Exception:  # noqa: BLE001 - Probe darf den Orb nie blockieren.
                logger.debug(
                    "Zentrale Internetpruefung fehlgeschlagen; "
                    "Provider werden einzeln geprueft.",
                    exc_info=True,
                )

        for name, provider in self._providers.items():
            if self._allowed_names is not None and name not in self._allowed_names:
                continue
            entry = self.record(name)
            previous = entry.available

            if network_available is False and not provider.is_local:
                entry.available = False
                entry.last_check = time.time()
                results[name] = False
                if previous and self._on_change is not None:
                    await self._notify_change(name, False)
                continue

            if (
                not force
                and not (network_recovered and not provider.is_local)
                and not entry.available
                and entry.last_check > 0
                and (jetzt - entry.last_check) < self.UNAVAILABLE_RETRY_INTERVAL
            ):
                results[name] = False
                continue

            # Wer gerade geantwortet hat, muss nicht gefragt werden, ob er
            # antworten kann.
            #
            # Das klingt selbstverstaendlich und war es nicht: Die Pruefung
            # startet bei Claude Code einen eigenen Prozess, und der kostet
            # auf Windows Sekunden. Sie lief jede Minute, unabhaengig davon,
            # ob der Anbieter kurz zuvor eine ganze Antwort geliefert hatte -
            # im Protokoll des Benutzers 271 Mal. Schlimmer als die reine
            # Rechenzeit ist der Zufall: Faellt so eine Pruefung mit einer
            # Frage zusammen, wartet der Benutzer laenger, ohne dass es
            # dafuer einen Grund gibt.
            # ... aber nur, solange seither nichts schiefgegangen ist.
            #
            # Ohne die Fehlerbedingung war diese Abkuerzung eine
            # Wiederbelebung: ``note_error`` hatte den Anbieter nach zwei
            # Fehlschlaegen gerade auf nicht verfuegbar gesetzt, und die
            # naechste Runde setzte ihn ungeprueft wieder auf verfuegbar,
            # weil die letzte gelungene Antwort noch keine fuenf Minuten
            # zurueckliegt. Der Orb schaltete daraufhin auf den soeben
            # gescheiterten Anbieter zurueck und flatterte zwischen beiden.
            # Wer Fehler gemeldet hat, wird jetzt wirklich gefragt.
            if (
                not force
                and entry.consecutive_failures == 0
                and (jetzt - entry.last_success) < self._vertrauensdauer
            ):
                entry.available = True
                results[name] = True
                continue

            try:
                available = await provider.is_available()
            except Exception:  # noqa: BLE001 - Health-Check darf nie werfen.
                logger.debug("Health-Check für %s fehlgeschlagen.", name, exc_info=True)
                available = False

            entry.available = available
            entry.last_check = time.time()
            if available:
                entry.consecutive_failures = 0
                entry.last_success = entry.last_check
            results[name] = available

            if previous != available and self._on_change is not None:
                await self._notify_change(name, available)

        return results

    async def _notify_change(self, name: str, available: bool) -> None:
        try:
            result = self._on_change(name, available)  # type: ignore[misc]
            if asyncio.iscoroutine(result):
                await result
        except Exception:  # noqa: BLE001
            logger.exception("Fehler im Health-Change-Callback.")

    async def start(self) -> None:
        """Startet die periodische Überwachung im Hintergrund."""

        if self._task is not None:
            return

        async def _loop() -> None:
            # Der Abstand waechst, solange nichts passiert.
            #
            # Eine feste Minute ist fuer den Fall gedacht, dass gerade etwas
            # kaputt ist - und dafuer ist sie richtig. Laeuft dagegen seit
            # Stunden alles, fragt der Orb stuendlich sechzig Mal nach
            # etwas, das sich nicht geaendert hat. Beim ersten Fehlschlag
            # geht der Abstand sofort auf den Ausgangswert zurueck: Wenn
            # etwas nicht stimmt, will man es schnell wissen und nicht in
            # einer Viertelstunde.
            abstand = self._interval
            while True:
                ergebnisse = await self.check_now()
                if ergebnisse and all(ergebnisse.values()):
                    abstand = min(self._max_interval, abstand * 1.6)
                else:
                    abstand = self._interval
                await asyncio.sleep(abstand)

        self._task = asyncio.create_task(_loop(), name="provider-health")
        logger.info("Provider-Überwachung gestartet (Intervall %.0fs).", self._interval)

    async def stop(self) -> None:
        """Beendet die periodische Überwachung."""

        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None

    def snapshot(self) -> dict[str, Any]:
        """Gibt den aktuellen Zustand aller Provider zurück."""

        return {name: record.to_dict() for name, record in self._records.items()}
