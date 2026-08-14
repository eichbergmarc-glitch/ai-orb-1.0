/**
 * energy_orb.ts – Der Orb als lebendiges Energie-Wesen.
 *
 * Das visuelle Leitbild: ein kleines, schwebendes, intelligentes
 * Energieobjekt – dunkler gläserner Kern, leuchtende Augen, Energie in
 * Cyan, Blau und Violett, organische Lichtbahnen, Partikel, räumliche
 * Tiefe. Kein Kreis, kein Ladeindikator, kein Spielfigürchen.
 *
 * Der Aufbau in Ebenen, von innen nach außen:
 *
 * 1. **Core** – eine dunkle, leicht gläserne Kugel mit Fresnel-Rand und
 *    weichem inneren Glühen. Sie schreibt Tiefe in den Tiefenpuffer,
 *    wodurch die Energiebahnen räumlich HINTER ihr verschwinden – das ist
 *    der halbe räumliche Eindruck.
 * 2. **Inner Energy** – eine Plasmaschicht dicht über dem Kern. Kein
 *    drehender Farbverlauf, sondern domänenverzerrtes Rauschen: Schwaden,
 *    die entstehen, wandern und vergehen.
 * 3. **Energy Shell** – eine weiche Fresnel-Hülle mit Staubpartikeln.
 * 4. **Energie-Ringe** – mehrere elliptische Bahnen aus Licht, verschieden
 *    geneigt, verschieden schnell, teils unterbrochen, mit wandernden
 *    Kometenköpfen und Partikeln auf der Bahn.
 * 5. **Augen** – zwei abstrakte Lichtformen, die auf den Zustand reagieren.
 * 6. **Boden-Glow** – ein weicher Schein unter dem Orb, der mit der
 *    Schwebehöhe atmet.
 *
 * Gegen sichtbare Schleifen laufen alle Bewegungen mit unteilbaren
 * Frequenzverhältnissen, Rausch-Anteilen und langsamen Parameterdrifts.
 *
 * Dieses Modul kennt nur das Zeichnen. Zustände liefert states.ts, das
 * Schweben die Präsenz-Engine, die Ereignisse main.ts – wie beim alten Orb.
 */

import * as THREE from "three";

import type { OrbStateName, StateAppearance } from "./states";

/**
 * Die zentralen Animationsparameter – EINE Stelle für das visuelle Tuning.
 *
 * Werte, die pro Zustand variieren (Tempo, Glühen, Augen), stehen nicht
 * hier, sondern in states.ts. Hier steht die Grundauslegung des Körpers.
 */
export const ENERGY_PARAMS = {
  /** Radius des dunklen Kerns. */
  coreRadius: 0.61,
  /** Radius der Plasmaschicht (knapp über dem Kern). */
  plasmaRadius: 0.735,
  /** Zwei transparente Tiefen fuer den synaptischen Nebel im Hohlraum. */
  synapticInnerRadius: 0.675,
  synapticOuterRadius: 0.785,
  /** Radius der weichen Außenhülle. */
  shellRadius: 0.82,
  /** Radius der unregelmaessigen, aeusseren Energiekorona. */
  coronaRadius: 0.88,
  /** Die Lichtbahnen: Halbachsen, Neigung, Tempo und Farbakzente. */
  rings: [
    { a: 1.08, b: 0.78, tiltX: 1.08, tiltZ: 0.18, speed: 0.086, gain: 1.00, tube: 0.034, violet: 0.08, warmth: 0.00 },
    { a: 1.13, b: 0.73, tiltX: -0.78, tiltZ: 0.82, speed: -0.064, gain: 0.82, tube: 0.027, violet: 0.56, warmth: 0.00 },
    { a: 1.00, b: 0.88, tiltX: 0.31, tiltZ: -1.08, speed: 0.049, gain: 0.64, tube: 0.023, violet: 0.18, warmth: 0.34 },
    { a: 1.17, b: 0.67, tiltX: 0.70, tiltZ: 1.31, speed: -0.040, gain: 0.50, tube: 0.019, violet: 0.74, warmth: 0.00 },
    { a: 0.94, b: 0.91, tiltX: -0.24, tiltZ: -0.55, speed: 0.036, gain: 0.38, tube: 0.016, violet: 0.04, warmth: 0.48 },
  ],
  /** Geflochtene Lichtfasern direkt auf der Korona der Referenz. */
  filaments: [
    { radius: 0.80, amplitude: 0.16, lobes: 3, phase: 0.20, tiltX: 0.18, tiltZ: 0.10, speed: 0.030, gain: 0.72, tube: 0.020, violet: 0.00, warmth: 0.00 },
    { radius: 0.83, amplitude: 0.13, lobes: 4, phase: 1.35, tiltX: -0.24, tiltZ: 0.42, speed: -0.026, gain: 0.64, tube: 0.017, violet: 0.66, warmth: 0.00 },
    { radius: 0.78, amplitude: 0.19, lobes: 5, phase: 2.10, tiltX: 0.31, tiltZ: -0.36, speed: 0.022, gain: 0.58, tube: 0.016, violet: 0.12, warmth: 0.00 },
    { radius: 0.85, amplitude: 0.11, lobes: 3, phase: 3.05, tiltX: -0.12, tiltZ: 0.78, speed: -0.019, gain: 0.50, tube: 0.014, violet: 0.82, warmth: 0.00 },
    { radius: 0.81, amplitude: 0.17, lobes: 6, phase: 4.30, tiltX: 0.47, tiltZ: 0.20, speed: 0.017, gain: 0.46, tube: 0.013, violet: 0.05, warmth: 0.65 },
    { radius: 0.86, amplitude: 0.10, lobes: 5, phase: 5.10, tiltX: -0.38, tiltZ: -0.62, speed: -0.015, gain: 0.43, tube: 0.012, violet: 0.48, warmth: 0.00 },
    { radius: 0.79, amplitude: 0.15, lobes: 7, phase: 0.85, tiltX: 0.09, tiltZ: 1.04, speed: 0.014, gain: 0.39, tube: 0.011, violet: 0.00, warmth: 0.88 },
    { radius: 0.84, amplitude: 0.12, lobes: 4, phase: 2.75, tiltX: 0.58, tiltZ: -0.12, speed: -0.013, gain: 0.37, tube: 0.010, violet: 0.74, warmth: 0.00 },
    { radius: 0.82, amplitude: 0.18, lobes: 8, phase: 3.72, tiltX: -0.52, tiltZ: 0.16, speed: 0.012, gain: 0.34, tube: 0.009, violet: 0.14, warmth: 0.00 },
    { radius: 0.87, amplitude: 0.09, lobes: 6, phase: 4.92, tiltX: 0.22, tiltZ: -0.92, speed: -0.011, gain: 0.31, tube: 0.009, violet: 0.42, warmth: 0.55 },
  ],
  /** Partikel je Bahn (HIGH; MEDIUM/LOW reduzieren). */
  ringParticles: 12,
  /** Freie Staubpartikel um die Hülle. */
  dustParticles: 52,
  /** Wie stark der Sprechpegel in das Leuchten eingeht (klein!). */
  audioSensitivity: 0.22,
  /** Boden-Glow: Grundgröße, Grundstärke, Kopplung an die Schwebehöhe. */
  ground: { y: -0.94, size: 1.52, strength: 0.48, heightCoupling: 3.2 },
  /** Augen: Grundabstand, Grundgröße – klein; sie dürfen den Orb nie dominieren. */
  eyes: { dx: 0.124, width: 0.044, height: 0.076, z: 0.0 },
  /** Wie lang ein Lichtimpuls (Erfolg/Fehler/Aufwachen) nachklingt. */
  flashSeconds: 1.1,
} as const;

// ---------------------------------------------------------------------------
//  GLSL-Bausteine
// ---------------------------------------------------------------------------

/** Wertrauschen + fbm – die Grundlage aller organischen Bewegung hier. */
const NOISE_GLSL = /* glsl */ `
  float hash13(vec3 p) {
    p = fract(p * 0.3183099 + 0.1);
    p *= 17.0;
    return fract(p.x * p.y * p.z * (p.x + p.y + p.z));
  }
  float noise3(vec3 p) {
    vec3 i = floor(p);
    vec3 f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    return mix(
      mix(mix(hash13(i), hash13(i + vec3(1,0,0)), f.x),
          mix(hash13(i + vec3(0,1,0)), hash13(i + vec3(1,1,0)), f.x), f.y),
      mix(mix(hash13(i + vec3(0,0,1)), hash13(i + vec3(1,0,1)), f.x),
          mix(hash13(i + vec3(0,1,1)), hash13(i + vec3(1,1,1)), f.x), f.y),
      f.z);
  }
  float fbm(vec3 p, int octaves) {
    float value = 0.0;
    float amp = 0.55;
    for (int o = 0; o < 4; o++) {
      if (o >= octaves) break;
      value += amp * noise3(p);
      p = p * 2.03 + vec3(11.7, 5.3, 7.1);
      amp *= 0.5;
    }
    return value;
  }
`;

const BASIC_VERT = /* glsl */ `
  varying vec3 vNormal;
  varying vec3 vView;
  varying vec3 vLocal;
  void main() {
    vLocal = position;
    vNormal = normalize(normalMatrix * normal);
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    vView = normalize(-mv.xyz);
    gl_Position = projectionMatrix * mv;
  }
`;

/** Layer 1: der dunkle, gläserne Kern. */
const CORE_FRAG = /* glsl */ `
  uniform vec3 uDeep;
  uniform vec3 uGlow;
  uniform float uTime;
  uniform float uGlowStrength;
  uniform float uBoost;
  varying vec3 vNormal;
  varying vec3 vView;
  varying vec3 vLocal;
  ${NOISE_GLSL}
  void main() {
    vec3 n = normalize(vNormal);
    vec3 v = normalize(vView);
    float facing = max(dot(n, v), 0.0);
    float rim = pow(1.0 - facing, 2.6);

    // Tiefes, fast schwarzes Zentrum mit einer Spur Farbe und einem sehr
    // langsamen inneren Schimmer - keine flache Farbe.
    float shimmer = fbm(vLocal * 2.4 + vec3(0.0, uTime * 0.05, uTime * 0.033), 3);
    vec3 base = uDeep * (0.16 + 0.10 * shimmer);

    // Weiches inneres Glühen zur Mitte hin (volumetrischer Eindruck).
    float innerGlow = pow(facing, 3.0) * 0.10 * (1.0 + uBoost * 2.2);

    vec3 color = base
      + uGlow * rim * (0.85 * uGlowStrength)
      + uGlow * innerGlow;

    // Fast deckend; am Rand minimal durchscheinend - Glas, kein Stein.
    float alpha = 0.90 + rim * 0.10;
    gl_FragColor = vec4(color, alpha);
  }
`;

/** Layer 2: die Plasmaschicht – Energie, nicht Farbverlauf. */
const PLASMA_FRAG = /* glsl */ `
  uniform vec3 uColorA;
  uniform vec3 uColorB;
  uniform float uTime;
  uniform float uFlow;
  uniform float uAudio;
  uniform int uOctaves;
  varying vec3 vNormal;
  varying vec3 vView;
  varying vec3 vLocal;
  ${NOISE_GLSL}
  void main() {
    vec3 n = normalize(vNormal);
    vec3 v = normalize(vView);
    float rim = pow(1.0 - max(dot(n, v), 0.0), 1.6);

    // Domaenenverzerrtes Rauschen: das Feld wird von einem zweiten Feld
    // verschoben, dadurch ziehen die Schwaden statt zu rotieren.
    vec3 p = normalize(vLocal) * 2.3;
    vec3 warp = vec3(
      fbm(p * 1.6 + vec3(uTime * 0.070, 0.0, uTime * 0.050), uOctaves),
      fbm(p * 1.6 + vec3(7.3, uTime * 0.056, 3.1), uOctaves),
      0.0
    );
    float field = fbm(p + warp * 1.1 + vec3(0.0, uTime * 0.045, -uTime * 0.038), uOctaves);
    float wisp = smoothstep(0.42, 0.86, field);

    vec3 color = mix(uColorA, uColorB, clamp(field * 1.4 - 0.2, 0.0, 1.0));
    // Keine schnelle Funkelkomponente: Bewegung entsteht ausschliesslich
    // durch das langsam wandernde Feld. Auf feinen, hellen Strukturen
    // wuerde ein zeitliches Rauschen durch Bloom als Flackern erscheinen.
    float strength = wisp * (0.18 + 0.82 * rim);
    strength *= uFlow * (1.0 + uAudio);

    gl_FragColor = vec4(color * strength, strength);
  }
`;

/**
 * Langsame synaptische Schwaden zwischen Kern und Energiehuelle.
 *
 * Zwei versetzte Kugelschalen ergeben den Eindruck eines Volumens. Die
 * Leuchtdichte selbst pulst nicht: Nur die Koordinaten des kontinuierlichen
 * Feldes driften. Dadurch bewegen sich Nebeladern und Knoten organisch,
 * ohne dass einzelne Pixel ein- und ausgeschaltet werden.
 */
