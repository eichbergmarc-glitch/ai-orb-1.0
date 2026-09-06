"""Wiedergabe von Sprachdateien.

Spielt die von der Sprachausgabe erzeugten WAV-Dateien ab. Drei
Eigenschaften sind dabei wesentlich, und alle drei betreffen den
Gesprächsfluss, nicht die Tonqualität.

**Unterbrechbarkeit.** Wer dem Assistenten ins Wort fällt, will nicht warten,
bis er ausgeredet hat. :meth:`AudioPlayer.stop` bricht deshalb sofort ab –
nicht am Ende des Satzes, sondern am Ende des nächsten Audioblocks, also
nach wenigen Millisekunden.

**Rückmeldung an den Orb.** Während der Wiedergabe soll der Orb sichtbar
sprechen. Der Pegel jedes Blocks wird deshalb gemeldet, sodass die
Darstellung mitschwingen kann.

**Kein Selbstgespräch.** Solange der Orb spricht, darf das Mikrofon nicht
mithören, sonst reagiert er auf die eigene Stimme. Das Stummschalten regelt
die Ebene darüber; hier wird nur zuverlässig gemeldet, wann Anfang und Ende
sind.

Ohne das Paket ``sounddevice`` weicht das Modul unter Windows auf ``winsound``
aus. Das kann weniger, ist aber immer da – und ein Assistent, der erst nach
einer Paketinstallation hörbar wird, hilft niemandem.
"""

from __future__ import annotations

import array
import math
import platform
import threading
import wave
from pathlib import Path
from typing import Any, Callable

from backend.audio.vad import rms
from backend.system.logging_setup import get_logger

logger = get_logger(__name__)

#: Wie viele Bilder pro Sekunde der Pegel gemeldet wird.
LEVEL_UPDATES_PER_SECOND = 30


