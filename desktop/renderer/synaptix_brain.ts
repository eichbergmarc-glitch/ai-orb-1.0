/**
 * synaptix_brain.ts – Das Synaptix-Gehirn als lebendige Orb-Animation.
 *
 * Die Vorlage ist das Synaptix-Logo: ein Gehirn, dessen linke Haelfte aus
 * fliessender blauer Energie besteht und dessen rechte Haelfte ein dunkles,
 * leuchtendes Neuronennetz ist. In der Mitte trennt beide ein heller
 * Winkel ("<"), an dem die Energie von der fluessigen in die synaptische
 * Seite umschlaegt.
 *
 * Umgesetzt ist das Bild nicht als Grafikdatei, sondern gerechnet:
 *
 *   1. Die Gehirnform entsteht aus weich verschmolzenen Kreisen
 *      (Signed-Distance-Feld). Dadurch ist sie in jeder Groesse scharf
 *      und laesst sich an den Raendern zum Leuchten bringen.
 *   2. Die linke Haelfte ist ein zweifach domaenenverzerrter Rauschfluss –
 *      das ergibt Wellen, die tatsaechlich stroemen statt nur zu wabern.
 *   3. Die rechte Haelfte ist echte Geometrie: Knoten und Verbindungen,
 *      die aus derselben Gehirnform gewuerfelt werden. Auf jeder
 *      Verbindung laeuft ein Signal – im Shader, nicht in JavaScript,
 *      damit auch 300 Verbindungen nichts kosten.
 *   4. Alles Leuchtende liegt additiv oben und wird vom bestehenden
 *      Bloom-Pass des Renderers aufgenommen.
 *
 * Die Klasse ist absichtlich zur bestehenden `EnergyOrb` schnittstellen-
 * gleich: dieselben oeffentlichen Methoden, dieselben Zustandswerte aus
 * `states.ts`. Dadurch ist der Wechsel in `main.ts` eine einzige Zeile und
 * `orb.energie: true` bleibt als Rueckweg unangetastet bestehen.
 */

import * as THREE from "three";

import type { StateAppearance, OrbStateName } from "./states";
import type { OrbEmotionName, OrbVisualStyle } from "./energy_orb";

// ---------------------------------------------------------------------------
// Die Gehirnform
// ---------------------------------------------------------------------------

/**
 * Die Kreise, aus denen die Gehirnkontur weich verschmolzen wird.
 *
 * Reihenfolge und Werte sind an der Silhouette der Vorlage abgenommen:
 * ein breiter Kern, drei Lappen oben, zwei Schlaefen, drei Lappen unten,
 * dazu Kleinhirn und Hirnstamm. `k` ist die Verschmelzungsweite – je
 * groesser, desto organischer und weniger "aus Kreisen gebaut".
 */
const HIRN_KREISE: Array<{ x: number; y: number; r: number; k: number }> = [
  // Grosshirn: die obere Masse
  { x: 0.0, y: 0.16, r: 0.5, k: 0.26 },
  { x: -0.36, y: 0.28, r: 0.34, k: 0.26 },
  { x: 0.34, y: 0.26, r: 0.34, k: 0.26 },
  { x: -0.55, y: 0.0, r: 0.26, k: 0.24 },
  { x: 0.56, y: 0.02, r: 0.26, k: 0.24 },
  { x: 0.0, y: -0.14, r: 0.44, k: 0.26 },
  // Schlaefenlappen: nach vorne unten gezogen
  { x: -0.34, y: -0.34, r: 0.26, k: 0.22 },
  { x: -0.54, y: -0.24, r: 0.18, k: 0.2 },
  // Kleinhirn: die kompakte Masse hinten unten
  { x: 0.34, y: -0.42, r: 0.22, k: 0.18 },
  { x: 0.14, y: -0.5, r: 0.19, k: 0.18 },
  // Hirnstamm
  { x: 0.04, y: -0.66, r: 0.11, k: 0.14 },
];

/**
 * Die Kerbe zwischen Schlaefenlappen und Kleinhirn.
 *
 * Ohne sie bleibt die Silhouette ein Klumpen. Erst dieser eine
 * herausgeschnittene Kreis macht aus der Masse ein Gehirn: Er trennt die
 * beiden unteren Lappen sichtbar voneinander.
 */
const HIRN_KERBE = { x: -0.11, y: -0.9, r: 0.28, k: 0.09 };

/** Weiches Minimum - die Verschmelzung zweier Formen ohne harte Kante. */
function weichesMinimum(a: number, b: number, k: number): number {
  const h = Math.min(1, Math.max(0, 0.5 + (0.5 * (b - a)) / k));
  return b * (1 - h) + a * h - k * h * (1 - h);
}

/** Weiches Maximum - dasselbe fuer das Herausschneiden. */
function weichesMaximum(a: number, b: number, k: number): number {
  const h = Math.min(1, Math.max(0, 0.5 - (0.5 * (b - a)) / k));
  return b * (1 - h) + a * h + k * h * (1 - h);
}

/**
 * Abstand zur Gehirnkontur. Negativ heisst innerhalb.
 *
 * Auf die verschmolzenen Kreise kommt zum Schluss eine leise Welle in
 * Abhaengigkeit vom Winkel. Sie kostet nichts und nimmt der Form das
 * Gebaute: Aus glatten Boegen werden Windungen.
 *
 * Dieselbe Rechnung laeuft im Shader - der GLSL-Text unten wird aus
 * genau diesen Werten erzeugt, damit beide nie auseinanderlaufen koennen.
 */
export function gehirnAbstand(x: number, y: number): number {
  let d = Math.hypot(x - HIRN_KREISE[0].x, y - HIRN_KREISE[0].y) - HIRN_KREISE[0].r;
  for (let i = 1; i < HIRN_KREISE.length; i += 1) {
    const c = HIRN_KREISE[i];
    d = weichesMinimum(d, Math.hypot(x - c.x, y - c.y) - c.r, c.k);
  }
  const kerbe = Math.hypot(x - HIRN_KERBE.x, y - HIRN_KERBE.y) - HIRN_KERBE.r;
  d = weichesMaximum(d, -kerbe, HIRN_KERBE.k);
  const winkel = Math.atan2(y, x);
  d += 0.026 * Math.sin(winkel * 3.0 + 0.9) + 0.016 * Math.sin(winkel * 6.0 - 1.4);
  return d;
}

