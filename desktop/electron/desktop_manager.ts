/**
 * desktop_manager.ts – Die Smart Desktop Engine.
 *
 * Beobachtet Maus, Monitore und Fenster, bewertet mit Hilfe der
 * {@link PlacementEngine} laufend mögliche Positionen und bewegt den Orb
 * langsam dorthin, wo er am wenigsten stört.
 *
 * Verhalten je Kontext:
 * - Editor aktiv → der Orb entfernt sich vom Editorbereich
 * - Browser aktiv → freie Ecke
 * - Video im Vollbild → der Orb blendet sich aus
 * - Spiel im Vollbild → der Orb schläft
 *
 * Bewegungen sind immer weich; es gibt keine Sprünge und keine hektischen
 * Richtungswechsel.
 */

import type { BrowserWindow } from "electron";
import * as http from "http";

import { MonitorManager, type MonitorInfo } from "./monitor_manager";
import {
  PlacementEngine,
  type Candidate,
  type DesktopState,
  type WindowInfo,
} from "./placement_engine";

/** Einstellungen der Smart Desktop Engine. */
export interface SmartDesktopOptions {
  enabled: boolean;
  avoidMouse: boolean;
  avoidActiveWindow: boolean;
  learnBehavior: boolean;
  movementSpeed: string;
  monitorSupport: boolean;
  fullscreenSleep: boolean;
  /** Abstand der Neubewertung in Millisekunden. */
  evaluationInterval: number;
  /** Ecken meiden – dort sieht man den Orb am schlechtesten. */
  avoidCorners: boolean;
  /** In Sichtweite des aktiven Fensters bleiben. */
  stayNearWork: boolean;
  /** Bis zu welchem Abstand das als „in Sichtweite“ gilt. */
  workReach: number;
  /** Wie deutlich eine neue Position besser sein muss. */
  switchThreshold: number;
  /** Adresse des Kerns, über den die Fensterliste kommt. Leer: keine. */
  backendUrl: string;
}

/** Die Voreinstellungen der Smart Desktop Engine. */
export const DEFAULT_SMART_DESKTOP: SmartDesktopOptions = {
  enabled: true,
  avoidMouse: true,
  avoidActiveWindow: true,
  learnBehavior: true,
  movementSpeed: "medium",
  monitorSupport: true,
  fullscreenSleep: true,
  // Häufiger als früher (2500 ms): Der Orb soll dem Geschehen folgen und
  // nicht dort stehenbleiben, wo vor einer Minute etwas los war.
  evaluationInterval: 1500,
  avoidCorners: true,
  stayNearWork: true,
  workReach: 900,
  switchThreshold: 0.08,
  backendUrl: "",
};

/** Rückrufe der Smart Desktop Engine. */
export interface DesktopHandlers {
  /** Fragt die gelernte Bewertung einer Position ab. */
  preferenceLookup?: (x: number, y: number, monitorId: number) => number;
  /** Meldet eine neue Orb-Position an das Lernsystem. */
  onPositionChosen?: (candidate: Candidate) => void;
  /** Fordert einen Zustandswechsel des Orb an. */
  onStateRequest?: (state: "idle" | "sleep") => void;
  /** Meldet, dass der Orb ausgeblendet oder eingeblendet werden soll. */
  onVisibilityRequest?: (visible: boolean) => void;
}

/**
 * Bewegt den Orb intelligent über den Desktop.
 */
export class DesktopManager {
  /** Die zuletzt vom Kern gemeldeten Fenster. */
  private remoteWindows: WindowInfo[] = [];

  /** Ob gerade eine Abfrage läuft – zwei gleichzeitig bringen nichts. */
  private remoteFetchInFlight = false;

  private window: BrowserWindow;
  private monitors: MonitorManager;
  private placement: PlacementEngine;
  private options: SmartDesktopOptions;
  private handlers: DesktopHandlers;

  private timer: NodeJS.Timeout | null = null;
  private usage: Map<string, number> = new Map();
  private lastMouse = { x: 0, y: 0, at: Date.now() };
  private mouseSpeed = 0;
  private suspended = false;

  /**
   * @param window Das Orb-Fenster.
   * @param monitors Die Monitorverwaltung.
   * @param options Einstellungen aus `config.yaml` (`smart_desktop`).
   * @param handlers Rückrufe für Lernsystem und Zustandswechsel.
   */
  constructor(
    window: BrowserWindow,
    monitors: MonitorManager,
    options: Partial<SmartDesktopOptions> = {},
    handlers: DesktopHandlers = {}
  ) {
    this.window = window;
    this.monitors = monitors;
    this.options = { ...DEFAULT_SMART_DESKTOP, ...options };
    this.handlers = handlers;

    const [width, height] = window.getSize();
    this.placement = new PlacementEngine({
      orbWidth: width,
      orbHeight: height,
      avoidMouse: this.options.avoidMouse,
      avoidActiveWindow: this.options.avoidActiveWindow,
    });
  }

  /** Startet die laufende Bewertung. */
  public start(): void {
    if (!this.options.enabled || this.timer !== null) {
      return;
    }
    this.timer = setInterval(() => this.evaluate(), this.options.evaluationInterval);
  }

