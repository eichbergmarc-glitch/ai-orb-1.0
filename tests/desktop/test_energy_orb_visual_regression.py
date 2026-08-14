"""Deterministischer visueller Vertrag des Energy-Orb.

GPU-Screenshots unterscheiden sich je Treiber leicht. Diese Tests sichern
deshalb die Parameter, aus denen das sichtbare Bild entsteht: Farbe, Größe,
Augenform und Zustandssymbol. Ändert sich einer davon, ist die Abweichung
explizit und reviewbar statt ein stiller visueller Rückschritt.
"""

from __future__ import annotations

import re

from PIL import Image

from backend.utils.paths import get_project_root

STATES = get_project_root() / "desktop" / "renderer" / "states.ts"
ORB = get_project_root() / "desktop" / "renderer" / "energy_orb.ts"
MAIN = get_project_root() / "desktop" / "renderer" / "main.ts"
HTML = get_project_root() / "desktop" / "renderer" / "index.html"
PRELOAD = get_project_root() / "desktop" / "electron" / "preload.ts"
ELECTRON = get_project_root() / "desktop" / "electron" / "main.ts"
ANIMATION = get_project_root() / "desktop" / "renderer" / "animation.ts"
RENDERER = get_project_root() / "desktop" / "renderer" / "renderer.ts"
INTERACTION = get_project_root() / "desktop" / "renderer" / "interaction.ts"
DESKTOP_MANAGER = get_project_root() / "desktop" / "electron" / "desktop_manager.ts"


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


def test_referenzsilhouette_hat_kleinen_kern_dichte_korona_und_fuenf_bahnen():
    text = ORB.read_text(encoding="utf-8")
    core = float(re.search(r"coreRadius:\s*([0-9.]+)", text).group(1))
    corona = float(re.search(r"coronaRadius:\s*([0-9.]+)", text).group(1))
    assert core <= 0.62
    assert corona >= 0.86
    assert len(re.findall(r"\{ a: [^\n]+ violet:", text)) == 5
    for token in ("CORONA_FRAG", "coronaMaterial", "uAccent", "uWarm", "violettesBahnlicht"):
        assert token in text


def test_referenzpalette_ist_zustandsgebunden_und_nicht_personalisiert():
    states = STATES.read_text(encoding="utf-8")
    assert "THINKING_COLOR = { core: 0x7a37ff, glow: 0xd0a0ff }" in states
    for color in ("0x35d97a", "0xffb340", "0xff4a4a", "0x91a3b8"):
        assert color in states
    orb = ORB.read_text(encoding="utf-8")
    assert "float bogen = abs(length(q) - radius)" in orb


def test_referenzkrone_besteht_aus_zehn_geflochtenen_lichtfasern():
    orb = ORB.read_text(encoding="utf-8")
    assert len(re.findall(r"\{ radius: [^\n]+ lobes:", orb)) == 10
    assert "function filamentTube(" in orb
    assert "private readonly filaments: FilamentBundle[]" in orb
    assert "this.filamentPhase += delta" in orb


def test_professormodus_hat_runde_brille_und_eigene_farbmischung():
    orb = ORB.read_text(encoding="utf-8")
    main = MAIN.read_text(encoding="utf-8")
    cognitive = (
        get_project_root() / "backend" / "cognitive" / "cognitive_core.py"
    ).read_text(encoding="utf-8")
    for token in (
        "uProfessor", "glassRight", "glassLeft", "glassBridge",
        "professorKern", "professorGlow", "professorPartikel",
    ):
        assert token in orb
    assert 'event.event !== "orb.professor.changed"' in main
    assert "setProfessorMode(active === true)" in main
    assert '"orb.professor.changed"' in cognitive


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
    assert "const delta = Math.min(rawDelta / 1000, 1 / 30)" in animation
    assert "float flare" not in orb
    assert "flicker + flare" not in orb
    assert "group.rotation.x +=" not in (
        get_project_root() / "desktop" / "renderer" / "presence.ts"
    ).read_text(encoding="utf-8")
    assert re.search(r"^\s+adaptive_quality:\s*false\s*$", config, re.MULTILINE)


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


def test_zustandswechsel_sind_weich_aber_noch_reaktionsschnell():
    config = (get_project_root() / "config.yaml").read_text(encoding="utf-8")
    transition = float(
        re.search(r"^\s+transition_seconds:\s*([0-9.]+)", config, re.MULTILINE).group(1)
    )
    assert 0.5 <= transition <= 0.8


