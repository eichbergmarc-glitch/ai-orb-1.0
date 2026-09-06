/**
 * main.ts – Der Hauptprozess der AI-Orb Desktop-Anwendung.
 *
 * Erzeugt das transparente, rahmenlose Orb-Fenster, liest die zentrale
 * `config.yaml`, verbindet die Smart Desktop Engine mit der
 * Fensterverwaltung und stellt dem Renderer über `preload.ts` eine
 * abgesicherte Schnittstelle bereit.
 *
 * Der Hauptprozess führt selbst keine KI-Logik aus – diese liegt
 * vollständig im Python-Backend.
 *
 * In der installierten Fassung ist dieser Prozess zugleich der Launcher
 * (Phase 45): Er startet den Python-Kern selbst, zeigt währenddessen einen
 * Ladebildschirm und beendet alles wieder, wenn der Benutzer den Orb
 * schließt. Der Benutzer klickt auf einen Startmenü-Eintrag – mehr ist
 * nicht zu tun.
 */

import {
  app,
  BrowserWindow,
  globalShortcut,
  ipcMain,
  Menu,
  screen,
  shell,
  Tray,
  nativeImage,
} from "electron";
import * as fs from "fs";
import * as http from "http";
import * as path from "path";

import { BackendProcess } from "./backend_process";
import { ConsentBridge } from "./consent";
import { DesktopManager } from "./desktop_manager";
import { FlipperCenter, readFlipperStatus } from "./flipper_center";
import {
  LectureVisualWindow,
  type LectureVisualBounds,
  type LectureVisualPayload,
} from "./lecture_visual";
import { MonitorManager } from "./monitor_manager";
import {
  describePaths,
  ensureUserConfig,
  getAppRoot,
  getConfigPath,
  getDataDir,
  getLogsDir,
} from "./paths";
import { SplashScreen, SPLASH_STEPS } from "./splash";
import { WindowManager } from "./window_manager";

/**
 * Der Programmordner.
 *
 * Aufgelöst in `paths.ts`, weil die Antwort im Quellordner eine andere ist
 * als in der installierten Fassung – und weil der Python-Kern dieselbe
 * Antwort braucht.
 */
const PROJECT_ROOT = getAppRoot();

/** Verzeichnis der gebauten Renderer-Dateien. */
const RENDERER_DIR = path.resolve(__dirname, "..", "renderer");
const flipperCenter = new FlipperCenter(RENDERER_DIR);

/** Die geladene Konfiguration. */
let config: Record<string, any> = {};

let orbWindow: BrowserWindow | null = null;
let tray: Tray | null = null;
const lectureVisual = new LectureVisualWindow((visible, bounds) => {
  setLectureVisualMode(visible, bounds);
});

/** Der Python-Kern, den dieser Prozess startet und überwacht. */
let backend: BackendProcess | null = null;

/** Der Ladebildschirm während des Starts. */
let splash: SplashScreen | null = null;

/**
 * Stellt die Zustimmungsfragen des Kerns dar.
 *
 * Ohne diese Brücke fragt der Kern ins Leere: Er wartet, die Frist läuft
 * ab, und Schweigen gilt – zu Recht – als Nein. Das traf ausgerechnet die
 * Erlaubnis für das Mikrofon, ohne die es kein Weckwort gibt.
 */
let consentBridge: ConsentBridge | null = null;

/** Kennung, die der Kern seinen Fortschrittszeilen voranstellt. */
const PROGRESS_PREFIX = "@@ORB@@";
let windowManager: WindowManager | null = null;
let monitorManager: MonitorManager | null = null;
let desktopManager: DesktopManager | null = null;
let mouseTimer: NodeJS.Timeout | null = null;
let gazeTimer: NodeJS.Timeout | null = null;

/**
 * Liest einen verschachtelten Konfigurationswert.
 *
 * @param dottedKey Punktgetrennter Pfad, z. B. `window.width`.
 * @param fallback Rückgabewert, falls der Pfad fehlt.
 */
function readConfig<T>(dottedKey: string, fallback: T): T {
  let current: any = config;
  for (const part of dottedKey.split(".")) {
    if (current === null || typeof current !== "object" || !(part in current)) {
      return fallback;
    }
    current = current[part];
  }
  return (current ?? fallback) as T;
}

/**
 * Liest `config.yaml`.
 *
 * Bewusst mit einem eigenen, minimalen Parser umgesetzt: Dadurch benötigt
 * der Hauptprozess keine zusätzliche Abhängigkeit, und die Anwendung
 * startet auch dann, wenn `npm install` unvollständig war.
 *
 * Unterstützt werden die in `config.yaml` verwendeten Konstrukte:
 * verschachtelte Zuordnungen, Listen, Zeichenketten, Zahlen, Wahrheitswerte
 * und mehrzeilige Blöcke (`>-`).
 */
