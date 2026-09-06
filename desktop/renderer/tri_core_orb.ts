/**
 * tri_core_orb.ts – Tri-Core Fusion.
 *
 * Drei kleine, klar gezeichnete Energiekerne bilden den Assistenten. Je
 * nach Zustand ordnen sie sich neu, verschmelzen zu einem grossen Kern und
 * trennen sich wieder. Eine ruhige, fluessige Energiehaut und gekruemmte
 * Stroeme verbinden sie, ohne Nebelflimmern oder hektische Partikel. Dadurch
 * bleibt die Silhouette auch bei kleiner Desktop-Darstellung eindeutig.
 */

import * as THREE from "three";

import type { OrbStateName, StateAppearance } from "./states";

export type OrbEmotionName =
  | "friendly" | "curious" | "surprised"
  | "thoughtful" | "joyful" | "relaxed";

const CORE_VERT = /* glsl */ `
  uniform float uTime;
  uniform float uSeed;
  uniform float uBreath;
  varying vec3 vNormal;
  varying vec3 vView;
  varying vec3 vLocal;
  void main() {
    // Zwei sehr langsame, gegeneinander laufende Oberflaechenwellen lassen
    // den Kern atmen. Die geringe Amplitude verhindert nervoeses Flimmern.
    float organic = sin(position.y * 7.0 + uTime * 0.72 + uSeed * 2.3)
      * sin(position.x * 5.2 - uTime * 0.41 + uSeed) * 0.5 + 0.5;
    float drift = sin(position.z * 8.1 + uTime * 0.29 + uSeed * 4.1) * 0.5 + 0.5;
    float deformation = (organic * 0.021 + drift * 0.011) * uBreath;
    vec3 transformed = position + normal * deformation;
    vLocal = transformed;
    vNormal = normalize(normalMatrix * normal);
    vec4 mv = modelViewMatrix * vec4(transformed, 1.0);
    vView = normalize(-mv.xyz);
    gl_Position = projectionMatrix * mv;
  }
`;

const AURA_FRAG = /* glsl */ `
  uniform vec3 uColor;
  uniform float uOpacity;
  uniform float uTime;
  uniform float uSeed;
  varying vec2 vUv;
  void main() {
    vec2 p = (vUv - 0.5) * 2.0;
    float r = length(p);
    float angle = atan(p.y, p.x);
    float edgeLife = sin(angle * 3.0 + uTime * 0.31 + uSeed)
      * sin(angle * 5.0 - uTime * 0.19 + uSeed * 2.0);
    float radius = 0.68 + edgeLife * 0.035;
    float body = smoothstep(radius, 0.05, r);
    float halo = exp(-r * r * 3.4) * 0.42;
    float alpha = (body * 0.42 + halo * 1.18) * uOpacity;
    gl_FragColor = vec4(uColor, alpha);
  }
`;

const MEMBRANE_FRAG = /* glsl */ `
  uniform vec2 uCoreA;
  uniform vec2 uCoreB;
  uniform vec2 uCoreC;
  uniform vec3 uColorA;
  uniform vec3 uColorB;
  uniform vec3 uColorC;
  uniform float uOpacity;
  uniform float uLife;
  uniform float uTime;
  varying vec2 vUv;

  float influence(vec2 p, vec2 center, float radius) {
    vec2 d = p - center;
    return radius * radius / (dot(d, d) + 0.0022);
  }

  void main() {
    vec2 p = (vUv - 0.5) * 1.55;
    float a = influence(p, uCoreA, 0.175);
    float b = influence(p, uCoreB, 0.175);
    float c = influence(p, uCoreC, 0.175);
    float field = a + b + c;
    float body = smoothstep(0.82, 1.08, field);
    float edge = exp(-abs(field - 0.94) * 4.2);

    float total = max(a + b + c, 0.001);
    vec3 color = (uColorA * a + uColorB * b + uColorC * c) / total;
    // Ruhige Stroeme laufen durch die gemeinsame Haut. Ihre Frequenzen sind
    // absichtlich niedrig: sichtbar lebendig, aber niemals stroboskopartig.
    float flowA = 0.5 + 0.5 * sin(p.x * 13.0 + p.y * 8.0 + uTime * 0.38);
    float flowB = 0.5 + 0.5 * sin(p.y * 17.0 - p.x * 5.0 - uTime * 0.24 + 1.7);
    float vein = smoothstep(0.78, 0.98, flowA * 0.58 + flowB * 0.52);
    vec3 lightColor = mix(color, vec3(0.88, 0.97, 1.0), 0.28 + vein * 0.30);
    float alpha = (body * (0.18 + uLife * 0.18) + edge * 0.34 + vein * body * 0.12)
      * uOpacity;
    if (alpha < 0.004) discard;
    gl_FragColor = vec4(lightColor, min(alpha, 0.62));
  }
`;

const FUSION_MIST_FRAG = /* glsl */ `
  uniform vec3 uColorA;
  uniform vec3 uColorB;
  uniform float uTime;
  uniform float uOpacity;
  uniform float uLayer;
  varying vec3 vNormal;
  varying vec3 vView;
  varying vec3 vLocal;
  void main() {
    float facing = max(dot(normalize(vNormal), normalize(vView)), 0.0);
    vec3 p = normalize(vLocal);
    float broad = 0.5 + 0.5 * sin(
      p.x * 8.7 + p.y * 5.1 + uTime * (0.18 + uLayer * 0.025)
      + sin(p.z * 7.3 - uTime * 0.11) * 1.4
    );
    float crossed = 0.5 + 0.5 * sin(
      p.y * 11.2 - p.z * 6.4 - uTime * (0.13 + uLayer * 0.018)
      + sin(p.x * 9.1 + uTime * 0.08) * 1.2
    );
    float ridgeA = 1.0 - abs(broad * 2.0 - 1.0);
    float ridgeB = 1.0 - abs(crossed * 2.0 - 1.0);
    float cloud = smoothstep(0.58, 0.90, broad * 0.64 + crossed * 0.42);
    float fibres = smoothstep(0.78, 0.965, ridgeA * 0.70 + ridgeB * 0.48);
    float depth = mix(0.10, 1.0, pow(1.0 - facing, 0.68));
    float strength = (cloud * 0.12 + fibres * 0.58) * depth * uOpacity;
    vec3 color = mix(uColorA, uColorB, crossed * 0.62 + fibres * 0.24);
    if (strength < 0.004) discard;
    gl_FragColor = vec4(color, min(strength, 0.38));
  }
`;

const FUSION_SHELL_FRAG = /* glsl */ `
  uniform vec3 uColorA;
  uniform vec3 uColorB;
  uniform float uTime;
  uniform float uOpacity;
  varying vec3 vNormal;
  varying vec3 vView;
  varying vec3 vLocal;
  void main() {
    float facing = max(dot(normalize(vNormal), normalize(vView)), 0.0);
    float rim = pow(1.0 - facing, 2.05);
    vec3 p = normalize(vLocal);
    float currentA = 0.5 + 0.5 * sin(p.x * 15.0 + p.y * 8.0 + uTime * 0.16);
    float currentB = 0.5 + 0.5 * sin(p.y * 17.0 - p.z * 10.0 - uTime * 0.12 + 1.4);
    float network = smoothstep(0.86, 0.985, currentA * 0.60 + currentB * 0.52);
    float strength = (rim * 0.66 + network * (0.10 + rim * 0.34)) * uOpacity;
    vec3 color = mix(uColorA, uColorB, currentB * 0.48 + network * 0.18);
    if (strength < 0.004) discard;
    gl_FragColor = vec4(color, min(strength, 0.54));
  }
`;

