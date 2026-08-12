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

import type { StateAppearance } from "./states";

/**
 * Die zentralen Animationsparameter – EINE Stelle für das visuelle Tuning.
 *
 * Werte, die pro Zustand variieren (Tempo, Glühen, Augen), stehen nicht
 * hier, sondern in states.ts. Hier steht die Grundauslegung des Körpers.
 */
export const ENERGY_PARAMS = {
  /** Radius des dunklen Kerns. */
  coreRadius: 0.62,
  /** Radius der Plasmaschicht (knapp über dem Kern). */
  plasmaRadius: 0.655,
  /** Radius der weichen Außenhülle. */
  shellRadius: 0.82,
  /** Die drei Bahnen: Halbachsen, Neigung, Grundtempo, Grundhelligkeit. */
  rings: [
    { a: 1.06, b: 0.86, tiltX: 1.15, tiltZ: 0.20, speed: 0.110, gain: 1.00, tube: 0.038 },
    { a: 1.18, b: 0.80, tiltX: -0.85, tiltZ: 0.75, speed: -0.080, gain: 0.80, tube: 0.030 },
    { a: 0.98, b: 0.94, tiltX: 0.35, tiltZ: -1.05, speed: 0.062, gain: 0.62, tube: 0.024 },
  ],
  /** Partikel je Bahn (HIGH; MEDIUM/LOW reduzieren). */
  ringParticles: 40,
  /** Freie Staubpartikel um die Hülle. */
  dustParticles: 64,
  /** Wie stark der Sprechpegel in das Leuchten eingeht (klein!). */
  audioSensitivity: 0.22,
  /** Boden-Glow: Grundgröße, Grundstärke, Kopplung an die Schwebehöhe. */
  ground: { y: -0.95, size: 1.25, strength: 0.85, heightCoupling: 3.2 },
  /** Augen: Grundabstand, Grundgröße – klein; sie dürfen den Orb nie dominieren. */
  eyes: { dx: 0.105, width: 0.034, height: 0.085, z: 0.0 },
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

    // Elektrisches Flackern: schnelles, feines Rauschen nur in den Schwaden.
    float spark = noise3(p * 6.0 + vec3(uTime * 0.9)) * wisp;

    vec3 color = mix(uColorA, uColorB, clamp(field * 1.4 - 0.2, 0.0, 1.0));
    float strength = wisp * (0.18 + 0.82 * rim) + spark * 0.10;
    strength *= uFlow * (1.0 + uAudio);

    gl_FragColor = vec4(color * strength, strength);
  }
`;

/** Layer 3: die weiche Außenhülle. */
const SHELL_FRAG = /* glsl */ `
  uniform vec3 uColor;
  uniform float uIntensity;
  varying vec3 vNormal;
  varying vec3 vView;
  void main() {
    vec3 n = normalize(vNormal);
    vec3 v = normalize(vView);
    // Hohe Potenz und niedrige Staerke: ein weicher Lichthauch am Rand,
    // ausdruecklich KEIN gezeichneter Kreis um die Kugel.
    float rim = pow(1.0 - max(dot(n, v), 0.0), 4.2);
    float strength = rim * uIntensity;
    gl_FragColor = vec4(uColor * strength, strength);
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

    // Das Grundband: von Rauschen unterbrochen, mit wandernder Phase -
    // die Luecken bleiben nicht stehen, sie ziehen langsam mit.
    float band = fbm(vec3(u * 5.0 + uSeed * 13.0, uSeed * 7.0, uTime * 0.05), 3);
    band = smoothstep(uGap, uGap + 0.30, band);

    // Breite atmet leicht entlang der Bahn.
    float width = 0.75 + 0.25 * noise3(vec3(u * 8.0, uSeed, uTime * 0.08));

    // Zwei Kometenkoepfe mit Schweif, gegenlaeufig unterschiedlich schnell.
    float h1 = fract(u - uTime * uSpeed);
    float h2 = fract(0.37 + uSeed * 0.31 - u * 1.0 + uTime * uSpeed * 0.617);
    float comet = exp(-h1 * 5.5) + exp(-h2 * 8.0) * 0.6;

    // Langsame Helligkeitsdrift, damit kein Ring konstant leuchtet.
    float drift = 0.75 + 0.25 * sin(uTime * 0.11 + uSeed * 17.0)
                * cos(uTime * 0.071 + uSeed * 5.0);

    float glow = (0.8 * band * width + comet * 2.0) * profile * uIntensity * drift * 1.25;
    vec3 color = mix(uColorA, uColorB, 0.5 + 0.5 * sin(u * 6.2831 + uSeed * 9.0));
    gl_FragColor = vec4(color * glow, glow);
  }
