"""Mikrofonaufnahme mit Erkennung von Sprachabschnitten.

Nimmt fortlaufend vom Mikrofon auf, erkennt über die
:class:`~backend.audio.vad.VoiceActivityDetector` wann gesprochen wird, und
gibt jede abgeschlossene Äußerung als WAV-Datei weiter.

Zwei Eigenschaften sind für die Alltagstauglichkeit wesentlich:

Erstens ein **Vorlauf-Puffer**: Die letzten Millisekunden vor dem erkannten
Sprachbeginn werden mitgespeichert. Ohne ihn fehlte der Anfang jedes Wortes,
und gerade das Weckwort würde regelmäßig verstümmelt.

Zweitens läuft die Aufnahme in einem **eigenen Thread**. Die Audio-Rückrufe
des Betriebssystems dürfen nicht warten; sie legen ihre Daten nur in eine
Warteschlange, aus der ein Worker sie in Ruhe verarbeitet.

Ohne das Paket ``sounddevice`` meldet das Modul das ausdrücklich mit einer
Anleitung.
"""

from __future__ import annotations

import array
import queue
import tempfile
import threading
import time
import wave
from collections import deque
from pathlib import Path
from typing import Any, Callable

from backend.audio.vad import VoiceActivityDetector
from backend.system.logging_setup import get_logger

logger = get_logger(__name__)

#: Abtastrate, die Whisper erwartet.
SAMPLE_RATE = 16000

#: Ein Audioblock umfasst 30 Millisekunden.
BLOCK_DURATION_MS = 30.0
BLOCK_SIZE = int(SAMPLE_RATE * BLOCK_DURATION_MS / 1000.0)