const CORE_FRAG = /* glsl */ `
  uniform vec3 uColor;
  uniform vec3 uColorB;
  uniform vec3 uColorC;
  uniform float uOpacity;
  uniform float uEnergy;
  uniform float uFluidMix;
  uniform float uTime;
  varying vec3 vNormal;
  varying vec3 vView;
  varying vec3 vLocal;
  void main() {
    float facing = max(dot(normalize(vNormal), normalize(vView)), 0.0);
    float rim = pow(1.0 - facing, 2.2);
    float highlight = pow(facing, 5.0);
    // Im Fusionskern bleiben alle drei Identitäten sichtbar. Zwei langsam
    // gegeneinander driftende Felder mischen Blau, Rot und Gelb wie
    // Flüssigkeiten; kleine Einzelkerne setzen uFluidMix auf null.
    float waveA = sin(
      vLocal.x * 13.1 + vLocal.y * 5.7 + uTime * 0.34
      + sin(vLocal.z * 9.1 - uTime * 0.19) * 1.8
    );
    float waveB = sin(
      vLocal.y * 11.7 - vLocal.z * 7.9 - uTime * 0.27
      + sin(vLocal.x * 8.4 + uTime * 0.15) * 1.6
    );
    float waveC = sin(
      (vLocal.x - vLocal.z) * 9.6 + vLocal.y * 4.3 + uTime * 0.21
      + waveA * 0.8
    );
    float fieldA = 0.18 + pow(abs(waveA), 1.5);
    float fieldB = 0.18 + pow(abs(waveB), 1.5);
    float fieldC = 0.18 + pow(abs(waveC), 1.5);
    float fieldSum = fieldA * 1.22 + fieldB + fieldC;
    vec3 fluid = (uColor * fieldA * 1.22 + uColorB * fieldB + uColorC * fieldC) / fieldSum;
    vec3 identity = mix(uColor, fluid, uFluidMix);
    vec3 pale = mix(identity, vec3(0.92, 0.98, 1.0), 0.42);
    float vein = smoothstep(0.70, 0.97, abs(waveA * 0.52 + waveB * 0.34 + waveC * 0.28));
    float depth = 0.30 + facing * 0.62;
    vec3 color = identity * depth
      + pale * rim * 0.78
      + vec3(1.0) * highlight * 0.20
      + mix(pale, vec3(1.0), 0.38) * vein * (0.20 + uFluidMix * 0.34);
    gl_FragColor = vec4(color * uEnergy, uOpacity);
  }
`;

const PLANE_VERT = /* glsl */ `
  varying vec2 vUv;
  void main() {
    vUv = uv;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`;

const FACE_FRAG = /* glsl */ `
  uniform vec3 uColor;
  uniform vec3 uGlassColor;
  uniform vec2 uLook;
  uniform float uOpacity;
  uniform float uOpen;
  uniform float uHappy;
  uniform float uAngry;
  uniform float uQuestion;
  uniform float uAlert;
  uniform float uProfessor;
  varying vec2 vUv;

  float segment(vec2 p, vec2 a, vec2 b) {
    vec2 pa = p - a, ba = b - a;
    float h = clamp(dot(pa, ba) / dot(ba, ba), 0.0, 1.0);
    return length(pa - ba * h);
  }

  float capsule(vec2 p, float halfHeight, float width) {
    p.y -= clamp(p.y, -halfHeight, halfHeight);
    return length(p) - width;
  }

  void main() {
    // Grössere Zeichenfläche für den kleinen Fusionskern. Die Augen nehmen
    // bewusst mehr Raum ein als beim früheren grossen Energy-Orb.
    vec2 p = (vUv - 0.5) * vec2(0.58, 0.42);
    p -= uLook * 0.035;
    float symbolMix = max(uQuestion, uAlert);

    vec2 left = p + vec2(0.098, 0.0);
    vec2 right = p - vec2(0.098, 0.0);
    float tilt = uAngry * 0.48;
    mat2 leftRotation = mat2(cos(tilt), -sin(tilt), sin(tilt), cos(tilt));
    mat2 rightRotation = mat2(cos(-tilt), -sin(-tilt), sin(-tilt), cos(-tilt));
    float dLeft = capsule(leftRotation * left, 0.072 * uOpen, 0.039);
    float dRight = capsule(rightRotation * right, 0.072 * uOpen, 0.039);
    float dEyes = min(dLeft, dRight);

    if (uHappy > 0.05) {
      float smileLeft = abs(length(left - vec2(0.0, -0.035)) - 0.060) - 0.009;
      float smileRight = abs(length(right - vec2(0.0, -0.035)) - 0.060) - 0.009;
      smileLeft = max(smileLeft, -(left.y + 0.025));
      smileRight = max(smileRight, -(right.y + 0.025));
      dEyes = mix(dEyes, min(smileLeft, smileRight), uHappy);
    }

    float questionHead = abs(length(p - vec2(0.0, 0.055)) - 0.072) - 0.012;
    questionHead = max(questionHead, -(p.x + p.y * 0.55 + 0.018));
    float questionHook = segment(p, vec2(0.052, 0.020), vec2(0.0, -0.050)) - 0.012;
    float questionDot = length(p - vec2(0.0, -0.125)) - 0.014;
    float dQuestion = min(questionHead, min(questionHook, questionDot));

    float alertBar = segment(p, vec2(0.0, 0.120), vec2(0.0, -0.045)) - 0.016;
    float alertDot = length(p - vec2(0.0, -0.130)) - 0.017;
    float dAlert = min(alertBar, alertDot);
    float dSymbol = mix(dQuestion, dAlert, uAlert);
    float dFace = mix(dEyes, dSymbol, symbolMix);
    float body = smoothstep(0.008, -0.008, dFace);
    float outline = smoothstep(0.024, 0.002, dFace);
    float edge = exp(-max(dFace, 0.0) * 58.0) * 0.28;

    float glassRadius = 0.118;
    float glassLeft = abs(length(p + vec2(0.135, 0.0)) - glassRadius) - 0.009;
    float glassRight = abs(length(p - vec2(0.135, 0.0)) - glassRadius) - 0.009;
    float bridge = segment(p, vec2(-0.020, 0.012), vec2(0.020, 0.012)) - 0.007;
    float glasses = min(glassLeft, min(glassRight, bridge));
    float glassBody = smoothstep(0.008, -0.008, glasses) * uProfessor;

    vec3 eyeShadow = vec3(0.008, 0.035, 0.085) * outline;
    vec3 color = eyeShadow + uColor * (body * 1.35 + edge * 0.72) + uGlassColor * glassBody;
    float alpha = max(max(outline * 0.94, body + edge), glassBody) * uOpacity;
    gl_FragColor = vec4(color, alpha);
  }
`;

const GROUND_FRAG = /* glsl */ `
  uniform vec3 uColorA;
  uniform vec3 uColorB;
  uniform vec3 uColorC;
  uniform float uFusion;
  uniform float uOpacity;
  varying vec2 vUv;
  void main() {
    vec2 p = (vUv - 0.5) * vec2(2.0, 7.0);
    float left = exp(-dot(p - vec2(-0.34, 0.0), p - vec2(-0.34, 0.0)) * 7.0);
    float right = exp(-dot(p - vec2(0.34, 0.0), p - vec2(0.34, 0.0)) * 7.0);
    float middle = exp(-dot(p, p) * mix(10.0, 4.8, uFusion));
    vec3 color = uColorA * left + uColorB * right + uColorC * middle;
    float alpha = (left + right + middle * (0.65 + uFusion * 0.7)) * 0.16 * uOpacity;
    gl_FragColor = vec4(color * 0.34, min(alpha, 0.22));
  }
`;

const PROGRESS_FRAG = /* glsl */ `
  uniform vec3 uColor;
  uniform float uProgress;
  uniform float uOpacity;
  uniform float uTime;
  varying vec2 vUv;
  void main() {
    vec2 p = (vUv - 0.5) * 2.0;
    float radius = length(p);
    float ring = 1.0 - smoothstep(0.012, 0.035, abs(radius - 0.78));
    float angle = mod(atan(p.y, p.x) + 1.5707963 + 6.2831853, 6.2831853) / 6.2831853;
    float arc = uProgress >= 0.0
      ? step(angle, uProgress)
      : smoothstep(0.16, 0.0, abs(fract(angle - uTime * 0.15 + 0.5) - 0.5));
    float glow = ring * arc * uOpacity;
    gl_FragColor = vec4(uColor, glow);
  }
`;

