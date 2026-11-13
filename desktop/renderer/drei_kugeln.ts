/**
 * drei_kugeln.ts – drei lebendige Kugeln in Rot, Gruen und Blau (13.11.2026).
 *
 * Marcs Wunsch: drei Baelle, die sich drehen und ineinander verschmelzen,
 * gluehen, und in denen ein Nebel zieht, damit es aussieht, als lebten sie.
 * Denkt Synapse nach, wirbeln sie eng zusammen und verschmelzen zu einer
 * Kugel; spricht sie, pulsieren sie mit der Stimme; hoert sie zu, ruecken
 * sie wach auseinander.
 *
 * Technik: eine einzige Flaeche mit einem Shader (Metaballs). Jede Kugel
 * ist ein Feld; wo sich die Felder ueberlagern, fliessen Form und Farbe
 * ineinander. Der Nebel ist verwirbeltes Rauschen (fbm) innerhalb der Form.
 *
 * Die oeffentliche Schnittstelle ist dieselbe wie bei EnergyOrb und
 * SynaptixBrain - main.ts behandelt alle drei gleich. Eingeschaltet mit
 * ``orb.darstellung: drei_kugeln`` in der config.yaml oder per Sprache
 * ("wechsle zur Kugel-Animation").
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
uniform vec3 uB0;
uniform vec3 uB1;
uniform vec3 uB2;
uniform float uDenk;
uniform float uSprech;
uniform float uHelligkeit;
uniform float uWach;
uniform float uBlitz;
uniform float uNebelStufen;

float h(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
float n(vec2 p) {
  vec2 i = floor(p), f = fract(p);
  f = f * f * (3.0 - 2.0 * f);
  return mix(mix(h(i), h(i + vec2(1, 0)), f.x), mix(h(i + vec2(0, 1)), h(i + vec2(1, 1)), f.x), f.y);
}
float fbm(vec2 p) {
  float s = 0.0, a = 0.5;
  for (int i = 0; i < 5; i++) {
    if (float(i) >= uNebelStufen) break;
    s += a * n(p);
    p = p * 2.03 + vec2(1.7, 9.2);
    a *= 0.5;
  }
  return s;
}
float feld(vec2 q, vec3 b) { vec2 d = q - b.xy; return b.z * b.z / (dot(d, d) + 1e-4); }

void main() {
  vec2 q = (vUv - 0.5) * 2.0;
  float f0 = feld(q, uB0), f1 = feld(q, uB1), f2 = feld(q, uB2);
  float f = f0 + f1 + f2;
  vec3 farbe = (f0 * vec3(1.0, 0.16, 0.12) + f1 * vec3(0.14, 1.0, 0.32) + f2 * vec3(0.18, 0.36, 1.0)) / max(f, 1e-4);

  float t = uZeit * (0.18 + 0.5 * uDenk);
  vec2 w = q * 3.2;
  w += vec2(fbm(w + t), fbm(w - t + 3.1)) * 1.4;
  float nebel = fbm(w * 1.3 + vec2(t * 0.7, -t * 0.5));
  float wolke = smoothstep(0.25, 0.85, nebel);

  float rand = smoothstep(0.75, 1.08, f);
  float kern = smoothstep(1.0, 3.5, f);
  vec3 innen = farbe * (0.25 + 1.35 * wolke) + farbe * pow(kern, 2.0) * 0.25 + vec3(1.0) * pow(kern, 4.0) * 0.08;
  innen *= 1.0 + 0.35 * uSprech * sin(uZeit * 9.0 + nebel * 6.0);

  float gluehen = pow(clamp(f, 0.0, 1.0), 2.2) * (0.55 + 0.25 * uDenk + 0.3 * uSprech);
  vec3 col = mix(farbe * gluehen * 0.75, innen, rand);
  col += farbe * 0.08 * smoothstep(0.0, 0.6, f);
  col *= uHelligkeit * uWach * (1.0 + 0.6 * uBlitz);
  col = 1.0 - exp(-col * 1.35);

  // Weicher Rand der Flaeche - nirgends eine harte Kante.
  float r = length(q);
  float maske = 1.0 - smoothstep(0.82, 1.0, r);
  float alpha = clamp(max(max(col.r, col.g), col.b) * 1.4, 0.0, 1.0) * maske;
  gl_FragColor = vec4(col * maske, alpha);
}
`;

export class DreiKugeln {
  public readonly group: THREE.Group;
  public readonly groundGroup: THREE.Group;

  private readonly flaeche: THREE.Mesh;
  private readonly u: Record<string, THREE.IUniform>;
  private readonly grundTempo: number;
  private readonly grundHelligkeit: number;

  private eigenzeit = 0;
  private winkel = 0;
  private basisSkala = 0.28;
  private zustand: OrbStateName = "idle";
  private denk = 0;
  private sprech = 0;
  private hoer = 0;
  private stimme = 0;
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
    this.grundHelligkeit = 0.75 + 0.2 * (options?.helligkeit ?? 1.0);
    this.group = new THREE.Group();
    this.groundGroup = new THREE.Group();

    this.u = {
      uZeit: { value: 0 },
      uB0: { value: new THREE.Vector3() },
      uB1: { value: new THREE.Vector3() },
      uB2: { value: new THREE.Vector3() },
      uDenk: { value: 0 },
      uSprech: { value: 0 },
      uHelligkeit: { value: this.grundHelligkeit },
      uWach: { value: 1 },
      uBlitz: { value: 0 },
      uNebelStufen: { value: 5 },
    };
    this.flaeche = new THREE.Mesh(
      new THREE.PlaneGeometry(2.8, 2.8, 1, 1),
      new THREE.ShaderMaterial({
        uniforms: this.u,
        vertexShader: VERTEX,
        fragmentShader: FRAGMENT,
        transparent: true,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
      })
    );
    this.group.add(this.flaeche);
  }

  public setBaseScale(scale: number): void {
    this.basisSkala = scale;
    this.group.scale.setScalar(scale);
    this.groundGroup.scale.setScalar(scale);
  }

  public setVoiceLevel(level: number): void {
    if (Number.isFinite(level)) this.stimme = Math.max(0, Math.min(1, level));
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
    this.flash(kind === "surprise" ? 0.9 : 0.5);
    this.reizRest = kind === "surprise" ? 1.4 : 0.7;
  }

  public setVisualStyle(style: OrbVisualStyle): void {
    void style;
  }

  public flash(strength = 1.0): void {
    this.blitz = Math.max(this.blitz, Math.max(0, Math.min(1.5, strength)));
  }

  public setProgress(progress: number | null, indeterminate = false): void {
    this.fortschritt = progress;
    void indeterminate;
  }

  public get scaleFactor(): number {
    return this.basisSkala;
  }

  public applyAppearance(a: StateAppearance): void {
    this.u.uHelligkeit.value =
      this.grundHelligkeit * (0.7 + 0.45 * a.lightIntensity) * (this.professor ? 1.1 : 1.0);
    this.u.uWach.value = this.zustand === "offline" || this.zustand === "sleep" ? 0.35 : 1.0;
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

    const gefuehlTempo =
      this.gefuehl === "joyful" || this.gefuehl === "surprised" ? 1.3
        : this.gefuehl === "relaxed" ? 0.8 : 1.0;
    const tempo = this.grundTempo * Math.max(0.3, a.speed) * gefuehlTempo * (1 + this.reizRest * 0.5);
    this.eigenzeit += schritt * tempo;
    const z = this.eigenzeit;

    // Ruhe: langsames Kreisen und Atmen. Denkt: schnelles, enges Wirbeln -
    // die Kugeln verschmelzen. Spricht: Pulsieren mit der Stimme.
    const puls = 0.35 * this.sprech * (0.4 + this.stimme);
    this.winkel += schritt * tempo * (0.35 + 2.6 * this.denk + 0.5 * this.sprech + 0.15 * this.hoer);
    const abstand =
      0.42 + 0.07 * Math.sin(z * 0.7) - 0.24 * this.denk + 0.12 * this.hoer + 0.05 * puls * Math.sin(z * 8);
    const radius = 0.24 + 0.025 * Math.sin(z * 1.3) + 0.04 * puls;
    const kugel = (i: number, ziel: THREE.Vector3): void => {
      const w = this.winkel + i * 2.0944 + 0.25 * Math.sin(z * 0.9 + i);
      const r = abstand * (1 + 0.18 * Math.sin(z * (0.8 + i * 0.13) + i * 2.0));
      ziel.set(
        Math.cos(w) * r,
        Math.sin(w) * r * (0.92 + 0.08 * Math.sin(z + i)),
        radius * (1 + 0.06 * Math.sin(z * 1.7 + i * 1.3))
      );
    };
    kugel(0, this.u.uB0.value as THREE.Vector3);
    kugel(1, this.u.uB1.value as THREE.Vector3);
    kugel(2, this.u.uB2.value as THREE.Vector3);

    this.u.uZeit.value = z;
    this.u.uDenk.value = this.denk;
    this.u.uSprech.value = Math.min(1, this.sprech * (0.5 + this.stimme));
    this.u.uBlitz.value = this.blitz;

    const folgen = 1 - Math.exp(-schritt * 6.0);
    this.zeiger.lerp(this.zeigerZiel, folgen);
    this.group.rotation.y = this.zeiger.x * 0.2;
    this.group.rotation.x = -this.zeiger.y * 0.14;
  }

  public setQuality(level: number): void {
    const stufe = Math.max(0, Math.min(2, Math.round(level)));
    this.u.uNebelStufen.value = stufe === 0 ? 3 : stufe === 1 ? 4 : 5;
  }

  public dispose(): void {
    this.flaeche.geometry.dispose();
    (this.flaeche.material as THREE.Material).dispose();
    this.group.clear();
    this.groundGroup.clear();
  }
}
