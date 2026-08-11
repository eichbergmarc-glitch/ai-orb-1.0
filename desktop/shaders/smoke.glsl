// =============================================================================
// smoke.glsl – volumetrischer Nebel im Inneren des Orb (Phase 14)
// =============================================================================
// Der Orb soll nicht wie eine bemalte Kugel aussehen, sondern wie ein Gefäß,
// in dem sich etwas bewegt. Dafür genügt keine Oberflächentextur – man sieht
// ihr an, dass sie auf der Haut klebt.
//
// Deshalb wird hier tatsächlich durch das Volumen marschiert: Für jeden
// Bildpunkt wird der Strahl von der Kamera durch die Kugel verfolgt und
// dabei in mehreren Schritten Dichte aufgesammelt. Was man sieht, ist die
// Summe dessen, was hinter der Oberfläche liegt – daher der räumliche
// Eindruck und die weichen Verläufe.
//
// Drei Kunstgriffe machen den Unterschied zwischen "Rauschmuster" und
// "Nebel":
//
//   1. Mehrfachrauschen (fbm): Grobe Schwaden mit feiner Struktur darin.
//      Ein einzelnes Rauschen sieht immer nach Fernsehschnee aus.
//
//   2. Verzerrung des Raums (domain warping): Bevor das Rauschen gelesen
//      wird, wird der Ort selbst mit Rauschen verschoben. Daraus entstehen
//      die langsamen Wirbel und fließenden Strukturen – gerade Kanten und
//      Kacheln verschwinden dabei von selbst.
//
//   3. Randabfall: Zum Rand der Kugel hin nimmt die Dichte ab, sodass der
//      Nebel nicht an der Hülle abgeschnitten wirkt.
//
// Die Zahl der Schritte ist eine Uniform. Damit lässt sich die Qualität zur
// Laufzeit senken, wenn die Bildrate einbricht, ohne den Shader zu tauschen.
// =============================================================================

#ifdef VERTEX_STAGE

varying vec3 vLocalPosition;
varying vec3 vLocalCamera;

//: Die umgekehrte Modellmatrix – von aussen gesetzt.
//:
//: Hier stand `inverse(modelMatrix)`. Das gibt es erst ab GLSL ES 3.00,
//: three.js übersetzt eigene Shader aber als ES 1.00 – dieser Shader wurde
//: also nie übersetzt und der Nebel nie gezeichnet. Was man für Nebel
//: hielt, war die leuchtende Hülle.
uniform mat4 uInvModel;

void main() {
  vLocalPosition = position;

  // Die Kameraposition im Koordinatensystem des Objekts. Damit lässt sich
  // im Fragment-Shader ohne weitere Matrizen durch das Volumen marschieren,
  // und der Nebel dreht sich korrekt mit, wenn der Orb sich bewegt.
  vLocalCamera = (uInvModel * vec4(cameraPosition, 1.0)).xyz;

  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}

#endif

#ifdef FRAGMENT_STAGE

precision highp float;

uniform float uTime;
uniform vec3 uColorInner;
uniform vec3 uColorOuter;
uniform float uIntensity;

// Wie stark sich der Nebel bewegt. Ruhezustand nahe 0.3, Denken nahe 1.6.
uniform float uTurbulence;

// Wie dicht der Nebel ist.
uniform float uDensity;

// Pulsieren beim Sprechen. 0 bedeutet aus.
uniform float uPulse;

// Anzahl der Schritte durch das Volumen. Weniger heißt schneller.
uniform float uSteps;

// Warnschimmer bei einem Fehler. 0 bedeutet aus.
uniform float uWarning;

varying vec3 vLocalPosition;
varying vec3 vLocalCamera;

// --- Rauschen ----------------------------------------------------------------

// Wertrauschen ohne Textur. Die Konstanten sind gebräuchliche Primzahlbrüche;
// sie sorgen dafür, dass sich das Muster nicht früh wiederholt.
float hash(vec3 p) {
  p = fract(p * 0.3183099 + vec3(0.71, 0.113, 0.419));
  p *= 17.0;
  return fract(p.x * p.y * p.z * (p.x + p.y + p.z));
}

float noise(vec3 x) {
  vec3 i = floor(x);
  vec3 f = fract(x);

  // Glättung nach Perlin: An den Zellgrenzen ist die Ableitung null, sonst
  // sähe man das Gitter als Rautenmuster.
  f = f * f * (3.0 - 2.0 * f);

  return mix(
    mix(mix(hash(i + vec3(0, 0, 0)), hash(i + vec3(1, 0, 0)), f.x),
        mix(hash(i + vec3(0, 1, 0)), hash(i + vec3(1, 1, 0)), f.x), f.y),
    mix(mix(hash(i + vec3(0, 0, 1)), hash(i + vec3(1, 0, 1)), f.x),
        mix(hash(i + vec3(0, 1, 1)), hash(i + vec3(1, 1, 1)), f.x), f.y),
    f.z);
}

// Mehrfachrauschen: vier Lagen mit doppelter Frequenz und halber Stärke.
// Vier ist der Kompromiss – bei drei fehlt die Feinstruktur, bei fünf
// kostet es spürbar, ohne dass man es auf einem Symbol von sechzig
// Bildpunkten sehen könnte.
float fbm(vec3 p) {
  float value = 0.0;
  float amplitude = 0.5;

  for (int i = 0; i < 4; i++) {
    value += amplitude * noise(p);
    p *= 2.02;          // knapp über 2, damit sich die Lagen nicht ausrichten
    amplitude *= 0.5;
  }

  return value;
}