function clamp(value: number, low: number, high: number): number {
  return Math.max(low, Math.min(high, value));
}

function synapseArcGeometry(seed: number): THREE.TubeGeometry {
  const points = Array.from({ length: 10 }, (_, index) => {
    const phase = index / 9;
    const radius = 0.30 + phase * 0.20;
    const envelope = Math.sin(phase * Math.PI);
    const angle = Math.sin(phase * 19.0 + seed * 11.0) * 0.13 * envelope;
    return new THREE.Vector3(
      Math.cos(angle) * radius,
      Math.sin(angle) * radius + Math.sin(phase * 31.0 + seed * 7.0) * 0.018 * envelope,
      Math.sin(phase * 23.0 + seed * 13.0) * 0.026 * envelope,
    );
  });
  const curve = new THREE.CatmullRomCurve3(points, false, "catmullrom", 0.16);
  return new THREE.TubeGeometry(curve, 42, 0.012, 5, false);
}

function makeCoreMaterial(color: number): THREE.ShaderMaterial {
  return new THREE.ShaderMaterial({
    vertexShader: CORE_VERT,
    fragmentShader: CORE_FRAG,
    uniforms: {
      uColor: { value: new THREE.Color(color) },
      uColorB: { value: new THREE.Color(color) },
      uColorC: { value: new THREE.Color(color) },
      uOpacity: { value: 1.0 },
      uEnergy: { value: 1.0 },
      uFluidMix: { value: 0.0 },
      uTime: { value: 0.0 },
      uSeed: { value: color / 0xffffff },
      uBreath: { value: 1.0 },
    },
    transparent: true,
    depthWrite: true,
    blending: THREE.NormalBlending,
  });
}

interface CoreBundle {
  mesh: THREE.Mesh;
  material: THREE.ShaderMaterial;
  aura: THREE.Mesh;
  auraMaterial: THREE.ShaderMaterial;
  position: THREE.Vector3;
  target: THREE.Vector3;
  velocity: THREE.Vector3;
  baseColor: THREE.Color;
  phaseDrift: number;
  phaseDriftTarget: number;
  radiusDrift: number;
  radiusDriftTarget: number;
}

export class TriCoreOrb {
  public readonly group = new THREE.Group();
  public readonly groundGroup = new THREE.Group();

  private readonly cores: CoreBundle[] = [];
  private readonly fusedAura: THREE.Mesh;
  private readonly fusedAuraMaterial: THREE.ShaderMaterial;
  private readonly fusionMistInner: THREE.Mesh;
  private readonly fusionMistOuter: THREE.Mesh;
  private readonly fusionMistInnerMaterial: THREE.ShaderMaterial;
  private readonly fusionMistOuterMaterial: THREE.ShaderMaterial;
  private readonly fusionShell: THREE.Mesh;
  private readonly fusionShellMaterial: THREE.ShaderMaterial;
  private readonly synapseArcs: Array<{
    group: THREE.Group;
    material: THREE.MeshBasicMaterial;
    active: boolean;
    age: number;
    duration: number;
  }> = [];
  private readonly membrane: THREE.Mesh;
  private readonly membraneMaterial: THREE.ShaderMaterial;
  private readonly fusedCore: THREE.Mesh;
  private readonly fusedMaterial: THREE.ShaderMaterial;
  private readonly linkGeometry: THREE.BufferGeometry;
  private readonly linkMaterial: THREE.LineBasicMaterial;
  private readonly links: THREE.LineSegments;
  private readonly faceMaterial: THREE.ShaderMaterial;
  private readonly face: THREE.Mesh;
  private readonly glassesGroup = new THREE.Group();
  private readonly progressMaterial: THREE.ShaderMaterial;
  private readonly progress: THREE.Mesh;
  private readonly groundMaterial: THREE.ShaderMaterial;
  private readonly wave: THREE.Mesh;
  private readonly waveMaterial: THREE.MeshBasicMaterial;
  private readonly geometries: THREE.BufferGeometry[] = [];
  private readonly materials: THREE.Material[] = [];

  private baseScale = 1.0;
  private state: OrbStateName = "idle";
  private fusion = 0.08;
  private fusionTarget = 0.08;
  private voiceLevel = 0.0;
  private voiceTarget = 0.0;
  private floatHeight = 0.0;
  private pointer = new THREE.Vector2();
  private pointerTarget = new THREE.Vector2();
  private pointerActive = false;
  /** Fortlaufende Formation statt Winkel aus absoluter Laufzeit. */
  private formationPhase = 0.0;
  private formationSpeed = 0.045;
  /** Unregelmaessige, aber weich ueberblendete soziale Gesten. */
  private gestureIn = 1.8;
  private socialMix = 0.12;
  private socialTarget = 0.12;
  private gestureLead = 0;
  private synapseIn = 1.4 + Math.random() * 2.8;
  private readonly motionDelta = new THREE.Vector3();
  private readonly pointerOffset = new THREE.Vector3();
  private readonly lookTarget = new THREE.Vector2();
  private professorMix = 0.0;
  private professorTarget = 0.0;
  private emotion: OrbEmotionName | null = null;
  private emotionUntil = 0.0;
  private flashAge = 99.0;
  private flashStrength = 0.0;
  private reactionAge = 99.0;
  private reactionKind: "click" | "surprise" = "click";
  private reactionBaseY = 0.0;
  private blinkIn = 3.0;
  private blinkPhase = -1.0;
  private progressValue: number | null = null;
  private progressIndeterminate = false;
  private currentAppearance: StateAppearance | null = null;
  private readonly tempo: number;
  private readonly brightness: number;

  /** Feste Identitäten – Zustände verändern Bewegung und Helligkeit, nicht die Farbe. */
  private readonly blue = new THREE.Color(0x1688ff);
  private readonly red = new THREE.Color(0xff4054);
  private readonly yellow = new THREE.Color(0xffd23f);
  private readonly fusionBlue = new THREE.Color(0x087dff);
  private readonly fusionCyan = new THREE.Color(0x43ddff);
  private readonly fusionViolet = new THREE.Color(0x7556ff);

