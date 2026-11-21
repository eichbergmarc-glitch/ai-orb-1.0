/**
 * nebel_kreis.ts – ein runder Kreis, in dem weicher Nebel zieht (19.11.2026).
 *
 * Marcs Wunsch: eine Animation wie der Sprach-Orb von ChatGPT – ein klarer
 * Kreis, und darin bewegt sich Nebel. Gebaut ist es als eigene Fassung:
 * eine leicht gewoelbte Kugel in Himmelblau, durch die helle Wolken
 * treiben. Oben ist sie heller (Licht von oben), unten tiefer blau.
 *
 * Verhalten:
 *   - Ruhe:      die Wolken treiben langsam, die Kugel atmet kaum merklich.
 *   - Zuhoeren:  die Wolken werden lebhafter, die Kugel wird etwas groesser.
 *   - Denken:    die Wolken drehen sich im Kreis, langsames Pulsieren.
 *   - Sprechen:  die Kugel pulsiert mit der Lautstaerke der Stimme.
 *
 * Technik wie bei DreiKugeln: eine einzige Flaeche mit einem Shader, nur
 * GLSL ES 1.00 (keine Schleifen mit variabler Grenze ausser per break).
 * Die oeffentliche Schnittstelle ist dieselbe wie bei EnergyOrb, Synaptix
 * und DreiKugeln. Eingeschaltet mit ``orb.darstellung: nebel``.
 */

import * as THREE from "three";

import type { StateAppearance, OrbStateName } from "./states";
import type { OrbEmotionName, OrbVisualStyle } from "./energy_orb";

const VERTEX = /* glsl */ `
varying vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`;