def test_alle_sechs_emotionen_und_reaktionen_sind_implementiert():
    orb = ORB.read_text(encoding="utf-8")
    main = MAIN.read_text(encoding="utf-8")
    for emotion in ("friendly", "curious", "surprised", "thoughtful", "joyful", "relaxed"):
        assert emotion in orb
        assert emotion in main
    assert 'react(kind: "click" | "surprise")' in orb
    assert "Math.sin(p * Math.PI) * 0.18" in orb


def test_vorlagenmuster_bleiben_animiert_und_zustandsabhaengig():
    root = get_project_root()
    orb = ORB.read_text(encoding="utf-8")
    main = MAIN.read_text(encoding="utf-8")
    copy_assets = (root / "scripts" / "copy-assets.js").read_text(encoding="utf-8")
    asset_dir = root / "desktop" / "assets" / "orb" / "reference-layers"

    for name in (
        "idle-base.png", "idle-crown.png", "idle-inner-energy.png",
        "idle-orbits.png", "idle-reflection.png", "state-base-idle.png",
        "state-base-listening.png", "state-base-thinking.png",
        "state-base-executing.png", "state-base-waiting.png",
        "state-base-success.png", "state-base-warning.png",
        "state-base-error.png", "state-base-offline.png",
    ):
        assert (asset_dir / name).is_file(), name

    assert "const REFERENCE_FRAG" in orb
    assert "flow * uWarp" in orb
    assert "showReferenceState" in orb
    assert "public setState(state: OrbStateName)" in orb
    assert "energyOrb?.setState(state)" in main
    assert 'copyDirectory("desktop/assets/orb", "assets/orb")' in copy_assets
    assert 'crownIdle: "assets/orb/reference-layers/idle-base.png"' in orb
    assert "state-base-${state}.png" in orb


def test_referenzbasis_behaelt_den_dunklen_kern_aber_spart_live_augen_aus():
    asset_dir = get_project_root() / "desktop" / "assets" / "orb" / "reference-layers"
    idle = Image.open(asset_dir / "idle-base.png").convert("RGBA")
    assert idle.getpixel((200, 250))[3] > 240
    assert idle.getpixel((170, 203))[3] < 12
    assert idle.getpixel((234, 201))[3] < 12

    warning = Image.open(asset_dir / "state-base-warning.png").convert("RGBA")
    assert warning.getpixel((59, 40))[3] < 12
    assert warning.getpixel((59, 25))[3] < 20


def test_bloom_verstaerkt_live_funken_ohne_die_referenz_zu_verbrennen():
    config = (get_project_root() / "config.yaml").read_text(encoding="utf-8")
    strength = float(re.search(r"^\s+bloom_strength:\s*([0-9.]+)", config, re.MULTILINE).group(1))
    radius = float(re.search(r"^\s+bloom_radius:\s*([0-9.]+)", config, re.MULTILINE).group(1))
    threshold = float(re.search(r"^\s+bloom_threshold:\s*([0-9.]+)", config, re.MULTILINE).group(1))
    assert 0.45 <= strength <= 0.75
    assert 0.25 <= radius <= 0.42
    assert 0.35 <= threshold <= 0.55


def test_ueberraschungssprung_summiert_position_nicht_frameweise():
    orb = ORB.read_text(encoding="utf-8")
    assert "this.reactionBaseY + Math.sin(p * Math.PI) * 0.18" in orb
    assert "this.group.position.y += Math.sin(p * Math.PI)" not in orb


def test_referenzhuelle_hat_keine_zeitliche_helligkeitsmodulation():
    orb = ORB.read_text(encoding="utf-8")
    reference_shader = orb.split("const REFERENCE_FRAG", 1)[1].split("`;", 1)[0]
    assert "source.rgb * living" not in reference_shader
    assert "source.a * uOpacity * living" not in reference_shader
    assert "float darkTransmission" in reference_shader
    assert "source.a * uOpacity * darkTransmission" in reference_shader
    assert "uDarkFloor" in reference_shader
    assert "makeReferenceMaterial(0.0, 0.0, 0.30)" in orb
    assert "texture.minFilter = THREE.LinearFilter" in orb
    assert "texture.generateMipmaps = false" in orb
    assert "this.referenceOrbit.rotation.z = 0.0" in orb
    assert "float spark =" not in orb


