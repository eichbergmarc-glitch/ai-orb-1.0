"""Die Webcam: ein Standbild aufnehmen und von einem Sprachmodell ansehen lassen.

Seit 07.11.2026. Marc wollte, dass Synapse ueber die Webcam sieht, was
passiert, und ihn erkennt.

Aufgenommen wird **nur auf ausdruecklichen Wunsch** (das Werkzeug
``kamera_ansehen``), nie im Hintergrund. Das Bild verlaesst den Rechner, um
ausgewertet zu werden, und wird nicht aufbewahrt - mit einer Ausnahme: das
Referenzbild, das ``gesicht_merken`` anlegt, damit Synapse Marc wiedererkennt.

Zwei Wege zur Kamera, ohne neue Pakete:

1. **PyAV** (``av``) liegt ohnehin in der Laufzeit (faster-whisper braucht es)
   und spricht unter Windows DirectShow. Dafuer braucht es den Namen der
   Kamera, z. B. "Logi C270 HD WebCam".
2. **OpenCV** (``cv2``), falls es installiert ist - dann genuegt die Nummer 0.
"""

from __future__ import annotations

import asyncio
import base64
import io
import time
from pathlib import Path
from typing import Any

from backend.system.logging_setup import get_logger
from backend.utils.paths import get_user_dir

logger = get_logger(__name__)


class KameraFehler(RuntimeError):
    """Die Kamera liess sich nicht oeffnen oder lieferte kein Bild."""


def referenz_pfad() -> Path:
    ordner = get_user_dir() / "data" / "kamera"
    ordner.mkdir(parents=True, exist_ok=True)
    return ordner / "referenz.jpg"


def _jpeg(bild: Any, *, breite: int = 960) -> bytes:
    """PIL-Bild verkleinern und als JPEG liefern."""

    if bild.width > breite:
        hoehe = int(bild.height * breite / bild.width)
        bild = bild.resize((breite, hoehe))
    puffer = io.BytesIO()
    bild.convert("RGB").save(puffer, format="JPEG", quality=85)
    return puffer.getvalue()


def _aufnahme_pyav(geraet: str, aufwaermen: int) -> bytes:
    import av  # type: ignore

    container = av.open(
        f"video={geraet}",
        format="dshow",
        options={"rtbufsize": "64M"},
    )
    try:
        stream = container.streams.video[0]
        letzter = None
        for index, frame in enumerate(container.decode(stream)):
            letzter = frame
            # Die ersten Bilder sind oft dunkel, waehrend die Kamera die
            # Belichtung einstellt.
            if index >= aufwaermen:
                break
        if letzter is None:
            raise KameraFehler("Die Kamera lieferte kein Bild.")
        return _jpeg(letzter.to_image())
    finally:
        container.close()


def _aufnahme_opencv(index: int, aufwaermen: int) -> bytes:
    import cv2  # type: ignore
    from PIL import Image

    kamera = cv2.VideoCapture(index, getattr(cv2, "CAP_DSHOW", 0))
    try:
        if not kamera.isOpened():
            raise KameraFehler(f"Kamera {index} liess sich nicht oeffnen.")
        bild = None
        for _ in range(max(1, aufwaermen)):
            ok, bild = kamera.read()
            if not ok:
                bild = None
        if bild is None:
            raise KameraFehler("Die Kamera lieferte kein Bild.")
        return _jpeg(Image.fromarray(cv2.cvtColor(bild, cv2.COLOR_BGR2RGB)))
    finally:
        kamera.release()


def aufnehmen_blocking(einstellungen: dict[str, Any]) -> bytes:
    """Nimmt ein Standbild auf und gibt es als JPEG zurueck."""

    geraet = str(einstellungen.get("geraet", "") or "").strip()
    aufwaermen = int(einstellungen.get("aufwaermen_bilder", 15) or 15)
    fehler: list[str] = []

    if geraet:
        try:
            return _aufnahme_pyav(geraet, aufwaermen)
        except ImportError:
            fehler.append("PyAV fehlt")
        except Exception as error:  # noqa: BLE001
            fehler.append(f"DirectShow '{geraet}': {error}")

    try:
        return _aufnahme_opencv(int(einstellungen.get("index", 0) or 0), aufwaermen)
    except ImportError:
        fehler.append("OpenCV fehlt")
    except Exception as error:  # noqa: BLE001
        fehler.append(f"OpenCV: {error}")

    raise KameraFehler("; ".join(fehler) or "Keine Kamera gefunden.")


class Kamera:
    """Standbild aufnehmen und an ein bildfaehiges Sprachmodell geben."""

    def __init__(self, *, provider_manager: Any, einstellungen: dict[str, Any] | None = None) -> None:
        self._providers = provider_manager
        self._einstellungen = dict(einstellungen or {})

    async def aufnehmen(self) -> bytes:
        return await asyncio.to_thread(aufnehmen_blocking, self._einstellungen)

    async def referenz_speichern(self) -> Path:
        daten = await self.aufnehmen()
        ziel = referenz_pfad()
        ziel.write_bytes(daten)
        logger.info("Referenzbild fuer die Wiedererkennung gespeichert: %s", ziel)
        return ziel

    async def ansehen(self, frage: str) -> str:
        started = time.perf_counter()
        daten = await self.aufnehmen()
        bilder: list[dict[str, str]] = []
        referenz = referenz_pfad()
        name = str(self._einstellungen.get("name", "Marc") or "Marc")
        hinweis = ""
        if referenz.is_file():
            bilder.append({
                "media_type": "image/jpeg",
                "data": base64.b64encode(referenz.read_bytes()).decode("ascii"),
            })
            hinweis = (
                f"Bild 1 zeigt {name} (Referenzfoto). Bild 2 ist das aktuelle "
                f"Kamerabild. Sag, ob {name} auf Bild 2 zu sehen ist - nur wenn "
                "du dir anhand des Gesichts wirklich sicher bist; sonst sag, dass "
                "du es nicht sicher erkennst. "
            )
        else:
            hinweis = "Das ist das aktuelle Bild der Webcam. "
        bilder.append({"media_type": "image/jpeg", "data": base64.b64encode(daten).decode("ascii")})

        antwort = await self._providers.complete(
            hinweis + (frage.strip() or "Beschreibe kurz, was zu sehen ist."),
            system_prompt=(
                "Du siehst durch die Webcam des Benutzers. Beschreibe knapp und "
                "sachlich, was wirklich zu sehen ist, auf Deutsch, in ein bis drei "
                "Saetzen. Erfinde nichts."
            ),
            images=bilder,
        )
        logger.info("Kamerabild ausgewertet (%.1f s).", time.perf_counter() - started)
        return str(antwort or "").strip()
