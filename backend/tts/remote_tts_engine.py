"""Sprachausgabe über einen eigenen entfernten TTS-Server (z. B. CSM-1B).

Manche Stimmen sind zu schwer für den eigenen Rechner. CSM-1B von Sesame –
die Stimme hinter „Miles“ – ist so eine: Sie klingt wunderbar natürlich,
braucht aber eine Grafikkarte, um flüssig zu laufen. Auf einem gewöhnlichen
Notebook ist sie unbrauchbar langsam.

Die Lösung ist eine Arbeitsteilung: Das Modell läuft dort, wo eine GPU ist –
auf einem gemieteten GPU-Server oder in einem Colab-Notebook –, und AI-Orb
schickt ihm nur den Text und bekommt fertige Sprache zurück. Dieses Modul
ist die Orb-Seite dieser Teilung: ein schlanker Client, der zu jedem Server
spricht, der Text entgegennimmt und eine WAV-Datei zurückgibt.

## Warum das flüssig sein kann

Drei Dinge greifen ineinander:

* AI-Orb schickt **Satz für Satz**, nicht die ganze Antwort. Jede Anfrage
  ist kurz, also schnell erzeugt.
* Während ein Satz abgespielt wird, ist der nächste schon unterwegs zum
  Server (siehe die Vorbereitung in der Sprechpipeline). Die Wartezeit
  verschwindet hinter dem Sprechen.
* Der Server hält das Modell geladen und antwortet in Sekundenbruchteilen.

Auf einer GPU ist das flüssig. Ohne GPU – etwa auf der Gegenstelle eines
überlasteten Gratis-Colab – kann es haken; dann fällt AI-Orb auf die lokale
Stimme zurück, wie bei jeder anderen Engine auch.

## Was der Server liefern muss

Ein POST mit ``{"text": ...}`` beantwortet er mit den rohen Bytes einer
WAV-Datei (``Content-Type: audio/wav``). Mehr ist nicht nötig; die
Abtastrate ist gleichgültig, der Player von AI-Orb kommt mit jeder zurecht.
Ein Beispielserver liegt unter ``server/csm_tts_server.py`` bei.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from backend.system.logging_setup import get_logger
from backend.tts.base_engine import SpeechRequest, SpeechResult, TtsEngine

logger = get_logger(__name__)


class RemoteTtsEngine(TtsEngine):
    """Ruft einen selbst betriebenen TTS-Server auf und spielt dessen WAV ab."""

    name = "remote"

    def __init__(self, *, output_directory: Path, options: dict[str, Any] | None = None) -> None:
        super().__init__(output_directory=output_directory, options=options)
        # Die Adresse steht in der Konfiguration – sie ist kein Geheimnis,
        # sondern der Ort deines Servers (etwa eine Colab-Tunnel-URL).
        self._endpoint = str(self.option("endpoint", "")).strip().rstrip("/")
        # Ein optionaler Zugangstoken schützt den Server davor, dass Fremde
        # ihn benutzen. Er kommt – falls gesetzt – aus der Umgebung.
        self._token_env = str(self.option("token_env", "REMOTE_TTS_TOKEN"))
        self._speaker = int(self.option("speaker", 0))
        self._timeout = float(self.option("timeout", 30.0))

    @property
    def token(self) -> str:
        return os.environ.get(self._token_env, "").strip()

    # --- Verfügbarkeit ---------------------------------------------------------

    def is_available(self) -> bool:
        """Verfügbar, sobald eine Serveradresse eingetragen ist.

        Ob der Server tatsächlich antwortet, zeigt sich erst beim Sprechen –
        eine ständige Erreichbarkeitsprüfung würde jeden Start verzögern.
        Fällt der Server aus, greift der Rückfall auf die lokale Stimme.
        """

        return bool(self._endpoint)

    def installation_hint(self) -> str:
        return (
            "Kein TTS-Server eingetragen. Starte den Server aus "
            "server/csm_tts_server.py (Anleitung in docs/STIMME_CSM.md) und "
            "trage seine Adresse unter voice.output.remote.endpoint in "
            "config.yaml ein."
        )

    # --- Erzeugung -------------------------------------------------------------

    def synthesize_blocking(self, request: SpeechRequest, target: Path) -> SpeechResult:
        """Schickt den Text an den Server und speichert die Antwort als WAV."""

        if not self._endpoint:
            return SpeechResult(engine=self.name, error=self.installation_hint())

        payload = json.dumps(
            {
                "text": request.text,
                "speaker": self._speaker,
                # Der Server darf diese Hinweise nutzen oder ignorieren.
                "speed": request.speed,
            }
        ).encode("utf-8")

        headers = {"Content-Type": "application/json", "Accept": "audio/wav"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        http_request = urllib.request.Request(
            f"{self._endpoint}/tts", data=payload, headers=headers, method="POST"
        )

        started = self._now()
        try:
            with urllib.request.urlopen(http_request, timeout=self._timeout) as response:
                audio = response.read()
                content_type = response.headers.get("Content-Type", "")
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")[:300]
            return SpeechResult(engine=self.name, error=f"TTS-Server meldete {error.code}: {detail}")
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            # Der häufigste Fall bei einem Colab-Server: eingeschlafen oder
            # getrennt. Bewusst als Debug, nicht als Fehler – der Rückfall
            # auf Piper besorgt den Rest.
            logger.debug("TTS-Server nicht erreichbar (%s): %s", self._endpoint, error)
            return SpeechResult(engine=self.name, error=f"TTS-Server nicht erreichbar: {error}")

        if not audio:
            return SpeechResult(engine=self.name, error="Der TTS-Server lieferte keine Audiodaten.")

        # Eine JSON-Fehlermeldung statt Audio erkennen, damit sie nicht als
        # kaputte WAV auf der Platte landet.
        if "application/json" in content_type or audio[:1] == b"{":
            message = audio.decode("utf-8", errors="replace")[:300]
            return SpeechResult(engine=self.name, error=f"TTS-Server: {message}")

        try:
            target.write_bytes(audio)
        except OSError as error:
            return SpeechResult(engine=self.name, error=f"Datei nicht speicherbar: {error}")

        return SpeechResult(
            audio_path=target,
            engine=self.name,
            processing_seconds=self._now() - started,
            context={"endpoint": self._endpoint, "speaker": self._speaker},
        )

    def voices(self) -> list[dict[str, str]]:
        return [{"engine": self.name, "voice": f"Server {self._endpoint or '(nicht gesetzt)'}"}]
