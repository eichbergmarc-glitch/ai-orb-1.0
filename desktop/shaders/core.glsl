// =============================================================================
// core.glsl – Shader für den Kern des Orb
// =============================================================================
// Der Kern besitzt eine innere Struktur, die sich langsam bewegt, und einen
// Tiefeneffekt durch simulierte Brechung. Zusammen mit dem emissiven
// Material und dem Bloom-Effekt entsteht der Eindruck von Volumen.
// =============================================================================

#ifdef VERTEX_STAGE

varying vec3 vNormal;
varying vec3 vPosition;
varying vec3 vViewPosition;

uniform float uTime;
uniform float uDeform;

void main() {
  vNormal = normalize(normalMatrix * normal);
  vPosition = position;

  // Sehr leichte Verformung: der Kern "atmet".
  float wave =
    sin(position.x * 3.0 + uTime * 0.9) *
    cos(position.y * 3.0 + uTime * 0.7) *
    sin(position.z * 3.0 + uTime * 0.5);
  vec3 displaced = position + normal * wave * uDeform;

  vec4 viewPosition = modelViewMatrix * vec4(displaced, 1.0);
  vViewPosition = -viewPosition.xyz;
  gl_Position = projectionMatrix * viewPosition;
}

#endif

#ifdef FRAGMENT_STAGE

uniform vec3 uColorInner;
uniform vec3 uColorOuter;
uniform float uTime;
uniform float uIntensity;

varying vec3 vNormal;
varying vec3 vPosition;
varying vec3 vViewPosition;

// Einfaches, wiederholbares Rauschen ohne Textur.
float hash(vec3 p) {
  p = fract(p * 0.3183099 + vec3(0.71, 0.113, 0.419));
  p *= 17.0;
  return fract(p.x * p.y * p.z * (p.x + p.y + p.z));
}

float noise(vec3 x) {
  vec3 i = floor(x);
  vec3 f = fract(x);
  f = f * f * (3.0 - 2.0 * f);
  return mix(
    mix(mix(hash(i + vec3(0, 0, 0)), hash(i + vec3(1, 0, 0)), f.x),
        mix(hash(i + vec3(0, 1, 0)), hash(i + vec3(1, 1, 0)), f.x), f.y),
    mix(mix(hash(i + vec3(0, 0, 1)), hash(i + vec3(1, 0, 1)), f.x),
        mix(hash(i + vec3(0, 1, 1)), hash(i + vec3(1, 1, 1)), f.x), f.y),
    f.z);
}

void main() {
  vec3 normal = normalize(vNormal);
  vec3 viewDirection = normalize(vViewPosition);

  float facing = clamp(dot(normal, viewDirection), 0.0, 1.0);

  // Innere Strömung: erzeugt Tiefe, ohne dass eine Textur nötig ist.
  float flow = noise(vPosition * 2.5 + vec3(0.0, uTime * 0.25, uTime * 0.15));
  flow = smoothstep(0.35, 0.85, flow);

  // Simulierte Brechung: Ränder wirken dichter als die Mitte.
  float refraction = pow(1.0 - facing, 1.6);

  vec3 color = mix(uColorOuter, uColorInner, facing);
  color += uColorInner * flow * 0.45;
  color += uColorOuter * refraction * 0.6;

  gl_FragColor = vec4(color * uIntensity, 1.0);
}

#endif