  constructor(options?: { tempo?: number; helligkeit?: number }, _pixelRatio = 1) {
    this.tempo = clamp(options?.tempo ?? 1.0, 0.25, 2.5);
    this.brightness = clamp(options?.helligkeit ?? 1.0, 0.35, 1.8);

    const smallGeometry = new THREE.SphereGeometry(0.155, 32, 22);
    const auraGeometry = new THREE.PlaneGeometry(0.58, 0.58);
    this.geometries.push(smallGeometry);
    this.geometries.push(auraGeometry);
    const initial = [
      new THREE.Vector3(-0.34, -0.12, 0.02),
      new THREE.Vector3(0.34, -0.12, 0.01),
      new THREE.Vector3(0.0, 0.31, 0.03),
    ];
    [this.blue, this.red, this.yellow].forEach((color, index) => {
      const auraMaterial = new THREE.ShaderMaterial({
        vertexShader: PLANE_VERT,
        fragmentShader: AURA_FRAG,
        uniforms: {
          uColor: { value: color.clone() },
          uOpacity: { value: 0.42 },
          uTime: { value: 0.0 },
          uSeed: { value: index * 2.17 + 0.4 },
        },
        transparent: true,
        depthWrite: false,
        depthTest: false,
        blending: THREE.AdditiveBlending,
      });
      this.materials.push(auraMaterial);
      const aura = new THREE.Mesh(auraGeometry, auraMaterial);
      aura.position.copy(initial[index]);
      aura.position.z = -0.01 + index * 0.002;
      aura.renderOrder = 0;
      this.group.add(aura);

      const material = makeCoreMaterial(color.getHex());
      this.materials.push(material);
      const mesh = new THREE.Mesh(smallGeometry, material);
      mesh.position.copy(initial[index]);
      mesh.renderOrder = 3;
      this.group.add(mesh);
      this.cores.push({
        mesh,
        material,
        aura,
        auraMaterial,
        position: initial[index].clone(),
        target: initial[index].clone(),
        velocity: new THREE.Vector3(),
        baseColor: color.clone(),
        phaseDrift: 0.0,
        phaseDriftTarget: 0.0,
        radiusDrift: 1.0,
        radiusDriftTarget: 1.0,
      });
    });

    this.fusedAuraMaterial = new THREE.ShaderMaterial({
      vertexShader: PLANE_VERT,
      fragmentShader: AURA_FRAG,
      uniforms: {
        uColor: { value: new THREE.Color(0x6acfff) },
        uOpacity: { value: 0.0 },
        uTime: { value: 0.0 },
        uSeed: { value: 4.7 },
      },
      transparent: true,
      depthWrite: false,
      depthTest: false,
      blending: THREE.AdditiveBlending,
    });
    this.materials.push(this.fusedAuraMaterial);
    this.fusedAura = new THREE.Mesh(auraGeometry, this.fusedAuraMaterial);
    this.fusedAura.position.z = -0.025;
    this.fusedAura.renderOrder = 0;
    this.group.add(this.fusedAura);

    // Der verschmolzene Orb ist wieder mehrschichtig aufgebaut: ein
    // kompakter Kern, zwei feine Nebelschalen und eine groessere Aussenhaut.
    const fusedGeometry = new THREE.SphereGeometry(0.31, 40, 28);
    this.geometries.push(fusedGeometry);
    this.fusedMaterial = makeCoreMaterial(0x2d9dff);
    (this.fusedMaterial.uniforms.uColor.value as THREE.Color).copy(this.fusionBlue);
    (this.fusedMaterial.uniforms.uColorB.value as THREE.Color).copy(this.fusionCyan);
    (this.fusedMaterial.uniforms.uColorC.value as THREE.Color).copy(this.fusionViolet);
    this.fusedMaterial.uniforms.uFluidMix.value = 1.0;
    this.fusedMaterial.uniforms.uOpacity.value = 0.0;
    this.materials.push(this.fusedMaterial);
    this.fusedCore = new THREE.Mesh(fusedGeometry, this.fusedMaterial);
    this.fusedCore.renderOrder = 4;
    this.group.add(this.fusedCore);

    const mistInnerGeometry = new THREE.SphereGeometry(0.38, 36, 24);
    const mistOuterGeometry = new THREE.SphereGeometry(0.43, 36, 24);
    const shellGeometry = new THREE.SphereGeometry(0.50, 42, 28);
    this.geometries.push(mistInnerGeometry, mistOuterGeometry, shellGeometry);
    const makeMistMaterial = (layer: number): THREE.ShaderMaterial => new THREE.ShaderMaterial({
      vertexShader: CORE_VERT,
      fragmentShader: FUSION_MIST_FRAG,
      uniforms: {
        uColorA: { value: this.fusionBlue.clone() },
        uColorB: { value: layer < 0.5 ? this.fusionCyan.clone() : this.fusionViolet.clone() },
        uTime: { value: 0.0 },
        uOpacity: { value: 0.0 },
        uLayer: { value: layer },
        uSeed: { value: 5.1 + layer },
        uBreath: { value: 0.20 },
      },
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    });
    this.fusionMistInnerMaterial = makeMistMaterial(0.0);
    this.fusionMistOuterMaterial = makeMistMaterial(1.0);
    this.materials.push(this.fusionMistInnerMaterial, this.fusionMistOuterMaterial);
    this.fusionMistInner = new THREE.Mesh(mistInnerGeometry, this.fusionMistInnerMaterial);
    this.fusionMistOuter = new THREE.Mesh(mistOuterGeometry, this.fusionMistOuterMaterial);
    this.fusionMistInner.renderOrder = 5;
    this.fusionMistOuter.renderOrder = 5;
    this.group.add(this.fusionMistInner, this.fusionMistOuter);

    this.fusionShellMaterial = new THREE.ShaderMaterial({
      vertexShader: CORE_VERT,
      fragmentShader: FUSION_SHELL_FRAG,
      uniforms: {
        uColorA: { value: this.fusionCyan.clone() },
        uColorB: { value: this.fusionViolet.clone() },
        uTime: { value: 0.0 },
        uOpacity: { value: 0.0 },
        uSeed: { value: 7.4 },
        uBreath: { value: 0.10 },
      },
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    });
    this.materials.push(this.fusionShellMaterial);
    this.fusionShell = new THREE.Mesh(shellGeometry, this.fusionShellMaterial);
    this.fusionShell.renderOrder = 6;
    this.group.add(this.fusionShell);

    [0.17, 0.43, 0.79, 1.11].forEach((seed) => {
      const geometry = synapseArcGeometry(seed);
      this.geometries.push(geometry);
      const material = new THREE.MeshBasicMaterial({
        color: seed > 0.7 ? 0xff4a38 : 0xffa43b,
        transparent: true,
        opacity: 0.0,
        depthWrite: false,
        depthTest: false,
        blending: THREE.AdditiveBlending,
      });
      this.materials.push(material);
      const mesh = new THREE.Mesh(geometry, material);
      mesh.renderOrder = 7;
      const arcGroup = new THREE.Group();
      arcGroup.visible = false;
      arcGroup.add(mesh);
      this.group.add(arcGroup);
      this.synapseArcs.push({ group: arcGroup, material, active: false, age: 99, duration: 0.4 });
    });

    const membraneGeometry = new THREE.PlaneGeometry(1.55, 1.55);
    this.geometries.push(membraneGeometry);
    this.membraneMaterial = new THREE.ShaderMaterial({
      vertexShader: PLANE_VERT,
      fragmentShader: MEMBRANE_FRAG,
      uniforms: {
        uCoreA: { value: new THREE.Vector2(initial[0].x, initial[0].y) },
        uCoreB: { value: new THREE.Vector2(initial[1].x, initial[1].y) },
        uCoreC: { value: new THREE.Vector2(initial[2].x, initial[2].y) },
        uColorA: { value: this.blue.clone() },
        uColorB: { value: this.red.clone() },
        uColorC: { value: this.yellow.clone() },
        uOpacity: { value: 1.0 },
        uLife: { value: this.socialMix },
        uTime: { value: 0.0 },
      },
      transparent: true,
      depthWrite: false,
      depthTest: false,
      blending: THREE.AdditiveBlending,
    });
    this.materials.push(this.membraneMaterial);
    this.membrane = new THREE.Mesh(membraneGeometry, this.membraneMaterial);
    this.membrane.position.z = -0.018;
    this.membrane.renderOrder = 1;
    this.group.add(this.membrane);

    this.linkGeometry = new THREE.BufferGeometry();
    // Je Verbindung mehrere kurze Segmente: daraus entstehen gebogene,
    // wandernde Energiestroeme statt eines statischen Dreiecks.
    this.linkGeometry.setAttribute("position", new THREE.BufferAttribute(new Float32Array(3 * 18 * 2 * 3), 3));
    this.linkGeometry.setAttribute("color", new THREE.BufferAttribute(new Float32Array(3 * 18 * 2 * 3), 3));
    this.geometries.push(this.linkGeometry);
    this.linkMaterial = new THREE.LineBasicMaterial({
      color: 0x69dcff,
      transparent: true,
      opacity: 0.34,
      vertexColors: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    });
    this.materials.push(this.linkMaterial);
    this.links = new THREE.LineSegments(this.linkGeometry, this.linkMaterial);
    this.links.renderOrder = 2;
    this.group.add(this.links);

    const faceGeometry = new THREE.PlaneGeometry(0.94, 0.72);
    this.geometries.push(faceGeometry);
    this.faceMaterial = new THREE.ShaderMaterial({
      vertexShader: PLANE_VERT,
      fragmentShader: FACE_FRAG,
      uniforms: {
        uColor: { value: new THREE.Color(0xe8fbff) },
        uGlassColor: { value: new THREE.Color(0xffcf72) },
        uLook: { value: new THREE.Vector2() },
        uOpacity: { value: 0.0 },
        uOpen: { value: 1.0 },
        uHappy: { value: 0.0 },
        uAngry: { value: 0.0 },
        uQuestion: { value: 0.0 },
        uAlert: { value: 0.0 },
        uProfessor: { value: 0.0 },
      },
      transparent: true,
      depthWrite: false,
      depthTest: false,
      blending: THREE.NormalBlending,
    });
    this.materials.push(this.faceMaterial);
    this.face = new THREE.Mesh(faceGeometry, this.faceMaterial);
    this.face.position.z = 0.515;
    this.face.renderOrder = 8;
    this.group.add(this.face);

    // Zwei reale, schmale Ringe machen den Professormodus auch dann lesbar,
    // wenn die drei Kerne gerade getrennt sind.
    const glassGeometry = new THREE.TorusGeometry(0.155, 0.012, 10, 48);
    this.geometries.push(glassGeometry);
    const glassMaterial = new THREE.MeshBasicMaterial({
      color: 0xffcf72,
      transparent: true,
      opacity: 0.0,
      depthWrite: false,
      depthTest: false,
    });
    this.materials.push(glassMaterial);
    const leftGlass = new THREE.Mesh(glassGeometry, glassMaterial);
    const rightGlass = new THREE.Mesh(glassGeometry, glassMaterial);
    leftGlass.renderOrder = 9;
    rightGlass.renderOrder = 9;
    leftGlass.position.x = -0.175;
    rightGlass.position.x = 0.175;
    const bridgeGeometry = new THREE.PlaneGeometry(0.052, 0.016);
    this.geometries.push(bridgeGeometry);
    const bridge = new THREE.Mesh(bridgeGeometry, glassMaterial);
    bridge.renderOrder = 9;
    bridge.position.z = 0.01;
    this.glassesGroup.add(leftGlass, rightGlass, bridge);
    this.glassesGroup.position.z = 0.545;
    this.glassesGroup.renderOrder = 9;
    this.group.add(this.glassesGroup);

    const progressGeometry = new THREE.PlaneGeometry(1.18, 1.18);
    this.geometries.push(progressGeometry);
    this.progressMaterial = new THREE.ShaderMaterial({
      vertexShader: PLANE_VERT,
      fragmentShader: PROGRESS_FRAG,
      uniforms: {
        uColor: { value: new THREE.Color(0x62dcff) },
        uProgress: { value: 0.0 },
        uOpacity: { value: 0.0 },
        uTime: { value: 0.0 },
      },
      transparent: true,
      depthWrite: false,
      depthTest: false,
      blending: THREE.NormalBlending,
    });
    this.materials.push(this.progressMaterial);
    this.progress = new THREE.Mesh(progressGeometry, this.progressMaterial);
    this.progress.position.z = 0.38;
    this.progress.renderOrder = 4;
    this.group.add(this.progress);

    const waveGeometry = new THREE.RingGeometry(0.46, 0.475, 64);
    this.geometries.push(waveGeometry);
    this.waveMaterial = new THREE.MeshBasicMaterial({
      color: 0x6fe5ff,
      transparent: true,
      opacity: 0.0,
      depthWrite: false,
    });
    this.materials.push(this.waveMaterial);
    this.wave = new THREE.Mesh(waveGeometry, this.waveMaterial);
    this.wave.position.z = 0.36;
    this.wave.visible = false;
    this.group.add(this.wave);

    const groundGeometry = new THREE.PlaneGeometry(1.45, 0.55);
    this.geometries.push(groundGeometry);
    this.groundMaterial = new THREE.ShaderMaterial({
      vertexShader: PLANE_VERT,
      fragmentShader: GROUND_FRAG,
      uniforms: {
        uColorA: { value: this.blue.clone() },
        uColorB: { value: this.red.clone() },
        uColorC: { value: this.yellow.clone() },
        uFusion: { value: this.fusion },
        uOpacity: { value: 1.0 },
      },
      transparent: true,
      depthWrite: false,
      blending: THREE.NormalBlending,
    });
    this.materials.push(this.groundMaterial);
    const ground = new THREE.Mesh(groundGeometry, this.groundMaterial);
    ground.rotation.x = -Math.PI / 2;
    ground.position.y = -0.59;
    this.groundGroup.add(ground);
  }

