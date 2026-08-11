"""Bildverstehen von AI-Orb (v2 Phase 17).

Erlaubt es, den Bildschirm aufzunehmen, den Text darauf lokal auszulesen
und bei Bedarf ein Sprachmodell zu fragen, was zu sehen ist.

Die Reihenfolge ist Absicht: Erst lokal lesen, dann erst übertragen. Wer
nur wissen will, was in einer Fehlermeldung steht, soll dafür kein Bild
seines Bildschirms aus der Hand geben müssen.
"""

from backend.vision.screen_capture import Capture, ScreenCapture, ScreenRegion
from backend.vision.text_recognition import TextRecognition, TextResult
from backend.vision.vision_engine import VisionEngine, VisionResult

__all__ = [
    "Capture",
    "ScreenCapture",
    "ScreenRegion",
    "TextRecognition",
    "TextResult",
    "VisionEngine",
    "VisionResult",
]
