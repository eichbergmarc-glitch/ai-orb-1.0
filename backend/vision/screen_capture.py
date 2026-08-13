"""Bildschirmaufnahme.

Nimmt den Bildschirm oder einen Ausschnitt davon auf. Zwei Vorgaben aus der
Spezifikation prägen dieses Modul mehr als alles Technische:

*„Keine Screenshots werden automatisch hochgeladen."* Eine Aufnahme
entsteht hier nur auf ausdrücklichen Auftrag, sie bleibt auf der Festplatte,
und sie wird nur dann an ein Sprachmodell gegeben, wenn der Benutzer dem in
demselben Vorgang zugestimmt hat.

*„Alle Daten lokal speichern."* Aufnahmen liegen unter ``data/vision/`` und
werden nach kurzer Zeit selbsttätig gelöscht. Es gibt keinen Weg, sie
dauerhaft anzusammeln.

Zusätzlich schwärzt das Modul auf Wunsch Bereiche, bevor das Bild irgendwo
hingeht – etwa den Bereich, in dem ein Passwortfeld steht.

Die Aufnahme braucht das Paket ``mss``. Fehlt es, meldet das Modul das mit
einer Anleitung, statt ein leeres Bild zu liefern.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.system.logging_setup import get_logger
from backend.utils.paths import get_data_dir

logger = get_logger(__name__)


@dataclass
class ScreenRegion:
    """Ein rechteckiger Ausschnitt des Bildschirms."""

    left: int
    top: int
    width: int
    height: int

    def to_dict(self) -> dict[str, int]:
        return {"left": self.left, "top": self.top, "width": self.width, "height": self.height}

    @property
    def is_valid(self) -> bool:
        return self.width > 0 and self.height > 0


@dataclass
class Capture:
    """Eine erstellte Aufnahme."""

    path: Path | None = None
    width: int = 0
    height: int = 0
    monitor: int = 0
    region: ScreenRegion | None = None
    seconds: float = 0.0
    error: str = ""
    redactions: list[ScreenRegion] = field(default_factory=list)

    @property
    def succeeded(self) -> bool:
        return self.path is not None and self.path.exists()

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path) if self.path else "",
            "width": self.width,
            "height": self.height,
            "monitor": self.monitor,
            "region": self.region.to_dict() if self.region else None,
            "seconds": round(self.seconds, 3),
            "error": self.error,
            "redactions": [item.to_dict() for item in self.redactions],
        }


class ScreenCapture:
    """Nimmt den Bildschirm auf."""

    def __init__(self, *, max_edge: int = 1600, keep_minutes: float = 10.0) -> None:
        """
        Args:
            max_edge: Längste Kante des gespeicherten Bildes. Größere
                Aufnahmen werden verkleinert – ein Sprachmodell braucht
                keine vier Millionen Bildpunkte, und kleinere Bilder gehen
                schneller und kosten weniger.
            keep_minutes: Nach wie vielen Minuten eine Aufnahme gelöscht wird.
        """

        self._directory = get_data_dir() / "vision"
        self._directory.mkdir(parents=True, exist_ok=True)
        self._max_edge = max(320, max_edge)
        self._keep_seconds = max(60.0, keep_minutes * 60.0)
        self._count = 0

    # --- Verfügbarkeit -------------------------------------------------------------

    @staticmethod
    def is_available() -> bool:
        """Ob aufgenommen werden kann.

        Es genügt ``mss``. Pillow war früher ebenfalls Bedingung – und weil
        es beim Bauen nie mitinstalliert wurde, konnte AI-Orb überhaupt
        kein Bildschirmfoto machen, obwohl das Aufnehmen selbst gar kein
        Pillow braucht. ``mss`` schreibt PNG selbst. Pillow wird nur noch
        für das Verkleinern und das Schwärzen von Bereichen benutzt; fehlt
        es, entfällt beides, und das Bild wird in voller Größe gespeichert.
        """

        try:
            import mss  # noqa: F401
        except (ImportError, OSError):
            return False
        return True

    @staticmethod
    def has_pillow() -> bool:
        """Ob Pillow da ist – für Verkleinern und Schwärzen."""

        try:
            from PIL import Image  # noqa: F401
        except (ImportError, OSError):
            return False
        return True

    @staticmethod
    def installation_hint() -> str:
        """Anleitung, falls die Aufnahme nicht möglich ist."""

        return (
            "Für die Bildschirmaufnahme fehlt das Paket 'mss'. Der Orb kann "
            "es sich selbst nachrüsten – benutze dafür das Werkzeug "
            "'pakete_nachruesten' mit 'mss Pillow'."
        )

    def monitors(self) -> list[dict[str, Any]]:
        """Listet die vorhandenen Bildschirme auf."""

        try:
            import mss
        except (ImportError, OSError):
            return []

        try:
            with mss.MSS() as sct:
                # Der erste Eintrag ist die Gesamtfläche aller Bildschirme.
                return [
                    {
                        "index": index,
                        "left": monitor["left"],
                        "top": monitor["top"],
                        "width": monitor["width"],
                        "height": monitor["height"],
                        "combined": index == 0,
                    }
                    for index, monitor in enumerate(sct.monitors)
                ]
        except Exception:  # noqa: BLE001
            logger.exception("Die Bildschirmliste ließ sich nicht lesen.")
            return []

    # --- Aufnahme ----------------------------------------------------------------------

    def capture_blocking(
        self,
        *,
        monitor: int = 1,
        region: ScreenRegion | None = None,
        redactions: list[ScreenRegion] | None = None,
    ) -> Capture:
        """Nimmt auf. Blockierend – im Worker-Thread aufzurufen.

        Args:
            monitor: Welcher Bildschirm. 0 nimmt alle zusammen.
            region: Ausschnitt; ``None`` nimmt den ganzen Bildschirm.
            redactions: Bereiche, die vor dem Speichern geschwärzt werden.

        Returns:
            Die Aufnahme oder eine Fehlerbeschreibung.
        """

        started = time.perf_counter()

        try:
            import mss
        except (ImportError, OSError):
            return Capture(error=self.installation_hint())

        mit_pillow = self.has_pillow()

        try:
            with mss.MSS() as sct:
                available = len(sct.monitors)
                if monitor < 0 or monitor >= available:
                    return Capture(
                        error=f"Bildschirm {monitor} gibt es nicht. Vorhanden sind 0 bis {available - 1}."
                    )

                area: dict[str, int] = dict(sct.monitors[monitor])
                if region is not None and region.is_valid:
                    area = {
                        "left": area["left"] + region.left,
                        "top": area["top"] + region.top,
                        "width": region.width,
                        "height": region.height,
                    }

                raw = sct.grab(area)
                if mit_pillow:
                    from PIL import Image

                    image = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
                else:
                    image = None

        except Exception as error:  # noqa: BLE001
            logger.exception("Die Bildschirmaufnahme ist fehlgeschlagen.")
            return Capture(error=f"Die Aufnahme ist fehlgeschlagen: {error}")

        applied = redactions or []
        path = self._directory / f"screen-{int(time.time() * 1000)}.png"

        if image is None:
            # Ohne Pillow: mss schreibt das PNG selbst. Schwärzen und
            # Verkleinern entfallen dann – lieber ein volles Bild als gar
            # keines. Wer Bereiche schwärzen will, braucht Pillow.
            if applied:
                logger.warning(
                    "Ohne Pillow lassen sich keine Bereiche schwärzen. "
                    "Rüste es mit dem Werkzeug 'pakete_nachruesten' nach."
                )
            try:
                import mss.tools

                mss.tools.to_png(raw.rgb, raw.size, output=str(path))
            except Exception as error:  # noqa: BLE001
                return Capture(error=f"Die Aufnahme ließ sich nicht speichern: {error}")

            breite, hoehe = raw.size
            self._count += 1
            self.cleanup()
            return Capture(
                path=path,
                width=breite,
                height=hoehe,
                monitor=monitor,
                region=region,
                seconds=time.perf_counter() - started,
                redactions=[],
            )

        if applied:
            image = self._redact(image, applied)

        image = self._downscale(image)

        try:
            image.save(path, format="PNG", optimize=True)
        except OSError as error:
            return Capture(error=f"Die Aufnahme ließ sich nicht speichern: {error}")

        self._count += 1
        self.cleanup()

        return Capture(
            path=path,
            width=image.width,
            height=image.height,
            monitor=monitor,
            region=region,
            seconds=time.perf_counter() - started,
            redactions=list(applied),
        )

    @staticmethod
    def _redact(image: Any, regions: list[ScreenRegion]) -> Any:
        """Schwärzt Bereiche im Bild."""

        from PIL import ImageDraw

        drawing = ImageDraw.Draw(image)
        for region in regions:
            if not region.is_valid:
                continue
            drawing.rectangle(
                [region.left, region.top, region.left + region.width, region.top + region.height],
                fill=(0, 0, 0),
            )
        return image

    def _downscale(self, image: Any) -> Any:
        """Verkleinert das Bild, wenn es zu groß ist."""

        from PIL import Image

        longest = max(image.width, image.height)
        if longest <= self._max_edge:
            return image

        factor = self._max_edge / float(longest)
        return image.resize(
            (max(1, int(image.width * factor)), max(1, int(image.height * factor))),
            Image.LANCZOS,
        )

    # --- Pflege ------------------------------------------------------------------------

    def cleanup(self) -> int:
        """Löscht abgelaufene Aufnahmen.

        Returns:
            Wie viele gelöscht wurden.
        """

        cutoff = time.time() - self._keep_seconds
        removed = 0
        for path in self._directory.glob("screen-*.png"):
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
                    removed += 1
            except OSError:
                continue
        return removed

    def discard_all(self) -> int:
        """Löscht alle Aufnahmen sofort."""

        removed = 0
        for path in self._directory.glob("screen-*.png"):
            try:
                path.unlink()
                removed += 1
            except OSError:
                continue
        return removed

    def status(self) -> dict[str, Any]:
        """Statusangaben für die Transparenzansicht."""

        stored = list(self._directory.glob("screen-*.png"))
        return {
            "available": self.is_available(),
            "directory": str(self._directory),
            "captures_taken": self._count,
            "captures_stored": len(stored),
            "keep_minutes": round(self._keep_seconds / 60.0, 1),
            "max_edge": self._max_edge,
            "monitors": len(self.monitors()),
        }
