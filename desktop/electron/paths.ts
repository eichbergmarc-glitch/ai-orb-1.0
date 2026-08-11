/**
 * paths.ts – zentrale Pfadauflösung für den Electron-Teil.
 *
 * Dies ist das Gegenstück zu `backend/utils/paths.py`. Beide Seiten müssen
 * zum selben Ergebnis kommen, sonst startet Electron einen Kern, der seine
 * Konfiguration woanders sucht als die Oberfläche – und dann verhält sich
 * ein installiertes AI-Orb anders als eines aus dem Quellordner, ohne dass
 * man sähe, warum.
 *
 * ## Warum es diese Datei überhaupt gibt
 *
 * Vorher stand in `main.ts` eine einzige Zeile:
 *
 *     const PROJECT_ROOT = path.resolve(__dirname, "..", "..", "..", "..");
 *
 * Im Quellordner stimmt das. In der installierten Fassung liegt `main.js`
 * aber in `app.asar` – einem Archiv. Vier Ebenen darüber landet man dann
 * nicht im Programmordner, sondern *im Archiv selbst*. Von dort aus gibt es
 * keine `config.yaml`, keinen `runtime`-Ordner und kein Verzeichnis, in dem
 * sich ein Prozess starten ließe. Die Folge war nicht ein Fehler, sondern
 * drei: Der Orb nahm seine Vorgabewerte statt der Konfiguration (und war
 * damit zu groß), der Python-Kern kam nie hoch (also keine Antworten), und
 * ohne Kern gab es auch kein Weckwort.
 *
 * Genau deshalb liegt die Pfadauflösung jetzt an einer Stelle, mit Namen
 * und Begründung, statt als Nebenbemerkung in einer Konstante.
 *
 * ## Die beiden Orte
 *
 * * **Programmordner** – wird nur gelesen. Enthält Code, die mitgelieferte
 *   `config.yaml`, die Python-Runtime, Plugins und Skills.
 * * **Benutzerordner** – `%APPDATA%\AI-Orb`. Enthält alles, was beim
 *   Benutzen entsteht: eigene Konfiguration, Gedächtnis, Protokolle,
 *   Fensterposition.
 *
 * Im Quellbetrieb fallen beide zusammen. Das ist beim Entwickeln praktisch
 * und für einen USB-Stick brauchbar.
 */

import { app } from "electron";
import * as fs from "fs";
import * as os from "os";
import * as path from "path";

/** Name des Anwendungsordners unterhalb von %APPDATA%. */
export const APP_FOLDER_NAME = "AI-Orb";

/** Liegt diese Datei im Programmordner, bleibt alles beisammen. */
const DEVELOPMENT_MARKER = ".entwicklung";

/** Diese Datei legt der Installer an. Ihr Fehlen heißt: Quellbetrieb. */
const INSTALL_MARKER = ".installiert";

/** Erzwingt den tragbaren Betrieb. */
const PORTABLE_ENVIRONMENT_VARIABLE = "AI_ORB_PORTABLE";

/** Überschreibt den Benutzerordner vollständig. */
const DATA_DIRECTORY_ENVIRONMENT_VARIABLE = "AI_ORB_DATA_DIR";

/**
 * Der Programmordner.
 *
 * In der installierten Fassung ist das `<Installation>\resources\app`.
 * Dorthin legt `package.json` per `extraResources` den Backend-Code, die
 * Runtime, die Konfiguration, Plugins und Skills – bewusst *neben* das
 * Archiv `app.asar` und nicht hinein, denn aus einem Archiv lässt sich
 * keine `python.exe` starten.
 *
 * Im Quellbetrieb ist es der Projektordner.
 */
export function getAppRoot(): string {
  if (app.isPackaged) {
    return path.join(process.resourcesPath, "app");
  }
  // dist/electron/main.js -> desktop/electron/dist/electron -> vier hoch.
  return path.resolve(__dirname, "..", "..", "..", "..");
}

/**
 * Ob AI-Orb aus dem Quellordner läuft.
 *
 * Die Reihenfolge der Prüfungen ist bewusst gewählt: Eine ausdrücklich
 * gesetzte Umgebungsvariable schlägt alles, dann ein Entwicklungskennzeichen,
 * und erst zuletzt wird aus dem Fehlen des Installationskennzeichens
 * geschlossen. Die letzte Prüfung ist die unsicherste, deshalb kommt sie
 * zum Schluss.
 */