const FRAGMENT = /* glsl */ `
precision highp float;
varying vec2 vUv;
uniform float uZeit;
uniform float uDrehung;
uniform float uDenk;
uniform float uHoer;
uniform float uSprech;
uniform float uStimme;
uniform float uHelligkeit;
uniform float uWach;
uniform float uBlitz;
uniform float uStufen;
uniform vec3 uTief;
uniform vec3 uHimmel;
uniform vec3 uWolke;

float h(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
float n(vec2 p) {
  vec2 i = floor(p), f = fract(p);
  f = f * f * (3.0 - 2.0 * f);
  return mix(mix(h(i), h(i + vec2(1, 0)), f.x), mix(h(i + vec2(0, 1)), h(i + vec2(1, 1)), f.x), f.y);
}
float fbm(vec2 p) {
  float s = 0.0, a = 0.5;
  for (int i = 0; i < 6; i++) {
    if (float(i) >= uStufen) break;
    s += a * n(p);
    p = mat2(1.6, 1.2, -1.2, 1.6) * p + vec2(1.7, 9.2);
    a *= 0.5;
  }
  return s;
}
vec2 drehe(vec2 p, float w) { float c = cos(w), s = sin(w); return vec2(c * p.x - s * p.y, s * p.x + c * p.y); }

void main() {
  // Die Flaeche ist groesser als die Kugel, damit der Schein Platz hat.
  vec2 q = (vUv - 0.5) * 2.0 / 0.82;
  float r = length(q);

  // Woelbung: Punkte am Rand ruecken zusammen – so wirkt der Nebel wie
  // auf einer Kugel und nicht wie auf einer Scheibe.
  float z = sqrt(max(0.0, 1.0 - min(r * r, 1.0)));
  vec2 k = q / (0.55 + 0.45 * z);
  k = drehe(k, uDrehung);

  float t = uZeit;
  // Stimme: der Nebel quillt von innen nach aussen und wird unruhiger.
  k *= 1.0 - 0.2 * uStimme;
  // Atem der "Seele": ein langsamer Puls, der alles mitnimmt.
  float atem = 0.5 + 0.5 * sin(t * 0.9);
  float wirbel = 2.2 + 0.8 * sin(t * 0.37) + 1.6 * uStimme + 0.6 * uHoer;
  // Ein Wirbel um die Mitte: innen schneller als aussen - wie Rauch, der kreist.
  float rr = length(k);
  k = drehe(k, (0.55 + 0.6 * uStimme) * sin(t * 0.21) * (1.2 - rr * 0.6) + t * 0.12 * (1.0 - rr * 0.4));
  // Drei Schichten, die sich gegeneinander bewegen und ineinander greifen.
  vec2 w1 = k * 1.25 + vec2(t * 0.45, -t * 0.28);
  vec2 v = vec2(fbm(w1 + vec2(0.0, t * 0.6)), fbm(w1 + vec2(5.2, 1.3) - t * 0.52));
  vec2 w1b = drehe(k, -t * 0.23) * 1.6 + wirbel * v;
  vec2 u2 = vec2(fbm(w1b + vec2(t * 0.38, 2.0)), fbm(w1b + vec2(8.3, -t * 0.41)));
  float wolke1 = fbm(w1 + wirbel * u2);
  // Aufsteigender Rauch: die zweite Schicht zieht nach oben.
  vec2 w2 = drehe(k, t * 0.3) * 2.4 + vec2(-t * 0.25, -t * 0.7) + 1.4 * v;
  float wolke2 = fbm(w2);
  float dichte = smoothstep(0.44, 0.88, wolke1) * 0.72 + smoothstep(0.56, 0.92, wolke2) * 0.32;
  dichte *= 0.75 + 0.25 * atem + 0.3 * uHoer + 0.5 * uStimme;
  // Tiefe Schlieren: zwischen den Wolken kraeftigeres Blau.
  float schliere = smoothstep(0.35, 0.6, fbm(w2 * 0.7 + u2 * 1.5 - t * 0.2));

  // Das innere Licht: wandert langsam umher, atmet, und wird mit der Stimme heller.
  vec2 seele = 0.32 * vec2(sin(t * 0.43) + 0.4 * sin(t * 1.07), cos(t * 0.37) + 0.4 * sin(t * 0.83 + 1.0));
  float naehe = exp(-dot(q - seele, q - seele) * (3.0 - 1.2 * uStimme));
  float licht_innen = naehe * (0.35 + 0.35 * atem + 0.9 * uStimme + 0.25 * uDenk);

  // Grund: oben hell, unten tief.
  float hoehe = clamp(q.y * 0.5 + 0.5, 0.0, 1.0);
  vec3 grund = mix(uTief, uHimmel, smoothstep(0.0, 1.0, hoehe * 0.8 + 0.35 * (wolke1 - 0.5) + 0.2 * schliere));
  // Wolken sind hellblau; nur ihre dichtesten Stellen werden fast weiss.
  vec3 hellblau = mix(uHimmel, uWolke, 0.55);
  vec3 col = mix(grund, hellblau, clamp(dichte, 0.0, 1.0));
  col = mix(col, uWolke, smoothstep(0.8, 1.15, dichte) * 0.35);
  // Das innere Licht scheint durch den Nebel: dort, wo Nebel ist, leuchtet es mehr.
  col += mix(uHimmel, uWolke, 0.35) * licht_innen * (0.3 + 0.8 * dichte);

  // Licht von oben links, weicher Glanz und dunklerer Rand – die Woelbung.
  float licht = clamp(dot(normalize(vec3(q, z)), normalize(vec3(-0.35, 0.6, 0.75))), 0.0, 1.0);
  col *= 0.78 + 0.32 * licht;
  col += uWolke * pow(licht, 18.0) * 0.1;
  col *= mix(0.8, 1.0, pow(z, 0.35));
  col *= 1.0 + 0.1 * uStimme;

  col *= uHelligkeit * uWach * (1.0 + 0.5 * uBlitz);

  // Glatter, ruhiger Rand: der Kreis ist klar, aber nicht pixelig.
  float kante = fwidth(r) * 1.5 + 0.004;
  float innen = 1.0 - smoothstep(1.0 - kante, 1.0 + kante, r);
  // Ein sehr leiser Schein ausserhalb – kein Ring.
  float schein = (1.0 - innen) * exp(-(r - 1.0) * 9.0) * (0.12 + 0.18 * uSprech + 0.08 * uDenk);
  vec3 farbe = col * innen + uHimmel * schein * uHelligkeit * uWach;
  float alpha = clamp(innen + schein, 0.0, 1.0);
  gl_FragColor = vec4(farbe, alpha);
}
`;

/** Farben je Gefuehl: Tiefe, Himmel, Wolke. */
const FARBEN: Record<string, [number, number, number][]> = {
  grund: [[0.01, 0.1, 0.55], [0.12, 0.42, 1.0], [0.62, 0.82, 1.0]],
  joyful: [[0.1, 0.3, 0.85], [0.45, 0.75, 1.0], [1.0, 0.99, 0.95]],
  relaxed: [[0.05, 0.3, 0.62], [0.4, 0.72, 0.9], [0.92, 0.98, 1.0]],
  surprised: [[0.14, 0.2, 0.86], [0.55, 0.62, 1.0], [1.0, 1.0, 1.0]],
  professor: [[0.12, 0.16, 0.6], [0.48, 0.55, 0.98], [0.96, 0.96, 1.0]],
};

