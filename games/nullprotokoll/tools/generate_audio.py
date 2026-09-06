#!/usr/bin/env python3
"""Erzeugt Raumatmosphären und Effektgeräusche für NULLPROTOKOLL.

Alle Klänge werden synthetisiert, es werden keine Fremddateien benötigt und es
entstehen keine Lizenzfragen. Ergebnis:

    assets/audio/ambience/<ort>.ogg   nahtlose 30-Sekunden-Schleifen
    assets/audio/sfx/<name>.ogg       kurze Einzelgeräusche

Aufruf:  python3 tools/generate_audio.py [zielordner]
Benötigt: numpy und ffmpeg (mit libvorbis).
"""

from __future__ import annotations

import math
import os
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

RATE = 44100
LOOP_SECONDS = 30.0
RNG = np.random.default_rng(20260828)


# ---------------------------------------------------------------- Bausteine


def timeline(seconds: float) -> np.ndarray:
    return np.arange(int(RATE * seconds), dtype=np.float64) / RATE


def sine(t: np.ndarray, freq: float, phase: float = 0.0) -> np.ndarray:
    return np.sin(2.0 * math.pi * freq * t + phase)


def loop_lfo(t: np.ndarray, cycles: int, phase: float = 0.0) -> np.ndarray:
    """LFO, dessen Periode die Schleifenlänge exakt teilt."""
    return np.sin(2.0 * math.pi * cycles * t / LOOP_SECONDS + phase)


def noise(length: int) -> np.ndarray:
    return RNG.normal(0.0, 1.0, length)


def lowpass(signal: np.ndarray, cutoff: float) -> np.ndarray:
    """Einpoliger Tiefpass; ausreichend und sehr schnell."""
    alpha = 1.0 - math.exp(-2.0 * math.pi * cutoff / RATE)
    out = np.empty_like(signal)
    acc = 0.0
    for index in range(signal.size):
        acc += alpha * (signal[index] - acc)
        out[index] = acc
    return out


def lowpass_fast(signal: np.ndarray, cutoff: float) -> np.ndarray:
    """Tiefpass über FFT – für lange Puffer deutlich schneller."""
    spectrum = np.fft.rfft(signal)
    freqs = np.fft.rfftfreq(signal.size, 1.0 / RATE)
    spectrum *= 1.0 / (1.0 + (freqs / max(cutoff, 1.0)) ** 2)
    return np.fft.irfft(spectrum, n=signal.size)


def highpass_fast(signal: np.ndarray, cutoff: float) -> np.ndarray:
    spectrum = np.fft.rfft(signal)
    freqs = np.fft.rfftfreq(signal.size, 1.0 / RATE)
    ratio = (freqs / max(cutoff, 1.0)) ** 2
    spectrum *= ratio / (1.0 + ratio)
    return np.fft.irfft(spectrum, n=signal.size)


def bandpass(signal: np.ndarray, low: float, high: float) -> np.ndarray:
    return highpass_fast(lowpass_fast(signal, high), low)


def impulses(length: int, count: int, spread: float = 0.0) -> np.ndarray:
    """Gleichmäßig verteilte Impulse mit optionalem Jitter."""
    out = np.zeros(length)
    if count <= 0:
        return out
    step = length / count
    for index in range(count):
        position = int(index * step + RNG.uniform(-spread, spread) * step)
        if 0 <= position < length:
            out[position] = 1.0
    return out


def envelope(length: int, attack: float, decay: float) -> np.ndarray:
    t = np.arange(length, dtype=np.float64) / RATE
    attack = max(attack, 1e-4)
    rise = np.clip(t / attack, 0.0, 1.0)
    fall = np.exp(-t / max(decay, 1e-4))
    return rise * fall


def place(target: np.ndarray, source: np.ndarray, position: int) -> None:
    end = min(target.size, position + source.size)
    if end <= position:
        return
    target[position:end] += source[: end - position]


def scatter(length: int, maker, count: int, gain: float = 1.0) -> np.ndarray:
    out = np.zeros(length)
    for _ in range(count):
        grain = maker()
        place(out, grain * gain, int(RNG.uniform(0, length)))
    return out


