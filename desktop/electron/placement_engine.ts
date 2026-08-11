/**
 * placement_engine.ts – Die Platzierungslogik der Smart Desktop Engine.
 *
 * Der Orb soll niemals im Weg sein. Diese Engine unterteilt die
 * Arbeitsfläche jedes Monitors in ein Raster, bewertet jede Zelle und wählt
 * die beste Position.
 *
 * Bewertung (Scoring):
 *
 *     + freie Fläche
 *     + Abstand zur Maus
 *     + Abstand zu aktiven Fenstern
 *     + Benutzerpräferenz (gelernt)
 *     + selten genutzte Bereiche
 *     − Nähe zum Cursor
 *     − Überdeckung wichtiger Bedienelemente
 *     − aktive Eingabe
 *     − Vollbild
 *
 * Die Position mit dem höchsten Wert gewinnt. Ein Wechsel erfolgt nur, wenn
 * die neue Position deutlich besser ist – so entstehen keine ständigen
 * Richtungswechsel.
 */

import type { MonitorInfo } from "./monitor_manager";

/** Eine bewertete Kandidatenposition. */
export interface Candidate {
  x: number;
  y: number;
  monitorId: number;
  score: number;
  /** Die einzelnen Bewertungsbestandteile – für die Nachvollziehbarkeit. */
  breakdown: Record<string, number>;
}

/** Die Beschreibung eines Fensters auf dem Desktop. */
export interface WindowInfo {
  bounds: { x: number; y: number; width: number; height: number };
  isActive: boolean;
  isFullscreen: boolean;
  isMaximized: boolean;
  /** Fensterklasse bzw. Programmname, z. B. `code` oder `firefox`. */
  className?: string;
}

/** Der Zustand des Desktops zum Zeitpunkt der Bewertung. */
export interface DesktopState {
  monitors: MonitorInfo[];
  cursor: { x: number; y: number };
  windows: WindowInfo[];
  /** Gelernte Benutzerpräferenz je Position (0.0 bis 1.0). */
  preferenceLookup?: (x: number, y: number, monitorId: number) => number;
  /** Wie oft eine Zone bereits genutzt wurde (für „selten genutzt“). */
  usageLookup?: (x: number, y: number, monitorId: number) => number;
}

/** Einstellungen der Platzierungslogik. */
export interface PlacementOptions {
  orbWidth: number;
  orbHeight: number;
  /** Auflösung des Rasters je Achse. */
  gridSteps: number;
  /** Mindestabstand zum Bildschirmrand. */
  margin: number;
  /** Abstand, ab dem die Maus als „nah“ gilt. */
  mouseAvoidRadius: number;
  /** Ob aktiven Fenstern ausgewichen wird. */
  avoidActiveWindow: boolean;
  /** Ob der Maus ausgewichen wird. */
  avoidMouse: boolean;
  /** Um wie viel besser eine neue Position sein muss, damit gewechselt wird. */
  switchThreshold: number;
  /** Ecken meiden – dort sieht man den Orb am schlechtesten. */
  avoidCorners: boolean;
  /** Wie stark Randnähe belohnt wird. */
  edgeWeight: number;
  /** In Sichtweite des aktiven Fensters bleiben. */
  stayNearWork: boolean;
  /** Bis zu welchem Abstand (Pixel) das als „in Sichtweite“ gilt. */
  workReach: number;
  /** Wie stark die Nähe zur Arbeit belohnt wird. */
  workWeight: number;
}

/** Voreinstellungen der Platzierungslogik. */
export const DEFAULT_PLACEMENT: PlacementOptions = {
  orbWidth: 220,
  orbHeight: 220,
  gridSteps: 12,
  margin: 24,
  mouseAvoidRadius: 260,
  avoidActiveWindow: true,
  avoidMouse: true,
  // Niedriger als früher (0.18). Der Orb soll dem Geschehen folgen; ist er
  // zu träge, klebt er dort, wo vor zehn Minuten etwas los war.
  switchThreshold: 0.08,
  avoidCorners: true,
  // Schwächer als früher (0.10): Der Rand ist ein Vorzug, kein Gesetz.
  edgeWeight: 0.05,
  stayNearWork: true,
  workReach: 900,
  workWeight: 0.26,
};

/**
 * Bereiche, in denen sich typischerweise wichtige Bedienelemente befinden
 * und die daher gemieden werden: der obere Fensterbereich (Titelleiste,
 * Menü, Adressleiste, Werkzeugleisten) sowie der linke Rand (Seitenleisten).
 */
function importantAreaPenalty(
  x: number,
  y: number,
  width: number,
  height: number,
  window: WindowInfo
): number {
  const bounds = window.bounds;
  const overlapsWindow =
    x < bounds.x + bounds.width &&
    x + width > bounds.x &&
    y < bounds.y + bounds.height &&
    y + height > bounds.y;

  if (!overlapsWindow) {
    return 0;
  }

  let penalty = 0.25;

  // Oberer Fensterbereich: Titelleiste, Menü, Tabs, Adressleiste, Toolbar.
  if (y < bounds.y + 140) {
    penalty += 0.5;
  }
  // Linker Rand: Seitenleisten, Dateibäume, Explorer.
  if (x < bounds.x + 260) {
    penalty += 0.25;
  }
  // Unterer Rand: Statusleisten und Terminals.
  if (y + height > bounds.y + bounds.height - 80) {
    penalty += 0.15;
  }

  return penalty;
}