  /** Hält die Bewertung an. */
  public stop(): void {
    if (this.timer !== null) {
      clearInterval(this.timer);
      this.timer = null;
    }
  }

  /**
   * Setzt die automatische Platzierung vorübergehend aus.
   *
   * Wird genutzt, während der Benutzer den Orb selbst zieht – seine
   * Entscheidung hat immer Vorrang.
   */
  public suspend(suspended: boolean): void {
    this.suspended = suspended;
  }

  /**
   * Verfolgt die Mausbewegung.
   *
   * Kommt die Maus dem Orb nahe, weicht er langsam aus – ohne hektische
   * Bewegungen.
   */
  public trackMouse(): void {
    const point = this.monitors.cursorPosition();
    const now = Date.now();
    const elapsed = Math.max(1, now - this.lastMouse.at);

    const distance = Math.hypot(point.x - this.lastMouse.x, point.y - this.lastMouse.y);
    this.mouseSpeed = (distance / elapsed) * 1000;
    this.lastMouse = { x: point.x, y: point.y, at: now };

    if (!this.options.enabled || !this.options.avoidMouse || this.suspended) {
      return;
    }

    const [x, y] = this.window.getPosition();
    const [width, height] = this.window.getSize();
    const centerX = x + width / 2;
    const centerY = y + height / 2;
    const toCursor = Math.hypot(centerX - point.x, centerY - point.y);

    // Nur ausweichen, wenn die Maus wirklich nah ist und sich nicht rasend
    // schnell bewegt (sonst wirkt der Orb nervös).
    if (toCursor < 130 && this.mouseSpeed < 2500) {
      this.evaluate(true);
    }
  }

  /**
   * Bewertet den Desktop neu und bewegt den Orb bei Bedarf.
   *
   * @param urgent Ob die Bewertung durch eine Mausannäherung ausgelöst wurde.
   */
  public evaluate(urgent = false): void {
    if (!this.options.enabled || this.suspended || this.window.isDestroyed()) {
      return;
    }

    const monitors = this.options.monitorSupport
      ? this.monitors.all()
      : [this.monitors.primary()];
    // Frische Fensterliste anstoßen. Die Antwort kommt asynchron und
    // wird beim nächsten Durchgang benutzt – auf sie zu warten würde die
    // Bewertung an die Antwortzeit des Kerns koppeln.
    this.refreshRemoteWindows();

    const windows = this.collectWindows(monitors);

    // --- Vollbild: ausblenden bzw. schlafen legen -------------------------
    const fullscreen = windows.find((window) => window.isFullscreen);
    if (fullscreen !== undefined && this.options.fullscreenSleep) {
      this.handlers.onVisibilityRequest?.(false);
      this.handlers.onStateRequest?.("sleep");
      return;
    }
    this.handlers.onVisibilityRequest?.(true);
    this.handlers.onStateRequest?.("idle");

    const state: DesktopState = {
      monitors,
      cursor: this.monitors.cursorPosition(),
      windows,
      preferenceLookup: this.handlers.preferenceLookup,
      usageLookup: (x, y, monitorId) => this.usageFor(x, y, monitorId),
    };

    const candidates = this.placement.evaluate(state);
    const [currentX, currentY] = this.window.getPosition();
    const currentMonitor = this.monitors.forPoint(currentX, currentY);

    const target = urgent
      ? candidates[0] ?? null
      : this.placement.shouldMove(
          { x: currentX, y: currentY, monitorId: currentMonitor.id },
          candidates,
          state
        );

    if (target === null) {
      return;
    }

    this.noteUsage(target.x, target.y, target.monitorId);
    this.handlers.onPositionChosen?.(target);
  }

  /**
   * Ermittelt die Fenster auf dem Desktop.
   *
   * Electron kann fremde Fenster nicht ohne zusätzliche Systembibliotheken
   * aufzählen. Damit die Engine trotzdem sinnvoll arbeitet, wird der
   * belegte Bereich aus der Differenz zwischen Bildschirmfläche und
   * Arbeitsfläche abgeleitet (Taskleiste, angedockte Leisten) und der
   * Vollbildzustand über die Arbeitsflächenhöhe erkannt.
   *
   * Sobald ein Skill zur Fensterabfrage installiert ist, liefert dieser
   * genauere Daten; die Bewertungslogik bleibt davon unberührt.
   */
  /**
   * Holt die echte Fensterliste vom Kern.
   *
   * Electron kennt nur seine eigenen Fenster. Welche Programme sonst
   * offen sind und welches davon gerade vorn ist, weiß allein das
   * Betriebssystem – und danach fragt auf dieser Seite niemand. Der
   * Python-Kern kann es längst (`EnumWindows`, `GetForegroundWindow`) und
   * stellt es unter `/windows` bereit; abgefragt wurde es nur nie.
   *
   * Das war der Grund, warum der Orb praktisch stillstand: Ohne Fenster
   * war die Bewertungslandschaft fast eben, und es gewann immer dieselbe
   * Ecke.
   */
  private refreshRemoteWindows(): void {
    if (!this.options.backendUrl || this.remoteFetchInFlight) {
      return;
    }

    this.remoteFetchInFlight = true;

    const request = http.get(`${this.options.backendUrl}/windows`, { timeout: 1500 }, (response) => {
      let body = "";
      response.on("data", (chunk) => {
        body += chunk;
      });
      response.on("end", () => {
        this.remoteFetchInFlight = false;
        try {
          const parsed = JSON.parse(body) as {
            windows?: Array<Record<string, unknown>>;
            active_handle?: number;
          };
          this.remoteWindows = this.convertRemoteWindows(parsed);
        } catch {
          // Eine unlesbare Antwort ist kein Grund, die alte Liste
          // wegzuwerfen – sie ist immer noch besser als gar keine.
        }
      });
    });

    request.on("error", () => {
      this.remoteFetchInFlight = false;
    });
    request.on("timeout", () => {
      request.destroy();
      this.remoteFetchInFlight = false;
    });
  }

