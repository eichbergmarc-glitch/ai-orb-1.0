/**
 * copy-assets.js
 *
 * Kopiert die statischen Bestandteile der Oberfläche (HTML, CSS, Icons) in
 * das Build-Verzeichnis. Bewusst plattformunabhängig in Node geschrieben,
 * damit derselbe Befehl unter Windows, Linux und macOS funktioniert.
 */

"use strict";

const fs = require("fs");
const path = require("path");

const projectRoot = path.resolve(__dirname, "..");
const outputDir = path.join(projectRoot, "desktop", "electron", "dist", "renderer");

/**
 * Kopiert eine einzelne Datei und legt das Zielverzeichnis bei Bedarf an.
 *
 * @param {string} source Quellpfad, relativ zum Projekt-Root.
 * @param {string} destination Zielpfad, relativ zum Ausgabeverzeichnis.
 */
function copyFile(source, destination) {
  const from = path.join(projectRoot, source);
  const to = path.join(outputDir, destination);

  if (!fs.existsSync(from)) {
    console.warn(`[copy-assets] Übersprungen (nicht gefunden): ${source}`);
    return;
  }

  fs.mkdirSync(path.dirname(to), { recursive: true });
  fs.copyFileSync(from, to);
  console.log(`[copy-assets] ${source} -> ${path.relative(projectRoot, to)}`);
}

/**
 * Kopiert ein ganzes Verzeichnis rekursiv.
 *
 * @param {string} source Quellverzeichnis, relativ zum Projekt-Root.
 * @param {string} destination Zielverzeichnis, relativ zum Ausgabeverzeichnis.
 */
function copyDirectory(source, destination) {
  const from = path.join(projectRoot, source);
  if (!fs.existsSync(from)) {
    console.warn(`[copy-assets] Übersprungen (nicht gefunden): ${source}`);
    return;
  }
  const to = path.join(outputDir, destination);
  fs.mkdirSync(to, { recursive: true });
  fs.cpSync(from, to, { recursive: true });
  console.log(`[copy-assets] ${source}/ -> ${path.relative(projectRoot, to)}/`);
}

fs.mkdirSync(outputDir, { recursive: true });

copyFile("desktop/renderer/index.html", "index.html");
copyFile("desktop/renderer/preview-bridge.js", "preview-bridge.js");
copyFile("desktop/styles/orb.css", "styles/orb.css");
copyFile("desktop/styles/themes.css", "styles/themes.css");
copyDirectory("desktop/assets/icons", "assets/icons");
copyDirectory("desktop/assets/orb", "assets/orb");

console.log("[copy-assets] Fertig.");