// --- Dichte an einem Punkt ------------------------------------------------------

float densityAt(vec3 p) {
  // Zuegiger als zuvor (0.11), damit sich der Nebel sichtbar veraendert -
  // aber langsam genug, dass es ruhig bleibt.
  float t = uTime * 0.17;

  // Verzerrung des Raums: Der Ort wird mit Rauschen verschoben, bevor die
  // Dichte gelesen wird. Das erzeugt die Wirbel.
  vec3 warp = vec3(
    fbm(p * 1.6 + vec3(0.0, t, 0.0)),
    fbm(p * 1.6 + vec3(5.2, t * 0.8, 1.3)),
    fbm(p * 1.6 + vec3(1.7, t * 1.2, 9.1))
  );

  // Kraeftigere Verzerrung: daraus entstehen die sichtbaren Schwaden.
  vec3 warped = p + (warp - 0.5) * uTurbulence * 1.9;

  // Feinere Koernung (2.3 -> 3.1) und eine zweite, langsamere Lage:
  // zusammen ergibt das Nebel mit Tiefe statt einer glatten Wolke.
  float density = fbm(warped * 3.1 + vec3(0.0, -t * 1.4, t * 0.6));
  density = mix(density, fbm(warped * 1.4 + vec3(t * 0.5, 0.0, -t)), 0.35);

  // Zum Rand hin ausdünnen, damit der Nebel nicht an der Hülle abbricht.
  float radius = length(p);
  // Der Nebel FUELLT die Kugel und verblasst erst kurz vor der Schale.
  // Vorher begann das Ausblenden schon bei Radius 0.25 - der Nebel war
  // lange vor dem Rand verschwunden, und was man sah, war ein weicher
  // Fleck ohne Form. Jetzt entsteht die runde Silhouette aus dem Nebel
  // selbst, ganz ohne gezeichneten Umriss.
  density *= smoothstep(1.0, 0.82, radius);

  // Mehr Kontrast, damit Schwaden sichtbar werden statt gleichmaessigem
  // Dunst.
  density = pow(clamp(density, 0.0, 1.0), 1.7);

  // In der Mitte verdichten – dort sitzt der leuchtende Kern.
  density += smoothstep(0.42, 0.0, radius) * 0.20;

  // Beim Sprechen atmet die Dichte im Takt.
  density *= 1.0 + sin(uTime * 6.0) * 0.12 * uPulse;

  return max(0.0, density * uDensity);
}

// --- Strahlverfolgung -------------------------------------------------------------

// Schnittpunkte eines Strahls mit der Einheitskugel. x ist der Eintritt,
// y der Austritt. Bleibt y unter x, trifft der Strahl nicht.
vec2 sphereIntersect(vec3 origin, vec3 direction) {
  float b = dot(origin, direction);
  float c = dot(origin, origin) - 1.0;
  float h = b * b - c;

  if (h < 0.0) {
    return vec2(1.0, -1.0);
  }

  h = sqrt(h);
  return vec2(-b - h, -b + h);
}

void main() {
  vec3 rayOrigin = vLocalCamera;
  vec3 rayDirection = normalize(vLocalPosition - vLocalCamera);

  vec2 hit = sphereIntersect(rayOrigin, rayDirection);
  if (hit.y < hit.x) {
    discard;
  }

  // Vor der Kamera beginnen, nicht dahinter.
  float near = max(hit.x, 0.0);
  float far = hit.y;

  int steps = int(clamp(uSteps, 8.0, 48.0));
  float stepSize = (far - near) / float(steps);

  vec3 accumulated = vec3(0.0);
  float transmittance = 1.0;

  // Streuung von vorne nach hinten aufsammeln. Sobald kaum noch Licht
  // durchkommt, wird abgebrochen – die hinteren Schritte wären ohnehin
  // unsichtbar und kosten nur Rechenzeit.
  for (int i = 0; i < 48; i++) {
    if (i >= steps || transmittance < 0.02) {
      break;
    }

    float distance = near + (float(i) + 0.5) * stepSize;
    vec3 samplePoint = rayOrigin + rayDirection * distance;

    float density = densityAt(samplePoint);
    if (density <= 0.001) {
      continue;
    }

    // Farbe nach Tiefe: innen hell, außen kühler. Daraus entstehen die
    // mehreren Tiefenebenen, die der Nebel haben soll.
    float depth = clamp(length(samplePoint), 0.0, 1.0);
    vec3 tint = mix(uColorInner, uColorOuter, depth);

    // Warnschimmer: Bei einem Fehler wird ein warmer Ton eingemischt,
    // langsam pulsierend – auffällig genug, um bemerkt zu werden, ruhig
    // genug, um nicht zu hetzen.
    tint = mix(tint, vec3(1.0, 0.45, 0.35), uWarning * (0.5 + 0.5 * sin(uTime * 2.2)));

    float absorbed = density * stepSize * 3.2;
    accumulated += tint * absorbed * transmittance;
    transmittance *= 1.0 - clamp(absorbed, 0.0, 1.0);
  }

  float alpha = clamp(1.0 - transmittance, 0.0, 1.0);
  if (alpha < 0.004) {
    discard;
  }

  gl_FragColor = vec4(accumulated * uIntensity, alpha);
}

#endif
