// =============================================================================
// particles.glsl – Shader für die Partikel-Aura
// =============================================================================
// Die Partikel umkreisen den Orb auf leicht unterschiedlichen Bahnen und
// pulsieren dabei in Helligkeit und Größe. Sie werden additiv gemischt und
// besitzen keine harten Kanten, sondern einen weichen radialen Verlauf.
// =============================================================================

#ifdef VERTEX_STAGE

attribute float aSeed;
attribute float aRadius;
attribute float aSpeed;

uniform float uTime;
uniform float uSize;
uniform float uSpread;
uniform float uPixelRatio;

varying float vAlpha;

void main() {
  float angle = aSeed * 6.2831853 + uTime * aSpeed;
  float tilt = aSeed * 3.1415926;

  // Bahn um den Orb, leicht geneigt und mit langsamer vertikaler Schwebung.
  vec3 orbit = vec3(
    cos(angle) * aRadius,
    sin(angle * 0.7 + tilt) * aRadius * 0.55 + sin(uTime * 0.6 + aSeed * 10.0) * 0.08,
    sin(angle) * aRadius
  ) * uSpread;

  vec4 viewPosition = modelViewMatrix * vec4(position + orbit, 1.0);

  // Helligkeit pulsiert leicht, damit die Aura lebendig wirkt.
  vAlpha = 0.35 + 0.65 * (0.5 + 0.5 * sin(uTime * 2.0 + aSeed * 12.0));

  gl_PointSize = uSize * uPixelRatio * (1.0 / max(0.001, -viewPosition.z)) * (0.6 + 0.4 * vAlpha);
  gl_Position = projectionMatrix * viewPosition;
}

#endif

#ifdef FRAGMENT_STAGE

uniform vec3 uColor;
uniform float uIntensity;

varying float vAlpha;

void main() {
  // Weicher, runder Partikel ohne sichtbare Kante.
  vec2 offset = gl_PointCoord - vec2(0.5);
  float distance = length(offset);
  if (distance > 0.5) {
    discard;
  }

  float falloff = 1.0 - smoothstep(0.0, 0.5, distance);
  falloff = pow(falloff, 2.0);

  gl_FragColor = vec4(uColor * uIntensity, falloff * vAlpha);
}

#endif