/** Der GLSL-Zwilling - aus derselben Liste erzeugt. */
const GLSL_GEHIRN = `
float weichesMinimum(float a, float b, float k) {
  float h = clamp(0.5 + 0.5 * (b - a) / k, 0.0, 1.0);
  return mix(b, a, h) - k * h * (1.0 - h);
}

float weichesMaximum(float a, float b, float k) {
  float h = clamp(0.5 - 0.5 * (b - a) / k, 0.0, 1.0);
  return mix(b, a, h) + k * h * (1.0 - h);
}

float kreis(vec2 p, vec2 c, float r) {
  return length(p - c) - r;
}

float gehirnAbstand(vec2 p) {
  float d = kreis(p, vec2(${HIRN_KREISE[0].x.toFixed(3)}, ${HIRN_KREISE[0].y.toFixed(3)}), ${HIRN_KREISE[0].r.toFixed(3)});
${HIRN_KREISE.slice(1)
  .map(
    (c) =>
      `  d = weichesMinimum(d, kreis(p, vec2(${c.x.toFixed(3)}, ${c.y.toFixed(3)}), ${c.r.toFixed(3)}), ${c.k.toFixed(3)});`
  )
  .join("\n")}
  d = weichesMaximum(d, -kreis(p, vec2(${HIRN_KERBE.x.toFixed(3)}, ${HIRN_KERBE.y.toFixed(3)}), ${HIRN_KERBE.r.toFixed(3)}), ${HIRN_KERBE.k.toFixed(3)});
  float winkel = atan(p.y, p.x);
  d += 0.026 * sin(winkel * 3.0 + 0.9) + 0.016 * sin(winkel * 6.0 - 1.4);
  return d;
}
`;

/** Rauschen und fraktale Summe – die Grundlage der fliessenden Haelfte. */
const GLSL_RAUSCHEN = `
float streu(vec2 p) {
  vec3 p3 = fract(vec3(p.xyx) * 0.1031);
  p3 += dot(p3, p3.yzx + 33.33);
  return fract((p3.x + p3.y) * p3.z);
}

float rauschen(vec2 p) {
  vec2 i = floor(p);
  vec2 f = fract(p);
  vec2 u = f * f * (3.0 - 2.0 * f);
  float a = streu(i);
  float b = streu(i + vec2(1.0, 0.0));
  float c = streu(i + vec2(0.0, 1.0));
  float d = streu(i + vec2(1.0, 1.0));
  return mix(mix(a, b, u.x), mix(c, d, u.x), u.y);
}

float fraktal(vec2 p) {
  float summe = 0.0;
  float gewicht = 0.5;
  for (int i = 0; i < 5; i++) {
    summe += gewicht * rauschen(p);
    p = p * 2.03 + vec2(11.7, 5.3);
    gewicht *= 0.5;
  }
  return summe;
}
`;

/**
 * Der trennende Winkel in der Mitte ("<").
 *
 * Er ist nicht nur Dekoration: Dieselbe Funktion entscheidet auch, wo die
 * fliessende Haelfte endet und die synaptische beginnt. Dadurch sitzt die
 * Kante immer exakt im Licht und wirkt wie eine Naht, nicht wie ein
 * Schnitt.
 */
const GLSL_WINKEL = `
float streckeAbstand(vec2 p, vec2 a, vec2 b) {
  vec2 pa = p - a;
  vec2 ba = b - a;
  float h = clamp(dot(pa, ba) / dot(ba, ba), 0.0, 1.0);
  return length(pa - ba * h);
}

float winkelAbstand(vec2 p, float mitte) {
  vec2 q = vec2(p.x - mitte, abs(p.y));
  return streckeAbstand(q, vec2(-0.10, 0.0), vec2(0.34, 0.50));
}
`;

// ---------------------------------------------------------------------------
// Der Koerper: fliessende Haelfte, dunkle Haelfte, Naht und Rand
// ---------------------------------------------------------------------------

const KOERPER_VERTEX = `
varying vec2 vLage;
void main() {
  vLage = (uv - 0.5) * 2.8;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`;

