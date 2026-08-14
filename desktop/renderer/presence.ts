/**
 * presence.ts – Die Präsenz-Engine des Orb.
 *
 * Der Orb lebt: Er besitzt eine leichte Eigenbewegung, eine Atmung, eine
 * Neigung, kleine Zufallsbewegungen und Mikrobewegungen. Er steht niemals
 * vollkommen still.
 *
 * Alle Werte sind bewusst klein gehalten – die Bewegung soll wahrnehmbar,
 * aber nicht störend sein.
 */

import * as THREE from "three";

/** Parameter der Eigenbewegung. */
export interface PresenceOptions {
  /** Ausschlag der Schwebebewegung in Weltkoordinaten. */
  floatAmplitude: number;
  /** Geschwindigkeit der Schwebebewegung. */
  floatSpeed: number;
  /** Stärke der Atembewegung (Skalierung). */
  breathAmount: number;
  /** Geschwindigkeit der Atembewegung. */
  breathSpeed: number;
  /** Maximale Neigung in Radiant. */
  tiltAmount: number;
  /** Stärke der zufälligen Mikrobewegungen. */
  driftAmount: number;
}

/** Voreinstellungen für die Präsenz-Engine. */
export const DEFAULT_PRESENCE: PresenceOptions = {
  floatAmplitude: 0.055,
  floatSpeed: 0.55,
  breathAmount: 0.022,
  breathSpeed: 0.85,
  tiltAmount: 0.06,
  driftAmount: 0.03,
};

/**
 * Erzeugt die kontinuierliche Eigenbewegung des Orb.
 */
export class PresenceEngine {
  private options: PresenceOptions;
  private enabled: boolean;

  private driftTarget = new THREE.Vector2(0, 0);
  private driftCurrent = new THREE.Vector2(0, 0);
  private nextDriftIn = 0;

  private offset = new THREE.Vector3();

  /**
   * @param options Bewegungsparameter.
   * @param enabled Ob die Eigenbewegung aktiv ist (aus `config.yaml`).
   */
  constructor(options: Partial<PresenceOptions> = {}, enabled = true) {
    this.options = { ...DEFAULT_PRESENCE, ...options };
    this.enabled = enabled;
  }

  /** Schaltet die Eigenbewegung ein oder aus. */
  public setEnabled(enabled: boolean): void {
    this.enabled = enabled;
  }

  /**
   * Aktualisiert die Eigenbewegung und wendet sie auf eine Gruppe an.
   *
   * @param group Die Orb-Gruppe.
   * @param elapsed Gesamtlaufzeit in Sekunden.
   * @param delta Zeit seit dem letzten Bild in Sekunden.
   * @param speed Geschwindigkeitsfaktor des aktuellen Zustands.
   */
  public update(
    group: THREE.Object3D,
    elapsed: number,
    delta: number,
    speed: number
  ): void {
    if (!this.enabled) {
      return;
    }

    // --- Schweben ---------------------------------------------------------
    const float = Math.sin(elapsed * this.options.floatSpeed * speed) * this.options.floatAmplitude;
    const sway =
      Math.cos(elapsed * this.options.floatSpeed * 0.63 * speed) *
      this.options.floatAmplitude *
      0.6;

    // --- Zufällige Mikrobewegungen ----------------------------------------
    this.nextDriftIn -= delta;
    if (this.nextDriftIn <= 0) {
      this.driftTarget.set(
        (Math.random() - 0.5) * 2 * this.options.driftAmount,
        (Math.random() - 0.5) * 2 * this.options.driftAmount
      );
      // Neue Zufallsbewegung alle 2 bis 6 Sekunden.
      this.nextDriftIn = 2 + Math.random() * 4;
    }
    // Sehr langsames Nachziehen, damit keine Sprünge entstehen.
    this.driftCurrent.lerp(this.driftTarget, Math.min(1, delta * 0.6));

    this.offset.set(sway + this.driftCurrent.x, float + this.driftCurrent.y, 0);
    group.position.copy(this.offset);

    // --- Neigung ------------------------------------------------------------
    group.rotation.z = Math.sin(elapsed * 0.31 * speed) * this.options.tiltAmount;
    // Absolut setzen, nicht pro Bild addieren. Das frühere `+=` summierte
    // winzige Werte über Tausende Frames auf und erzeugte dadurch ein
    // langsames Wegdriften mit sichtbaren Korrektursprüngen.
    group.rotation.x =
      Math.sin(elapsed * 0.23 * speed) * this.options.tiltAmount * 0.28;
  }

  /**
   * Liefert den Atem-Skalierungsfaktor.
   *
   * Wird getrennt von der Position angewendet, damit Zustandspulsation und
   * Atmung sich überlagern können.
   *
   * @param elapsed Gesamtlaufzeit in Sekunden.
   * @returns Ein Faktor um 1.0 herum.
   */
  public breathScale(elapsed: number): number {
    if (!this.enabled) {
      return 1.0;
    }
    return 1.0 + Math.sin(elapsed * this.options.breathSpeed) * this.options.breathAmount;
  }

  /** Die aktuelle Verschiebung durch die Eigenbewegung. */
  public get currentOffset(): THREE.Vector3 {
    return this.offset;
  }
}