function loadConfig(): Record<string, any> {
  // Beim ersten Start eine eigene Fassung für den Benutzer anlegen. Ohne
  // das gäbe es in der installierten Anwendung keine Datei, die er
  // bearbeiten kann – seine Änderungen liefen ins Leere.
  const { created } = ensureUserConfig();
  const configPath = getConfigPath();

  if (created) {
    console.log(`[AI-Orb] Konfiguration angelegt: ${configPath}`);
  }

  let text = "";
  try {
    text = fs.readFileSync(configPath, "utf-8");
  } catch (error) {
    // Das ist kein Randfall, den man leise übergehen darf: Ohne
    // Konfiguration nimmt der Orb überall seine Vorgabewerte, und der
    // Benutzer sieht ein Programm, das seine Einstellungen ignoriert,
    // ohne zu erfahren warum. Deshalb hier alle Pfade ins Protokoll.
    console.error("[AI-Orb] config.yaml konnte nicht gelesen werden:", error);
    console.error("[AI-Orb] Gesucht wurde:", configPath);
    console.error("[AI-Orb] Pfade:", JSON.stringify(describePaths(), null, 2));
    return {};
  }

  const root: Record<string, any> = {};
  const stack: { indent: number; value: any }[] = [{ indent: -1, value: root }];

  const parseScalar = (raw: string): any => {
    const value = raw.trim();
    if (value === "" || value === "~" || value === "null") return null;
    if (value === "true") return true;
    if (value === "false") return false;
    if (/^-?\d+$/.test(value)) return parseInt(value, 10);
    if (/^-?\d*\.\d+$/.test(value)) return parseFloat(value);
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      return value.slice(1, -1);
    }
    return value;
  };

  const lines = text.split(/\r?\n/);

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    if (line.trim() === "" || line.trim().startsWith("#")) {
      continue;
    }

    const indent = line.length - line.trimStart().length;
    const content = line.trim();

    while (stack.length > 1 && indent <= stack[stack.length - 1].indent) {
      stack.pop();
    }
    const parent = stack[stack.length - 1].value;

    // --- Listeneintrag ---------------------------------------------------
    if (content.startsWith("- ")) {
      if (Array.isArray(parent)) {
        parent.push(parseScalar(content.slice(2)));
      }
      continue;
    }

    const separator = content.indexOf(":");
    if (separator < 0) {
      continue;
    }

    const key = content.slice(0, separator).trim();
    const rest = content.slice(separator + 1).trim();

    // --- Mehrzeiliger Block (>- oder |) -----------------------------------
    if (rest === ">-" || rest === ">" || rest === "|" || rest === "|-") {
      const parts: string[] = [];
      let cursor = index + 1;
      while (cursor < lines.length) {
        const blockLine = lines[cursor];
        const blockIndent = blockLine.length - blockLine.trimStart().length;
        if (blockLine.trim() === "") {
          cursor += 1;
          continue;
        }
        if (blockIndent <= indent) {
          break;
        }
        parts.push(blockLine.trim());
        cursor += 1;
      }
      parent[key] = parts.join(" ");
      index = cursor - 1;
      continue;
    }

    // --- Verschachtelte Zuordnung oder Liste --------------------------------
    if (rest === "") {
      // Vorausschauen: Folgt ein Listeneintrag oder eine Zuordnung?
      let lookahead = index + 1;
      while (lookahead < lines.length && lines[lookahead].trim() === "") {
        lookahead += 1;
      }
      const nextLine = lines[lookahead] ?? "";
      const nextIndent = nextLine.length - nextLine.trimStart().length;
      const isList = nextLine.trim().startsWith("- ") && nextIndent > indent;

      parent[key] = isList ? [] : {};
      stack.push({ indent, value: parent[key] });
      continue;
    }

    parent[key] = parseScalar(rest);
  }

  return root;
}

/** Erzeugt das Orb-Fenster. */
function createOrbWindow(): BrowserWindow {
  // Die Rückfallwerte entsprechen absichtlich der mitgelieferten
  // config.yaml. Ein Rückfallwert, der von der Vorgabe abweicht, macht aus
  // einer fehlenden Konfiguration ein *anderes* Verhalten statt des
  // gewohnten – und man sucht den Fehler dann an der falschen Stelle.
  const width = readConfig("window.width", 520);
  const height = readConfig("window.height", 520);

  windowManager = new WindowManager(getDataDir());
  const position = windowManager.getInitialPosition(
    width,
    height,
    readConfig("window.start_position", "remembered")
  );

  const window = new BrowserWindow({
    width,
    height,
    x: position.x,
    y: position.y,

    // --- Erscheinung: kein normales Fenster ------------------------------
    frame: false,
    transparent: readConfig("window.transparent", true),
    hasShadow: readConfig("window.has_shadow", false),
    alwaysOnTop: readConfig("window.always_on_top", true),
    skipTaskbar: readConfig("window.skip_taskbar", true),
    resizable: readConfig("window.resizable", false),
    movable: readConfig("window.movable", true),
    minimizable: false,
    maximizable: false,
    fullscreenable: false,
    titleBarStyle: "hidden",
    backgroundColor: "#00000000",
    show: false,

    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
      backgroundThrottling: false,
      devTools: readConfig("app.environment", "development") === "development",
    },
  });

  // Über allen Fenstern schweben, auch über Vollbildanwendungen anderer
  // Programme – aber ohne den Fokus zu stehlen.
  window.setAlwaysOnTop(readConfig("window.always_on_top", true), "screen-saver");
  window.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });

  void window.loadFile(path.join(RENDERER_DIR, "index.html"));

  window.once("ready-to-show", () => {
    window.show();
    // Der Orb soll den Fokus niemals an sich reißen.
    window.setFocusable(false);
  });

  // Externe Links niemals im Orb-Fenster öffnen.
  window.webContents.setWindowOpenHandler(({ url }) => {
    void shell.openExternal(url);
    return { action: "deny" };
  });

  // Meldungen der Oberfläche in die Konsole des Hauptprozesses spiegeln.
  // Ohne das bliebe ein Fehler beim Aufbau des Orb unsichtbar – das Fenster
  // ist transparent, ein Absturz im Renderer wäre also schlicht "nichts".
  window.webContents.on("console-message", (_event, level, message, line, sourceId) => {
    const labels = ["debug", "info", "warn", "error"];
    const label = labels[level] ?? "info";
    if (label === "error" || label === "warn") {
      const source = sourceId ? ` (${sourceId}:${line})` : "";
      console.error(`[orb:${label}] ${message}${source}`);
    }
  });

  // Schlägt das Laden der Oberfläche fehl, wird das ausdrücklich gemeldet.
  window.webContents.on("did-fail-load", (_event, errorCode, errorDescription) => {
    console.error(
      `[AI-Orb] Die Oberflaeche konnte nicht geladen werden: ${errorDescription} (${errorCode}).`
    );
    console.error("[AI-Orb] Wurde 'npm run build' ausgefuehrt?");
  });

  window.webContents.on("render-process-gone", (_event, details) => {
    console.error(`[AI-Orb] Der Renderer wurde beendet: ${details.reason}.`);
  });

  // Automatische Platzierungen werden absichtlich nicht bei jedem
  // `moved` gespeichert. Sonst wuerde eine voruebergehende Ausweichposition
  // (oder eine fehlerhafte Ecke) beim naechsten Start zur Benutzerposition.
  // Manuelle Positionen werden nach dem Ziehen in
  // `window:commit-position` sowie ueber "Position merken" gespeichert.

  window.on("closed", () => {
    orbWindow = null;
  });

  return window;
}

