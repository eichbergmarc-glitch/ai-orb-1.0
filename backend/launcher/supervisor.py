"""Absturzbehandlung (Phase 58).

Ein Assistent, der beim ersten Fehler eines Nebenmoduls ganz verschwindet,
ist unbrauchbar. Die Vorgabe sagt es deutlich: *„Nicht sofort den gesamten
Orb beenden, wenn nur ein optionales Modul ausgefallen ist."*

Dieses Modul überwacht die Dienste, erkennt Ausfälle, protokolliert sie und
startet neu – aber nicht endlos. Drei Vorkehrungen halten das vernünftig:

**Abstand zwischen den Versuchen.** Nach jedem Fehlschlag wird länger
gewartet: eine Sekunde, dann zwei, dann vier. Ein Dienst, der wegen einer
belegten Ressource nicht startet, bekommt so Zeit; ein dauerhaft kaputter
frisst nicht die CPU.

**Eine Obergrenze.** Nach der letzten Wiederholung wird aufgegeben und
gesagt, was fehlt. Ein Dienst, der sich zwanzigmal nicht starten lässt,
lässt sich auch beim einundzwanzigsten Mal nicht starten.

**Ein Zeitfenster.** Die Zählung wird zurückgesetzt, wenn ein Dienst lange
genug gelaufen ist. Sonst käme ein Dienst, der einmal im Monat abstürzt,
nach einem Jahr an seine Obergrenze.

Was bei einem Ausfall geschieht, hängt daran, ob der Dienst notwendig ist.
Fällt die Sprachausgabe aus, antwortet AI-Orb weiter in Text. Fällt das
Backend aus, ist Schluss – dann ist nichts mehr da, das antworten könnte.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from backend.system.logging_setup import get_logger

logger = get_logger(__name__)

#: Wie lange ein Dienst laufen muss, damit die Fehlerzählung zurückgesetzt wird.
STABLE_AFTER_SECONDS = 300.0


class ServiceState(Enum):
    """Der Zustand eines überwachten Dienstes."""

    STOPPED = "gestoppt"
    STARTING = "startet"
    RUNNING = "laeuft"
    #: Ausgefallen, wird neu gestartet.
    RECOVERING = "wird_neu_gestartet"
    #: Endgültig aufgegeben.
    FAILED = "ausgefallen"
    #: Nicht verfügbar, aber entbehrlich.
    UNAVAILABLE = "nicht_verfuegbar"


@dataclass
class Service:
    """Ein überwachter Dienst."""

    name: str
    #: Startet den Dienst. Gibt zurück, ob es geklappt hat.
    start: Callable[[], bool]
    #: Prüft, ob er noch läuft.
    is_alive: Callable[[], bool]
    #: Beendet ihn. Optional.
    stop: Callable[[], None] | None = None
    #: Ob AI-Orb ohne ihn nicht läuft.
    required: bool = True
    #: Wie oft höchstens neu gestartet wird.
    max_restarts: int = 3
    #: Was der Benutzer erfährt, wenn er endgültig ausfällt.
    failure_message: str = ""

    state: ServiceState = ServiceState.STOPPED
    restarts: int = 0
    last_started: float = 0.0
    last_failure: float = 0.0
    last_error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "state": self.state.value,
            "required": self.required,
            "restarts": self.restarts,
            "max_restarts": self.max_restarts,
            "uptime_seconds": (
                round(time.time() - self.last_started, 1) if self.last_started else 0.0
            ),
            "last_error": self.last_error,
        }


@dataclass
class RecoveryEvent:
    """Ein Ausfall und was daraufhin geschah."""

    service: str
    at: float
    attempt: int
    recovered: bool
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "service": self.service,
            "at": self.at,
            "time": time.strftime("%H:%M:%S", time.localtime(self.at)),
            "attempt": self.attempt,
            "recovered": self.recovered,
            "detail": self.detail,
        }


class Supervisor:
    """Überwacht Dienste und startet ausgefallene neu."""

    def __init__(
        self,
        *,
        check_interval: float = 5.0,
        on_event: Callable[[RecoveryEvent], None] | None = None,
    ) -> None:
        """
        Args:
            check_interval: Abstand der Prüfungen in Sekunden.
            on_event: Wird bei jedem Ausfall aufgerufen – für die Anzeige.
        """

        self._services: dict[str, Service] = {}
        self._interval = max(1.0, check_interval)
        self._on_event = on_event

        self._thread: threading.Thread | None = None
        self._stop_requested = threading.Event()
        self._history: list[RecoveryEvent] = []
        self._lock = threading.Lock()

    # --- Anmeldung ------------------------------------------------------------------

    def register(self, service: Service) -> None:
        """Meldet einen Dienst zur Überwachung an."""

        with self._lock:
            self._services[service.name] = service
        logger.debug(
            "Dienst überwacht: %s (%s)",
            service.name,
            "notwendig" if service.required else "entbehrlich",
        )

    def unregister(self, name: str) -> bool:
        """Nimmt einen Dienst aus der Überwachung."""

        with self._lock:
            return self._services.pop(name, None) is not None

    # --- Starten --------------------------------------------------------------------

    def start_service(self, name: str) -> bool:
        """Startet einen einzelnen Dienst."""

        service = self._services.get(name)
        if service is None:
            return False

        service.state = ServiceState.STARTING

        try:
            started = bool(service.start())
        except Exception as error:  # noqa: BLE001 - ein Dienst darf nichts mitreißen.
            logger.exception("Der Dienst '%s' ist beim Start abgestürzt.", name)
            service.last_error = f"{type(error).__name__}: {error}"
            started = False

        if started:
            service.state = ServiceState.RUNNING
            service.last_started = time.time()
            service.last_error = ""
        else:
            service.state = (
                ServiceState.FAILED if service.required else ServiceState.UNAVAILABLE
            )
            service.last_failure = time.time()

        return started

    def start_all(self) -> dict[str, bool]:
        """Startet alle angemeldeten Dienste.

        Returns:
            Je Dienst, ob er läuft.
        """

        results: dict[str, bool] = {}
        for name in list(self._services):
            results[name] = self.start_service(name)

            service = self._services[name]
            if not results[name] and service.required:
                logger.error(
                    "Der notwendige Dienst '%s' ließ sich nicht starten. %s",
                    name,
                    service.failure_message or service.last_error,
                )
            elif not results[name]:
                logger.warning(
                    "Der Dienst '%s' ist nicht verfügbar. %s AI-Orb läuft ohne ihn weiter.",
                    name,
                    service.failure_message or service.last_error,
                )

        return results

    # --- Überwachung ------------------------------------------------------------------

    def begin_watching(self) -> None:
        """Startet die Überwachung im Hintergrund."""

        if self._thread is not None and self._thread.is_alive():
            return

        self._stop_requested.clear()
        self._thread = threading.Thread(
            target=self._watch_loop, name="ai-orb-supervisor", daemon=True
        )
        self._thread.start()
        logger.info("Die Dienstüberwachung läuft (Prüfung alle %.0f s).", self._interval)

    def stop_watching(self) -> None:
        """Beendet die Überwachung."""

        self._stop_requested.set()
        if self._thread is not None:
            self._thread.join(timeout=self._interval + 2.0)
            self._thread = None

    def _watch_loop(self) -> None:
        """Prüft die Dienste in Abständen."""

        while not self._stop_requested.is_set():
            self._stop_requested.wait(self._interval)
            if self._stop_requested.is_set():
                break

            try:
                self.check_once()
            except Exception:  # noqa: BLE001 - die Überwachung darf nie abbrechen.
                logger.exception("Fehler in der Dienstüberwachung.")

    def check_once(self) -> list[RecoveryEvent]:
        """Prüft alle Dienste einmal und startet Ausgefallene neu."""

        events: list[RecoveryEvent] = []

        with self._lock:
            services = list(self._services.values())

        for service in services:
            if service.state in (ServiceState.FAILED, ServiceState.UNAVAILABLE):
                continue
            if service.state is not ServiceState.RUNNING:
                continue

            try:
                alive = bool(service.is_alive())
            except Exception:  # noqa: BLE001
                logger.exception("Die Lebensprüfung von '%s' ist abgestürzt.", service.name)
                alive = False

            if alive:
                # Ein Dienst, der lange genug läuft, gilt wieder als gesund.
                if (
                    service.restarts > 0
                    and service.last_started
                    and time.time() - service.last_started > STABLE_AFTER_SECONDS
                ):
                    logger.info(
                        "Der Dienst '%s' läuft seit %.0f Minuten stabil – die "
                        "Fehlerzählung wird zurückgesetzt.",
                        service.name,
                        (time.time() - service.last_started) / 60.0,
                    )
                    service.restarts = 0
                continue

            events.append(self._recover(service))

        return events

    def _recover(self, service: Service) -> RecoveryEvent:
        """Versucht, einen ausgefallenen Dienst neu zu starten."""

        service.state = ServiceState.RECOVERING
        service.restarts += 1
        service.last_failure = time.time()

        logger.warning(
            "Der Dienst '%s' ist ausgefallen (Versuch %d von %d).",
            service.name,
            service.restarts,
            service.max_restarts,
        )

        if service.restarts > service.max_restarts:
            service.state = (
                ServiceState.FAILED if service.required else ServiceState.UNAVAILABLE
            )
            detail = service.failure_message or (
                f"Nach {service.max_restarts} Versuchen aufgegeben."
            )

            if service.required:
                logger.error("Der notwendige Dienst '%s' bleibt ausgefallen. %s", service.name, detail)
            else:
                logger.warning(
                    "Der Dienst '%s' bleibt aus. %s AI-Orb läuft ohne ihn weiter.",
                    service.name,
                    detail,
                )

            event = RecoveryEvent(service.name, time.time(), service.restarts, False, detail)
            self._record(event)
            return event

        # Abstand vor dem nächsten Versuch: 1 s, 2 s, 4 s, höchstens 30 s.
        delay = min(30.0, 2.0 ** (service.restarts - 1))
        time.sleep(delay)

        recovered = self.start_service(service.name)
        detail = (
            f"Nach {delay:.0f} s neu gestartet."
            if recovered
            else service.last_error or "Der Neustart ist fehlgeschlagen."
        )

        if recovered:
            logger.info("Der Dienst '%s' läuft wieder.", service.name)
        else:
            service.state = ServiceState.RECOVERING

        event = RecoveryEvent(service.name, time.time(), service.restarts, recovered, detail)
        self._record(event)
        return event

    def _record(self, event: RecoveryEvent) -> None:
        """Hält einen Vorfall fest und meldet ihn weiter."""

        self._history.append(event)
        self._history = self._history[-100:]

        if self._on_event is not None:
            try:
                self._on_event(event)
            except Exception:  # noqa: BLE001
                logger.debug("Die Ausfallmeldung ist fehlgeschlagen.", exc_info=True)

    # --- Beenden ----------------------------------------------------------------------

    def stop_all(self) -> None:
        """Beendet alle Dienste geordnet.

        In umgekehrter Anmeldereihenfolge: Was zuletzt startete, hört
        zuerst auf. So verschwindet nichts unter einem Dienst, der noch
        darauf zugreift.
        """

        self.stop_watching()

        with self._lock:
            services = list(self._services.values())

        for service in reversed(services):
            if service.stop is None:
                continue
            try:
                service.stop()
                service.state = ServiceState.STOPPED
            except Exception:  # noqa: BLE001
                logger.exception("Der Dienst '%s' ließ sich nicht beenden.", service.name)

        logger.info("Alle Dienste beendet.")

    # --- Auskunft ------------------------------------------------------------------------

    def is_healthy(self) -> bool:
        """Ob alle notwendigen Dienste laufen."""

        return all(
            service.state is ServiceState.RUNNING
            for service in self._services.values()
            if service.required
        )

    def failed_services(self) -> list[str]:
        """Die endgültig ausgefallenen Dienste."""

        return [
            service.name
            for service in self._services.values()
            if service.state in (ServiceState.FAILED, ServiceState.UNAVAILABLE)
        ]

    def history(self, limit: int = 20) -> list[dict[str, Any]]:
        """Die jüngsten Vorfälle."""

        return [event.to_dict() for event in self._history[-limit:]][::-1]

    def status(self) -> dict[str, Any]:
        """Statusangaben für die Transparenzansicht."""

        return {
            "healthy": self.is_healthy(),
            "watching": self._thread is not None and self._thread.is_alive(),
            "interval_seconds": self._interval,
            "services": [service.to_dict() for service in self._services.values()],
            "failed": self.failed_services(),
            "recent_events": self.history(5),
        }