/**
 * Bewertet Positionen und wählt die beste aus.
 */
export class PlacementEngine {
  private options: PlacementOptions;

  constructor(options: Partial<PlacementOptions> = {}) {
    this.options = { ...DEFAULT_PLACEMENT, ...options };
  }

  /** Passt die Einstellungen zur Laufzeit an. */
  public configure(options: Partial<PlacementOptions>): void {
    this.options = { ...this.options, ...options };
  }

  /**
   * Erzeugt alle Kandidatenpositionen auf allen Monitoren.
   *
   * @param state Der aktuelle Desktopzustand.
   * @returns Absteigend nach Bewertung sortierte Kandidaten.
   */
  public evaluate(state: DesktopState): Candidate[] {
    const candidates: Candidate[] = [];
    const { orbWidth, orbHeight, gridSteps, margin } = this.options;

    for (const monitor of state.monitors) {
      const area = monitor.workArea;
      const usableWidth = area.width - orbWidth - margin * 2;
      const usableHeight = area.height - orbHeight - margin * 2;
      if (usableWidth <= 0 || usableHeight <= 0) {
        continue;
      }

      // Vollbildfenster auf diesem Monitor: Der Orb weicht ihm aus.
      const hasFullscreen = state.windows.some(
        (window) =>
          window.isFullscreen &&
          window.bounds.x >= area.x - 2 &&
          window.bounds.x < area.x + area.width
      );

      for (let column = 0; column <= gridSteps; column += 1) {
        for (let row = 0; row <= gridSteps; row += 1) {
          const x = area.x + margin + (usableWidth * column) / gridSteps;
          const y = area.y + margin + (usableHeight * row) / gridSteps;
          candidates.push(this.score(x, y, monitor, state, hasFullscreen));
        }
      }
    }

    candidates.sort((a, b) => b.score - a.score);
    return candidates;
  }