const KOERPER_FRAGMENT = `
precision highp float;

uniform float uZeit;      // fortlaufende, tempoabhaengige Eigenzeit
uniform float uTempo;     // Zustandstempo, wirkt auf Wellen und Naht
uniform float uFluss;     // wie kraeftig die Fluessigkeit arbeitet
uniform float uHelligkeit;
uniform float uPuls;      // Atmen bzw. Sprechrhythmus
uniform float uStimme;    // Sprechpegel 0..1
uniform float uBlitz;     // kurzer Lichtimpuls bei Zustandswechseln
uniform float uNaht;      // Leuchtkraft des Winkels
uniform float uWach;      // 1 = wach, 0 = offline/schlafend (entsaettigt)
uniform vec3  uTief;      // dunkle Grundfarbe der synaptischen Haelfte
uniform vec3  uFluid;     // Hauptton der fliessenden Haelfte
uniform vec3  uLicht;     // Spitzlichter, Rand und Naht

varying vec2 vLage;

${GLSL_GEHIRN}
${GLSL_RAUSCHEN}
${GLSL_WINKEL}

void main() {
  vec2 p = vLage;
  float d = gehirnAbstand(p);

  // Weiche Kante statt Treppenstufen: Die Breite folgt der tatsaechlichen
  // Bildschirmaufloesung, deshalb bleibt der Rand bei jeder Orb-Groesse
  // gleich sauber.
  float kante = fwidth(d) * 1.5 + 0.004;
  float innen = smoothstep(kante, -kante, d);
  if (innen <= 0.001 && d > 0.22) discard;

  // --- Die Naht in der Mitte -------------------------------------------
  float nahtMitte = -0.02 + 0.012 * sin(uZeit * 0.6);
  float dw = winkelAbstand(p, nahtMitte);

  // Links der Naht fliesst es, rechts denkt es. Der Uebergang ist bewusst
  // breit: So wirkt die Naht wie ein Umschlagpunkt, nicht wie eine Grenze.
  float seite = smoothstep(-0.03, 0.11, p.x - nahtMitte - abs(p.y) * 0.28);

  // --- Die fliessende Haelfte ------------------------------------------
  // Zweifache Domaenenverzerrung. Der erste Durchgang biegt den Raum, der
  // zweite biegt die Biegung – erst dadurch entstehen Wirbel, die sich
  // ineinander schieben, statt nur gemeinsam zu wandern.
  float t = uZeit;
  vec2 q = vec2(
    fraktal(p * 2.1 + vec2(0.0, t * 0.22)),
    fraktal(p * 2.1 + vec2(5.2, 1.3) - vec2(t * 0.17, 0.0))
  );
  vec2 r = vec2(
    fraktal(p * 2.6 + 2.6 * q + vec2(1.7, 9.2) + vec2(t * 0.31, t * 0.12)),
    fraktal(p * 2.6 + 2.6 * q + vec2(8.3, 2.8) - vec2(t * 0.24, t * 0.09))
  );
  float f = fraktal(p * 2.2 + 3.2 * r * uFluss);

  // Ein Wirbel um den Schwerpunkt der linken Haelfte: die charakteristische
  // Drehung der Vorlage.
  vec2 w = p - vec2(-0.34, 0.02);
  // Der Faktor vor dem Winkel MUSS ganzzahlig sein. atan springt an der
  // negativen x-Achse um 2*pi; nur bei ganzzahligem Vielfachen faellt der
  // Sprung im Sinus wieder heraus. Bei 1.35 lief ein sichtbarer, gerader
  // Strich vom Wirbelzentrum nach links - kein Rauschfehler, ein
  // Schnitt im Koordinatensystem.
  float wirbel = atan(w.y, w.x) * 2.0 - length(w) * 3.4 + t * 0.85;

  // Aus dem Rauschfeld werden Baender. Sie wandern nach aussen, wie eine
  // Fluessigkeit, die aus der Mitte quillt.
  float baender = sin(f * 6.0 + wirbel - t * 1.5) * 0.5 + 0.5;
  baender = pow(baender, 1.9);
  float schaum = smoothstep(0.66, 0.96, baender);

  vec3 fluid = mix(uTief * 1.25, uFluid, clamp(f * 1.35, 0.0, 1.0));
  fluid = mix(fluid, uFluid * 1.40, baender * 0.78);
  fluid += uLicht * schaum * (0.42 + 0.38 * uStimme);

  // --- Die synaptische Haelfte -----------------------------------------
  // Hier bleibt der Grund bewusst dunkel: Die Knoten und Bahnen liegen als
  // eigene Geometrie darueber und sollen aus dem Dunkeln kommen.
  float tiefe = smoothstep(0.9, -0.2, length(p * vec2(1.0, 1.15)));
  vec3 dunkel = uTief * (0.35 + 0.55 * tiefe);
  // Ein leiser Schimmer, damit die Haelfte nicht tot wirkt, wenn gerade
  // kein Signal laeuft.
  float schimmer = fraktal(p * 3.4 - vec2(t * 0.12, t * 0.05));
  dunkel += uFluid * 0.10 * smoothstep(0.55, 0.95, schimmer);

  vec3 farbe = mix(fluid, dunkel, seite);

  // --- Naht, Rand und Atem ---------------------------------------------
  // Die Naht bleibt bewusst INNERHALB der Form (Faktor innen). Ohne das
  // stach der Winkel oben und unten aus dem Gehirn heraus und sah aus wie
  // ein daraufgelegtes Zeichen statt wie ein Umschlagpunkt.
  float naht = exp(-dw * 44.0) * (0.65 + 0.35 * sin(uZeit * 2.2)) * innen;
  farbe += mix(uFluid, uLicht, 0.70) * naht * uNaht * 0.95;

  // Der Rand traegt das meiste Licht – das ist der Grund, warum die Form
  // auch vor hellem Desktop-Hintergrund noch als Gehirn lesbar bleibt.
  float rand = exp(-abs(d) * 40.0);
  farbe += mix(uFluid, uLicht, 0.5) * rand * (0.62 + 0.30 * uPuls);

  // Aussen: eine weiche Aura, die nur additiv dazukommt.
  float aura = exp(max(d, 0.0) * -9.0) * smoothstep(-0.002, 0.05, d);

  float atem = 1.0 + 0.10 * uPuls * sin(uZeit * 1.9) + 0.22 * uStimme;
  farbe *= atem * uHelligkeit;
  farbe += uLicht * uBlitz * (rand * 2.0 + innen * 0.35);

  // Offline/Schlaf: nicht ausschalten, sondern entfaerben und dimmen. Der
  // Orb sieht dann muede aus, nicht abgestuerzt.
  float grau = dot(farbe, vec3(0.299, 0.587, 0.114));
  farbe = mix(vec3(grau) * 0.7, farbe, uWach);

  float deckung = innen * (0.90 + 0.10 * uPuls) + aura * 0.30 * uHelligkeit;
  deckung = clamp(deckung, 0.0, 1.0);
  if (deckung < 0.004) discard;

  gl_FragColor = vec4(farbe * deckung, deckung);
}
`;

// ---------------------------------------------------------------------------
// Das Neuronennetz: Bahnen mit laufenden Signalen und pulsende Knoten
// ---------------------------------------------------------------------------

const BAHN_VERTEX = `
attribute float aLauf;   // 0 am Anfang der Bahn, 1 am Ende
attribute float aKeim;   // eigener Zufallswert je Bahn
varying float vLauf;
varying float vKeim;
void main() {
  vLauf = aLauf;
  vKeim = aKeim;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`;

const BAHN_FRAGMENT = `
precision highp float;
uniform float uZeit;
uniform float uFeuer;      // wie kraeftig die Signale sind
uniform float uGrund;      // Grundhelligkeit der ruhenden Bahn
uniform vec3  uFarbe;
uniform vec3  uSignal;
varying float vLauf;
varying float vKeim;

void main() {
  // Jede Bahn hat ihren eigenen Startzeitpunkt und ihre eigene
  // Geschwindigkeit. Ohne das wuerde das ganze Netz im Gleichtakt blinken –
  // und ein Gehirn, das im Gleichtakt blinkt, wirkt wie eine Lichterkette.
  float tempo = 0.35 + 0.55 * fract(vKeim * 7.13);
  float kopf = fract(uZeit * tempo + vKeim);
  float abstand = abs(vLauf - kopf);
  abstand = min(abstand, 1.0 - abstand);

  float signal = exp(-abstand * 26.0);
  float schweif = exp(-abstand * 7.0) * 0.35;

  float staerke = uGrund + (signal + schweif) * uFeuer;
  vec3 farbe = mix(uFarbe, uSignal, clamp(signal * 1.4, 0.0, 1.0));

  gl_FragColor = vec4(farbe * staerke, staerke);
}
`;