  public setBaseScale(scale: number): void {
    this.baseScale = clamp(scale, 0.08, 2.5);
  }

  public setVoiceLevel(level: number): void {
    this.voiceTarget = clamp(level, 0.0, 1.0);
  }

  public setFloatHeight(y: number): void {
    this.floatHeight = y;
  }

  public setPointer(x: number, y: number, active: boolean): void {
    this.pointerTarget.set(clamp(x, -1, 1), clamp(y, -1, 1));
    this.pointerActive = active;
  }

  public setState(state: OrbStateName): void {
    this.state = state;
  }

  public setProfessorMode(active: boolean): void {
    this.professorTarget = active ? 1.0 : 0.0;
  }

  public setEmotion(emotion: OrbEmotionName | null, seconds = 2.4): void {
    this.emotion = emotion;
    this.emotionUntil = performance.now() + Math.max(0.2, seconds) * 1000;
  }

  public react(kind: "click" | "surprise"): void {
    this.reactionKind = kind;
    this.reactionAge = 0.0;
    this.reactionBaseY = this.group.position.y;
  }

  public flash(strength = 1.0): void {
    this.flashAge = 0.0;
    this.flashStrength = clamp(strength, 0.0, 2.0);
  }

  public setProgress(progress: number | null, indeterminate = false): void {
    this.progressValue = progress === null ? null : clamp(progress, 0.0, 1.0);
    this.progressIndeterminate = indeterminate;
  }

  public applyAppearance(appearance: StateAppearance): void {
    this.currentAppearance = appearance;
    this.cores.forEach((core) => {
      (core.material.uniforms.uColor.value as THREE.Color)
        .copy(core.baseColor);
      (core.material.uniforms.uColorB.value as THREE.Color).copy(core.baseColor);
      (core.material.uniforms.uColorC.value as THREE.Color).copy(core.baseColor);
      core.material.uniforms.uEnergy.value =
        clamp((0.76 + appearance.lightIntensity * 0.28) * this.brightness, 0.48, 1.30);
    });
    (this.fusedMaterial.uniforms.uColor.value as THREE.Color).copy(this.fusionBlue);
    (this.fusedMaterial.uniforms.uColorB.value as THREE.Color).copy(this.fusionCyan);
    (this.fusedMaterial.uniforms.uColorC.value as THREE.Color).copy(this.fusionViolet);
    this.fusedMaterial.uniforms.uEnergy.value =
      clamp((0.88 + appearance.coreGlow * 0.20) * this.brightness, 0.65, 1.35);
    (this.faceMaterial.uniforms.uColor.value as THREE.Color)
      .setHex(appearance.glowColor).lerp(new THREE.Color(0xffffff), 0.82);
    this.faceMaterial.uniforms.uOpen.value = appearance.eyeOpen;
    this.faceMaterial.uniforms.uHappy.value = appearance.eyeHappy;
    this.faceMaterial.uniforms.uAngry.value = appearance.eyeAngry;
    this.faceMaterial.uniforms.uQuestion.value = appearance.eyeQuestion;
    this.faceMaterial.uniforms.uAlert.value = appearance.eyeAlert;
    // Die Stroeme behalten die Farben der verbundenen Kerne.
    this.linkMaterial.color.setHex(0xffffff);
    this.progressMaterial.uniforms.uColor.value.setHex(appearance.glowColor);
    this.waveMaterial.color.setHex(appearance.glowColor);
  }

