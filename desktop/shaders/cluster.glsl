// =============================================================================
// cluster.glsl – der Kern des Orb als lebender Kristallhaufen
// =============================================================================
// Vorbild ist eine Animation, die der Benutzer mitgebracht hat: ein dichter
// Haufen glänzender Knollen und Kristalle, der sich dreht, dabei atmet und
// seine Farbe wandern lässt, während aus den Lücken ein Licht dringt.
//
// Nachgebaut ist das nicht mit Geometrie, sondern mit einer Abstandsfunktion,
// durch die für jeden Bildpunkt marschiert wird (Sphere Tracing). Der Grund
// ist nicht Eleganz, sondern Notwendigkeit: ein Dutzend Körper, die
// ineinanderfliessen und dabei ihre Grösse ändern, wären als Dreiecksnetz in
// jedem Bild neu zu bauen. Als Abstandsfunktion sind sie eine Formel, die
// sich mit der Zeit ändert – und das Verschmelzen fällt gratis ab.
//
// Vier Dinge machen den Unterschied zwischen „ein paar Kugeln" und dem
// Vorbild:
//
//   1. Weiches Minimum (smin) statt Minimum. Damit gehen benachbarte Körper
//      ineinander über, statt sich zu durchdringen – daraus entsteht das
//      Organische, das Zusammengewachsene.
//
//   2. Die Mischung aus Knollen und Facetten. Jeder dritte Körper ist ein
//      kantiger Kristall. Erst der Gegensatz macht beides erkennbar; lauter
//      Kugeln sähen aus wie Schaum, lauter Würfel wie ein Haufen Kisten.
//
//   3. Das Licht aus den Lücken. Auf dem Weg durch den Haufen wird
//      aufgesammelt, wie nah der Strahl an einer Oberfläche vorbeischrammt.
//      Was knapp vorbeigeht, leuchtet – so scheint der Kern zwischen den
//      Körpern hindurch, ohne dass eine Lichtquelle nötig wäre.
//
//   4. Die Stimme als Welle. Der Sprechpegel erreicht jeden Körper mit
//      eigener Verzögerung, sodass bei jeder Silbe ein Zucken durch das
//      Gebilde läuft, statt dass sich alles gleichzeitig aufbläht.
//
// ## Zur Sparsamkeit
//
// Dieser Shader ist bewusst knapp gehalten, und zwar entlang einer harten
// Grenze. Unter Windows übersetzt three.js über ANGLE nach Direct3D, und
// dessen Übersetzer hat eine Obergrenze an Befehlen. Die Abstandsfunktion
// läuft pro Bildpunkt einmal je Marschschritt UND viermal für die Normale.
// Wer hier Körper hinzufügt, Trigonometrie einbaut oder die Schrittzahl
// erhöht, riskiert, dass der Shader gar nicht erst übersetzt wird – und ein
// Bild, das nicht gezeichnet wird, ist kein langsames Bild, sondern gar
// keines. Für diesen Fall gibt es `orb.cluster: false` in der config.yaml.
// =============================================================================

#ifdef VERTEX_STAGE

varying vec3 vLocalPosition;
varying vec3 vLocalCamera;

//: Die umgekehrte Modellmatrix – von aussen gesetzt, nicht hier gerechnet.
//:
//: `inverse()` gibt es erst ab GLSL ES 3.00. three.js übersetzt eigene
//: Shader aber als ES 1.00, solange nichts anderes verlangt wird – der
//: Aufruf liess den Shader also gar nicht erst übersetzen, und was nicht
//: übersetzt wird, wird auch nicht gezeichnet. Auf der Rechenseite ist es
//: ohnehin die bessere Wahl: Eine Matrix je Bild umzukehren kostet nichts,
//: sie in jedem Bildpunkt umzukehren dagegen sehr viel.
uniform mat4 uInvModel;