const SYNAPTIC_MIST_FRAG = /* glsl */ `
  uniform vec3 uColorA;
  uniform vec3 uColorB;
  uniform float uTime;
  uniform float uDensity;
  uniform float uTurbulence;
  uniform float uLayer;
  varying vec3 vNormal;
  varying vec3 vView;
  varying vec3 vLocal;
  ${NOISE_GLSL}
  void main() {
    vec3 n = normalize(vNormal);
    vec3 v = normalize(vView);
    float facing = max(dot(n, v), 0.0);
    vec3 p = normalize(vLocal) * mix(2.35, 3.05, uTurbulence);

    // Sehr langsamer, kontinuierlicher Fluss. Die beiden Schichten bewegen
    // sich gegeneinander und machen den Zwischenraum raeumlich lesbar.
    vec3 drift = vec3(
      uTime * (0.014 + uLayer * 0.004),
      -uTime * (0.010 + uLayer * 0.003),
      uTime * 0.008
    );
    vec3 warp = vec3(
      fbm(p * 0.82 + drift + vec3(1.7, 0.0, 4.2), 3),
      fbm(p * 0.87 - drift.yzx + vec3(0.0, 6.1, 2.4), 3),
      fbm(p * 0.79 + drift.zxy + vec3(5.2, 3.3, 0.0), 3)
    ) - 0.5;
    float broad = fbm(p + warp * (0.72 + uTurbulence * 0.42) + drift, 4);
    float fine = fbm(p * 2.35 - drift * 1.31 + vec3(3.1, 7.2, 1.4), 3);

    // Helle, weiche Adern und kleine synaptische Verdichtungen innerhalb
    // eines breiten Nebelfelds. Keine zufaellige Zeitmodulation.
    float ridge = 1.0 - abs(broad * 2.0 - 1.0);
    float fibres = smoothstep(0.69, 0.91, ridge * 0.72 + fine * 0.34);
    float cloud = smoothstep(0.36, 0.76, broad) * 0.36;
    // Zwei gekreuzte Ridge-Felder bilden verzweigte, synapsenaehnliche
    // Entladungen. Sie folgen demselben stetigen Fluss wie der Nebel und
    // schalten daher nicht zufaellig ein und aus.
    float branchA = 1.0 - abs(fbm(p * 1.52 + warp * 0.92 + drift * 0.74, 4) * 2.0 - 1.0);
    float branchB = 1.0 - abs(fbm(p.yzx * 1.91 - warp.zxy * 0.68 - drift * 0.61, 3) * 2.0 - 1.0);
    float synapse = smoothstep(0.875, 0.965, branchA * 0.72 + branchB * 0.38);
    float nodes = smoothstep(0.76, 0.94, fine + synapse * 0.24) * 0.18;
    float depth = mix(0.48, 1.0, pow(facing, 0.72));
    float strength = (cloud + fibres * 0.44 + synapse * 0.62 + nodes) * depth * uDensity;
    strength = min(strength, 0.38);

    // Farbe wandert im Feld von Blau ueber Cyan zu Violett; es gibt keine
    // separate zeitliche Helligkeitsmodulation.
    float colorFlow = clamp(broad * 0.48 + fine * 0.30 + synapse * 0.38, 0.0, 1.0);
    vec3 color = mix(uColorA, uColorB, colorFlow);
    color = mix(color, vec3(0.62, 0.94, 1.0), synapse * 0.28);
    gl_FragColor = vec4(color * strength, strength * 0.82);
  }
`;

/** Layer 3: die weiche Außenhülle. */
const SHELL_FRAG = /* glsl */ `
  uniform vec3 uColor;
  uniform float uIntensity;
  uniform float uTime;
  varying vec3 vNormal;
  varying vec3 vView;
  varying vec3 vLocal;
  ${NOISE_GLSL}
  void main() {
    vec3 n = normalize(vNormal);
    vec3 v = normalize(vView);
    float rim = pow(1.0 - max(dot(n, v), 0.0), 2.35);
    float field = fbm(normalize(vLocal) * 4.1 + vec3(uTime * 0.025, -uTime * 0.018, 0.0), 3);
    float filaments = smoothstep(0.42, 0.72, field + rim * 0.23);
    float strength = rim * (0.04 + filaments * 1.15) * uIntensity;
    gl_FragColor = vec4(uColor * strength, strength);
  }
`;

/** Unregelmaessige Energiekorona: macht aus der Kugel ein lebendes Feld. */
const CORONA_FRAG = /* glsl */ `
  uniform vec3 uColorA;
  uniform vec3 uColorB;
  uniform float uTime;
  uniform float uIntensity;
  varying vec3 vNormal;
  varying vec3 vView;
  varying vec3 vLocal;
  ${NOISE_GLSL}
  void main() {
    vec3 n = normalize(vNormal);
    vec3 v = normalize(vView);
    float rim = pow(1.0 - max(dot(n, v), 0.0), 3.0);
    vec3 p = normalize(vLocal) * 5.0;
    float broad = fbm(p + vec3(uTime * 0.030, uTime * -0.021, 2.7), 3);
    float fine = fbm(p * 1.75 + vec3(-uTime * 0.044, 5.1, uTime * 0.026), 3);
    float ribbon = smoothstep(0.51, 0.77, broad * 0.72 + fine * 0.42 + rim * 0.28);
    float veil = rim * (0.025 + ribbon * 1.35) * uIntensity;
    vec3 color = mix(uColorA, uColorB, smoothstep(0.38, 0.78, fine));
    gl_FragColor = vec4(color * veil, veil);
  }
`;

/** Energie-Ring: Band mit Lücken, Drift und zwei Kometenköpfen. */
const RING_VERT = /* glsl */ `
  varying vec2 vUv;
  void main() {
    vUv = uv;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`;

const RING_FRAG = /* glsl */ `
  uniform vec3 uColorA;
  uniform vec3 uColorB;
  uniform float uTime;
  uniform float uSpeed;
  uniform float uIntensity;
  uniform float uSeed;
  uniform float uGap;
  varying vec2 vUv;
  ${NOISE_GLSL}
  void main() {
    float u = vUv.x;                       // Lauflaenge entlang der Bahn
    float across = abs(vUv.y - 0.5) * 2.0; // Quer zur Bahn
    float profile = pow(max(0.0, 1.0 - across), 1.7);

    // Vier deutlich getrennte Bogenstuecke laufen ruhig um den Orb.
    float orbitPhase = fract(u * 4.0 - uTime * uSpeed * 0.34 + uSeed);
    float arcDistance = abs(orbitPhase - 0.5) * 2.0;
    float band = 1.0 - smoothstep(0.22, 0.46, arcDistance);
    float width = 0.88;

    // Zwei Kometenkoepfe mit Schweif, gegenlaeufig unterschiedlich schnell.
    float h1 = fract(u - uTime * uSpeed);
    float h2 = fract(0.37 + uSeed * 0.31 - u * 1.0 + uTime * uSpeed * 0.617);
    float comet = exp(-h1 * 5.5) + exp(-h2 * 8.0) * 0.6;

    // Keine permanente Grundlinie: Zwischen den Bogenstuecken ist die Bahn
    // transparent. Die Leuchtdichte bleibt unter der Bloom-Schwelle.
    float glow = (0.28 * band * width + comet * 0.26)
      * profile * uIntensity;
    glow = min(glow, 0.16);
    if (glow < 0.004) discard;
    vec3 color = mix(uColorA, uColorB, 0.5 + 0.5 * sin(u * 6.2831 + uSeed * 9.0));
    // AdditiveBlending verwendet Alpha nochmals als Faktor. Die Farbe darf
    // deshalb nicht bereits mit glow multipliziert sein, sonst werden aus
    // 16 Prozent effektiv 2,5 Prozent und die Bahn verschwindet.
    gl_FragColor = vec4(color, glow);
  }
`;

/** Kurze elektrische Uebergabe von der Huelle an eine Atom-Umlaufbahn. */
const TRANSFER_ARC_FRAG = /* glsl */ `
  uniform vec3 uColorA;
  uniform vec3 uColorB;
  uniform float uProgress;
  uniform float uIntensity;
  varying vec2 vUv;
  void main() {
    float along = vUv.x;
    float across = abs(vUv.y - 0.5) * 2.0;
    float filament = pow(max(0.0, 1.0 - across), 2.2);

    // Ein Energiepaket wandert von der Schale (0) zur Umlaufbahn (1).
    // Die breite Sinus-Huelle blendet es weich ein und aus; kein hartes
    // zufaelliges Blitzen und keine wechselnde Grundhelligkeit.
    if (uProgress < 0.0 || uProgress > 1.0) discard;
    float cycle = uProgress;
    float head = 1.0 - smoothstep(0.015, 0.115, abs(along - cycle));
    float tailDistance = mod(cycle - along + 1.0, 1.0);
    // Der warme Nachlauf zeichnet fuer einen Augenblick den gezackten
    // Uebertragungsweg nach. Ein nur punktfoermiger Kopf war am kleinen
    // Desktop-Orb kaum als Blitz zu erkennen.
    float tail = exp(-tailDistance * 5.5) * step(along, cycle);
    float envelope = smoothstep(0.03, 0.18, cycle)
      * (1.0 - smoothstep(0.82, 0.98, cycle));
    float glow = (head * 0.72 + tail * 0.40) * filament * envelope * uIntensity;
    // Deutlich lesbar, aber mit einer harten Obergrenze gegen Bloom-Flare.
    glow = min(glow, 0.52);
    if (glow < 0.003) discard;

    vec3 color = mix(uColorA, uColorB, smoothstep(0.18, 0.88, along));
    gl_FragColor = vec4(color, glow);
  }
`;

/** Partikel auf einer Bahn: laufen ruhig die Ellipse entlang und scheren aus. */
const RING_PARTICLE_VERT = /* glsl */ `
  attribute float aAngle;
  attribute float aSpeed;
  attribute float aSize;
  attribute float aSeed;
  attribute float aEscape;
  uniform float uTime;
  uniform float uSpeed;
  uniform float uA;
  uniform float uB;
  uniform float uPixelRatio;
  varying float vSeed;
  void main() {
    float angle = aAngle + uTime * uSpeed * aSpeed;
    vec3 pos = vec3(cos(angle) * uA, 0.0, sin(angle) * uB);
    // Gelegentliches Ausscheren: eine kleine, langsame Abweichung senkrecht
    // zur Bahn - einzelne Funken, kein Chaos.
    float wander = sin(uTime * (0.23 + aSeed * 0.4) + aSeed * 40.0);
    pos.y += wander * aEscape;
    pos.x += cos(uTime * 0.31 + aSeed * 21.0) * aEscape * 0.5;

    vec4 mv = modelViewMatrix * vec4(pos, 1.0);
    gl_Position = projectionMatrix * mv;
    gl_PointSize = aSize * uPixelRatio * (95.0 / max(0.5, -mv.z));
    vSeed = aSeed;
  }
`;

const RING_PARTICLE_FRAG = /* glsl */ `
  uniform vec3 uColor;
  uniform float uTime;
  uniform float uIntensity;
  varying float vSeed;
  void main() {
    vec2 d = gl_PointCoord - 0.5;
    float r = length(d) * 2.0;
    float disc = exp(-r * r * 5.0);
    // Ruhiges Schimmern statt Flackern. Die frühere harte 2,2-fache
    // Lichtspitze war auf kleinen Partikeln als Ein-/Ausschalten sichtbar.
    float glow = min(disc * uIntensity, 0.14);
    gl_FragColor = vec4(uColor * glow, glow);
  }
`;

/** Freier Staub um die Hülle. */
const DUST_VERT = /* glsl */ `
  attribute float aSeed;
  attribute float aRadius;
  attribute float aSpeed;
  uniform float uTime;
  uniform float uPixelRatio;
  varying float vSeed;
  void main() {
    float t = uTime * aSpeed * 0.22 + aSeed * 6.2831;
    // Bahnen auf unterschiedlichen Ebenen, langsam praezedierend.
    float tilt = aSeed * 3.1415;
    vec3 pos = vec3(cos(t) * aRadius, sin(t * 0.83 + aSeed * 4.0) * aRadius * 0.5, sin(t) * aRadius);
    pos.xy = mat2(cos(tilt), -sin(tilt), sin(tilt), cos(tilt)) * pos.xy;
    vec4 mv = modelViewMatrix * vec4(pos, 1.0);
    gl_Position = projectionMatrix * mv;
    gl_PointSize = (1.5 + aSeed * 2.0) * uPixelRatio * (90.0 / max(0.5, -mv.z));
    vSeed = aSeed;
  }
`;

const DUST_FRAG = /* glsl */ `
  uniform vec3 uColor;
  uniform float uTime;
  uniform float uIntensity;
  varying float vSeed;
  void main() {
    vec2 d = gl_PointCoord - 0.5;
    float disc = exp(-dot(d, d) * 18.0);
    float glow = min(disc * uIntensity * 0.38, 0.11);
    gl_FragColor = vec4(uColor * glow, glow);
  }
`;