/** Baut das Kontextmenü des Orb auf. */
function buildContextMenu(): Menu {
  const environment = readConfig("app.environment", "development");

  const template: Electron.MenuItemConstructorOptions[] = [
    { label: `AI-Orb ${readConfig("app.version", "0.1.0")}`, enabled: false },
    { type: "separator" },
    {
      label: "Flipper Control Center",
      click: () => flipperCenter.show(),
    },
    {
      label: "Chat öffnen",
      click: () => sendToRenderer("orb.chat.requested", { action: "open", source: "tray" }),
    },
    { type: "separator" },
    {
      label: "Position merken",
      click: () => {
        if (orbWindow === null) return;
        const [x, y] = orbWindow.getPosition();
        windowManager?.savePosition(x, y);
        sendToRenderer("orb.position.saved", { x, y });
      },
    },
    {
      label: "Automatische Platzierung",
      type: "checkbox",
      checked: readConfig("smart_desktop.enabled", true),
      click: (item) => {
        desktopManager?.configure({ enabled: item.checked });
        if (item.checked) {
          desktopManager?.start();
        } else {
          desktopManager?.stop();
        }
      },
    },
    {
      // Der Autostart wird hier geschaltet und nicht beim Installieren.
      //
      // Ein Kästchen auf der letzten Seite des Installationsprogramms sieht
      // man genau einmal, und wer es später bereut, sucht vergeblich –
      // ausgerechnet die Einstellung, die man am ehesten zurücknehmen will,
      // wäre die am schwersten auffindbare. Hier steht sie dort, wo man
      // ohnehin nachsieht, und lässt sich jederzeit wieder abwählen.
      label: "Mit Windows starten",
      type: "checkbox",
      checked: app.getLoginItemSettings().openAtLogin,
      click: (item) => {
        app.setLoginItemSettings({ openAtLogin: item.checked, args: [] });
      },
    },
    { type: "separator" },
    {
      label: "Konfiguration öffnen",
      click: () => {
        void shell.openPath(getConfigPath());
      },
    },
    {
      label: "Protokolle öffnen",
      click: () => {
        void shell.openPath(getLogsDir());
      },
    },
    {
      label: "Diagnose anzeigen",
      click: () => sendToRenderer("ui.diagnostics.toggle", {}),
    },
    ...(environment === "development"
      ? ([
          { type: "separator" },
          {
            label: "Entwicklerwerkzeuge",
            click: () => orbWindow?.webContents.openDevTools({ mode: "detach" }),
          },
        ] as Electron.MenuItemConstructorOptions[])
      : []),
    { type: "separator" },
    { label: "AI-Orb beenden", click: () => app.quit() },
  ];

  return Menu.buildFromTemplate(template);
}

/** Legt das Symbol im Infobereich an. */
function createTray(): void {
  const iconPath = path.join(RENDERER_DIR, "assets", "icons", "icon.png");
  let image = nativeImage.createFromPath(iconPath);
  if (image.isEmpty()) {
    // Ohne Symbol kein Absturz – der Infobereich wird dann übersprungen.
    console.warn("[AI-Orb] Symbol nicht gefunden:", iconPath);
    return;
  }
  image = image.resize({ width: 16, height: 16 });

  tray = new Tray(image);
  tray.setToolTip("AI-Orb");
  tray.setContextMenu(buildContextMenu());
  tray.on("double-click", () => orbWindow?.show());
}

