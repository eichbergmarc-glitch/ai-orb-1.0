"""Sprachausgabe über die Windows-Sprachausgabe (SAPI).

Dieses Verfahren ist die verlässliche Rückfallebene: Es ist auf jedem
Windows-Rechner vorhanden, verlangt keine Installation, kein Modell und
keinen Download, und es beherrscht Deutsch von Haus aus.

Angesprochen wird es über PowerShell und ``System.Speech``. Das ist
umständlicher als eine Python-Anbindung, hat aber einen entscheidenden
Vorteil: Es funktioniert ohne jedes zusätzliche Paket. Ein Assistent, der
erst nach einer Paketinstallation sprechen kann, schweigt genau dann, wenn
man ihn am nötigsten braucht.

Die Sprechgeschwindigkeit von SAPI reicht von -10 bis 10. Der hier
verwendete Faktor 1.0 entspricht 0; die Umrechnung ist bewusst flach
gehalten, weil SAPI schon bei kleinen Werten deutlich hörbar reagiert.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from backend.system.logging_setup import get_logger
from backend.tts.base_engine import SpeechRequest, SpeechResult, TtsEngine

logger = get_logger(__name__)

#: Zeitlimit für einen Aufruf. Sprechen dauert selten länger.
DEFAULT_TIMEOUT = 60.0


def _powershell() -> str | None:
    """Findet eine PowerShell. Bevorzugt die neuere, nimmt sonst die alte."""

    for candidate in ("pwsh", "powershell"):
        found = shutil.which(candidate)
        if found:
            return found
    return None


class SapiEngine(TtsEngine):
    """Windows-Sprachausgabe über System.Speech."""

    name = "sapi"

    def is_available(self) -> bool:
        """Ob Windows und eine PowerShell vorhanden sind."""

        if platform.system() != "Windows":
            return False
        return _powershell() is not None

    def installation_hint(self) -> str:
        if platform.system() != "Windows":
            return (
                "Die Windows-Sprachausgabe gibt es nur unter Windows. "
                "Trage in config.yaml unter 'voice.output.engines' ein anderes "
                "Verfahren an erster Stelle ein."
            )
        return (
            "PowerShell wurde nicht gefunden. Sie gehört zum Lieferumfang von "
            "Windows; prüfe, ob sie durch eine Richtlinie gesperrt ist."
        )

    # --- Erzeugung ---------------------------------------------------------------

    def synthesize_blocking(self, request: SpeechRequest, target: Path) -> SpeechResult:
        started = self._now()

        executable = _powershell()
        if executable is None:
            return SpeechResult(
                engine=self.name, error="PowerShell wurde nicht gefunden."
            )

        script = self._build_script(request, target)

        # Das Skript wird in eine Datei geschrieben statt als Argument
        # übergeben: Der Text kann Anführungszeichen, Zeilenumbrüche und
        # Sonderzeichen enthalten, die auf der Befehlszeile zu Fehlern
        # führen würden.
        script_file = Path(tempfile.gettempdir()) / f"ai-orb-sapi-{os.getpid()}.ps1"
        try:
            script_file.write_text(script, encoding="utf-8-sig")
        except OSError as error:
            return SpeechResult(
                engine=self.name, error=f"Das Sprachskript konnte nicht angelegt werden: {error}"
            )

        try:
            completed = subprocess.run(  # noqa: S603 - fester Befehl, kein Benutzereingabe-Shell
                [
                    executable,
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(script_file),
                ],
                capture_output=True,
                text=True,
                timeout=float(self.option("timeout", DEFAULT_TIMEOUT)),
                check=False,
            )
        except subprocess.TimeoutExpired:
            return SpeechResult(
                engine=self.name,
                error="Die Windows-Sprachausgabe hat nicht rechtzeitig geantwortet.",
            )
        except OSError as error:
            return SpeechResult(engine=self.name, error=f"PowerShell ließ sich nicht starten: {error}")
        finally:
            try:
                script_file.unlink()
            except OSError:
                pass

        if completed.returncode != 0 or not target.exists():
            message = (completed.stderr or completed.stdout or "").strip()
            return SpeechResult(
                engine=self.name,
                error=message or "Die Windows-Sprachausgabe hat keine Datei erzeugt.",
            )

        return SpeechResult(
            audio_path=target,
            engine=self.name,
            duration_seconds=self.wav_duration(target),
            processing_seconds=self._now() - started,
            context={"voice": request.voice or str(self.option("voice", ""))},
        )

    def _build_script(self, request: SpeechRequest, target: Path) -> str:
        """Setzt das PowerShell-Skript zusammen."""

        # SAPI-Geschwindigkeit: -10 bis 10, 0 ist normal.
        rate = int(round((request.speed - 1.0) * 6.0))
        rate = max(-10, min(10, rate))

        volume = int(round(max(0.0, min(1.0, request.volume)) * 100))

        voice = request.voice or str(self.option("voice", ""))

        # Einfache Anführungszeichen in PowerShell verdoppeln.
        text = request.text.replace("'", "''")
        voice_escaped = voice.replace("'", "''")
        target_escaped = str(target).replace("'", "''")

        select_voice = ""
        if voice:
            # Fehlt die gewünschte Stimme, wird die Standardstimme benutzt,
            # statt den ganzen Vorgang abzubrechen. Lieber eine andere
            # Stimme als Schweigen.
            select_voice = f"""
try {{ $synth.SelectVoice('{voice_escaped}') }}
catch {{ Write-Output "Stimme '{voice_escaped}' nicht gefunden, Standardstimme wird benutzt." }}
"""
        else:
            # Ohne feste Vorgabe die erste deutsche Stimme wählen, sonst
            # spricht Windows deutschen Text mit englischer Aussprache.
            select_voice = """
$german = $synth.GetInstalledVoices() |
    Where-Object { $_.VoiceInfo.Culture.TwoLetterISOLanguageName -eq 'de' } |
    Select-Object -First 1
if ($german) { $synth.SelectVoice($german.VoiceInfo.Name) }
"""

        return f"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
{select_voice}
$synth.Rate = {rate}
$synth.Volume = {volume}
$synth.SetOutputToWaveFile('{target_escaped}')
$synth.Speak('{text}')
$synth.SetOutputToNull()
$synth.Dispose()
"""

    # --- Auskunft ------------------------------------------------------------------

    def voices(self) -> list[dict[str, str]]:
        """Fragt die installierten Windows-Stimmen ab."""

        executable = _powershell()
        if executable is None:
            return []

        script = (
            "Add-Type -AssemblyName System.Speech; "
            "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            "$s.GetInstalledVoices() | ForEach-Object { "
            "  $_.VoiceInfo.Name + '|' + $_.VoiceInfo.Culture.Name + '|' + $_.VoiceInfo.Gender "
            "}"
        )

        try:
            completed = subprocess.run(  # noqa: S603
                [executable, "-NoProfile", "-NonInteractive", "-Command", script],
                capture_output=True,
                text=True,
                timeout=20.0,
                check=False,
            )
        except (subprocess.TimeoutExpired, OSError):
            return []

        found: list[dict[str, str]] = []
        for line in (completed.stdout or "").splitlines():
            parts = line.strip().split("|")
            if len(parts) >= 2 and parts[0]:
                found.append(
                    {"name": parts[0], "language": parts[1], "gender": parts[2] if len(parts) > 2 else ""}
                )
        return found

    def status(self) -> dict[str, Any]:
        base = super().status()
        base["note"] = "Immer verfügbar unter Windows, deutsche Stimmen enthalten."
        return base