/** Die Augen: zwei weiche Lichtkapseln mit Ausdruck. */
const EYES_FRAG = /* glsl */ `
  uniform vec3 uColor;
  uniform float uOpen;      // Groesse/Oeffnung (0..1.4)
  uniform float uBlink;     // 1 = offen, 0 = geschlossen
  uniform float uHappy;     // 0..1: unterer Bogen (freundlich)
  uniform float uSquint;    // 0..1: oben abgeflacht (fokussiert)
  uniform float uAngry;     // 0..1: nach innen geneigt (Fehler)
  uniform float uBright;    // Leuchtkraft
  uniform float uQuestion;  // Augen werden zum Fragezeichen
  uniform float uAlert;     // Augen werden zum Ausrufezeichen
  uniform float uCurious;   // subtile Asymmetrie
  uniform float uSurprised; // weiter, runder Blick
  uniform float uUncertain; // fragende Augenhoehe
  uniform float uProfessor; // runde Professorbrille (weich eingeblendet)
  uniform vec3 uProfessorColor;
  uniform vec2 uLook;       // kleiner Blickversatz
  uniform float uDx;        // halber Augenabstand
  uniform float uW;         // Kapselbreite
  uniform float uH;         // Kapselhoehe
  varying vec2 vUv;

  float kapsel(vec2 p, float h, float w) {
    vec2 q = p;
    q.y -= clamp(q.y, -h, h);
    return length(q) - w;
  }

  float segment(vec2 p, vec2 a, vec2 b) {
    vec2 pa = p - a, ba = b - a;
    float h = clamp(dot(pa, ba) / dot(ba, ba), 0.0, 1.0);
    return length(pa - ba * h);
  }

  float fragezeichen(vec2 p) {
    // Offener Kopf, kurzer Haken und Punkt. Die linke untere Seite des
    // Rings wird ausgeblendet, damit er nicht wie ein kleines O aussieht.
    vec2 q = p - vec2(0.0, 0.055);
    float ring = abs(length(q) - 0.060) - 0.012;
    ring = max(ring, -(q.x + q.y * 0.55 + 0.015));
    float haken = segment(p, vec2(0.045, 0.025), vec2(0.0, -0.040)) - 0.012;
    float punkt = length(p - vec2(0.0, -0.105)) - 0.014;
    return min(min(ring, haken), punkt);
  }

  float ausrufezeichen(vec2 p) {
    float strich = segment(p, vec2(0.0, 0.105), vec2(0.0, -0.035)) - 0.016;
    float punkt = length(p - vec2(0.0, -0.105)) - 0.017;
    return min(strich, punkt);
  }

  float eye(vec2 p) {
    // Neigung (Fehlerausdruck): inneres Ende hebt sich.
    float c = cos(uAngry * 0.55), s = sin(uAngry * 0.55);
    p = mat2(c, -s, s, c) * p;

    float h = uH * uOpen * (1.0 + uSurprised * 0.32) * max(0.04, uBlink);
    float w = uW * (1.0 + uSquint * 0.15 + uSurprised * 0.20);

    float d = kapsel(p, h, w);

    // Fokus: oben abflachen.
    d = max(d, p.y - h * (1.0 - uSquint * 0.55));

    // Freundlich und nachdenklich: ein kleiner oberer Bogen wie in der
    // Referenz. Die eigene Kreisform verhindert hohe, eckige Hufeisen.
    if (uHappy > 0.01) {
      float radius = max(w * 1.52, 0.035);
      vec2 q = p - vec2(0.0, -radius * 0.20);
      float bogen = abs(length(q) - radius) - max(0.006, w * 0.18);
      // Nur die obere Haelfte des Kreises behalten: eine kleine, ruhige
      // Augenbraue statt einer hohen, eckigen Hufeisenform.
      bogen = max(bogen, -(p.y + radius * 0.08));
      d = mix(d, bogen, smoothstep(0.12, 0.72, uHappy));
    }
    return d;
  }

  void main() {
    vec2 p = (vUv - 0.5) * vec2(0.62, 0.42);
    // Die leuchtenden Kapseln besitzen keine separaten Pupillen. Deshalb
    // bewegt sich das Augenpaar selbst innerhalb des Kerns. 0.045 ist
    // deutlich lesbar, bleibt aber kleiner als der halbe Augenabstand.
    p -= uLook * 0.045;
    vec2 pr = p - vec2(uDx, 0.0);
    vec2 pl = p + vec2(uDx, 0.0);
    // Neugier hebt ein Auge leicht an; Unsicherheit kippt die Augenhöhe
    // stärker gegeneinander. Beides bleibt klein genug, um nicht zu
    // flackern oder wie ein Defekt auszusehen.
    pr.y += uCurious * 0.018 + uUncertain * 0.028;
    pl.y -= uCurious * 0.008 + uUncertain * 0.028;
    pl.x = -pl.x; // spiegeln, damit die Neigung symmetrisch wirkt
    float dEyes = min(eye(pr), eye(pl));
    float symbolMix = clamp(max(uQuestion, uAlert), 0.0, 1.0);
    float dSymbol = mix(fragezeichen(p), ausrufezeichen(p), uAlert);

    // Runde Brille: zwei vollständige Lichtkreise, feiner Steg und kurze
    // Bügel. Sie liegt als eigene Form über den Augen und bleibt deshalb
    // auch bei schmalen/nachdenklichen Augen klar lesbar.
    float glassRadius = 0.104;
    float glassRight = abs(length(p - vec2(uDx, 0.005)) - glassRadius) - 0.008;
    float glassLeft = abs(length(p + vec2(uDx, -0.005)) - glassRadius) - 0.008;
    float glassBridge = segment(
      p,
      vec2(-uDx + glassRadius * 0.88, 0.012),
      vec2(uDx - glassRadius * 0.88, 0.012)
    ) - 0.007;
    float glassArmRight = segment(p, vec2(uDx + glassRadius, 0.018), vec2(0.305, 0.045)) - 0.006;
    float glassArmLeft = segment(p, vec2(-uDx - glassRadius, 0.018), vec2(-0.305, 0.045)) - 0.006;
    float dGlasses = min(min(glassRight, glassLeft), min(glassBridge, min(glassArmRight, glassArmLeft)));

    float eyeBody = smoothstep(0.006, -0.006, dEyes) * (1.0 - symbolMix);
    float symbolBody = smoothstep(0.006, -0.006, dSymbol) * symbolMix;
    float body = eyeBody + symbolBody;
    float d = mix(dEyes, dSymbol, symbolMix);
    float halo = exp(-max(d, 0.0) * 70.0) * 0.32;
    float eyeGlow = (body * 1.25 + halo) * uBright;
    float glassesBody = smoothstep(0.006, -0.006, dGlasses) * uProfessor;
    float glassesHalo = exp(-max(dGlasses, 0.0) * 55.0) * 0.25 * uProfessor;
    float glassesGlow = (glassesBody * 1.15 + glassesHalo) * uBright;
    vec3 color = uColor * eyeGlow + uProfessorColor * glassesGlow;
    gl_FragColor = vec4(color, max(eyeGlow, glassesGlow));
  }
`;

const PLANE_VERT = /* glsl */ `
  varying vec2 vUv;
  void main() {
    vUv = uv;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`;

/**
 * Animationsebene fuer die aus der Konzeptgrafik gewonnenen Lichtmuster.
 * Die Textur liefert unveraenderte RGB-Werte; nur ihre transparente
 * Energieform wird sehr behutsam verformt und gepulst. Dadurch bleibt die
 * Vorlage erkennbar, ohne zu einem eingefrorenen Bild zu werden.
 */
const REFERENCE_FRAG = /* glsl */ `
  uniform sampler2D uTexture;
  uniform float uTime;
  uniform float uOpacity;
  uniform float uWarp;
  uniform float uDarkFloor;
  varying vec2 vUv;
  void main() {
    vec2 p = vUv - 0.5;
    float angle = atan(p.y, p.x);
    float radius = length(p);
    vec2 flow = vec2(
      sin(angle * 3.0 + uTime * 0.23) + sin(p.y * 15.0 - uTime * 0.17),
      cos(angle * 4.0 - uTime * 0.19) + cos(p.x * 13.0 + uTime * 0.14)
    );
    vec2 uv = vUv + flow * uWarp * (0.45 + radius);
    vec4 source = texture2D(uTexture, uv);
    // Die Originalpixel behalten eine konstante Leuchtdichte. Das Muster
    // fliesst nur minimal; Helligkeitspulse an seinen duennen Fasern
    // erzeugen mit Bloom sonst ein scheinbares Ein-/Ausschalten.
    // Dunkle Pixel der Vorlage duerfen die darunter weiterlebende
    // prozedurale Energie nicht wie eine schwarze Folie abdecken. Helle
    // Fasern und die charakteristische Krone bleiben voll erhalten;
    // lediglich der dunkle Kern wird teilweise lichtdurchlaessig.
    float luminance = dot(source.rgb, vec3(0.2126, 0.7152, 0.0722));
    float darkTransmission = mix(uDarkFloor, 1.0, smoothstep(0.055, 0.30, luminance));
    gl_FragColor = vec4(source.rgb, source.a * uOpacity * darkTransmission);
    #include <colorspace_fragment>
  }
`;

export type OrbEmotionName =
  | "friendly" | "curious" | "surprised"
  | "thoughtful" | "joyful" | "relaxed";
export type OrbVisualStyle = "standard" | "galactic" | "minimal" | "nature" | "fire" | "ice";

/** Boden-Glow: weiche, elliptische Lichtlache. */
const GROUND_FRAG = /* glsl */ `
  uniform vec3 uColor;
  uniform vec3 uAccent;
  uniform vec3 uWarm;
  uniform float uStrength;
  uniform float uTime;
  uniform float uOrbitPhase;
  uniform float uTransferEnergy;
  varying vec2 vUv;
  void main() {
    vec2 p = vUv - 0.5;
    vec2 d = p * vec2(1.75, 5.2);
    float pool = exp(-dot(d, d) * 2.25);
    float r = length(p * vec2(1.0, 4.8));
    float ring = exp(-pow((r - 0.22) * 17.0, 2.0));
    float reflection = exp(-pow(p.x * 4.4, 2.0)) * exp(-abs(p.y) * 16.0);
    float violetLobe = exp(-dot((p - vec2(-0.13, 0.01)) * vec2(3.3, 8.0), (p - vec2(-0.13, 0.01)) * vec2(3.3, 8.0)) * 2.0);
    float warmLobe = exp(-dot((p - vec2(0.17, 0.0)) * vec2(4.0, 9.0), (p - vec2(0.17, 0.0)) * vec2(4.0, 9.0)) * 2.2);
    // Spiegelbilder der tatsaechlich umlaufenden Atomsegmente.
    float a1 = uOrbitPhase * 0.083;
    float a2 = -uOrbitPhase * 0.061 + 2.1;
    vec2 orbitPosA = vec2(cos(a1) * 0.29, sin(a1) * 0.028);
    vec2 orbitPosB = vec2(cos(a2) * 0.34, sin(a2) * 0.035);
    float orbitA = exp(-dot((p - orbitPosA) * vec2(8.0, 18.0), (p - orbitPosA) * vec2(8.0, 18.0)) * 2.0);
    float orbitB = exp(-dot((p - orbitPosB) * vec2(9.0, 20.0), (p - orbitPosB) * vec2(9.0, 20.0)) * 2.0);
    float transfer = exp(-dot((p - vec2(0.30, 0.005)) * vec2(11.0, 22.0), (p - vec2(0.30, 0.005)) * vec2(11.0, 22.0)) * 2.0)
      * uTransferEnergy;

    vec3 light = uColor * (pool * 0.52 + ring * 0.48 + reflection * 0.30)
      + uAccent * (violetLobe * 0.18 + orbitA * 0.22)
      + uWarm * (warmLobe * 0.12 + orbitB * 0.16 + transfer * 0.34);
    float alpha = (pool * 0.44 + ring * 0.38 + reflection * 0.18
      + violetLobe * 0.08 + warmLobe * 0.06 + orbitA * 0.10
      + orbitB * 0.08 + transfer * 0.12) * uStrength;
    gl_FragColor = vec4(light * uStrength, alpha);
  }
`;

/** Erfolgs-/Impulswelle: ein expandierender weicher Ring. */
const WAVE_FRAG = /* glsl */ `
  uniform vec3 uColor;
  uniform float uStrength;
  varying vec2 vUv;
  void main() {
    float r = length((vUv - 0.5) * 2.0);
    float ring = exp(-pow((r - 0.72) * 6.5, 2.0));
    float glow = ring * uStrength;
    gl_FragColor = vec4(uColor * glow, glow);
  }
`;

/** Dünner Fortschrittsbogen außerhalb der Energiebahnen. */
const PROGRESS_FRAG = /* glsl */ `
  uniform vec3 uColor;
  uniform float uProgress;
  uniform float uStrength;
  uniform float uTime;
  varying vec2 vUv;
  void main() {
    vec2 p = (vUv - 0.5) * 2.0;
    float r = length(p);
    float ring = exp(-pow((r - 0.82) * 45.0, 2.0));
    float angle = mod(atan(p.y, p.x) + 1.5707963 + 6.2831853, 6.2831853) / 6.2831853;
    float arc = uProgress >= 0.0
      ? step(angle, clamp(uProgress, 0.0, 1.0))
      : smoothstep(0.18, 0.0, abs(fract(angle - uTime * 0.16 + 0.5) - 0.5));
    float glow = ring * arc * uStrength;
    gl_FragColor = vec4(uColor * glow, glow);
  }
`;

// ---------------------------------------------------------------------------
//  Aufbauhelfer
// ---------------------------------------------------------------------------

function additiveMaterial(
  vertexShader: string,
  fragmentShader: string,
  uniforms: Record<string, THREE.IUniform>
): THREE.ShaderMaterial {
  return new THREE.ShaderMaterial({
    vertexShader,
    fragmentShader,
    uniforms,
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
    side: THREE.DoubleSide,
  });
}

/** Eine elliptische Bahn als Röhre. */
function ellipseTube(a: number, b: number, tube: number): THREE.TubeGeometry {
  const curve = new THREE.CatmullRomCurve3(
    Array.from({ length: 64 }, (_, i) => {
      const t = (i / 64) * Math.PI * 2;
      return new THREE.Vector3(Math.cos(t) * a, 0, Math.sin(t) * b);
    }),
    true,
    "catmullrom",
    0.5
  );
  // 168 Segmente sind bei der kleinen Desktop-Darstellung bereits glatt.
  // Die eingesparte Geometrie finanziert zwei zusaetzliche Lichtbahnen,
  // ohne die Bildrate gegenueber der alten Drei-Ring-Version zu belasten.
  return new THREE.TubeGeometry(curve, 168, tube, 6, true);
}