`;

/** Partikel auf einer Bahn: laufen die Ellipse entlang, flackern, scheren aus. */
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
    // Flackern und gelegentliches Aufleuchten.
    float flicker = 0.65 + 0.35 * sin(uTime * (1.3 + vSeed * 2.1) + vSeed * 61.0);
    float flare = smoothstep(0.985, 1.0, sin(uTime * 0.31 + vSeed * 97.0)) * 2.2;
    float glow = disc * uIntensity * (flicker + flare);
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
    float tw = 0.55 + 0.45 * sin(uTime * (0.7 + vSeed) + vSeed * 40.0);
    float glow = disc * uIntensity * tw * 0.5;
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

  float eye(vec2 p) {
    // Neigung (Fehlerausdruck): inneres Ende hebt sich.
    float c = cos(uAngry * 0.55), s = sin(uAngry * 0.55);
    p = mat2(c, -s, s, c) * p;

    float h = uH * uOpen * max(0.04, uBlink);
    float w = uW * (1.0 + uSquint * 0.15);

    float d = kapsel(p, h, w);

    // Fokus: oben abflachen.
    d = max(d, p.y - h * (1.0 - uSquint * 0.55));

    // Freundlich: ein Halbmond. Von der Kapsel wird dieselbe, nach oben
    // verschobene Form abgezogen - übrig bleibt ein liegender Bogen (u),
    // der bei jedem Wert von uHappy sichtbar bleibt, statt bei vollem
    // Lächeln zu verschwinden.
    if (uHappy > 0.01) {
      float oben = kapsel(p - vec2(0.0, h * 1.1 * uHappy), h, w * 0.9);
      d = max(d, -oben);
    }
    return d;
  }

  void main() {
    vec2 p = (vUv - 0.5) * vec2(0.62, 0.42);
    p -= uLook * 0.03;
    vec2 pr = p - vec2(uDx, 0.0);
    vec2 pl = p + vec2(uDx, 0.0);
    pl.x = -pl.x; // spiegeln, damit die Neigung symmetrisch wirkt
    float d = min(eye(pr), eye(pl));

    float body = smoothstep(0.006, -0.006, d);
    float halo = exp(-max(d, 0.0) * 70.0) * 0.32;
    float glow = (body * 1.25 + halo) * uBright;
    gl_FragColor = vec4(uColor * glow, glow);
  }
`;

const PLANE_VERT = /* glsl */ `
  varying vec2 vUv;
  void main() {
    vUv = uv;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`;