  /** Übersetzt die Antwort des Kerns in die eigene Fensterdarstellung. */
  private convertRemoteWindows(parsed: {
    windows?: Array<Record<string, unknown>>;
    active_handle?: number;
  }): WindowInfo[] {
    const activeHandle = Number(parsed.active_handle ?? 0);
    const result: WindowInfo[] = [];

    for (const entry of parsed.windows ?? []) {
      const width = Number(entry.width ?? 0);
      const height = Number(entry.height ?? 0);
      const title = String(entry.title ?? "");

      // Minimierte und winzige Fenster belegen keine Fläche.
      if (entry.minimized === true || width < 80 || height < 60) {
        continue;
      }
      // Der Orb weicht nicht sich selbst aus.
      if (title.startsWith("AI-Orb")) {
        continue;
      }

      result.push({
        bounds: {
          x: Number(entry.left ?? 0),
          y: Number(entry.top ?? 0),
          width,
          height,
        },
        isActive: Number(entry.handle ?? -1) === activeHandle && activeHandle !== 0,
        isFullscreen: false,
        isMaximized: entry.maximized === true,
        className: title.slice(0, 60),
      });
    }

    return result;
  }

  private collectWindows(monitors: MonitorInfo[]): WindowInfo[] {
    // Die echten Fenster zuerst; Taskleiste und Docks kommen darunter
    // weiterhin dazu, denn die meldet das Betriebssystem nicht als Fenster.
    const windows: WindowInfo[] = [...this.remoteWindows];

    for (const monitor of monitors) {
      const bounds = monitor.bounds;
      const area = monitor.workArea;

      // Taskleiste / angedockte Leisten als belegte Bereiche behandeln.
      if (area.height < bounds.height) {
        const taskbarHeight = bounds.height - area.height;
        const atTop = area.y > bounds.y;
        windows.push({
          bounds: {
            x: bounds.x,
            y: atTop ? bounds.y : area.y + area.height,
            width: bounds.width,
            height: taskbarHeight,
          },
          isActive: false,
          isFullscreen: false,
          isMaximized: false,
          className: "taskleiste",
        });
      }

      if (area.width < bounds.width) {
        const dockWidth = bounds.width - area.width;
        const atLeft = area.x > bounds.x;
        windows.push({
          bounds: {
            x: atLeft ? bounds.x : area.x + area.width,
            y: bounds.y,
            width: dockWidth,
            height: bounds.height,
          },
          isActive: false,
          isFullscreen: false,
          isMaximized: false,
          className: "dock",
        });
      }
    }

    return windows;
  }

  // --- Nutzungsverfolgung ----------------------------------------------------

  private usageKey(x: number, y: number, monitorId: number): string {
    return `${monitorId}:${Math.round(x / 200)}:${Math.round(y / 200)}`;
  }

  private noteUsage(x: number, y: number, monitorId: number): void {
    const key = this.usageKey(x, y, monitorId);
    this.usage.set(key, (this.usage.get(key) ?? 0) + 1);
  }

  private usageFor(x: number, y: number, monitorId: number): number {
    const key = this.usageKey(x, y, monitorId);
    const count = this.usage.get(key) ?? 0;
    const maximum = Math.max(1, ...this.usage.values());
    return count / maximum;
  }

  /** Die zuletzt gemessene Mausgeschwindigkeit in Pixeln pro Sekunde. */
  public get currentMouseSpeed(): number {
    return this.mouseSpeed;
  }

  /** Aktualisiert die Einstellungen zur Laufzeit. */
  public configure(options: Partial<SmartDesktopOptions>): void {
    this.options = { ...this.options, ...options };
    this.placement.configure({
      avoidMouse: this.options.avoidMouse,
      avoidActiveWindow: this.options.avoidActiveWindow,
      avoidCorners: this.options.avoidCorners,
      stayNearWork: this.options.stayNearWork,
      workReach: this.options.workReach,
      switchThreshold: this.options.switchThreshold,
    });
    if (!this.options.enabled) {
      this.stop();
    }
  }
}