def seamless(signal: np.ndarray, fade_seconds: float = 2.5) -> np.ndarray:
    """Blendet das Ende auf den Anfang, damit die Schleife nicht klickt."""
    fade = int(RATE * fade_seconds)
    if fade * 2 >= signal.size:
        return signal
    head = signal[:fade].copy()
    tail = signal[-fade:].copy()
    ramp = np.linspace(0.0, 1.0, fade)
    merged = tail * (1.0 - ramp) + head * ramp
    out = signal[:-fade].copy()
    out[:fade] = merged
    return out


def match_ends(signal: np.ndarray) -> np.ndarray:
    """Zieht eine minimale Rampe ab, damit Ende und Anfang exakt zusammenfallen."""
    if signal.size < 2:
        return signal
    delta = float(signal[-1] - signal[0])
    if abs(delta) < 1e-6:
        return signal
    return signal - np.linspace(0.0, delta, signal.size)


def normalize(signal: np.ndarray, peak: float = 0.82) -> np.ndarray:
    highest = float(np.max(np.abs(signal))) if signal.size else 0.0
    if highest < 1e-9:
        return signal
    return signal * (peak / highest)


def rms_normalize(signal: np.ndarray, target_rms: float = 0.16, ceiling: float = 0.86) -> np.ndarray:
    """Gleicht die empfundene Lautheit an, damit Raumwechsel nicht springen."""
    current = float(np.sqrt(np.mean(signal**2))) if signal.size else 0.0
    if current < 1e-9:
        return signal
    scaled = signal * (target_rms / current)
    highest = float(np.max(np.abs(scaled)))
    if highest > ceiling:
        # Weich begrenzen statt herunterskalieren: sonst zieht ein einzelnes
        # Knarzen die Lautheit des ganzen Raums nach unten.
        scaled = np.tanh(scaled / ceiling) * ceiling
    return scaled


def soft_clip(signal: np.ndarray) -> np.ndarray:
    return np.tanh(signal * 1.15) * 0.92


# ---------------------------------------------------------------- Räume


def ambience_krankenstation() -> np.ndarray:
    t = timeline(LOOP_SECONDS)
    n = t.size
    bed = lowpass_fast(noise(n), 180.0) * 0.55
    hum = (sine(t, 50.0) * 0.28 + sine(t, 100.0) * 0.12 + sine(t, 150.5) * 0.05)
    hum *= 0.85 + 0.15 * loop_lfo(t, 2)
    # Defekte Leuchtstoffröhre: schmalbandiges Zirpen, das unregelmäßig einsetzt.
    flicker_gate = np.clip(loop_lfo(t, 7, 0.6) * 3.0, 0.0, 1.0) * np.clip(loop_lfo(t, 23, 1.1) * 2.0, 0.0, 1.0)
    flicker = bandpass(noise(n), 2100.0, 5200.0) * flicker_gate * 0.10
    drip = scatter(n, lambda: bandpass(noise(1800), 900.0, 3600.0) * envelope(1800, 0.0008, 0.05), 9, 0.30)
    monitor = np.zeros(n)
    beat = int(RATE * 2.5)
    tone = sine(timeline(0.09), 1180.0) * envelope(int(RATE * 0.09), 0.004, 0.03)
    for index in range(int(LOOP_SECONDS / 2.5)):
        place(monitor, tone * 0.055, index * beat)
    return soft_clip(bed * 0.5 + hum + flicker + drip + monitor)


def ambience_diagnostiklabor() -> np.ndarray:
    t = timeline(LOOP_SECONDS)
    n = t.size
    bed = lowpass_fast(noise(n), 320.0) * 0.42
    fans = bandpass(noise(n), 260.0, 1500.0) * (0.10 + 0.03 * loop_lfo(t, 3))
    hum = sine(t, 62.0) * 0.20 + sine(t, 124.0) * 0.08
    relays = np.zeros(n)
    tick = bandpass(noise(700), 1400.0, 6000.0) * envelope(700, 0.0004, 0.014)
    for position in impulses(n, 26, 0.4).nonzero()[0]:
        place(relays, tick * RNG.uniform(0.18, 0.42), int(position))
    sweep = sine(t, 220.0 + 18.0 * loop_lfo(t, 1)) * 0.035 * np.clip(loop_lfo(t, 5, 0.4), 0.0, 1.0)
    return soft_clip(bed + fans + hum + relays + sweep)