/** Boden-Glow: weiche, elliptische Lichtlache. */
const GROUND_FRAG = /* glsl */ `
  uniform vec3 uColor;
  uniform float uStrength;
  varying vec2 vUv;
  void main() {
    vec2 d = (vUv - 0.5) * vec2(2.0, 3.2);
    float glow = exp(-dot(d, d) * 3.0) * uStrength;
    gl_FragColor = vec4(uColor * glow, glow);
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
  return new THREE.TubeGeometry(curve, 220, tube, 6, true);
}

interface RingBundle {
  group: THREE.Group;
  material: THREE.ShaderMaterial;
  particleMaterial: THREE.ShaderMaterial;
  particles: THREE.Points;
  mesh: THREE.Mesh;
  speed: number;
  gain: number;
  seed: number;
  precession: number;
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
  private readonly shellMaterial: THREE.ShaderMaterial;
  private readonly eyesMaterial: THREE.ShaderMaterial;
  private readonly groundMaterial: THREE.ShaderMaterial;
  private readonly waveMaterial: THREE.ShaderMaterial;
  private readonly dustMaterial: THREE.ShaderMaterial;

  private readonly rings: RingBundle[] = [];
  private readonly dust: THREE.Points;
  private readonly wave: THREE.Mesh;
  private readonly light: THREE.PointLight;

  private readonly geometries: THREE.BufferGeometry[] = [];

  private baseScale = 1.0;
  private floatHeight = 0.0;
  private voiceLevel = 0.0;
  private voiceTarget = 0.0;
  private pointer = new THREE.Vector2(0, 0);
  private pointerActive = false;

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
  private readonly hslHilfe = { h: 0, s: 0, l: 0 };

  constructor(options?: { tempo?: number; helligkeit?: number }, pixelRatio = 1) {
    this.tempoFactor = clampNumber(options?.tempo ?? 1.0, 0.2, 3.0);
    this.brightFactor = clampNumber(options?.helligkeit ?? 1.0, 0.2, 3.0);

    this.group = new THREE.Group();
    this.groundGroup = new THREE.Group();

    const P = ENERGY_PARAMS;

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

    // --- Layer 3: Shell ----------------------------------------------------
    const shellGeo = new THREE.SphereGeometry(P.shellRadius, 40, 26);
    this.geometries.push(shellGeo);
    this.shellMaterial = additiveMaterial(BASIC_VERT, SHELL_FRAG, {
      uColor: { value: new THREE.Color(0x3fb6ff) },
      uIntensity: { value: 0.5 },
    });
    const shell = new THREE.Mesh(shellGeo, this.shellMaterial);
    shell.renderOrder = 2;
    this.group.add(shell);

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
        uGap: { value: 0.34 },
      });
      const mesh = new THREE.Mesh(geo, material);
      mesh.renderOrder = 3;

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
      ringGroup.add(particles);
      this.group.add(ringGroup);

      this.rings.push({
        group: ringGroup,
        material,
        particleMaterial,
        particles,
        mesh,
        speed: def.speed,
        gain: def.gain,
        seed: index * 0.731 + 0.17,
        precession: (index + 1) * 0.021 * (index % 2 === 0 ? 1 : -1),
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

    // --- Boden-Glow ------------------------------------------------------------
    const groundGeo = new THREE.PlaneGeometry(1.0, 1.0);
    this.geometries.push(groundGeo);
    this.groundMaterial = additiveMaterial(PLANE_VERT, GROUND_FRAG, {
      uColor: { value: new THREE.Color(0x2f8fd8) },
      uStrength: { value: ENERGY_PARAMS.ground.strength },
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

  /** Löst einen kurzen Lichtimpuls aus (Aufwachen, Erfolg, Fehler). */
  public flash(strength = 1.0): void {
    this.flashAge = 0.0;
    this.flashStrength = clampNumber(strength, 0, 1.5);
  }

  /**
   * Übernimmt die (bereits weich interpolierten) Zustandswerte.
   */
  public applyAppearance(a: StateAppearance): void {
    const core = this.farbhilfeA.setHex(a.coreColor);
    const glow = this.farbhilfeB.setHex(a.glowColor);
    const particle = this.farbhilfeC.setHex(a.particleColor);
    const bright = this.brightFactor;

    this.coreMaterial.uniforms.uGlow.value.copy(glow);
    this.coreMaterial.uniforms.uGlowStrength.value =
      (0.55 + a.coreGlow * 0.75) * bright;

    this.plasmaMaterial.uniforms.uColorA.value.copy(core);
    // Die zweite Plasmafarbe ist die Zustandsfarbe mit VERSCHOBENEM
    // Farbton: Blau bekommt so den Cyan-Violett-Verlauf des Referenzbildes,
    // Orange bleibt Orange (rotwärts gespreizt) - feste Mischfarben hatten
    // den Arbeitszustand pink gefärbt.
    this.tonVerschieben(glow, 0.10, this.plasmaMaterial.uniforms.uColorB.value as THREE.Color);
    this.plasmaMaterial.uniforms.uFlow.value = a.energyFlow * bright;

    this.shellMaterial.uniforms.uColor.value.copy(glow);
    this.shellMaterial.uniforms.uIntensity.value = 0.20 * a.lightIntensity * bright;

    for (const ring of this.rings) {
      // Beide Bahnfarben aus der Zustandsfarbe, mit gegenläufig
      // verschobenem Farbton und angehobener Helligkeit: leuchtende
      // Plasmabahnen, die die Farbauskunft des Zustands nie verfälschen.
      this.tonVerschieben(core, -0.055, ring.material.uniforms.uColorA.value as THREE.Color, 0.52);
      this.tonVerschieben(glow, 0.085, ring.material.uniforms.uColorB.value as THREE.Color, 0.58);
      ring.material.uniforms.uIntensity.value = ring.gain * a.ringIntensity * bright;
      ring.particleMaterial.uniforms.uColor.value.copy(particle);
      ring.particleMaterial.uniforms.uIntensity.value =
        ring.gain * a.particleIntensity * bright;
    }

    this.dustMaterial.uniforms.uColor.value.copy(particle);
    this.dustMaterial.uniforms.uIntensity.value = 0.5 * a.particleIntensity * bright;

    this.eyesMaterial.uniforms.uColor.value.copy(glow).lerp(this.weiss, 0.55);
    this.eyesMaterial.uniforms.uOpen.value = a.eyeOpen;
    this.eyesMaterial.uniforms.uHappy.value = a.eyeHappy;
    this.eyesMaterial.uniforms.uSquint.value = a.eyeSquint;
    this.eyesMaterial.uniforms.uAngry.value = a.eyeAngry;
    this.eyesMaterial.uniforms.uBright.value = a.eyeBright * bright;

    this.groundMaterial.uniforms.uColor.value.copy(core);
    this.waveMaterial.uniforms.uColor.value.copy(glow);
    this.light.color.copy(core);
    this.light.intensity = 1.6 * a.lightIntensity * bright;
  }

  /**
   * Aktualisiert alle zeitabhängigen Werte.
   */
  public update(elapsed: number, delta: number, a: StateAppearance): void {
    const t = elapsed * this.tempoFactor;

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
          Math.sin(waveT * Math.PI) * 0.9 * this.flashStrength;
      }
    } else {
      this.wave.visible = false;
    }

    // --- Uniform-Zeiten ------------------------------------------------------
    this.coreMaterial.uniforms.uTime.value = t;
    this.coreMaterial.uniforms.uBoost.value = coreBoost + audio * 0.4;
    // Plasma läuft mit der Zustandsgeschwindigkeit – hier arbeitet die Energie.
    this.plasmaMaterial.uniforms.uTime.value = t * (0.7 + a.speed * 0.5);
    this.plasmaMaterial.uniforms.uAudio.value = audio + plasmaBoost;

    for (const ring of this.rings) {
      ring.material.uniforms.uTime.value = t * a.ringSpeed;
      ring.material.uniforms.uIntensity.value =
        ring.gain * a.ringIntensity * this.brightFactor * ringDamp;
      ring.particleMaterial.uniforms.uTime.value = t * a.particleSpeed;

      // Räumliche Präzession: Jede Bahn dreht langsam um eine eigene,
      // leicht wandernde Achse – die Bewegung wiederholt sich nie sichtbar.
      ring.group.rotation.y += delta * ring.precession * a.ringSpeed * this.tempoFactor;
      ring.group.rotation.x += Math.sin(t * 0.043 + ring.seed * 20.0) * delta * 0.012;
      ring.group.rotation.z += Math.cos(t * 0.037 + ring.seed * 31.0) * delta * 0.010;
    }

    this.dustMaterial.uniforms.uTime.value = t * (0.6 + a.speed * 0.4);

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

    // Blick: sehr dezent zur Maus, sonst langsames Umherschauen.
    const look = this.eyesMaterial.uniforms.uLook.value as THREE.Vector2;
    if (this.pointerActive) {
      look.lerp(this.pointer, Math.min(1, delta * 4.0));
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
      ground.position.y = g.y * this.baseScale * 1.7;
    }

    // Gesamtgröße: Grundgröße × sehr subtile Eigenpulsation.
    const pulse = 1.0 + Math.sin(t * 1.07) * a.pulseAmount * 0.5
      + Math.sin(t * 0.61 + 1.3) * a.pulseAmount * 0.3;
    this.group.scale.setScalar(this.baseScale * pulse * (1.0 + coreBoost * 0.05));

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
      const visible = q >= 1 || index < 2;
      ring.mesh.visible = visible;
      ring.particles.visible = visible && (q >= 1 || index < 1);
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
    this.shellMaterial.dispose();
    this.eyesMaterial.dispose();
    this.groundMaterial.dispose();
    this.waveMaterial.dispose();
    this.dustMaterial.dispose();
    for (const ring of this.rings) {
      ring.material.dispose();
      ring.particleMaterial.dispose();
    }
  }
}

function clampNumber(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}
