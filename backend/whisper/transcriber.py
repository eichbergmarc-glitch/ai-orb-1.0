"""Spracherkennung mit Whisper.

Wandelt aufgezeichnete Sprachabschnitte in Text um. Verwendet wird
``faster-whisper``, eine deutlich schnellere Umsetzung von Whisper, die auf
einer gewöhnlichen CPU in brauchbarer Geschwindigkeit läuft.

Das Modell wird erst beim ersten Gebrauch geladen, nicht beim Start – so
verzögert es den Start von AI-Orb nicht. Der Ladevorgang und die eigentliche
Erkennung laufen in einem Worker-Thread, damit die Event-Loop und damit die
Oberfläche nie blockieren.

Ist ``faster-whisper`` nicht installiert, meldet das Modul das ausdrücklich
mit einer Anleitung, statt stillschweigend nichts zu tun.
"""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.system.logging_setup import get_logger

logger = get_logger(__name__)

#: Modellgrößen mit ungefährem Speicherbedarf des Downloads.
MODEL_SIZES: dict[str, str] = {
    "tiny": "etwa 75 MB – sehr schnell, für Deutsch ungenau",
    "base": "etwa 145 MB – schnell, für kurze Befehle brauchbar",
    "small": "etwa 490 MB – guter Kompromiss, für Deutsch empfohlen",
    "medium": "etwa 1,5 GB – genau, spürbar langsamer",
    "large-v3": "etwa 3 GB – am genauesten, nur mit starker Hardware sinnvoll",
}


#: Die Groessen von gross nach klein – fuer die Rueckfallkette.
_REIHENFOLGE = ("large-v3", "large-v2", "large", "medium", "small", "base", "tiny")


def _ist_kleiner(kandidat: str, als: str) -> bool:
    """Ob ein Modell kleiner ist als ein anderes.

    Unbekannte Namen gelten als nicht kleiner: Lieber keinen Rueckfall
    anbieten als versehentlich ein groesseres Modell nachzuladen, wenn das
    kleinere schon nicht ging.
    """

    try:
        return _REIHENFOLGE.index(kandidat) > _REIHENFOLGE.index(als)
    except ValueError:
        return False


@dataclass
class Transcript:
    """Das Ergebnis einer Spracherkennung."""

    text: str = ""
    language: str = ""
    duration_seconds: float = 0.0
    processing_seconds: float = 0.0
    #: Mittlere Verlässlichkeit der erkannten Abschnitte (0.0 bis 1.0).
    confidence: float = 0.0
    segments: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        """Ob überhaupt etwas erkannt wurde."""

        return not self.text.strip()

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "language": self.language,
            "duration_seconds": round(self.duration_seconds, 2),
            "processing_seconds": round(self.processing_seconds, 2),
            "confidence": round(self.confidence, 3),
        }


