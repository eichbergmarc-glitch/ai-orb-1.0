"""Texterkennung auf Bildern (OCR).

Liest Text aus einem Bild – die Fehlermeldung in einem Dialogfenster, die
Tabelle in einem PDF-Ausdruck, die Beschriftung einer Schaltfläche.

Der springende Punkt ist, dass dies **lokal** geschieht. Wer nur wissen
will, was in einer Meldung steht, muss dafür kein Bild seines Bildschirms
aus der Hand geben. Deshalb bekommt die Texterkennung im Ablauf der Vision
Engine den Vorrang: Erst lokal auslesen, und nur wenn das nicht reicht, nach
einer Übertragung fragen.

Benutzt wird Tesseract über ``pytesseract``. Tesseract selbst ist ein
eigenständiges Programm und muss getrennt installiert werden; das Modul
sagt das im Klartext, statt einen unverständlichen Fehler durchzureichen.
"""

from __future__ import annotations

import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.system.logging_setup import get_logger

logger = get_logger(__name__)


@dataclass
class TextResult:
    """Der auf einem Bild gefundene Text."""

    text: str = ""
    #: Mittlere Verlässlichkeit der Erkennung (0.0 bis 1.0).
    confidence: float = 0.0
    #: Anzahl erkannter Wörter.
    word_count: int = 0
    seconds: float = 0.0
    error: str = ""
    lines: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "confidence": round(self.confidence, 3),
            "word_count": self.word_count,
            "seconds": round(self.seconds, 3),
            "error": self.error,
        }


class TextRecognition:
    """Liest Text aus Bildern."""

    def __init__(self, *, languages: str = "deu+eng", minimum_confidence: float = 0.3) -> None:
        """
        Args:
            languages: Sprachen für Tesseract, etwa ``deu+eng``. Für jede
                genannte Sprache muss das zugehörige Sprachpaket installiert
                sein.
            minimum_confidence: Wörter unterhalb dieser Verlässlichkeit
                werden verworfen. Das entfernt die typischen Zeichenwolken,
                die aus Bildbereichen ohne Text entstehen.
        """

        self._languages = languages
        self._minimum_confidence = minimum_confidence

    # --- Verfügbarkeit ------------------------------------------------------------

    @staticmethod
    def is_available() -> bool:
        """Ob Paket und Programm vorhanden sind."""

        try:
            import pytesseract  # noqa: F401
            from PIL import Image  # noqa: F401
        except (ImportError, OSError):
            return False

        return TextRecognition._find_tesseract() is not None

    @staticmethod
    def _find_tesseract() -> str | None:
        """Sucht das Tesseract-Programm.

        Unter Windows landet es meist in den Programmen und nicht im PATH;
        die üblichen Orte werden deshalb mitgeprüft.
        """

        found = shutil.which("tesseract")
        if found:
            return found

        candidates = [
            Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
            Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
        ]
        for candidate in candidates:
            if candidate.is_file():
                return str(candidate)
        return None

    @staticmethod
    def installation_hint() -> str:
        """Anleitung, falls die Texterkennung fehlt."""

        try:
            import pytesseract  # noqa: F401

            has_package = True
        except (ImportError, OSError):
            has_package = False

        if not has_package:
            return (
                "Für die Texterkennung fehlt das Paket 'pytesseract'. "
                "Installiere es mit:\n"
                "    .venv\\Scripts\\python.exe -m pip install -r requirements-vision.txt"
            )

        return (
            "Das Paket ist da, aber das Programm Tesseract fehlt. Es ist ein "
            "eigenständiges Programm und muss getrennt installiert werden:\n"
            "    winget install UB-Mannheim.TesseractOCR\n"
            "Achte darauf, bei der Installation die deutschen Sprachdaten "
            "mitauszuwählen."
        )

    # --- Erkennung ---------------------------------------------------------------------

    def read_blocking(self, image_path: Path | None) -> TextResult:
        """Liest den Text eines Bildes. Blockierend.

        Args:
            image_path: Pfad zum Bild.

        Returns:
            Der gefundene Text mit Verlässlichkeitsangabe.
        """

        if image_path is None or not image_path.exists():
            return TextResult(error="Es gibt kein Bild zum Auslesen.")

        started = time.perf_counter()

        try:
            import pytesseract
            from PIL import Image
        except (ImportError, OSError):
            return TextResult(error=self.installation_hint())

        executable = self._find_tesseract()
        if executable is None:
            return TextResult(error=self.installation_hint())
        pytesseract.pytesseract.tesseract_cmd = executable

        try:
            with Image.open(image_path) as image:
                data = pytesseract.image_to_data(
                    image,
                    lang=self._languages,
                    output_type=pytesseract.Output.DICT,
                )
        except Exception as error:  # noqa: BLE001
            message = str(error)
            if "language" in message.lower() or "tessdata" in message.lower():
                return TextResult(
                    error=(
                        f"Tesseract fehlen die Sprachdaten für '{self._languages}'. "
                        "Installiere sie nach oder stelle 'vision.ocr_languages' in "
                        "config.yaml auf 'eng' um."
                    )
                )
            logger.exception("Die Texterkennung ist fehlgeschlagen.")
            return TextResult(error=f"Die Texterkennung ist fehlgeschlagen: {error}")

        return self._assemble(data, time.perf_counter() - started)

    def _assemble(self, data: dict[str, Any], seconds: float) -> TextResult:
        """Setzt aus den Einzelwörtern wieder Zeilen zusammen.

        Tesseract liefert Wort für Wort mit Zeilennummer. Daraus Zeilen zu
        bauen ist etwas Arbeit, aber ohne sie käme ein Wortsalat heraus, in
        dem eine Fehlermeldung nicht mehr zu erkennen wäre.
        """

        words = data.get("text", [])
        confidences = data.get("conf", [])
        line_numbers = data.get("line_num", [])
        block_numbers = data.get("block_num", [])

        lines: dict[tuple[int, int], list[str]] = {}
        scores: list[float] = []

        for index, word in enumerate(words):
            text = str(word).strip()
            if not text:
                continue

            try:
                confidence = float(confidences[index]) / 100.0
            except (IndexError, TypeError, ValueError):
                confidence = 0.0

            if confidence < self._minimum_confidence:
                continue

            key = (
                int(block_numbers[index]) if index < len(block_numbers) else 0,
                int(line_numbers[index]) if index < len(line_numbers) else 0,
            )
            lines.setdefault(key, []).append(text)
            scores.append(confidence)

        assembled = [" ".join(parts) for _, parts in sorted(lines.items())]
        text = "\n".join(assembled).strip()

        return TextResult(
            text=text,
            confidence=sum(scores) / len(scores) if scores else 0.0,
            word_count=len(scores),
            seconds=seconds,
            lines=assembled,
        )

    def status(self) -> dict[str, Any]:
        """Statusangaben für die Transparenzansicht."""

        executable = self._find_tesseract()
        return {
            "available": self.is_available(),
            "languages": self._languages,
            "tesseract": executable or "",
            "hint": "" if self.is_available() else self.installation_hint(),
        }