def ambience_sicherheitsrotunde() -> np.ndarray:
    t = timeline(LOOP_SECONDS)
    n = t.size
    drone = (sine(t, 38.0) * 0.34 + sine(t, 57.0) * 0.16 + sine(t, 76.5) * 0.07)
    drone *= 0.8 + 0.2 * loop_lfo(t, 1)
    bed = lowpass_fast(noise(n), 140.0) * 0.5
    # Langsam kreisender Ton, wie eine rotierende Anzeige.
    rotor = sine(t, 190.0) * (0.5 + 0.5 * loop_lfo(t, 4)) * 0.055
    alarm_gate = np.clip(loop_lfo(t, 2, 1.9) * 4.0 - 2.6, 0.0, 1.0)
    alarm = sine(t, 620.0) * alarm_gate * 0.045
    return soft_clip(drone + bed * 0.6 + rotor + alarm)


def ambience_wartungsgalerie() -> np.ndarray:
    t = timeline(LOOP_SECONDS)
    n = t.size
    rumble = lowpass_fast(noise(n), 95.0) * 1.0
    rumble *= 0.75 + 0.25 * loop_lfo(t, 3, 0.3)
    airflow = bandpass(noise(n), 400.0, 3400.0) * 0.085
    creaks = scatter(
        n,
        lambda: bandpass(noise(int(RATE * 0.5)), 160.0, 900.0)
        * envelope(int(RATE * 0.5), 0.06, 0.16),
        7,
        0.24,
    )
    clang = scatter(
        n,
        lambda: bandpass(noise(int(RATE * 0.8)), 700.0, 4200.0)
        * envelope(int(RATE * 0.8), 0.001, 0.22),
        3,
        0.22,
    )
    return soft_clip(rumble * 0.55 + airflow + creaks + clang)


def ambience_quarantaene() -> np.ndarray:
    t = timeline(LOOP_SECONDS)
    n = t.size
    sterile = bandpass(noise(n), 220.0, 2600.0) * (0.11 + 0.03 * loop_lfo(t, 2, 0.8))
    glass = sine(t, 293.0) * 0.045 + sine(t, 441.0) * 0.022
    glass *= 0.6 + 0.4 * loop_lfo(t, 1, 0.2)
    hvac = lowpass_fast(noise(n), 200.0) * 0.36
    pressure = scatter(
        n,
        lambda: bandpass(noise(int(RATE * 1.1)), 300.0, 2200.0)
        * envelope(int(RATE * 1.1), 0.18, 0.35),
        4,
        0.22,
    )
    return soft_clip(sterile + glass + hvac + pressure)


def ambience_kaltarchiv() -> np.ndarray:
    t = timeline(LOOP_SECONDS)
    n = t.size
    cold = lowpass_fast(noise(n), 260.0) * 0.44
    compressor = sine(t, 44.0) * 0.24 * (0.7 + 0.3 * loop_lfo(t, 2, 1.4))
    clock = np.zeros(n)
    tick = bandpass(noise(520), 2200.0, 7000.0) * envelope(520, 0.0003, 0.010)
    for index in range(int(LOOP_SECONDS)):
        place(clock, tick * 0.30, int(index * RATE))
        place(clock, tick * 0.16, int((index + 0.5) * RATE))
    frost = bandpass(noise(n), 4200.0, 11000.0) * 0.028
    return soft_clip(cold + compressor + clock + frost)