void main() {
  vLocalPosition = position;

  // Die Kamera im Koordinatensystem des Objekts. Damit lässt sich unten
  // ohne weitere Matrizen marschieren, und der Haufen dreht sich richtig
  // mit, wenn der Orb bewegt wird.
  vLocalCamera = (uInvModel * vec4(cameraPosition, 1.0)).xyz;

  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}

#endif

#ifdef FRAGMENT_STAGE

precision highp float;

uniform float uTime;
//: Die beiden Farben des Zustands – bläulich im Ruhezustand, rot beim
//: Arbeiten. Zwischen ihnen wandert die Farbe hin und her.
uniform vec3 uColorInner;
uniform vec3 uColorOuter;
uniform float uIntensity;
//: Wie laut gerade gesprochen wird (0 bis 1).
uniform float uPulse;
//: Wie unruhig sich das Ganze bewegt.
uniform float uTurbulence;
//: Marschschritte. Weniger = gröber, aber schneller.
uniform int uSteps;

varying vec3 vLocalPosition;
varying vec3 vLocalCamera;

//: So viele Körper bilden den Haufen. Siehe „Zur Sparsamkeit" oben.
const int KNOLLEN = 12;

//: Richtung und Grundgrösse jedes Körpers – von aussen gesetzt.
//:
//: Zwei Gründe, warum das eine Uniform ist und keine Konstante im Shader:
//:
//: Erstens gibt es Array-Konstruktoren (`vec4[12](...)`) erst ab GLSL ES
//: 3.00; in ES 1.00, das three.js hier benutzt, ist die Schreibweise ein
//: Übersetzungsfehler. Zweitens standen davor Sinus und Kosinus für jeden
//: Körper im Shader – bei zwölf Körpern und rund dreissig Auswertungen je
//: Bildpunkt einige hundert trigonometrische Funktionen pro Pixel, für
//: Werte, die sich nie ändern.
//:
//: xyz ist die Richtung, w der Grundradius. Die Richtungen liegen nach dem
//: goldenen Winkel auf der Kugel: Gleichmässige Winkelabstände ergäben
//: sichtbare Reihen und Pole, diese Verteilung hat keine bevorzugte
//: Richtung.
uniform vec4 uKoerper[KNOLLEN];

/** Weiches Minimum: lässt zwei Körper ineinander übergehen. */
float smin(float a, float b, float k) {
  float h = clamp(0.5 + 0.5 * (b - a) / k, 0.0, 1.0);
  return mix(b, a, h) - k * h * (1.0 - h);
}

/** Abstand zu einer Kugel. */
float sdSphere(vec3 p, float r) {
  return length(p) - r;
}

/** Abstand zu einem gerundeten Würfel. */
float sdRoundBox(vec3 p, float halb, float rundung) {
  vec3 q = abs(p) - vec3(halb);
  return length(max(q, 0.0)) + min(max(q.x, max(q.y, q.z)), 0.0) - rundung;
}

/** Der Abstand zum gesamten Haufen. */
float haufen(vec3 p) {
  float d = 1e9;
  float takt = uTime * (0.75 + 0.55 * uTurbulence);

  for (int i = 0; i < KNOLLEN; i++) {
    vec4 koerper = uKoerper[i];
    float fi = float(i);

    // Jeder Körper atmet in eigenem Takt. Der Versatz je Körper sorgt
    // dafür, dass nie alle gleichzeitig gross sind – sonst pulsierte der
    // ganze Haufen wie ein Herz, statt zu wimmeln.
    float w = 0.55 + 0.45 * sin(takt * 1.1 + fi * 1.6);

    // Die Stimme läuft als WELLE durch den Haufen. Das ist der Unterschied
    // zwischen „reagiert" und „lebt": Bläht sich alles gleichzeitig auf,
    // sieht es aus wie ein Blasebalg.
    float welle = max(0.0, sin(takt * 5.0 - fi * 0.95)) * uPulse;

    float abstand = (0.40 + 0.16 * w) * (1.0 + 0.16 * uPulse + 0.22 * welle);
    vec3 q = p - koerper.xyz * abstand;
    float r = koerper.w * (0.80 + 0.35 * w) * (1.0 + 0.14 * uPulse + 0.30 * welle);

    float dd = (mod(fi, 3.0) < 0.5)
      ? sdRoundBox(q, r * 0.80, r * 0.14)
      : sdSphere(q, r);
    d = smin(d, dd, 0.07);
  }

  // Der Kern in der Mitte hält den Haufen zusammen. Ohne ihn zerfiele er
  // beim Atmen in Einzelteile, sobald die Körper nach aussen wandern.
  float kern = length(p) - (0.28 + 0.05 * sin(takt * 2.0)) * (1.0 + 0.15 * uPulse);
  return smin(d, kern, 0.16);
}

