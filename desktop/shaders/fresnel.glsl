// =============================================================================
// fresnel.glsl – Shader für die Hülle des Orb
// =============================================================================
// Umgekehrter Fresnel: dicht und leuchtend dort, wo die Hülle dem Betrachter
// zugewandt ist, und weich ausblendend zum Rand hin. Genau andersherum als
// der übliche Fresnel-Rand, und zwar mit Absicht: Ein heller Saum am Rand
// zeichnet einen Kreis – den Umriss einer Kugel. Der Orb soll aber kein Ball
// mit Kante sein, sondern ein dampfender Nebel in Kugelform. Also fällt die
// Hülle zum Rand hin ins Nichts ab; sichtbar bleibt ein weicher, dichter
// Kern, und der Umkreis verschwindet.
//
// Uniforms werden von desktop/renderer/effects.ts gesetzt.
// =============================================================================

#ifdef VERTEX_STAGE

varying vec3 vNormal;
varying vec3 vViewPosition;
varying vec3 vWorldPosition;

void main() {
  vNormal = normalize(normalMatrix * normal);
  vec4 viewPosition = modelViewMatrix * vec4(position, 1.0);
  vViewPosition = -viewPosition.xyz;
  vWorldPosition = (modelMatrix * vec4(position, 1.0)).xyz;
  gl_Position = projectionMatrix * viewPosition;
}

#endif

#ifdef FRAGMENT_STAGE

uniform vec3 uColor;
uniform vec3 uGlowColor;
uniform float uTime;
uniform float uIntensity;
uniform float uPower;
uniform float uOpacity;

varying vec3 vNormal;
varying vec3 vViewPosition;
varying vec3 vWorldPosition;

void main() {
  vec3 normal = normalize(vNormal);
  vec3 viewDirection = normalize(vViewPosition);

  // „Zugewandtheit“: 1 in der Mitte (Blick trifft die Fläche frontal), 0 am
  // Rand (streifender Blick). Das ist der Kehrwert des klassischen Fresnel.
  float facing = clamp(dot(normal, viewDirection), 0.0, 1.0);

  // Weicher Verlauf statt harter Kante. Ein zusätzliches smoothstep drückt
  // die äußersten Ränder ganz auf null, damit dort wirklich kein Umriss
  // stehen bleibt.
  float density = pow(facing, uPower);
  density *= smoothstep(0.0, 0.35, facing);

  // Langsame Schwebung, damit die Hülle niemals völlig statisch wirkt.
  float pulse = 0.85 + 0.15 * sin(uTime * 1.3 + vWorldPosition.y * 2.0);

  // Der Kern schimmert in der Glühfarbe, nach außen geht er in die
  // Grundfarbe über – nicht umgekehrt, sonst zeichnete die Glühfarbe doch
  // wieder einen Rand.
  vec3 color = mix(uColor, uGlowColor, density);
  float alpha = density * uIntensity * pulse * uOpacity;

  gl_FragColor = vec4(color * uIntensity * pulse, clamp(alpha, 0.0, 1.0));
}

#endif
