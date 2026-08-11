/**
 * monitor_manager.ts – Multi-Monitor-Verwaltung.
 *
 * Erkennt Anzahl, Auflösung, DPI-Skalierung und den primären Monitor sowie
 * Monitorwechsel und Hotplug (Anschließen und Abziehen von Bildschirmen zur
 * Laufzeit).
 *
 * Der Orb darf zwischen Monitoren wechseln; dieses Modul liefert dafür die
 * nötigen Informationen, führt den Wechsel aber nicht selbst aus.
 */

import { screen, type Display } from "electron";

/** Zusammengefasste Angaben zu einem Monitor. */
export interface MonitorInfo {
  id: number;
  index: number;
  isPrimary: boolean;
  bounds: { x: number; y: number; width: number; height: number };
  /** Arbeitsfläche ohne Taskleiste und angedockte Leisten. */
  workArea: { x: number; y: number; width: number; height: number };
  scaleFactor: number;
  rotation: number;
}

/** Rückrufe bei Änderungen der Monitorkonfiguration. */
export interface MonitorHandlers {
  /** Ein Monitor wurde angeschlossen. */
  onAdded?: (monitor: MonitorInfo) => void;
  /** Ein Monitor wurde entfernt. */
  onRemoved?: (monitorId: number) => void;
  /** Ein Monitor hat sich geändert (Auflösung, Skalierung, Anordnung). */
  onChanged?: (monitor: MonitorInfo) => void;
}

/**
 * Verwaltet alle angeschlossenen Monitore.
 */
export class MonitorManager {
  private handlers: MonitorHandlers;
  private known: Map<number, MonitorInfo> = new Map();

  /**
   * @param handlers Rückrufe für Änderungen der Monitorkonfiguration.
   */
  constructor(handlers: MonitorHandlers = {}) {
    this.handlers = handlers;
    this.refresh();
    this.attachListeners();
  }

  /** Wandelt einen Electron-Display in unsere Struktur um. */
  private toInfo(display: Display, index: number, primaryId: number): MonitorInfo {
    return {
      id: display.id,
      index,
      isPrimary: display.id === primaryId,
      bounds: { ...display.bounds },
      workArea: { ...display.workArea },
      scaleFactor: display.scaleFactor,
      rotation: display.rotation,
    };
  }

  /** Liest die aktuelle Monitorkonfiguration neu ein. */
  public refresh(): MonitorInfo[] {
    const primaryId = screen.getPrimaryDisplay().id;
    const monitors = screen
      .getAllDisplays()
      .map((display, index) => this.toInfo(display, index, primaryId));

    this.known = new Map(monitors.map((monitor) => [monitor.id, monitor]));
    return monitors;
  }

  private attachListeners(): void {
    screen.on("display-added", (_event, display) => {
      const monitors = this.refresh();
      const added = monitors.find((monitor) => monitor.id === display.id);
      if (added !== undefined) {
        this.handlers.onAdded?.(added);
      }
    });

    screen.on("display-removed", (_event, display) => {
      this.refresh();
      this.handlers.onRemoved?.(display.id);
    });

    screen.on("display-metrics-changed", (_event, display) => {
      const monitors = this.refresh();
      const changed = monitors.find((monitor) => monitor.id === display.id);
      if (changed !== undefined) {
        this.handlers.onChanged?.(changed);
      }
    });
  }

  /** Alle bekannten Monitore. */
  public all(): MonitorInfo[] {
    return Array.from(this.known.values()).sort((a, b) => a.index - b.index);
  }

  /** Anzahl der angeschlossenen Monitore. */
  public get count(): number {
    return this.known.size;
  }

  /** Der primäre Monitor. */
  public primary(): MonitorInfo {
    const primary = this.all().find((monitor) => monitor.isPrimary);
    return primary ?? this.all()[0];
  }

  /** Der Monitor mit einer bestimmten Kennung. */
  public byId(id: number): MonitorInfo | undefined {
    return this.known.get(id);
  }

  /** Der Monitor, auf dem sich ein Punkt befindet. */
  public forPoint(x: number, y: number): MonitorInfo {
    const display = screen.getDisplayNearestPoint({ x: Math.round(x), y: Math.round(y) });
    return this.byId(display.id) ?? this.primary();
  }

  /** Der Monitor, auf dem sich der Mauszeiger befindet. */
  public underCursor(): MonitorInfo {
    const point = screen.getCursorScreenPoint();
    return this.forPoint(point.x, point.y);
  }

  /**
   * Prüft, ob eine Fensterposition vollständig auf einem Monitor liegt.
   *
   * Wird nach Auflösungsänderungen oder dem Abziehen eines Monitors
   * genutzt, damit der Orb nie außerhalb des sichtbaren Bereichs landet.
   */
  public isVisible(x: number, y: number, width: number, height: number): boolean {
    return this.all().some((monitor) => {
      const area = monitor.workArea;
      return (
        x >= area.x &&
        y >= area.y &&
        x + width <= area.x + area.width &&
        y + height <= area.y + area.height
      );
    });
  }

  /** Die aktuelle Zeigerposition in Bildschirmkoordinaten. */
  public cursorPosition(): { x: number; y: number } {
    return screen.getCursorScreenPoint();
  }
}