/** Ein echtes, physisch getrenntes Teilstueck einer atomaren Umlaufbahn. */
function ellipseArcTube(
  a: number, b: number, start: number, length: number, tube: number
): THREE.TubeGeometry {
  const curve = new THREE.CatmullRomCurve3(
    Array.from({ length: 25 }, (_, index) => {
      const angle = start + (index / 24) * length;
      return new THREE.Vector3(Math.cos(angle) * a, 0, Math.sin(angle) * b);
    }),
    false,
    "catmullrom",
    0.22
  );
  return new THREE.TubeGeometry(curve, 64, tube, 6, false);
}

/** Eine geschlossene, unregelmaessig um die Kugel geflochtene Lichtfaser. */
function filamentTube(
  radius: number,
  amplitude: number,
  lobes: number,
  phase: number,
  tube: number
): THREE.TubeGeometry {
  const curve = new THREE.CatmullRomCurve3(
    Array.from({ length: 72 }, (_, i) => {
      const theta = (i / 72) * Math.PI * 2;
      const latitude = amplitude * Math.sin(theta * lobes + phase)
        + amplitude * 0.24 * Math.sin(theta * (lobes + 2) - phase * 0.7);
      const localRadius = radius
        + 0.025 * Math.sin(theta * (lobes - 1) + phase * 1.3)
        + 0.012 * Math.sin(theta * 9.0 - phase);
      const horizontal = Math.cos(latitude) * localRadius;
      return new THREE.Vector3(
        Math.cos(theta) * horizontal,
        Math.sin(latitude) * localRadius,
        Math.sin(theta) * horizontal
      );
    }),
    true,
    "catmullrom",
    0.5
  );
  return new THREE.TubeGeometry(curve, 132, tube, 5, true);
}

/** Gezackter, aber fester Strompfad zwischen Huelle und Umlaufbahn. */
function transferArcTube(seed: number, offsetY: number): THREE.TubeGeometry {
  const points = Array.from({ length: 13 }, (_, index) => {
    const p = index / 12;
    const x = 0.77 + p * 0.39;
    const y = offsetY + Math.sin(p * Math.PI) * 0.07
      + Math.sin(p * 31.0 + seed * 17.0) * 0.032 * Math.sin(p * Math.PI);
    const z = 0.10 + Math.sin(p * 18.0 + seed * 11.0) * 0.028 * Math.sin(p * Math.PI);
    return new THREE.Vector3(x, y, z);
  });
  const curve = new THREE.CatmullRomCurve3(points, false, "catmullrom", 0.18);
  // Etwa 1,3 bis 1,6 sichtbare Pixel beim produktiven Orb-Massstab: duenn
  // genug fuer einen elektrischen Funken, aber nicht mehr so duenn, dass
  // die Entladung durch Antialiasing verschwindet.
  return new THREE.TubeGeometry(curve, 64, 0.015, 5, false);
}

interface RingBundle {
  group: THREE.Group;
  material: THREE.ShaderMaterial;
  particleMaterial: THREE.ShaderMaterial;
  particles: THREE.Points;
  mesh: THREE.Mesh;
  arcs: THREE.Mesh[];
  arcMaterial: THREE.MeshBasicMaterial;
  speed: number;
  gain: number;
  seed: number;
  precession: number;
  violet: number;
  warmth: number;
  baseTiltX: number;
  baseTiltZ: number;
}

interface FilamentBundle {
  group: THREE.Group;
  material: THREE.ShaderMaterial;
  mesh: THREE.Mesh;
  gain: number;
  seed: number;
  speed: number;
  violet: number;
  warmth: number;
  baseTiltX: number;
  baseTiltZ: number;
}

interface ReferenceCrown {
  mesh: THREE.Mesh;
  material: THREE.ShaderMaterial;
  opacity: number;
  target: number;
  scale: number;
}

interface TransferArcBundle {
  group: THREE.Group;
  material: THREE.ShaderMaterial;
  baseZ: number;
  speed: number;
  seed: number;
  active: boolean;
  progress: number;
  duration: number;
  gain: number;
  eventGain: number;
}

/**
 * Der Energy-Orb – Aufbau, Zustandsübernahme und Bewegung.
 *
 * Öffentliche Schnittstelle wie beim bisherigen Orb (group, setBaseScale,
 * applyAppearance, setVoiceLevel, update, setQuality, dispose), ergänzt um
 * groundGroup (Boden-Glow), setFloatHeight, setPointer und flash.
 */
export class EnergyOrb {
  public readonly group: THREE.Group;
  /** Der Boden-Glow – vom Träger aufzunehmen, damit er NICHT mitschwebt. */
  public readonly groundGroup: THREE.Group;

  private readonly coreMaterial: THREE.ShaderMaterial;
  private readonly plasmaMaterial: THREE.ShaderMaterial;
  private readonly synapticInnerMaterial: THREE.ShaderMaterial;
  private readonly synapticOuterMaterial: THREE.ShaderMaterial;
  private readonly shellMaterial: THREE.ShaderMaterial;
  private readonly coronaMaterial: THREE.ShaderMaterial;
  private readonly eyesMaterial: THREE.ShaderMaterial;
  private readonly groundMaterial: THREE.ShaderMaterial;
  private readonly waveMaterial: THREE.ShaderMaterial;
  private readonly progressMaterial: THREE.ShaderMaterial;
  private readonly dustMaterial: THREE.ShaderMaterial;
  private readonly referenceCrowns: [ReferenceCrown, ReferenceCrown];
  private readonly referenceOrbitMaterial: THREE.ShaderMaterial;
  private readonly referenceInnerMaterial: THREE.ShaderMaterial;
  private readonly referenceReflectionMaterial: THREE.ShaderMaterial;
  private readonly referenceOrbit: THREE.Mesh;
  private readonly referenceInner: THREE.Mesh;
  private readonly referenceReflection: THREE.Mesh;
  private readonly referenceTextures = new Map<string, THREE.Texture>();

  private readonly rings: RingBundle[] = [];
  private readonly filaments: FilamentBundle[] = [];
  private readonly transferArcs: TransferArcBundle[] = [];
  private readonly dust: THREE.Points;
  private readonly wave: THREE.Mesh;
  private readonly progressRing: THREE.Mesh;
  private readonly light: THREE.PointLight;

  private readonly geometries: THREE.BufferGeometry[] = [];

  private baseScale = 1.0;
  private floatHeight = 0.0;
  private voiceLevel = 0.0;
  private voiceTarget = 0.0;
  private pointer = new THREE.Vector2(0, 0);
  private pointerActive = false;
  private professorTarget = 0.0;
  private professorMix = 0.0;
  private emotion: OrbEmotionName | null = null;
  private emotionUntil = 0;
  private reactionAge = 99.0;
  private reactionKind: "click" | "surprise" = "click";
  private reactionBaseY = 0.0;
  private styleRingGain = 1.0;
  private styleParticleGain = 1.0;
  /** Integrierte Phasen bleiben auch während Zustandsübergängen stetig. */
  private plasmaPhase = 0.0;
  private ringPhase = 0.0;
  private transferPhase = 0.0;
  private transferWait = 1.8 + Math.random() * 4.6;
  private transferReflection = 0.0;
  private filamentPhase = 0.0;
  private particlePhase = 0.0;
  private dustPhase = 0.0;
  private referencePhase = 0.0;
  private referenceReady = false;
  private referenceSlot = 0;
  private referenceState: OrbStateName = "idle";
  private referenceOrbitOpacity = 0.0;
  private referenceOrbitTarget = 0.0;
  private referenceInnerOpacity = 0.0;
  private referenceInnerTarget = 0.0;
  private referenceReflectionOpacity = 0.0;
  private referenceReflectionTarget = 0.0;

  /** Blinzeln: Uhr bis zum nächsten Lidschlag und dessen Fortschritt. */
  private blinkIn = 3.5;
  private blinkPhase = -1.0;

  /** Lichtimpuls (Erfolg, Aufwachen, Fehler): Alter und Stärke. */
  private flashAge = 99.0;
  private flashStrength = 0.0;

  /** Globale Faktoren aus orb.animation (tempo/helligkeit) – kompatibel
   *  mit dem bestehenden Werkzeug 'animation_anpassen'. */
  private readonly tempoFactor: number;
  private readonly brightFactor: number;

  private readonly farbhilfeA = new THREE.Color();
  private readonly farbhilfeB = new THREE.Color();
  private readonly farbhilfeC = new THREE.Color();
  /** Fest, statt eine Farbhilfe zu überschreiben: Genau das hat einmal den
   *  Boden-Glow und das Punktlicht weiss gefärbt. */
  private readonly weiss = new THREE.Color(0xffffff);
  private readonly warmesBahnlicht = new THREE.Color(0xffa34d);
  private readonly synapsenRot = new THREE.Color(0xff4a2f);
  private readonly synapsenOrange = new THREE.Color(0xffad38);
  private readonly violettesBahnlicht = new THREE.Color(0x9d63ff);
  private readonly freundlichBlau = new THREE.Color(0xa9e3ff);
  private readonly freudeKern = new THREE.Color(0x35d97a);
  private readonly freudeGlow = new THREE.Color(0xbcffd9);
  private readonly freudePartikel = new THREE.Color(0x7dffb5);
  /** Professorpalette: akademisches Blau/Cyan mit warmem Messingakzent. */
  private readonly professorKern = new THREE.Color(0x185edb);
  private readonly professorGlow = new THREE.Color(0x70dcff);
  private readonly professorPartikel = new THREE.Color(0xffd27a);
  private readonly hslHilfe = { h: 0, s: 0, l: 0 };

