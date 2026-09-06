#!/usr/bin/env python3
"""Rendert die Sprachzeilen von NULLPROTOKOLL mit Piper vor.

Gedanken, Juna, Samir und die Funkstimme werden einmalig zu OGG-Dateien
gerendert. MIRA und die Stationsansagen bleiben bewusst ausgespart: sie werden
im Spiel live über die Sprachausgabe des Betriebssystems gesprochen, weil eine
synthetische Stimme dort erzählerisch richtig ist und weil nur diese Zeilen
Platzhalter enthalten können.

Der Schlüssel einer Zeile ist der SHA-256-Hash ihres normalisierten Textes.
Genau dieselbe Normalisierung steht in scripts/core/voice_manager.gd, damit das
Spiel eine Zeile ohne Zuordnungstabelle wiederfindet. Wird ein Text geändert,
entsteht ein neuer Schlüssel und die Zeile wird beim nächsten Lauf neu gerendert.

Aufruf (Windows, nach SETUP_SPRACHE.ps1):
    python tools\\render_voice.py --piper .tools\\speech\\piper\\piper.exe ^
                                  --voices .tools\\speech\\voices
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Rolle -> Piper-Stimme. Die Dateien liegen als <name>.onnx neben <name>.onnx.json.
VOICES = {
    "gedanke_w": "de_DE-kerstin-low",
    "gedanke_m": "de_DE-thorsten-medium",
    "juna": "de_DE-ramona-low",
    "samir": "de_DE-karlsson-low",
    "funk": "de_DE-pavoque-low",
}

THOUGHT_ROLES = ["gedanke_w", "gedanke_m"]

SPEAKER_ROLES = {
    "dr. juna falk": ["juna"],
    "samir": ["samir"],
    "unbekannte funkstimme": ["funk"],
    "mira": [],  # live gesprochen
}

TEXT_FIELDS = {"text", "description", "tagline"}
SOURCES = ["data/prologue.json", "data/dialogues.json", "data/cutscenes.json"]


def voice_key(text: str) -> str:
    """Muss zeichengleich zu NPVoiceManager.voice_key in GDScript sein."""
    normalized = text.strip()
    while "  " in normalized:
        normalized = normalized.replace("  ", " ")
    normalized = normalized.replace("\n", " ").replace("\t", " ")
    while "  " in normalized:
        normalized = normalized.replace("  ", " ")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def roles_for(speaker: str, field: str) -> list[str]:
    if field == "player_text":
        # Was die Spielfigur sagt, spricht immer ihre eigene Stimme.
        return list(THOUGHT_ROLES)
    key = speaker.strip().lower()
    if key in SPEAKER_ROLES:
        return list(SPEAKER_ROLES[key])
    if not key:
        return list(THOUGHT_ROLES)
    return list(THOUGHT_ROLES)


def collect(project: Path) -> dict[str, dict]:
    """Sammelt alle sprechbaren Zeilen als key -> {text, roles}."""
    found: dict[str, dict] = {}

    def remember(text: str, speaker: str, field: str) -> None:
        if not text or not text.strip():
            return
        if "{" in text:
            # Platzhalter werden zur Laufzeit ersetzt; diese Zeilen spricht das
            # Betriebssystem live.
            return
        roles = roles_for(speaker, field)
        if not roles:
            return
        key = voice_key(text)
        entry = found.setdefault(key, {"text": text.strip(), "roles": []})
        for role in roles:
            if role not in entry["roles"]:
                entry["roles"].append(role)

    def walk(node, speaker: str) -> None:
        if isinstance(node, dict):
            own = node.get("speaker", speaker)
            current = own if isinstance(own, str) else speaker
            for key, value in node.items():
                if key in TEXT_FIELDS and isinstance(value, str):
                    remember(value, current, key)
                elif key == "player_text" and isinstance(value, str):
                    remember(value, current, "player_text")
                elif key == "consequences" and isinstance(value, list):
                    for item in value:
                        if isinstance(item, str):
                            remember(item, current, "text")
                else:
                    walk(value, current)
        elif isinstance(node, list):
            for value in node:
                walk(value, speaker)

    for relative in SOURCES:
        path = project / relative
        if not path.exists():
            print(f"  Hinweis: {relative} fehlt, wird übersprungen.")
            continue
        with path.open(encoding="utf-8") as handle:
            walk(json.load(handle), "")
    return found


def find_model(voices_dir: Path, name: str) -> Path | None:
    direct = voices_dir / f"{name}.onnx"
    if direct.exists():
        return direct
    matches = sorted(voices_dir.rglob(f"{name}.onnx"))
    return matches[0] if matches else None


def run_piper(piper: str, model: Path, jobs: list[tuple[str, Path]]) -> bool:
    """Rendert alle Zeilen einer Stimme in einem einzigen Piper-Aufruf."""
    if not jobs:
        return True
    payload = "\n".join(
        json.dumps({"text": text, "output_file": str(target)}, ensure_ascii=False)
        for text, target in jobs
    )
    command = [piper, "--model", str(model), "--json-input"]
    result = subprocess.run(
        command, input=payload, text=True, encoding="utf-8", capture_output=True
    )
    if result.returncode == 0:
        return True
    print(f"    Sammelmodus nicht verfügbar ({result.returncode}), einzeln rendern …")
    if result.stderr:
        print("    " + result.stderr.strip().splitlines()[-1])
    for text, target in jobs:
        single = subprocess.run(
            [piper, "--model", str(model), "--output_file", str(target)],
            input=text,
            text=True,
            encoding="utf-8",
            capture_output=True,
        )
        if single.returncode != 0:
            print(f"    Fehler bei: {text[:60]}…")
            return False
    return True


def encode(ffmpeg: str | None, wav: Path, ogg: Path) -> bool:
    ogg.parent.mkdir(parents=True, exist_ok=True)
    if ffmpeg is None:
        # Ohne ffmpeg bleibt die WAV-Datei liegen; Godot kann sie ebenfalls laden.
        shutil.move(str(wav), str(ogg.with_suffix(".wav")))
        return False
    subprocess.run(
        [ffmpeg, "-y", "-loglevel", "error", "-i", str(wav),
         "-c:a", "libvorbis", "-q:a", "0", "-ac", "1", str(ogg)],
        check=True,
    )
    wav.unlink(missing_ok=True)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Sprachzeilen vorrendern")
    parser.add_argument("--project", default=".", help="Projektordner")
    parser.add_argument("--piper", required=True, help="Pfad zu piper(.exe)")
    parser.add_argument("--voices", required=True, help="Ordner mit den .onnx-Stimmen")
    parser.add_argument("--ffmpeg", default=None, help="Pfad zu ffmpeg (sonst PATH)")
    parser.add_argument("--force", action="store_true", help="Vorhandene Dateien neu rendern")
    parser.add_argument("--only", default="", help="Nur diese Rolle rendern")
    arguments = parser.parse_args()

    project = Path(arguments.project).resolve()
    voices_dir = Path(arguments.voices).resolve()
    out_dir = project / "assets" / "voice"
    ffmpeg = arguments.ffmpeg or shutil.which("ffmpeg")
    if ffmpeg is None:
        print("Warnung: ffmpeg nicht gefunden – es werden WAV-Dateien geschrieben.")

    lines = collect(project)
    if not lines:
        print("Keine sprechbaren Zeilen gefunden.")
        return 1
    print(f"{len(lines)} Zeilen gefunden.")

    by_role: dict[str, list[tuple[str, str]]] = {role: [] for role in VOICES}
    for key, entry in lines.items():
        for role in entry["roles"]:
            if role in by_role:
                by_role[role].append((key, entry["text"]))

    index: dict[str, dict] = {}
    for key, entry in lines.items():
        index[key] = {"text": entry["text"], "roles": {}}

    total_written = 0
    for role, model_name in VOICES.items():
        if arguments.only and arguments.only != role:
            continue
        jobs = by_role.get(role, [])
        if not jobs:
            continue
        model = find_model(voices_dir, model_name)
        if model is None:
            print(f"  {role}: Stimme {model_name} fehlt in {voices_dir} – übersprungen.")
            continue

        role_dir = out_dir / role
        role_dir.mkdir(parents=True, exist_ok=True)
        pending: list[tuple[str, Path]] = []
        temp_dir = Path(tempfile.mkdtemp(prefix=f"np_{role}_"))
        for key, text in jobs:
            final = role_dir / f"{key}.ogg"
            existing_wav = role_dir / f"{key}.wav"
            if not arguments.force and (final.exists() or existing_wav.exists()):
                index[key]["roles"][role] = f"{role}/{final.name if final.exists() else existing_wav.name}"
                continue
            pending.append((text, temp_dir / f"{key}.wav"))

        print(f"  {role:10s} {model_name:24s} {len(pending):4d} neu")
        if pending and not run_piper(arguments.piper, model, pending):
            print(f"  {role}: Rendern fehlgeschlagen.")
            shutil.rmtree(temp_dir, ignore_errors=True)
            continue
        for text, wav in pending:
            if not wav.exists():
                continue
            key = wav.stem
            as_ogg = encode(ffmpeg, wav, role_dir / f"{key}.ogg")
            suffix = "ogg" if as_ogg else "wav"
            index[key]["roles"][role] = f"{role}/{key}.{suffix}"
            total_written += 1
        shutil.rmtree(temp_dir, ignore_errors=True)

    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "erzeugt_von": "tools/render_voice.py",
        "stimmen": VOICES,
        "lines": index,
    }
    (out_dir / "index.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"\n{total_written} neue Sprachdateien, Index: {out_dir / 'index.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
