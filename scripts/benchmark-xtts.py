"""Misst XTTS-v2-Streaming mit Orbs autorisierter Referenzstimme.

Die Abhaengigkeiten liegen absichtlich getrennt unter
``runtime/xtts-packages``. Das Skript veraendert deshalb den Suchpfad nur
fuer diesen Prozess und kann weder Chatterbox noch Whisper im Orb-Prozess
ueberschreiben.
"""

from __future__ import annotations

import json
import os
import sys
import time
import wave
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
XTTS_PACKAGES = ROOT / "runtime" / "xtts-packages"
CACHE = ROOT / "data" / "cache" / "models" / "xtts"
REFERENCE = ROOT / "data" / "voice" / "orb-reference.wav"
OUTPUT = ROOT / "data" / "tts" / "xtts-benchmark.wav"

sys.path.insert(0, str(XTTS_PACKAGES))
os.environ.setdefault("COQUI_TOS_AGREED", "1")
os.environ.setdefault("TTS_HOME", str(CACHE))
os.environ.setdefault("MPLCONFIGDIR", str(CACHE / "matplotlib"))
os.environ.setdefault("NUMBA_CACHE_DIR", str(CACHE / "numba"))
os.environ.setdefault("HF_HOME", str(CACHE / "huggingface"))


def save_pcm(path: Path, waveform: object, sample_rate: int) -> float:
    """Schreibt einen Torch-Tensor ohne weitere Audio-Backends als PCM16."""

    samples = (
        waveform.detach().cpu().float().clamp(-1.0, 1.0).numpy().reshape(-1)
        * 32767.0
    ).astype("<i2")
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(samples.tobytes())
    return len(samples) / float(sample_rate)


def main() -> None:
    import torch
    from TTS.api import TTS

    if not REFERENCE.exists():
        raise FileNotFoundError(REFERENCE)

    threads = max(1, int(os.environ.get("XTTS_THREADS", str(torch.get_num_threads()))))
    greedy = os.environ.get("XTTS_GREEDY", "0") == "1"
    torch.set_num_threads(threads)

    load_started = time.perf_counter()
    api = TTS(
        "tts_models/multilingual/multi-dataset/xtts_v2",
        progress_bar=True,
        gpu=False,
    )
    model = api.synthesizer.tts_model
    load_seconds = time.perf_counter() - load_started

    conditioning_started = time.perf_counter()
    gpt_cond_latent, speaker_embedding = model.get_conditioning_latents(
        audio_path=[str(REFERENCE)],
        gpt_cond_len=6,
        gpt_cond_chunk_len=6,
        max_ref_length=12,
    )
    conditioning_seconds = time.perf_counter() - conditioning_started

    text = "Die lokale Stimme ist jetzt bereit."
    generation_started = time.perf_counter()
    first_chunk_seconds = 0.0
    chunks = []
    for chunk in model.inference_stream(
        text,
        "de",
        gpt_cond_latent,
        speaker_embedding,
        stream_chunk_size=20,
        overlap_wav_len=1024,
        enable_text_splitting=False,
        speed=1.0,
        do_sample=not greedy,
    ):
        if not chunks:
            first_chunk_seconds = time.perf_counter() - generation_started
        chunks.append(chunk)

    generation_seconds = time.perf_counter() - generation_started
    if not chunks:
        raise RuntimeError("XTTS hat keinen Audioblock erzeugt.")
    waveform = torch.cat(chunks, dim=-1)
    duration_seconds = save_pcm(OUTPUT, waveform, int(model.config.audio.output_sample_rate))
    _, generated_embedding = model.get_conditioning_latents(
        audio_path=[str(OUTPUT)],
        gpt_cond_len=min(4, max(1, int(duration_seconds))),
        gpt_cond_chunk_len=min(4, max(1, int(duration_seconds))),
        max_ref_length=max(2, int(duration_seconds) + 1),
    )
    speaker_similarity = torch.nn.functional.cosine_similarity(
        speaker_embedding.reshape(1, -1),
        generated_embedding.reshape(1, -1),
    ).item()

    print(
        json.dumps(
            {
                "output": str(OUTPUT),
                "load_seconds": round(load_seconds, 3),
                "conditioning_seconds": round(conditioning_seconds, 3),
                "first_chunk_seconds": round(first_chunk_seconds, 3),
                "generation_seconds": round(generation_seconds, 3),
                "audio_seconds": round(duration_seconds, 3),
                "realtime_factor": round(generation_seconds / max(duration_seconds, 0.001), 3),
                "speaker_similarity": round(speaker_similarity, 4),
                "chunks": len(chunks),
                "torch": torch.__version__,
                "device": "cpu",
                "threads": threads,
                "greedy": greedy,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