const KNOTEN_VERTEX = `
attribute float aKeim;
attribute float aGroesse;
uniform float uZeit;
uniform float uPixel;
uniform float uFeuer;
varying float vKeim;
varying float vSchlag;
void main() {
  vKeim = aKeim;
  // Jeder Knoten feuert in eigenem Takt. Der kurze, harte Anstieg und das
  // langsame Abklingen sind bewusst: So sieht es nach Entladung aus und
  // nicht nach Pulsieren.
  float takt = fract(uZeit * (0.22 + 0.45 * fract(aKeim * 3.71)) + aKeim);
  vSchlag = pow(1.0 - takt, 5.0);
  vec4 sicht = modelViewMatrix * vec4(position, 1.0);
  float groesse = aGroesse * (1.0 + 1.5 * vSchlag * uFeuer);
  gl_PointSize = groesse * uPixel / max(0.001, -sicht.z);
  gl_Position = projectionMatrix * sicht;
}
`;

const KNOTEN_FRAGMENT = `
precision highp float;
uniform vec3 uFarbe;
uniform vec3 uKern;
uniform float uHelligkeit;
varying float vKeim;
varying float vSchlag;

void main() {
  vec2 m = gl_PointCoord - 0.5;
  float r = length(m) * 2.0;
  if (r > 1.0) discard;

  float kern = exp(-r * r * 9.0);
  float hof  = exp(-r * r * 2.2) * 0.55;
  float staerke = (kern + hof) * (0.45 + 0.85 * vSchlag) * uHelligkeit;

  vec3 farbe = mix(uFarbe, uKern, kern * (0.5 + 0.5 * vSchlag));
  gl_FragColor = vec4(farbe * staerke, staerke);
}
`;

// ---------------------------------------------------------------------------
// Aura, Bodenschein und Fortschrittsbogen
// ---------------------------------------------------------------------------

const AURA_FRAGMENT = `
precision highp float;
uniform float uZeit;
uniform float uStaerke;
uniform vec3  uFarbe;
varying vec2 vLage;

${GLSL_GEHIRN}

void main() {
  float d = gehirnAbstand(vLage);
  // Weich einblenden statt hart abschneiden: Ein Sprung an dieser Stelle
  // zeichnete einen sichtbaren Ring um das Gehirn.
  float saum = smoothstep(-0.06, 0.03, d);
  // Die Aura folgt der Gehirnform, nicht einem Kreis. Deshalb liest man
  // die Silhouette selbst dann noch, wenn der Koerper fast dunkel ist.
  float hof = exp(-max(d, 0.0) * 4.2);
  float wellen = 0.92 + 0.08 * sin(uZeit * 1.4 - d * 9.0);
  float a = hof * wellen * saum * uStaerke;
  if (a < 0.003) discard;
  gl_FragColor = vec4(uFarbe * a, a);
}
`;

const BODEN_FRAGMENT = `
precision highp float;
uniform float uStaerke;
uniform vec3  uFarbe;
varying vec2 vLage;
void main() {
  // Bewusst als flache Ellipse: Sie liest sich als Schatten-Gegenstueck
  // zur Schwebehoehe und verankert das Gehirn im Raum.
  float r = length(vLage * vec2(1.0, 3.1));
  float a = exp(-r * r * 2.2) * uStaerke;
  if (a < 0.003) discard;
  gl_FragColor = vec4(uFarbe * a, a);
}
`;

const BOGEN_FRAGMENT = `
precision highp float;
uniform float uFortschritt;   // 0..1
uniform float uUnbestimmt;    // 1 = Umlauf statt Fuellstand
uniform float uZeit;
uniform float uStaerke;
uniform vec3  uFarbe;
varying vec2 vLage;

void main() {
  float r = length(vLage);
  float ring = exp(-pow((r - 1.06) * 34.0, 2.0));
  if (ring < 0.004) discard;

  // Oben beginnen und im Uhrzeigersinn laufen – so, wie ein Mensch eine
  // Fortschrittsanzeige liest.
  float winkel = atan(vLage.x, vLage.y) / 6.2831853;
  winkel = fract(winkel + 1.0);

  float sichtbar;
  if (uUnbestimmt > 0.5) {
    float kopf = fract(uZeit * 0.42);
    float ab = abs(winkel - kopf);
    ab = min(ab, 1.0 - ab);
    sichtbar = exp(-ab * 9.0);
  } else {
    sichtbar = smoothstep(0.012, 0.0, winkel - uFortschritt);
  }

  float a = ring * sichtbar * uStaerke;
  if (a < 0.004) discard;
  gl_FragColor = vec4(uFarbe * a, a);
}
`;

// ---------------------------------------------------------------------------
// Erzeugung des Netzes
// ---------------------------------------------------------------------------

/** Kleiner, wiederholbarer Zufall – das Netz sieht bei jedem Start gleich aus. */
function zufall(keim: number): () => number {
  let a = keim >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), 1 | t);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

interface Netz {
  knoten: Array<{ x: number; y: number; z: number; g: number; k: number }>;
  bahnen: Array<[number, number]>;
}

/**
 * Wuerfelt Knoten in die rechte Gehirnhaelfte und verbindet sie.
 *
 * Die Knoten werden verworfen, solange sie zu nah am Rand, zu nah an der
 * Naht oder zu nah aneinander liegen. Der Mindestabstand ist das
 * Entscheidende: Ohne ihn entstehen Klumpen, und ein Netz mit Klumpen
 * sieht nach Zufall aus statt nach Struktur.
 */
