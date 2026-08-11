/**
 * movement.ts – Weiche Bewegung des Orb-Fensters.
 *
 * Der Orb springt nie und teleportiert nie. Jede Positionsänderung wird
 * über Tweening mit Ease-In/Ease-Out, einer kubischen Bézier-Kurve oder
 * einer Federanimation ausgeführt.
 *
 * Dieses Modul berechnet ausschließlich Positionen. Das tatsächliche
 * Verschieben des Fensters übernimmt der Hauptprozess.
 */

/** Die verfügbaren Bewegungsarten. */
export type EasingName = "linear" | "easeIn" | "easeOut" | "easeInOut" | "spring" | "bezier";

/** Ein zweidimensionaler Punkt. */
export interface Point {
  x: number;
  y: number;
}

/** Voreingestellte Geschwindigkeiten (Dauer in Sekunden pro 1000 Pixel). */
const SPEED_PRESETS: Record<string, number> = {
  slow: 2.4,
  medium: 1.4,
  fast: 0.8,
};

/** Interpoliert zwei Zahlen. */
function lerp(from: number, to: number, amount: number): number {
  return from + (to - from) * amount;
}

/** Die Easing-Funktionen. */
const EASINGS: Record<string, (t: number) => number> = {
  linear: (t) => t,
  easeIn: (t) => t * t * t,
  easeOut: (t) => 1 - Math.pow(1 - t, 3),
  easeInOut: (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2),
  // Kubische Bézier-Annäherung mit sanftem Anlauf und weichem Ausklang.
  bezier: (t) => {
    const inverse = 1 - t;
    return 3 * inverse * inverse * t * 0.1 + 3 * inverse * t * t * 0.9 + t * t * t;
  },
  // Federartiges Einschwingen ohne starkes Überschwingen.
  spring: (t) => {
    if (t >= 1) {
      return 1;
    }
    return 1 - Math.pow(2, -9 * t) * Math.cos(t * Math.PI * 2.4);
  },
};

/**
 * Bewegt den Orb weich von einer Position zur nächsten.
 */
export class MovementEngine {
  private start: Point = { x: 0, y: 0 };
  private target: Point = { x: 0, y: 0 };
  private current: Point = { x: 0, y: 0 };
  private elapsed = 0;
  private duration = 0;
  private easing: EasingName = "easeInOut";
  private speedFactor: number;
  private active = false;
  private onArrive: (() => void) | null = null;

  /**
   * @param speed Geschwindigkeitsvoreinstellung: `slow`, `medium` oder `fast`.
   */
  constructor(speed: string = "medium") {
    this.speedFactor = SPEED_PRESETS[speed] ?? SPEED_PRESETS.medium;
  }

  /** Setzt die Position ohne Animation (z. B. beim Start). */
  public reset(position: Point): void {
    this.current = { ...position };
    this.start = { ...position };
    this.target = { ...position };
    this.active = false;
    this.elapsed = 0;
  }

  /**
   * Startet eine Bewegung zu einer neuen Position.
   *
   * @param target Zielposition in Bildschirmkoordinaten.
   * @param easing Die gewünschte Bewegungsart.
   * @param onArrive Callback, der beim Erreichen des Ziels läuft.
   */
  public moveTo(target: Point, easing: EasingName = "easeInOut", onArrive?: () => void): void {
    const distance = Math.hypot(target.x - this.current.x, target.y - this.current.y);
    if (distance < 1) {
      this.current = { ...target };
      onArrive?.();
      return;
    }

    this.start = { ...this.current };
    this.target = { ...target };
    this.easing = easing;
    this.elapsed = 0;
    // Längere Wege dauern länger, aber nicht linear – sonst wirken kurze
    // Wege hektisch und lange Wege zäh.
    this.duration = Math.max(0.35, (Math.sqrt(distance) / 31.6) * this.speedFactor);
    this.active = true;
    this.onArrive = onArrive ?? null;
  }

  /**
   * Aktualisiert die Bewegung.
   *
   * @param delta Zeit seit dem letzten Bild in Sekunden.
   * @returns Die aktuelle Position, oder `null`, wenn keine Bewegung läuft.
   */
  public update(delta: number): Point | null {
    if (!this.active) {
      return null;
    }

    this.elapsed = Math.min(this.duration, this.elapsed + delta);
    const progress = this.duration <= 0 ? 1 : this.elapsed / this.duration;
    const eased = (EASINGS[this.easing] ?? EASINGS.easeInOut)(progress);

    this.current = {
      x: lerp(this.start.x, this.target.x, eased),
      y: lerp(this.start.y, this.target.y, eased),
    };

    if (progress >= 1) {
      this.active = false;
      this.current = { ...this.target };
      const callback = this.onArrive;
      this.onArrive = null;
      callback?.();
    }

    return this.current;
  }

  /** Bricht die laufende Bewegung an der aktuellen Position ab. */
  public stop(): void {
    this.active = false;
    this.onArrive = null;
    this.target = { ...this.current };
  }

  /** Ob gerade eine Bewegung läuft. */
  public get isMoving(): boolean {
    return this.active;
  }

  /** Die aktuelle Position. */
  public get position(): Point {
    return { ...this.current };
  }

  /** Die angestrebte Zielposition. */
  public get destination(): Point {
    return { ...this.target };
  }

  /** Ändert die Bewegungsgeschwindigkeit zur Laufzeit. */
  public setSpeed(speed: string): void {
    this.speedFactor = SPEED_PRESETS[speed] ?? SPEED_PRESETS.medium;
  }
}
