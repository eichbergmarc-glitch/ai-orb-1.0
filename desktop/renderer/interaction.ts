/**
 * interaction.ts – Die Benutzerinteraktion mit dem Orb.
 *
 * - **Linksklick**: Orb aktivieren
 * - **Rechtsklick**: Kontextmenü
 * - **Hover**: Glow verstärken
 * - **Drag**: Fenster verschieben
 * - **Doppelklick**: konfigurierbare Aktion
 *
 * Das Modul kennt ausschließlich Eingabeereignisse und meldet sie über
 * Callbacks weiter. Es rendert nichts und verändert keine Fenster.
 */

/** Die Callbacks, die auf Interaktionen reagieren. */
export interface InteractionHandlers {
  /** Linksklick auf den Orb (ohne vorheriges Ziehen). */
  onActivate: () => void;
  /** Rechtsklick auf den Orb. */
  onContextMenu: () => void;
  /** Doppelklick auf den Orb. */
  onDoubleClick: () => void;
  /** Beginn einer Ziehbewegung. */
  onDragStart: () => void;
  /** Fortlaufende Ziehbewegung mit Verschiebung seit dem letzten Ereignis. */
  onDrag: (deltaX: number, deltaY: number) => void;
  /** Ende einer Ziehbewegung. */
  onDragEnd: () => void;
  /** Der Zeiger befindet sich über dem Orb (oder verlässt ihn). */
  onHover: (hovering: boolean) => void;
}

/** Optionen der Interaktionserkennung. */
export interface InteractionOptions {
  /**
   * Radius um die Orb-Mitte, innerhalb dessen ein Klick als Treffer gilt.
   *
   * Als Funktion angegeben, weil der Orb je nach Zustand seine Größe
   * ändert: Im Ruhezustand ist er kleiner, beim Zuhören größer. Die
   * Trefferfläche folgt dieser Änderung.
   */
  hitRadius: number | (() => number);
  /** Ab dieser Verschiebung gilt eine Bewegung als Ziehen, nicht als Klick. */
  dragThreshold: number;
}

/**
 * Wertet Maus- und Zeigerereignisse aus und ordnet sie den Interaktionen zu.
 */
export class InteractionController {
  private element: HTMLElement;
  private handlers: InteractionHandlers;
  private options: InteractionOptions;

  private isPointerDown = false;
  private isDragging = false;
  private hovering = false;
  private orbOffset = { x: 0, y: 0 };
  private downPosition = { x: 0, y: 0 };
  private lastPosition = { x: 0, y: 0 };
  private lastClickAt = 0;
  private enabled = true;

  /**
   * @param element Das Element, das die Ereignisse empfängt (das Canvas).
   * @param handlers Die Reaktionen auf die Interaktionen.
   * @param options Erkennungsparameter.
   */
  constructor(
    element: HTMLElement,
    handlers: InteractionHandlers,
    options: Partial<InteractionOptions> = {}
  ) {
    this.element = element;
    this.handlers = handlers;
    this.options = {
      hitRadius: options.hitRadius ?? 80,
      dragThreshold: options.dragThreshold ?? 4,
    };

    this.attach();
  }

  /** Aktiviert oder deaktiviert die Interaktion (z. B. im Schlafzustand). */
  public setEnabled(enabled: boolean): void {
    this.enabled = enabled;
    if (!enabled && this.hovering) {
      this.hovering = false;
      this.handlers.onHover(false);
    }
  }

  /** Ob der Zeiger sich gerade über dem Orb befindet. */
  public get isHovering(): boolean {
    return this.hovering;
  }

  /**
   * Prüft, ob eine Position innerhalb des Orb liegt.
   *
   * Da das Fenster größer ist als der sichtbare Orb, wäre ein Treffer im
   * gesamten Fenster irreführend – geprüft wird daher der Abstand zur
   * Fenstermitte.
   */
  private isOverOrb(clientX: number, clientY: number): boolean {
    const centerX = window.innerWidth / 2 + this.orbOffset.x;
    const centerY = window.innerHeight / 2 + this.orbOffset.y;
    const distance = Math.hypot(clientX - centerX, clientY - centerY);

    const radius =
      typeof this.options.hitRadius === "function"
        ? this.options.hitRadius()
        : this.options.hitRadius;

    // Ein Mindestradius sorgt dafür, dass der Orb auch im kleinsten
    // Zustand (Schlaf) noch bequem anklickbar bleibt.
    return distance <= Math.max(28, radius);
  }