  constructor(options?: { tempo?: number; helligkeit?: number }, pixelRatio = 1) {
    this.tempoFactor = clampNumber(options?.tempo ?? 1.0, 0.2, 3.0);
    this.brightFactor = clampNumber(options?.helligkeit ?? 1.0, 0.2, 3.0);

    this.group = new THREE.Group();
    this.groundGroup = new THREE.Group();

    const P = ENERGY_PARAMS;

    // Die transparente Starttextur verhindert einen weissen Platzhalter,
    // solange Electron die Bilddateien asynchron von der Platte laedt.
    const emptyData = new Uint8Array([0, 0, 0, 0]);
    const emptyTexture = new THREE.DataTexture(emptyData, 1, 1, THREE.RGBAFormat);
    emptyTexture.needsUpdate = true;

    const makeReferenceMaterial = (
      opacity = 0.0,
      warp = 0.0,
      darkFloor = 1.0
    ): THREE.ShaderMaterial => {
      const material = new THREE.ShaderMaterial({
        vertexShader: PLANE_VERT,
        fragmentShader: REFERENCE_FRAG,
        uniforms: {
          uTexture: { value: emptyTexture },
          uTime: { value: 0.0 },
          uOpacity: { value: opacity },
          uWarp: { value: warp },
          uDarkFloor: { value: darkFloor },
        },
        transparent: true,
        depthWrite: false,
        depthTest: false,
        blending: THREE.NormalBlending,
        toneMapped: false,
      });
      return material;
    };

    const referenceGeo = new THREE.PlaneGeometry(2.72, 2.66);
    this.geometries.push(referenceGeo);
    const crownA = new THREE.Mesh(referenceGeo, makeReferenceMaterial(0.0, 0.0, 0.30));
    const crownB = new THREE.Mesh(referenceGeo, makeReferenceMaterial(0.0, 0.0, 0.30));
    crownA.renderOrder = 3;
    crownB.renderOrder = 3;
    crownA.position.z = 0.69;
    crownB.position.z = 0.695;
    this.group.add(crownA, crownB);
    this.referenceCrowns = [
      { mesh: crownA, material: crownA.material as THREE.ShaderMaterial, opacity: 0, target: 0, scale: 1 },
      { mesh: crownB, material: crownB.material as THREE.ShaderMaterial, opacity: 0, target: 0, scale: 1 },
    ];

    this.referenceOrbitMaterial = makeReferenceMaterial();
    this.referenceOrbit = new THREE.Mesh(referenceGeo, this.referenceOrbitMaterial);
    this.referenceOrbit.position.z = 0.68;
    this.referenceOrbit.renderOrder = 2;
    this.group.add(this.referenceOrbit);

    // Originale synaptische Lichtzeichnung aus dem Hohlraum der Vorlage.
    // Sie liegt hinter der Krone und vor dem dunklen Kern; Augen sind aus
    // der Textur ausgespart und bleiben dadurch komplett interaktiv.
    this.referenceInnerMaterial = makeReferenceMaterial(0.0, 0.0018);
    this.referenceInner = new THREE.Mesh(referenceGeo, this.referenceInnerMaterial);
    this.referenceInner.position.z = 0.685;
    this.referenceInner.renderOrder = 2;
    this.group.add(this.referenceInner);

    this.referenceReflectionMaterial = makeReferenceMaterial();
    this.referenceReflection = new THREE.Mesh(referenceGeo, this.referenceReflectionMaterial);
    this.referenceReflection.position.z = 0.67;
    this.referenceReflection.renderOrder = 1;
    this.group.add(this.referenceReflection);

    this.loadReferenceTextures();

    // --- Layer 1: Core -----------------------------------------------------
    const coreGeo = new THREE.SphereGeometry(P.coreRadius, 48, 32);
    this.geometries.push(coreGeo);
    this.coreMaterial = new THREE.ShaderMaterial({
      vertexShader: BASIC_VERT,
      fragmentShader: CORE_FRAG,
      uniforms: {
        uDeep: { value: new THREE.Color(0x0a1428) },
        uGlow: { value: new THREE.Color(0x46c8ff) },
        uTime: { value: 0 },
        uGlowStrength: { value: 1.0 },
        uBoost: { value: 0.0 },
      },
      transparent: true,
      depthWrite: true, // wichtig: verdeckt die Ringe räumlich
    });
    const core = new THREE.Mesh(coreGeo, this.coreMaterial);
    core.renderOrder = 0;
    this.group.add(core);

    // --- Layer 2: Plasma ---------------------------------------------------
    const plasmaGeo = new THREE.SphereGeometry(P.plasmaRadius, 48, 32);
    this.geometries.push(plasmaGeo);
    this.plasmaMaterial = additiveMaterial(BASIC_VERT, PLASMA_FRAG, {
      uColorA: { value: new THREE.Color(0x2fa8ff) },
      uColorB: { value: new THREE.Color(0x9a5cff) },
      uTime: { value: 0 },
      uFlow: { value: 1.0 },
      uAudio: { value: 0.0 },
      uOctaves: { value: 4 },
    });
    const plasma = new THREE.Mesh(plasmaGeo, this.plasmaMaterial);
    plasma.renderOrder = 1;
    this.group.add(plasma);

    // --- Synaptischer Nebel im Raum zwischen Kern und Huelle -------------
    const createSynapticMaterial = (layer: number): THREE.ShaderMaterial =>
      additiveMaterial(BASIC_VERT, SYNAPTIC_MIST_FRAG, {
        uColorA: { value: new THREE.Color(0x25a9ff) },
        uColorB: { value: new THREE.Color(0x8c66ff) },
        uTime: { value: 0.0 },
        uDensity: { value: layer < 0.5 ? 0.54 : 0.38 },
        uTurbulence: { value: 0.35 },
        uLayer: { value: layer },
      });
    const synapticInnerGeo = new THREE.SphereGeometry(P.synapticInnerRadius, 40, 28);
    const synapticOuterGeo = new THREE.SphereGeometry(P.synapticOuterRadius, 44, 30);
    this.geometries.push(synapticInnerGeo, synapticOuterGeo);
    this.synapticInnerMaterial = createSynapticMaterial(0.0);
    this.synapticOuterMaterial = createSynapticMaterial(1.0);
    const synapticInner = new THREE.Mesh(synapticInnerGeo, this.synapticInnerMaterial);
    const synapticOuter = new THREE.Mesh(synapticOuterGeo, this.synapticOuterMaterial);
    synapticInner.rotation.set(0.18, -0.24, 0.09);
    synapticOuter.rotation.set(-0.13, 0.31, -0.17);
    synapticInner.renderOrder = 1;
    synapticOuter.renderOrder = 1;
    this.group.add(synapticInner, synapticOuter);

    // --- Layer 3: Shell ----------------------------------------------------
    const shellGeo = new THREE.SphereGeometry(P.shellRadius, 40, 26);
    this.geometries.push(shellGeo);
    this.shellMaterial = additiveMaterial(BASIC_VERT, SHELL_FRAG, {
      uColor: { value: new THREE.Color(0x3fb6ff) },
      uIntensity: { value: 0.68 },
      uTime: { value: 0.0 },
    });
    const shell = new THREE.Mesh(shellGeo, this.shellMaterial);
    shell.renderOrder = 2;
    this.group.add(shell);

    // --- Layer 4: organische Energiekorona -------------------------------
    const coronaGeo = new THREE.SphereGeometry(P.coronaRadius, 40, 26);
    this.geometries.push(coronaGeo);
    this.coronaMaterial = additiveMaterial(BASIC_VERT, CORONA_FRAG, {
      uColorA: { value: new THREE.Color(0x27caff) },
      uColorB: { value: new THREE.Color(0x9d63ff) },
      uTime: { value: 0.0 },
      uIntensity: { value: 0.58 },
    });
    const corona = new THREE.Mesh(coronaGeo, this.coronaMaterial);
    corona.renderOrder = 2;
    this.group.add(corona);

    // --- Geflochtene Energiekrone ----------------------------------------
    // Die Referenz zeigt keine geschlossene Neon-Hohlkugel, sondern viele
    // unterschiedlich geneigte Lichtfasern. Jede Faser folgt einer leicht
    // anderen Wellenlinie direkt ueber dem Kern.
    P.filaments.forEach((def, index) => {
      const geo = filamentTube(def.radius, def.amplitude, def.lobes, def.phase, def.tube * 1.35);
      this.geometries.push(geo);
      const material = additiveMaterial(RING_VERT, RING_FRAG, {
        uColorA: { value: new THREE.Color(0x28cfff) },
        uColorB: { value: new THREE.Color(0x9d63ff) },
        uTime: { value: 0.0 },
        uSpeed: { value: def.speed },
        uIntensity: { value: def.gain * 0.28 },
        uSeed: { value: index * 0.417 + 0.09 },
        uGap: { value: 0.30 },
      });
      const mesh = new THREE.Mesh(geo, material);
      mesh.renderOrder = 2;
      const filamentGroup = new THREE.Group();
      filamentGroup.rotation.set(def.tiltX, 0, def.tiltZ);
      filamentGroup.add(mesh);
      this.group.add(filamentGroup);
      this.filaments.push({
        group: filamentGroup,
        material,
        mesh,
        gain: def.gain,
        seed: index * 0.417 + 0.09,
        speed: def.speed,
        violet: def.violet,
        warmth: def.warmth,
        baseTiltX: def.tiltX,
        baseTiltZ: def.tiltZ,
      });
    });

    // --- Energie-Ringe -----------------------------------------------------
    P.rings.forEach((def, index) => {
      const geo = ellipseTube(def.a, def.b, def.tube);
      this.geometries.push(geo);
      const material = additiveMaterial(RING_VERT, RING_FRAG, {
        uColorA: { value: new THREE.Color(0x35d5ff) },
        uColorB: { value: new THREE.Color(0x8a5cff) },
        uTime: { value: 0 },
        uSpeed: { value: def.speed },
        uIntensity: { value: def.gain },
        uSeed: { value: index * 0.731 + 0.17 },
        uGap: { value: 0.25 },
      });
      const mesh = new THREE.Mesh(geo, material);
      mesh.renderOrder = 3;

      // Vier physisch getrennte Bogensegmente bleiben auch beim kompakten
      // Desktop-Orb sichtbar. Die Luecken sind echte Geometrie; es kann
      // daher kein geschlossener Neonreifen entstehen.
      const arcMaterial = new THREE.MeshBasicMaterial({
        color: 0x4fdcff,
        transparent: true,
        opacity: 0.72,
        depthWrite: false,
        depthTest: true,
        blending: THREE.AdditiveBlending,
        toneMapped: false,
      });
      const arcs = Array.from({ length: 4 }, (_, arcIndex) => {
        const arcGeo = ellipseArcTube(
          def.a,
          def.b,
          arcIndex * (Math.PI / 2) + index * 0.21,
          0.54 + (arcIndex % 2) * 0.12,
          Math.max(0.012, def.tube * 0.72)
        );
        this.geometries.push(arcGeo);
        const arc = new THREE.Mesh(arcGeo, arcMaterial);
        arc.renderOrder = 4;
        return arc;
      });

      // Partikel derselben Bahn – im selben Koordinatensystem, damit sie
      // exakt auf der Ellipse laufen.
      const particleMaterial = additiveMaterial(RING_PARTICLE_VERT, RING_PARTICLE_FRAG, {
        uColor: { value: new THREE.Color(0x9fe8ff) },
        uTime: { value: 0 },
        uSpeed: { value: def.speed * 6.0 },
        uA: { value: def.a },
        uB: { value: def.b },
        uPixelRatio: { value: pixelRatio },
        uIntensity: { value: def.gain },
      });
      const particles = this.createRingParticles(ENERGY_PARAMS.ringParticles, particleMaterial);
      particles.renderOrder = 4;

      const ringGroup = new THREE.Group();
      ringGroup.rotation.set(def.tiltX, 0, def.tiltZ);
      ringGroup.add(mesh);
      ringGroup.add(...arcs);
      ringGroup.add(particles);
      this.group.add(ringGroup);

      this.rings.push({
        group: ringGroup,
        material,
        particleMaterial,
        particles,
        mesh,
        arcs,
        arcMaterial,
        speed: def.speed,
        gain: def.gain,
        seed: index * 0.731 + 0.17,
        precession: (index + 1) * 0.021 * (index % 2 === 0 ? 1 : -1),
        violet: def.violet,
        warmth: def.warmth,
        baseTiltX: def.tiltX,
        baseTiltZ: def.tiltZ,
      });
    });

    // --- Elektrische Transferentladungen ---------------------------------
    // Energiepakete loesen sich zufaellig an wechselnden Stellen aus der
    // Huelle und springen in eine Umlaufbahn. Vier Pfade plus frei gewaehlte
    // Rotation verhindern einen mechanisch wiederholten Einzelblitz.
    [
      { seed: 0.19, y: 0.13, z: -0.18, speed: 0.105, gain: 0.88 },
      { seed: 0.43, y: -0.05, z: 0.23, speed: 0.091, gain: 0.78 },
      { seed: 0.71, y: -0.16, z: 0.46, speed: 0.078, gain: 0.84 },
      { seed: 0.91, y: 0.04, z: -0.55, speed: 0.086, gain: 0.72 },
    ].forEach((definition) => {
      const geometry = transferArcTube(definition.seed, definition.y);
      this.geometries.push(geometry);
      const material = additiveMaterial(RING_VERT, TRANSFER_ARC_FRAG, {
        uColorA: { value: new THREE.Color(0x8eeeff) },
        uColorB: { value: new THREE.Color(0x8b64ff) },
        uProgress: { value: -1.0 },
        uIntensity: { value: definition.gain },
      });
      const mesh = new THREE.Mesh(geometry, material);
      mesh.renderOrder = 4;
      const transferGroup = new THREE.Group();
      transferGroup.rotation.z = definition.z;
      transferGroup.add(mesh);
      this.group.add(transferGroup);
      this.transferArcs.push({
        group: transferGroup,
        material,
        baseZ: definition.z,
        speed: definition.speed,
        seed: definition.seed,
        active: false,
        progress: -1.0,
        duration: 0.55,
        gain: definition.gain,
        eventGain: 1.0,
      });
    });

    // --- Staub -------------------------------------------------------------
    this.dustMaterial = additiveMaterial(DUST_VERT, DUST_FRAG, {
      uColor: { value: new THREE.Color(0x9fd8ff) },
      uTime: { value: 0 },
      uIntensity: { value: 0.5 },
      uPixelRatio: { value: pixelRatio },
    });
    this.dust = this.createDust(ENERGY_PARAMS.dustParticles, this.dustMaterial);
    this.dust.renderOrder = 4;
    this.group.add(this.dust);

    // --- Augen ---------------------------------------------------------------
    const eyesGeo = new THREE.PlaneGeometry(1.0, 0.68);
    this.geometries.push(eyesGeo);
    this.eyesMaterial = additiveMaterial(PLANE_VERT, EYES_FRAG, {
      uColor: { value: new THREE.Color(0xd8f4ff) },
      uOpen: { value: 1.0 },
      uBlink: { value: 1.0 },
      uHappy: { value: 0.0 },
      uSquint: { value: 0.0 },
      uAngry: { value: 0.0 },
      uBright: { value: 1.0 },
      uQuestion: { value: 0.0 },
      uAlert: { value: 0.0 },
      uCurious: { value: 0.0 },
      uSurprised: { value: 0.0 },
      uUncertain: { value: 0.0 },
      uProfessor: { value: 0.0 },
      uProfessorColor: { value: new THREE.Color(0xffd996) },
      uLook: { value: new THREE.Vector2(0, 0) },
      uDx: { value: ENERGY_PARAMS.eyes.dx },
      uW: { value: ENERGY_PARAMS.eyes.width },
      uH: { value: ENERGY_PARAMS.eyes.height },
    });
    this.eyesMaterial.depthTest = false; // immer auf dem Kern sichtbar
    const eyes = new THREE.Mesh(eyesGeo, this.eyesMaterial);
    eyes.position.set(0, 0.03, ENERGY_PARAMS.coreRadius + 0.02);
    eyes.renderOrder = 6;
    this.group.add(eyes);

    // --- Impulswelle ---------------------------------------------------------
    const waveGeo = new THREE.PlaneGeometry(1.0, 1.0);
    this.geometries.push(waveGeo);
    this.waveMaterial = additiveMaterial(PLANE_VERT, WAVE_FRAG, {
      uColor: { value: new THREE.Color(0x7fe0ff) },
      uStrength: { value: 0.0 },
    });
    this.waveMaterial.depthTest = false;
    this.wave = new THREE.Mesh(waveGeo, this.waveMaterial);
    this.wave.renderOrder = 5;
    this.wave.visible = false;
    this.group.add(this.wave);

    const progressGeo = new THREE.PlaneGeometry(2.55, 2.55);
    this.geometries.push(progressGeo);
    this.progressMaterial = additiveMaterial(PLANE_VERT, PROGRESS_FRAG, {
      uColor: { value: new THREE.Color(0x6fe4ff) },
      uProgress: { value: -1.0 },
      uStrength: { value: 0.0 },
      uTime: { value: 0.0 },
    });
    this.progressMaterial.depthTest = false;
    this.progressRing = new THREE.Mesh(progressGeo, this.progressMaterial);
    this.progressRing.renderOrder = 7;
    this.progressRing.visible = false;
    this.group.add(this.progressRing);

    // --- Boden-Glow ------------------------------------------------------------
    const groundGeo = new THREE.PlaneGeometry(1.0, 1.0);
    this.geometries.push(groundGeo);
    this.groundMaterial = additiveMaterial(PLANE_VERT, GROUND_FRAG, {
      uColor: { value: new THREE.Color(0x2f8fd8) },
      uAccent: { value: new THREE.Color(0x8a5cff) },
      uWarm: { value: new THREE.Color(0xffa34d) },
      uStrength: { value: ENERGY_PARAMS.ground.strength },
      uTime: { value: 0.0 },
      uOrbitPhase: { value: 0.0 },
      uTransferEnergy: { value: 0.0 },
    });
    const ground = new THREE.Mesh(groundGeo, this.groundMaterial);
    ground.rotation.x = -Math.PI / 2;
    ground.position.y = ENERGY_PARAMS.ground.y;
    ground.scale.setScalar(ENERGY_PARAMS.ground.size);
    this.groundGroup.add(ground);

    // --- Licht -------------------------------------------------------------------
    this.light = new THREE.PointLight(0x46c8ff, 1.6, 6.0, 2.0);
    this.group.add(this.light);
  }