def ambience_relaiskern() -> np.ndarray:
    t = timeline(LOOP_SECONDS)
    n = t.size
    sub = sine(t, 31.0) * 0.42 + sine(t, 46.5) * 0.15
    sub *= 0.82 + 0.18 * loop_lfo(t, 1)
    bed = lowpass_fast(noise(n), 130.0) * 0.5
    rain = bandpass(noise(n), 1800.0, 9000.0) * (0.055 + 0.015 * loop_lfo(t, 3, 0.7))
    # Siebzehn ruhige Knotenimpulse und ein abweichender – wie im Raum selbst.
    nodes = np.zeros(n)
    pulse = sine(timeline(0.16), 780.0) * envelope(int(RATE * 0.16), 0.006, 0.05)
    for index in range(17):
        place(nodes, pulse * 0.045, int(index * (n / 17.0)))
    odd = sine(timeline(0.22), 410.0) * envelope(int(RATE * 0.22), 0.01, 0.09)
    place(nodes, odd * 0.09, int(n * 0.63))
    return soft_clip(sub + bed * 0.55 + rain + nodes)


AMBIENCES = {
    "krankenstation": ambience_krankenstation,
    "diagnostiklabor": ambience_diagnostiklabor,
    "sicherheitsrotunde": ambience_sicherheitsrotunde,
    "wartungsgalerie": ambience_wartungsgalerie,
    "quarantaene": ambience_quarantaene,
    "kaltarchiv": ambience_kaltarchiv,
    "relaiskern": ambience_relaiskern,
}


# ---------------------------------------------------------------- Effekte


def sfx_item_pickup() -> np.ndarray:
    t = timeline(0.30)
    n = t.size
    body = bandpass(noise(n), 900.0, 5200.0) * envelope(n, 0.001, 0.045)
    ring = sine(t, 880.0) * envelope(n, 0.004, 0.10) * 0.5
    ring += sine(t, 1320.0) * envelope(n, 0.004, 0.06) * 0.25
    return normalize(body * 0.8 + ring, 0.75)


def sfx_device_use() -> np.ndarray:
    t = timeline(0.55)
    n = t.size
    clunk = lowpass_fast(noise(n), 700.0) * envelope(n, 0.002, 0.06)
    servo = sine(t, 130.0 + 90.0 * np.linspace(0.0, 1.0, n)) * envelope(n, 0.02, 0.20) * 0.5
    confirm = sine(t, 1560.0) * envelope(n, 0.004, 0.05) * 0.22
    return normalize(clunk + servo + np.roll(confirm, int(RATE * 0.22)), 0.78)


def sfx_comm_open() -> np.ndarray:
    t = timeline(0.7)
    n = t.size
    carrier = bandpass(noise(n), 700.0, 3200.0) * envelope(n, 0.03, 0.22) * 0.55
    beep = sine(t, 990.0) * envelope(n, 0.003, 0.04) * 0.4
    beep2 = np.roll(sine(t, 1320.0) * envelope(n, 0.003, 0.04) * 0.35, int(RATE * 0.12))
    return normalize(carrier + beep + beep2, 0.72)


def sfx_door_move() -> np.ndarray:
    t = timeline(1.25)
    n = t.size
    slide = bandpass(noise(n), 180.0, 1600.0) * envelope(n, 0.12, 0.55) * 0.9
    rail = sine(t, 74.0) * envelope(n, 0.08, 0.42) * 0.35
    latch = np.roll(
        bandpass(noise(n), 900.0, 4800.0) * envelope(n, 0.001, 0.05) * 0.5,
        int(RATE * 0.95),
    )
    return normalize(slide + rail + latch, 0.74)


def sfx_inspect() -> np.ndarray:
    t = timeline(0.32)
    n = t.size
    sweep = sine(t, 420.0 + 260.0 * np.linspace(0.0, 1.0, n)) * envelope(n, 0.01, 0.09) * 0.5
    air = bandpass(noise(n), 1500.0, 7000.0) * envelope(n, 0.01, 0.06) * 0.25
    return normalize(sweep + air, 0.6)


def sfx_ui_click() -> np.ndarray:
    n = int(RATE * 0.10)
    body = bandpass(noise(n), 1400.0, 6500.0) * envelope(n, 0.0004, 0.016)
    return normalize(body, 0.55)