function netzBauen(anzahl: number, keim: number): Netz {
  const wuerfel = zufall(keim);
  const knoten: Netz["knoten"] = [];
  const mindestAbstand = 0.112;

  for (let versuch = 0; versuch < 6000 && knoten.length < anzahl; versuch += 1) {
    const x = -0.05 + wuerfel() * 0.95;
    const y = (wuerfel() - 0.5) * 1.6;
    if (gehirnAbstand(x, y) > -0.06) continue;
    // Rechts der Naht: dieselbe Trennlinie wie im Koerper-Shader.
    if (x + 0.02 - Math.abs(y) * 0.28 < 0.02) continue;

    let frei = true;
    for (const k of knoten) {
      if (Math.hypot(k.x - x, k.y - y) < mindestAbstand) {
        frei = false;
        break;
      }
    }
    if (!frei) continue;

    knoten.push({
      x,
      y,
      // Eine leichte Tiefenstreuung. Sie ist winzig, macht aber aus einer
      // flachen Zeichnung ein Netz, das bei der Neigung zur Maus atmet.
      z: (wuerfel() - 0.5) * 0.16,
      g: 5.5 + wuerfel() * 7.5,
      k: wuerfel(),
    });
  }

  // Jeder Knoten sucht seine naechsten Nachbarn. Doppelte Verbindungen
  // werden ueber ein Schluesselpaar ausgeschlossen.
  const bahnen: Array<[number, number]> = [];
  const gesehen = new Set<string>();
  for (let i = 0; i < knoten.length; i += 1) {
    const abstaende = knoten
      .map((k, j) => ({ j, d: Math.hypot(k.x - knoten[i].x, k.y - knoten[i].y) }))
      .filter((e) => e.j !== i && e.d < 0.34)
      .sort((a, b) => a.d - b.d)
      .slice(0, 3);
    for (const e of abstaende) {
      const schluessel = i < e.j ? `${i}:${e.j}` : `${e.j}:${i}`;
      if (gesehen.has(schluessel)) continue;
      gesehen.add(schluessel);
      bahnen.push([i, e.j]);
    }
  }

  return { knoten, bahnen };
}

// ---------------------------------------------------------------------------
// Die Klasse
// ---------------------------------------------------------------------------

/** Zusaetzliche Zustandsfarben, die `states.ts` so nicht kennt. */
interface Zustandsbild {
  tief: number;
  fluid: number;
  licht: number;
  netz: number;
  signal: number;
}

/**
 * Farbcharakter je Zustand.
 *
 * `states.ts` liefert bereits weich ueberblendete Farben; die hier sind die
 * *Rollen*, die das Gehirn zusaetzlich braucht (Grundton der Fluessigkeit,
 * Farbe der Bahnen, Farbe eines laufenden Signals). Fehlt ein Zustand,
 * gilt `idle`.
 */
const ZUSTANDSBILD: Partial<Record<OrbStateName, Zustandsbild>> = {
  // Alles bleibt im BLAUEN Feld.
  //
  // Vorher war "arbeitet" tuerkis und "erfolg" gruen. Beide leuchteten
  // heller als der Ruhezustand und zogen dadurch den Blick auf sich,
  // obwohl sie das Haeufigste sind, was der Orb tut - das Ergebnis war ein
  // Gruenstich, der die Anzeige unuebersichtlich machte. Jetzt trennt die
  // Zustaende die HELLIGKEIT innerhalb desselben Blaus, nicht ein
  // Farbwechsel: ruhig und tief im Leerlauf, hell und klar beim Antworten.
  //
  // Warnung und Fehler behalten Bernstein und Rot. Sie sind selten, und
  // genau dort ist ein Farbwechsel richtig - er soll auffallen.
  idle:      { tief: 0x030b1c, fluid: 0x1f6fd0, licht: 0x8fd4ff, netz: 0x1a5fa8, signal: 0x7fe4ff },
  listening: { tief: 0x04122a, fluid: 0x2a8ae8, licht: 0xb0e8ff, netz: 0x2477c4, signal: 0x9deeff },
  thinking:  { tief: 0x050d24, fluid: 0x3f6ae0, licht: 0xa9c4ff, netz: 0x3a5fc8, signal: 0x8fd0ff },
  speaking:  { tief: 0x04122a, fluid: 0x2f9be8, licht: 0xc8f0ff, netz: 0x2a86cc, signal: 0xbdeeff },
  executing: { tief: 0x02142e, fluid: 0x1785d8, licht: 0x9fdcff, netz: 0x1470b8, signal: 0x8ce0ff },
  busy:      { tief: 0x02142e, fluid: 0x1785d8, licht: 0x9fdcff, netz: 0x1470b8, signal: 0x8ce0ff },
  waiting:   { tief: 0x060f22, fluid: 0x3a6aa8, licht: 0x9dbde0, netz: 0x33598c, signal: 0x8fb4d8 },
  success:   { tief: 0x031a33, fluid: 0x2ec2ff, licht: 0xd8f6ff, netz: 0x27a6dd, signal: 0xcdf2ff },
  warning:   { tief: 0x231603, fluid: 0xd99420, licht: 0xffdca0, netz: 0xba7f1a, signal: 0xffcf85 },
  error:     { tief: 0x25070a, fluid: 0xd8423c, licht: 0xffb8b2, netz: 0xb83833, signal: 0xff9f97 },
  offline:   { tief: 0x0a0f18, fluid: 0x455468, licht: 0x8496a8, netz: 0x3d4b5e, signal: 0x718499 },
  sleep:     { tief: 0x050912, fluid: 0x22355a, licht: 0x5d7aa4, netz: 0x1e2f4d, signal: 0x4f6b93 },
};

const IDLE_BILD = ZUSTANDSBILD.idle as Zustandsbild;

export class SynaptixBrain {
  /** Der Gehirnkoerper. Haengt in der Traegergruppe von `main.ts`. */
  public readonly group: THREE.Group;
  /** Der Bodenschein. Haengt am Traeger, damit er nicht mitschwebt. */
  public readonly groundGroup: THREE.Group;

  private readonly koerper: THREE.Mesh;
  private readonly aura: THREE.Mesh;
  private readonly boden: THREE.Mesh;
  private readonly bogen: THREE.Mesh;
  private readonly bahnen: THREE.LineSegments;
  private readonly knoten: THREE.Points;
  private readonly netzGruppe: THREE.Group;

  private readonly uKoerper: Record<string, THREE.IUniform>;
  private readonly uAura: Record<string, THREE.IUniform>;
  private readonly uBoden: Record<string, THREE.IUniform>;
  private readonly uBogen: Record<string, THREE.IUniform>;
  private readonly uBahn: Record<string, THREE.IUniform>;
  private readonly uKnoten: Record<string, THREE.IUniform>;

  private readonly netz: Netz;
  private readonly pixelRatio: number;
  private readonly grundTempo: number;
  private readonly grundHelligkeit: number;

  /** Eigenzeit: laeuft mit dem Zustandstempo, nie mit der absoluten Uhr. */
  private eigenzeit = 0;
  private basisSkala = 0.28;
  private zustand: OrbStateName = "idle";
  private blitz = 0;
  private stimme = 0;
  private schwebe = 0;
  private zeigerZiel = new THREE.Vector2(0, 0);
  private zeiger = new THREE.Vector2(0, 0);
  private fortschritt: number | null = null;
  private unbestimmt = false;
  private professor = false;
  private gefuehl: OrbEmotionName | null = null;
  private gefuehlRest = 0;
  private reizRest = 0;
  private qualitaet = 2;