/** Sendet ein Ereignis an die Oberfläche. */
function sendToRenderer(event: string, payload: Record<string, unknown>): void {
  if (orbWindow !== null && !orbWindow.isDestroyed()) {
    orbWindow.webContents.send("backend:event", { event, payload });
  }
}

/** Richtet die Smart Desktop Engine ein. */
function setupSmartDesktop(window: BrowserWindow): void {
  monitorManager = new MonitorManager({
    onAdded: (monitor) => sendToRenderer("monitor.added", { id: monitor.id }),
    onRemoved: (id) => {
      sendToRenderer("monitor.removed", { id });
      // Nach dem Abziehen eines Monitors könnte der Orb außerhalb liegen.
      ensureVisible(window);
    },
    onChanged: () => ensureVisible(window),
  });

  desktopManager = new DesktopManager(
    window,
    monitorManager,
    {
      enabled: readConfig("smart_desktop.enabled", true),
      avoidMouse: readConfig("smart_desktop.avoid_mouse", true),
      avoidActiveWindow: readConfig("smart_desktop.avoid_active_window", true),
      learnBehavior: readConfig("smart_desktop.learn_behavior", true),
      movementSpeed: readConfig("smart_desktop.movement_speed", "medium"),
      monitorSupport: readConfig("smart_desktop.monitor_support", true),
      fullscreenSleep: readConfig("smart_desktop.fullscreen_sleep", true),
      avoidCorners: readConfig("smart_desktop.avoid_corners", true),
      stayNearWork: readConfig("smart_desktop.stay_near_work", true),
      workReach: readConfig("smart_desktop.work_reach", 900),
      switchThreshold: readConfig("smart_desktop.switch_threshold", 0.08),
      evaluationInterval: readConfig("smart_desktop.evaluation_interval_ms", 1500),
      backendUrl:
        `http://${backendHost()}:` +
        `${readConfig("backend.port", 8756)}`,
    },
    {
      onPositionChosen: (candidate) => {
        const [windowWidth, windowHeight] = window.getSize();
        // PlacementEngine bewertet Fenster-Rechtecke und liefert deren
        // linke obere Ecke. moveOrbTo erwartet dagegen den sichtbaren
        // Orb-Mittelpunkt. Die bisher direkte Übergabe setzte einen
        // Kandidaten bei (48, 48) mit seinem Mittelpunkt in die Ecke.
        const centerX = candidate.x + windowWidth / 2;
        const centerY = candidate.y + windowHeight / 2;
        // Weiche Bewegung: Das Fenster wird schrittweise verschoben, nie
        // teleportiert.
        moveOrbTo(window, centerX, centerY);
        sendToRenderer("orb.position.chosen", {
          x: centerX,
          y: centerY,
          score: candidate.score,
        });
      },
      onStateRequest: (state) => sendToRenderer("orb.state.request", { state }),
      onVisibilityRequest: (visible) => {
        if (window.isDestroyed()) return;
        if (visible && !window.isVisible()) {
          window.showInactive();
        } else if (!visible && window.isVisible()) {
          window.hide();
        }
      },
    }
  );

  desktopManager.start();

  // Mausverfolgung: Electron liefert die Zeigerposition nur auf Abruf.
  mouseTimer = setInterval(() => desktopManager?.trackMouse(), 220);
}

/**
 * Der aktuelle Versatz des Orb gegenüber der Fenstermitte, in Pixeln.
 *
 * Das Fenster ist deutlich größer als der sichtbare Orb. Kleine
 * Ausweichbewegungen finden dadurch **innerhalb** des Fensters statt und
 * werden von der Grafikkarte gezeichnet – flüssig und ohne Ruckeln. Das
 * Fenster selbst wird nur versetzt, wenn das Ziel außerhalb davon liegt.
 */
let orbOffset = { x: 0, y: 0 };

/** Berechnet die Bildschirmposition der Orb-Mitte. */
function getOrbCenter(window: BrowserWindow): { x: number; y: number } {
  const [x, y] = window.getPosition();
  const [width, height] = window.getSize();
  return { x: x + width / 2 + orbOffset.x, y: y + height / 2 + orbOffset.y };
}

/** Sendet einen Zielversatz an die Oberfläche. */
function sendOrbOffset(
  window: BrowserWindow,
  x: number,
  y: number,
  immediate: boolean
): void {
  if (!window.isDestroyed()) {
    window.webContents.send("orb:offset", { x, y, immediate });
  }
}

/**
 * Bewegt den Orb weich an eine Bildschirmposition.
 *
 * Erfüllt die Vorgabe „Keine Sprünge. Keine Teleportation.": Die sichtbare
 * Bewegung ist immer eine Animation in der Oberfläche. Muss dabei das
 * Fenster umgesetzt werden, geschieht das in einem einzigen Schritt,
 * während der Versatz gegengerechnet wird – der Orb bleibt dadurch optisch
 * exakt stehen und läuft von dort aus weich weiter.
 *
 * @param window Das Orb-Fenster.
 * @param targetX Ziel der Orb-Mitte, waagerecht.
 * @param targetY Ziel der Orb-Mitte, senkrecht.
 */
