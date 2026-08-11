"""Sprachsteuerung von AI-Orb (v2 Phasen 9, 10, 13 und 23).

Dieses Paket verbindet die Einzelteile zu einem Gespräch:

* :mod:`backend.audio` – Mikrofon, Sprachaktivitätserkennung, Wiedergabe
* :mod:`backend.whisper` – Spracherkennung und Weckwort
* :mod:`backend.tts` – Sprachausgabe und Gefühlslage

Der Einstiegspunkt ist :class:`~backend.voice.voice_pipeline.VoicePipeline`.
"""

from backend.voice.voice_pipeline import VoicePipeline, VoiceState, VoiceTurn

__all__ = ["VoicePipeline", "VoiceState", "VoiceTurn"]