class AudioPlayer:
    """Spielt WAV-Dateien ab und meldet den Fortschritt."""

    def __init__(
        self,
        *,
        device: int | str | None = None,
        normalize_volume: bool = True,
        target_rms: float = 0.10,
        trim_boundary_silence: bool = True,
        leading_silence_ms: float = 30.0,
        trailing_silence_ms: float = 70.0,
        on_level: Callable[[float], None] | None = None,
        on_started: Callable[[Path], None] | None = None,
        on_finished: Callable[[Path, bool], None] | None = None,
    ) -> None:
        """
        Args:
            device: Ausgabegerät; ``None`` nutzt den Standardlautsprecher.
            on_level: Wird während der Wiedergabe mit dem Pegel (0.0 bis 1.0)
                aufgerufen, damit der Orb mitschwingen kann.
            on_started: Wird beim Beginn einer Wiedergabe aufgerufen.
            on_finished: Wird am Ende aufgerufen; der zweite Wert sagt, ob
                vollständig abgespielt wurde (``False`` bei Abbruch).
        """

        self._device = device
        self._normalize_volume = bool(normalize_volume)
        self._target_rms = max(0.06, min(0.18, float(target_rms)))
        self._trim_boundary_silence = bool(trim_boundary_silence)
        self._leading_silence_ms = max(0.0, min(120.0, float(leading_silence_ms)))
        self._trailing_silence_ms = max(20.0, min(180.0, float(trailing_silence_ms)))
        self._on_level = on_level
        self._on_started = on_started
        self._on_finished = on_finished

        self._stop_requested = threading.Event()
        self._playing = threading.Event()
        self._lock = threading.Lock()
        self._current: Path | None = None

    # --- Verfügbarkeit -------------------------------------------------------------

    @staticmethod
    def is_available() -> bool:
        """Ob überhaupt abgespielt werden kann."""

        try:
            import sounddevice  # noqa: F401

            return True
        except (ImportError, OSError):
            pass
        return platform.system() == "Windows"

    @staticmethod
    def uses_fallback() -> bool:
        """Ob die einfache Windows-Wiedergabe benutzt wird."""

        try:
            import sounddevice  # noqa: F401

            return False
        except (ImportError, OSError):
            return platform.system() == "Windows"

    @staticmethod
    def installation_hint() -> str:
        """Anleitung, falls nichts abgespielt werden kann."""

        return (
            "Für die Sprachwiedergabe fehlt das Paket 'sounddevice'. "
            "Installiere es mit:\n"
            "    .venv\\Scripts\\python.exe -m pip install -r requirements-voice.txt"
        )

    @property
    def is_playing(self) -> bool:
        """Ob gerade etwas abgespielt wird."""

        return self._playing.is_set()

    @property
    def current_file(self) -> Path | None:
        """Welche Datei gerade läuft."""

        return self._current

    # --- Steuerung ---------------------------------------------------------------------

    def stop(self) -> None:
        """Bricht die laufende Wiedergabe ab."""

        if self._playing.is_set():
            self._stop_requested.set()
            logger.debug("Wiedergabe wird abgebrochen.")

    def play_blocking(self, path: Path) -> bool:
        """Spielt eine Datei ab und wartet, bis sie zu Ende ist.

        Blockierend – von der Ebene darüber in einem Worker-Thread
        aufzurufen.

        Args:
            path: Die abzuspielende WAV-Datei.

        Returns:
            ``True``, wenn vollständig abgespielt wurde.
        """

        if not path.exists():
            logger.error("Die Sprachdatei fehlt: %s", path)
            return False

        # Nur eine Wiedergabe gleichzeitig. Zwei übereinander wären nicht
        # nur unschön, sie würden auch das Stummschalten des Mikrofons
        # durcheinanderbringen.
        with self._lock:
            self._stop_requested.clear()
            self._playing.set()
            self._current = path

            if self._on_started is not None:
                self._safely(lambda: self._on_started(path))  # type: ignore[misc]

            try:
                completed = self._play(path)
            except Exception:  # noqa: BLE001 - Wiedergabefehler dürfen nichts abbrechen.
                logger.exception("Die Wiedergabe ist fehlgeschlagen.")
                completed = False
            finally:
                self._playing.clear()
                self._current = None
                if self._on_level is not None:
                    self._safely(lambda: self._on_level(0.0))  # type: ignore[misc]
                if self._on_finished is not None:
                    self._safely(lambda: self._on_finished(path, completed))  # type: ignore[misc]

            return completed

    def play_result_blocking(self, result: Any) -> bool:
        """Spielt ein TTS-Ergebnis, bei Pocket TTS schon waehrend der Erzeugung."""

        stream = getattr(result, "context", {}).get("pcm_stream")
        if stream is None:
            path = getattr(result, "audio_path", None)
            return bool(path) and self.play_blocking(path)

        path = getattr(result, "audio_path", None) or Path("pocket-tts-stream.wav")
        with self._lock:
            self._stop_requested.clear()
            self._playing.set()
            self._current = path
            if self._on_started is not None:
                self._safely(lambda: self._on_started(path))  # type: ignore[misc]

            try:
                completed = self._play_pcm_stream(
                    stream,
                    path,
                    on_buffered=getattr(result, "context", {}).get(
                        "on_stream_buffered"
                    ),
                )
            except Exception:  # noqa: BLE001
                logger.exception("Die Streaming-Wiedergabe ist fehlgeschlagen.")
                completed = False
            finally:
                self._playing.clear()
                self._current = None
                if self._on_level is not None:
                    self._safely(lambda: self._on_level(0.0))  # type: ignore[misc]
                if self._on_finished is not None:
                    self._safely(lambda: self._on_finished(path, completed))  # type: ignore[misc]
            return completed

    def _play_pcm_stream(
        self,
        stream: Any,
        final_path: Path,
        *,
        on_buffered: Callable[[], None] | None = None,
    ) -> bool:
        """Spielt PCM16-Bloecke ohne auf die fertige WAV-Datei zu warten."""

        try:
            import sounddevice as sd
        except (ImportError, OSError):
            # winsound kennt keine PCM-Streams. In dieser seltenen Reserve
            # wird auf die parallel entstehende WAV gewartet.
            if not stream.wait_until_done(timeout=120.0) or not final_path.exists():
                return False
            return self._play_with_winsound(final_path)

        try:
            output = sd.RawOutputStream(
                samplerate=int(stream.sample_rate),
                channels=int(stream.channels),
                dtype="int16",
                device=self._device,
                blocksize=0,
            )
        except Exception:  # noqa: BLE001
            logger.exception("Der Lautsprecher konnte fuer Streaming nicht geoeffnet werden.")
            stream.cancel()
            return False

        buffered_reported = False
        with output:
            for frames in stream.iter_chunks():
                if self._stop_requested.is_set():
                    stream.cancel()
                    return False
                if stream.done and not buffered_reported and on_buffered is not None:
                    self._safely(on_buffered)
                    buffered_reported = True
                if not frames:
                    continue
                if self._on_level is not None:
                    samples = array.array("h")
                    samples.frombytes(frames[: len(frames) // 2 * 2])
                    level = min(1.0, math.sqrt(sum(v * v for v in samples) / max(1, len(samples))) / 32768.0)
                    self._safely(lambda value=level: self._on_level(value))
                output.write(frames)
        return not self._stop_requested.is_set() and not bool(stream.error)

    # --- Wiedergabewege ------------------------------------------------------------------

    def _play(self, path: Path) -> bool:
        try:
            import sounddevice  # noqa: F401
        except (ImportError, OSError):
            return self._play_with_winsound(path)
        return self._play_with_sounddevice(path)

    def _play_with_sounddevice(self, path: Path) -> bool:
        """Spielt blockweise ab, damit der Abbruch sofort greift."""

        import sounddevice as sd

        gain = self._normalization_gain(path)
        start_frame, end_frame = self._playback_bounds(path)

        with wave.open(str(path), "rb") as handle:
            channels = handle.getnchannels()
            width = handle.getsampwidth()
            rate = handle.getframerate()

            if width != 2:
                logger.warning(
                    "Die Sprachdatei hat %d Byte je Wert; erwartet werden 2. "
                    "Es wird die einfache Wiedergabe benutzt.",
                    width,
                )
                return self._play_with_winsound(path)

            block_frames = max(256, int(rate / LEVEL_UPDATES_PER_SECOND))
            if start_frame:
                handle.setpos(min(start_frame, handle.getnframes()))
            remaining_frames = max(0, min(end_frame, handle.getnframes()) - start_frame)

            try:
                stream = sd.RawOutputStream(
                    samplerate=rate,
                    channels=channels,
                    dtype="int16",
                    device=self._device,
                    blocksize=block_frames,
                )
            except Exception:  # noqa: BLE001
                logger.exception(
                    "Der Lautsprecher konnte nicht geöffnet werden. Ist ein "
                    "Wiedergabegerät angeschlossen?"
                )
                return False

            with stream:
                while True:
                    if self._stop_requested.is_set():
                        return False

                    if remaining_frames <= 0:
                        break
                    frames_to_read = min(block_frames, remaining_frames)
                    frames = handle.readframes(frames_to_read)
                    if not frames:
                        break
                    remaining_frames -= frames_to_read

                    samples = array.array("h")
                    samples.frombytes(frames[: len(frames) // 2 * 2])
                    if gain != 1.0:
                        samples = array.array(
                            "h",
                            (
                                max(-32768, min(32767, round(value * gain)))
                                for value in samples
                            ),
                        )
                        frames = samples.tobytes()

                    if self._on_level is not None:
                        level = rms(samples)
                        self._safely(lambda value=level: self._on_level(value))  # type: ignore[misc]

                    stream.write(frames)

        return not self._stop_requested.is_set()

    def _normalization_gain(self, path: Path) -> float:
        """Gleicht Pegelunterschiede zwischen getrennt erzeugten Sätzen aus.

        Neuronale TTS-Dienste liefern selbst bei derselben Stimme je Satz
        einen etwas anderen RMS-Pegel. Eine behutsam begrenzte Verstärkung
        sorgt dafür, dass eine Antwort nicht hörbar lauter und leiser wird.
        """

        if not self._normalize_volume:
            return 1.0
        try:
            with wave.open(str(path), "rb") as handle:
                if handle.getsampwidth() != 2:
                    return 1.0
                sample_rate = handle.getframerate()
                channels = handle.getnchannels()
                raw = handle.readframes(handle.getnframes())
        except (OSError, wave.Error):
            return 1.0

        samples = array.array("h")
        samples.frombytes(raw[: len(raw) // 2 * 2])
        if not samples:
            return 1.0

        # Nicht die Stille zwischen zwei Saetzen vermessen. ElevenLabs und
        # lokale Stimmen lassen je nach Text unterschiedlich lange Atem- und
        # Satzpausen in der WAV-Datei. Der alte Gesamt-RMS hielt eine Datei
        # mit mehr Stille fuer leiser und hob sie dadurch unnoetig an. In den
        # realen Orb-Dateien ergab das trotz Normalisierung eine Spanne von
        # mehr als 9:1. Vermessen werden deshalb nur aktive 20-ms-Rahmen.
        measured = self._active_speech_rms(
            samples,
            sample_rate=sample_rate,
            channels=channels,
        )
        if measured < 0.004:
            return 1.0

        peak = max(abs(value) for value in samples) / 32768.0
        desired = self._target_rms / measured
        # Ein einziger fester Faktor pro Datei erhaelt die natuerliche Dynamik
        # innerhalb des Satzes. Leise Cloud-Ausgaben muessen aber deutlich
        # staerker als die bisher erlaubten 1,55 angehoben werden duerfen.
        # Die echte Spitze setzt stets die haertere Grenze und verhindert
        # Clipping.
        peak_limit = 0.96 / max(peak, 0.01)
        return max(0.55, min(6.0, desired, peak_limit))

    def _playback_bounds(self, path: Path) -> tuple[int, int]:
        """Begrenzt nur ueberfluessige Stille am Anfang und Ende einer WAV.

        Cloud-TTS liefert je Satz eigene Dateien. In 80 realen ElevenLabs-
        Dateien lagen am Uebergang im Median rund 430 ms Randstille; zusammen
        mit einer Satzpause klang das wie ein Haken. Ein kleiner Atemrand
        bleibt bewusst stehen, die Prosodie innerhalb der Aufnahme wird nicht
        veraendert.
        """

        try:
            with wave.open(str(path), "rb") as handle:
                total_frames = handle.getnframes()
                if not self._trim_boundary_silence or handle.getsampwidth() != 2:
                    return 0, total_frames
                rate = handle.getframerate()
                channels = max(1, handle.getnchannels())
                raw = handle.readframes(total_frames)
        except (OSError, wave.Error):
            return 0, 0

        samples = array.array("h")
        samples.frombytes(raw[: len(raw) // 2 * 2])
        block_frames = max(1, int(max(1, rate) * 0.01))
        block_samples = block_frames * channels
        levels: list[float] = []
        for start in range(0, len(samples), block_samples):
            frame = samples[start : start + block_samples]
            if frame:
                levels.append(rms(frame))
        active = [index for index, level in enumerate(levels) if level >= 0.004]
        if not active:
            return 0, total_frames

        keep_before = int(rate * self._leading_silence_ms / 1000.0)
        keep_after = int(rate * self._trailing_silence_ms / 1000.0)
        first_frame = active[0] * block_frames
        last_frame = min(total_frames, (active[-1] + 1) * block_frames)
        start_frame = max(0, first_frame - keep_before)
        end_frame = min(total_frames, last_frame + keep_after)
        # Zu aggressive Erkennung darf eine sehr kurze Meldung nie leeren.
        if end_frame - start_frame < int(rate * 0.08):
            return 0, total_frames
        return start_frame, end_frame

    @staticmethod
    def _active_speech_rms(
        samples: array.array[int], *, sample_rate: int, channels: int
    ) -> float:
        """Misst die Lautheit nur in Rahmen, in denen wirklich Sprache liegt.

        Der Schwellwert folgt dem Grundpegel der jeweiligen Datei. Damit
        werden sowohl digitale Stille als auch leises Hintergrundrauschen
        ausgeschlossen, ohne leise gesprochene Silben abzuschneiden.
        """

        if not samples:
            return 0.0
        channel_count = max(1, int(channels))
        frame_samples = max(channel_count, int(max(1, sample_rate) * 0.02) * channel_count)
        levels: list[float] = []
        for start in range(0, len(samples), frame_samples):
            frame = samples[start : start + frame_samples]
            if len(frame) >= channel_count:
                levels.append(rms(frame))
        if not levels:
            return rms(samples)

        ordered = sorted(levels)
        noise_floor = ordered[int((len(ordered) - 1) * 0.20)]
        threshold = max(0.006, noise_floor * 1.8)
        active = [level for level in levels if level >= threshold]
        # Bei extrem kurzen/ungewoehnlichen Dateien nicht aus einem einzigen
        # Spitzenrahmen auf die ganze Lautheit schliessen.
        if len(active) < min(3, len(levels)):
            active = levels
        return math.sqrt(sum(level * level for level in active) / len(active))

    def _play_with_winsound(self, path: Path) -> bool:
        """Windows-Notlösung ohne Zusatzpakete.

        ``winsound`` kann weder den Pegel melden noch sauber mitten im Stück
        abbrechen; es wird deshalb nur benutzt, wenn ``sounddevice`` fehlt.
        Ein Abbruch wird über ``PlaySound(None)`` erzwungen.
        """

        if platform.system() != "Windows":
            logger.error(self.installation_hint())
            return False

        try:
            import winsound
        except ImportError:
            logger.error(self.installation_hint())
            return False

        duration = 0.0
        try:
            with wave.open(str(path), "rb") as handle:
                duration = handle.getnframes() / float(handle.getframerate() or 1)
        except Exception:  # noqa: BLE001
            duration = 0.0

        try:
            winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC)
        except RuntimeError:
            logger.exception("Die Windows-Wiedergabe ist fehlgeschlagen.")
            return False

        # In kleinen Schritten warten, damit ein Abbruch schnell greift.
        step = 0.05
        waited = 0.0
        while waited < duration:
            if self._stop_requested.is_set():
                try:
                    winsound.PlaySound(None, winsound.SND_PURGE)
                except RuntimeError:
                    pass
                return False
            threading.Event().wait(step)
            waited += step

        return True

    # --- Hilfen ------------------------------------------------------------------------

    @staticmethod
    def _safely(action: Callable[[], Any]) -> None:
        """Ruft eine Rückmeldung auf, ohne dass ein Fehler darin stört."""

        try:
            action()
        except Exception:  # noqa: BLE001
            logger.debug("Eine Rückmeldung der Wiedergabe ist fehlgeschlagen.", exc_info=True)

    @staticmethod
    def list_devices() -> list[dict[str, Any]]:
        """Listet die verfügbaren Ausgabegeräte auf."""

        try:
            import sounddevice as sd
        except (ImportError, OSError):
            return []

        devices: list[dict[str, Any]] = []
        try:
            for index, info in enumerate(sd.query_devices()):
                if int(info.get("max_output_channels", 0)) > 0:
                    devices.append(
                        {
                            "index": index,
                            "name": str(info.get("name", "")),
                            "channels": int(info.get("max_output_channels", 0)),
                        }
                    )
        except Exception:  # noqa: BLE001
            logger.exception("Die Lautsprecherliste konnte nicht gelesen werden.")
        return devices

    def status(self) -> dict[str, Any]:
        """Statusangaben für die Transparenzansicht."""

        return {
            "available": self.is_available(),
            "fallback": self.uses_fallback(),
            "playing": self.is_playing,
            "current": str(self._current) if self._current else "",
            "normalize_volume": self._normalize_volume,
            "target_rms": self._target_rms,
            "trim_boundary_silence": self._trim_boundary_silence,
        }
