"""Deterministischer visueller Vertrag des Energy-Orb.

GPU-Screenshots unterscheiden sich je Treiber leicht. Diese Tests sichern
deshalb die Parameter, aus denen das sichtbare Bild entsteht: Farbe, Größe,
Augenform und Zustandssymbol. Ändert sich einer davon, ist die Abweichung
explizit und reviewbar statt ein stiller visueller Rückschritt.
"""

from __future__ import annotations

import re

from backend.utils.paths import get_project_root

STATES = get_project_root() / "desktop" / "renderer" / "states.ts"
ORB = get_project_root() / "desktop" / "renderer" / "energy_orb.ts"


def _state(name: str) -> dict[str, float]:
    text = STATES.read_text(encoding="utf-8")
    start = text.index(f"    {name}: {{")
    candidates = [text.find(f"    {other}: {{", start + 1) for other in (
        "idle", "listening", "thinking", "speaking", "busy", "error",
        "sleep", "executing", "waiting", "success", "warning", "offline",
    )]
    end = min(pos for pos in candidates if pos >= 0) if any(pos >= 0 for pos in candidates) else text.index("  };", start)
    block = text[start:end]
    values: dict[str, float] = {}
    for key, raw in re.findall(r"^\s+(scale|eyeOpen|eyeHappy|eyeSquint|eyeAngry|eyeBright|eyeQuestion|eyeAlert|eyeCurious|eyeSurprised|eyeUncertain):\s*([0-9.]+)", block, re.MULTILINE):
        values[key] = float(raw)
    return values


def test_zustandsaugen_haben_eindeutige_signaturen():
    signatures = {
        name: tuple(_state(name).get(key, 0.0) for key in (
            "eyeOpen", "eyeHappy", "eyeSquint", "eyeAngry", "eyeQuestion", "eyeAlert",
            "eyeCurious", "eyeSurprised", "eyeUncertain"
        ))
        for name in ("idle", "listening", "thinking", "executing", "waiting", "success", "warning", "error", "offline")
    }
    assert len(set(signatures.values())) == len(signatures), signatures


def test_symbole_bleiben_exklusiv():
    assert _state("waiting")["eyeQuestion"] == 1.0
    assert _state("waiting")["eyeAlert"] == 0.0
    assert _state("warning")["eyeAlert"] == 1.0
    assert _state("warning")["eyeQuestion"] == 0.0


def test_emotionale_extreme_bleiben_erkennbar():
    assert _state("success")["eyeHappy"] >= 0.9
    assert _state("error")["eyeAngry"] >= 0.9
    assert _state("listening")["eyeOpen"] > _state("idle")["eyeOpen"]
    assert _state("offline")["eyeBright"] < 0.5
    assert _state("idle")["eyeCurious"] > 0.0
    assert _state("listening")["eyeSurprised"] > 0.0
    assert _state("thinking")["eyeUncertain"] > 0.0


def test_orb_bleibt_kompakt_und_zustandswechsel_sind_begrenzt():
    config = (get_project_root() / "config.yaml").read_text(encoding="utf-8")
    scale = float(re.search(r"^\s+scale:\s*([0-9.]+)", config, re.MULTILINE).group(1))
    assert 0.20 <= scale <= 0.35
    for name in ("idle", "listening", "thinking", "speaking", "executing", "success"):
        assert 0.6 <= _state(name)["scale"] <= 1.1


def test_shader_enthaelt_augen_und_beide_symbole():
    text = ORB.read_text(encoding="utf-8")
    for token in ("fragezeichen", "ausrufezeichen", "uQuestion", "uAlert", "uBlink", "uCurious", "uSurprised", "uUncertain"):
        assert token in text
