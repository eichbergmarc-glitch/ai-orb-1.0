"""Vision Engine – der Orb schaut auf den Bildschirm (v2 Phase 17).

Führt Aufnahme, Texterkennung und Bildbeschreibung zusammen. Der Nutzen ist
groß: „Was steht hier in dieser Fehlermeldung?" ist eine Frage, die man
sonst abtippen müsste.

Der Preis ist es ebenso. Ein Bildschirmbild kann alles enthalten – geöffnete
Nachrichten, Kontostände, Passwörter. Deshalb gelten hier strengere Regeln
als sonst irgendwo im Programm:

**Jede Aufnahme wird einzeln freigegeben.** Es gibt keine gemerkte
Zustimmung für den Bildschirm; die Berechtigung ``screen_capture`` ist als
heikel eingestuft und wird bei jeder Nutzung neu erfragt, sofern der Benutzer
sie nicht selbst vorab in der Konfiguration erteilt hat.

**Die Übertragung ist ein zweiter Schritt.** Aufnehmen und an ein
Sprachmodell geben sind getrennte Vorgänge mit getrennter Zustimmung. Wer
nur den Text ausgelesen haben will, muss das Bild nicht aus der Hand geben –
die Texterkennung läuft lokal.

**Nichts bleibt liegen.** Aufnahmen werden nach kurzer Zeit gelöscht, und
nach einer Auswertung sofort, sofern nicht ausdrücklich anders gewünscht.
"""

from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.config import get_config
from backend.security.security_engine import SecurityEngine
from backend.system.logging_setup import get_logger
from backend.vision.screen_capture import Capture, ScreenCapture, ScreenRegion
from backend.vision.text_recognition import TextRecognition, TextResult

logger = get_logger(__name__)


@dataclass
class VisionResult:
    """Das Ergebnis einer Bildschirmauswertung."""

    ok: bool = False
    #: Die Antwort in normaler Sprache.
    answer: str = ""
    #: Der erkannte Text, falls ausgelesen wurde.
    text: str = ""
    #: Klartextbegründung bei Misserfolg.
    error: str = ""
    #: Ob das Bild an ein Sprachmodell gegeben wurde.
    image_sent: bool = False
    capture: Capture | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "answer": self.answer,
            "text": self.text[:2000],
            "error": self.error,
            "image_sent": self.image_sent,
            "capture": self.capture.to_dict() if self.capture else None,
        }


