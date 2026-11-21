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
import socket
import time
import urllib.error
import urllib.parse
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
        #: Wie lange eine Erreichbarkeitsantwort gilt, bevor neu geklopft wird.
        self._probe_gueltig = float(self.option("probe_cache_seconds", 60.0))
        #: Wie kurz das Klopfen selbst sein darf.
        self._probe_frist = float(self.option("connect_timeout", 1.5))
        self._probe_zeit = 0.0
        self._probe_ergebnis: bool | None = None

    @property
    def token(self) -> str:
        return os.environ.get(self._token_env, "").strip()

    # --- Verfügbarkeit ---------------------------------------------------------

    def is_available(self) -> bool:
        """Verfügbar, wenn eine Adresse eingetragen ist UND jemand antwortet.

        Der zweite Teil ist neu, und er ist der Unterschied zwischen
        „fällt zurück" und „fällt nach dreissig Sekunden zurück". Vorher
        genügte ein Eintrag in der Konfiguration: Ein eingeschlafener
        Colab-Server galt als verfügbar, jeder Satz lief in sein Zeitlimit,
        und der Orb schwieg jedes Mal aufs Neue, bevor die lokale Stimme
        übernahm.

        Geklopft wird kurz (anderthalb Sekunden) und höchstens einmal je
        Minute - eine Erreichbarkeitsprüfung, die selbst zur Wartezeit
        wird, hätte nichts gewonnen.
        """

        if not self._endpoint:
            return False

        jetzt = time.monotonic()
        if (
            self._probe_ergebnis is not None
            and (jetzt - self._probe_zeit) < self._probe_gueltig
        ):
            return self._probe_ergebnis

        self._probe_zeit = jetzt
        self._probe_ergebnis = self._klopfen()
        if not self._probe_ergebnis:
            logger.info(
                "Der TTS-Server unter %s antwortet nicht; es spricht die "
                "lokale Stimme.",
                self._endpoint,
            )
        return self._probe_ergebnis

    def _klopfen(self) -> bool:
        """Ein kurzer Verbindungsversuch zur Serveradresse."""

        adresse = urllib.parse.urlparse(self._endpoint)
        host = adresse.hostname
        if not host:
            # Eine Adresse, die sich nicht lesen laesst, wird beim Sprechen
            # ohnehin scheitern - dann aber mit einer klaren Meldung.
            return True
        port = adresse.port or (443 if adresse.scheme == "https" else 80)
        try:
            with socket.create_connection((host, port), timeout=self._probe_frist):
                return True
        except OSError:
            return False

    def vermerke_fehlschlag(self) -> None:
        """Merkt sich einen gescheiterten Sprechversuch.

        Damit gilt der Server sofort als nicht erreichbar und nicht erst
        nach Ablauf der Probefrist.
        """

        self._probe_zeit = time.monotonic()
        self._probe_ergebnis = False

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
                "emotion": request.emotion,
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
            # Gleich vermerken: Der naechste Satz soll nicht noch einmal
            # das volle Zeitlimit kosten.
            self.vermerke_fehlschlag()
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