  private targetsForState(): [THREE.Vector3, THREE.Vector3, THREE.Vector3, number] {
    const professor = this.professorMix > 0.35;
    if (professor) {
      // Beim Erklaeren bleibt der Professor ein vollstaendiger Orb mit
      // Augen und Brille. In ruhigen Denkphasen duerfen die drei Kerne
      // weiterhin als eigene, gemeinsam bebrillte Formation erscheinen.
      if (this.state === "speaking") {
        return [new THREE.Vector3(), new THREE.Vector3(), new THREE.Vector3(), 0.94];
      }
      if (this.state === "busy" || this.state === "executing") {
        return [new THREE.Vector3(), new THREE.Vector3(), new THREE.Vector3(), 1.0];
      }
      return [
        new THREE.Vector3(-0.175, 0.0, 0.02),
        new THREE.Vector3(0.175, 0.0, 0.02),
        new THREE.Vector3(0.0, 0.33, 0.03),
        0.04,
      ];
    }
    switch (this.state) {
      case "listening":
        return [
          new THREE.Vector3(-0.43, 0.02, 0.02),
          new THREE.Vector3(0.23, -0.20, 0.01),
          new THREE.Vector3(0.16, 0.30, 0.03),
          0.05,
        ];
      case "thinking":
        return [
          new THREE.Vector3(-0.45, -0.20, 0.02),
          new THREE.Vector3(0.45, -0.20, 0.01),
          new THREE.Vector3(0.0, 0.45, 0.03),
          0.0,
        ];
      case "speaking":
        return [new THREE.Vector3(), new THREE.Vector3(), new THREE.Vector3(), 0.92];
      case "busy":
      case "executing":
        return [new THREE.Vector3(), new THREE.Vector3(), new THREE.Vector3(), 1.0];
      case "waiting":
        return [
          new THREE.Vector3(0.0, 0.31, 0.02),
          new THREE.Vector3(0.12, 0.02, 0.01),
          new THREE.Vector3(0.0, -0.30, 0.03),
          0.36,
        ];
      case "warning":
        return [
          new THREE.Vector3(0.0, 0.32, 0.02),
          new THREE.Vector3(0.0, 0.02, 0.01),
          new THREE.Vector3(0.0, -0.31, 0.03),
          0.24,
        ];
      case "error":
        return [
          new THREE.Vector3(-0.29, 0.18, 0.02),
          new THREE.Vector3(0.29, 0.18, 0.01),
          new THREE.Vector3(0.0, -0.28, 0.03),
          0.15,
        ];
      case "success":
        return [
          new THREE.Vector3(-0.32, -0.10, 0.02),
          new THREE.Vector3(0.32, -0.10, 0.01),
          new THREE.Vector3(0.0, 0.33, 0.03),
          0.18,
        ];
      case "offline":
      case "sleep":
        return [
          new THREE.Vector3(-0.24, -0.10, 0.02),
          new THREE.Vector3(0.24, -0.10, 0.01),
          new THREE.Vector3(0.0, 0.22, 0.03),
          0.0,
        ];
      default:
        return [
          new THREE.Vector3(-0.34, -0.12, 0.02),
          new THREE.Vector3(0.34, -0.12, 0.01),
          new THREE.Vector3(0.0, 0.31, 0.03),
          0.08,
        ];
    }
  }