def sfx_ui_confirm() -> np.ndarray:
    t = timeline(0.36)
    n = t.size
    first = sine(t, 660.0) * envelope(n, 0.004, 0.06) * 0.5
    second = np.roll(sine(t, 990.0) * envelope(n, 0.004, 0.08) * 0.45, int(RATE * 0.10))
    return normalize(first + second, 0.6)


def sfx_voice_listen_start() -> np.ndarray:
    t = timeline(0.26)
    n = t.size
    tone = sine(t, 520.0 + 340.0 * np.linspace(0.0, 1.0, n)) * envelope(n, 0.006, 0.07)
    return normalize(tone, 0.5)


def sfx_voice_listen_stop() -> np.ndarray:
    t = timeline(0.26)
    n = t.size
    tone = sine(t, 860.0 - 340.0 * np.linspace(0.0, 1.0, n)) * envelope(n, 0.006, 0.07)
    return normalize(tone, 0.45)


def sfx_voice_fail() -> np.ndarray:
    t = timeline(0.40)
    n = t.size
    tone = sine(t, 300.0) * envelope(n, 0.008, 0.10) * 0.5
    tone += sine(t, 224.0) * envelope(n, 0.02, 0.12) * 0.4
    return normalize(tone, 0.45)


def sfx_event_sting() -> np.ndarray:
    t = timeline(1.6)
    n = t.size
    swell = lowpass_fast(noise(n), 220.0) * envelope(n, 0.35, 0.55) * 1.2
    drop = sine(t, 58.0) * envelope(n, 0.02, 0.7) * 0.5
    shimmer = bandpass(noise(n), 3000.0, 9000.0) * envelope(n, 0.25, 0.30) * 0.18
    return normalize(swell + drop + shimmer, 0.7)


EFFECTS = {
    "item_pickup": sfx_item_pickup,
    "device_use": sfx_device_use,
    "comm_open": sfx_comm_open,
    "door_move": sfx_door_move,
    "inspect": sfx_inspect,
    "ui_click": sfx_ui_click,
    "ui_confirm": sfx_ui_confirm,
    "voice_listen_start": sfx_voice_listen_start,
    "voice_listen_stop": sfx_voice_listen_stop,
    "voice_fail": sfx_voice_fail,
    "event_sting": sfx_event_sting,
}


# ---------------------------------------------------------------- Ausgabe


def write_wav(path: Path, signal: np.ndarray) -> None:
    data = np.clip(signal, -1.0, 1.0)
    pcm = (data * 32767.0).astype("<i2")
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(RATE)
        handle.writeframes(pcm.tobytes())


def to_ogg(wav_path: Path, ogg_path: Path, quality: str) -> None:
    ogg_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", str(wav_path),
            "-c:a", "libvorbis", "-q:a", quality, "-ac", "1",
            str(ogg_path),
        ],
        check=True,
    )
    wav_path.unlink(missing_ok=True)


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    ambience_dir = root / "assets" / "audio" / "ambience"
    sfx_dir = root / "assets" / "audio" / "sfx"
    temp_dir = root / "assets" / "audio" / ".tmp"

    produced = 0
    for name, maker in AMBIENCES.items():
        signal = rms_normalize(match_ends(seamless(maker(), 4.0)))
        wav = temp_dir / f"{name}.wav"
        write_wav(wav, signal)
        to_ogg(wav, ambience_dir / f"{name}.ogg", "2")
        produced += 1
        print(f"  Atmosphäre  {name}")

    for name, maker in EFFECTS.items():
        signal = maker()
        wav = temp_dir / f"{name}.wav"
        write_wav(wav, signal)
        to_ogg(wav, sfx_dir / f"{name}.ogg", "4")
        produced += 1
        print(f"  Effekt      {name}")

    if temp_dir.exists() and not any(temp_dir.iterdir()):
        temp_dir.rmdir()
    print(f"\n{produced} Klangdateien erzeugt in {ambience_dir.parent}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