/** Die Normale – über die Steigung der Abstandsfunktion.
 *
 *  Vier Auswertungen statt sechs: Die vier Ecken eines Tetraeders genügen,
 *  um die Steigung im Raum zu bestimmen. Das ist ein Drittel weniger
 *  Rechenaufwand an der teuersten Stelle des ganzen Shaders.
 */
vec3 normale(vec3 p) {
  vec2 k = vec2(1.0, -1.0) * 0.0035;
  return normalize(
      k.xyy * haufen(p + k.xyy)
    + k.yyx * haufen(p + k.yyx)
    + k.yxy * haufen(p + k.yxy)
    + k.xxx * haufen(p + k.xxx)
  );
}

void main() {
  vec3 ro = vLocalCamera;
  vec3 rd = normalize(vLocalPosition - vLocalCamera);

  float t = 0.0;
  float schein = 0.0;
  bool getroffen = false;
  vec3 p = ro;

  int schritte = clamp(uSteps, 20, 40);
  for (int i = 0; i < 40; i++) {
    if (i >= schritte) { break; }
    p = ro + rd * t;
    float d = haufen(p);

    // Was knapp an einer Oberfläche vorbeigeht, leuchtet. Daraus entsteht
    // das Licht aus den Lücken, ohne dass eine Lichtquelle nötig wäre.
    schein += exp(-abs(d) * 7.0) * 0.02;

    if (d < 0.005) { getroffen = true; break; }
    t += max(d * 0.85, 0.005);
    if (t > 4.5) { break; }
  }

  // Die Farbe wandert zwischen den beiden Zustandsfarben hin und her – das
  // ist der Farbwechsel aus der Vorlage, aber innerhalb dessen, was der
  // Zustand vorgibt: bläulich im Ruhezustand, rot beim Arbeiten. Beim
  // Sprechen läuft er schneller; ein Bild, das sich synchron zum Klang
  // ändert, ordnet das Auge derselben Ursache zu.
  float ph = 0.5 + 0.5 * sin(uTime * (0.35 + 0.5 * uPulse));
  vec3 basis = mix(uColorOuter, uColorInner, ph);

  if (!getroffen) {
    // Kein Körper getroffen: nur das Licht aus den Lücken, sonst nichts.
    float a = clamp(schein * 0.9, 0.0, 1.0);
    if (a < 0.01) { discard; }
    gl_FragColor = vec4(uColorInner * a * uIntensity, a);
    return;
  }

  vec3 n = normale(p);
  vec3 lampe = normalize(vec3(0.4, 0.7, 0.6));
  float diff = clamp(dot(n, lampe), 0.0, 1.0);

  // Fresnel: Zum Rand hin wirkt die Oberfläche dichter und heller. Das ist
  // es, was Glanz von Anstrich unterscheidet.
  float fres = pow(1.0 - clamp(dot(n, -rd), 0.0, 1.0), 3.0);

  vec3 halb = normalize(lampe - rd);
  float spek = pow(clamp(dot(n, halb), 0.0, 1.0), 48.0);

  vec3 farbe =
      basis * (0.05 + 0.50 * diff)
    + basis * fres * 0.30
    + uColorInner * spek * 0.35
    + uColorInner * clamp(schein, 0.0, 1.0) * (0.22 + 0.30 * uPulse);

  gl_FragColor = vec4(farbe * uIntensity, 1.0);
}

#endif
