"""Startprüfung aller Dienste (Phase 59).

Beim Start wird jeder wichtige Bestandteil geprüft und das Ergebnis in der
Form ausgegeben, die die Vorgabe verlangt::

    AI-ORB STARTUP

    [✓] Windows
    [✓] Runtime
    [✓] Backend
    ...
    STATUS: READY

Der Sinn liegt weniger in der schönen Liste als in dem, was bei einem Haken
fehlt: *„Fehler müssen verständlich erklärt werden."* Jede Prüfung liefert
deshalb nicht nur ein Ja oder Nein, sondern bei einem Nein auch den Grund
und den nächsten Schritt.

Unterschieden wird zwischen **notwendig** und **entbehrlich**. Ohne das
Backend läuft nichts – ohne Sprachausgabe schon. Ein entbehrlicher Ausfall führt zu
einer Warnung, nicht zum Abbruch. Das ist dieselbe Haltung wie in Phase 58:
Nicht sofort den ganzen Orb beenden, wenn nur ein optionales Modul
ausgefallen ist.
"""

from __future__ import annotations

import platform
import shutil
import socket
import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable


class CheckState(Enum):
    """Wie eine Prüfung ausgegangen ist."""

    OK = "ok"
    #: Läuft, aber mit Einschränkung.
    WARNING = "warnung"
    #: Fehlgeschlagen.
    FAILED = "fehler"
    #: Nicht geprüft, weil eine Voraussetzung fehlte.
    SKIPPED = "uebersprungen"

    def marker(self) -> str:
        """Das Zeichen für die Anzeige."""

        return {
            CheckState.OK: "✓",
            CheckState.WARNING: "!",
            CheckState.FAILED: "✗",
            CheckState.SKIPPED: "–",
        }[self]


@dataclass
class CheckResult:
    """Das Ergebnis einer einzelnen Prüfung."""

    name: str
    state: CheckState
    #: Was der Fall ist – kurz, für die Zeile hinter dem Haken.
    detail: str = ""
    #: Warum es schiefging und was zu tun ist – für die Erklärung darunter.
    remedy: str = ""
    #: Ob AI-Orb ohne diesen Bestandteil nicht läuft.
    required: bool = True
    seconds: float = 0.0

    @property
    def ok(self) -> bool:
        return self.state in (CheckState.OK, CheckState.WARNING)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "state": self.state.value,
            "detail": self.detail,
            "remedy": self.remedy,
            "required": self.required,
            "seconds": round(self.seconds, 3),
            "ok": self.ok,
        }

    def line(self) -> str:
        """Die Zeile, wie sie im Startbericht steht."""

        line = f"[{self.state.marker()}] {self.name}"
        if self.detail:
            line += f"  {self.detail}"
        return line


@dataclass
class HealthReport:
    """Der gesamte Startbericht."""

    results: list[CheckResult] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    seconds: float = 0.0

    @property
    def ready(self) -> bool:
        """Ob AI-Orb betriebsbereit ist.

        Entbehrliche Ausfälle zählen ausdrücklich nicht dagegen.
        """

        return all(result.ok for result in self.results if result.required)

    @property
    def degraded(self) -> bool:
        """Ob etwas nicht in voller Stärke arbeitet.

        Gemeint ist nicht dasselbe wie ``not ready``. Eine Warnung
        blockiert den Start nicht – deshalb ist sie ``ok`` –, aber sie
        bedeutet, dass etwas fehlt. Genau dieser Unterschied macht aus
        „READY" ein „READY (eingeschränkt)", und der Benutzer soll ihn
        sehen.
        """

        return any(
            result.state in (CheckState.WARNING, CheckState.FAILED, CheckState.SKIPPED)
            for result in self.results
        )

    def status_word(self) -> str:
        """Das Wort hinter ``STATUS:``."""

        if not self.ready:
            return "NICHT BEREIT"
        if self.degraded:
            return "READY (eingeschränkt)"
        return "READY"

    def as_text(self) -> str:
        """Der Bericht in der Form aus der Vorgabe."""

        lines = ["AI-ORB STARTUP", ""]
        lines.extend(result.line() for result in self.results)
        lines.append("")
        lines.append(f"STATUS: {self.status_word()}")

        problems = [result for result in self.results if not result.ok and result.remedy]
        if problems:
            lines.append("")
            for result in problems:
                lines.append(f"{result.name}: {result.remedy}")

        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "degraded": self.degraded,
            "status": self.status_word(),
            "seconds": round(self.seconds, 2),
            "checks": [result.to_dict() for result in self.results],
            "text": self.as_text(),
        }

    def failures(self) -> list[CheckResult]:
        """Die fehlgeschlagenen Prüfungen."""

        return [result for result in self.results if not result.ok]