def test_transparenter_webgl_puffer_bleibt_bis_zur_desktopkomposition_erhalten():
    renderer = (get_project_root() / "desktop" / "renderer" / "renderer.ts").read_text(
        encoding="utf-8"
    )
    assert "preserveDrawingBuffer: true" in renderer
    assert "premultipliedAlpha: true" in renderer


def test_original_orbits_sind_sichtbar_aber_gegen_ueberstrahlen_begrenzt():
    orb = ORB.read_text(encoding="utf-8")
    assert "idle: 0.62" in orb
    assert "this.referenceOrbitTarget = 0.62" in orb
    assert 'crown.target = state === "idle" ? 0.90 : 0.86' in orb
    assert "this.referenceInnerTarget = 0.28" in orb
    assert "ring.particles.visible = true" in orb


def test_synaptischer_nebel_fuellt_den_raum_zwischen_kern_und_huelle():
    orb = ORB.read_text(encoding="utf-8")
    assert "const SYNAPTIC_MIST_FRAG" in orb
    assert "synapticInnerRadius: 0.675" in orb
    assert "synapticOuterRadius: 0.785" in orb
    assert "private readonly synapticInnerMaterial" in orb
    assert "private readonly synapticOuterMaterial" in orb
    shader = orb.split("const SYNAPTIC_MIST_FRAG", 1)[1].split("`;", 1)[0]
    assert "float fibres" in shader and "float nodes" in shader
    assert "sin(uTime" not in shader
    assert "float branchA" in shader and "float branchB" in shader
    assert "float synapse" in shader
    assert "strength = min(strength, 0.38)" in shader


def test_orbitale_schweife_bleiben_raeumlich_sichtbar_aber_gedaempft():
    orb = ORB.read_text(encoding="utf-8")
    ring_shader = orb.split("const RING_FRAG", 1)[1].split("`;", 1)[0]
    assert "float orbitPhase" in ring_shader
    assert "comet * 0.26" in ring_shader
    assert "glow = min(glow, 0.16)" in ring_shader
    assert "if (glow < 0.004) discard" in ring_shader
    assert "float drift" not in ring_shader
    assert "ring.mesh.visible = visible" in orb
    assert "this.styleRingGain * 0.30" in orb
    assert "ringParticles: 12" in orb
    assert "function ellipseArcTube" in orb
    assert "ringGroup.add(...arcs)" in orb
    assert "ring.arcMaterial.opacity" in orb


def test_transferentladung_springt_von_der_huelle_in_die_atomare_bahn():
    orb = ORB.read_text(encoding="utf-8")
    shader = orb.split("const TRANSFER_ARC_FRAG", 1)[1].split("`;", 1)[0]
    assert "function transferArcTube" in orb
    assert "private readonly transferArcs" in orb
    assert "float cycle = uProgress" in shader
    assert "float head" in shader and "float tail" in shader
    assert "tailDistance * 5.5" in shader
    assert "head * 0.72 + tail * 0.40" in shader
    assert "glow = min(glow, 0.52)" in shader
    assert "this.synapsenRot" in orb and "this.synapsenOrange" in orb
    assert "this.transferWait = Math.random() < 0.16" in orb
    assert "2.4 + Math.random() * 5.8" in orb
    assert "new THREE.TubeGeometry(curve, 64, 0.015, 5, false)" in orb
    assert "chosen.duration = 1.25 + Math.random() * 0.95" in orb
    assert "chosen.group.rotation.z = Math.random() * Math.PI * 2.0" in orb


def test_aussenbahnen_haben_keine_pulsierende_grundlinie():
    orb = ORB.read_text(encoding="utf-8")
    ring_shader = orb.split("const RING_FRAG", 1)[1].split("`;", 1)[0]
    assert "0.08 +" not in ring_shader
    assert "float drift" not in ring_shader
    assert "a.pulseAmount * 0.12" in orb
    assert "a.pulseAmount * 0.07" in orb
    particle_shader = orb.split("const RING_PARTICLE_FRAG", 1)[1].split("`;", 1)[0]
    dust_shader = orb.split("const DUST_FRAG", 1)[1].split("`;", 1)[0]
    assert "shimmer" not in particle_shader
    assert "float tw" not in dust_shader


