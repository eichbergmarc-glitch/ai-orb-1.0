"""Spielt die weiblichen Supertonic-Stimmen F1 bis F5 nacheinander vor.

Aufruf: STIMMEN-VORHOEREN.bat (oder runtime\\python\\python.exe stimmen_vorhoeren.py)

Das Skript benutzt dieselben Modelldateien und denselben Aufruf wie die
Sprachausgabe des Orb (backend/tts/supertonic_engine.py). Was hier klingt,
klingt im Orb genauso. Gewuenscht wird mit der Stimme gewaehlt: in
config.yaml unter voice.output.supertonic.voice den Namen eintragen.
"""

from __future__ import annotations

import sys
import time
import wave
from pathlib import Path

WURZEL = Path(__file__).resolve().parent
sys.path.insert(0, str(WURZEL))

from backend.utils.paths import get_models_dir  # noqa: E402

STIMMEN = ["F1", "F2", "F3", "F4", "F5"]
TEXT = (
    "Hallo, ich bin dein persönlicher Assistent. Schön, dass du da bist. "
    "Wie kann ich dir heute helfen?"
)
STUFEN = 8  # fuer das Vorhoeren die hoehere Qualitaet; im Orb gilt 'steps' aus der Config
AUSGABE = WURZEL / "stimmen-vorschau"

BENOETIGT = [
    "onnx/duration_predictor.onnx",
    "onnx/text_encoder.onnx",
    "onnx/vector_estimator.onnx",
    "onnx/vocoder.onnx",
    "onnx/tts.json",
    "onnx/unicode_indexer.json",
]


def fehlend(ordner: Path) -> list[str]:
    liste = [r for r in BENOETIGT if not (ordner / r).is_file()]
    liste += [
        f"voice_styles/{name}.json"
        for name in STIMMEN
        if not (ordner / "voice_styles" / f"{name}.json").is_file()
    ]
    return liste


def main() -> int:
    try:
        from supertonic import TTS
    except ImportError:
        print("Das Paket 'supertonic' ist nicht installiert. Installieren mit:")
        print(r'  runtime\python\python.exe -m pip install supertonic==1.3.1')
        return 1

    modelle = get_models_dir() / "supertonic-3"
    modelle.mkdir(parents=True, exist_ok=True)
    print(f"Modellordner: {modelle}")

    luecken = fehlend(modelle)
    if luecken:
        print("Es fehlen Dateien:")
        for eintrag in luecken:
            print("  -", eintrag)
        print("Versuche, sie herunterzuladen (Internetverbindung noetig)...")
        try:
            TTS(model="supertonic-3", model_dir=modelle, auto_download=True)
        except Exception as fehler:  # noqa: BLE001
            print(f"Der Download ist gescheitert: {fehler}")
        luecken = fehlend(modelle)
        if luecken:
            print("Noch immer fehlen:", ", ".join(luecken))
            print("Stimmen ohne Datei werden uebersprungen.")

    modell = TTS(model="supertonic-3", model_dir=modelle, auto_download=False)
    AUSGABE.mkdir(exist_ok=True)

    try:
        import winsound
    except ImportError:
        winsound = None

    gehoert = 0
    for name in STIMMEN:
        if not (modelle / "voice_styles" / f"{name}.json").is_file():
            print(f"{name}: Stimmdatei fehlt, uebersprungen.")
            continue
        stil = modell.get_voice_style(name)
        start = time.perf_counter()
        wellenform, _ = modell.synthesize(
            TEXT, voice_style=stil, total_steps=STUFEN, speed=1.0, lang="de"
        )
        dauer = time.perf_counter() - start

        import numpy as np

        pcm = (
            np.asarray(wellenform, dtype=np.float32).reshape(-1).clip(-1.0, 1.0)
            * 32767.0
        ).astype("<i2")
        datei = AUSGABE / f"{name}.wav"
        with wave.open(str(datei), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(44100)
            w.writeframes(pcm.tobytes())

        sekunden = len(pcm) / 44100
        print(f"{name}: erzeugt in {dauer:.1f} s fuer {sekunden:.1f} s Audio "
              f"(Echtzeitfaktor {dauer / sekunden:.2f}) -> {datei.name}")
        if winsound is not None:
            print(f"   Spiele {name}...")
            winsound.PlaySound(str(datei), winsound.SND_FILENAME)
        gehoert += 1

    if not gehoert:
        print("Keine weibliche Stimme verfuegbar.")
        return 2
    print()
    print("Fertig. Die Dateien liegen in:", AUSGABE)
    print("Die beste Stimme in config.yaml eintragen:")
    print("  voice.output.supertonic.voice: F1   (oder F2 ... F5)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
