/**
 * effects.ts – Materialien und Nachbearbeitungseffekte des Orb.
 *
 * Hier entstehen die Shader-Materialien für Kern, Hülle und Partikel sowie
 * der Bloom-Effekt, der dem Orb seinen HDR-artigen Eindruck gibt.
 *
 * Dieses Modul kennt ausschließlich Materialien und Effekte – es kennt
 * weder Zustände noch Interaktion.
 */

import * as THREE from "three";
import { EffectComposer } from "three/examples/jsm/postprocessing/EffectComposer.js";
import { RenderPass } from "three/examples/jsm/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/examples/jsm/postprocessing/UnrealBloomPass.js";
import { ShaderPass } from "three/examples/jsm/postprocessing/ShaderPass.js";

import clusterShader from "../shaders/cluster.glsl";
import coreShader from "../shaders/core.glsl";
import fresnelShader from "../shaders/fresnel.glsl";
import particlesShader from "../shaders/particles.glsl";
import smokeShader from "../shaders/smoke.glsl";

/**
 * Trennt eine kombinierte GLSL-Datei in Vertex- und Fragment-Shader.
 *
 * Die Shader-Dateien enthalten beide Stufen, abgegrenzt durch
 * `#ifdef VERTEX_STAGE` bzw. `#ifdef FRAGMENT_STAGE`. Damit bleibt der
 * zusammengehörige Code in einer Datei, ohne dass GLSL-Präprozessordirektiven
 * zur Laufzeit ausgewertet werden müssen.
 *
 * @param source Inhalt der GLSL-Datei.
 * @returns Vertex- und Fragment-Quelltext.
 */
export function splitShader(source: string): { vertex: string; fragment: string } {
  const extract = (stage: string): string => {
    const startMarker = `#ifdef ${stage}`;
    const start = source.indexOf(startMarker);
    if (start < 0) {
      return "";
    }
    const bodyStart = start + startMarker.length;
    const end = source.indexOf("#endif", bodyStart);
    return source.slice(bodyStart, end < 0 ? undefined : end).trim();
  };

  return { vertex: extract("VERTEX_STAGE"), fragment: extract("FRAGMENT_STAGE") };
}

/**
 * Erzeugt das Material für den Kristallhaufen im Inneren.
 *
 * Er wird nicht als Geometrie gebaut, sondern für jeden Bildpunkt
 * ausgerechnet (siehe cluster.glsl). Deshalb genügt als Träger eine
 * beliebige Hülle, die den Haufen umschliesst – gezeichnet wird, was der
 * Shader darin findet.
 *
 * `depthWrite` bleibt an: Der Haufen ist ein fester Körper und soll
 * verdecken, was hinter ihm liegt. `FrontSide`, weil von aussen darauf
 * geschaut wird – anders als beim Nebel, bei dem der Strahl im Inneren
 * beginnt.
 */
/**
 * Die Körper des Kristallhaufens: Richtung (xyz) und Grundgrösse (w).
 *
 * Sie stehen hier und nicht im Shader, weil GLSL ES 1.00 – das three.js
 * für eigene Shader benutzt – keine Array-Konstruktoren kennt. Und weil
 * es ohnehin verschwendet wäre, Werte in jedem Bildpunkt auszurechnen,
 * die sich nie ändern.
 *
 * Die Richtungen liegen nach dem goldenen Winkel auf der Kugel:
 * gleichmässig verteilt, ohne bevorzugte Richtung und ohne die sichtbaren
 * Reihen, die gleichmässige Winkelabstände erzeugen würden.
 */
const CLUSTER_BODIES: THREE.Vector4[] = [
  new THREE.Vector4(+0.3997, +0.0000, +0.9167, 0.1600),
  new THREE.Vector4(-0.4877, +0.4468, +0.7500, 0.2798),
  new THREE.Vector4(+0.0710, -0.8091, +0.5833, 0.1674),
  new THREE.Vector4(+0.5531, +0.7214, +0.4167, 0.2326),
  new THREE.Vector4(-0.9534, -0.1687, +0.2500, 0.2086),
  new THREE.Vector4(+0.8408, -0.5349, +0.0833, 0.2190),
  new THREE.Vector4(-0.2587, +0.9624, -0.0833, 0.2414),
  new THREE.Vector4(-0.4463, -0.8593, -0.2500, 0.1815),
  new THREE.Vector4(+0.8539, +0.3118, -0.4167, 0.2028),
  new THREE.Vector4(-0.7508, +0.3099, -0.5833, 0.2302),
  new THREE.Vector4(+0.2803, -0.5991, -0.7500, 0.2863),
  new THREE.Vector4(+0.1196, +0.3813, -0.9167, 0.2668),
];

