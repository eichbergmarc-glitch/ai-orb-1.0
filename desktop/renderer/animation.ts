/**
 * animation.ts – Die Animationsschleife des Orb.
 *
 * Die Animation läuft dauerhaft mit `requestAnimationFrame`. Sie zielt auf
 * 60 Bilder pro Sekunde, misst laufend die tatsächliche Bildrate und senkt
 * bei Bedarf automatisch die Qualität, um die Auslastung gering zu halten.
 *
 * Die mitgelieferte Konfiguration hält auch bei Inaktivität die volle
 * Bildrate. Eine niedrigere Leerlauf-Bildrate bleibt optional möglich,
 * führt bei den langsam wandernden Energieringen aber sichtbar zu Stufen.
 */

/** Die Rückrufe der Animationsschleife. */
export interface AnimationCallbacks {
  /** Wird in jedem Bild aufgerufen. */
  update: (elapsed: number, delta: number) => void;
  /** Wird nach dem Update aufgerufen und rendert das Bild. */
  render: () => void;
  /** Wird aufgerufen, wenn sich die Qualitätsstufe ändert. */
  onQualityChange?: (level: number) => void;
}

/** Optionen der Animationsschleife. */
export interface AnimationOptions {
  /** Angestrebte Bildrate. */
  targetFps: number;
  /** Ob die Qualität automatisch angepasst wird. */
  adaptiveQuality: boolean;
  /** Bildrate im Energiesparmodus. */
  idleFps: number;
  /** Nach wie vielen Sekunden ohne Interaktion gespart wird. */
  idleAfterSeconds: number;
}

/** Die Voreinstellungen der Animation. */
export const DEFAULT_ANIMATION: AnimationOptions = {
  targetFps: 60,
  adaptiveQuality: true,
  idleFps: 60,
  idleAfterSeconds: 45,
};

/**
 * Steuert die Animationsschleife samt Qualitäts- und Energieverwaltung.
 */
export class AnimationLoop {
  private callbacks: AnimationCallbacks;
  private options: AnimationOptions;

  private running = false;
  private frameHandle = 0;
  private lastFrameTime = 0;
  private elapsed = 0;
  private lastActivity = 0;

  private frameTimes: number[] = [];
  private qualityLevel = 2;
  private qualityCooldown = 0;

  /**
   * @param callbacks Die auszuführenden Rückrufe.
   * @param options Bildrate und Qualitätsverhalten aus `config.yaml`.
   */
  constructor(callbacks: AnimationCallbacks, options: Partial<AnimationOptions> = {}) {
    this.callbacks = callbacks;
    this.options = { ...DEFAULT_ANIMATION, ...options };
    this.lastActivity = performance.now();
  }

  /** Startet die Animation. */
  public start(): void {
    if (this.running) {
      return;
    }
    this.running = true;
    this.lastFrameTime = performance.now();
    this.frameHandle = requestAnimationFrame((time) => this.tick(time));
  }

  /** Hält die Animation an. */
  public stop(): void {
    this.running = false;
    cancelAnimationFrame(this.frameHandle);
  }

  /**
   * Vermerkt Benutzeraktivität.
   *
   * Beendet den Energiesparmodus sofort und stellt volle Qualität her.
   */
  public noteActivity(): void {
    this.lastActivity = performance.now();
  }

  /** Die aktuell gemessene Bildrate. */
  public get fps(): number {
    if (this.frameTimes.length < 2) {
      return this.options.targetFps;
    }
    const average =
      this.frameTimes.reduce((total, value) => total + value, 0) / this.frameTimes.length;
    return average > 0 ? 1000 / average : this.options.targetFps;
  }

  /** Die aktuelle Qualitätsstufe (0 = niedrig, 2 = hoch). */
  public get quality(): number {
    return this.qualityLevel;
  }

  /** Ob der Orb sich derzeit im Energiesparmodus befindet. */
  public get isIdle(): boolean {
    return (performance.now() - this.lastActivity) / 1000 > this.options.idleAfterSeconds;
  }

  private tick(now: number): void {
    if (!this.running) {
      return;
    }
    this.frameHandle = requestAnimationFrame((time) => this.tick(time));

    const rawDelta = now - this.lastFrameTime;
    const targetFps = this.isIdle ? this.options.idleFps : this.options.targetFps;
    const minimumFrameTime = 1000 / targetFps;

    // Bei 60 FPS zeichnet requestAnimationFrame genau im Takt des Monitors.
    // Ein eigener 60-FPS-Begrenzer erzeugt auf 90/144-Hz-Bildschirmen ein
    // ungleichmäßiges 2/3-Frame-Muster und lässt gerade langsame Ringe
    // stocken. Nur ausdrücklich niedrige Sparraten werden noch gedrosselt.
    if (targetFps < 55 && rawDelta < minimumFrameTime - 0.5) {
      return;
    }

    this.lastFrameTime = now;
    // Ein ausgelassenes GPU-Bild darf die Ringe nicht im nächsten Bild um
    // ein Zehntel Sekunde vorspringen lassen. Maximal ein 30-FPS-Schritt
    // wird sichtbar nachgeholt; Zeitlupe nach einem Hänger ist weniger
    // störend als ein harter Positionssprung.
    const delta = Math.min(rawDelta / 1000, 1 / 30);
    this.elapsed += delta;

    this.trackFrameTime(rawDelta);
    if (this.options.adaptiveQuality) {
      this.adaptQuality(delta);
    }

    this.callbacks.update(this.elapsed, delta);
    this.callbacks.render();
  }

  private trackFrameTime(frameTime: number): void {
    this.frameTimes.push(frameTime);
    if (this.frameTimes.length > 60) {
      this.frameTimes.shift();
    }
  }

  /**
   * Senkt oder erhöht die Qualität abhängig von der gemessenen Bildrate.
   *
   * Der Wechsel erfolgt bewusst träge (Abkühlzeit), damit die Darstellung
   * nicht ständig zwischen Stufen springt.
   */
  private adaptQuality(delta: number): void {
    this.qualityCooldown -= delta;
    if (this.qualityCooldown > 0 || this.frameTimes.length < 40) {
      return;
    }

    const measured = this.fps;
    const target = this.isIdle ? this.options.idleFps : this.options.targetFps;
    let nextLevel = this.qualityLevel;

    if (measured < target * 0.7 && this.qualityLevel > 0) {
      nextLevel = this.qualityLevel - 1;
    } else if (measured > target * 0.95 && this.qualityLevel < 2) {
      nextLevel = this.qualityLevel + 1;
    }

    if (nextLevel !== this.qualityLevel) {
      this.qualityLevel = nextLevel;
      this.qualityCooldown = 5;
      this.frameTimes = [];
      this.callbacks.onQualityChange?.(nextLevel);
    }
  }
}