  /**
   * Bewertet eine einzelne Position.
   *
   * Die Einzelwerte bleiben in `breakdown` erhalten, damit die Entscheidung
   * nachvollziehbar bleibt und protokolliert werden kann.
   */
  private score(
    x: number,
    y: number,
    monitor: MonitorInfo,
    state: DesktopState,
    hasFullscreen: boolean
  ): Candidate {
    const { orbWidth, orbHeight, mouseAvoidRadius } = this.options;
    const centerX = x + orbWidth / 2;
    const centerY = y + orbHeight / 2;

    const breakdown: Record<string, number> = {};

    // --- Freie Fläche: keine Fensterüberdeckung ---------------------------
    let coverage = 0;
    let importantPenalty = 0;
    let activeWindowPenalty = 0;

    for (const window of state.windows) {
      const overlap = this.overlapRatio(x, y, orbWidth, orbHeight, window.bounds);
      if (overlap > 0) {
        coverage += overlap;
        importantPenalty += importantAreaPenalty(x, y, orbWidth, orbHeight, window);
        if (window.isActive && this.options.avoidActiveWindow) {
          activeWindowPenalty += overlap * 0.8;
        }
      }
    }

    breakdown.freieFläche = Math.max(0, 1 - Math.min(1, coverage)) * 0.30;
    breakdown.wichtigeBedienelemente = -Math.min(1, importantPenalty) * 0.25;
    breakdown.aktivesFenster = -Math.min(1, activeWindowPenalty) * 0.20;

    // --- Abstand zur Maus --------------------------------------------------
    if (this.options.avoidMouse) {
      const distance = Math.hypot(centerX - state.cursor.x, centerY - state.cursor.y);
      const normalized = Math.min(1, distance / mouseAvoidRadius);
      breakdown.abstandZurMaus = normalized * 0.18;
      if (distance < mouseAvoidRadius * 0.5) {
        breakdown.näheZumCursor = -(1 - distance / (mouseAvoidRadius * 0.5)) * 0.25;
      } else {
        breakdown.näheZumCursor = 0;
      }
    } else {
      breakdown.abstandZurMaus = 0;
      breakdown.näheZumCursor = 0;
    }

    // --- Benutzerpräferenz (gelernt) -----------------------------------------
    const preference = state.preferenceLookup?.(centerX, centerY, monitor.id) ?? 0;
    breakdown.benutzerpräferenz = preference * 0.28;

    // --- Selten genutzte Bereiche bevorzugen ----------------------------------
    const usage = state.usageLookup?.(centerX, centerY, monitor.id) ?? 0;
    breakdown.seltenGenutzt = (1 - Math.min(1, usage)) * 0.08;

    // --- Vollbild --------------------------------------------------------------
    breakdown.vollbild = hasFullscreen ? -0.6 : 0;

    // --- Rand ja, Ecke nein ------------------------------------------------
    //
    // Randnähe war früher pauschal belohnt: "dort stört er am wenigsten".
    // Nur ist eine Ecke an *zwei* Rändern zugleich und gewinnt deshalb
    // immer. Der Orb parkte oben rechts, wo man ihn kaum noch wahrnimmt –
    // ein Assistent, den man suchen muss, ist keiner.
    //
    // Jetzt wird der Rand weiterhin leicht bevorzugt, die Ecke aber
    // ausdrücklich bestraft. Der Orb sitzt damit an einer Kante, aber auf
    // ihrer Länge, nicht in ihrem Zipfel.
    const area = monitor.workArea;
    const distanceLeft = centerX - area.x;
    const distanceRight = area.x + area.width - centerX;
    const distanceTop = centerY - area.y;
    const distanceBottom = area.y + area.height - centerY;

    const edgeDistance = Math.min(distanceLeft, distanceRight, distanceTop, distanceBottom);
    const halfSpan = Math.min(area.width, area.height) / 2;
    const edgeRatio = 1 - Math.min(1, edgeDistance / halfSpan);
    breakdown.randnähe = edgeRatio * this.options.edgeWeight;

    if (this.options.avoidCorners) {
      // Eine Ecke liegt vor, wenn beide Achsen nahe am Rand sind.
      const horizontal = 1 - Math.min(1, Math.min(distanceLeft, distanceRight) / (area.width * 0.22));
      const vertical = 1 - Math.min(1, Math.min(distanceTop, distanceBottom) / (area.height * 0.22));
      breakdown.ecke = -(horizontal * vertical) * 0.32;
    } else {
      breakdown.ecke = 0;
    }

    // --- In Sichtweite der Arbeit bleiben -----------------------------------
    //
    // Das aktive Fenster wurde bisher nur gemieden. Gemieden heißt aber
    // nicht "möglichst weit weg": Wer am linken Bildschirmrand schreibt,
    // will den Orb nicht am rechten Rand suchen. Belohnt wird deshalb ein
    // Platz dicht neben dem Fenster – daneben, nicht darauf. Das Meiden
    // der Fensterfläche selbst besorgen die Strafterme weiter oben.
    if (this.options.stayNearWork) {
      const active = state.windows.find((window) => window.isActive);
      if (active) {
        const workX = active.bounds.x + active.bounds.width / 2;
        const workY = active.bounds.y + active.bounds.height / 2;
        const distance = Math.hypot(centerX - workX, centerY - workY);
        const reach = Math.max(1, this.options.workReach);
        breakdown.näheZurArbeit = (1 - Math.min(1, distance / reach)) * this.options.workWeight;
      } else {
        breakdown.näheZurArbeit = 0;
      }
    } else {
      breakdown.näheZurArbeit = 0;
    }

    const total = Object.values(breakdown).reduce((sum, value) => sum + value, 0);

    return {
      x: Math.round(x),
      y: Math.round(y),
      monitorId: monitor.id,
      score: total,
      breakdown,
    };
  }

  /** Berechnet den Anteil der Orb-Fläche, der von einem Fenster überdeckt wird. */
  private overlapRatio(
    x: number,
    y: number,
    width: number,
    height: number,
    bounds: { x: number; y: number; width: number; height: number }
  ): number {
    const overlapX = Math.max(0, Math.min(x + width, bounds.x + bounds.width) - Math.max(x, bounds.x));
    const overlapY = Math.max(
      0,
      Math.min(y + height, bounds.y + bounds.height) - Math.max(y, bounds.y)
    );
    const area = width * height;
    return area <= 0 ? 0 : (overlapX * overlapY) / area;
  }

  /**
   * Entscheidet, ob sich ein Wechsel zur besten Position lohnt.
   *
   * Ein Wechsel erfolgt nur, wenn die neue Position deutlich besser ist –
   * andernfalls bliebe der Orb ständig in Bewegung.
   *
   * @param current Die aktuelle Position.
   * @param candidates Die bewerteten Kandidaten.
   * @param state Der Desktopzustand.
   * @returns Die neue Position, oder `null`, wenn kein Wechsel nötig ist.
   */
  public shouldMove(
    current: { x: number; y: number; monitorId: number },
    candidates: Candidate[],
    state: DesktopState
  ): Candidate | null {
    if (candidates.length === 0) {
      return null;
    }

    const best = candidates[0];
    const monitor =
      state.monitors.find((item) => item.id === current.monitorId) ?? state.monitors[0];
    if (monitor === undefined) {
      return null;
    }

    const currentScore = this.score(
      current.x,
      current.y,
      monitor,
      state,
      state.windows.some((window) => window.isFullscreen)
    ).score;

    if (best.score - currentScore < this.options.switchThreshold) {
      return null;
    }

    // Sehr kurze Wege lohnen sich nicht – sie wirken nur unruhig.
    const distance = Math.hypot(best.x - current.x, best.y - current.y);
    if (distance < 60 && best.monitorId === current.monitorId) {
      return null;
    }

    return best;
  }
}