function moveOrbTo(window: BrowserWindow, targetX: number, targetY: number): void {
  if (window.isDestroyed()) {
    return;
  }

  const [windowX, windowY] = window.getPosition();
  const [width, height] = window.getSize();

  // Wie weit darf sich der Orb von der Fenstermitte entfernen, ohne aus dem
  // Fenster zu laufen? Der Abstand berücksichtigt seine sichtbare Größe.
  const orbRadius = (Math.min(width, height) / 2) * readConfig("orb.scale", 0.5);
  const maximumOffset = Math.max(0, Math.min(width, height) / 2 - orbRadius - 12);

  const desiredX = targetX - (windowX + width / 2);
  const desiredY = targetY - (windowY + height / 2);

  if (Math.hypot(desiredX, desiredY) <= maximumOffset) {
    // Ziel liegt im Fenster: rein grafische Bewegung, nichts wird verschoben.
    orbOffset = { x: desiredX, y: desiredY };
    sendOrbOffset(window, orbOffset.x, orbOffset.y, false);
    return;
  }

  // Ziel liegt außerhalb: Fenster einmalig neu setzen und den bisherigen
  // Standort des Orb über den Versatz beibehalten, damit nichts springt.
  const currentCenter = getOrbCenter(window);
  const newWindowX = Math.round(targetX - width / 2);
  const newWindowY = Math.round(targetY - height / 2);

  window.setPosition(newWindowX, newWindowY);

  const compensatedX = currentCenter.x - (newWindowX + width / 2);
  const compensatedY = currentCenter.y - (newWindowY + height / 2);

  // Erst den alten Standort ohne Animation einnehmen …
  orbOffset = { x: compensatedX, y: compensatedY };
  sendOrbOffset(window, compensatedX, compensatedY, true);

  // … und von dort aus weich in die neue Fenstermitte laufen.
  setTimeout(() => {
    if (!window.isDestroyed()) {
      orbOffset = { x: 0, y: 0 };
      sendOrbOffset(window, 0, 0, false);
    }
  }, 40);
}

/**
 * Reserviert links unten neben der Lehrtafel einen festen Platz fuer den Orb.
 *
 * Das Orb-Fenster ist groesser als die sichtbare Kugel und transparent. Fuer
 * die Kollisionsrechnung ist daher allein der sichtbare Radius entscheidend.
 * Die Smart-Desktop-Automatik bleibt ausgesetzt, solange die Tafel offen ist;
 * sonst koennte die naechste Mausbewegung die Anordnung sofort aufheben.
 */
function setLectureVisualMode(
  visible: boolean,
  bounds?: LectureVisualBounds,
): void {
  desktopManager?.setSuspended("lecture-visual", visible);
  if (!visible || bounds === undefined || orbWindow === null || orbWindow.isDestroyed()) {
    return;
  }

  const display = screen.getDisplayMatching(bounds);
  const [width, height] = orbWindow.getSize();
  const orbRadius = (Math.min(width, height) / 2) * readConfig("orb.scale", 0.5);
  const workArea = display.workArea;
  const gap = 6;

  // Rechts liegt die Tafel. Der Orb sitzt mit seiner sichtbaren Aussenkante
  // links davon und mit seiner Unterkante knapp ueber dem Bildschirmrand.
  // Falls ein kleiner Monitor weniger Raum bietet, halten die Grenzen ihn
  // trotzdem vollstaendig im sichtbaren Arbeitsbereich.
  const targetX = Math.max(
    workArea.x + orbRadius,
    Math.min(bounds.x - orbRadius - gap, workArea.x + workArea.width - orbRadius),
  );
  const targetY = Math.max(
    workArea.y + orbRadius,
    workArea.y + workArea.height - orbRadius - 8,
  );

  moveOrbTo(orbWindow, targetX, targetY);
  orbWindow.showInactive();
}

/**
 * Setzt das Fenster so um, dass der Orb wieder in seiner Mitte sitzt.
 *
 * Wird nach dem Ziehen aufgerufen, damit dem Orb anschließend in alle
 * Richtungen gleich viel Bewegungsraum zur Verfügung steht. Sichtbar
 * bewegt sich dabei nichts.
 */
function normalizeWindow(window: BrowserWindow): void {
  if (window.isDestroyed() || (orbOffset.x === 0 && orbOffset.y === 0)) {
    return;
  }
  const center = getOrbCenter(window);
  const [width, height] = window.getSize();
  window.setPosition(Math.round(center.x - width / 2), Math.round(center.y - height / 2));
  orbOffset = { x: 0, y: 0 };
  sendOrbOffset(window, 0, 0, true);
}

/** Holt das Fenster zurück, falls es außerhalb aller Monitore liegt. */
function ensureVisible(window: BrowserWindow): void {
  if (window.isDestroyed() || monitorManager === null || windowManager === null) {
    return;
  }
  const center = getOrbCenter(window);
  const [width, height] = window.getSize();
  const orbRadius = (Math.min(width, height) / 2) * readConfig("orb.scale", 0.5);

  // Geprüft wird der sichtbare Orb, nicht das (viel größere) Fenster.
  if (
    monitorManager.isVisible(
      center.x - orbRadius,
      center.y - orbRadius,
      orbRadius * 2,
      orbRadius * 2
    )
  ) {
    return;
  }

  const fallback = windowManager.getDefaultPosition(width, height);
  moveOrbTo(window, fallback.x + width / 2, fallback.y + height / 2);
}

