/**
 * window_manager.ts
 *
 * Verantwortlich für die Positionierung des Orb-Fensters: Berechnung einer
 * sinnvollen Startposition (zentriert oder zuletzt gemerkt), Persistierung
 * der zuletzt gewählten Position über Neustarts hinweg sowie grundlegende
 * Multi-Monitor-Unterstützung (Auflösung, Skalierung, Fallback, falls ein
 * gemerkter Monitor nicht mehr angeschlossen ist).
 *
 * Die fortgeschrittene "Smart Desktop Engine" (freie Bildschirmbereiche,
 * Scoring, Lernsystem) ist Gegenstand von AI-Orb v2 Phase 3 und wird hier
 * bewusst nicht vorweggenommen; dieses Modul stellt ausschließlich die in
 * Phase 2 geforderte grundlegende Fensterverwaltung bereit.
 */

import { screen, Display } from "electron";
import * as fs from "fs";
import * as path from "path";

/** Persistierter Fensterzustand (Position + zugehöriger Monitor). */
export interface WindowState {
  x: number;
  y: number;
  displayId: number;
}

/**
 * Verwaltet die Positionierung des Orb-Fensters über mehrere Monitore
 * hinweg und persistiert die zuletzt genutzte Position in
 * ``data/window_state.json``.
 */
export class WindowManager {
  private readonly stateFilePath: string;

  constructor(dataDir: string) {
    this.stateFilePath = path.join(dataDir, "window_state.json");
  }

  /**
   * Ermittelt die initiale Fensterposition.
   *
   * @param width Fensterbreite in Pixeln.
   * @param height Fensterhöhe in Pixeln.
   * @param mode "remembered" nutzt eine zuvor gespeicherte Position (falls
   *   vorhanden und der zugehörige Monitor noch existiert), ansonsten wird
   *   auf "center" zurückgefallen. "center" zentriert immer auf dem
   *   primären Monitor.
   */
  public getInitialPosition(
    width: number,
    height: number,
    mode: string
  ): { x: number; y: number } {
    if (mode === "remembered") {
      const remembered = this.loadState();
      if (remembered) {
        const display = screen
          .getAllDisplays()
          .find((d) => d.id === remembered.displayId);
        if (display) {
          return this.clampToDisplay(
            remembered.x,
            remembered.y,
            width,
            height,
            display
          );
        }
      }
    }
    return this.getDefaultPosition(width, height);
  }

  /**
   * Berechnet eine Standardposition (untere rechte Ecke des primären
   * Monitors, mit etwas Abstand zum Bildschirmrand), falls keine gemerkte
   * Position verfügbar oder gültig ist.
   */
  public getDefaultPosition(
    width: number,
    height: number
  ): { x: number; y: number } {
    const display = screen.getPrimaryDisplay();
    const margin = 48;
    const { x: areaX, y: areaY, width: areaW, height: areaH } =
      display.workArea;
    return {
      x: areaX + areaW - width - margin,
      y: areaY + areaH - height - margin,
    };
  }

  /**
   * Stellt sicher, dass eine Position vollständig innerhalb der
   * sichtbaren Arbeitsfläche eines Monitors liegt (relevant nach
   * Auflösungsänderungen oder wenn ein Monitor entfernt wurde).
   */
  public clampToDisplay(
    x: number,
    y: number,
    width: number,
    height: number,
    display: Display
  ): { x: number; y: number } {
    const { x: areaX, y: areaY, width: areaW, height: areaH } =
      display.workArea;
    const clampedX = Math.min(Math.max(x, areaX), areaX + areaW - width);
    const clampedY = Math.min(Math.max(y, areaY), areaY + areaH - height);
    return { x: clampedX, y: clampedY };
  }

  /** Ermittelt den Monitor, auf dem sich ein gegebener Punkt befindet. */
  public getDisplayForPoint(x: number, y: number): Display {
    return screen.getDisplayNearestPoint({ x, y });
  }

  /** Speichert die aktuelle Fensterposition persistent für den nächsten Start. */
  public savePosition(x: number, y: number): void {
    const display = this.getDisplayForPoint(x, y);
    const state: WindowState = { x, y, displayId: display.id };
    try {
      fs.mkdirSync(path.dirname(this.stateFilePath), { recursive: true });
      fs.writeFileSync(
        this.stateFilePath,
        JSON.stringify(state, null, 2),
        "utf-8"
      );
    } catch (error) {
      // Ein fehlgeschlagener Schreibversuch (z. B. fehlende Berechtigung)
      // darf die Anwendung nicht zum Absturz bringen; die Position wird
      // beim nächsten Start dann erneut aus der Standardposition berechnet.
      // eslint-disable-next-line no-console
      console.error("[window_manager] Position konnte nicht gespeichert werden:", error);
    }
  }

  /** Lädt die zuletzt gespeicherte Fensterposition, falls vorhanden. */
  private loadState(): WindowState | null {
    try {
      if (!fs.existsSync(this.stateFilePath)) {
        return null;
      }
      const raw = fs.readFileSync(this.stateFilePath, "utf-8");
      const parsed = JSON.parse(raw) as Partial<WindowState>;
      if (
        typeof parsed.x === "number" &&
        typeof parsed.y === "number" &&
        typeof parsed.displayId === "number"
      ) {
        return parsed as WindowState;
      }
      return null;
    } catch (error) {
      // eslint-disable-next-line no-console
      console.error("[window_manager] Gespeicherte Position ungültig:", error);
      return null;
    }
  }
}