export function createClusterMaterial(): THREE.ShaderMaterial {
  const { vertex, fragment } = splitShader(clusterShader);
  return new THREE.ShaderMaterial({
    vertexShader: vertex,
    fragmentShader: fragment,
    uniforms: {
      uTime: { value: 0 },
      uColorInner: { value: new THREE.Color(0xbfe4ff) },
      uColorOuter: { value: new THREE.Color(0x4aa3ff) },
      uIntensity: { value: 1.0 },
      uPulse: { value: 0.0 },
      uTurbulence: { value: 0.6 },
      uSteps: { value: 40 },
      // Wird in jedem Bild gesetzt (siehe orb.ts): die umgekehrte
      // Modellmatrix. Im Shader gibt es dafür kein inverse().
      uInvModel: { value: new THREE.Matrix4() },
      uKoerper: { value: CLUSTER_BODIES.map((v) => v.clone()) },
    },
    transparent: true,
    blending: THREE.NormalBlending,
    depthWrite: true,
    side: THREE.FrontSide,
  });
}

/** Erzeugt das Material für den Kern des Orb. */
export function createCoreMaterial(): THREE.ShaderMaterial {
  const { vertex, fragment } = splitShader(coreShader);
  return new THREE.ShaderMaterial({
    vertexShader: vertex,
    fragmentShader: fragment,
    uniforms: {
      uTime: { value: 0 },
      uDeform: { value: 0.045 },
      uColorInner: { value: new THREE.Color(0xbfe4ff) },
      uColorOuter: { value: new THREE.Color(0x4aa3ff) },
      uIntensity: { value: 1.0 },
    },
    transparent: false,
    depthWrite: true,
  });
}

/**
 * Erzeugt das Material für die leuchtende Hülle.
 *
 * Die Hülle nutzt additives Blending und wird von innen gerendert, damit
 * sie den Kern umschließt, ohne ihn zu verdecken.
 */
export function createShellMaterial(): THREE.ShaderMaterial {
  const { vertex, fragment } = splitShader(fresnelShader);
  return new THREE.ShaderMaterial({
    vertexShader: vertex,
    fragmentShader: fragment,
    uniforms: {
      uTime: { value: 0 },
      uColor: { value: new THREE.Color(0x4aa3ff) },
      uGlowColor: { value: new THREE.Color(0xbfe4ff) },
      uIntensity: { value: 1.0 },
      uPower: { value: 2.6 },
      uOpacity: { value: 0.9 },
    },
    transparent: true,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
    side: THREE.FrontSide,
  });
}

/**
 * Erzeugt das Material für den volumetrischen Nebel im Inneren (Phase 14).
 *
 * Anders als Kern und Hülle beschreibt dieses Material keine Oberfläche,
 * sondern ein Volumen: Der Shader verfolgt jeden Strahl durch die Kugel und
 * sammelt dabei Dichte auf. Deshalb wird von innen gerendert
 * (`side: BackSide`) – so bleibt die Rückseite der Kugel als Eintrittsfläche
 * erhalten, auch wenn die Kamera in die Kugel hineinfährt.
 *
 * `depthWrite` bleibt aus: Der Nebel ist durchscheinend und darf die
 * Tiefenprüfung nicht für alles blockieren, was hinter ihm liegt.
 */
export function createSmokeMaterial(): THREE.ShaderMaterial {
  const { vertex, fragment } = splitShader(smokeShader);
  return new THREE.ShaderMaterial({
    vertexShader: vertex,
    fragmentShader: fragment,
    uniforms: {
      uTime: { value: 0 },
      uColorInner: { value: new THREE.Color(0xdcf1ff) },
      uColorOuter: { value: new THREE.Color(0x2f7fd6) },
      uIntensity: { value: 1.0 },
      uTurbulence: { value: 0.6 },
      uDensity: { value: 1.0 },
      uPulse: { value: 0.0 },
      uSteps: { value: 28 },
      uWarning: { value: 0.0 },
      uInvModel: { value: new THREE.Matrix4() },
    },
    transparent: true,
    blending: THREE.NormalBlending,
    depthWrite: false,
    side: THREE.BackSide,
  });
}

/** Erzeugt das Material für die äußere Aura (weicher, größer, schwächer). */
export function createAuraMaterial(): THREE.ShaderMaterial {
  const material = createShellMaterial();
  material.uniforms.uPower.value = 4.2;
  material.uniforms.uOpacity.value = 0.45;
  material.side = THREE.BackSide;
  return material;
}

/** Erzeugt das Material für die Partikel-Aura. */
export function createParticleMaterial(pixelRatio: number): THREE.ShaderMaterial {
  const { vertex, fragment } = splitShader(particlesShader);
  return new THREE.ShaderMaterial({
    vertexShader: vertex,
    fragmentShader: fragment,
    uniforms: {
      uTime: { value: 0 },
      uSize: { value: 90 },
      uSpread: { value: 1.0 },
      uPixelRatio: { value: pixelRatio },
      uColor: { value: new THREE.Color(0xbfe4ff) },
      uIntensity: { value: 1.0 },
    },
    transparent: true,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
  });
}