  public update(elapsed: number, delta: number, appearance: StateAppearance): void {
    const t = elapsed * this.tempo;
    const ease = 1.0 - Math.exp(-delta * 3.25);
    this.professorMix += (this.professorTarget - this.professorMix) * (1.0 - Math.exp(-delta * 4.6));
    if (this.emotion !== null && performance.now() >= this.emotionUntil) this.emotion = null;

    const [a, b, c, stateFusionTarget] = this.targetsForState();
    this.cores[0].target.copy(a);
    this.cores[1].target.copy(b);
    this.cores[2].target.copy(c);

    // Das Wesen entscheidet in unregelmaessigen Abstaenden, ob es sich
    // sammelt, oeffnet oder einem seiner Kerne kurz die Fuehrung ueberlaesst.
    // Zufall wird nur fuer neue Ziele benutzt; die sichtbare Bewegung selbst
    // wird immer weich interpoliert und kann daher nicht zittern.
    const freeFlow = this.professorMix < 0.35
      && (this.state === "idle" || this.state === "listening"
        || this.state === "thinking" || this.state === "success");
    const safeDelta = Math.min(delta, 0.05);
    this.gestureIn -= safeDelta;
    if (freeFlow && this.gestureIn <= 0.0) {
      this.gestureIn = 3.6 + Math.random() * 5.8;
      const choice = Math.random();
      this.socialTarget = choice < 0.38
        ? 0.58 + Math.random() * 0.30
        : choice < 0.72 ? 0.24 + Math.random() * 0.22 : 0.04 + Math.random() * 0.10;
      this.gestureLead = Math.floor(Math.random() * 3);
      this.cores.forEach((core, index) => {
        const lead = index === this.gestureLead ? 1.0 : -0.35;
        core.phaseDriftTarget = lead * (0.16 + Math.random() * 0.22)
          + (Math.random() - 0.5) * 0.16;
        core.radiusDriftTarget = 0.84 + Math.random() * 0.33
          + (index === this.gestureLead ? 0.06 : 0.0);
      });
    } else if (!freeFlow) {
      this.socialTarget = 0.0;
      this.cores.forEach((core) => {
        core.phaseDriftTarget = 0.0;
        core.radiusDriftTarget = 1.0;
      });
    }
    this.socialMix += (this.socialTarget - this.socialMix)
      * (1.0 - Math.exp(-safeDelta * (this.socialTarget > this.socialMix ? 0.72 : 0.42)));

    // Langperiodische Eigenaktivitaet verhindert Stillstand zwischen den
    // bewussten Gesten, ohne einen kurzen oder offensichtlichen Loop zu bilden.
    const livingField = 0.5 + 0.5 * (
      Math.sin(t * 0.173)
      + Math.sin(t * 0.287 + 1.73) * 0.57
      + Math.sin(t * 0.109 + 3.11) * 0.36
    ) / 1.93;
    const encounter = freeFlow ? smoothstep(0.44, 0.84, livingField) : 0.0;
    const encounterStrength = this.state === "thinking" ? 0.78
      : this.state === "listening" ? 0.68
      : this.state === "success" ? 0.62 : 0.74;
    const socialEncounter = smoothstep(0.18, 0.82, this.socialMix) * encounterStrength;
    this.fusionTarget = Math.max(stateFusionTarget, encounter * encounterStrength * 0.28, socialEncounter);

    // Denken bleibt lebendig, aber ohne Flimmern: Die ganze Formation dreht
    // sich langsam als Einheit; die Abstaende der Kerne bleiben konstant.
    // Zustandswechsel ändern nur das ZIELTEMPO. Der Winkel selbst läuft
    // kontinuierlich weiter; so kann auch nach Stunden kein Sprung aus der
    // absoluten Laufzeit entstehen.
    const livingTempo = 0.82
      + Math.sin(t * 0.071 + 0.4) * 0.18
      + Math.sin(t * 0.113 + 2.2) * 0.10;
    const targetFormationSpeed = this.professorMix > 0.35
      ? 0.0
      : (this.state === "thinking" ? 0.18 : this.state === "listening" ? 0.120 : 0.085)
        * livingTempo;
    this.formationSpeed += (targetFormationSpeed - this.formationSpeed)
      * (1.0 - Math.exp(-delta * 1.8));
    this.formationPhase += delta * this.tempo * this.formationSpeed;
    const rotation = this.formationPhase;
    this.pointer.lerp(this.pointerTarget, 1.0 - Math.exp(-delta * 2.15));
    if (this.pointerActive) {
      this.pointerOffset.set(this.pointer.x * 0.032, this.pointer.y * 0.026, 0);
    } else {
      this.pointerOffset.set(Math.sin(t * 0.13) * 0.018, Math.cos(t * 0.11) * 0.014, 0);
    }

    this.fusion += (this.fusionTarget - this.fusion)
      * (1.0 - Math.exp(-safeDelta * (this.fusionTarget > this.fusion ? 1.35 : 0.70)));
    this.cores.forEach((core, index) => {
      core.phaseDrift += (core.phaseDriftTarget - core.phaseDrift)
        * (1.0 - Math.exp(-safeDelta * 0.46));
      core.radiusDrift += (core.radiusDriftTarget - core.radiusDrift)
        * (1.0 - Math.exp(-safeDelta * 0.39));
      const phaseDrift = core.phaseDrift
        + Math.sin(t * (0.127 + index * 0.017) + index * 2.17) * 0.10
        + Math.sin(t * (0.071 + index * 0.009) + index * 1.11) * 0.045;
      const radiusDrift = core.radiusDrift * (
        1.0 + Math.sin(t * (0.157 + index * 0.019) + index * 1.91) * 0.055
      );
      const contraction = 1.0 - this.fusion * 0.82;
      const localRotation = rotation + phaseDrift;
      const localCos = Math.cos(localRotation), localSin = Math.sin(localRotation);
      const sourceX = core.target.x * radiusDrift * contraction;
      const sourceY = core.target.y * radiusDrift * contraction;
      const tx = sourceX * localCos - sourceY * localSin;
      const ty = sourceX * localSin + sourceY * localCos;
      // Der jeweils fuehrende Kern zieht leicht vor, die beiden anderen
      // folgen. Beim naechsten Impuls kann die Rolle wechseln.
      const lead = freeFlow && index === this.gestureLead ? 1.0 : 0.0;
      const organicX = Math.sin(t * (0.23 + index * 0.027) + index * 2.1) * (0.012 + lead * 0.012);
      const organicY = Math.cos(t * (0.18 + index * 0.021) + index * 1.7) * (0.010 + lead * 0.009);
      core.target.set(tx + organicX, ty + organicY, core.target.z).add(this.pointerOffset);

      // Feder + Traegheit statt Lerp: Die Kerne beschleunigen, ueberholen
      // ihr Ziel minimal und finden weich zurueck – wie Masse in Fluessigkeit.
      const spring = this.state === "thinking" ? 11.0 : 8.6;
      this.motionDelta.copy(core.target).sub(core.position);
      core.velocity.addScaledVector(this.motionDelta, spring * safeDelta);
      core.velocity.multiplyScalar(Math.exp(-safeDelta * 4.2));
      core.position.addScaledVector(core.velocity, safeDelta);
      core.mesh.position.copy(core.position);
      // Sobald sich die Energiehaeute beruehren, gehen die Einzelkoerper
      // weich in den gemeinsamen Kern ueber. So entstehen keine gestapelten,
      // halbtransparenten Kreise in der Verschmelzungsphase.
      const mergeFade = smoothstep(0.16, 0.55, this.fusion);
      const individualOpacity = 1.0 - mergeFade * 0.96;
      core.material.uniforms.uOpacity.value = individualOpacity;
      let scale = 1.0 - this.fusion * 0.30;
      if (this.state === "listening" && index === 0) scale *= 1.28;
      if (this.professorMix > 0.2 && index < 2) scale *= 1.12;
      const breath = 1.0 + Math.sin(t * (0.72 + index * 0.07) + index * 1.4) * 0.035;
      core.mesh.scale.set(scale * breath, scale / Math.sqrt(breath), scale * breath);
      core.material.uniforms.uBreath.value = freeFlow ? 1.0 : 0.55;

      core.aura.position.copy(core.position);
      core.aura.position.z = core.position.z - 0.035;
      const auraBreath = 0.92 + breath * 0.10 + this.socialMix * 0.10;
      core.aura.scale.setScalar(scale * auraBreath);
      core.auraMaterial.uniforms.uOpacity.value = individualOpacity
        * (0.40 + this.socialMix * 0.18 + this.voiceLevel * 0.08);
      core.auraMaterial.uniforms.uTime.value = t;
    });

    const voiceEase = 1.0 - Math.exp(-delta * (this.voiceTarget > this.voiceLevel ? 18.0 : 5.0));
    this.voiceLevel += (this.voiceTarget - this.voiceLevel) * voiceEase;
    this.voiceTarget = Math.max(0.0, this.voiceTarget - delta * 1.8);
    const fusedOpacity = smoothstep(0.12, 0.52, this.fusion);
    this.fusedMaterial.uniforms.uOpacity.value = fusedOpacity;
    this.fusedMaterial.uniforms.uTime.value = t;
    this.fusedMaterial.uniforms.uBreath.value = 1.35;
    (this.membraneMaterial.uniforms.uCoreA.value as THREE.Vector2)
      .set(this.cores[0].position.x, this.cores[0].position.y);
    (this.membraneMaterial.uniforms.uCoreB.value as THREE.Vector2)
      .set(this.cores[1].position.x, this.cores[1].position.y);
    (this.membraneMaterial.uniforms.uCoreC.value as THREE.Vector2)
      .set(this.cores[2].position.x, this.cores[2].position.y);
    this.membraneMaterial.uniforms.uLife.value = this.socialMix;
    this.membraneMaterial.uniforms.uOpacity.value = 1.0 - fusedOpacity * 0.94;
    this.membraneMaterial.uniforms.uTime.value = t;
    this.cores.forEach((core) => {
      core.material.uniforms.uTime.value = t;
    });
    const voicePulse = 1.0 + this.voiceLevel * 0.10;
    const fusionPulse = 1.0 + fusedOpacity * (
      Math.sin(t * 0.82) * 0.024 + Math.sin(t * 0.37 + 1.4) * 0.011
    );
    const fusionVisualScale = (0.38 + this.fusion * 0.72) * voicePulse;
    this.fusedCore.scale.setScalar(fusionVisualScale * fusionPulse);
    this.fusionMistInner.scale.setScalar(
      fusionVisualScale * (1.0 + Math.sin(t * 0.71 + 0.6) * 0.012 * fusedOpacity),
    );
    this.fusionMistOuter.scale.setScalar(
      fusionVisualScale * (1.0 + Math.sin(t * 0.59 + 2.1) * 0.010 * fusedOpacity),
    );
    this.fusionShell.scale.setScalar(
      fusionVisualScale * (1.0 + Math.sin(t * 0.47 + 1.2) * 0.008 * fusedOpacity),
    );
    this.fusionMistInnerMaterial.uniforms.uOpacity.value = fusedOpacity * 0.74;
    this.fusionMistOuterMaterial.uniforms.uOpacity.value = fusedOpacity * 0.62;
    this.fusionShellMaterial.uniforms.uOpacity.value = fusedOpacity * 0.82;
    this.fusionMistInnerMaterial.uniforms.uTime.value = t;
    this.fusionMistOuterMaterial.uniforms.uTime.value = t;
    this.fusionShellMaterial.uniforms.uTime.value = t;
    this.fusedAura.scale.setScalar((0.72 + this.fusion * 1.12) * voicePulse * fusionPulse);
    this.fusedAuraMaterial.uniforms.uOpacity.value = fusedOpacity * (0.34 + this.voiceLevel * 0.10);
    this.fusedAuraMaterial.uniforms.uTime.value = t;

    // Kurze rot-orange Entladungen springen in unregelmaessigen Abstaenden
    // vom inneren Kern an die Aussenhaut. Zwischen Ereignissen bleibt die
    // Darstellung vollkommen ruhig und kann daher nicht flackern.
    if (fusedOpacity > 0.34) {
      this.synapseIn -= safeDelta;
      if (this.synapseIn <= 0.0) {
        const inactive = this.synapseArcs.filter((arc) => !arc.active);
        const chosen = inactive[Math.floor(Math.random() * inactive.length)];
        if (chosen !== undefined) {
          chosen.active = true;
          chosen.age = 0.0;
          chosen.duration = 0.30 + Math.random() * 0.42;
          chosen.group.rotation.set(
            (Math.random() - 0.5) * 0.72,
            (Math.random() - 0.5) * 0.82,
            Math.random() * Math.PI * 2.0,
          );
          chosen.group.visible = true;
        }
        this.synapseIn = 1.3 + Math.random() * 4.2;
      }
    } else {
      this.synapseIn = Math.max(this.synapseIn, 0.8);
    }
    this.synapseArcs.forEach((arc) => {
      arc.group.scale.setScalar(fusionVisualScale);
      if (!arc.active || fusedOpacity <= 0.20) {
        arc.group.visible = false;
        arc.material.opacity = 0.0;
        arc.active = false;
        return;
      }
      arc.age += safeDelta;
      const phase = arc.age / arc.duration;
      if (phase >= 1.0) {
        arc.active = false;
        arc.group.visible = false;
        arc.material.opacity = 0.0;
      } else {
        arc.material.opacity = Math.pow(Math.sin(phase * Math.PI), 1.35)
          * fusedOpacity * 0.96;
      }
    });

    const faceOpacity = smoothstep(0.80, 0.94, this.fusion);
    this.faceMaterial.uniforms.uOpacity.value = faceOpacity;
    const look = this.faceMaterial.uniforms.uLook.value as THREE.Vector2;
    if (this.pointerActive) {
      this.lookTarget.copy(this.pointer);
    } else {
      this.lookTarget.set(Math.sin(t * 0.16) * 0.30, Math.cos(t * 0.12) * 0.20);
    }
    look.lerp(this.lookTarget, Math.min(1.0, delta * 6.0));

    this.blinkIn -= delta;
    if (this.blinkIn <= 0 && this.blinkPhase < 0 && appearance.eyeOpen > 0.2) {
      this.blinkPhase = 0.0;
      this.blinkIn = 3.2 + Math.random() * 4.8;
    }
    let blink = 1.0;
    if (this.blinkPhase >= 0) {
      this.blinkPhase += delta;
      blink = this.blinkPhase < 0.11
        ? 1.0 - this.blinkPhase / 0.11
        : Math.min(1.0, (this.blinkPhase - 0.11) / 0.17);
      if (this.blinkPhase >= 0.28) this.blinkPhase = -1.0;
    }
    this.faceMaterial.uniforms.uOpen.value = appearance.eyeOpen * blink;
    // Die Brille wird als echte Vordergrundgeometrie gezeichnet; im
    // Gesichtsshader waere sie von hellen Energieadern ueberstrahlt.
    this.faceMaterial.uniforms.uProfessor.value = 0.0;
    const glassesMaterial = (this.glassesGroup.children[0] as THREE.Mesh | undefined)
      ?.material as THREE.MeshBasicMaterial | undefined;
    if (glassesMaterial !== undefined) glassesMaterial.opacity = this.professorMix * 0.96;
    this.glassesGroup.visible = this.professorMix > 0.01;

    const positions = this.linkGeometry.getAttribute("position") as THREE.BufferAttribute;
    const colors = this.linkGeometry.getAttribute("color") as THREE.BufferAttribute;
    const pairs = [[0, 1], [1, 2], [2, 0]] as const;
    pairs.forEach(([from, to], pairIndex) => {
      const start = this.cores[from].position;
      const end = this.cores[to].position;
      const colorA = this.cores[from].baseColor;
      const colorB = this.cores[to].baseColor;
      const dx = end.x - start.x;
      const dy = end.y - start.y;
      const length = Math.max(0.001, Math.hypot(dx, dy));
      const normalX = -dy / length;
      const normalY = dx / length;
      const bend = (0.026 + this.socialMix * 0.052)
        * Math.sin(t * (0.31 + pairIndex * 0.027) + pairIndex * 2.13);
      for (let segment = 0; segment < 18; segment += 1) {
        const u0 = segment / 18;
        const u1 = (segment + 1) / 18;
        const writePoint = (u: number, vertex: number): void => {
          const curve = 4.0 * u * (1.0 - u);
          const current = Math.sin(u * Math.PI * 3.0 - t * 0.74 + pairIndex * 1.7)
            * 0.006 * curve;
          const x = start.x + dx * u + normalX * (bend * curve + current);
          const y = start.y + dy * u + normalY * (bend * curve + current);
          const z = start.z + (end.z - start.z) * u - 0.008;
          positions.setXYZ(vertex, x, y, z);
          const flow = 0.68 + Math.sin(u * Math.PI * 2.0 - t * 0.62 + pairIndex) * 0.18;
          colors.setXYZ(
            vertex,
            (colorA.r + (colorB.r - colorA.r) * u) * flow,
            (colorA.g + (colorB.g - colorA.g) * u) * flow,
            (colorA.b + (colorB.b - colorA.b) * u) * flow,
          );
        };
        const baseVertex = (pairIndex * 18 + segment) * 2;
        writePoint(u0, baseVertex);
        writePoint(u1, baseVertex + 1);
      }
    });
    positions.needsUpdate = true;
    colors.needsUpdate = true;
    this.linkMaterial.opacity = clamp(
      Math.pow(1.0 - this.fusion, 1.7)
        * (0.22 + this.socialMix * 0.20 + (this.state === "listening" ? 0.08 : 0.0)),
      0.0,
      0.48,
    );

    this.progress.visible = this.progressValue !== null;
    this.progressMaterial.uniforms.uOpacity.value = this.progress.visible ? 0.72 : 0.0;
    this.progressMaterial.uniforms.uProgress.value = this.progressIndeterminate
      ? -1.0 : (this.progressValue ?? 0.0);
    this.progressMaterial.uniforms.uTime.value = t;

    this.flashAge += delta;
    if (this.flashAge < 0.9) {
      const phase = this.flashAge / 0.9;
      this.wave.visible = true;
      this.wave.scale.setScalar(0.85 + phase * 1.15);
      this.waveMaterial.opacity = Math.sin(phase * Math.PI) * 0.42 * this.flashStrength;
    } else {
      this.wave.visible = false;
    }

    this.reactionAge += delta;
    let reactionScale = 1.0;
    if (this.reactionAge < 0.7) {
      const phase = this.reactionAge / 0.7;
      if (this.reactionKind === "surprise") {
        this.group.position.y = this.reactionBaseY + Math.sin(phase * Math.PI) * 0.18;
      } else {
        reactionScale += Math.sin(phase * Math.PI * 4.0) * 0.035 * (1.0 - phase);
      }
    }

    const pulse = 1.0 + Math.sin(t * 0.88) * appearance.pulseAmount * 0.035;
    // main.ts hat die Zustandsgrösse bereits in baseScale eingerechnet.
    // Eine zweite Multiplikation liess Fusionen und Warnzustände ungewollt
    // stark in der Grösse springen.
    this.group.scale.setScalar(this.baseScale * pulse * reactionScale);

    const ground = this.groundGroup.children[0] as THREE.Mesh | undefined;
    if (ground !== undefined) {
      const height = clamp(this.floatHeight * 2.6, -0.4, 0.4);
      ground.scale.setScalar(this.baseScale * (1.0 - height * 0.22));
      ground.position.y = -0.59 * this.baseScale;
      this.groundMaterial.uniforms.uFusion.value = this.fusion;
      this.groundMaterial.uniforms.uOpacity.value = 1.0 - height * 0.35;
      this.groundMaterial.uniforms.uColorA.value.copy(this.cores[0].material.uniforms.uColor.value);
      this.groundMaterial.uniforms.uColorB.value.copy(this.cores[1].material.uniforms.uColor.value);
      this.groundMaterial.uniforms.uColorC.value.copy(this.cores[2].material.uniforms.uColor.value);
    }
  }

  public setQuality(_level: number): void {
    // Drei Kerne und wenige Linien sind auf jeder Stufe bereits billig.
  }

  public get scaleFactor(): number {
    return this.baseScale;
  }

  public dispose(): void {
    for (const geometry of this.geometries) geometry.dispose();
    for (const material of this.materials) material.dispose();
  }
}

function smoothstep(edge0: number, edge1: number, value: number): number {
  const t = clamp((value - edge0) / (edge1 - edge0), 0.0, 1.0);
  return t * t * (3.0 - 2.0 * t);
}
