"""Sprachausgabe über ElevenLabs (die authentische Stimme).

Die lokalen Stimmen (Piper, SAPI) sind brauchbar, aber hörbar synthetisch –
und die natürlichste unter ihnen, Piper in der ``high``-Fassung, ist
zugleich die langsamste. Wer eine Stimme will, die wie ein Mensch klingt
*und* schnell da ist, kommt an einem Cloud-Dienst nicht vorbei. ElevenLabs
ist der beste seiner Art; die Stimme „Miles“ stammt von dort.

## Der Preis der Natürlichkeit

Diese Engine schickt den zu sprechenden Text an einen fremden Server. Das
steht gegen das „alles bleibt lokal“ der übrigen Anlage und muss deshalb
eine ausdrückliche Wahl bleiben, keine Voreinstellung: Sie greift nur,
wenn ``elevenlabs`` in ``voice.output.engines`` steht und ein Schlüssel
hinterlegt ist. Ohne Schlüssel meldet sie sich als nicht verfügbar, und
AI-Orb spricht weiter über Piper – der Rückfall funktioniert wie bei jeder
anderen Engine.

## Warum trotz Cloud die stdlib genügt

ElevenLabs ist eine gewöhnliche REST-API. Ein POST mit dem Text, zurück
kommt Audio. Dafür braucht es keine Bibliothek, nur ``urllib`` – dieselbe
Beschränkung wie im ganzen Projekt.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
import wave
from pathlib import Path
from typing import Any

from backend.system.logging_setup import get_logger
from backend.tts.base_engine import SpeechRequest, SpeechResult, TtsEngine

logger = get_logger(__name__)

_API_BASE = "https://api.elevenlabs.io/v1"

#: Rohes PCM statt MP3.
#:
#: Der Player von AI-Orb spielt WAV, nicht MP3 – und eine MP3-Umwandlung
#: bräuchte ffmpeg, eine weitere Abhängigkeit. ElevenLabs liefert auf Wunsch
#: rohes PCM; das lässt sich mit der stdlib in wenige Zeilen WAV-Header
#: verpacken, und die Kette bleibt schlank. 22050 Hz genügt für Sprache.
_OUTPUT_FORMAT = "pcm_22050"
_SAMPLE_RATE = 22050

#: Eine Standardstimme, falls sich die Stimmenliste nicht abrufen lässt.
#:
#: Der Grund für diesen Rückfall: ElevenLabs-Schlüssel können eingeschränkte
#: Rechte haben. Ein Schlüssel, der nur Sprache erzeugen darf, wird beim
#: Abrufen der Stimmenliste abgewiesen – und AI-Orb gab dann auf, obwohl
#: das Sprechen selbst funktioniert hätte. Diese Kennung gehört zu einer
#: der mitgelieferten Stimmen, die jedes Konto benutzen darf.
_FALLBACK_VOICE_ID = "pNInz6obpgDQGcFmaJgB"


class ElevenLabsEngine(TtsEngine):
    """Erzeugt Sprache über die ElevenLabs-API.

    Der Schlüssel kommt aus der Umgebung (``ELEVENLABS_API_KEY``), niemals
    aus der Konfiguration. Stimme (``voice_id``) und Modell stehen in
    ``config.yaml`` und sind frei wählbar – die konkrete Stimme ist kein
    Fall für den Quellcode.
    """

    name = "elevenlabs"

    def __init__(self, *, output_directory: Path, options: dict[str, Any] | None = None) -> None:
        super().__init__(output_directory=output_directory, options=options)
        self._api_key_env = str(self.option("api_key_env", "ELEVENLABS_API_KEY"))
        self._voice_id = str(self.option("voice_id", "")).strip()

        # ``eleven_turbo_v2_5`` als Vorgabe – die preiswerte Wahl.
        #
        # ElevenLabs rechnet nach Zeichen ab, und die Modelle kosten
        # unterschiedlich viel: ``eleven_multilingual_v2`` schlägt mit dem
        # vollen Satz zu Buche, ``turbo_v2_5`` mit dem halben. Turbo
        # beherrscht Deutsch, klingt sehr nah am großen Modell und
        # antwortet dabei schneller – bei einer Stimme, die Satz für Satz
        # erzeugt wird, ist das doppelt willkommen. Wer die letzte Nuance
        # will, trägt ``eleven_multilingual_v2`` ein und zahlt das Doppelte.
        self._model = str(self.option("model", "eleven_turbo_v2_5"))

        #: Merker für die selbst gewählte Stimme, damit die Liste nur
        #: einmal je Sitzung abgefragt wird.
        self._resolved_voice = ""

    @property
    def api_key(self) -> str:
        return os.environ.get(self._api_key_env, "").strip()

    # --- Verfügbarkeit ---------------------------------------------------------

    def is_available(self) -> bool:
        """Verfügbar nur mit Schlüssel und gewählter Stimme.

        Beides fehlt im Auslieferungszustand – die Engine ist also von
        sich aus still, bis der Benutzer sie einrichtet. Das ist gewollt:
        Eine Cloud-Stimme darf sich nicht ungefragt einschalten.
        """

        # Der Schlüssel genügt. Eine Stimme sucht sich die Engine selbst,
        # wenn keine eingetragen ist – siehe resolve_voice(). Vorher war
        # eine fehlende voice_id ein Ausschlussgrund; damit blieb die
        # Stimme stumm, obwohl alles Nötige vorlag und die Auswahl mit
        # einer einzigen Abfrage zu klären ist.
        return bool(self.api_key)

    def installation_hint(self) -> str:
        if not self.api_key:
            return (
                "ElevenLabs ist nicht eingerichtet. Trage ELEVENLABS_API_KEY in "
                "die .env ein. Wie, steht in docs/STIMME.md."
            )
        return "ElevenLabs: keine Stimme verfügbar."

    # --- Stimmenwahl -----------------------------------------------------------

    def resolve_voice(self) -> str:
        """Bestimmt die zu verwendende Stimme.

        Drei Stufen, von der genauesten zur verlässlichsten:

        1. Die ``voice_id`` aus der Konfiguration, falls eingetragen.
        2. Die erste Stimme des Kontos, per Abfrage ermittelt.
        3. Eine mitgelieferte Standardstimme.

        Die dritte Stufe ist der wichtige Zusatz: Ein Schlüssel mit
        eingeschränkten Rechten darf oft sprechen, aber die Stimmenliste
        nicht lesen. Ohne Rückfall verstummte ElevenLabs dann vollständig –
        wegen einer Abfrage, die für das Sprechen gar nicht nötig ist.
        """

        if self._voice_id:
            return self._voice_id
        if self._resolved_voice:
            return self._resolved_voice

        http_request = urllib.request.Request(
            f"{_API_BASE}/voices", headers={"xi-api-key": self.api_key}
        )
        try:
            with urllib.request.urlopen(http_request, timeout=20) as response:
                voices = json.loads(response.read()).get("voices", [])
        except urllib.error.HTTPError as error:
            logger.warning(
                "ElevenLabs: Stimmenliste nicht lesbar (%s). Das ist kein "
                "Hindernis – der Schlüssel darf vermutlich nur sprechen. "
                "Es wird die Standardstimme benutzt. Eine andere trägst du "
                "unter voice.output.elevenlabs.voice_id ein.",
                error.code,
            )
            self._resolved_voice = _FALLBACK_VOICE_ID
            return self._resolved_voice
        except Exception as error:  # noqa: BLE001
            logger.warning(
                "ElevenLabs: Stimmenliste nicht abrufbar (%s). Es wird die "
                "Standardstimme benutzt.",
                error,
            )
            self._resolved_voice = _FALLBACK_VOICE_ID
            return self._resolved_voice

        if not voices:
            logger.warning(
                "ElevenLabs: Das Konto führt keine eigenen Stimmen. Es wird "
                "die Standardstimme benutzt."
            )
            self._resolved_voice = _FALLBACK_VOICE_ID
            return self._resolved_voice

        chosen = voices[0]
        self._resolved_voice = str(chosen.get("voice_id", "")) or _FALLBACK_VOICE_ID
        logger.info(
            "ElevenLabs: Stimme '%s' gewählt (%s). Eine andere trägst du unter "
            "voice.output.elevenlabs.voice_id ein; verfügbar sind: %s",
            chosen.get("name", "?"),
            self._resolved_voice,
            ", ".join(str(v.get("name", "?")) for v in voices[:12]),
        )
        return self._resolved_voice

    # --- Erzeugung -------------------------------------------------------------

    def synthesize_blocking(self, request: SpeechRequest, target: Path) -> SpeechResult:
        """Erzeugt die Sprachdatei über die API."""

        if not self.is_available():
            return SpeechResult(engine=self.name, error=self.installation_hint())

        voice_id = self.resolve_voice()
        if not voice_id:
            return SpeechResult(
                engine=self.name,
                error=(
                    "ElevenLabs: keine Stimme ermittelbar. Prüfe den Schlüssel "
                    "in der .env und ob dem Konto Stimmen zugeordnet sind."
                ),
            )

        payload = json.dumps(
            {
                "text": request.text,
                "model_id": self._model,
                "voice_settings": {
                    # Aus der Sprechgeschwindigkeit/Betonung des Requests
                    # abgeleitet. „stability“ niedriger = lebendiger,
                    # „similarity_boost“ hoch = näher an der Vorlagenstimme.
                    "stability": 0.4,
                    "similarity_boost": 0.85,
                    "style": min(1.0, max(0.0, request.pitch)),
                },
            }
        ).encode("utf-8")

        url = f"{_API_BASE}/text-to-speech/{voice_id}?output_format={_OUTPUT_FORMAT}"
        http_request = urllib.request.Request(
            url,
            data=payload,
            headers={
                "xi-api-key": self.api_key,
                "Content-Type": "application/json",
                "Accept": "audio/mpeg",
            },
            method="POST",
        )

        started = self._now()
        try:
            with urllib.request.urlopen(http_request, timeout=30) as response:
                pcm = response.read()
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")[:300]
            # Die beiden häufigsten Fälle im Klartext benennen. Sonst
            # klingt jeder davon nach „irgendetwas mit der Stimme kaputt",
            # dabei ist der eine ein falscher Schlüssel und der andere ein
            # leeres Guthaben – zwei ganz verschiedene Dinge.
            if error.code in (401, 403):
                hinweis = (
                    "Der Schlüssel wurde abgelehnt. Prüfe ELEVENLABS_API_KEY "
                    "in der .env – möglicherweise ist er abgelaufen oder wurde "
                    "zurückgezogen."
                )
            elif error.code == 429:
                hinweis = (
                    "Das Zeichenguthaben ist aufgebraucht oder das Limit "
                    "erreicht. Bis zur Verlängerung spricht AI-Orb wieder "
                    "mit der lokalen Thorsten-Stimme."
                )
            else:
                hinweis = ""
            logger.warning("ElevenLabs %s: %s", error.code, hinweis or detail)
            return SpeechResult(
                engine=self.name,
                error=(
                    f"ElevenLabs antwortete mit {error.code}: {hinweis or detail}"
                ),
            )
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            return SpeechResult(engine=self.name, error=f"ElevenLabs nicht erreichbar: {error}")

        if not pcm:
            return SpeechResult(engine=self.name, error="ElevenLabs lieferte keine Audiodaten.")

        # Rohes PCM in einen WAV-Rahmen legen: 16 Bit, ein Kanal.
        try:
            with wave.open(str(target), "wb") as handle:
                handle.setnchannels(1)
                handle.setsampwidth(2)
                handle.setframerate(_SAMPLE_RATE)
                handle.writeframes(pcm)
        except OSError as error:
            return SpeechResult(engine=self.name, error=f"Datei nicht speicherbar: {error}")

        return SpeechResult(
            audio_path=target,
            engine=self.name,
            duration_seconds=len(pcm) / (2 * _SAMPLE_RATE),
            processing_seconds=self._now() - started,
            context={"model": self._model, "voice_id": voice_id},
        )

    def voices(self) -> list[dict[str, str]]:
        gewaehlt = self._voice_id or self._resolved_voice
        return [{"engine": self.name, "voice": gewaehlt or "(wird beim ersten Sprechen gewählt)"}]
