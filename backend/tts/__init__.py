"""Sprachausgabe von AI-Orb (v2 Phase 13).

Wandelt Text in hörbare Sprache. Die Verfahren werden
in der in ``config.yaml`` eingetragenen Reihenfolge versucht:

* :class:`~backend.tts.supertonic_engine.SupertonicEngine` – klare,
  schnelle 44,1-kHz-Neuralstimme, vollständig lokal. Voreinstellung.
* :class:`~backend.tts.piper_engine.PiperEngine` – neuronal, auf Deutsch
  trainiert, läuft lokal. Schnelle Rückfallebene.
* :class:`~backend.tts.sapi_engine.SapiEngine` – die Windows-Sprachausgabe.
  Immer vorhanden, verlangt keine Installation. Die Rückfallebene.
* :class:`~backend.tts.kokoro_engine.KokoroEngine` – neuronal und sehr
  natürlich, beherrscht aber kein Deutsch.

Die Gefühlslage der Stimme steuert :mod:`backend.tts.emotion`.
"""

from backend.tts.base_engine import SpeechRequest, SpeechResult, TtsEngine
from backend.tts.emotion import EMOTIONS, EmotionProfile, detect, for_state, get_emotion
from backend.tts.kokoro_engine import KokoroEngine
from backend.tts.openvoice_clone_engine import OpenVoiceCloneEngine
from backend.tts.piper_engine import PiperEngine
from backend.tts.pocket_tts_engine import PocketTtsEngine
from backend.tts.chatterbox_engine import ChatterboxEngine
from backend.tts.sapi_engine import SapiEngine
from backend.tts.supertonic_engine import SupertonicEngine
from backend.tts.tts_manager import ENGINE_CLASSES, TtsManager

__all__ = [
    "EMOTIONS",
    "ENGINE_CLASSES",
    "EmotionProfile",
    "KokoroEngine",
    "OpenVoiceCloneEngine",
    "PiperEngine",
    "PocketTtsEngine",
    "SapiEngine",
    "SpeechRequest",
    "SpeechResult",
    "SupertonicEngine",
    "TtsEngine",
    "TtsManager",
    "detect",
    "for_state",
    "get_emotion",
]
