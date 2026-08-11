"""Der AI-Orb Launcher (Phase 45).

Die zentrale Startkomponente. Ein Klick im Startmenü, und alles Übrige
geschieht hier – ohne Kommandozeile, ohne dass der Benutzer etwas von
Python, Ports oder Diensten wissen muss.

Der Ablauf entspricht der Vorgabe:

    System prüfen → Backend starten → Claude prüfen → Ollama prüfen
    → Memory → Voice → Whisper → Kokoro → Desktop/Vision
    → Human Experience → UI → READY

Zwei Entscheidungen prägen den Aufbau.

**Der Launcher startet, was geht, und meldet, was nicht geht.** Er bricht
nur ab, wenn etwas Notwendiges fehlt. Ohne Sprachausgabe läuft AI-Orb; ohne
Backend nicht. Was fehlt, steht danach im Bericht – im Klartext, mit dem
nächsten Schritt.

**Der Fortschritt wird gemeldet, während er geschieht.** Ein Start dauert
mit dem Laden der Sprachmodelle einige Sekunden. In dieser Zeit soll der
Ladebildschirm zeigen, woran gerade gearbeitet wird, statt zu schweigen.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from backend.config import get_config
from backend.launcher.health_check import CheckState, HealthCheck, HealthReport
from backend.launcher.ollama_service import OllamaService
from backend.launcher.supervisor import RecoveryEvent, Service, Supervisor
from backend.system.logging_setup import get_logger, setup_logging

logger = get_logger(__name__)


@dataclass
class StartupStep:
    """Ein Schritt des Startvorgangs."""

    key: str
    label: str
    done: bool = False
    ok: bool = True
    detail: str = ""
    seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "done": self.done,
            "ok": self.ok,
            "detail": self.detail,
            "seconds": round(self.seconds, 2),
        }


@dataclass
class StartupResult:
    """Das Ergebnis des Startvorgangs."""

    ready: bool = False
    steps: list[StartupStep] = field(default_factory=list)
    report: HealthReport | None = None
    seconds: float = 0.0
    message: str = ""
    #: Was fehlt, obwohl AI-Orb läuft.
    limitations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "steps": [step.to_dict() for step in self.steps],
            "health": self.report.to_dict() if self.report else None,
            "seconds": round(self.seconds, 2),
            "message": self.message,
            "limitations": self.limitations,
        }


#: Die Schritte in der Reihenfolge der Vorgabe.
STARTUP_STEPS: tuple[tuple[str, str], ...] = (
    ("system", "System"),
    ("backend", "Backend"),
    ("claude", "Claude"),
    ("offline", "Offline-KI"),
    ("memory", "Memory"),
    ("voice", "Voice"),
    ("desktop", "Desktop"),
    ("presence", "Human Experience"),
)


class Launcher:
    """Startet und überwacht die gesamte AI-Orb-Umgebung."""

    def __init__(
        self,
        *,
        on_progress: Callable[[StartupStep], None] | None = None,
        on_recovery: Callable[[RecoveryEvent], None] | None = None,
    ) -> None:
        """
        Args:
            on_progress: Wird nach jedem Startschritt aufgerufen – für den
                Ladebildschirm.
            on_recovery: Wird bei einem Dienstausfall aufgerufen.
        """

        self._on_progress = on_progress
        self._steps: dict[str, StartupStep] = {
            key: StartupStep(key=key, label=label) for key, label in STARTUP_STEPS
        }

        self.health = HealthCheck()
        self.ollama = OllamaService()
        self.supervisor = Supervisor(on_event=on_recovery)

        self._runtime: Any | None = None
        self._server: Any | None = None
        self._server_thread: threading.Thread | None = None
        self._result: StartupResult | None = None
        self._started_at = 0.0

    # --- Fortschritt --------------------------------------------------------------

    def _begin(self, key: str) -> float:
        step = self._steps[key]
        step.done = False
        logger.info("Startschritt: %s", step.label)
        return time.perf_counter()

    def _finish(self, key: str, started: float, *, ok: bool = True, detail: str = "") -> None:
        step = self._steps[key]
        step.done = True
        step.ok = ok
        step.detail = detail
        step.seconds = time.perf_counter() - started

        if self._on_progress is not None:
            try:
                self._on_progress(step)
            except Exception:  # noqa: BLE001
                logger.debug("Fortschrittsmeldung fehlgeschlagen.", exc_info=True)

    # --- Startvorgang -----------------------------------------------------------------

    def start(self, *, start_ui: bool = False) -> StartupResult:
        """Fährt AI-Orb vollständig hoch.

        Args:
            start_ui: Ob die Oberfläche mitgestartet wird. In der
                installierten Fassung startet Electron den Launcher, nicht
                umgekehrt – dann bleibt das aus.

        Returns:
            Das Ergebnis samt Bericht.
        """

        setup_logging()
        self._started_at = time.perf_counter()
        result = StartupResult()

        # --- 1. System ------------------------------------------------------
        started = self._begin("system")
        report = self.health.run()
        result.report = report

        blocking = [
            check for check in report.failures() if check.required
        ]
        if blocking:
            names = ", ".join(check.name for check in blocking)
            self._finish("system", started, ok=False, detail=names)
            result.ready = False
            result.message = self._describe_blocking(blocking)
            result.seconds = time.perf_counter() - self._started_at
            logger.error("Der Start wurde abgebrochen:\n%s", result.message)
            self._result = result
            return result

        self._finish("system", started, detail=report.status_word())

        # --- 2. Backend -----------------------------------------------------
        started = self._begin("backend")
        try:
            from backend.runtime import get_runtime

            self._runtime = get_runtime()
            self._runtime.start()
            self._finish("backend", started, detail="läuft")
        except Exception as error:  # noqa: BLE001
            logger.exception("Das Backend ließ sich nicht starten.")
            self._finish("backend", started, ok=False, detail=str(error))
            result.ready = False
            result.message = (
                "Das Backend ließ sich nicht starten. Die Einzelheiten stehen "
                f"im Protokoll.\n{type(error).__name__}: {error}"
            )
            result.seconds = time.perf_counter() - self._started_at
            self._result = result
            return result

        # --- 3. Claude ------------------------------------------------------
        started = self._begin("claude")
        provider_check = next(
            (check for check in report.results if check.name == "ProviderManager"), None
        )
        claude_ok = provider_check is not None and provider_check.ok
        self._finish(
            "claude",
            started,
            ok=claude_ok,
            detail=provider_check.detail if provider_check else "unbekannt",
        )
        if not claude_ok:
            result.limitations.append(
                "Es ist kein Sprachmodell erreichbar. AI-Orb startet, kann aber "
                "nicht antworten."
            )

        # --- 4. Offline-Rückfall ---------------------------------------------
        started = self._begin("offline")
        ollama_state = self.ollama.prepare()
        self._finish(
            "offline",
            started,
            ok=bool(ollama_state.get("running")),
            detail=str(ollama_state.get("message", "")),
        )
        if not ollama_state.get("ready"):
            remedy = str(ollama_state.get("remedy", "")).strip()
            if remedy:
                result.limitations.append(f"Offline-Betrieb eingeschränkt: {remedy}")

        # --- 5. Memory ------------------------------------------------------
        started = self._begin("memory")
        memory_check = next(
            (check for check in report.results if check.name == "Memory"), None
        )
        self._finish(
            "memory",
            started,
            ok=memory_check is None or memory_check.ok,
            detail=memory_check.detail if memory_check else "bereit",
        )

        # --- 6. Voice -------------------------------------------------------
        started = self._begin("voice")
        voice_ok = True
        voice_detail = "bereit"
        try:
            voice_ok = self._runtime.voice.is_ready()
            voice_detail = "bereit" if voice_ok else "eingeschränkt"
            if not voice_ok:
                result.limitations.append(self._runtime.voice.requirements_report())
        except Exception as error:  # noqa: BLE001
            voice_ok = False
            voice_detail = str(error)
        self._finish("voice", started, ok=voice_ok, detail=voice_detail)

        # --- 7. Desktop und Vision -------------------------------------------
        started = self._begin("desktop")
        desktop_check = next(
            (check for check in report.results if check.name == "Desktop"), None
        )
        self._finish(
            "desktop",
            started,
            ok=desktop_check is None or desktop_check.ok,
            detail=desktop_check.detail if desktop_check else "bereit",
        )

        # --- 8. Human Experience ----------------------------------------------
        started = self._begin("presence")
        presence_check = next(
            (check for check in report.results if check.name == "Human Experience"), None
        )
        self._finish(
            "presence",
            started,
            ok=presence_check is None or presence_check.ok,
            detail=presence_check.detail if presence_check else "bereit",
        )

        # --- API-Server und Überwachung ------------------------------------------
        self._start_api_server()
        self._register_services()
        self.supervisor.begin_watching()

        result.ready = True
        result.steps = list(self._steps.values())
        result.seconds = time.perf_counter() - self._started_at
        result.message = (
            "AI-Orb ist bereit."
            if not result.limitations
            else "AI-Orb ist bereit, mit Einschränkungen."
        )

        logger.info("AI-Orb bereit nach %.1f Sekunden.", result.seconds)
        for limitation in result.limitations:
            logger.warning("Einschränkung: %s", limitation.replace("\n", " "))

        # Erst jetzt begrüßen – nach diesem Punkt ist wirklich alles oben:
        # Startprüfung bestanden, API-Server läuft, die Dienstüberwachung
        # wacht. Eine Begrüßung vorher wäre eine Verheißung auf etwas, das
        # noch gar nicht steht.
        self._greet(result)

        self._result = result
        return result

    def _greet(self, result: StartupResult) -> None:
        """Begrüßt den Benutzer, sobald AI-Orb einsatzfähig ist.

        Bewusst nach dem Bereit-Zustand und über denselben Sprechweg wie
        jede andere Ausgabe – so klingt die Begrüßung wie der Orb und nicht
        wie ein Systemton.

        Zwei Vorsichtsmaßnahmen, die hier nicht verhandelbar sind:

        1. **Der ganze Rumpf ist gekapselt.** Nichts an einer Begrüßung darf
           den Start zum Scheitern bringen – eine fehlende Begrüßung ist ein
           Schönheitsfehler, ein nicht startender Orb ist einer, mit dem man
           nicht arbeiten kann.
        2. **Es wird nicht gewartet.** Die Begrüßung wird auf die Kern-Loop
           geschickt und läuft dort für sich; der Start kehrt sofort zurück.
           Würde hier auf das Ende des Sprechens gewartet, hinge die
           Startmeldung an der Sprachausgabe – und ein Klemmen dort sähe aus
           wie ein hängender Kern.
        """

        try:
            config = get_config()
            if not bool(config.get("startup.greeting_enabled", True)):
                return
            if self._runtime is None or getattr(self._runtime, "voice", None) is None:
                return

            text = str(
                config.get("startup.greeting_text", "")
            ).strip() or self._default_greeting(result)

            loop = getattr(self._runtime, "_loop", None)
            if loop is None:
                return

            # Fire-and-forget auf der Kern-Loop: nicht warten, nicht das
            # Ergebnis prüfen. Was beim Sprechen schiefgeht, steht im
            # Protokoll und bleibt folgenlos für den Start.
            import asyncio

            async def _spaeter_gruessen() -> None:
                """Erst begrüßen, wenn der Orb wirklich antworten kann.

                Vorher wurde sofort gesprochen, sobald der Kern stand –
                Whisper lud danach noch mehrere Sekunden. Wer gleich nach
                dem „Ich bin bereit" etwas sagte, wartete trotzdem. Die
                Begrüßung war ein Versprechen, das erst später einlöste.
                """

                warten = getattr(self._runtime.voice, "wait_until_warm", None)
                if warten is not None:
                    await warten()
                await self._runtime.voice.say(text)

            asyncio.run_coroutine_threadsafe(_spaeter_gruessen(), loop)
        except Exception:  # noqa: BLE001 - eine Begrüßung darf NIE den Start kippen.
            logger.debug("Die Begrüßung ließ sich nicht anstoßen.", exc_info=True)

    @staticmethod
    def _default_greeting(result: StartupResult) -> str:
        """Die Standardbegrüßung – kurz, und ehrlich über Einschränkungen.

        Läuft alles, ist es ein schlichtes „Ich bin bereit“. Fehlt etwas
        Entbehrliches (kein Ollama, keine Sprachpakete), sagt der Orb das
        nicht beim Gruß – das steht im Startbericht. Der Gruß bleibt
        freundlich und knapp; niemand will beim Hochfahren einen Vortrag.
        """

        from datetime import datetime

        hour = datetime.now().hour
        if hour < 11:
            tageszeit = "Guten Morgen"
        elif hour < 18:
            tageszeit = "Hallo"
        else:
            tageszeit = "Guten Abend"

        if result.limitations:
            return f"{tageszeit}. Ich bin bereit, mit ein paar Einschränkungen."
        return f"{tageszeit}. Ich bin bereit."

    @staticmethod
    def _describe_blocking(failures: list[Any]) -> str:
        """Erklärt im Klartext, warum nicht gestartet werden konnte."""

        lines = ["AI-Orb konnte nicht starten:", ""]
        for check in failures:
            lines.append(f"  {check.name}: {check.detail}")
            if check.remedy:
                for part in check.remedy.split("\n"):
                    lines.append(f"      {part}")
        return "\n".join(lines)

    # --- API-Server -----------------------------------------------------------------

    def _start_api_server(self) -> None:
        """Startet den lokalen HTTP-Server.

        ``start()`` kehrt sofort zurück – der Server bringt seinen eigenen
        Thread mit. Ihn hier noch einmal in einen Thread zu stecken wäre
        nicht nur überflüssig, sondern würde das geordnete Beenden
        erschweren.
        """

        try:
            from backend.api.server import create_server

            self._server = create_server(self._runtime)
            self._server.start()
            logger.info("Die Schnittstelle zur Oberfläche läuft.")
        except Exception:  # noqa: BLE001
            logger.exception("Der API-Server ließ sich nicht starten.")
            self._server = None

    # --- Überwachung -------------------------------------------------------------------

    def _register_services(self) -> None:
        """Meldet die laufenden Dienste zur Überwachung an.

        Was hier als ``required`` steht, entscheidet, ob ein Ausfall den
        Orb beendet oder nur eine Einschränkung bedeutet.
        """

        runtime = self._runtime
        if runtime is None:
            return

        self.supervisor.register(
            Service(
                name="Backend",
                start=lambda: self._restart_runtime(),
                is_alive=lambda: runtime is not None and runtime.is_running(),
                stop=lambda: runtime.stop(),
                required=True,
                failure_message=(
                    "Der Kern von AI-Orb ist ausgefallen und ließ sich nicht "
                    "wiederherstellen. Starte AI-Orb neu."
                ),
            )
        )

        self.supervisor.register(
            Service(
                name="Voice",
                start=lambda: self._restart_voice(),
                is_alive=lambda: bool(runtime.voice.is_running),
                stop=lambda: None,
                required=False,
                max_restarts=2,
                failure_message=(
                    "Die Sprachsteuerung ist ausgefallen. AI-Orb antwortet "
                    "weiterhin auf getippte Eingaben."
                ),
            )
        )

        if self.ollama.is_installed():
            self.supervisor.register(
                Service(
                    name="Ollama",
                    start=lambda: self.ollama.start()[0],
                    is_alive=self.ollama.is_running,
                    stop=lambda: self.ollama.stop(),
                    required=False,
                    max_restarts=2,
                    failure_message=(
                        "Der Offline-Rückfall ist ausgefallen. Solange Claude "
                        "erreichbar ist, fällt das nicht auf."
                    ),
                )
            )

        # Die überwachten Dienste laufen bereits – als solche vermerken,
        # damit die Überwachung sie nicht sofort neu zu starten versucht.
        for service in self.supervisor._services.values():  # noqa: SLF001
            try:
                if service.is_alive():
                    service.state = type(service.state).RUNNING
                    service.last_started = time.time()
            except Exception:  # noqa: BLE001
                continue

    def _restart_runtime(self) -> bool:
        """Startet den Kern neu."""

        try:
            from backend.runtime import get_runtime

            if self._runtime is not None:
                self._runtime.stop()
            self._runtime = get_runtime()
            self._runtime.start()
            return self._runtime.is_running()
        except Exception:  # noqa: BLE001
            logger.exception("Der Kern ließ sich nicht neu starten.")
            return False

    def _restart_voice(self) -> bool:
        """Startet die Sprachsteuerung neu."""

        if self._runtime is None:
            return False
        try:
            return bool(self._runtime.run(self._runtime.voice.start(), timeout=60.0))
        except Exception:  # noqa: BLE001
            logger.exception("Die Sprachsteuerung ließ sich nicht neu starten.")
            return False

    # --- Beenden -----------------------------------------------------------------------

    def stop(self) -> None:
        """Fährt alles geordnet herunter."""

        logger.info("AI-Orb wird beendet.")

        self.supervisor.stop_watching()

        if self._server is not None:
            try:
                self._server.stop()
            except Exception:  # noqa: BLE001
                logger.debug("Der API-Server ließ sich nicht sauber beenden.", exc_info=True)
            self._server = None

        if self._runtime is not None:
            try:
                self._runtime.stop()
            except Exception:  # noqa: BLE001
                logger.exception("Der Kern ließ sich nicht sauber beenden.")
            self._runtime = None

        # Ollama nur beenden, wenn AI-Orb es gestartet hat – es könnte von
        # etwas anderem benutzt werden.
        self.ollama.stop()

        logger.info("AI-Orb ist beendet.")

    # --- Auskunft ------------------------------------------------------------------------

    @property
    def runtime(self) -> Any | None:
        """Der laufende Kern."""

        return self._runtime

    def is_ready(self) -> bool:
        """Ob AI-Orb betriebsbereit ist."""

        return self._result is not None and self._result.ready

    def status(self) -> dict[str, Any]:
        """Der gesamte Zustand des Launchers."""

        return {
            "ready": self.is_ready(),
            "startup": self._result.to_dict() if self._result else None,
            "supervisor": self.supervisor.status(),
            "ollama": self.ollama.status(),
        }