/**
 * Schickt dem Kern die Anweisung, die Sprachausgabe abzubrechen.
 *
 * Ein Fehler ist hier folgenlos: Der Kern läuft weiter, es wurde nur nicht
 * unterbrochen. Deshalb wird still protokolliert statt gestört.
 */
function requestVoiceInterrupt(): void {
  const host = backendHost();
  const port = readConfig<number>("backend.port", 8756);

  const request = http.request(
    { host, port, path: "/voice/interrupt", method: "POST", timeout: 2000 },
    (response) => response.resume()
  );
  request.on("error", (error) => {
    console.error("[AI-Orb] Unterbrechen fehlgeschlagen:", error.message);
  });
  request.on("timeout", () => request.destroy());
  request.end();
}

/**
 * Fängt die Unterbrechungs-Taste ab – aber nur, während der Orb spricht.
 *
 * Eine global registrierte Taste schluckt ihren Tastendruck überall, auch
 * in anderen Programmen. Genau deshalb wird sie hier nur für die Dauer der
 * Sprachausgabe registriert und unmittelbar danach wieder freigegeben:
 * Während der Orb redet, bricht Enter ihn ab; sobald er schweigt, gehört
 * Enter wieder dem Programm, in dem der Benutzer gerade arbeitet.
 *
 * @param active Ob der Orb gerade spricht.
 */
function setInterruptShortcut(active: boolean): void {
  const key = readConfig("voice.interrupt_key", "Enter");

  if (!key) {
    return;
  }

  if (active) {
    if (globalShortcut.isRegistered(key)) {
      return;
    }
    const ok = globalShortcut.register(key, () => {
      requestVoiceInterrupt();
      // Nach dem Abbruch sofort freigeben – der nächste Enter des
      // Benutzers soll wieder normal wirken.
      setInterruptShortcut(false);
    });
    if (!ok) {
      console.error(`[AI-Orb] Taste '${key}' liess sich nicht belegen.`);
    }
  } else {
    if (globalShortcut.isRegistered(key)) {
      globalShortcut.unregister(key);
    }
  }
}

/** Registriert alle IPC-Handler. */
function registerIpcHandlers(): void {
  ipcMain.handle("flipper:status", () => readFlipperStatus());
  ipcMain.handle("flipper:open-qflipper", () => flipperCenter.launchQFlipper());
  ipcMain.handle("flipper:choose-app", () => flipperCenter.chooseApp());

  // Bei jedem Abruf frisch von der Platte lesen.
  //
  // Sonst bekäme der Renderer nach einem Neuladen die beim Programmstart
  // eingelesene config – und die Animationswerte, die der Orb gerade
  // geändert hat, kämen nie an. `loadConfig` liest die Datei neu.
  ipcMain.handle("config:get", () => {
    config = loadConfig();
    return config;
  });

  ipcMain.on("voice:speaking", (_event, { speaking }: { speaking: boolean }) => {
    setInterruptShortcut(speaking);
  });

  ipcMain.on("lecture-visual:show", (_event, payload: LectureVisualPayload) => {
    void lectureVisual.show(payload, orbWindow);
  });

  ipcMain.handle("backend:url", () => {
    const host = backendHost();
    const port = readConfig("backend.port", 8756);
    return `http://${host}:${port}`;
  });

  ipcMain.on("window:move-by", (_event, { dx, dy }: { dx: number; dy: number }) => {
    if (orbWindow === null || orbWindow.isDestroyed()) return;
    // Während der Benutzer zieht, mischt sich die automatische Platzierung
    // nicht ein.
    desktopManager?.setSuspended("drag", true);
    const [x, y] = orbWindow.getPosition();
    orbWindow.setPosition(Math.round(x + dx), Math.round(y + dy));
  });

  ipcMain.on("window:commit-position", (_event, { manual }: { manual: boolean }) => {
    if (orbWindow === null || orbWindow.isDestroyed()) return;
    desktopManager?.setSuspended("drag", false);

    // Nach dem Ziehen sitzt der Orb wieder mittig im Fenster, damit ihm in
    // alle Richtungen gleich viel Bewegungsraum bleibt.
    normalizeWindow(orbWindow);

    const center = getOrbCenter(orbWindow);
    const [x, y] = orbWindow.getPosition();
    windowManager?.savePosition(x, y);

    const monitor = monitorManager?.forPoint(center.x, center.y);
    sendToRenderer("orb.position.committed", {
      x: Math.round(center.x),
      y: Math.round(center.y),
      manual,
      monitor: monitor?.index ?? 0,
      screen_width: monitor?.workArea.width ?? 1920,
      screen_height: monitor?.workArea.height ?? 1080,
    });
  });

  // Die Oberfläche meldet, wo der Orb im Fenster gerade tatsächlich steht.
  ipcMain.on("orb:offset-report", (_event, { x, y }: { x: number; y: number }) => {
    orbOffset = { x, y };
  });

  ipcMain.on("orb:menu-action", (_event, { action }: { action: string }) => {
    if (action === "files") {
      void shell.openPath(app.getPath("documents"));
    } else if (action === "settings") {
      void shell.openPath(getConfigPath());
    } else if (action === "chat") {
      sendToRenderer("orb.chat.requested", { action: "open", source: "menu" });
    } else if (action === "quit") {
      app.quit();
    } else if (action === "search") {
      sendToRenderer("orb.listen.toggle", { source: action });
    }
  });

  ipcMain.on("window:ignore-mouse", (_event, { ignore }: { ignore: boolean }) => {
    if (orbWindow === null || orbWindow.isDestroyed()) return;
    // `forward: true` sorgt dafür, dass der Renderer weiterhin
    // Mausbewegungen sieht und den Hover-Zustand erkennen kann.
    orbWindow.setIgnoreMouseEvents(ignore, { forward: true });
  });

  ipcMain.on(
    "window:interaction-lock",
    (_event, { active, reason }: { active: boolean; reason: string }) => {
      const allowed = new Set(["menu", "chat", "pointer"]);
      if (!allowed.has(reason)) return;
      desktopManager?.setSuspended(reason, active);
    }
  );

  ipcMain.on("window:chat-focus", (_event, { active }: { active: boolean }) => {
    if (orbWindow === null || orbWindow.isDestroyed()) return;
    // Der Orb ist im Normalbetrieb absichtlich nicht fokussierbar. Ein
    // Textfeld kann dann jedoch keine Tastatureingaben annehmen. Nur fuer
    // den sichtbaren Chat wird der Fokus freigegeben und aktiv angefordert;
    // beim Schliessen kehrt das schwebende, nicht stoerende Verhalten zurueck.
    orbWindow.setFocusable(active);
    if (active) {
      orbWindow.show();
      orbWindow.focus();
    }
  });

  ipcMain.on("orb:context-menu", () => {
    if (orbWindow === null || orbWindow.isDestroyed()) return;
    buildContextMenu().popup({ window: orbWindow });
  });

  ipcMain.on("orb:double-click", () => {
    const action = readConfig<string>("interaction.double_click_action", "open_settings");
    if (action === "open_settings") {
      void shell.openPath(getConfigPath());
    } else if (action === "toggle_listen") {
      sendToRenderer("orb.listen.toggle", {});
    }
  });
}