export class NebelKreis {
  public readonly group: THREE.Group;
  public readonly groundGroup: THREE.Group;

  private readonly flaeche: THREE.Mesh;
  private readonly u: Record<string, THREE.IUniform>;
  private readonly grundTempo: number;
  private readonly grundHelligkeit: number;

  private eigenzeit = 0;
  private drehung = 0;
  private basisSkala = 0.28;
  private zustand: OrbStateName = "idle";
  private denk = 0;
  private sprech = 0;
  private hoer = 0;
  private stimme = 0;
  private stimmeGlatt = 0;
  private blitz = 0;
  private reizRest = 0;
  private gefuehl: OrbEmotionName | null = null;
  private gefuehlRest = 0;
  private professor = false;
  private fortschritt: number | null = null;
  private zeigerZiel = new THREE.Vector2(0, 0);
  private zeiger = new THREE.Vector2(0, 0);

  constructor(options?: { tempo?: number; helligkeit?: number }, pixelRatio = 1) {
    void pixelRatio;
    this.grundTempo = options?.tempo ?? 1.0;
    this.grundHelligkeit = 0.85 + 0.15 * (options?.helligkeit ?? 1.0);
    this.group = new THREE.Group();
    this.groundGroup = new THREE.Group();

    const [tief, himmel, wolke] = FARBEN.grund;
    this.u = {
      uZeit: { value: 0 },
      uDrehung: { value: 0 },
      uDenk: { value: 0 },
      uHoer: { value: 0 },
      uSprech: { value: 0 },
      uStimme: { value: 0 },
      uHelligkeit: { value: this.grundHelligkeit },
      uWach: { value: 1 },
      uBlitz: { value: 0 },
      uStufen: { value: 5 },
      uTief: { value: new THREE.Color(...tief) },
      uHimmel: { value: new THREE.Color(...himmel) },
      uWolke: { value: new THREE.Color(...wolke) },
    };
    const material = new THREE.ShaderMaterial({
      uniforms: this.u,
      vertexShader: VERTEX,
      fragmentShader: FRAGMENT,
      transparent: true,
      depthWrite: false,
      blending: THREE.NormalBlending,
    });
    // fwidth braucht in WebGL1 die Ableitungs-Erweiterung.
    (material as unknown as { extensions: Record<string, boolean> }).extensions = { derivatives: true };
    this.flaeche = new THREE.Mesh(new THREE.PlaneGeometry(2.8, 2.8, 1, 1), material);
    this.group.add(this.flaeche);
  }

  public setBaseScale(scale: number): void {
    this.basisSkala = scale;
    this.group.scale.setScalar(scale);
    this.groundGroup.scale.setScalar(scale);
  }

  public setVoiceLevel(level: number): void {
    // Der Pegel ist ein RMS um 0.1 (der Player gleicht Saetze darauf an).
    // Die Wurzel hebt leise Silben, damit der Nebel jedem Wort folgt.
    if (Number.isFinite(level)) this.stimme = Math.min(1, Math.sqrt(Math.max(0, level) / 0.25));
  }

  public setFloatHeight(y: number): void {
    void y;
  }

  public setPointer(x: number, y: number, active: boolean): void {
    if (!active) {
      this.zeigerZiel.set(0, 0);
      return;
    }
    this.zeigerZiel.set(Math.max(-1.4, Math.min(1.4, x)), Math.max(-1.4, Math.min(1.4, y)));
  }

  public setState(state: OrbStateName): void {
    this.zustand = state;
  }

  public setProfessorMode(active: boolean): void {
    this.professor = active;
  }

  public setEmotion(emotion: OrbEmotionName | null, seconds = 2.4): void {
    this.gefuehl = emotion;
    this.gefuehlRest = emotion === null ? 0 : Math.max(0, seconds);
  }

  public react(kind: "click" | "surprise"): void {
    this.flash(kind === "surprise" ? 0.7 : 0.35);
    this.reizRest = kind === "surprise" ? 1.4 : 0.7;
  }

  public setVisualStyle(style: OrbVisualStyle): void {
    void style;
  }

  public flash(strength = 1.0): void {
    this.blitz = Math.max(this.blitz, Math.max(0, Math.min(1.2, strength)));
  }