class Transcriber:
    """Wandelt Audioaufnahmen in Text um."""

    def __init__(
        self,
        *,
        model_size: str = "small",
        language: str = "de",
        device: str = "auto",
        compute_type: str = "int8",
        cpu_threads: int = 0,
        beam_size: int = 1,
        models_directory: Path | None = None,
        anfangshinweis: str = "",
    ) -> None:
        """
        Args:
            model_size: Eine der Größen aus :data:`MODEL_SIZES`.
            language: Sprachkürzel, ``de`` für Deutsch. ``auto`` erkennt die
                Sprache selbst, ist aber langsamer und bei kurzen Befehlen
                fehleranfällig.
            device: ``cpu``, ``cuda`` oder ``auto``.
            compute_type: Rechengenauigkeit; ``int8`` ist auf der CPU am
                schnellsten.
            beam_size: Höhere Werte sind genauer, aber langsamer.
            models_directory: Wohin das Modell heruntergeladen wird.
            anfangshinweis: Text, auf den Whisper seine Ausgabe bedingt –
                als wäre er das, was unmittelbar davor gesagt wurde. Damit
                lassen sich Fachbegriffe, Eigennamen und das Weckwort
                verankern, ohne dass sie je ausgegeben werden.
        """

        self._model_size = model_size
        self._language = language
        self._device = device
        #: Rechenkerne fuer die Erkennung. 0 heisst: selbst bestimmen.
        #:
        #: faster-whisper nimmt ohne Angabe genau VIER Threads, gleichgueltig
        #: wie viele Kerne der Rechner hat. Die Messung vom 16.08.2026 zeigt
        #: die Erkennung bei 5,2 Sekunden im Median - auf der CPU fast reine
        #: Rechenzeit. Ein Kern bleibt frei: Sprachausgabe und Animation
        #: laufen gleichzeitig, und eine voll belegte CPU laesst den Orb
        #: ruckeln.
        gewuenscht = int(cpu_threads or 0)
        if gewuenscht <= 0:
            import os as _os
            gewuenscht = max(4, (_os.cpu_count() or 4) - 1)
        self._cpu_threads = gewuenscht
        self._compute_type = compute_type
        self._beam_size = max(1, beam_size)
        self._models_directory = models_directory
        self._anfangshinweis = anfangshinweis.strip()

        self._model: Any | None = None
        self._load_lock = threading.Lock()
        self._load_failed = False
        #: Es erkennt immer nur EINE Aufnahme zugleich.
        #:
        #: Ohne diese Sperre laufen mehrere Erkennungen gleichzeitig auf
        #: demselben Modell und nehmen sich gegenseitig die Rechenkerne weg -
        #: jede einzelne wird dadurch langsamer, und unter Last wird aus
        #: Sekunden eine Schlange. Am 17.08.2026 stand sie bei 194 Sekunden.
        self._reihen_sperre = threading.Lock()

    # --- Verfügbarkeit ---------------------------------------------------------

    @staticmethod
    def is_available() -> bool:
        """Ob ``faster-whisper`` installiert ist."""

        try:
            import faster_whisper  # noqa: F401
        except ImportError:
            return False
        return True

    @staticmethod
    def installation_hint() -> str:
        """Anleitung, falls die Spracherkennung fehlt."""

        return (
            "Für die Spracheingabe fehlt das Paket 'faster-whisper'. "
            "Installiere es mit:\n"
            "    .venv\\Scripts\\python.exe -m pip install -r requirements-voice.txt"
        )

    @property
    def is_loaded(self) -> bool:
        """Ob das Modell bereits im Speicher liegt."""

        return self._model is not None

    @property
    def load_failed(self) -> bool:
        """Ob das Laden endgültig fehlgeschlagen ist.

        Wer eine zweite Erkennung als Ausweichlösung bereithält, kann daran
        erkennen, dass diese hier nichts mehr liefern wird – statt bei jeder
        Anfrage aufs Neue ein leeres Ergebnis zu bekommen.
        """

        return self._load_failed

    @property
    def model_size(self) -> str:
        """Die eingestellte Modellgröße."""

        return self._model_size

    # --- Modell laden ------------------------------------------------------------

    def _load_model(self) -> Any | None:
        """Lädt das Modell (blockierend, daher nur im Worker-Thread aufrufen)."""

        if self._model is not None:
            return self._model
        if self._load_failed:
            return None

        with self._load_lock:
            if self._model is not None:
                return self._model

            try:
                from faster_whisper import WhisperModel
            except ImportError:
                logger.error(self.installation_hint())
                self._load_failed = True
                return None

            logger.info(
                "Whisper-Modell '%s' wird geladen (%s). Beim ersten Mal wird es "
                "heruntergeladen, das kann einige Minuten dauern.",
                self._model_size,
                MODEL_SIZES.get(self._model_size, "unbekannte Größe"),
            )
            started = time.perf_counter()

            # Eine Kette statt eines einzelnen Versuchs.
            #
            # Ein groesseres Modell versteht deutlich besser - und es kann
            # fehlschlagen: Der Download bricht ab, der Arbeitsspeicher
            # reicht nicht, der Rechner hat kein passendes Rechenwerk. Ohne
            # Rueckfall waere die Folge nicht "etwas schlechter", sondern
            # "gar keine Spracherkennung mehr", und der Orb waere taub.
            #
            # Deshalb wird nach unten ausgewichen. Wer das grosse Modell
            # will und es nicht bekommt, hoert es im Protokoll und behaelt
            # trotzdem einen brauchbaren Orb.
            kette = [self._model_size]
            for kleiner in ("medium", "small", "base"):
                if kleiner not in kette and _ist_kleiner(kleiner, self._model_size):
                    kette.append(kleiner)

            letzter: Exception | None = None
            for groesse in kette:
                try:
                    self._model = WhisperModel(
                        groesse,
                        device=self._device,
                        compute_type=self._compute_type,
                        cpu_threads=self._cpu_threads,
                        download_root=(
                            str(self._models_directory) if self._models_directory else None
                        ),
                    )
                except Exception as fehler:  # noqa: BLE001
                    letzter = fehler
                    logger.warning(
                        "Das Whisper-Modell '%s' liess sich nicht laden (%s).",
                        groesse,
                        fehler,
                    )
                    continue

                if groesse != self._model_size:
                    logger.warning(
                        "Es laeuft ersatzweise '%s' statt '%s'. Die Erkennung "
                        "ist damit schlechter - fuer die volle Genauigkeit "
                        "muss '%s' geladen werden koennen.",
                        groesse,
                        self._model_size,
                        self._model_size,
                    )
                    self._model_size = groesse
                break

            if self._model is None:
                logger.error(
                    "Kein Whisper-Modell liess sich laden. Zuletzt: %s", letzter
                )
                self._load_failed = True
                return None

            logger.info(
                "Whisper-Modell bereit (%.1f s).", time.perf_counter() - started
            )
            return self._model

    async def preload(self) -> bool:
        """Lädt das Modell im Voraus.

        Sinnvoll direkt nach dem Start: Dann ist die erste Spracheingabe
        genauso schnell wie alle folgenden.

        Returns:
            ``True``, wenn das Modell bereit ist.
        """

        model = await asyncio.to_thread(self._load_model)
        return model is not None

    # --- Erkennung ----------------------------------------------------------------

    async def transcribe(
        self, audio_path: Path, *, verfallen_nach: float | None = None
    ) -> Transcript:
        """Wandelt eine Audiodatei in Text um.

        Args:
            audio_path: Pfad zu einer WAV-Datei (16 kHz, mono).
            verfallen_nach: Nach so vielen Sekunden Wartezeit wird die
                Aufnahme verworfen statt erkannt. Das ist der Riegel gegen
                die Schlange vom 17.08.2026: Während der Orb eine lange
                Antwort sprach, hörte das Mikrofon ihn selbst mit, jede
                dieser Aufnahmen stellte sich zur Erkennung an, und als der
                Benutzer dann wirklich sprach, wartete sein Satz drei
                Minuten - "Kannst du mich jetzt verstehen?" wurde um 13:48
                klar erkannt und kam trotzdem nie an. Eine Aufnahme, die
                Minuten alt ist, ist keine Anweisung mehr; sie zu erkennen
                verzögert nur die, die es noch ist.

        Returns:
            Das Erkennungsergebnis. Bei einem Fehler oder einer verfallenen
            Aufnahme ist der Text leer.
        """

        abgegeben = time.monotonic()
        return await asyncio.to_thread(
            self._transcribe_blocking, audio_path, abgegeben, verfallen_nach
        )

    def _transcribe_blocking(
        self,
        audio_path: Path,
        abgegeben: float | None = None,
        verfallen_nach: float | None = None,
    ) -> Transcript:
        with self._reihen_sperre:
            return self._transcribe_geordnet(audio_path, abgegeben, verfallen_nach)

    def _transcribe_geordnet(
        self,
        audio_path: Path,
        abgegeben: float | None = None,
        verfallen_nach: float | None = None,
    ) -> Transcript:
        # ERST die Frische pruefen, DANN rechnen. Die Wartezeit entsteht in
        # der Schlange vor der Sperre - genau hier ist der Moment, in dem
        # eine veraltete Aufnahme noch nichts gekostet hat.
        if (
            verfallen_nach is not None
            and abgegeben is not None
            and time.monotonic() - abgegeben > verfallen_nach
        ):
            logger.info(
                "Aufnahme verworfen: Sie wartete %.0f s auf die Erkennung "
                "(Grenze %.0f s) und ist damit keine Anweisung mehr.",
                time.monotonic() - abgegeben,
                verfallen_nach,
            )
            return Transcript()

        model = self._load_model()
        if model is None:
            return Transcript()

        started = time.perf_counter()
        try:
            segments, info = model.transcribe(
                str(audio_path),
                language=None if self._language == "auto" else self._language,
                beam_size=self._beam_size,
                # Der Anfangshinweis.
                #
                # Whisper bedingt seine Ausgabe darauf, als waere es der
                # Text unmittelbar davor. Das ist der billigste Hebel, den
                # es hier gibt: Ohne ihn raet das Modell Fachbegriffe,
                # Eigennamen und das Weckwort nach dem, was im Deutschen
                # allgemein haeufig ist - und "Hallo Orb" wird zu "Hallo
                # Robert", "Historiografie" zu "Historio Grafie".
                #
                # Er kostet nichts an Rechenzeit und wird nie mit
                # ausgegeben.
                initial_prompt=self._anfangshinweis or None,
                # Die Sprachaktivität wurde bereits vor der Aufnahme
                # geprüft; eine zweite Filterung würde nur Zeit kosten.
                vad_filter=False,
                condition_on_previous_text=False,
            )

            texts: list[str] = []
            probabilities: list[float] = []
            for segment in segments:
                text = str(getattr(segment, "text", "")).strip()
                if text:
                    texts.append(text)
                probability = getattr(segment, "avg_logprob", None)
                if probability is not None:
                    # Log-Wahrscheinlichkeit grob in eine Spanne von 0 bis 1
                    # überführen, damit sie mit anderen Maßen vergleichbar ist.
                    probabilities.append(max(0.0, min(1.0, 1.0 + float(probability) / 5.0)))

        except Exception:  # noqa: BLE001
            logger.exception("Die Spracherkennung ist fehlgeschlagen.")
            return Transcript()

        confidence = sum(probabilities) / len(probabilities) if probabilities else 0.0

        # Die Aufteilung ins Protokoll - Warten und Rechnen getrennt.
        #
        # Gemessen am 19.08.2026: 5,8 Sekunden vom Ende des Satzes bis zum
        # Text, der groesste einzelne Posten auf dem Weg zur Antwort. Nur
        # war nicht zu sehen, WOVON: Stand die Aufnahme in der Schlange vor
        # dem Modell, oder rechnete das Modell so lange? Das sind zwei
        # verschiedene Fehler mit zwei verschiedenen Abhilfen - ein
        # zweites Modell gegen das eine, ein kleineres gegen das andere.
        # Ohne diese Zeile waere jede Abhilfe geraten.
        rechenzeit = time.perf_counter() - started
        wartezeit = (time.monotonic() - abgegeben) - rechenzeit if abgegeben else 0.0
        logger.info(
            "Erkannt in %.1f s (%.1f s gewartet, %.1f s gerechnet, "
            "%.1f s Aufnahme, Modell '%s').",
            wartezeit + rechenzeit,
            max(0.0, wartezeit),
            rechenzeit,
            float(getattr(info, "duration", 0.0)),
            self._model_size,
        )

        return Transcript(
            text=" ".join(texts).strip(),
            language=str(getattr(info, "language", self._language)),
            duration_seconds=float(getattr(info, "duration", 0.0)),
            processing_seconds=time.perf_counter() - started,
            confidence=confidence,
            segments=texts,
        )

    def status(self) -> dict[str, Any]:
        """Statusangaben für die Transparenzansicht."""

        return {
            "available": self.is_available(),
            "loaded": self.is_loaded,
            "model_size": self._model_size,
            "model_info": MODEL_SIZES.get(self._model_size, ""),
            "language": self._language,
            "device": self._device,
        }