// --- Anwendungsstart ---------------------------------------------------------


// =============================================================================
// Start des Python-Kerns (Phasen 44, 45, 58)
// =============================================================================

/**
 * Startet den Python-Kern und zeigt dabei den Ladebildschirm.
 *
 * Der Kern meldet seinen Fortschritt zeilenweise auf der Standardausgabe.
 * Zeilen mit der Kennung `@@ORB@@` sind für uns bestimmt und tragen JSON;
 * alles andere ist gewöhnliches Protokoll und wandert in die Konsole.
 *
 * Schlägt der Start fehl, bleibt der Ladebildschirm mit der Begründung
 * stehen. Das ist Absicht: Ein Fenster, das sich wortlos schließt, lässt
 * den Benutzer ratlos zurück.
 *
 * @returns Ob der Kern bereit ist.
 */
async function startBackend(): Promise<boolean> {
  const host = backendHost();
  const port = readConfig<number>("backend.port", 8756);

  splash = new SplashScreen();
  splash.show();
  splash.begin("system");

  backend = new BackendProcess(PROJECT_ROOT, host, port);

  // Alles, was der Kern von sich gibt, zusätzlich in eine Datei.
  //
  // Stirbt er, bevor seine eigene Protokollierung steht, steht der Grund
  // nirgends sonst – und die Konsole ist beim nächsten Start weg.
  const startupLog = path.join(getLogsDir(), "kern-start.log");
  try {
    fs.writeFileSync(startupLog, `AI-Orb Kernstart ${new Date().toISOString()}\n`);
  } catch {
    // Kein Protokoll ist ärgerlich, aber kein Grund, nicht zu starten.
  }

  const started = backend.start((line, isError) => {
    try {
      fs.appendFileSync(startupLog, `${isError ? "! " : "  "}${line}\n`);
    } catch {
      // siehe oben
    }

    if (line.startsWith(PROGRESS_PREFIX)) {
      handleProgressLine(line.slice(PROGRESS_PREFIX.length));
      return;
    }
    if (isError) {
      console.error("[Kern]", line);
    } else {
      console.log("[Kern]", line);
    }
  });

  if (!started) {
    splash.fail(backend.error);
    return false;
  }

  const ready = await backend.waitUntilReady();
  if (!ready) {
    splash.fail(backend.error);
    return false;
  }

  // Erst jetzt zuhören: Vorher gibt es niemanden, den man fragen könnte.
  consentBridge = new ConsentBridge(host, port, () => orbWindow);
  consentBridge.start();

  // Alles, was der Kern nicht ausdrücklich gemeldet hat, gilt jetzt als
  // erledigt – sonst blieben Haken offen, obwohl der Orb längst läuft.
  for (const step of SPLASH_STEPS) {
    splash.complete(step.key, true);
  }
  splash.ready();

  return true;
}

/**
 * Wertet eine Fortschrittszeile des Kerns aus.
 *
 * Ein fehlerhaftes JSON wird stillschweigend übergangen: Eine kaputte
 * Meldung darf den Start nicht aufhalten.
 */
