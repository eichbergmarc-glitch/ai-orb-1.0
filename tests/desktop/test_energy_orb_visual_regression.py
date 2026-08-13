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
MAIN = get_project_root() / "desktop" / "renderer" / "main.ts"
HTML = get_project_root() / "desktop" / "renderer" / "index.html"
PRELOAD = get_project_root() / "desktop" / "electron" / "preload.ts"
ELECTRON = get_project_root() / "desktop" / "electron" / "main.ts"
ANIMATION = get_project_root() / "desktop" / "renderer" / "animation.ts"
RENDERER = get_project_root() / "desktop" / "renderer" / "renderer.ts"


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
    assert _state("listening")["eyeOpen"] < _state("idle")["eyeOpen"]
    assert _state("listening")["eyeSquint"] >= 0.7
    assert _state("listening")["eyeAngry"] >= 0.7
    assert _state("executing")["eyeBright"] < 0.25
    assert _state("offline")["eyeBright"] < 0.5
    assert _state("idle")["eyeCurious"] > 0.0
    assert _state("listening")["eyeSurprised"] == 0.0
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


def test_blick_ist_relativ_zum_orb_und_deutlich_sichtbar():
    shader = ORB.read_text(encoding="utf-8")
    main = MAIN.read_text(encoding="utf-8")
    assert "p -= uLook * 0.045" in shader
    assert "delta * 7.0" in shader
    assert "orbHitRadiusPixels" in main
    assert "renderedOrbOffset" in main
    assert "window.innerWidth / 2)" not in main


def test_energieringe_bleiben_auch_im_leerlauf_und_bei_zustandswechseln_fluessig():
    animation = ANIMATION.read_text(encoding="utf-8")
    config = (get_project_root() / "config.yaml").read_text(encoding="utf-8")
    main = MAIN.read_text(encoding="utf-8")
    orb = ORB.read_text(encoding="utf-8")
    renderer = RENDERER.read_text(encoding="utf-8")

    assert "idleFps: 60" in animation
    assert "targetFps < 55" in animation
    assert re.search(r"^\s+idle_fps:\s*60\s*$", config, re.MULTILINE)
    assert "orb.update(elapsed, delta, appearance)" in main
    assert "orb.update(scaledElapsed" not in main
    assert "this.ringPhase += delta" in orb
    assert "uTime.value = this.ringPhase" in orb
    assert "rotation.y = this.ringPhase" in orb
    assert "Math.min(window.devicePixelRatio, this.maxPixelRatio)" in renderer


def test_backend_steuert_alle_beschriebenen_augenzustaende_an():
    text = MAIN.read_text(encoding="utf-8")
    assert 'event.event === "orb.state.changed"' in text
    assert 'event.event === "orb.state.request"' in text
    assert 'event.event === "voice.state.changed"' in text
    assert 'event.event === "voice.response.finished"' in text
    assert '"task.started": "executing"' in text
    assert 'event.event === "task.finished"' in text
    assert 'ok === false ? "error" : "success"' in text
    assert 'event.event === "security.consent.resolved"' in text
    assert 'granted === false ? "warning" : "idle"' in text
    assert '"system.warning": "warning"' in text
    assert '"system.error": "error"' in text
    assert "ORB_STATES.includes" in text
    assert '"tts.finished": "success"' not in text
    assert "}, 2600);" not in text


def test_zustandswechsel_sind_schnell_genug_fuer_kurze_werkzeuge():
    config = (get_project_root() / "config.yaml").read_text(encoding="utf-8")
    transition = float(
        re.search(r"^\s+transition_seconds:\s*([0-9.]+)", config, re.MULTILINE).group(1)
    )
    assert 0.2 <= transition <= 0.45


def test_alle_sechs_emotionen_und_reaktionen_sind_implementiert():
    orb = ORB.read_text(encoding="utf-8")
    main = MAIN.read_text(encoding="utf-8")
    for emotion in ("friendly", "curious", "surprised", "thoughtful", "joyful", "relaxed"):
        assert emotion in orb
        assert emotion in main
    assert 'react(kind: "click" | "surprise")' in orb
    assert "Math.sin(p * Math.PI) * 0.18" in orb


def test_ringmenue_chat_automatik_und_globale_maus_sind_verdrahtet():
    html = HTML.read_text(encoding="utf-8")
    main = MAIN.read_text(encoding="utf-8")
    preload = PRELOAD.read_text(encoding="utf-8")
    electron = ELECTRON.read_text(encoding="utf-8")
    for token in ('id="orb-menu"', 'id="orb-info"', 'id="chat-panel"',
                  'id="chat-form"', 'id="chat-input"'):
        assert token in html
    assert 'id="personalization"' not in html
    assert "automaticStyles" in main and "setVisualStyle" in main
    assert "backend.ask(text)" in main and 'showChat(true)' in main
    assert "onGlobalPointer" in preload and '"pointer:global"' in preload
    assert "screen.getCursorScreenPoint" in electron and '"pointer:global"' in electron
    assert "lastMousePassthrough" in main
    assert "lastCursorX" in electron and "}, 50);" in electron
