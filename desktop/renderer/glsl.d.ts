/**
 * Typdeklaration für importierte GLSL-Dateien.
 *
 * Die Shader werden beim Bauen über esbuild als Text eingebunden
 * (`--loader:.glsl=text`), damit es nur eine einzige Quelle für den
 * Shader-Code gibt: die Dateien unter `desktop/shaders/`.
 */
declare module "*.glsl" {
  const source: string;
  export default source;
}