  private readonly farbTief = new THREE.Color(IDLE_BILD.tief);
  private readonly farbFluid = new THREE.Color(IDLE_BILD.fluid);
  private readonly farbLicht = new THREE.Color(IDLE_BILD.licht);
  private readonly farbNetz = new THREE.Color(IDLE_BILD.netz);
  private readonly farbSignal = new THREE.Color(IDLE_BILD.signal);
  private readonly hilfsfarbe = new THREE.Color();

  constructor(options?: { tempo?: number; helligkeit?: number }, pixelRatio = 1) {
    this.pixelRatio = Math.max(1, pixelRatio);
    this.grundTempo = options?.tempo ?? 1.0;
    // Der Wert aus config.yaml ist auf den alten Orb geeicht (1.69). Das
    // Gehirn leuchtet flaechig statt punktuell; ungedaempft uebernommen
    // waere es ausgebrannt statt hell.
    this.grundHelligkeit = 0.50 + 0.32 * (options?.helligkeit ?? 1.0);

    this.group = new THREE.Group();
    this.groundGroup = new THREE.Group();
    this.netzGruppe = new THREE.Group();

    const flaeche = new THREE.PlaneGeometry(2.8, 2.8, 1, 1);

    // --- Aura (ganz hinten, additiv) --------------------------------------
    this.uAura = {
      uZeit: { value: 0 },
      uStaerke: { value: 0.5 },
      uFarbe: { value: new THREE.Color(IDLE_BILD.fluid) },
    };
    this.aura = new THREE.Mesh(
      flaeche.clone(),
      new THREE.ShaderMaterial({
        uniforms: this.uAura,
        vertexShader: KOERPER_VERTEX,
        fragmentShader: AURA_FRAGMENT,
        transparent: true,
        depthWrite: false,
        depthTest: false,
        blending: THREE.AdditiveBlending,
        premultipliedAlpha: true,
      })
    );
    // Bewusst NICHT vergroessert: Eine skalierte Aura hat ihre eigene
    // Kontur - und die erschien als zweiter, heller Umriss um das Gehirn.
    // Stattdessen faellt der Schein vom echten Rand nach aussen ab.
    this.aura.renderOrder = 0;
    this.group.add(this.aura);

    // --- Koerper ------------------------------------------------------------
    this.uKoerper = {
      uZeit: { value: 0 },
      uTempo: { value: 1 },
      uFluss: { value: 1 },
      uHelligkeit: { value: this.grundHelligkeit },
      uPuls: { value: 0.35 },
      uStimme: { value: 0 },
      uBlitz: { value: 0 },
      uNaht: { value: 1 },
      uWach: { value: 1 },
      uTief: { value: this.farbTief },
      uFluid: { value: this.farbFluid },
      uLicht: { value: this.farbLicht },
    };
    this.koerper = new THREE.Mesh(
      flaeche.clone(),
      new THREE.ShaderMaterial({
        uniforms: this.uKoerper,
        vertexShader: KOERPER_VERTEX,
        fragmentShader: KOERPER_FRAGMENT,
        transparent: true,
        depthWrite: false,
        depthTest: false,
        premultipliedAlpha: true,
      })
    );
    this.koerper.renderOrder = 1;
    this.group.add(this.koerper);

    // --- Netz ---------------------------------------------------------------
    this.netz = netzBauen(62, 0x5ee7);
    this.uBahn = {
      uZeit: { value: 0 },
      uFeuer: { value: 1 },
      uGrund: { value: 0.30 },
      uFarbe: { value: this.farbNetz },
      uSignal: { value: this.farbSignal },
    };
    this.uKnoten = {
      uZeit: { value: 0 },
      uPixel: { value: 120 },
      uFeuer: { value: 1 },
      uFarbe: { value: this.farbNetz },
      uKern: { value: this.farbSignal },
      uHelligkeit: { value: 1 },
    };
    this.bahnen = this.bahnenBauen();
    this.knoten = this.knotenBauen();
    this.netzGruppe.add(this.bahnen);
    this.netzGruppe.add(this.knoten);
    this.netzGruppe.renderOrder = 2;
    this.group.add(this.netzGruppe);

    // --- Fortschrittsbogen ---------------------------------------------------
    this.uBogen = {
      uFortschritt: { value: 0 },
      uUnbestimmt: { value: 0 },
      uZeit: { value: 0 },
      uStaerke: { value: 0 },
      uFarbe: { value: new THREE.Color(IDLE_BILD.licht) },
    };
    this.bogen = new THREE.Mesh(
      flaeche.clone(),
      new THREE.ShaderMaterial({
        uniforms: this.uBogen,
        vertexShader: KOERPER_VERTEX,
        fragmentShader: BOGEN_FRAGMENT,
        transparent: true,
        depthWrite: false,
        depthTest: false,
        blending: THREE.AdditiveBlending,
        premultipliedAlpha: true,
      })
    );
    this.bogen.renderOrder = 3;
    this.bogen.visible = false;
    this.group.add(this.bogen);

    // --- Bodenschein ---------------------------------------------------------
    this.uBoden = {
      uStaerke: { value: 0.34 },
      uFarbe: { value: new THREE.Color(IDLE_BILD.fluid) },
    };
    this.boden = new THREE.Mesh(
      flaeche.clone(),
      new THREE.ShaderMaterial({
        uniforms: this.uBoden,
        vertexShader: KOERPER_VERTEX,
        fragmentShader: BODEN_FRAGMENT,
        transparent: true,
        depthWrite: false,
        depthTest: false,
        blending: THREE.AdditiveBlending,
        premultipliedAlpha: true,
      })
    );
    this.boden.renderOrder = 0;
    this.groundGroup.add(this.boden);

    this.group.scale.setScalar(this.basisSkala);
  }