/**
 * Letzter Durchgang: bestimmt, was vom Bild überhaupt sichtbar wird.
 *
 * ## Warum die Deckung aus der Helligkeit kommt und nicht aus dem Alphakanal
 *
 * Naheliegend wäre `color.a` – der Alphakanal sagt schließlich, was
 * durchsichtig ist. Nur stimmt er hier nicht: Sobald ein Bild durch einen
 * EffectComposer läuft, schreibt jeder Durchgang in ein eigenes Ziel, und
 * Bloom füllt dabei die *gesamte* Fläche mit Deckung 1. Nach dem Bloom ist
 * jedes Pixel undurchsichtig, auch das leere.
 *
 * Wer dann `color.a` mit einer runden Ausblendung multipliziert, bekommt
 * genau das, was auf dem Bildschirm zu sehen war: eine große schwarze
 * Scheibe mit weichem Rand, in deren Mitte der Orb sitzt. Der Orb selbst
 * war nie zu groß – die Scheibe war es, und sie war so groß wie das Fenster.
 *
 * Die Helligkeit dagegen weiß es besser. Der Orb leuchtet, der Hintergrund
 * ist schwarz. Der hellste Farbkanal ist damit genau das Maß dafür, wie
 * viel an dieser Stelle wirklich da ist. Dunkles wird durchsichtig, Helles
 * bleibt stehen – und ein leuchtender Körper auf einem transparenten
 * Fenster sieht so ohnehin richtiger aus als einer mit hartem Rand.
 */
const EDGE_FADE_SHADER = {
  uniforms: {
    tDiffuse: { value: null as THREE.Texture | null },
    uFadeStart: { value: 0.36 },
    uFadeEnd: { value: 0.5 },
  },
  vertexShader: `
    varying vec2 vUv;
    void main() {
      vUv = uv;
      gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
    }
  `,
  fragmentShader: `
    uniform sampler2D tDiffuse;
    uniform float uFadeStart;
    uniform float uFadeEnd;
    varying vec2 vUv;

    void main() {
      vec4 color = texture2D(tDiffuse, vUv);

      // Der hellste Kanal als Mass fuer die Deckung. Schwarz wird
      // unsichtbar, Leuchtendes bleibt.
      float luminance = max(color.r, max(color.g, color.b));

      // Die unteren Werte etwas anheben, damit der weiche Aussenschein
      // des Bloom nicht abrupt abreisst.
      float alpha = smoothstep(0.02, 0.35, luminance);

      // Zusaetzlich zum Fensterrand hin ausblenden. Ohne das zeichnete
      // sich bei einem sehr hellen Orb die rechteckige Fensterkante ab.
      float fade = 1.0 - smoothstep(uFadeStart, uFadeEnd, length(vUv - vec2(0.5)));

      gl_FragColor = vec4(color.rgb, alpha * fade);
    }
  `,
};

/** Bündelt den Nachbearbeitungs-Stapel. */
export interface PostProcessing {
  composer: EffectComposer;
  bloom: UnrealBloomPass;
  render(): void;
  setSize(width: number, height: number): void;
  setBloomStrength(strength: number): void;
}

/**
 * Baut den Nachbearbeitungs-Stapel auf: Szene rendern, Bloom anwenden,
 * Ränder weich ausblenden.
 *
 * @param renderer Der WebGL-Renderer.
 * @param scene Die zu rendernde Szene.
 * @param camera Die Kamera.
 * @param options Bloom-Parameter aus `config.yaml`.
 */
export function createPostProcessing(
  renderer: THREE.WebGLRenderer,
  scene: THREE.Scene,
  camera: THREE.Camera,
  options: { strength: number; radius: number; threshold: number }
): PostProcessing {
  const size = renderer.getSize(new THREE.Vector2());

  // Ein eigenes Ziel mit Alphakanal und ohne Tiefenpuffer.
  //
  // Das Standardziel des EffectComposer taugt für ein undurchsichtiges
  // Fenster; hier soll am Ende etwas durchscheinen. Die Deckung errechnet
  // der letzte Durchgang zwar aus der Helligkeit, aber ein Ziel ohne
  // Alphakanal verfälscht schon die Farben auf dem Weg dorthin.
  const target = new THREE.WebGLRenderTarget(size.x, size.y, {
    format: THREE.RGBAFormat,
    depthBuffer: true,
    stencilBuffer: false,
  });

  const composer = new EffectComposer(renderer, target);
  composer.setSize(size.x, size.y);

  composer.addPass(new RenderPass(scene, camera));

  const bloom = new UnrealBloomPass(
    new THREE.Vector2(size.x, size.y),
    options.strength,
    options.radius,
    options.threshold
  );
  composer.addPass(bloom);

  const edgeFade = new ShaderPass(EDGE_FADE_SHADER);
  edgeFade.renderToScreen = true;
  composer.addPass(edgeFade);

  const baseStrength = options.strength;

  return {
    composer,
    bloom,
    render(): void {
      composer.render();
    },
    setSize(width: number, height: number): void {
      composer.setSize(width, height);
      bloom.setSize(width, height);
    },
    setBloomStrength(multiplier: number): void {
      bloom.strength = baseStrength * multiplier;
    },
  };
}