  private createRingParticles(count: number, material: THREE.ShaderMaterial): THREE.Points {
    const geometry = new THREE.BufferGeometry();
    const positions = new Float32Array(count * 3);
    const angle = new Float32Array(count);
    const speed = new Float32Array(count);
    const size = new Float32Array(count);
    const seed = new Float32Array(count);
    const escape = new Float32Array(count);
    for (let i = 0; i < count; i += 1) {
      angle[i] = Math.random() * Math.PI * 2;
      speed[i] = 0.5 + Math.random() * 1.1;
      // Klein: Funken auf der Bahn, keine Blasen um den Orb.
      size[i] = 0.7 + Math.random() * 1.1;
      seed[i] = Math.random();
      // Nur wenige Partikel scheren aus – kein Chaos.
      escape[i] = Math.random() < 0.18 ? 0.05 + Math.random() * 0.07 : 0.0;
    }
    geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    geometry.setAttribute("aAngle", new THREE.BufferAttribute(angle, 1));
    geometry.setAttribute("aSpeed", new THREE.BufferAttribute(speed, 1));
    geometry.setAttribute("aSize", new THREE.BufferAttribute(size, 1));
    geometry.setAttribute("aSeed", new THREE.BufferAttribute(seed, 1));
    geometry.setAttribute("aEscape", new THREE.BufferAttribute(escape, 1));
    this.geometries.push(geometry);
    return new THREE.Points(geometry, material);
  }

  private loadReferenceTextures(): void {
    const loader = new THREE.TextureLoader();
    const states = ["idle", "listening", "thinking", "executing", "waiting", "success", "warning", "error", "offline"];
    const files: Record<string, string> = {
      // Die vollstaendige Referenzkugel traegt den dunklen Kern und die
      // charakteristische Flechtstruktur exakt. Augen/Symbole sind in den
      // Dateien ausgespart und bleiben deshalb vollstaendig dynamisch.
      crownIdle: "assets/orb/reference-layers/idle-base.png",
      innerIdle: "assets/orb/reference-layers/idle-inner-energy.png",
      orbitIdle: "assets/orb/reference-layers/idle-orbits.png",
      reflectionIdle: "assets/orb/reference-layers/idle-reflection.png",
    };
    for (const state of states) {
      files[`state:${state}`] = `assets/orb/reference-layers/state-base-${state}.png`;
    }

    let remaining = Object.keys(files).length;
    const loaded = (): void => {
      remaining -= 1;
      if (remaining !== 0) return;
      this.referenceReady = true;
      this.referenceInnerMaterial.uniforms.uTexture.value = this.referenceTextures.get("innerIdle");
      this.referenceOrbitMaterial.uniforms.uTexture.value = this.referenceTextures.get("orbitIdle");
      this.referenceReflectionMaterial.uniforms.uTexture.value = this.referenceTextures.get("reflectionIdle");
      // Die Quelle besitzt bereits die gewuenschten unterbrochenen Bahnen
      // und Farbverlaeufe. Die 3D-Bogenstuecke darunter geben ihnen Tiefe.
      this.referenceInnerTarget = 0.28;
      this.referenceOrbitTarget = 0.62;
      this.referenceReflectionTarget = 0.16;
      for (const ring of this.rings) ring.particles.visible = true;
      for (const filament of this.filaments) filament.mesh.visible = true;
      this.showReferenceState(this.referenceState);
    };

    for (const [key, file] of Object.entries(files)) {
      loader.load(
        file,
        (texture) => {
          texture.colorSpace = THREE.SRGBColorSpace;
          // Keine wechselnden Mip-Stufen auf den nur ein bis zwei Pixel
          // breiten Plasmafasern. Das beseitigt deren Helligkeitsschimmern
          // beim Schweben des gesamten Orb.
          texture.minFilter = THREE.LinearFilter;
          texture.magFilter = THREE.LinearFilter;
          texture.generateMipmaps = false;
          this.referenceTextures.set(key, texture);
          loaded();
        },
        undefined,
        () => loaded()
      );
    }
  }

  private patternForState(state: OrbStateName): { key: string; scale: number; orbit: number; inner: number; reflection: number } {
    const normalized = state === "busy" ? "executing"
      : state === "speaking" ? "success"
        : state === "sleep" ? "offline"
          : state;
    // Die Quellgrafik besitzt bereits einen eingebrannten Leuchthof. Mit
    // dem Live-Bloom darf sie deshalb nur als dezente Bahnzeichnung
    // zugemischt werden, sonst ueberstrahlt sie nach dem Einblenden.
    const orbitByState: Record<string, number> = {
      idle: 0.62, listening: 0.44, thinking: 0.50, executing: 0.58,
      waiting: 0.45, success: 0.46, warning: 0.52, error: 0.54, offline: 0.20,
    };
    const innerByState: Record<string, number> = {
      idle: 0.28, listening: 0.20, thinking: 0.30, executing: 0.32,
      waiting: 0.22, success: 0.24, warning: 0.28, error: 0.30, offline: 0.08,
    };
    if (normalized === "idle") {
      return { key: "crownIdle", scale: 1.0, orbit: orbitByState.idle, inner: innerByState.idle, reflection: 0.16 };
    }
    return {
      key: `state:${normalized}`,
      scale: 0.67,
      orbit: orbitByState[normalized] ?? 0.36,
      inner: innerByState[normalized] ?? 0.42,
      reflection: normalized === "offline" ? 0.06 : 0.14,
    };
  }

  private showReferenceState(state: OrbStateName): void {
    this.referenceState = state;
    if (!this.referenceReady) return;
    const pattern = this.patternForState(state);
    const texture = this.referenceTextures.get(pattern.key) ?? this.referenceTextures.get("crownIdle");
    if (texture === undefined) return;

    const next = 1 - this.referenceSlot;
    const crown = this.referenceCrowns[next];
    crown.material.uniforms.uTexture.value = texture;
    crown.scale = pattern.scale;
    crown.mesh.scale.setScalar(pattern.scale);
    // Auch beim ersten Laden weich einblenden. Zuvor erschien die komplette
    // helle Textur in einem einzigen Frame und sah wie ein Blitz aus.
    crown.opacity = 0.0;
    // Der Quellausschnitt besitzt bereits fotografischen Glow. In der
    // WebGL-Szene kommt Live-Bloom hinzu; volle Deckkraft wuerde deshalb
    // nach dem Laden heller als die perfekte Startdarstellung werden.
    // Die Referenzkrone liefert Formdetails, darf aber die live berechnete
    // Zustandsfarbe von Nebel, Huelle und Bahnen nicht ueberdecken.
    crown.target = state === "idle" ? 0.90 : 0.86;
    crown.material.uniforms.uOpacity.value = crown.opacity;
    this.referenceCrowns[1 - next].target = 0.0;
    this.referenceSlot = next;
    this.referenceOrbitTarget = pattern.orbit;
    this.referenceInnerTarget = pattern.inner;
    this.referenceReflectionTarget = pattern.reflection;
  }

  private createDust(count: number, material: THREE.ShaderMaterial): THREE.Points {
    const geometry = new THREE.BufferGeometry();
    const positions = new Float32Array(count * 3);
    const seed = new Float32Array(count);
    const radius = new Float32Array(count);
    const speed = new Float32Array(count);
    for (let i = 0; i < count; i += 1) {
      seed[i] = Math.random();
      radius[i] = 0.92 + Math.random() * 0.5;
      speed[i] = 0.3 + Math.random() * 0.8;
    }
    geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    geometry.setAttribute("aSeed", new THREE.BufferAttribute(seed, 1));
    geometry.setAttribute("aRadius", new THREE.BufferAttribute(radius, 1));
    geometry.setAttribute("aSpeed", new THREE.BufferAttribute(speed, 1));
    this.geometries.push(geometry);
    return new THREE.Points(geometry, material);
  }

  // --- Schnittstelle wie beim bisherigen Orb --------------------------------

  public setBaseScale(scale: number): void {
    this.baseScale = scale;
  }

  public setVoiceLevel(level: number): void {
    this.voiceTarget = clampNumber(level, 0, 1);
  }

  /** Die Schwebehöhe aus der Präsenz-Engine – steuert den Boden-Glow. */
  public setFloatHeight(y: number): void {
    this.floatHeight = y;
  }

  /** Zeigerposition relativ zur Orbmitte (-1..1) für den subtilen Blick. */
  public setPointer(x: number, y: number, active: boolean): void {
    this.pointer.set(clampNumber(x, -1, 1), clampNumber(y, -1, 1));
    this.pointerActive = active;
  }

  /** Verbindet das exakte Farbmuster der Vorlage mit dem semantischen Zustand. */
  public setState(state: OrbStateName): void {
    if (state !== this.referenceState) this.showReferenceState(state);
  }

  /** Blendet die runde Brille und die akademische Farbmischung weich ein. */
  public setProfessorMode(active: boolean): void {
    this.professorTarget = active ? 1.0 : 0.0;
  }


  /** Zeigt einen der sechs Ausdruecke aus der Referenz fuer kurze Zeit. */
  public setEmotion(emotion: OrbEmotionName | null, seconds = 2.4): void {
    this.emotion = emotion;
    this.emotionUntil = emotion === null ? 0 : performance.now() + seconds * 1000;
    if (emotion === "surprised") this.react("surprise");
  }

  /** Kurze koerperliche Antwort auf Klick beziehungsweise Ueberraschung. */
  public react(kind: "click" | "surprise"): void {
    this.reactionKind = kind;
    this.reactionAge = 0;
    this.reactionBaseY = this.group.position.y;
    this.flash(kind === "surprise" ? 0.75 : 0.38);
  }

  public setVisualStyle(style: OrbVisualStyle): void {
    const values: Record<OrbVisualStyle, [number, number]> = {
      standard: [1.0, 1.0], galactic: [1.35, 1.45], minimal: [0.38, 0.18],
      nature: [0.92, 1.15], fire: [1.22, 1.35], ice: [0.82, 1.0],
    };
    [this.styleRingGain, this.styleParticleGain] = values[style];
  }

  /** Löst einen kurzen Lichtimpuls aus (Aufwachen, Erfolg, Fehler). */
  public flash(strength = 1.0): void {
    this.flashAge = 0.0;
    this.flashStrength = clampNumber(strength, 0, 1.5);
  }

  /** Zeigt 0..1 oder einen laufenden Bogen bei fehlendem Prozentwert. */
  public setProgress(progress: number | null, indeterminate = false): void {
    this.progressRing.visible = progress !== null;
    this.progressMaterial.uniforms.uProgress.value = indeterminate
      ? -1.0
      : clampNumber(progress ?? 0.0, 0.0, 1.0);
    this.progressMaterial.uniforms.uStrength.value = progress === null ? 0.0 : 0.9;
  }