  /** Baut die Verbindungslinien mit Lauf- und Keimattribut. */
  private bahnenBauen(): THREE.LineSegments {
    const anzahl = this.netz.bahnen.length;
    const punkte = new Float32Array(anzahl * 2 * 3);
    const lauf = new Float32Array(anzahl * 2);
    const keim = new Float32Array(anzahl * 2);

    this.netz.bahnen.forEach(([a, b], i) => {
      const ka = this.netz.knoten[a];
      const kb = this.netz.knoten[b];
      punkte.set([ka.x, ka.y, ka.z, kb.x, kb.y, kb.z], i * 6);
      lauf[i * 2] = 0;
      lauf[i * 2 + 1] = 1;
      const eigen = (ka.k + kb.k) * 0.5;
      keim[i * 2] = eigen;
      keim[i * 2 + 1] = eigen;
    });

    const geometrie = new THREE.BufferGeometry();
    geometrie.setAttribute("position", new THREE.BufferAttribute(punkte, 3));
    geometrie.setAttribute("aLauf", new THREE.BufferAttribute(lauf, 1));
    geometrie.setAttribute("aKeim", new THREE.BufferAttribute(keim, 1));

    return new THREE.LineSegments(
      geometrie,
      new THREE.ShaderMaterial({
        uniforms: this.uBahn,
        vertexShader: BAHN_VERTEX,
        fragmentShader: BAHN_FRAGMENT,
        transparent: true,
        depthWrite: false,
        depthTest: false,
        blending: THREE.AdditiveBlending,
        premultipliedAlpha: true,
      })
    );
  }

  /** Baut die Knotenpunkte. */
  private knotenBauen(): THREE.Points {
    const anzahl = this.netz.knoten.length;
    const punkte = new Float32Array(anzahl * 3);
    const keim = new Float32Array(anzahl);
    const groesse = new Float32Array(anzahl);

    this.netz.knoten.forEach((k, i) => {
      punkte.set([k.x, k.y, k.z], i * 3);
      keim[i] = k.k;
      // Die Groesse ist in Orb-Einheiten angegeben, nicht in Pixeln: So
      // bleibt ein Knoten bei jeder Orb-Groesse gleich gross im Verhaeltnis
      // zum Gehirn.
      groesse[i] = k.g / 78;
    });

    const geometrie = new THREE.BufferGeometry();
    geometrie.setAttribute("position", new THREE.BufferAttribute(punkte, 3));
    geometrie.setAttribute("aKeim", new THREE.BufferAttribute(keim, 1));
    geometrie.setAttribute("aGroesse", new THREE.BufferAttribute(groesse, 1));

    return new THREE.Points(
      geometrie,
      new THREE.ShaderMaterial({
        uniforms: this.uKnoten,
        vertexShader: KNOTEN_VERTEX,
        fragmentShader: KNOTEN_FRAGMENT,
        transparent: true,
        depthWrite: false,
        depthTest: false,
        blending: THREE.AdditiveBlending,
        premultipliedAlpha: true,
      })
    );
  }

  // --- Oeffentliche Schnittstelle (identisch zur EnergyOrb) ----------------

  public setBaseScale(scale: number): void {
    this.basisSkala = scale;
    this.group.scale.setScalar(scale);
    this.groundGroup.scale.setScalar(scale);
  }

  public setVoiceLevel(level: number): void {
    if (!Number.isFinite(level)) return;
    this.stimme = Math.max(0, Math.min(1, level));
  }

  public setFloatHeight(y: number): void {
    this.schwebe = y;
  }