class VisionEngine:
    """Nimmt den Bildschirm auf und wertet ihn aus."""

    def __init__(self, *, security: SecurityEngine, provider_manager: Any) -> None:
        config = get_config()

        self._security = security
        self._providers = provider_manager

        self._enabled = bool(config.get("vision.enabled", True))
        self._keep_after_analysis = bool(config.get("vision.keep_after_analysis", False))
        self._allow_image_to_model = bool(config.get("vision.allow_image_to_model", True))

        self._capture = ScreenCapture(
            max_edge=int(config.get("vision.max_edge", 1600)),
            keep_minutes=float(config.get("vision.keep_minutes", 10)),
        )
        self._ocr = TextRecognition(
            languages=str(config.get("vision.ocr_languages", "deu+eng")),
        )

    @property
    def enabled(self) -> bool:
        """Ob das Bildverstehen eingeschaltet ist."""

        return self._enabled

    # --- Aufnahme -------------------------------------------------------------------

    async def take_screenshot(
        self,
        *,
        monitor: int = 1,
        region: ScreenRegion | None = None,
        purpose: str = "",
        actor: str = "vision",
    ) -> Capture:
        """Nimmt den Bildschirm auf – nach Freigabe.

        Args:
            monitor: Welcher Bildschirm.
            region: Ausschnitt; ``None`` nimmt alles.
            purpose: Wofür – wird im Zustimmungsdialog gezeigt.
            actor: Wer fragt.

        Returns:
            Die Aufnahme oder eine Fehlerbeschreibung.
        """

        if not self._enabled:
            return Capture(error="Das Bildverstehen ist in config.yaml ausgeschaltet.")

        if not ScreenCapture.is_available():
            return Capture(error=ScreenCapture.installation_hint())

        what = "einen Ausschnitt des Bildschirms" if region else "den ganzen Bildschirm"
        detail = f"{what} aufnehmen"
        if purpose:
            detail += f", um {purpose}"
        detail += ". Die Aufnahme bleibt auf diesem Rechner."

        decision = await self._security.require(
            actor, "screen_capture", detail, context={"monitor": monitor}
        )
        if not decision.allowed:
            return Capture(error=f"Nicht aufgenommen: {decision.reason}")

        capture = await asyncio.to_thread(
            self._capture.capture_blocking, monitor=monitor, region=region
        )

        self._security.record_action(
            actor,
            "screen_capture",
            detail,
            succeeded=capture.succeeded,
            context={"path": str(capture.path) if capture.path else ""},
        )
        return capture

    # --- Texterkennung -----------------------------------------------------------------

    async def read_screen(
        self,
        *,
        monitor: int = 1,
        region: ScreenRegion | None = None,
        actor: str = "vision",
    ) -> VisionResult:
        """Liest den Text vom Bildschirm.

        Läuft vollständig lokal: Das Bild verlässt den Rechner nicht.
        """

        capture = await self.take_screenshot(
            monitor=monitor,
            region=region,
            purpose="den darauf stehenden Text auszulesen",
            actor=actor,
        )

        if not capture.succeeded:
            return VisionResult(error=capture.error, capture=capture)

        if not TextRecognition.is_available():
            self._discard(capture)
            return VisionResult(
                error=TextRecognition.installation_hint(), capture=capture
            )

        text_result: TextResult = await asyncio.to_thread(self._ocr.read_blocking, capture.path)

        if not self._keep_after_analysis:
            self._discard(capture)

        if text_result.error:
            return VisionResult(error=text_result.error, capture=capture)

        if not text_result.text.strip():
            return VisionResult(
                ok=True,
                answer="Auf dem Bildschirm ist kein lesbarer Text zu finden.",
                capture=capture,
            )

        return VisionResult(
            ok=True,
            answer=text_result.text,
            text=text_result.text,
            capture=capture,
        )

    # --- Bildbeschreibung ---------------------------------------------------------------

    async def describe_screen(
        self,
        question: str = "",
        *,
        monitor: int = 1,
        region: ScreenRegion | None = None,
        actor: str = "vision",
    ) -> VisionResult:
        """Lässt ein Sprachmodell beschreiben, was auf dem Bildschirm zu sehen ist.

        Hier verlässt das Bild den Rechner. Deshalb wird dafür ein zweites
        Mal gefragt, mit unmissverständlicher Ansage.

        Args:
            question: Was genau wissenswert ist. Leer heißt: beschreiben.
            monitor: Welcher Bildschirm.
            region: Ausschnitt.
            actor: Wer fragt.
        """

        if not self._allow_image_to_model:
            return VisionResult(
                error=(
                    "Das Übertragen von Bildschirmbildern an ein Sprachmodell ist "
                    "in config.yaml ausgeschaltet ('vision.allow_image_to_model'). "
                    "Der Text lässt sich trotzdem lokal auslesen."
                )
            )

        capture = await self.take_screenshot(
            monitor=monitor,
            region=region,
            purpose="dich zu fragen, was darauf zu sehen ist",
            actor=actor,
        )

        if not capture.succeeded:
            return VisionResult(error=capture.error, capture=capture)

        decision = await self._security.require(
            actor,
            "network",
            "Diese Bildschirmaufnahme an das Sprachmodell übertragen. Das Bild "
            "verlässt damit deinen Rechner. Prüfe, ob darauf etwas zu sehen ist, "
            "das niemand sonst sehen soll.",
            context={"path": str(capture.path)},
        )

        if not decision.allowed:
            self._discard(capture)
            return VisionResult(
                error=f"Das Bild wurde nicht übertragen: {decision.reason}", capture=capture
            )

        prompt = question.strip() or "Beschreibe, was auf diesem Bildschirmbild zu sehen ist."

        try:
            answer = await self._ask_with_image(capture.path, prompt)
        except Exception as error:  # noqa: BLE001
            logger.exception("Die Bildauswertung ist fehlgeschlagen.")
            self._discard(capture)
            return VisionResult(error=f"Die Auswertung ist fehlgeschlagen: {error}", capture=capture)
        finally:
            if not self._keep_after_analysis:
                self._discard(capture)

        self._security.record_action(
            actor, "network", "Bildschirmaufnahme an das Sprachmodell übertragen."
        )

        return VisionResult(ok=True, answer=answer, image_sent=True, capture=capture)

    async def _ask_with_image(self, path: Path | None, prompt: str) -> str:
        """Gibt Bild und Frage an das Sprachmodell.

        Nicht jeder Anbieter kann Bilder. Kann er es nicht, wird der Text
        lokal ausgelesen und stattdessen dieser mitgegeben – das ist
        schlechter als ein Bild, aber besser als eine Absage.
        """

        if path is None:
            return "Es gibt kein Bild zum Auswerten."

        provider = getattr(self._providers, "active_provider", None)
        supports_images = bool(getattr(provider, "supports_images", False))
        reads_files = bool(getattr(provider, "reads_local_files", False))

        # Der Weg für Claude Code: den Pfad nennen, die Datei öffnet es
        # selbst.
        #
        # Vorher war das der blinde Fleck der ganzen Bildauswertung: Geprüft
        # wurde nur ``supports_images``, und das setzt kein einziger
        # Anbieter. Der Orb landete deshalb IMMER beim Rückfall auf
        # Texterkennung – die ohne Tesseract nicht kann – und meldete, er
        # könne keine Bilder ansehen. Dabei kann Claude Code genau das,
        # sobald es weiß, wo die Datei liegt.
        if not supports_images and reads_files:
            response = await self._providers.complete(
                f"Sieh dir das Bildschirmfoto unter diesem Pfad an und "
                f"beantworte damit die Frage.\n\nPfad: {path}\n\n"
                f"Frage: {prompt}",
                system_prompt=(
                    "Du beschreibst Bildschirmbilder sachlich und knapp. "
                    "Öffne die genannte Bilddatei und beziehe dich nur auf "
                    "das, was darauf wirklich zu sehen ist."
                ),
            )
            return self._as_text(response)

        if supports_images:
            encoded = base64.b64encode(path.read_bytes()).decode("ascii")
            response = await self._providers.complete(
                prompt,
                system_prompt="Du beschreibst Bildschirmbilder sachlich und knapp.",
                images=[{"media_type": "image/png", "data": encoded}],
            )
            return self._as_text(response)

        text_result = await asyncio.to_thread(self._ocr.read_blocking, path)
        if text_result.error or not text_result.text.strip():
            return (
                "Das eingestellte Sprachmodell kann keine Bilder verarbeiten, und "
                "es ließ sich auch kein Text aus dem Bild auslesen. Für die "
                "Texterkennung fehlt möglicherweise Tesseract – siehe "
                "requirements-vision.txt."
            )

        response = await self._providers.complete(
            f"{prompt}\n\nDas ist der Text, der auf dem Bildschirm steht:\n\n"
            f"{text_result.text[:6000]}",
            system_prompt="Du beantwortest Fragen zu Bildschirminhalten sachlich und knapp.",
        )
        return self._as_text(response)

    @staticmethod
    def _as_text(response: Any) -> str:
        if isinstance(response, str):
            return response
        for attribute in ("text", "content", "answer"):
            value = getattr(response, attribute, None)
            if isinstance(value, str):
                return value
        if isinstance(response, dict):
            for key in ("text", "content", "answer"):
                value = response.get(key)
                if isinstance(value, str):
                    return value
        return str(response)

    @staticmethod
    def _discard(capture: Capture) -> None:
        """Löscht eine Aufnahme sofort."""

        if capture.path is None:
            return
        try:
            capture.path.unlink()
        except OSError:
            pass

    # --- Auskunft --------------------------------------------------------------------------

    def discard_all(self) -> int:
        """Löscht alle gespeicherten Aufnahmen."""

        return self._capture.discard_all()

    def status(self) -> dict[str, Any]:
        """Statusangaben für die Transparenzansicht."""

        return {
            "enabled": self._enabled,
            "allow_image_to_model": self._allow_image_to_model,
            "keep_after_analysis": self._keep_after_analysis,
            "capture": self._capture.status(),
            "ocr": self._ocr.status(),
        }
