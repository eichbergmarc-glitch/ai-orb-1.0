#!/usr/bin/env python3
"""Rendert die Sprachzeilen von NULLPROTOKOLL mit XTTS-v2 vor.

XTTS-v2 klingt deutlich natuerlicher als Piper und kann eine Stimme aus einer
kurzen Sprachprobe klonen. Der Lauf ist lang, deshalb ist er wiederaufnehmbar:
bereits gerenderte Zeilen werden uebersprungen, ein Abbruch kostet also nichts.

    python tools/render_voice_xtts.py                  alles rendern
    python tools/render_voice_xtts.py --limit 10       kurze Hoerprobe
    python tools/render_voice_xtts.py --only juna      nur eine Rolle
    python tools/render_voice_xtts.py --list-speakers  mitgelieferte Stimmen zeigen

Welche Stimme welche Rolle spricht, steht in tools/voice_config.json.

Rechtliches: XTTS-v2 steht unter der Coqui Public Model License und darf nur
nicht-kommerziell genutzt werden. Klone ausschliesslich Stimmen, die dir gehoeren
oder fuer die dir eine Erlaubnis vorliegt.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from render_voice import collect  # noqa: E402  gemeinsame Zeilenerfassung

MODEL_NAME = "tts_models/multilingual/multi-dataset/xtts_v2"
MAX_CHARS = 220


def load_config(project: Path, path: str | None) -> dict:
    config_path = Path(path) if path else project / "tools" / "voice_config.json"
    if not config_path.exists():
        raise SystemExit(f"Konfiguration fehlt: {config_path}")
    with config_path.open(encoding="utf-8") as handle:
        return json.load(handle)


def split_text(text: str) -> list[str]:
    """Teilt zu lange Zeilen an Satzgrenzen.

    XTTS erzeugt bei sehr langen Eingaben Aussetzer und verschluckt Woerter.
    coqui-tts teilt selbst, aber nicht immer zuverlaessig fuer Deutsch, deshalb
    hier eine ruhige eigene Aufteilung entlang der Satzzeichen.
    """
    text = " ".join(text.split())
    if len(text) <= MAX_CHARS:
        return [text]

    pieces: list[str] = []
    current = ""
    token = ""
    for character in text:
        token += character
        if character in ".!?:;":
            if len(current) + len(token) <= MAX_CHARS or not current:
                current += token
            else:
                pieces.append(current.strip())
                current = token
            token = ""
    current += token
    if current.strip():
        pieces.append(current.strip())

    # Falls ein einzelner Satz immer noch zu lang ist, an Kommas nachteilen.
    result: list[str] = []
    for piece in pieces:
        while len(piece) > MAX_CHARS:
            cut = piece.rfind(",", 0, MAX_CHARS)
            if cut < 60:
                cut = piece.rfind(" ", 0, MAX_CHARS)
            if cut < 40:
                cut = MAX_CHARS
            result.append(piece[:cut].strip())
            piece = piece[cut:].strip(" ,")
        if piece:
            result.append(piece)
    return [p for p in result if p]


def concat_wavs(parts: list[Path], target: Path, ffmpeg: str | None, gap: float = 0.22) -> None:
    """Fuegt Teilstuecke mit kurzer Atempause zusammen."""
    if len(parts) == 1:
        shutil.move(str(parts[0]), str(target))
        return
    if ffmpeg is None:
        shutil.move(str(parts[0]), str(target))
        return
    listing = target.with_suffix(".txt")
    silence = target.with_name(target.stem + "_pause.wav")
    subprocess.run(
        [ffmpeg, "-y", "-loglevel", "error", "-f", "lavfi",
         "-i", f"anullsrc=r=24000:cl=mono:d={gap}", str(silence)],
        check=True,
    )
    with listing.open("w", encoding="utf-8") as handle:
        for index, part in enumerate(parts):
            handle.write(f"file '{part.as_posix()}'\n")
            if index < len(parts) - 1:
                handle.write(f"file '{silence.as_posix()}'\n")
    subprocess.run(
        [ffmpeg, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
         "-i", str(listing), "-c", "copy", str(target)],
        check=True,
    )
    listing.unlink(missing_ok=True)
    silence.unlink(missing_ok=True)
    for part in parts:
        part.unlink(missing_ok=True)


def encode(ffmpeg: str | None, wav: Path, ogg: Path) -> str:
    ogg.parent.mkdir(parents=True, exist_ok=True)
    if ffmpeg is None:
        shutil.move(str(wav), str(ogg.with_suffix(".wav")))
        return "wav"
    subprocess.run(
        [ffmpeg, "-y", "-loglevel", "error", "-i", str(wav),
         "-c:a", "libvorbis", "-q:a", "1", "-ac", "1", "-ar", "24000", str(ogg)],
        check=True,
    )
    wav.unlink(missing_ok=True)
    return "ogg"


def human_time(seconds: float) -> str:
    seconds = int(max(seconds, 0))
    if seconds < 90:
        return f"{seconds}s"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 90:
        return f"{minutes}m {seconds:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m"


def main() -> int:
    parser = argparse.ArgumentParser(description="Sprachzeilen mit XTTS-v2 vorrendern")
    parser.add_argument("--project", default=".", help="Projektordner")
    parser.add_argument("--config", default=None, help="Abweichende voice_config.json")
    parser.add_argument("--ffmpeg", default=None, help="Pfad zu ffmpeg (sonst PATH)")
    parser.add_argument("--only", default="", help="Nur diese Rolle rendern")
    parser.add_argument("--limit", type=int, default=0, help="Nur die ersten N Zeilen je Rolle")
    parser.add_argument("--force", action="store_true", help="Vorhandene Dateien neu rendern")
    parser.add_argument("--cpu", action="store_true", help="Grafikkarte nicht verwenden")
    parser.add_argument("--list-speakers", action="store_true", help="Mitgelieferte Stimmen auflisten")
    arguments = parser.parse_args()

    project = Path(arguments.project).resolve()
    ffmpeg = arguments.ffmpeg or shutil.which("ffmpeg")
    if ffmpeg is None:
        print("Warnung: ffmpeg nicht gefunden - es werden WAV-Dateien geschrieben.")

    # Die Lizenzzustimmung muss gesetzt sein, sonst fragt die Bibliothek
    # interaktiv nach und blockiert einen unbeaufsichtigten Lauf.
    os.environ.setdefault("COQUI_TOS_AGREED", "1")

    try:
        import torch
        from TTS.api import TTS
    except ImportError as error:
        message = str(error)
        print("XTTS konnte nicht geladen werden:", message)
        if "isin_mps_friendly" in message or "transformers" in message:
            # coqui-tts fordert transformers ohne Obergrenze; ab Version 5 fehlen
            # interne Funktionen, die es noch benutzt.
            print()
            print("Das ist ein Versionskonflikt, keine fehlende Installation.")
            print("Behebung im selben Python:")
            print('    python -m pip install "transformers>=4.57,<5"')
        else:
            print("Einrichten mit:  .\\STIMMEN_EINRICHTEN.bat")
        return 2

    use_gpu = torch.cuda.is_available() and not arguments.cpu
    device = "cuda" if use_gpu else "cpu"
    print(f"Modell wird geladen ({device}) - beim ersten Mal werden ~1,8 GB heruntergeladen.")
    started = time.time()
    tts = TTS(MODEL_NAME).to(device)
    print(f"Modell bereit nach {human_time(time.time() - started)}.")

    available = list(getattr(tts, "speakers", []) or [])
    if arguments.list_speakers:
        print(f"\n{len(available)} mitgelieferte Stimmen:")
        for name in available:
            print("  " + str(name))
        return 0

    config = load_config(project, arguments.config)
    language = str(config.get("sprache", "de"))
    roles = config.get("rollen", {})

    lines = collect(project)
    if not lines:
        print("Keine sprechbaren Zeilen gefunden.")
        return 1

    jobs: dict[str, list[tuple[str, str]]] = {role: [] for role in roles}
    for key, entry in lines.items():
        for role in entry["roles"]:
            if role in jobs:
                jobs[role].append((key, entry["text"]))

    out_dir = project / "assets" / "voice"
    index_path = out_dir / "index.json"
    index: dict[str, dict] = {}
    if index_path.exists() and not arguments.force:
        try:
            with index_path.open(encoding="utf-8") as handle:
                index = json.load(handle).get("lines", {})
        except (OSError, json.JSONDecodeError):
            index = {}
    for key, entry in lines.items():
        index.setdefault(key, {"text": entry["text"], "roles": {}})
        index[key]["text"] = entry["text"]

    temp_dir = project / "assets" / "voice" / ".tmp"
    temp_dir.mkdir(parents=True, exist_ok=True)

    total_pending = 0
    plan: list[tuple[str, dict, list[tuple[str, str]]]] = []
    for role, settings in roles.items():
        if arguments.only and arguments.only != role:
            continue
        role_jobs = jobs.get(role, [])
        if arguments.limit > 0:
            role_jobs = role_jobs[: arguments.limit]
        role_dir = out_dir / role
        pending = []
        for key, text in role_jobs:
            ogg = role_dir / f"{key}.ogg"
            wav = role_dir / f"{key}.wav"
            if not arguments.force and (ogg.exists() or wav.exists()):
                index[key]["roles"][role] = f"{role}/{ogg.name if ogg.exists() else wav.name}"
                continue
            pending.append((key, text))
        plan.append((role, settings, pending))
        total_pending += len(pending)

    print(f"\n{len(lines)} Zeilen insgesamt, {total_pending} noch zu rendern.\n")
    if total_pending == 0:
        print("Nichts zu tun. Mit --force wird alles neu erzeugt.")

    done = 0
    run_started = time.time()
    for role, settings, pending in plan:
        if not pending:
            continue
        role_dir = out_dir / role
        role_dir.mkdir(parents=True, exist_ok=True)

        reference = settings.get("reference", "")
        reference_path = (project / reference) if reference else None
        speaker_wav = None
        speaker_name = None
        if reference_path is not None and reference_path.exists():
            speaker_wav = str(reference_path)
            source = f"geklont aus {reference_path.name}"
        else:
            speaker_name = settings.get("speaker")
            if available and speaker_name not in available:
                fallback = available[0]
                print(f"  Hinweis: Stimme '{speaker_name}' gibt es nicht, nehme '{fallback}'.")
                speaker_name = fallback
            source = f"Studiostimme {speaker_name}"
        speed = float(settings.get("speed", 1.0))

        print(f"== {role}: {len(pending)} Zeilen, {source}")
        for key, text in pending:
            chunks = split_text(text)
            parts: list[Path] = []
            try:
                for position, chunk in enumerate(chunks):
                    part = temp_dir / f"{role}_{key}_{position}.wav"
                    tts.tts_to_file(
                        text=chunk,
                        file_path=str(part),
                        language=language,
                        speaker_wav=speaker_wav,
                        speaker=speaker_name,
                        speed=speed,
                        split_sentences=False,
                    )
                    parts.append(part)
                merged = temp_dir / f"{role}_{key}.wav"
                concat_wavs(parts, merged, ffmpeg)
                suffix = encode(ffmpeg, merged, role_dir / f"{key}.ogg")
                index[key]["roles"][role] = f"{role}/{key}.{suffix}"
            except Exception as error:  # noqa: BLE001  ein Ausfall darf den Lauf nicht beenden
                print(f"  Fehler bei {key}: {error}")
                for part in parts:
                    part.unlink(missing_ok=True)
                continue

            done += 1
            elapsed = time.time() - run_started
            rate = elapsed / max(done, 1)
            remaining = (total_pending - done) * rate
            print(
                f"  [{done:4d}/{total_pending}] {human_time(elapsed)} verstrichen, "
                f"noch etwa {human_time(remaining)}  {text[:52]}…"
            )
            # Nach jeder Zeile sichern, damit ein Abbruch nichts kostet.
            _write_index(index_path, config, index)

    _write_index(index_path, config, index)
    if temp_dir.exists() and not any(temp_dir.iterdir()):
        temp_dir.rmdir()
    print(f"\nFertig. {done} neue Sprachdateien in {out_dir}")
    return 0


def _write_index(index_path: Path, config: dict, index: dict) -> None:
    index_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "erzeugt_von": "tools/render_voice_xtts.py",
        "modell": MODEL_NAME,
        "rollen": {role: settings.get("speaker", "") for role, settings in config.get("rollen", {}).items()},
        "lines": index,
    }
    index_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