def test_bodenspiegelung_folgt_orbitfarben_und_entladungen():
    orb = ORB.read_text(encoding="utf-8")
    shader = orb.split("const GROUND_FRAG", 1)[1].split("`;", 1)[0]
    assert "uOrbitPhase" in shader and "uTransferEnergy" in shader
    assert "float orbitA" in shader and "float orbitB" in shader
    assert "float transfer" in shader
    assert "this.groundMaterial.uniforms.uOrbitPhase.value = this.ringPhase" in orb
    assert "this.groundMaterial.uniforms.uTransferEnergy.value = this.transferReflection" in orb
    assert "this.referenceReflectionTarget = 0.16" in orb


def test_zustandsfarben_faerben_kern_nebel_huelle_und_atomsegmente():
    orb = ORB.read_text(encoding="utf-8")
    assert "uDeep.value as THREE.Color" in orb
    assert "a.smokeDensity * 0.68" in orb
    assert "a.smokeDensity * 0.48" in orb
    assert "0.44 * a.lightIntensity" in orb
    assert "ring.arcMaterial.color.copy" in orb


def test_start_und_laufzeit_nutzen_dieselben_ruhigen_energiewerte():
    orb = ORB.read_text(encoding="utf-8")
    main = MAIN.read_text(encoding="utf-8")
    # applyAppearance und update duerfen die Bahnhelligkeit nicht beim
    # ersten Frame auf einen voellig anderen Faktor springen lassen.
    assert orb.count("a.ringIntensity * bright * 0.58") == 1
    assert orb.count("a.ringIntensity * this.brightFactor * ringDamp * 0.58") == 1
    assert orb.count("this.styleRingGain * 0.30") >= 2
    assert "baseBloomStrength * appearance.bloomStrength" in main


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
    assert "setChatFocus(show)" in main
    assert 'ipcRenderer.send("window:chat-focus"' in preload
    assert 'ipcMain.on("window:chat-focus"' in electron
    assert "orbWindow.setFocusable(active)" in electron
    assert "onGlobalPointer" in preload and '"pointer:global"' in preload
    assert "screen.getCursorScreenPoint" in electron and '"pointer:global"' in electron
    assert "lastMousePassthrough" in main
    assert "lastCursorX" in electron and "}, 50);" in electron


def test_automatische_position_wird_als_fensterecke_in_orbmittelpunkt_umgerechnet():
    electron = ELECTRON.read_text(encoding="utf-8")
    assert "const centerX = candidate.x + windowWidth / 2" in electron
    assert "const centerY = candidate.y + windowHeight / 2" in electron
    assert "moveOrbTo(window, centerX, centerY)" in electron
    assert 'window.on("moved"' not in electron


def test_rechtsklick_ist_entprellt_und_veraendert_keinen_sprachzustand():
    main = MAIN.read_text(encoding="utf-8")
    interaction = INTERACTION.read_text(encoding="utf-8")
    context_handler = main.split("onContextMenu: () => {", 1)[1].split("},", 1)[0]

    assert "lastContextMenuAt" in interaction
    assert "now - this.lastContextMenuAt < 350" in interaction
    assert 'reportInteraction("kontextmen' not in context_handler
    assert "states.setState" not in context_handler


def test_desktopmanager_ueberschreibt_aktive_zustaende_nicht_periodisch_mit_idle():
    manager = DESKTOP_MANAGER.read_text(encoding="utf-8")
    assert "private sleepRequested = false" in manager
    assert "if (this.sleepRequested)" in manager
    assert manager.count('this.handlers.onStateRequest?.("idle")') == 1


def test_sprachmenue_sperrt_automatische_bewegung_bis_zum_schliessen():
    root = get_project_root()
    main = MAIN.read_text(encoding="utf-8")
    preload = PRELOAD.read_text(encoding="utf-8")
    electron = ELECTRON.read_text(encoding="utf-8")
    manager = DESKTOP_MANAGER.read_text(encoding="utf-8")
    voice = (root / "backend" / "voice" / "voice_pipeline.py").read_text(encoding="utf-8")

    assert 'event.event !== "orb.menu.requested"' in main
    assert 'setInteractionLock(show, "menu")' in main
    assert 'ipcRenderer.send("window:interaction-lock"' in preload
    assert '"window:interaction-lock"' in electron
    assert "private readonly suspensionReasons" in manager
    assert "now - this.mouseNearSince >= 750" in manager
    assert 'event_types.ORB_MENU_REQUESTED, {"action": "open"}' in voice
    assert 'event_types.ORB_MENU_REQUESTED, {"action": "close"}' in voice