  /**
   * Übernimmt die (bereits weich interpolierten) Zustandswerte.
   */
  public applyAppearance(a: StateAppearance): void {
    const core = this.farbhilfeA.setHex(a.coreColor);
    const glow = this.farbhilfeB.setHex(a.glowColor);
    const particle = this.farbhilfeC.setHex(a.particleColor);
    const bright = this.brightFactor;

    if (this.emotion !== null && performance.now() >= this.emotionUntil) {
      this.emotion = null;
    }
    if (this.emotion === "joyful") {
      core.lerp(this.freudeKern, 0.72);
      glow.lerp(this.freudeGlow, 0.72);
      particle.lerp(this.freudePartikel, 0.72);
    } else if (this.emotion === "friendly") {
      glow.lerp(this.freundlichBlau, 0.38);
    }

    // Im Professorbetrieb bleibt Blau die Basis; Cyan macht das Erklären
    // heller, ein kleiner Goldanteil gibt ihm einen eigenen akademischen
    // Charakter, ohne den Orb wieder violett erscheinen zu lassen.
    core.lerp(this.professorKern, this.professorMix * 0.74);
    glow.lerp(this.professorGlow, this.professorMix * 0.68);
    particle.lerp(this.professorPartikel, this.professorMix * 0.34);

    this.coreMaterial.uniforms.uGlow.value.copy(glow);
    (this.coreMaterial.uniforms.uDeep.value as THREE.Color).copy(core).multiplyScalar(0.30);
    this.coreMaterial.uniforms.uGlowStrength.value =
      (0.46 + a.coreGlow * 0.62) * bright;

    this.plasmaMaterial.uniforms.uColorA.value.copy(core);
    // Die zweite Plasmafarbe ist die Zustandsfarbe mit VERSCHOBENEM
    // Farbton: Ein kleiner Zug Richtung Cyan hält Blau wirklich blau.
    // Orange bleibt dabei warm, statt über Rot ins Pink zu kippen.
    this.tonVerschieben(glow, -0.035, this.plasmaMaterial.uniforms.uColorB.value as THREE.Color);
    this.plasmaMaterial.uniforms.uFlow.value = a.energyFlow * bright * 0.40;

    // Blau/Cyan traegt violette Nebeladern und Fasern wie die Vorlage.
    // Eindeutige Statusfarben faerben dagegen das gesamte Energiefeld.
    core.getHSL(this.hslHilfe, THREE.SRGBColorSpace);
    const blueFamily = this.hslHilfe.s > 0.25 && this.hslHilfe.h >= 0.50 && this.hslHilfe.h <= 0.72;

    for (const mist of [this.synapticInnerMaterial, this.synapticOuterMaterial]) {
      this.tonVerschieben(core, -0.055, mist.uniforms.uColorA.value as THREE.Color, 0.44);
      this.tonVerschieben(glow, 0.035, mist.uniforms.uColorB.value as THREE.Color, 0.46);
      (mist.uniforms.uColorB.value as THREE.Color).lerp(
        this.violettesBahnlicht,
        blueFamily ? 0.48 : 0.06
      );
      mist.uniforms.uTurbulence.value = clampNumber(a.smokeTurbulence / 1.6, 0.12, 1.0);
    }
    this.synapticInnerMaterial.uniforms.uDensity.value =
      clampNumber(a.smokeDensity * 0.68 * bright, 0.30, 0.82);
    this.synapticOuterMaterial.uniforms.uDensity.value =
      clampNumber(a.smokeDensity * 0.48 * bright, 0.22, 0.62);

    this.tonVerschieben(core, -0.045, this.shellMaterial.uniforms.uColor.value as THREE.Color, 0.50);
    this.shellMaterial.uniforms.uIntensity.value = 0.44 * a.lightIntensity * bright;

    this.tonVerschieben(core, -0.045, this.coronaMaterial.uniforms.uColorA.value as THREE.Color, 0.46);
    this.tonVerschieben(core, 0.065, this.coronaMaterial.uniforms.uColorB.value as THREE.Color, 0.48);
    (this.coronaMaterial.uniforms.uColorB.value as THREE.Color).lerp(
      this.violettesBahnlicht,
      blueFamily ? 0.68 : 0.10
    );
    this.coronaMaterial.uniforms.uIntensity.value =
      (0.19 + a.energyFlow * 0.11) * a.lightIntensity * bright;

    for (const filament of this.filaments) {
      this.tonVerschieben(core, -0.045, filament.material.uniforms.uColorA.value as THREE.Color, 0.46);
      this.tonVerschieben(core, 0.055, filament.material.uniforms.uColorB.value as THREE.Color, 0.48);
      (filament.material.uniforms.uColorB.value as THREE.Color).lerp(
        this.violettesBahnlicht,
        blueFamily ? filament.violet * 0.82 : filament.violet * 0.06
      );
      (filament.material.uniforms.uColorA.value as THREE.Color).lerp(
        this.violettesBahnlicht,
        blueFamily ? filament.violet * 0.42 : filament.violet * 0.03
      );
      (filament.material.uniforms.uColorB.value as THREE.Color).lerp(
        this.warmesBahnlicht,
        blueFamily ? filament.warmth : 0.0
      );
      (filament.material.uniforms.uColorA.value as THREE.Color).lerp(
        this.warmesBahnlicht,
        blueFamily ? filament.warmth * 0.58 : 0.0
      );
      filament.material.uniforms.uIntensity.value =
        filament.gain * a.ringIntensity * bright * 0.58;
    }

    for (const ring of this.rings) {
      // Beide Bahnfarben aus der Zustandsfarbe, mit gegenläufig
      // verschobenem Farbton und angehobener Helligkeit: leuchtende
      // Plasmabahnen, die die Farbauskunft des Zustands nie verfälschen.
      this.tonVerschieben(core, -0.055, ring.material.uniforms.uColorA.value as THREE.Color, 0.52);
      this.tonVerschieben(core, 0.045, ring.material.uniforms.uColorB.value as THREE.Color, 0.50);
      (ring.material.uniforms.uColorB.value as THREE.Color).lerp(
        this.violettesBahnlicht,
        blueFamily ? ring.violet : ring.violet * 0.06
      );
      (ring.material.uniforms.uColorA.value as THREE.Color).lerp(
        this.violettesBahnlicht,
        blueFamily ? ring.violet * 0.28 : ring.violet * 0.03
      );
      // Wie in der Referenz liegt auf einer der hinteren Bahnen ein kleiner
      // warmer Lichtreflex. Er ist nur Akzent und ueberdeckt nie die
      // Zustandsfarbe des Orb.
      (ring.material.uniforms.uColorB.value as THREE.Color).lerp(
        this.warmesBahnlicht,
        blueFamily ? ring.warmth : 0.0
      );
      (ring.material.uniforms.uColorA.value as THREE.Color).lerp(
        this.warmesBahnlicht,
        blueFamily ? ring.warmth * 0.55 : 0.0
      );
      ring.material.uniforms.uIntensity.value =
        ring.gain * a.ringIntensity * bright * this.styleRingGain * 0.30;
      ring.arcMaterial.color.copy(ring.material.uniforms.uColorA.value as THREE.Color).lerp(
        ring.material.uniforms.uColorB.value as THREE.Color,
        0.34
      );
      ring.arcMaterial.opacity = clampNumber(
        0.14 + ring.gain * a.ringIntensity * bright * 0.10,
        0.14,
        0.30
      );
      ring.particleMaterial.uniforms.uColor.value.copy(particle);
      ring.particleMaterial.uniforms.uIntensity.value =
        ring.gain * a.particleIntensity * bright * this.styleParticleGain * 0.22;
    }

    for (const transfer of this.transferArcs) {
      // Synaptische Uebertragungen sind absichtlich warm und dadurch auch
      // im blauen Grundzustand eindeutig als einzelne Ereignisse lesbar.
      (transfer.material.uniforms.uColorA.value as THREE.Color)
        .copy(this.synapsenRot).lerp(glow, 0.08);
      (transfer.material.uniforms.uColorB.value as THREE.Color)
        .copy(this.synapsenOrange).lerp(glow, 0.06);
      transfer.gain = 1.38 * Math.max(0.72, a.ringIntensity) * bright;
      transfer.material.uniforms.uIntensity.value =
        transfer.gain * (transfer.active ? transfer.eventGain : 1.0);
    }

    this.dustMaterial.uniforms.uColor.value.copy(particle);
    this.dustMaterial.uniforms.uIntensity.value =
      0.5 * a.particleIntensity * bright * this.styleParticleGain;

    this.eyesMaterial.uniforms.uColor.value.copy(glow).lerp(
      this.weiss,
      a.eyeAlert > 0.5 ? 0.06 : 0.55
    );
    const emotionEyes: Partial<Record<OrbEmotionName, [number, number, number, number, number, number, number]>> = {
      friendly: [0.72, 0.62, 0.0, 0.0, 0.2, 0.0, 0.0],
      curious: [1.12, 0.0, 0.0, 0.0, 1.0, 0.15, 0.0],
      surprised: [1.32, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0],
      thoughtful: [0.70, 0.25, 0.32, 0.0, 0.0, 0.0, 0.9],
      joyful: [0.95, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0],
      relaxed: [0.34, 0.92, 0.08, 0.0, 0.0, 0.0, 0.18],
    };
    const expression = this.emotion === null ? undefined : emotionEyes[this.emotion];
    this.eyesMaterial.uniforms.uOpen.value = expression?.[0] ?? a.eyeOpen;
    this.eyesMaterial.uniforms.uHappy.value = expression?.[1] ?? a.eyeHappy;
    this.eyesMaterial.uniforms.uSquint.value = expression?.[2] ?? a.eyeSquint;
    this.eyesMaterial.uniforms.uAngry.value = expression?.[3] ?? a.eyeAngry;
    this.eyesMaterial.uniforms.uBright.value = a.eyeBright * bright;
    this.eyesMaterial.uniforms.uQuestion.value = a.eyeQuestion;
    this.eyesMaterial.uniforms.uAlert.value = a.eyeAlert;
    this.eyesMaterial.uniforms.uCurious.value = expression?.[4] ?? a.eyeCurious;
    this.eyesMaterial.uniforms.uSurprised.value = expression?.[5] ?? a.eyeSurprised;
    this.eyesMaterial.uniforms.uUncertain.value = expression?.[6] ?? a.eyeUncertain;

    this.groundMaterial.uniforms.uColor.value.copy(core);
    (this.groundMaterial.uniforms.uAccent.value as THREE.Color).copy(
      blueFamily ? this.violettesBahnlicht : glow
    );
    (this.groundMaterial.uniforms.uWarm.value as THREE.Color).copy(
      blueFamily ? this.warmesBahnlicht : glow
    );
    this.waveMaterial.uniforms.uColor.value.copy(glow);
    this.light.color.copy(core);
    this.light.intensity = 1.6 * a.lightIntensity * bright;
  }