export function isPortable(): boolean {
  const forced = (process.env[PORTABLE_ENVIRONMENT_VARIABLE] ?? "").trim().toLowerCase();
  if (["1", "true", "ja"].includes(forced)) {
    return true;
  }

  const root = getAppRoot();
  if (fs.existsSync(path.join(root, DEVELOPMENT_MARKER))) {
    return true;
  }

  return !fs.existsSync(path.join(root, INSTALL_MARKER));
}

/** Legt einen Ordner an, ohne bei einem Fehlschlag zu stürzen. */
function ensureDirectory(directory: string): string {
  try {
    fs.mkdirSync(directory, { recursive: true });
  } catch {
    // Ein nicht anlegbarer Ordner ist kein Grund, den Orb nicht zu zeigen.
    // Die Stelle, die tatsächlich schreiben will, meldet sich früh genug.
  }
  return directory;
}

/**
 * Der Ordner für Benutzerdaten.
 *
 * Unter Windows `%APPDATA%\AI-Orb`, sonst `~/.config/ai-orb`. Im tragbaren
 * Betrieb der Programmordner selbst.
 */
export function getUserDir(): string {
  const override = (process.env[DATA_DIRECTORY_ENVIRONMENT_VARIABLE] ?? "").trim();
  if (override) {
    return ensureDirectory(path.resolve(override));
  }

  if (isPortable()) {
    return getAppRoot();
  }

  if (process.platform === "win32") {
    const base = process.env.APPDATA ?? "";
    return ensureDirectory(
      base ? path.join(base, APP_FOLDER_NAME) : path.join(os.homedir(), APP_FOLDER_NAME)
    );
  }

  const base = process.env.XDG_CONFIG_HOME ?? path.join(os.homedir(), ".config");
  return ensureDirectory(path.join(base, "ai-orb"));
}

/**
 * Der Pfad zur wirksamen `config.yaml`.
 *
 * Erst die Fassung des Benutzers, dann die mitgelieferte. So überlebt eine
 * angepasste Konfiguration jedes Update, und wer nie etwas geändert hat,
 * bekommt beim Update die neuen Vorgabewerte.
 */
export function getConfigPath(): string {
  const userConfig = path.join(getUserDir(), "config.yaml");
  if (fs.existsSync(userConfig)) {
    return userConfig;
  }
  return path.join(getAppRoot(), "config.yaml");
}

/** Die mitgelieferte Standardkonfiguration. */
export function getBundledConfigPath(): string {
  return path.join(getAppRoot(), "config.yaml");
}

/**
 * Stellt sicher, dass eine Konfiguration des Benutzers vorliegt.
 *
 * Beim ersten Start wird die mitgelieferte Fassung kopiert. Erst dadurch
 * hat der Benutzer eine Datei, die er bearbeiten *kann* – und die ein
 * Update nicht mehr anfasst.
 *
 * Electron macht das und nicht erst der Python-Kern, weil Electron zuerst
 * läuft und die Konfiguration bereits braucht, um das Fenster zu bauen.
 *
 * @returns Der Pfad und ob die Datei neu angelegt wurde.
 */
export function ensureUserConfig(): { path: string; created: boolean } {
  if (isPortable()) {
    return { path: getBundledConfigPath(), created: false };
  }

  const target = path.join(getUserDir(), "config.yaml");
  if (fs.existsSync(target)) {
    return { path: target, created: false };
  }

  const source = getBundledConfigPath();
  if (!fs.existsSync(source)) {
    return { path: target, created: false };
  }

  try {
    fs.copyFileSync(source, target);
    return { path: target, created: true };
  } catch {
    // Konnte nicht kopiert werden – dann eben die mitgelieferte lesen.
    return { path: source, created: false };
  }
}

/** Der Ordner für Anwendungsdaten (Fensterposition, Gedächtnis, …). */
export function getDataDir(): string {
  return ensureDirectory(path.join(getUserDir(), "data"));
}

/** Der Ordner für Protokolldateien. */
export function getLogsDir(): string {
  return ensureDirectory(path.join(getUserDir(), "logs"));
}

/** Wo alles liegt – für die Fehlersuche. */
export function describePaths(): Record<string, string> {
  return {
    modus: isPortable() ? "tragbar" : "installiert",
    programm: getAppRoot(),
    benutzerdaten: getUserDir(),
    konfiguration: getConfigPath(),
    daten: getDataDir(),
    protokolle: getLogsDir(),
  };
}