  public setPointer(x: number, y: number, active: boolean): void {
    if (!active) {
      this.zeigerZiel.set(0, 0);
      return;
    }
    this.zeigerZiel.set(
      Math.max(-1.4, Math.min(1.4, x)),
      Math.max(-1.4, Math.min(1.4, y))
    );
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

  /**
   * Vorhanden, damit die Schnittstelle vollstaendig ist.
   *
   * Das Gehirn hat nur eine Gestalt – die Stilvarianten der EnergyOrb
   * betreffen deren Kern und Bahnen und haben hier keine Entsprechung.
   */
  public setVisualStyle(style: OrbVisualStyle): void {
    void style;
  }

  public flash(strength = 1.0): void {
    this.blitz = Math.max(this.blitz, Math.max(0, Math.min(1.5, strength)));
  }

  public setProgress(progress: number | null, indeterminate = false): void {
    this.fortschritt = progress;
    this.unbestimmt = indeterminate;
    this.bogen.visible = progress !== null;
  }

  public get scaleFactor(): number {
    return this.basisSkala;
  }

  /**
   * Uebernimmt die weich ueberblendeten Zustandswerte aus `states.ts`.
   *
   * Hier stehen nur die *Zahlen*. Die Farben werden in `update` nachgezogen,
   * weil sie zwischen den Zustandsbildern interpoliert werden muessen –
   * sonst spraenge das Gehirn beim Zustandswechsel die Farbe um.
   */
  public applyAppearance(a: StateAppearance): void {
    const feuer = a.ringIntensity * (0.55 + 0.85 * a.particleIntensity) * (this.professor ? 1.35 : 1.0);

    this.uKoerper.uFluss.value = 0.6 + 0.9 * a.smokeTurbulence * a.energyFlow;
    this.uKoerper.uPuls.value = a.pulseAmount * (0.6 + 0.8 * a.smokePulse) + 0.18;
    this.uKoerper.uNaht.value = 0.45 + 1.25 * a.coreGlow + 0.5 * a.smokeWarning;
    this.uKoerper.uHelligkeit.value =
      this.grundHelligkeit * (0.55 + 0.55 * a.lightIntensity) * (this.professor ? 1.12 : 1.0);
    this.uKoerper.uWach.value = this.zustand === "offline" || this.zustand === "sleep" ? 0.28 : 1.0;

    this.uBahn.uFeuer.value = feuer;
    this.uBahn.uGrund.value = 0.20 + 0.26 * a.ringIntensity;
    this.uKnoten.uFeuer.value = feuer;
    this.uKnoten.uHelligkeit.value = 0.7 + 0.7 * a.lightIntensity;

    this.uAura.uStaerke.value = 0.20 + 0.42 * a.auraScale * a.particleIntensity;
    this.uBoden.uStaerke.value = 0.16 + 0.30 * a.lightIntensity;
    this.uBogen.uStaerke.value = 0.9 + 0.5 * a.coreGlow;
  }

  /**
   * Ein Bild weiterrechnen.
   *
   * Wichtig: Die absolute Laufzeit `elapsed` wird bewusst NICHT mit dem
   * Zustandstempo multipliziert. Nach einer Stunde Laufzeit wuerde schon
   * eine kleine Tempoaenderung die Wellen sichtbar vorspringen lassen. Das
   * Gehirn fuehrt deshalb – wie die EnergyOrb – seine eigene Zeit.
   */
  public update(elapsed: number, delta: number, a: StateAppearance): void {
    const schritt = Math.min(0.1, Math.max(0, delta));

    // Gefuehl und Reiz klingen von selbst ab.
    if (this.gefuehlRest > 0) {
      this.gefuehlRest = Math.max(0, this.gefuehlRest - schritt);
      if (this.gefuehlRest === 0) this.gefuehl = null;
    }
    this.reizRest = Math.max(0, this.reizRest - schritt * 1.6);
    this.blitz = Math.max(0, this.blitz - schritt * 2.2);

    const gefuehlTempo =
      this.gefuehl === "joyful" || this.gefuehl === "surprised"
        ? 1.35
        : this.gefuehl === "relaxed" || this.gefuehl === "thoughtful"
          ? 0.78
          : 1.0;

    const tempo =
      this.grundTempo *
      a.speed *
      (0.72 + 0.42 * a.ringSpeed) *
      gefuehlTempo *
      (1.0 + this.reizRest * 0.55);
    this.eigenzeit += schritt * Math.max(0.05, tempo);

    // --- Farben nachziehen ---------------------------------------------
    const bild = ZUSTANDSBILD[this.zustand] ?? IDLE_BILD;
    const zug = 1 - Math.exp(-schritt * 4.2);
    this.farbTief.lerp(this.hilfsfarbe.setHex(bild.tief), zug);
    this.farbFluid.lerp(this.hilfsfarbe.setHex(bild.fluid), zug);
    this.farbLicht.lerp(this.hilfsfarbe.setHex(bild.licht), zug);
    this.farbNetz.lerp(this.hilfsfarbe.setHex(bild.netz), zug);
    this.farbSignal.lerp(this.hilfsfarbe.setHex(bild.signal), zug);

    (this.uAura.uFarbe.value as THREE.Color).copy(this.farbFluid);
    (this.uBoden.uFarbe.value as THREE.Color).copy(this.farbFluid);
    (this.uBogen.uFarbe.value as THREE.Color).copy(this.farbLicht);

    // --- Uniforms setzen -------------------------------------------------
    const stimme = this.stimme;
    this.uKoerper.uZeit.value = this.eigenzeit;
    this.uKoerper.uTempo.value = tempo;
    this.uKoerper.uStimme.value = stimme;
    this.uKoerper.uBlitz.value = this.blitz;
    this.uAura.uZeit.value = this.eigenzeit;
    this.uBahn.uZeit.value = this.eigenzeit;
    this.uKnoten.uZeit.value = this.eigenzeit;
    this.uBogen.uZeit.value = this.eigenzeit;

    // Sprechen laesst das Netz mitfeuern – die Antwort entsteht sichtbar
    // auf der denkenden Haelfte, nicht nur in der Fluessigkeit.
    const feuerBasis = this.uBahn.uFeuer.value as number;
    this.uKnoten.uFeuer.value = feuerBasis * (1.0 + stimme * 0.8 + this.blitz * 0.6);

    // Punktgroesse in echten Pixeln: Bildhoehe geteilt durch die sichtbare
    // Welthoehe. Nur so bleiben die Knoten auf jedem Bildschirm und bei
    // jeder Orb-Groesse gleich fein.
    const sichtFaktor =
      (window.innerHeight * this.pixelRatio) / (2 * Math.tan((45 * Math.PI) / 360));
    this.uKnoten.uPixel.value = sichtFaktor * this.basisSkala;

    if (this.fortschritt !== null) {
      this.uBogen.uFortschritt.value = Math.max(0, Math.min(1, this.fortschritt));
      this.uBogen.uUnbestimmt.value = this.unbestimmt ? 1 : 0;
    }

    // --- Neigung zur Maus -------------------------------------------------
    const folgen = 1 - Math.exp(-schritt * 6.0);
    this.zeiger.lerp(this.zeigerZiel, folgen);
    this.group.rotation.y = this.zeiger.x * 0.26;
    this.group.rotation.x = -this.zeiger.y * 0.18;
    // Das Netz sitzt eine Spur vor dem Koerper. Bei der Neigung entsteht
    // dadurch echte Parallaxe – das Gehirn bekommt Tiefe, obwohl es aus
    // flachen Ebenen besteht.
    this.netzGruppe.position.z = 0.045 + 0.012 * Math.sin(this.eigenzeit * 0.8);

    // --- Bodenschein ------------------------------------------------------
    this.groundGroup.position.y = -0.92 * this.basisSkala;
    const hoehe = Math.max(-0.4, Math.min(0.6, this.schwebe * 6.0));
    this.uBoden.uStaerke.value =
      (0.16 + 0.30 * a.lightIntensity) * (1.0 - hoehe * 0.35);

    void elapsed;
  }

  /**
   * Leistungsstufe. 0 = niedrig, 1 = mittel, 2 = hoch.
   *
   * Zuerst faellt die Aura, dann duennt das Netz aus. Der Koerper bleibt
   * immer vollstaendig – ohne ihn waere es kein Gehirn mehr.
   */
  public setQuality(level: number): void {
    const stufe = Math.max(0, Math.min(2, Math.round(level)));
    if (stufe === this.qualitaet) return;
    this.qualitaet = stufe;

    this.aura.visible = stufe > 0;
    const anteil = stufe === 0 ? 0.55 : stufe === 1 ? 0.8 : 1.0;
    const bahnPunkte = Math.max(2, Math.floor(this.netz.bahnen.length * anteil) * 2);
    this.bahnen.geometry.setDrawRange(0, bahnPunkte);
    this.knoten.geometry.setDrawRange(
      0,
      Math.max(4, Math.floor(this.netz.knoten.length * (stufe === 0 ? 0.7 : 1.0)))
    );
  }

  /** Gibt alle GPU-Ressourcen frei. */
  public dispose(): void {
    const aufraeumen = (objekt: THREE.Mesh | THREE.Points | THREE.LineSegments): void => {
      objekt.geometry.dispose();
      const material = objekt.material;
      if (Array.isArray(material)) {
        material.forEach((m) => m.dispose());
      } else {
        material.dispose();
      }
    };
    aufraeumen(this.koerper);
    aufraeumen(this.aura);
    aufraeumen(this.boden);
    aufraeumen(this.bogen);
    aufraeumen(this.bahnen);
    aufraeumen(this.knoten);
    this.group.clear();
    this.groundGroup.clear();
  }
}