function handleProgressLine(json: string): void {
  let payload: Record<string, any>;
  try {
    payload = JSON.parse(json);
  } catch {
    return;
  }

  switch (payload.kind) {
    case "progress":
      splash?.complete(String(payload.step), payload.ok !== false);
      break;

    case "ready":
      splash?.ready();
      if (Array.isArray(payload.limitations) && payload.limitations.length > 0) {
        for (const limitation of payload.limitations) {
          console.warn("[Kern] Einschränkung:", String(limitation).split("\n")[0]);
        }
      }
      break;

    case "failed":
      splash?.fail(String(payload.message ?? "Der Start ist fehlgeschlagen."));
      break;

    case "recovery":
      // Ein Dienst ist ausgefallen und wurde neu gestartet. Für den
      // Benutzer ist das nur dann interessant, wenn es nicht geklappt hat.
      console.warn("[Kern] Dienstausfall:", JSON.stringify(payload.event));
      break;

    default:
      break;
  }
}

/**
 * Beendet den Kern geordnet.
 *
 * Wird beim Schließen des Orb aufgerufen. Ohne diesen Schritt liefe der
 * Python-Prozess weiter und hielte das Mikrofon belegt.
 */
function stopBackend(): void {
  // Zuerst aufhören zu fragen. Sonst öffnete sich womöglich noch ein
  // Fenster für einen Kern, den es nicht mehr gibt.
  consentBridge?.stop();
  consentBridge = null;

  backend?.stop();
  backend = null;
}

// Nur eine Instanz zulassen – zwei Orbs wären verwirrend.
if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", () => {
    orbWindow?.show();
  });

  // GPU-Beschleunigung ist für die Darstellung des Orb wesentlich.
  app.commandLine.appendSwitch("enable-gpu-rasterization");
  app.commandLine.appendSwitch("enable-zero-copy");

  void app.whenReady().then(async () => {
    config = loadConfig();

    if (!readConfig("window.gpu_acceleration", true)) {
      app.disableHardwareAcceleration();
    }

    registerIpcHandlers();

    // Erst der Kern, dann der Orb. Andersherum stünde ein Orb da, der auf
    // nichts antwortet – schlimmer als ein Ladebildschirm.
    const backendReady = await startBackend();
    if (!backendReady) {
      // Der Ladebildschirm zeigt die Begründung und bleibt stehen. Der
      // Benutzer schließt ihn selbst.
      return;
    }

    splash?.close();
    splash = null;

    orbWindow = createOrbWindow();
    setupSmartDesktop(orbWindow);
    // Globale Blickdaten nur senden, wenn der Zeiger sich wirklich bewegt.
    // Die Augen glaetten selbst; 20 Hz Eingabe wirkt deshalb fluessig, ohne
    // Haupt- und Rendererprozess mit dauernden IPC-Nachrichten zu belasten.
    let lastCursorX = Number.NaN;
    let lastCursorY = Number.NaN;
    gazeTimer = setInterval(() => {
      if (orbWindow === null || orbWindow.isDestroyed()) return;
      const cursor = screen.getCursorScreenPoint();
      if (cursor.x === lastCursorX && cursor.y === lastCursorY) return;
      lastCursorX = cursor.x;
      lastCursorY = cursor.y;
      const bounds = orbWindow.getBounds();
      orbWindow.webContents.send("pointer:global", {
        x: cursor.x - bounds.x,
        y: cursor.y - bounds.y,
      });
    }, 50);
    createTray();

    // Beim Start ist das Fenster außerhalb des Orb klickdurchlässig.
    orbWindow.setIgnoreMouseEvents(true, { forward: true });
    orbOffset = { x: 0, y: 0 };

    screen.on("display-metrics-changed", () => {
      if (orbWindow !== null) {
        ensureVisible(orbWindow);
      }
    });

    app.on("activate", () => {
      if (BrowserWindow.getAllWindows().length === 0) {
        orbWindow = createOrbWindow();
      }
    });
  });

  app.on("window-all-closed", () => {
    // Auf allen Plattformen beenden: Der Orb ist die gesamte Oberfläche.
    app.quit();
  });

  app.on("before-quit", () => {
    if (mouseTimer !== null) {
      clearInterval(mouseTimer);
      mouseTimer = null;
    }
    if (gazeTimer !== null) {
      clearInterval(gazeTimer);
      gazeTimer = null;
    }
    desktopManager?.stop();
    tray?.destroy();
    splash?.close();
    lectureVisual.close();
    flipperCenter.close();
    // Keine Taste zurücklassen, die AI-Orb nach dem Beenden noch abfinge.
    globalShortcut.unregisterAll();
    stopBackend();
  });
}

/**
 * Die Adresse, unter der DIESER Prozess den Kern erreicht.
 *
 * `backend.host` beantwortet eine andere Frage als die, die hier gestellt
 * wird. Es sagt, auf welchen Netzwerkkarten der Server LAUSCHT. "0.0.0.0"
 * heisst dort "auf allen" - als Ziel einer Verbindung ist es dagegen
 * keine Adresse, sondern die Abwesenheit einer Adresse. Wer sie einsetzt,
 * baut sich einen Fehler, der genau dann auftritt, wenn der Fernzugang
 * eingerichtet wurde: Der Orb auf dem Rechner selbst faende seinen
 * eigenen Kern nicht mehr.
 */
function backendHost(): string {
  const host = readConfig<string>("backend.host", "127.0.0.1");
  return host === "0.0.0.0" || host === "::" ? "127.0.0.1" : host;
}