class AudioCapture:
    """Nimmt vom Mikrofon auf und liefert einzelne Sprachabschnitte."""

    def __init__(
        self,
        on_utterance: Callable[[Path, float], None],
        *,
        on_interruption: Callable[[], None] | None = None,
        on_stop_window: Callable[[Path], None] | None = None,
        stop_window_ready: Callable[[], bool] | None = None,
        stop_window_ms: float = 1200.0,
        interruption_hold_ms: float = 270.0,
        device: int | str | None = None,
        preroll_ms: float = 400.0,
        silence_ms: float = 900.0,
        threshold_factor: float = 3.0,
        minimum_speech_ms: float = 350.0,
        max_utterance_seconds: float = 20.0,
        output_directory: Path | None = None,
    ) -> None:
        """
        Args:
            on_utterance: Wird für jede erkannte Äußerung aufgerufen und
                erhält Pfad und Dauer der Aufnahme.
            on_interruption: Wird aufgerufen, wenn während der
                Stummschaltung anhaltend gesprochen wird – also wenn der
                Benutzer dem Orb ins Wort fällt.
            on_stop_window: Bekommt während des Sprechens in festen
                Abständen ein kurzes Hörfenster als WAV-Datei. Darüber
                erkennt der Orb das Stop-Wort, WÄHREND er selbst redet –
                die gewöhnliche Äußerungserkennung taugt dafür nicht, denn
                sie wartet auf Stille, und die gibt es nicht, solange die
                eigene Stimme aus dem Lautsprecher kommt.
            stop_window_ready: Wird vor jedem Hörfenster gefragt, ob
                eines gebraucht wird. Sagt es nein, wird gar nicht erst
                geschrieben.
            stop_window_ms: Länge eines solchen Hörfensters.
            interruption_hold_ms: Wie lange dafür durchgehend Sprache
                anliegen muss.
            device: Eingabegerät; ``None`` nutzt das Standardmikrofon.
            preroll_ms: Wie viel vor dem Sprachbeginn mitgespeichert wird.
            silence_ms: Wie lange Stille eine Äußerung beendet.
            threshold_factor: Empfindlichkeit der Sprachaktivitätserkennung.
            minimum_speech_ms: Kürzere Geräusche werden verworfen.
            max_utterance_seconds: Obergrenze einer einzelnen Aufnahme.
            output_directory: Wohin die WAV-Dateien geschrieben werden.
        """

        self._on_utterance = on_utterance
        self._on_interruption = on_interruption
        self._on_stop_window = on_stop_window
        self._stop_window_ready = stop_window_ready

        # Der Stop-Späher: sammelt während des Sprechens alle Blöcke und
        # gibt sie in festen Fenstern weiter – unabhängig von der
        # Sprachaktivitätserkennung.
        self._stop_spotting = False
        self._spot_blocks_per_window = max(10, int(stop_window_ms / BLOCK_DURATION_MS))
        # Die Fenster ÜBERLAPPEN sich: Ein neues beginnt, bevor das alte
        # endet.
        #
        # Ohne Überlappung lagen die Fenster lückenlos aneinander – und ein
        # kurzes „stop" fiel dann leicht genau auf die Naht: die erste
        # Hälfte im einen Fenster, die zweite im nächsten, in keinem davon
        # erkennbar. Bei halber Schrittweite ist jedes gesprochene Wort in
        # mindestens einem Fenster vollständig enthalten.
        self._spot_hop_blocks = max(5, self._spot_blocks_per_window // 2)
        self._spot_buffer: list[bytes] = []
        self._spot_since_last = 0
        self._spot_window_counter = 0

        # Wie viele Blöcke am Stück Sprache sein müssen, damit es als
        # Dazwischenreden gilt.
        #
        # Eine einzelne laute Stelle genügt nicht: Der Lautsprecher spielt
        # die Stimme des Orb ab, das Mikrofon hört sie mit, und ein
        # einzelner Ausschlag wäre nicht von einem Wort zu unterscheiden.
        # Ein Viertel einer Sekunde durchgehend ist es sehr wohl.
        self._interruption_blocks = max(2, int(interruption_hold_ms / BLOCK_DURATION_MS))
        self._speech_run = 0
        self._interruption_sent = False

        self._device = device
        self._minimum_blocks = int(minimum_speech_ms / BLOCK_DURATION_MS)
        self._output_directory = output_directory or Path(tempfile.gettempdir()) / "ai-orb-audio"
        self._output_directory.mkdir(parents=True, exist_ok=True)

        self._vad = VoiceActivityDetector(
            block_duration_ms=BLOCK_DURATION_MS,
            silence_duration_ms=silence_ms,
            threshold_factor=threshold_factor,
            max_utterance_seconds=max_utterance_seconds,
        )

        preroll_blocks = max(1, int(preroll_ms / BLOCK_DURATION_MS))
        self._preroll: deque[bytes] = deque(maxlen=preroll_blocks)

        self._queue: queue.Queue[bytes | None] = queue.Queue(maxsize=200)
        self._stream: Any | None = None
        self._worker: threading.Thread | None = None
        self._running = False
        self._muted = False
        self._current: list[bytes] = []
        self._level = 0.0

    # --- Verfügbarkeit ---------------------------------------------------------

    @staticmethod
    def is_available() -> bool:
        """Ob das Paket ``sounddevice`` installiert ist."""

        try:
            import sounddevice  # noqa: F401
        except (ImportError, OSError):
            return False
        return True

    @staticmethod
    def installation_hint() -> str:
        """Anleitung, falls die Aufnahme nicht möglich ist."""

        return (
            "Für die Spracheingabe fehlt das Paket 'sounddevice'. "
            "Installiere es mit:\n"
            "    .venv\\Scripts\\python.exe -m pip install -r requirements-voice.txt"
        )

    @staticmethod
    def list_devices() -> list[dict[str, Any]]:
        """Listet die verfügbaren Eingabegeräte auf."""

        try:
            import sounddevice as sd
        except (ImportError, OSError):
            return []

        devices: list[dict[str, Any]] = []
        try:
            for index, info in enumerate(sd.query_devices()):
                if int(info.get("max_input_channels", 0)) > 0:
                    devices.append(
                        {
                            "index": index,
                            "name": str(info.get("name", "")),
                            "channels": int(info.get("max_input_channels", 0)),
                        }
                    )
        except Exception:  # noqa: BLE001
            logger.exception("Die Mikrofonliste konnte nicht gelesen werden.")
        return devices

    # --- Steuerung ---------------------------------------------------------------

    def start(self) -> bool:
        """Startet die Aufnahme.

        Returns:
            ``True``, wenn das Mikrofon geöffnet werden konnte.
        """

        if self._running:
            return True

        try:
            import sounddevice as sd
        except (ImportError, OSError):
            logger.error(self.installation_hint())
            return False

        def callback(indata: Any, frames: int, time_info: Any, status: Any) -> None:
            # Der Rückruf des Audiotreibers muss sofort zurückkehren – hier
            # wird ausschließlich in die Warteschlange gelegt.
            if status:
                logger.debug("Audiostatus: %s", status)
            try:
                self._queue.put_nowait(bytes(indata))
            except queue.Full:
                # Lieber einen Block verwerfen als den Treiber aufhalten.
                pass

        # Drei Anläufe statt einem. Der häufigste Fehler im Betrieb war
        # PortAudios „Unanticipated host error“ (MME) direkt beim Öffnen –
        # vierzehn Vorfälle in den Protokollen. Der Fehler ist meist
        # vorübergehend: Windows hat das Gerät gerade gewechselt (Kopfhörer
        # ein- oder ausgesteckt) oder eine andere Anwendung hält es noch
        # einen Moment fest. Ein zweiter Versuch eine Sekunde später
        # genügt dann.
        #
        # Und wenn ein BESTIMMTES Mikrofon eingestellt ist, kann dessen
        # Nummer nach dem Umstecken ins Leere zeigen. Als letzter Anlauf
        # gilt darum das Standardgerät – lieber mit dem falschen Mikrofon
        # hören als gar nicht, und im Protokoll steht, dass gewechselt
        # wurde.
        anlaeufe: list[tuple[Any, float]] = [(self._device, 0.0), (self._device, 1.0)]
        if self._device is not None:
            anlaeufe.append((None, 1.0))

        letzter_fehler: Exception | None = None
        for nummer, (geraet, pause) in enumerate(anlaeufe, start=1):
            if pause:
                time.sleep(pause)
            try:
                stream = sd.RawInputStream(
                    samplerate=SAMPLE_RATE,
                    blocksize=BLOCK_SIZE,
                    device=geraet,
                    channels=1,
                    dtype="int16",
                    callback=callback,
                )
                stream.start()
            except Exception as fehler:  # noqa: BLE001
                letzter_fehler = fehler
                logger.warning(
                    "Mikrofon-Anlauf %d/%d fehlgeschlagen (%s).",
                    nummer, len(anlaeufe), fehler,
                )
                continue
            self._stream = stream
            if nummer > 1:
                logger.info("Mikrofon im %d. Anlauf geöffnet.", nummer)
            if geraet is None and self._device is not None:
                logger.warning(
                    "Das eingestellte Mikrofon (%s) war nicht zu öffnen - "
                    "es läuft jetzt das Standardgerät.", self._device,
                )
            break
        else:
            logger.error(
                "Das Mikrofon konnte nicht geöffnet werden. Ist eines "
                "angeschlossen, und darf AI-Orb darauf zugreifen? "
                "(Windows-Einstellungen → Datenschutz → Mikrofon)",
                exc_info=letzter_fehler,
            )
            self._stream = None
            return False

        self._running = True
        self._worker = threading.Thread(target=self._process_loop, name="ai-orb-audio", daemon=True)
        self._worker.start()

        logger.info("Mikrofon aktiv (%d Hz, Blöcke à %.0f ms).", SAMPLE_RATE, BLOCK_DURATION_MS)
        return True

    def stop(self) -> None:
        """Beendet die Aufnahme und gibt das Mikrofon frei."""

        if not self._running:
            return

        self._running = False
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass

        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:  # noqa: BLE001
                logger.debug("Fehler beim Schließen des Mikrofons.", exc_info=True)
            self._stream = None

        if self._worker is not None:
            self._worker.join(timeout=2.0)
            self._worker = None

        logger.info("Mikrofon freigegeben.")

    def mute(self, muted: bool) -> None:
        """Schaltet die Auswertung stumm, ohne das Mikrofon zu schließen.

        Wird genutzt, während der Orb selbst spricht – sonst würde er sich
        selbst zuhören und auf die eigene Antwort reagieren.
        """

        self._muted = muted
        self._speech_run = 0

        if muted:
            self._current.clear()
            self._preroll.clear()
            self._vad.reset()
            # Jede Stummschaltung darf einmal unterbrochen werden.
            self._interruption_sent = False

    @property
    def is_running(self) -> bool:
        """Ob die Aufnahme läuft."""

        return self._running

    @property
    def is_muted(self) -> bool:
        """Ob die Auswertung gerade stummgeschaltet ist."""

        return self._muted

    @property
    def level(self) -> float:
        """Der zuletzt gemessene Lautstärkepegel (0.0 bis 1.0)."""

        return self._level

    # --- Verarbeitung ---------------------------------------------------------------

    def _process_loop(self) -> None:
        """Wertet die aufgenommenen Blöcke aus (eigener Thread)."""

        while self._running:
            try:
                block = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue

            if block is None:
                break

            try:
                self._handle_block(block)
            except Exception:  # noqa: BLE001 - die Aufnahme darf nie abbrechen.
                logger.exception("Fehler bei der Audioverarbeitung.")

    def _handle_block(self, block: bytes) -> None:
        samples = array.array("h")
        samples.frombytes(block)

        event = self._vad.process(samples)
        self._level = event.level

        # Der Stop-Späher läuft VOR allem anderen und unabhängig von der
        # Stummschaltung: Solange der Orb spricht, wird jedes Fenster
        # weitergegeben – ob die Sprachaktivitätserkennung darin Sprache
        # sieht oder nicht, entscheidet nicht hier, sondern die Erkennung.
        if self._stop_spotting and self._on_stop_window is not None:
            self._spot_buffer.append(block)
            # Nur die letzten Blöcke behalten – das ist das Schiebefenster.
            if len(self._spot_buffer) > self._spot_blocks_per_window:
                del self._spot_buffer[: len(self._spot_buffer) - self._spot_blocks_per_window]

            self._spot_since_last += 1
            if (
                self._spot_since_last >= self._spot_hop_blocks
                and len(self._spot_buffer) >= self._spot_blocks_per_window
            ):
                self._spot_since_last = 0
                if self._stop_window_lohnt():
                    self._emit_stop_window(list(self._spot_buffer))

        if self._muted:
            # Stummgeschaltet heißt: nichts aufnehmen. Es heißt nicht:
            # nichts merken.
            #
            # Vorher wurde hier abgebrochen, und damit war das
            # Dazwischenreden nicht bloß unzuverlässig, sondern unmöglich:
            # Der Orb schaltet das Mikrofon ab, solange er spricht, damit
            # er sich nicht selbst zuhört. Wer ihn unterbrechen wollte,
            # redete gegen ein taubes Ohr.
            #
            # Jetzt läuft die Erkennung weiter. Aufgenommen wird immer
            # noch nichts – gemeldet wird nur, dass da jemand spricht.
            self._note_interruption(event)
            return

        self._speech_run = 0
        self._interruption_sent = False

        if event.speech_started:
            # Der Vorlauf wird vorangestellt, damit der Wortanfang erhalten
            # bleibt.
            self._current = list(self._preroll)
            self._current.append(block)
            return

        if self._vad.state.value == "sprache":
            self._current.append(block)
        else:
            self._preroll.append(block)

        if event.speech_ended and self._current:
            blocks = self._current
            self._current = []
            self._preroll.clear()

            if len(blocks) < self._minimum_blocks:
                # Zu kurz – vermutlich ein Husten, eine Tür, ein Tastenklick.
                return

            self._emit(blocks)

    def _note_interruption(self, event: Any) -> None:
        """Erkennt anhaltendes Sprechen während der Stummschaltung.

        Gemeldet wird höchstens einmal je Stummschaltung. Ein zweiter
        Hinweis brächte nichts – die Wiedergabe ist beim ersten schon
        gestoppt.
        """

        if self._on_interruption is None or self._interruption_sent:
            return

        if self._vad.state.value == "sprache" or event.speech_started:
            self._speech_run += 1
        else:
            self._speech_run = 0
            return

        if self._speech_run < self._interruption_blocks:
            return

        self._interruption_sent = True
        self._speech_run = 0

        try:
            self._on_interruption()
        except Exception:  # noqa: BLE001 - die Aufnahme darf nie abbrechen.
            logger.exception("Fehler beim Melden einer Unterbrechung.")

    def set_stop_spotting(self, enabled: bool) -> None:
        """Schaltet den Stop-Späher an oder aus.

        An, solange der Orb spricht; aus, sobald er fertig ist. Beim
        Ausschalten wird der angefangene Puffer verworfen – ein halbes
        Fenster nach dem Ende des Sprechens interessiert niemanden mehr.
        """

        self._stop_spotting = enabled
        if not enabled:
            self._spot_buffer = []
            self._spot_since_last = 0

    def _stop_window_lohnt(self) -> bool:
        """Ob dieses Hörfenster geschrieben werden muss.

        Zwei Gründe, es zu lassen - und beide sparen dieselbe Sache: eine
        WAV-Datei, die niemand ansieht. Bei einer Antwort von 45 Sekunden
        entstanden hier rund 75 davon, ueberwiegend aufgenommen von der
        eigenen Lautsprecherstimme.

        Erstens: Die Erkennung ist beschaeftigt und hat sich bereits ein
        naechstes Fenster gemerkt. Ein drittes waere schon veraltet, bevor
        es an die Reihe kaeme.

        Eine Pegelsperre stand hier auch schon - "unter dem Schwellwert
        ist nichts zu hoeren, also auch kein stop". Sie ist wieder
        gegangen: Sie haette ein leise gesprochenes "stop" gegen die eigene
        Lautsprecherstimme verschluckt, und die Eigenschaft, auf der dieser
        Spaeher beruht - jedes Wort liegt VOLLSTAENDIG in mindestens einem
        Fenster -, gilt nur, wenn die Fenster lueckenlos weiterlaufen.

        Im Zweifel wird geschrieben: Ein Fenster zu viel kostet eine Datei,
        ein Fenster zu wenig kostet das Stop-Wort.
        """

        if self._stop_window_ready is not None:
            try:
                if not self._stop_window_ready():
                    return False
            except Exception:  # noqa: BLE001 - die Aufnahme darf nie abbrechen.
                logger.debug(
                    "Die Rückfrage nach dem Hörfenster schlug fehl.", exc_info=True
                )

        return True

    def _emit_stop_window(self, blocks: list[bytes]) -> None:
        """Schreibt ein Hörfenster als WAV und meldet es weiter."""

        # Die laufende Nummer ist wichtig, nicht Zierde: Die Fenster
        # überlappen sich und folgen dicht aufeinander. Zwei Fenster in
        # derselben Millisekunde würden sich sonst gegenseitig
        # überschreiben – und die Erkennung liefe auf eine Datei, die es
        # so nicht mehr gibt.
        self._spot_window_counter += 1
        stempel = int(time.time() * 1000)
        path = (
            self._output_directory
            / f"stopfenster-{stempel}-{self._spot_window_counter}.wav"
        )
        try:
            with wave.open(str(path), "wb") as handle:
                handle.setnchannels(1)
                handle.setsampwidth(2)
                handle.setframerate(SAMPLE_RATE)
                handle.writeframes(b"".join(blocks))
        except OSError:
            logger.exception("Das Hörfenster konnte nicht gespeichert werden.")
            return

        try:
            self._on_stop_window(path)  # type: ignore[misc]
        except Exception:  # noqa: BLE001 - die Aufnahme darf nie abbrechen.
            logger.exception("Fehler bei der Weitergabe des Hörfensters.")

    def _emit(self, blocks: list[bytes]) -> None:
        """Schreibt eine Äußerung als WAV-Datei und meldet sie weiter."""

        duration = len(blocks) * BLOCK_DURATION_MS / 1000.0
        path = self._output_directory / f"utterance-{int(time.time() * 1000)}.wav"

        try:
            with wave.open(str(path), "wb") as handle:
                handle.setnchannels(1)
                handle.setsampwidth(2)
                handle.setframerate(SAMPLE_RATE)
                handle.writeframes(b"".join(blocks))
        except OSError:
            logger.exception("Die Aufnahme konnte nicht gespeichert werden.")
            return

        logger.debug("Äußerung aufgenommen (%.1f s): %s", duration, path.name)

        try:
            self._on_utterance(path, duration)
        except Exception:  # noqa: BLE001
            logger.exception("Fehler bei der Weitergabe der Aufnahme.")

    def cleanup(self, keep_last: int = 5) -> int:
        """Räumt alte Aufnahmen auf.

        Returns:
            Anzahl der gelöschten Dateien.
        """

        files = sorted(self._output_directory.glob("utterance-*.wav"))
        removed = 0
        for path in files[:-keep_last] if keep_last else files:
            try:
                path.unlink()
                removed += 1
            except OSError:
                pass
        return removed

    def status(self) -> dict[str, Any]:
        """Statusangaben für die Transparenzansicht."""

        return {
            "available": self.is_available(),
            "running": self._running,
            "muted": self._muted,
            "level": round(self._level, 4),
            "noise_floor": round(self._vad.noise_floor, 4),
            "threshold": round(self._vad.threshold, 4),
            "sample_rate": SAMPLE_RATE,
        }