  /**
   * Teilt der Erkennung mit, wo der Orb sich gerade im Fenster befindet.
   *
   * Der Orb bewegt sich innerhalb des Fensters; ohne diese Angabe würde
   * die Trefferfläche an der Fenstermitte kleben.
   */
  public setOrbOffset(x: number, y: number): void {
    this.orbOffset = { x, y };
  }

  private attach(): void {
    this.element.addEventListener("pointerdown", (event) => this.handlePointerDown(event));
    window.addEventListener("pointermove", (event) => this.handlePointerMove(event));
    window.addEventListener("pointerup", (event) => this.handlePointerUp(event));
    this.element.addEventListener("contextmenu", (event) => this.handleContextMenu(event));
    this.element.addEventListener("pointerleave", () => {
      if (this.hovering && !this.isDragging) {
        this.hovering = false;
        this.handlers.onHover(false);
      }
    });
  }

  private handlePointerDown(event: PointerEvent): void {
    if (!this.enabled || event.button !== 0) {
      return;
    }
    if (!this.isOverOrb(event.clientX, event.clientY)) {
      return;
    }

    this.isPointerDown = true;
    this.isDragging = false;
    this.downPosition = { x: event.screenX, y: event.screenY };
    this.lastPosition = { x: event.screenX, y: event.screenY };
  }

  private handlePointerMove(event: PointerEvent): void {
    if (!this.enabled) {
      return;
    }

    // --- Hover ----------------------------------------------------------
    if (!this.isPointerDown) {
      const over = this.isOverOrb(event.clientX, event.clientY);
      if (over !== this.hovering) {
        this.hovering = over;
        this.handlers.onHover(over);
      }
      return;
    }

    // --- Ziehen -----------------------------------------------------------
    const totalX = event.screenX - this.downPosition.x;
    const totalY = event.screenY - this.downPosition.y;

    if (!this.isDragging && Math.hypot(totalX, totalY) > this.options.dragThreshold) {
      this.isDragging = true;
      this.handlers.onDragStart();
    }

    if (this.isDragging) {
      const deltaX = event.screenX - this.lastPosition.x;
      const deltaY = event.screenY - this.lastPosition.y;
      this.lastPosition = { x: event.screenX, y: event.screenY };
      if (deltaX !== 0 || deltaY !== 0) {
        this.handlers.onDrag(deltaX, deltaY);
      }
    }
  }

  private handlePointerUp(event: PointerEvent): void {
    if (!this.enabled || !this.isPointerDown) {
      return;
    }
    this.isPointerDown = false;

    if (this.isDragging) {
      this.isDragging = false;
      this.handlers.onDragEnd();
      return;
    }

    if (!this.isOverOrb(event.clientX, event.clientY)) {
      return;
    }

    // --- Doppelklick erkennen ---------------------------------------------
    const now = performance.now();
    if (now - this.lastClickAt < 350) {
      this.lastClickAt = 0;
      this.handlers.onDoubleClick();
      return;
    }
    this.lastClickAt = now;

    // Der Einzelklick wird erst ausgelöst, wenn feststeht, dass kein
    // zweiter Klick folgt.
    window.setTimeout(() => {
      if (this.lastClickAt !== 0 && performance.now() - this.lastClickAt >= 340) {
        this.lastClickAt = 0;
        this.handlers.onActivate();
      }
    }, 360);
  }

  private handleContextMenu(event: MouseEvent): void {
    event.preventDefault();
    if (!this.enabled || !this.isOverOrb(event.clientX, event.clientY)) {
      return;
    }
    this.handlers.onContextMenu();
  }
}