  public setProgress(progress: number | null, indeterminate = false): void {
    this.fortschritt = progress;
    void indeterminate;
  }

  public get scaleFactor(): number {
    return this.basisSkala;
  }

  public applyAppearance(a: StateAppearance): void {
    this.u.uHelligkeit.value = this.grundHelligkeit * (0.85 + 0.2 * a.lightIntensity);
    this.u.uWach.value = this.zustand === "offline" || this.zustand === "sleep" ? 0.45 : 1.0;
  }

  public update(elapsed: number, delta: number, a: StateAppearance): void {
    void elapsed;
    const schritt = Math.min(0.1, Math.max(0, delta));
    if (this.gefuehlRest > 0) {
      this.gefuehlRest = Math.max(0, this.gefuehlRest - schritt);
      if (this.gefuehlRest === 0) this.gefuehl = null;
    }
    this.reizRest = Math.max(0, this.reizRest - schritt * 1.6);
    this.blitz = Math.max(0, this.blitz - schritt * 2.2);

    const denkt = this.zustand === "thinking" || this.zustand === "busy" || this.fortschritt !== null;
    const spricht = this.zustand === "speaking";
    const hoert = this.zustand === "listening";
    this.denk += ((denkt ? 1 : 0) - this.denk) * Math.min(1, schritt * 2.5);
    this.sprech += ((spricht ? 1 : 0) - this.sprech) * Math.min(1, schritt * 4);
    this.hoer += ((hoert ? 1 : 0) - this.hoer) * Math.min(1, schritt * 3);
    // Die Stimme rasch steigen, langsamer fallen lassen – sonst flackert es.
    const ziel = spricht ? this.stimme : 0;
    this.stimmeGlatt += (ziel - this.stimmeGlatt) * Math.min(1, schritt * (ziel > this.stimmeGlatt ? 18 : 7));

    // Die Stimme treibt den Nebel: laut = schnelles Quellen, Pause = er beruhigt sich.
    const tempo =
      this.grundTempo * Math.max(0.3, a.speed) *
      (1 + 0.7 * this.hoer + 0.3 * this.sprech + 2.6 * this.stimmeGlatt + this.reizRest * 0.5);
    this.eigenzeit += schritt * tempo;
    // Denken: der Nebel kreist; sonst ein ganz langsames Drehen.
    this.drehung += schritt * (0.08 + 0.9 * this.denk + 0.3 * this.stimmeGlatt);
    const z = this.eigenzeit;

    // Groesse: Atmen in Ruhe, wacher beim Zuhoeren, Puls beim Sprechen.
    const atmen = 0.018 * Math.sin(z * 0.9);
    const denkPuls = 0.03 * this.denk * Math.sin(z * 3.2);
    const skala = 1 + atmen + 0.05 * this.hoer + denkPuls + 0.12 * this.stimmeGlatt;
    this.flaeche.scale.setScalar(skala);

    // Farben sanft zum Gefuehl hin ziehen.
    const satz = this.professor ? FARBEN.professor : FARBEN[this.gefuehl ?? "grund"] ?? FARBEN.grund;
    const mischen = Math.min(1, schritt * 2.0);
    (this.u.uTief.value as THREE.Color).lerp(new THREE.Color(...satz[0]), mischen);
    (this.u.uHimmel.value as THREE.Color).lerp(new THREE.Color(...satz[1]), mischen);
    (this.u.uWolke.value as THREE.Color).lerp(new THREE.Color(...satz[2]), mischen);

    this.u.uZeit.value = z;
    this.u.uDrehung.value = this.drehung;
    this.u.uDenk.value = this.denk;
    this.u.uHoer.value = this.hoer;
    this.u.uSprech.value = this.sprech;
    this.u.uStimme.value = this.stimmeGlatt;
    this.u.uBlitz.value = this.blitz;

    const folgen = 1 - Math.exp(-schritt * 6.0);
    this.zeiger.lerp(this.zeigerZiel, folgen);
    this.group.rotation.y = this.zeiger.x * 0.15;
    this.group.rotation.x = -this.zeiger.y * 0.1;
  }

  public setQuality(level: number): void {
    const stufe = Math.max(0, Math.min(2, Math.round(level)));
    this.u.uStufen.value = stufe === 0 ? 4 : stufe === 1 ? 5 : 6;
  }

  public dispose(): void {
    this.flaeche.geometry.dispose();
    (this.flaeche.material as THREE.Material).dispose();
    this.group.clear();
    this.groundGroup.clear();
  }
}