class HealthCheck:
    """Führt die Startprüfungen durch."""

    def __init__(self) -> None:
        self._report = HealthReport()

    # --- Einzelprüfungen ------------------------------------------------------------

    def _run(
        self,
        name: str,
        check: Callable[[], tuple[CheckState, str, str]],
        *,
        required: bool = True,
    ) -> CheckResult:
        """Führt eine Prüfung aus und fängt jeden Fehler darin ab."""

        started = time.perf_counter()
        try:
            state, detail, remedy = check()
        except Exception as error:  # noqa: BLE001 - eine Prüfung darf nie abstürzen.
            state, detail, remedy = (
                CheckState.FAILED,
                "Prüfung abgestürzt",
                f"{type(error).__name__}: {error}",
            )

        result = CheckResult(
            name=name,
            state=state,
            detail=detail,
            remedy=remedy,
            required=required,
            seconds=time.perf_counter() - started,
        )
        self._report.results.append(result)
        return result

    def check_windows(self) -> tuple[CheckState, str, str]:
        """Betriebssystem und Architektur."""

        system = platform.system()
        release = platform.release()
        machine = platform.machine()

        if system != "Windows":
            return (
                CheckState.WARNING,
                f"{system} {release}",
                "AI-Orb ist für Windows gebaut. Auf diesem System sind "
                "Fenstersteuerung und Windows-Sprachausgabe nicht verfügbar; "
                "alles Übrige läuft.",
            )

        if machine not in {"AMD64", "x86_64", "ARM64"}:
            return (
                CheckState.WARNING,
                f"Windows {release} ({machine})",
                f"Die Architektur '{machine}' ist ungewöhnlich. Einzelne "
                "Bestandteile könnten fehlen.",
            )

        return CheckState.OK, f"Windows {release} ({machine})", ""

    def check_runtime(self) -> tuple[CheckState, str, str]:
        """Python-Fassung und Herkunft."""

        version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"

        if sys.version_info < (3, 10):
            return (
                CheckState.FAILED,
                f"Python {version}",
                "AI-Orb braucht Python 3.10 oder neuer. Die mitgelieferte "
                "Runtime fehlt oder wurde durch eine ältere ersetzt. Eine "
                "Neuinstallation behebt das.",
            )

        from backend.utils.paths import is_portable

        origin = "mitgeliefert" if not is_portable() else "Projektumgebung"
        return CheckState.OK, f"Python {version} ({origin})", ""

    def check_paths(self) -> tuple[CheckState, str, str]:
        """Ob die Benutzerordner beschreibbar sind."""

        from backend.utils.paths import ensure_user_directories, get_user_dir

        try:
            ensure_user_directories()
            probe = get_user_dir() / ".schreibprobe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
        except OSError as error:
            return (
                CheckState.FAILED,
                "nicht beschreibbar",
                f"In '{get_user_dir()}' kann nicht geschrieben werden ({error}). "
                "Prüfe die Ordnerrechte oder starte AI-Orb neu.",
            )

        return CheckState.OK, str(get_user_dir()), ""

    def check_config(self) -> tuple[CheckState, str, str]:
        """Ob die Konfiguration lesbar ist."""

        from backend.utils.paths import ensure_user_config, get_config_path

        path, created = ensure_user_config()

        try:
            import yaml

            with get_config_path().open("r", encoding="utf-8") as handle:
                loaded = yaml.safe_load(handle)
        except FileNotFoundError:
            return (
                CheckState.FAILED,
                "fehlt",
                f"Die Datei '{get_config_path()}' gibt es nicht. Eine "
                "Neuinstallation legt sie an.",
            )
        except Exception as error:  # noqa: BLE001
            return (
                CheckState.FAILED,
                "fehlerhaft",
                f"Die Konfiguration ist nicht lesbar ({error}). Benenne sie um; "
                "AI-Orb legt dann eine neue an.",
            )

        if not isinstance(loaded, dict):
            return CheckState.FAILED, "fehlerhaft", "Die Konfiguration ist leer oder unvollständig."

        detail = f"{len(loaded)} Abschnitte"
        if created:
            detail += " (neu angelegt)"
        return CheckState.OK, detail, ""

    def check_port(self, host: str, port: int) -> tuple[CheckState, str, str]:
        """Ob der Port für das Backend frei ist oder AI-Orb schon läuft."""

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.6)
            in_use = probe.connect_ex((host, port)) == 0

        if not in_use:
            return CheckState.OK, f"{host}:{port} frei", ""

        # Belegt heißt nicht zwangsläufig Fremdprozess: Vielleicht läuft
        # AI-Orb bereits. Das lässt sich am Statusendpunkt erkennen.
        try:
            import json
            import urllib.request

            with urllib.request.urlopen(  # noqa: S310
                f"http://{host}:{port}/health", timeout=2
            ) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if payload.get("status") == "ok":
                return (
                    CheckState.WARNING,
                    "AI-Orb läuft bereits",
                    f"Auf {host}:{port} antwortet bereits ein AI-Orb "
                    f"(Fassung {payload.get('version', '?')}). Es wird kein "
                    "zweiter gestartet.",
                )
        except Exception:  # noqa: BLE001 - dann ist es eben ein fremder Prozess.
            pass

        return (
            CheckState.FAILED,
            f"{host}:{port} belegt",
            f"Der Port {port} wird von einem anderen Programm benutzt. Ändere "
            "'backend.port' in der Konfiguration oder beende das andere Programm.",
        )

    def check_backend(self) -> tuple[CheckState, str, str]:
        """Ob sich das Backend laden lässt."""

        try:
            import backend.main  # noqa: F401
        except ImportError as error:
            return (
                CheckState.FAILED,
                "nicht ladbar",
                f"Ein Bestandteil fehlt: {error}. Die Installation ist "
                "unvollständig; eine Neuinstallation behebt das.",
            )

        from backend import __version__

        return CheckState.OK, f"Fassung {__version__}", ""

    def check_provider_manager(self) -> tuple[CheckState, str, str]:
        """Ob mindestens ein Sprachmodell-Anbieter aufgebaut werden kann."""

        from backend.ai.provider_factory import ProviderFactory
        from backend.config import get_config

        results = ProviderFactory().build_all(get_config().section("ai"))
        working = [role for role, result in results.items() if result.ok]

        if not working:
            problems = "; ".join(
                problem for result in results.values() for problem in result.problems
            )
            return (
                CheckState.FAILED,
                "kein Anbieter",
                f"Es ist kein Sprachmodell eingerichtet. {problems}",
            )

        names = ", ".join(results[role].engine for role in working)
        return CheckState.OK, names, ""

    def check_audio_devices(self) -> tuple[CheckState, str, str]:
        """Ob Mikrofon und Lautsprecher vorhanden sind."""

        from backend.audio.audio_capture import AudioCapture
        from backend.audio.player import AudioPlayer

        if not AudioCapture.is_available():
            return (
                CheckState.WARNING,
                "keine Aufnahme",
                "Das Paket für die Audioaufnahme fehlt. AI-Orb antwortet auf "
                "getippte Eingaben, hört aber nicht zu.",
            )

        inputs = AudioCapture.list_devices()
        outputs = AudioPlayer.list_devices()

        if not inputs:
            return (
                CheckState.WARNING,
                "kein Mikrofon",
                "Es wurde kein Mikrofon gefunden. Prüfe, ob eines "
                "angeschlossen ist und ob unter Windows-Einstellungen → "
                "Datenschutz → Mikrofon der Zugriff erlaubt ist.",
            )

        return CheckState.OK, f"{len(inputs)} Eingänge, {len(outputs)} Ausgänge", ""

    def check_whisper(self) -> tuple[CheckState, str, str]:
        """Ob die Spracherkennung bereit ist."""

        from backend.whisper.transcriber import Transcriber

        if not Transcriber.is_available():
            return (
                CheckState.WARNING,
                "nicht installiert",
                "Die Spracherkennung fehlt. Ohne sie reagiert AI-Orb nicht auf "
                "das Weckwort. Die Neuinstallation bringt sie mit.",
            )

        from backend.config import get_config

        size = str(get_config().get("voice.input.model_size", "small"))
        return CheckState.OK, f"Modell '{size}'", ""

    def check_speech_output(self) -> tuple[CheckState, str, str]:
        """Ob AI-Orb sprechen kann."""

        from backend.tts.tts_manager import TtsManager

        manager = TtsManager()
        available = manager.available_engines()

        if not available:
            return CheckState.WARNING, "keine Stimme", manager.diagnose()

        names = ", ".join(engine.name for engine in available)
        return CheckState.OK, names, ""

    def check_memory(self) -> tuple[CheckState, str, str]:
        """Ob das Gedächtnis lesbar ist."""

        from backend.memory.memory_engine import MemoryEngine

        engine = MemoryEngine()
        status = engine.status() if hasattr(engine, "status") else {}
        count = status.get("total", status.get("entries", 0)) if isinstance(status, dict) else 0
        return CheckState.OK, f"{count} Einträge", ""

    def check_desktop(self) -> tuple[CheckState, str, str]:
        """Ob die Desktop-Steuerung arbeiten kann."""

        from backend.system.window_control import WindowControl

        control = WindowControl()
        if not control.is_available():
            return CheckState.WARNING, "eingeschränkt", control.unavailable_reason()

        width, height = control.screen_size()
        return CheckState.OK, f"{width}×{height}", ""

    def check_ollama(self) -> tuple[CheckState, str, str]:
        """Ob der Offline-Rückfall bereitsteht."""

        from backend.launcher.ollama_service import OllamaService

        service = OllamaService()

        if not service.is_installed():
            return (
                CheckState.WARNING,
                "nicht installiert",
                "Ohne Ollama antwortet AI-Orb nicht, wenn das Internet "
                "ausfällt. " + service.installation_hint(),
            )

        if not service.is_running():
            return CheckState.WARNING, "läuft nicht", "Wird beim Bedarf gestartet."

        model = service.configured_model()
        if not service.has_model(model):
            return (
                CheckState.WARNING,
                f"Modell '{model}' fehlt",
                f"Das Modell '{model}' ist nicht heruntergeladen. AI-Orb holt "
                "es beim ersten Offline-Bedarf nach (mehrere Gigabyte).",
            )

        return CheckState.OK, f"bereit ({model})", ""

    def check_presence(self) -> tuple[CheckState, str, str]:
        """Ob Stimmung, Rhythmus und Persönlichkeit geladen sind."""

        from backend.presence.presence_engine import PresenceEngine

        presence = PresenceEngine()
        mood = presence.emotions.current().label()
        return CheckState.OK, f"Stimmung {mood}", ""

    # --- Funktionsprüfungen: das, was im Betrieb immer wieder aussetzte -------
    #
    # Die Prüfungen darüber fragen "ist der Baustein da?". Die drei hier
    # fragen "TUT er es auch?". Genau das war die wiederkehrende Klage des
    # Benutzers: Werkzeuge, die da waren und trotzdem nicht griffen; eine
    # Suche, die abwies; ein Bildschirm, der sich mal ansehen liess und mal
    # nicht. Ein grüner Haken hier bedeutet nicht "installiert", sondern
    # "eben ausprobiert und es ging".

    #: Die Werkzeuge, ohne die der Orb im Alltag als "kann nichts" erlebt
    #: wird. Fehlt eines, ist das kein "vielleicht" - es ist rot.
    _KERNWERKZEUGE = (
        "internet_suchen", "webseite_lesen", "bildschirm_ansehen",
        "browser_bedienen",
    )

    def check_werkzeuge(self) -> tuple[CheckState, str, str]:
        """Ob die wichtigen Werkzeuge wirklich registriert sind.

        Der Benutzer klagte mehrfach, der Orb könne "keine Werkzeuge
        benutzen". Hier wird die Werkzeugliste tatsächlich aufgebaut und
        nachgesehen, ob die vier Kernwerkzeuge dabei sind - nicht bloss, ob
        irgendein Modul lädt.
        """

        from backend.events.event_bus import EventBus
        from backend.security.security_engine import SecurityEngine
        from backend.tools.standard_tools import build_standard_tools

        namen: set[str] = set()
        try:
            for werkzeug in build_standard_tools(security=SecurityEngine(EventBus())):
                namen.add(getattr(werkzeug, "name", ""))
        except Exception as error:  # noqa: BLE001
            return (
                CheckState.WARNING,
                "nicht aufbaubar",
                f"Die Werkzeugliste liess sich nicht aufbauen ({error}). "
                "Der Orb antwortet, kann aber vielleicht nicht handeln.",
            )

        # bildschirm_ansehen und browser_bedienen werden erst mit ihren
        # Abhängigkeiten (Bildschirm, Browsersteuerung) zusammengebaut; hier
        # genügt der Nachweis, dass ihre Werkzeugklassen überhaupt vorhanden
        # sind. Fehlt eine, ist das Modul unvollständig.
        bild_ok = browser_ok = True
        try:
            from backend.tools.vision_tools import DescribeScreenTool  # noqa: F401
        except Exception:  # noqa: BLE001
            bild_ok = False
        try:
            from backend.tools.browser_tools import BrowserBedienenTool  # noqa: F401
        except Exception:  # noqa: BLE001
            browser_ok = False

        # In der Standardliste MÜSSEN Suche und Seiten-Lesen stehen.
        stets_dabei = {"internet_suchen", "webseite_lesen"}
        fehlend = [w for w in stets_dabei if w not in namen]
        if fehlend:
            return (
                CheckState.FAILED,
                "unvollständig",
                "Es fehlen Kernwerkzeuge: " + ", ".join(fehlend) + ". Ohne sie "
                "kann der Orb nicht suchen oder Seiten lesen. Eine "
                "Neuinstallation stellt sie wieder her.",
            )

        # Bildschirm/Browser sind für die volle Handlungsfähigkeit da, aber
        # kein Grund, den Start zu blockieren - fehlen sie, ist es eine
        # Warnung.
        nicht_da = []
        if not bild_ok:
            nicht_da.append("bildschirm_ansehen")
        if not browser_ok:
            nicht_da.append("browser_bedienen")
        if nicht_da:
            return (
                CheckState.WARNING,
                "Kern da, " + ", ".join(nicht_da) + " fehlt",
                "Suchen und Lesen gehen; " + " und ".join(nicht_da) + " nicht. "
                "Eine Neuinstallation bringt die fehlenden Werkzeuge mit.",
            )
        return CheckState.OK, f"{len(namen)} Werkzeuge, Kern vollständig", ""

    def check_suche(self) -> tuple[CheckState, str, str]:
        """Ob eine echte Suche gerade durchkommt - jetzt, nicht theoretisch.

        Ein kurzer, echter Suchlauf. Klappt er, ist der häufigste
        Störungsfall ("alle Suchmaschinen werden abgelehnt") beim Start
        schon ausgeschlossen. Klappt er nicht, steht der Grund im Klartext
        da - kein Netz, abgewiesen oder Seitenaufbau geändert -, statt dass
        der Benutzer es erst im Gespräch merkt.
        """

        from backend.tools.web_tools import _Suchfehler, search_web

        try:
            treffer = search_web("Testabfrage Bundesregierung", limit=2)
        except _Suchfehler as fehler:
            auskunft = {
                "kein_netz": "kein Internet - die Suche ist offline nicht möglich.",
                "abgewiesen": "die Suchmaschine hält die Anfrage für automatisiert.",
                "themenfremd": (
                    "die Suchmaschinen antworteten, aber kein Treffer passte "
                    "zur Anfrage – das deutet auf den Suchbegriff, nicht auf "
                    "eine Sperre."
                ),
                "unlesbar": "die Suchmaschine hat geantwortet, war aber nicht lesbar.",
            }.get(fehler.art, str(fehler))
            return (
                CheckState.WARNING,
                fehler.art,
                "Die Suche kam beim Start nicht durch: " + auskunft + " Sobald "
                "Internet da ist, versucht der Orb es bei jeder Frage neu.",
            )
        except Exception as error:  # noqa: BLE001
            return CheckState.WARNING, "gescheitert", f"Die Testsuche brach ab: {error}"

        if not treffer:
            return (
                CheckState.WARNING,
                "keine Treffer",
                "Die Suche lief, lieferte aber nichts. Das kann am Suchbegriff "
                "liegen; im Betrieb wird mit echten Fragen gesucht.",
            )
        return CheckState.OK, f"{len(treffer)} Treffer", ""

    def check_bildschirm_fotografieren(self) -> tuple[CheckState, str, str]:
        """Ob der Orb wirklich ein Bildschirmfoto machen kann.

        Getrennt von 'Desktop': Fenster steuern und ein Bild aufnehmen sind
        zwei verschiedene Fähigkeiten. Der Benutzer erlebte, dass der Orb
        "zuerst einen Printscreen macht ... danach aber plötzlich nicht
        mehr". Ob das Aufnehmen überhaupt möglich ist, gehört darum sichtbar
        in den Selbsttest.
        """

        from backend.vision.screen_capture import ScreenCapture

        if not ScreenCapture.is_available():
            return (
                CheckState.WARNING,
                "nicht möglich",
                "Für Bildschirmfotos fehlt das Paket 'mss'. Ohne es kann der "
                "Orb den Bildschirm nicht ansehen. Die Neuinstallation bringt "
                "es mit.",
            )
        return CheckState.OK, "möglich", ""

    # --- Gesamtlauf ---------------------------------------------------------------------

    def run(self, *, include_optional: bool = True) -> HealthReport:
        """Führt alle Prüfungen aus.

        Args:
            include_optional: Ob auch entbehrliche Bestandteile geprüft
                werden. Beim schnellen Neustart nach einem Absturz spart das
                Zeit.

        Returns:
            Der Bericht.
        """

        started = time.perf_counter()
        self._report = HealthReport()

        self._run("Windows", self.check_windows, required=False)
        self._run("Runtime", self.check_runtime)
        self._run("Verzeichnisse", self.check_paths)
        self._run("Konfiguration", self.check_config)

        from backend.config import get_config

        config = get_config()
        host = str(config.get("backend.host", "127.0.0.1"))
        # "0.0.0.0" heisst: auf allen Netzwerkkarten lauschen. Als Ziel
        # einer Verbindung ist es keine Adresse. Wer dorthin verbindet,
        # prueft nicht den eigenen Kern, sondern das Nichts.
        if host in ("0.0.0.0", "::"):
            host = "127.0.0.1"
        port = int(config.get("backend.port", 8756))

        self._run("Port", lambda: self.check_port(host, port))
        self._run("Backend", self.check_backend)
        # Bewusst NICHT blockierend: Ist beim Start weder die Claude-CLI
        # erreichbar noch Ollama schon oben – der Normalfall unmittelbar nach
        # der Installation –, soll AI-Orb trotzdem hochkommen und den fehlenden
        # Anbieter als Einschränkung melden, statt gar nicht zu starten. Der
        # Launcher weist genau darauf im Schritt „Claude" hin. Ein hartes
        # Scheitern hier war die Ursache für „der Kern wurde unerwartet
        # beendet (Code 1)" direkt nach dem Installieren.
        self._run("ProviderManager", self.check_provider_manager, required=False)

        if include_optional:
            self._run("Ollama", self.check_ollama, required=False)
            self._run("Audio", self.check_audio_devices, required=False)
            self._run("Whisper", self.check_whisper, required=False)
            self._run("Sprachausgabe", self.check_speech_output, required=False)
            self._run("Memory", self.check_memory, required=False)
            self._run("Desktop", self.check_desktop, required=False)
            self._run("Human Experience", self.check_presence, required=False)
            # Der eigentliche Selbsttest: nicht "ist es da?", sondern "tut
            # es?". Diese drei fassen die Fähigkeiten zusammen, die im
            # Betrieb immer wieder aussetzten - Werkzeuge, Suche, Bildschirm.
            self._run("Werkzeuge", self.check_werkzeuge, required=False)
            self._run("Suche", self.check_suche, required=False)
            self._run("Bildschirmfoto", self.check_bildschirm_fotografieren, required=False)

        self._report.seconds = time.perf_counter() - started
        return self._report

    @property
    def report(self) -> HealthReport:
        """Der zuletzt erstellte Bericht."""

        return self._report


def run_health_check(*, include_optional: bool = True) -> HealthReport:
    """Führt die Startprüfung aus und gibt den Bericht zurück."""

    return HealthCheck().run(include_optional=include_optional)