  /**
   * Aktualisiert alle zeitabhängigen Werte.
   */
  public update(elapsed: number, delta: number, a: StateAppearance): void {
    const t = elapsed * this.tempoFactor;
    const professorEase = 1.0 - Math.exp(-delta * 5.0);
    this.professorMix += (this.professorTarget - this.professorMix) * professorEase;
    this.eyesMaterial.uniforms.uProfessor.value = this.professorMix;
    this.plasmaPhase += delta * this.tempoFactor * (0.7 + a.speed * 0.5);
    this.ringPhase += delta * this.tempoFactor * a.ringSpeed;
    this.transferPhase += delta * this.tempoFactor * (0.55 + a.energyFlow * 0.28);
    this.filamentPhase += delta * this.tempoFactor * (0.45 + a.energyFlow * 0.38);
    this.particlePhase += delta * this.tempoFactor * a.particleSpeed;
    this.dustPhase += delta * this.tempoFactor * (0.6 + a.speed * 0.4);
    this.referencePhase += delta * this.tempoFactor * (0.45 + a.energyFlow * 0.28);

    const referenceEase = 1.0 - Math.exp(-delta * 5.5);
    for (const crown of this.referenceCrowns) {
      crown.opacity += (crown.target - crown.opacity) * referenceEase;
      crown.material.uniforms.uOpacity.value = crown.opacity * this.brightFactor;
      crown.material.uniforms.uTime.value = this.referencePhase;
      crown.mesh.scale.setScalar(crown.scale);
      crown.mesh.rotation.z = 0.0;
    }
    this.referenceOrbitOpacity +=
      (this.referenceOrbitTarget - this.referenceOrbitOpacity) * referenceEase;
    this.referenceInnerOpacity +=
      (this.referenceInnerTarget - this.referenceInnerOpacity) * referenceEase;
    this.referenceReflectionOpacity +=
      (this.referenceReflectionTarget - this.referenceReflectionOpacity) * referenceEase;
    this.referenceOrbitMaterial.uniforms.uOpacity.value =
      this.referenceOrbitOpacity * this.brightFactor;
    this.referenceInnerMaterial.uniforms.uOpacity.value =
      this.referenceInnerOpacity * this.brightFactor;
    this.referenceReflectionMaterial.uniforms.uOpacity.value =
      this.referenceReflectionOpacity * this.brightFactor;
    this.referenceOrbitMaterial.uniforms.uTime.value = this.referencePhase * 0.72;
    this.referenceInnerMaterial.uniforms.uTime.value = this.referencePhase * 0.58;
    this.referenceReflectionMaterial.uniforms.uTime.value = this.referencePhase * 0.42;
    // Die getrennten Originalbahnen praezedieren langsam und verformen sich
    // gleichzeitig im Shader. So sind sie weder starr noch ein durchgehender
    // technisch perfekter Kreis.
    // Das exakte Bahnkunstwerk bleibt rasterstabil. Bewegung liefern die
    // darauf laufenden Partikel; eine Subpixelrotation der duennen Linien
    // verursachte auf manchen Displays trotz 60 FPS ein starkes Flimmern.
    this.referenceOrbit.rotation.z = 0.0;
    this.referenceOrbit.scale.set(1.0, 1.0, 1.0);

    // Sprechpegel: schnell hinauf, langsam hinunter (wie bisher).
    const anstieg = 1.0 - Math.exp(-delta * 24.0);
    const abfall = 1.0 - Math.exp(-delta * 5.0);
    this.voiceLevel +=
      (this.voiceTarget - this.voiceLevel) *
      (this.voiceTarget > this.voiceLevel ? anstieg : abfall);
    const audio = this.voiceLevel * ENERGY_PARAMS.audioSensitivity;

    // --- Lichtimpuls-Choreografie -----------------------------------------
    // 1. Energie sammelt sich (Plasma an, Ringe kurz leiser)
    // 2. Kern leuchtet auf
    // 3. Welle läuft nach außen, alles kehrt weich zurück.
    this.flashAge += delta;
    const F = ENERGY_PARAMS.flashSeconds;
    let coreBoost = 0.0;
    let plasmaBoost = 0.0;
    let ringDamp = 1.0;
    if (this.flashAge < F) {
      const ph = this.flashAge / F;
      plasmaBoost = Math.sin(Math.min(1.0, ph * 3.0) * Math.PI) * 0.8 * this.flashStrength;
      coreBoost = Math.exp(-Math.pow((ph - 0.32) * 5.0, 2.0)) * this.flashStrength;
      ringDamp = 1.0 - 0.35 * Math.sin(Math.min(1.0, ph * 2.2) * Math.PI) * this.flashStrength;
      const waveT = clampNumber((ph - 0.3) / 0.7, 0, 1);
      this.wave.visible = waveT > 0 && waveT < 1;
      if (this.wave.visible) {
        this.wave.scale.setScalar(1.2 + waveT * 2.4);
        this.waveMaterial.uniforms.uStrength.value =
          Math.sin(waveT * Math.PI) * 0.38 * this.flashStrength;
      }
    } else {
      this.wave.visible = false;
    }

    // --- Uniform-Zeiten ------------------------------------------------------
    this.coreMaterial.uniforms.uTime.value = t;
    this.coreMaterial.uniforms.uBoost.value = coreBoost + audio * 0.4;
    // Plasma läuft mit der Zustandsgeschwindigkeit – hier arbeitet die Energie.
    this.plasmaMaterial.uniforms.uTime.value = this.plasmaPhase;
    this.plasmaMaterial.uniforms.uAudio.value = audio + plasmaBoost;
    this.synapticInnerMaterial.uniforms.uTime.value = this.plasmaPhase;
    this.synapticOuterMaterial.uniforms.uTime.value = this.plasmaPhase * 0.91;
    this.shellMaterial.uniforms.uTime.value = this.plasmaPhase;
    this.coronaMaterial.uniforms.uTime.value = this.plasmaPhase * 0.86;
    this.groundMaterial.uniforms.uTime.value = t;

    for (const filament of this.filaments) {
      filament.material.uniforms.uTime.value = this.filamentPhase;
      filament.material.uniforms.uIntensity.value =
        filament.gain * a.ringIntensity * this.brightFactor * ringDamp * 0.58;
      filament.group.rotation.y = this.filamentPhase * filament.speed * 0.24;
      filament.group.rotation.x = filament.baseTiltX
        + Math.sin(t * 0.031 + filament.seed * 19.0) * 0.014;
      filament.group.rotation.z = filament.baseTiltZ
        + Math.cos(t * 0.027 + filament.seed * 23.0) * 0.012;
    }

    for (const ring of this.rings) {
      ring.material.uniforms.uTime.value = this.ringPhase;
      ring.material.uniforms.uIntensity.value =
        ring.gain * a.ringIntensity * this.brightFactor * ringDamp * this.styleRingGain * 0.30;
      ring.particleMaterial.uniforms.uTime.value = this.particlePhase;

      // Räumliche Präzession: Jede Bahn dreht langsam um eine eigene,
      // leicht wandernde Achse – die Bewegung wiederholt sich nie sichtbar.
      ring.group.rotation.y = this.ringPhase * ring.precession;
      ring.group.rotation.x = ring.baseTiltX
        + Math.sin(t * 0.043 + ring.seed * 20.0) * 0.026;
      ring.group.rotation.z = ring.baseTiltZ
        + Math.cos(t * 0.037 + ring.seed * 31.0) * 0.022;
      for (const arc of ring.arcs) {
        arc.rotation.y = this.ringPhase * ring.speed * 1.8;
      }
    }

    // Seltene, echte Ereignisse statt eines periodischen Shaderzyklus.
    // Die Pause, der Pfad, die Dauer und die leichte Pfadabweichung werden
    // nur beim Start einer Entladung zufaellig bestimmt. Waerend des
    // Ereignisses bleibt die Bewegung kontinuierlich und flackerfrei.
    this.transferWait -= delta;
    if (this.transferWait <= 0 && !this.transferArcs.some((arc) => arc.active)) {
      const chosen = this.transferArcs[Math.floor(Math.random() * this.transferArcs.length)];
      if (chosen !== undefined) {
        chosen.active = true;
        chosen.progress = 0.0;
        chosen.duration = 1.25 + Math.random() * 0.95;
        chosen.group.rotation.z = Math.random() * Math.PI * 2.0;
        chosen.group.rotation.x = (Math.random() - 0.5) * 0.34;
        chosen.group.rotation.y = (Math.random() - 0.5) * 0.30;
        chosen.eventGain = 1.24 + Math.random() * 0.56;
        chosen.material.uniforms.uIntensity.value = chosen.gain * chosen.eventGain;
      }
      // Selten entsteht kurz danach eine zweite Entladung; meistens folgt
      // eine deutlich laengere, unregelmaessige Ruhephase.
      this.transferWait = Math.random() < 0.16
        ? 0.35 + Math.random() * 0.45
        : 2.4 + Math.random() * 5.8;
    }
    let transferEnergy = 0.0;
    for (const transfer of this.transferArcs) {
      if (!transfer.active) {
        transfer.material.uniforms.uProgress.value = -1.0;
        continue;
      }
      transfer.progress += delta / transfer.duration;
      if (transfer.progress >= 1.0) {
        transfer.active = false;
        transfer.progress = -1.0;
        transfer.material.uniforms.uProgress.value = -1.0;
        continue;
      }
      transfer.material.uniforms.uProgress.value = transfer.progress;
      transferEnergy = Math.max(transferEnergy, Math.sin(transfer.progress * Math.PI));
    }
    const reflectionEase = 1.0 - Math.exp(-delta * (transferEnergy > this.transferReflection ? 18.0 : 7.0));
    this.transferReflection += (transferEnergy - this.transferReflection) * reflectionEase;

    this.dustMaterial.uniforms.uTime.value = this.dustPhase;
    this.progressMaterial.uniforms.uTime.value = t;
    this.groundMaterial.uniforms.uOrbitPhase.value = this.ringPhase;
    this.groundMaterial.uniforms.uTransferEnergy.value = this.transferReflection;

    // --- Augen: Blinzeln und Blick -------------------------------------------
    this.blinkIn -= delta;
    if (this.blinkIn <= 0 && this.blinkPhase < 0 && a.eyeOpen > 0.2) {
      this.blinkPhase = 0;
      // Nächster Lidschlag in 3 bis 8 Sekunden, gelegentlich doppelt.
      this.blinkIn = Math.random() < 0.18 ? 0.35 : 3.0 + Math.random() * 5.0;
    }
    let blink = 1.0;
    if (this.blinkPhase >= 0) {
      this.blinkPhase += delta;
      const D = 0.30; // gesamte Lidschlagdauer
      blink = this.blinkPhase < 0.12
        ? 1.0 - this.blinkPhase / 0.12
        : Math.min(1.0, (this.blinkPhase - 0.12) / 0.18);
      if (this.blinkPhase >= D) {
        this.blinkPhase = -1.0;
        blink = 1.0;
      }
    }
    this.eyesMaterial.uniforms.uBlink.value = blink;

    // Blick: klar zur Maus, sonst langsames Umherschauen. Die Eingabe ist
    // bereits relativ zur tatsaechlichen Orb-Groesse normiert; hier muss
    // sie deshalb nicht noch einmal abgeschwaecht werden.
    const look = this.eyesMaterial.uniforms.uLook.value as THREE.Vector2;
    if (this.pointerActive) {
      look.lerp(this.pointer, Math.min(1, delta * 7.0));
    } else {
      look.x += (Math.sin(t * 0.11) * 0.4 - look.x) * Math.min(1, delta * 0.8);
      look.y += (Math.sin(t * 0.073 + 1.7) * 0.25 - look.y) * Math.min(1, delta * 0.8);
    }

    // --- Boden-Glow: atmet mit der Schwebehöhe -------------------------------
    const g = ENERGY_PARAMS.ground;
    const height = clampNumber(this.floatHeight * g.heightCoupling, -0.55, 0.55);
    const ground = this.groundGroup.children[0] as THREE.Mesh | undefined;
    if (ground !== undefined) {
      ground.scale.setScalar(g.size * this.baseScale * (1.0 - height * 0.45) * (0.8 + a.scale * 0.3));
      this.groundMaterial.uniforms.uStrength.value =
        g.strength * a.lightIntensity * (1.0 - height * 0.7) * this.brightFactor;
      // Knapp unter den Orb, nicht an den Fensterrand: Der Schein gehört
      // optisch zum Objekt, erst dadurch liest sich das Schweben.
      ground.position.y = g.y * this.baseScale * 1.05;
    }

    // Gesamtgröße: Grundgröße × sehr subtile Eigenpulsation.
    this.reactionAge += delta;
    let reactionScale = 1.0;
    if (this.reactionAge < 0.72) {
      if (this.reactionKind === "surprise") {
        const p = this.reactionAge / 0.72;
        this.group.position.y = this.reactionBaseY + Math.sin(p * Math.PI) * 0.18;
        reactionScale += Math.sin(p * Math.PI * 2.0) * 0.055 * (1.0 - p);
      } else {
        reactionScale += Math.sin(this.reactionAge * 18.0) * 0.045
          * Math.exp(-this.reactionAge * 6.0);
      }
    }

    // Duenne Aussenbahnen duerfen nicht sichtbar ueber Pixelgrenzen
    // gepumpt werden. Der Kern atmet weiterhin, nur deutlich subtiler.
    const pulse = 1.0 + Math.sin(t * 1.07) * a.pulseAmount * 0.12
      + Math.sin(t * 0.61 + 1.3) * a.pulseAmount * 0.07;
    const totalScale = this.baseScale * pulse * reactionScale * (1.0 + coreBoost * 0.05);
    this.group.scale.setScalar(totalScale);

    // Der Pegel verfällt von selbst (wie bisher im alten Orb).
    this.voiceTarget = Math.max(0.0, this.voiceTarget - delta * 1.8);
  }

  /** Leistungsstufe: 0 = niedrig, 1 = mittel, 2 = hoch. */
  public setQuality(level: number): void {
    const q = Math.max(0, Math.min(2, level));
    // Rauschoktaven des Plasmas – der teuerste Posten.
    this.plasmaMaterial.uniforms.uOctaves.value = q >= 2 ? 4 : q >= 1 ? 3 : 2;
    // Dritter Ring und Staub erst ab Mittel; die Bahnen selbst bleiben –
    // ein Energy-Orb ohne Energiebahnen wäre keiner mehr.
    this.rings.forEach((ring, index) => {
      const visible = q >= 2 || (q >= 1 ? index < 4 : index < 2);
      // Die Referenztextur liefert Farbe und Silhouette; diese echten
      // 3D-Bahnen liefern die fehlende raeumliche Bewegung. Sie bleiben
      // deshalb auch nach dem Laden sichtbar, aber bewusst sehr gedimmt.
      ring.mesh.visible = visible;
      for (const arc of ring.arcs) arc.visible = visible;
      ring.particles.visible = visible && (q >= 1 || index < 1);
    });
    this.filaments.forEach((filament, index) => {
      filament.mesh.visible = q >= 2 || (q >= 1 ? index < 7 : index < 4);
    });
    this.dust.visible = q >= 1;
  }

  public get scaleFactor(): number {
    return this.baseScale;
  }

  /**
   * Verschiebt den Farbton einer Farbe, ohne sie blass zu machen.
   *
   * Dasselbe Prinzip wie beim bisherigen Orb: Wer mit den Farbkanälen
   * mischt, bekommt blasse Zwischentöne; über den Farbton bleibt die Farbe
   * kräftig. Bei fast grauen Farben (Offline) bleibt der Ton unangetastet -
   * dort wäre er beliebig, und Schieben ergäbe Farbflackern.
   *
   * @param minHelligkeit Hebt dunkle Zustandsfarben für die Bahnen an -
   *   eine Energiebahn in Themetiefblau wäre sonst unsichtbar.
   */
  private tonVerschieben(
    von: THREE.Color, zug: number, ziel: THREE.Color, minHelligkeit = 0.0
  ): void {
    // Ausdruecklich im sRGB-Raum: three rechnet HSL sonst im LINEAREN
    // Arbeitsraum, und dort liegt Orange bei Farbton 0.04 - eine kleine
    // Verschiebung nach unten landete im Magenta, und der Arbeitszustand
    // wurde pink statt orange.
    von.getHSL(this.hslHilfe, THREE.SRGBColorSpace);
    if (this.hslHilfe.s < 0.06) {
      ziel.copy(von);
      return;
    }
    ziel.setHSL(
      (((this.hslHilfe.h + zug) % 1.0) + 1.0) % 1.0,
      this.hslHilfe.s,
      Math.max(this.hslHilfe.l, minHelligkeit),
      THREE.SRGBColorSpace
    );
  }

  public dispose(): void {
    for (const geo of this.geometries) {
      geo.dispose();
    }
    this.coreMaterial.dispose();
    this.plasmaMaterial.dispose();
    this.synapticInnerMaterial.dispose();
    this.synapticOuterMaterial.dispose();
    this.shellMaterial.dispose();
    this.coronaMaterial.dispose();
    this.eyesMaterial.dispose();
    this.groundMaterial.dispose();
    this.waveMaterial.dispose();
    this.progressMaterial.dispose();
    this.dustMaterial.dispose();
    for (const crown of this.referenceCrowns) crown.material.dispose();
    this.referenceOrbitMaterial.dispose();
    this.referenceReflectionMaterial.dispose();
    for (const texture of this.referenceTextures.values()) texture.dispose();
    for (const ring of this.rings) {
      ring.material.dispose();
      ring.particleMaterial.dispose();
      ring.arcMaterial.dispose();
    }
    for (const filament of this.filaments) {
      filament.material.dispose();
    }
    for (const transfer of this.transferArcs) transfer.material.dispose();
  }
}

function clampNumber(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}
