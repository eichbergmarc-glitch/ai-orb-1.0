"""Benchmark: schnelle deutsche Piper-Sprache mit OpenVoice-Klangfarbenklon."""

from __future__ import annotations

import sys
import time
import wave
from pathlib import Path

import librosa
import soundfile
import torch


PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / "runtime" / "openvoice-source"))

from backend.tts.base_engine import SpeechRequest  # noqa: E402
from backend.tts.piper_engine import PiperEngine  # noqa: E402
from openvoice import utils  # noqa: E402
from openvoice.mel_processing import spectrogram_torch  # noqa: E402
from openvoice.models import SynthesizerTrn  # noqa: E402


class Converter:
    """Schlanker OpenVoice-V2-Konverter ohne Demo-/Whisper-Abhaengigkeiten."""

    def __init__(self, config: Path, checkpoint: Path) -> None:
        self.device = "cpu"
        self.hps = utils.get_hparams_from_file(str(config))
        self.model = SynthesizerTrn(
            len(getattr(self.hps, "symbols", [])),
            self.hps.data.filter_length // 2 + 1,
            n_speakers=self.hps.data.n_speakers,
            **self.hps.model,
        ).to(self.device)
        state = torch.load(str(checkpoint), map_location="cpu", weights_only=True)
        self.model.load_state_dict(state["model"], strict=False)
        self.model.eval()

    def extract_se(self, audio_path: Path) -> torch.Tensor:
        audio, _ = librosa.load(str(audio_path), sr=self.hps.data.sampling_rate)
        samples = torch.from_numpy(audio).float().unsqueeze(0)
        spec = spectrogram_torch(
            samples,
            self.hps.data.filter_length,
            self.hps.data.sampling_rate,
            self.hps.data.hop_length,
            self.hps.data.win_length,
            center=False,
        )
        with torch.inference_mode():
            return self.model.ref_enc(spec.transpose(1, 2)).unsqueeze(-1).detach()

    def convert(
        self,
        source: Path,
        source_se: torch.Tensor,
        target_se: torch.Tensor,
        output: Path,
    ) -> None:
        audio, _ = librosa.load(str(source), sr=self.hps.data.sampling_rate)
        samples = torch.from_numpy(audio).float().unsqueeze(0)
        spec = spectrogram_torch(
            samples,
            self.hps.data.filter_length,
            self.hps.data.sampling_rate,
            self.hps.data.hop_length,
            self.hps.data.win_length,
            center=False,
        )
        lengths = torch.LongTensor([spec.size(-1)])
        with torch.inference_mode():
            result = self.model.voice_conversion(
                spec,
                lengths,
                sid_src=source_se,
                sid_tgt=target_se,
                tau=0.3,
            )[0][0, 0].cpu().float().numpy()
        soundfile.write(str(output), result, self.hps.data.sampling_rate, subtype="PCM_16")


def duration(path: Path) -> float:
    with wave.open(str(path), "rb") as handle:
        return handle.getnframes() / float(handle.getframerate())


def main() -> None:
    torch.set_num_threads(min(10, max(1, torch.get_num_threads())))
    output_dir = PROJECT / "data" / "tts"
    output_dir.mkdir(parents=True, exist_ok=True)
    source_reference = PROJECT / "data" / "voice" / "piper-source-reference.wav"
    target_reference = PROJECT / "data" / "voice" / "orb-reference.wav"

    piper = PiperEngine(
        output_directory=output_dir,
        options={"voice": "de_DE-thorsten-high"},
    )
    if not source_reference.exists():
        result = piper.synthesize_blocking(
            SpeechRequest(
                text=(
                    "Dies ist eine ruhige deutsche Referenzstimme. Sie spricht klar, "
                    "natürlich und mit gleichmäßigem Tempo."
                )
            ),
            source_reference,
        )
        if not result.succeeded:
            raise RuntimeError(result.error)

    model_dir = PROJECT / "data" / "cache" / "models" / "openvoice" / "converter"
    started = time.perf_counter()
    converter = Converter(model_dir / "config.json", model_dir / "checkpoint.pth")
    load_seconds = time.perf_counter() - started

    started = time.perf_counter()
    source_se = converter.extract_se(source_reference)
    target_se = converter.extract_se(target_reference)
    embedding_seconds = time.perf_counter() - started

    texts = (
        "Ich antworte jetzt schnell und mit der vertrauten Stimme.",
        "Das lokale Sprachmodell ist bereit und der naechste Satz folgt ohne lange Pause.",
        "So klingt eine etwas laengere Antwort, die trotzdem fluessig erzeugt werden soll.",
    )
    print(f"load={load_seconds:.3f}s embeddings={embedding_seconds:.3f}s")
    for index, text in enumerate(texts, start=1):
        source = output_dir / f"openvoice-source-{index}.wav"
        cloned = output_dir / f"openvoice-benchmark-{index}.wav"
        started = time.perf_counter()
        base = piper.synthesize_blocking(SpeechRequest(text=text), source)
        piper_seconds = time.perf_counter() - started
        if not base.succeeded:
            raise RuntimeError(base.error)
        conversion_started = time.perf_counter()
        converter.convert(source, source_se, target_se, cloned)
        conversion_seconds = time.perf_counter() - conversion_started
        total_seconds = time.perf_counter() - started
        audio_seconds = duration(cloned)
        print(
            f"run={index} piper={piper_seconds:.3f}s convert={conversion_seconds:.3f}s "
            f"total={total_seconds:.3f}s audio={audio_seconds:.3f}s "
            f"rtf={total_seconds / max(audio_seconds, 0.001):.3f} file={cloned}"
        )


if __name__ == "__main__":
    main()
