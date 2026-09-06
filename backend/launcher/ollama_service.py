"""Ollama als Offline-Rückfall (Phase 49).

Die Vorgabe ist eindeutig: *„Der Benutzer darf Ollama nicht manuell über die
Kommandozeile starten müssen."* Dieses Modul erledigt das – es findet
Ollama, startet den Dienst, prüft das Modell und meldet den Ladestand.

Eine Grenze wird dabei offen benannt: Ollama ist ein eigenständiges
Programm mit eigenem Installationsprogramm. AI-Orb kann es **starten**, wenn
es da ist, und den Benutzer beim Installieren führen, wenn es fehlt – aber
es nicht ungefragt im Hintergrund installieren. Das wäre auch nach den
Sicherheitsvorgaben nicht zulässig: keine automatische Installation von
Abhängigkeiten.

Ebenso beim Modell. ``lfm2.5:8b`` sind rund fünf Gigabyte. Ein Programm,
das die ungefragt herunterlädt, ist ein schlechtes Programm. AI-Orb fragt,
zeigt den Fortschritt und lässt sich abbrechen.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

from backend.system.logging_setup import get_logger

logger = get_logger(__name__)

#: Wo Ollama unter Windows üblicherweise landet, wenn es nicht im PATH steht.
WINDOWS_CANDIDATES: tuple[str, ...] = (
    r"%LOCALAPPDATA%\Programs\Ollama\ollama.exe",
    r"%PROGRAMFILES%\Ollama\ollama.exe",
    r"%PROGRAMFILES(X86)%\Ollama\ollama.exe",
)

#: Wie lange nach dem Start auf den Dienst gewartet wird.
STARTUP_TIMEOUT = 25.0


class OllamaService:
    """Findet, startet und überwacht Ollama."""

    def __init__(self, *, base_url: str = "", model: str = "") -> None:
        """
        Args:
            base_url: Adresse des Dienstes. Leer nimmt die Konfiguration.
            model: Das zu verwendende Modell. Leer nimmt die Konfiguration.
        """

        self._base_url = base_url.rstrip("/")
        self._model = model
        self._process: subprocess.Popen[bytes] | None = None
        self._pull_progress: dict[str, Any] = {}
        self._pull_thread: threading.Thread | None = None

    # --- Konfiguration ---------------------------------------------------------

    def _ollama_section(self) -> dict[str, Any]:
        """Der Abschnitt der Konfiguration, in dem Ollama tatsächlich steht.

        Früher wurde fest unter ``ai.fallback`` nachgesehen, weil Ollama dort
        eingetragen war: vorne ein Anbieter aus dem Netz, hinten das lokale
        Modell. Wer auf Offline-Betrieb umstellt, tauscht die beiden – und
        seitdem las diese Klasse den falschen Abschnitt. Sie fragte Ollama
        dann nach ``sonnet``, fand es dort erwartungsgemäß nicht und meldete
        beim Start eine Einschränkung, die es nicht gab: das lokale Modell
        müsse erst geladen werden, mehrere Gigabyte. Es lag längst da.

        Deshalb wird jetzt nicht nach dem Platz gesucht, sondern nach der
        Maschine: genommen wird der Abschnitt, in dem ``engine: ollama``
        steht, egal ob er vorn oder hinten hängt.
        """

        try:
            from backend.config import get_config

            konfiguration = get_config()
        except Exception:  # noqa: BLE001 - vor dem Laden der Konfiguration nutzbar.
            return {}

        for rolle in ("ai.primary", "ai.fallback"):
            try:
                abschnitt = konfiguration.get(rolle, {}) or {}
            except Exception:  # noqa: BLE001
                continue
            if not isinstance(abschnitt, dict):
                continue
            if str(abschnitt.get("engine", "")).strip().lower() == "ollama":
                return dict(abschnitt)

        # Kein Abschnitt nennt Ollama - dann gilt weiterhin der Rückfall,
        # damit Adresse und Modellname nicht ins Leere zeigen.
        try:
            abschnitt = konfiguration.get("ai.fallback", {}) or {}
        except Exception:  # noqa: BLE001
            return {}
        return dict(abschnitt) if isinstance(abschnitt, dict) else {}

    #: Alter Name, damit vorhandene Aufrufe nichts merken.
    _fallback_section = _ollama_section

    def base_url(self) -> str:
        """Die Adresse des Dienstes."""

        if self._base_url:
            return self._base_url
        configured = str(self._ollama_section().get("base_url", "")).strip()
        return (configured or "http://127.0.0.1:11434").rstrip("/")

    def configured_model(self) -> str:
        """Das in der Konfiguration eingetragene Modell."""

        if self._model:
            return self._model
        return str(self._ollama_section().get("model", "lfm2.5:8b")).strip()

    # --- Auffinden ---------------------------------------------------------------

    def executable(self) -> str | None:
        """Findet das Ollama-Programm.

        Unter Windows landet es häufig unter ``%LOCALAPPDATA%`` und ist
        dann nicht im PATH – die üblichen Orte werden deshalb mitgeprüft.
        """

        found = shutil.which("ollama")
        if found:
            return found

        if platform.system() == "Windows":
            for candidate in WINDOWS_CANDIDATES:
                path = Path(os.path.expandvars(candidate))
                try:
                    if path.is_file():
                        return str(path)
                except OSError:
                    # Ein gesperrter oder nicht erreichbarer Installationsort
                    # bedeutet nicht, dass der ganze Status-Endpunkt scheitern
                    # darf. Weitere Kandidaten koennen weiterhin gueltig sein.
                    logger.debug("Ollama-Kandidat nicht lesbar: %s", path, exc_info=True)

        return None

    def is_installed(self) -> bool:
        """Ob Ollama vorhanden ist."""

        return self.executable() is not None

    def installation_hint(self) -> str:
        """Wie Ollama zu bekommen ist."""

        if platform.system() == "Windows":
            return (
                "Ollama installieren:\n"
                "    winget install Ollama.Ollama\n"
                "oder herunterladen von https://ollama.com/download\n"
                "Danach AI-Orb neu starten."
            )
        return "Ollama installieren: https://ollama.com/download"

    # --- Zustand -------------------------------------------------------------------

    def is_running(self, *, timeout: float = 2.0) -> bool:
        """Ob der Dienst antwortet."""

        try:
            with urllib.request.urlopen(  # noqa: S310
                f"{self.base_url()}/api/tags", timeout=timeout
            ) as response:
                return response.status == 200
        except (urllib.error.URLError, OSError, TimeoutError):
            return False

    def models(self) -> list[str]:
        """Die lokal vorhandenen Modelle."""

        try:
            with urllib.request.urlopen(  # noqa: S310
                f"{self.base_url()}/api/tags", timeout=5
            ) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError):
            return []

        return [str(entry.get("name", "")) for entry in payload.get("models", []) if entry]

    def has_model(self, name: str = "") -> bool:
        """Ob ein Modell vorhanden ist.

        Der Vergleich ist nachsichtig: Ollama führt ``llama3.1:8b``
        gelegentlich als ``llama3.1:8b-instruct-q4_0``. Wer das Grundmodell
        verlangt, soll damit zufrieden sein.
        """

        wanted = (name or self.configured_model()).strip().lower()
        if not wanted:
            return False

        available = [entry.lower() for entry in self.models()]
        if wanted in available:
            return True

        base = wanted.split(":")[0]
        return any(entry.split(":")[0] == base for entry in available)

    # --- Starten ---------------------------------------------------------------------

    def start(self, *, timeout: float = STARTUP_TIMEOUT) -> tuple[bool, str]:
        """Startet den Dienst, falls er nicht läuft.

        Returns:
            Erfolg und eine Meldung im Klartext.
        """

        if self.is_running():
            return True, "Ollama läuft bereits."

        executable = self.executable()
        if executable is None:
            return False, (
                "Ollama ist nicht installiert. Ohne es antwortet AI-Orb nicht, "
                "wenn das Internet ausfällt.\n" + self.installation_hint()
            )

        logger.info("Ollama wird gestartet.")

        try:
            # Ohne Fenster starten – die Vorgabe verlangt, dass der Benutzer
            # keine Kommandozeile zu sehen bekommt.
            creation_flags = 0
            if platform.system() == "Windows":
                creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

            self._process = subprocess.Popen(  # noqa: S603
                [executable, "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creation_flags,
            )
        except OSError as error:
            return False, f"Ollama ließ sich nicht starten: {error}"

        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.is_running(timeout=1.0):
                logger.info("Ollama ist bereit.")
                return True, "Ollama läuft."
            time.sleep(0.5)

        return False, (
            f"Ollama hat nach {timeout:.0f} Sekunden nicht geantwortet. "
            "Starte es einmal von Hand, um die Meldung zu sehen."
        )

    def stop(self) -> bool:
        """Beendet den von AI-Orb gestarteten Dienst.

        Ein Ollama, das schon vorher lief, wird nicht angerührt – es könnte
        von etwas anderem benutzt werden.
        """

        if self._process is None:
            return False

        try:
            self._process.terminate()
            self._process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            self._process.kill()
        except OSError:
            return False
        finally:
            self._process = None

        logger.info("Ollama beendet.")
        return True

    # --- Modelle laden ---------------------------------------------------------------

    def pull_model(
        self,
        name: str = "",
        *,
        on_progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> tuple[bool, str]:
        """Lädt ein Modell herunter. Blockierend.

        Args:
            name: Das Modell. Leer nimmt das konfigurierte.
            on_progress: Wird mit dem Fortschritt aufgerufen.

        Returns:
            Erfolg und eine Meldung.
        """

        model = (name or self.configured_model()).strip()
        if not model:
            return False, "Es ist kein Modell eingetragen."

        if not self.is_running():
            started, message = self.start()
            if not started:
                return False, message

        logger.info("Das Modell '%s' wird geladen. Das dauert und ist groß.", model)

        request = urllib.request.Request(  # noqa: S310
            f"{self.base_url()}/api/pull",
            data=json.dumps({"name": model, "stream": True}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )

        try:
            with urllib.request.urlopen(request, timeout=None) as response:  # noqa: S310
                for raw in response:
                    line = raw.decode("utf-8", errors="replace").strip()
                    if not line:
                        continue

                    try:
                        payload = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    self._pull_progress = self._describe_progress(payload, model)

                    if on_progress is not None:
                        try:
                            on_progress(self._pull_progress)
                        except Exception:  # noqa: BLE001
                            logger.debug("Fortschrittsmeldung fehlgeschlagen.", exc_info=True)

                    if payload.get("error"):
                        return False, str(payload["error"])

        except (urllib.error.URLError, OSError) as error:
            return False, f"Der Download ist fehlgeschlagen: {error}"

        self._pull_progress = {"model": model, "status": "fertig", "percent": 100.0}
        return True, f"Das Modell '{model}' ist bereit."

    @staticmethod
    def _describe_progress(payload: dict[str, Any], model: str) -> dict[str, Any]:
        """Übersetzt Ollamas Fortschrittsmeldung in etwas Lesbares."""

        completed = float(payload.get("completed", 0) or 0)
        total = float(payload.get("total", 0) or 0)
        percent = (completed / total * 100.0) if total > 0 else 0.0

        return {
            "model": model,
            "status": str(payload.get("status", "")),
            "percent": round(percent, 1),
            "completed_mb": round(completed / 1024 / 1024, 1),
            "total_mb": round(total / 1024 / 1024, 1),
        }

    def pull_model_async(
        self, name: str = "", *, on_progress: Callable[[dict[str, Any]], None] | None = None
    ) -> None:
        """Lädt ein Modell im Hintergrund."""

        if self._pull_thread is not None and self._pull_thread.is_alive():
            return

        self._pull_thread = threading.Thread(
            target=lambda: self.pull_model(name, on_progress=on_progress),
            name="ai-orb-ollama-pull",
            daemon=True,
        )
        self._pull_thread.start()

    def pull_progress(self) -> dict[str, Any]:
        """Der Stand eines laufenden Downloads."""

        return dict(self._pull_progress)

    # --- Gesamtvorbereitung ---------------------------------------------------------------

    def prepare(self, *, download_model: bool = False) -> dict[str, Any]:
        """Bringt Ollama in einen brauchbaren Zustand.

        Der Ablauf entspricht der Vorgabe: vorhanden? – ja, dann prüfen; –
        nein, dann vorbereiten. Das Modell wird nur auf ausdrücklichen
        Wunsch geladen; mehrere Gigabyte lädt man nicht nebenbei.

        Returns:
            Was der Fall ist und was gegebenenfalls noch fehlt.
        """

        if not self.is_installed():
            return {
                "ready": False,
                "installed": False,
                "running": False,
                "model_ready": False,
                "message": "Ollama ist nicht installiert.",
                "remedy": self.installation_hint(),
            }

        started, message = self.start()
        if not started:
            return {
                "ready": False,
                "installed": True,
                "running": False,
                "model_ready": False,
                "message": message,
                "remedy": "Starte Ollama einmal von Hand, um die Meldung zu sehen.",
            }

        model = self.configured_model()
        model_ready = self.has_model(model)

        if not model_ready and download_model:
            downloaded, download_message = self.pull_model(model)
            model_ready = downloaded
            message = download_message

        return {
            "ready": model_ready,
            "installed": True,
            "running": True,
            "model_ready": model_ready,
            "model": model,
            "message": message
            if model_ready
            else f"Das Modell '{model}' ist noch nicht heruntergeladen.",
            "remedy": ""
            if model_ready
            else (
                f"AI-Orb lädt '{model}' beim ersten Offline-Bedarf nach. Das "
                "sind mehrere Gigabyte und dauert entsprechend."
            ),
        }

    def status(self) -> dict[str, Any]:
        """Statusangaben für die Transparenzansicht."""

        installed = self.is_installed()
        running = self.is_running() if installed else False

        return {
            "installed": installed,
            "executable": self.executable() or "",
            "running": running,
            "base_url": self.base_url(),
            "model": self.configured_model(),
            "model_ready": self.has_model() if running else False,
            "available_models": self.models() if running else [],
            "started_by_orb": self._process is not None,
            "pull_progress": self.pull_progress(),
        }
