/**
 * states.ts – Die Zustandsmaschine des Orb.
 *
 * Der Orb besitzt die Zustände Idle, Listening, Thinking, Speaking, Busy,
 * Error und Sleep. Jeder Zustand hat eigene Farben, eine eigene
 * Geschwindigkeit, eigene Partikel, eine eigene Lichtstärke, eine eigene
 * Animation und eine eigene Aura.
 *
 * Übergänge erfolgen weich: Alle Werte werden über eine Übergangszeit
 * interpoliert, es gibt keine harten Wechsel.
 *
 * Dieses Modul kennt ausschließlich Zustände und deren Werte – es rendert
 * nichts und kennt weder Three.js noch das DOM.
 */

/** Die möglichen Zustände des Orb. */
export type OrbStateName =
  | "idle"
  | "listening"
  | "thinking"
  | "speaking"
  | "busy"
  | "error"
  | "sleep";

/** Alle Zustände in fester Reihenfolge. */
export const ORB_STATES: OrbStateName[] = [
  "idle",
  "listening",
  "thinking",
  "speaking",
  "busy",
  "error",
  "sleep",
];

/** Die visuellen Eigenschaften eines Zustands. */
export interface StateAppearance {
  /** Innere Kernfarbe als Hex-Zahl. */
  coreColor: number;
  /** Äußere Hüllen-/Glühfarbe als Hex-Zahl. */
  glowColor: number;
  /** Farbe der Partikel-Aura. */
  particleColor: number;
  /** Relative Animationsgeschwindigkeit (1.0 = normal). */
  speed: number;
  /** Intensität der Partikel (0.0 bis 1.0). */
  particleIntensity: number;
  /** Lichtstärke des Kerns. */
  lightIntensity: number;
  /** Stärke der Pulsation. */
  pulseAmount: number;
  /** Ausdehnung der Aura. */
  auraScale: number;
  /** Stärke des Bloom-Effekts. */
  bloomStrength: number;
  /**
   * Größe des Orb in diesem Zustand, relativ zur Grundgröße aus
   * `config.yaml` (`orb.scale`).
   *
   * Der Orb zieht sich zusammen, wenn er nichts zu tun hat, und richtet
   * sich auf, wenn er zuhört – wie ein Lebewesen, das aufmerkt. Die
   * Änderung läuft über dieselbe weiche Interpolation wie Farbe und
   * Geschwindigkeit; es gibt also keinen sichtbaren Sprung.
   */
  scale: number;

  /**
   * Wie stark der Nebel im Inneren wirbelt (Phase 14).
   *
   * Steuert die Verzerrung des Raums im Volumen-Shader. Niedrige Werte
   * ergeben langsame, breite Schwaden, hohe Werte enge Wirbel. Der
   * Unterschied zwischen Ruhe und Denken ist hier am deutlichsten zu
   * sehen.
   */
  smokeTurbulence: number;

  /** Wie dicht der Nebel ist. Höhere Werte wirken massiver. */
  smokeDensity: number;

  /**
   * Rhythmisches Atmen des Nebels beim Sprechen (0.0 bis 1.0).
   *
   * Nur im Sprechzustand über null – sonst wirkte der Orb, als spräche er
   * ständig.
   */
  smokePulse: number;

  /**
   * Warmer Warnschimmer im Fehlerzustand (0.0 bis 1.0).
   *
   * Bewusst als langsames Pulsieren umgesetzt und nicht als Blinken: Es
   * soll auffallen, ohne zu hetzen.
   */
  smokeWarning: number;
}

/** Ein Zustand mit Namen und Erscheinungsbild. */
export interface OrbState extends StateAppearance {
  name: OrbStateName;
}

/**
 * Die Farbpaletten der sechs vorbereiteten Themes.
 *
 * Jedes Theme liefert eine Basisfarbe und eine Akzentfarbe; die Zustände
 * leiten daraus ihre konkreten Farben ab. Dadurch bleiben alle Farben
 * zentral konfigurierbar.
 */
/**
 * Die Farbe, in der der Nebel beim Zuhören umschlägt.
 *
 * Bewusst unabhängig vom gewählten Theme: „Er hört zu" ist eine Auskunft
 * über den Zustand, keine Frage des Geschmacks. Wer sein Theme wechselt,
 * soll nicht neu lernen müssen, woran er das Zuhören erkennt.
 *
 * Rot, weil der Benutzer es so wollte – und weil es auf einen Blick
 * unmissverständlich ist: Rot heißt hier „ich nehme gerade auf", wie die
 * Aufnahmeleuchte an einer Kamera. Der Kern ist kräftig, der Schein hell,
 * damit die Kugel auch vor dunklem Hintergrund nicht bloß dunkelrot
 * absäuft.
 */
export const LISTENING_COLOR = { core: 0xff3b30, glow: 0xffc9c4 };

/**
 * Die Farbe beim Nachdenken.
 *
 * Ebenfalls rot, aber eine Spur tiefer und wärmer als beim Zuhören: Beide
 * Zustände sind auf einen Blick als „der Orb ist gerade beschäftigt"
 * erkennbar, lassen sich bei genauerem Hinsehen aber unterscheiden. Ein
 * einziges Rot für beides würde die Auskunft verschenken, welcher der
 * beiden Vorgänge gerade läuft.
 */
export const THINKING_COLOR = { core: 0xd81f26, glow: 0xff8a7a };

export const THEMES: Record<string, { base: number; accent: number; deep: number }> = {
  blue: { base: 0x4aa3ff, accent: 0xbfe4ff, deep: 0x0d3a72 },
  purple: { base: 0xa46bff, accent: 0xe2ccff, deep: 0x3a1a6b },
  green: { base: 0x3fdd90, accent: 0xc6ffe6, deep: 0x0c4a30 },
  red: { base: 0xff5f6d, accent: 0xffc9cd, deep: 0x6b1218 },
  white: { base: 0xdfe9f5, accent: 0xffffff, deep: 0x6d7d90 },
  cyber: { base: 0x00ffc8, accent: 0xff2fd0, deep: 0x081b2a },

  /**
   * Sand – die Farben des Wirbels, aus dem sich der Würfel bildet.
   *
   * Drei Werte, drei Aufgaben. `base` ist warmer Sand in der Sonne und
   * trägt die Kanten. `accent` ist fast weiss, aber nicht ganz: aufgewirbelte
   * Körner streuen Licht, sie leuchten nicht selbst – ein reines Weiss
   * sähe aus wie Funken, nicht wie Staub. `deep` ist nasser Sand im
   * Schatten und liegt hinten.
   *
   * Der Grünanteil liegt bewusst zwischen Rot und Blau statt auf halbem
   * Weg: Sand ohne diesen Zwischenschritt kippt ins Rosa und wirkt wie
   * Puder.
   */
  sand: { base: 0xd9a441, accent: 0xf3e0b8, deep: 0x4a3416 },

  /**
   * Neural – die Farben des atmenden Nervenkerns.
   *
   * Drei Werte, drei Aufgaben. `base` ist das Blaugrün im Inneren und
   * trägt die Fäden dort, wo sie am dichtesten liegen. `accent` ist ein
   * warmes Weiss, kein reines: Reines Weiss wirkt wie ein Scheinwerfer,
   * ein warmes wie Licht, das aus etwas Lebendigem kommt. `deep` ist das
   * Violett des Übergangs und liegt zwischen beiden.
   *
   * Der Kern mischt daraus seinen Verlauf von innen nach aussen. Beim
   * Arbeiten ersetzt der Zustand `base` und `accent` durch Rot, und der
   * Verlauf wird zu einem Purpur – die Farbe bleibt damit eine Auskunft
   * und wird nicht zum Schmuck.
   */
  neural: { base: 0x35e0ff, accent: 0xfff0e0, deep: 0x6b3fd4 },

  /**
   * Neon – die Farben des pulsierenden O.
   *
   * Neon ist keine bestimmte Farbe, sondern eine Machart: voll gesättigt,
   * hell, und in eine dunkle Umgebung ausblutend. Was dieses Theme
   * beiträgt, ist deshalb vor allem der FARBTON, um den herum sich das
   * Band spannt – Sättigung und Helligkeit setzt der Ring selbst, sonst
   * ergäbe ein blasses Theme ein blasses O.
   *
   * `base` ist das Neonblau der Mitte, `accent` das Magenta am äusseren
   * Ende des Bandes, `deep` das Violett dazwischen.
   */
  neon: { base: 0x00e5ff, accent: 0xff2fd0, deep: 0x7a00ff },
};

/**
 * Erzeugt die Zustandsdefinitionen für ein Theme.
 *
 * @param themeName Name des Themes aus {@link THEMES}.
 * @param overrides Werte aus `config.yaml` (Abschnitt `states`), die die
 *   Vorgaben überschreiben.
 * @returns Alle Zustände mit ihrem Erscheinungsbild.
 */
export function buildStates(
  themeName: string,
  overrides: Record<string, Partial<StateAppearance>> = {}
): Record<OrbStateName, OrbState> {
  const theme = THEMES[themeName] ?? THEMES.blue;

  const defaults: Record<OrbStateName, StateAppearance> = {
    idle: {
      coreColor: theme.base,
      glowColor: theme.accent,
      particleColor: theme.accent,
      speed: 1.0,
      particleIntensity: 0.4,
      lightIntensity: 1.0,
      pulseAmount: 0.05,
      auraScale: 1.0,
      bloomStrength: 1.0,
      // Ruhezustand: Der Orb zieht sich etwas zusammen.
      scale: 0.88,
      smokeTurbulence: 0.35,
      smokeDensity: 0.85,
      smokePulse: 0.0,
      smokeWarning: 0.0,
    },
    listening: {
      // Zuhören zeigt sich in der Farbe, nicht in der Bewegung.
      //
      // Vorher pulsierte der ganze Orb (pulseAmount 0.1) und wechselte
      // nur zwischen zwei Tönen desselben Themes – aus der Entfernung ein
      // Zittern und sonst nichts. Zittern liest sich aber als Nervosität
      // oder als Fehler, nicht als Aufmerksamkeit.
      //
      // Jetzt schlägt der Nebel im Inneren deutlich in einen anderen Ton
      // um: ruhiges Türkisgrün, unabhängig vom eingestellten Theme, damit
      // "er hört zu" immer gleich aussieht. Die Bewegung bleibt innen –
      // der Nebel zieht schneller –, die Hülle steht still.
      coreColor: LISTENING_COLOR.core,
      glowColor: LISTENING_COLOR.glow,
      particleColor: LISTENING_COLOR.glow,
      speed: 1.35,
      particleIntensity: 0.75,
      lightIntensity: 1.3,
      // Kein Pulsieren der Hülle. Das war das Zittern.
      pulseAmount: 0.0,
      auraScale: 1.15,
      bloomStrength: 1.25,
      // Zuhören: Der Orb richtet sich auf und wirkt aufmerksam.
      scale: 1.14,
      // Der Nebel wirbelt lebhafter – die Bewegung wandert nach innen.
      smokeTurbulence: 1.15,
      smokeDensity: 1.15,
      smokePulse: 0.0,
      smokeWarning: 0.0,
    },
    thinking: {
      // Wie beim Zuhören themeunabhängig: Der Zustand soll immer gleich
      // aussehen, gleich welches Theme eingestellt ist.
      coreColor: THINKING_COLOR.core,
      glowColor: THINKING_COLOR.glow,
      particleColor: THINKING_COLOR.core,
      speed: 1.6,
      particleIntensity: 0.9,
      lightIntensity: 1.1,
      pulseAmount: 0.14,
      auraScale: 1.08,
      bloomStrength: 1.15,
      scale: 1.04,
      smokeTurbulence: 1.55,
      smokeDensity: 1.15,
      smokePulse: 0.0,
      smokeWarning: 0.0,
    },
    speaking: {
      coreColor: theme.accent,
      glowColor: theme.accent,
      particleColor: theme.accent,
      speed: 1.5,
      particleIntensity: 1.0,
      lightIntensity: 1.4,
      pulseAmount: 0.18,
      auraScale: 1.2,
      bloomStrength: 1.35,
      scale: 1.08,
      smokeTurbulence: 0.95,
      smokeDensity: 1.1,
      smokePulse: 1.0,
      smokeWarning: 0.0,
    },
    busy: {
      // Auch beim Arbeiten rot – und aus demselben Grund wie beim Denken:
      //
      // „Beschäftigt" ist die Auskunft, auf die es ankommt. Blieb der Orb
      // hier blau, sah Arbeiten aus wie Nichtstun, und man fragte sich, ob
      // die Anweisung überhaupt angekommen ist. Der Nebel wirbelt dabei
      // kräftiger als beim Denken: Es ist derselbe Zustand, nur mit mehr
      // Getriebe dahinter.
      coreColor: THINKING_COLOR.core,
      glowColor: THINKING_COLOR.glow,
      particleColor: THINKING_COLOR.core,
      speed: 1.2,
      particleIntensity: 0.6,
      lightIntensity: 1.05,
      pulseAmount: 0.08,
      auraScale: 1.02,
      bloomStrength: 1.0,
      scale: 0.98,
      smokeTurbulence: 1.05,
      smokeDensity: 0.95,
      smokePulse: 0.0,
      smokeWarning: 0.0,
    },
    error: {
      coreColor: 0xff4a4a,
      glowColor: 0xffb3b3,
      particleColor: 0xff6b6b,
      speed: 0.8,
      particleIntensity: 0.5,
      lightIntensity: 0.9,
      pulseAmount: 0.22,
      auraScale: 0.95,
      bloomStrength: 0.9,
      scale: 0.95,
      smokeTurbulence: 0.5,
      smokeDensity: 0.9,
      smokePulse: 0.0,
      smokeWarning: 1.0,
    },
    sleep: {
      coreColor: theme.deep,
      glowColor: theme.base,
      particleColor: theme.deep,
      speed: 0.25,
      particleIntensity: 0.1,
      lightIntensity: 0.35,
      pulseAmount: 0.03,
      auraScale: 0.85,
      bloomStrength: 0.5,
      // Schlaf: deutlich kleiner, damit er kaum auffällt.
      scale: 0.62,
      smokeTurbulence: 0.15,
      smokeDensity: 0.5,
      smokePulse: 0.0,
      smokeWarning: 0.0,
    },
  };

  const result = {} as Record<OrbStateName, OrbState>;
  for (const name of ORB_STATES) {
    result[name] = { name, ...defaults[name], ...(overrides[name] ?? {}) };
  }
  return result;
}

/** Interpoliert zwei Zahlen linear. */
function lerp(from: number, to: number, amount: number): number {
  return from + (to - from) * amount;
}

/** Interpoliert zwei Farben komponentenweise. */
function lerpColor(from: number, to: number, amount: number): number {
  const fromR = (from >> 16) & 0xff;
  const fromG = (from >> 8) & 0xff;
  const fromB = from & 0xff;
  const toR = (to >> 16) & 0xff;
  const toG = (to >> 8) & 0xff;
  const toB = to & 0xff;

  const r = Math.round(lerp(fromR, toR, amount));
  const g = Math.round(lerp(fromG, toG, amount));
  const b = Math.round(lerp(fromB, toB, amount));
  return (r << 16) | (g << 8) | b;
}

/** Weiche Ease-in-out-Kurve für Zustandsübergänge. */
function easeInOut(t: number): number {
  return t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
}

/**
 * Verwaltet den aktuellen Zustand des Orb und blendet zwischen Zuständen
 * weich über.
 */
export class StateMachine {
  private states: Record<OrbStateName, OrbState>;
  private currentName: OrbStateName = "idle";
  private fromAppearance: StateAppearance;
  private toAppearance: StateAppearance;
  private blended: StateAppearance;
  private transitionElapsed = 0;
  private transitionDuration: number;
  private listeners: ((state: OrbStateName) => void)[] = [];

  /**
   * @param themeName Aktives Theme.
   * @param overrides Zustandswerte aus `config.yaml`.
   * @param transitionSeconds Dauer eines Zustandsübergangs.
   */
  constructor(
    themeName: string,
    overrides: Record<string, Partial<StateAppearance>> = {},
    transitionSeconds = 0.9
  ) {
    this.states = buildStates(themeName, overrides);
    this.transitionDuration = Math.max(0.05, transitionSeconds);
    this.fromAppearance = { ...this.states.idle };
    this.toAppearance = { ...this.states.idle };
    this.blended = { ...this.states.idle };
    this.transitionElapsed = this.transitionDuration;
  }

  /** Der aktuell angestrebte Zustand. */
  public get current(): OrbStateName {
    return this.currentName;
  }

  /** Ob gerade ein Übergang läuft. */
  public get isTransitioning(): boolean {
    return this.transitionElapsed < this.transitionDuration;
  }

  /** Die aktuell wirksamen (interpolierten) Werte. */
  public get appearance(): StateAppearance {
    return this.blended;
  }

  /**
   * Wechselt in einen neuen Zustand. Ein erneuter Wechsel in denselben
   * Zustand wird ignoriert, damit laufende Übergänge nicht zurückspringen.
   */
  public setState(name: OrbStateName): void {
    if (name === this.currentName || !this.states[name]) {
      return;
    }
    this.fromAppearance = { ...this.blended };
    this.toAppearance = { ...this.states[name] };
    this.transitionElapsed = 0;
    this.currentName = name;
    for (const listener of this.listeners) {
      listener(name);
    }
  }

  /** Registriert einen Callback für Zustandswechsel. */
  public onChange(listener: (state: OrbStateName) => void): void {
    this.listeners.push(listener);
  }

  /**
   * Aktualisiert die Interpolation.
   *
   * @param delta Vergangene Zeit seit dem letzten Bild in Sekunden.
   */
  public update(delta: number): void {
    if (this.transitionElapsed >= this.transitionDuration) {
      this.blended = { ...this.toAppearance };
      return;
    }

    this.transitionElapsed = Math.min(
      this.transitionDuration,
      this.transitionElapsed + delta
    );
    const amount = easeInOut(this.transitionElapsed / this.transitionDuration);

    this.blended = {
      coreColor: lerpColor(this.fromAppearance.coreColor, this.toAppearance.coreColor, amount),
      glowColor: lerpColor(this.fromAppearance.glowColor, this.toAppearance.glowColor, amount),
      particleColor: lerpColor(
        this.fromAppearance.particleColor,
        this.toAppearance.particleColor,
        amount
      ),
      speed: lerp(this.fromAppearance.speed, this.toAppearance.speed, amount),
      particleIntensity: lerp(
        this.fromAppearance.particleIntensity,
        this.toAppearance.particleIntensity,
        amount
      ),
      lightIntensity: lerp(
        this.fromAppearance.lightIntensity,
        this.toAppearance.lightIntensity,
        amount
      ),
      pulseAmount: lerp(this.fromAppearance.pulseAmount, this.toAppearance.pulseAmount, amount),
      auraScale: lerp(this.fromAppearance.auraScale, this.toAppearance.auraScale, amount),
      bloomStrength: lerp(
        this.fromAppearance.bloomStrength,
        this.toAppearance.bloomStrength,
        amount
      ),
      scale: lerp(this.fromAppearance.scale, this.toAppearance.scale, amount),
      smokeTurbulence: lerp(
        this.fromAppearance.smokeTurbulence,
        this.toAppearance.smokeTurbulence,
        amount
      ),
      smokeDensity: lerp(
        this.fromAppearance.smokeDensity,
        this.toAppearance.smokeDensity,
        amount
      ),
      smokePulse: lerp(this.fromAppearance.smokePulse, this.toAppearance.smokePulse, amount),
      smokeWarning: lerp(
        this.fromAppearance.smokeWarning,
        this.toAppearance.smokeWarning,
        amount
      ),
    };
  }

  /** Wechselt das Theme zur Laufzeit, ohne den Zustand zu verlieren. */
  public setTheme(themeName: string, overrides: Record<string, Partial<StateAppearance>> = {}): void {
    this.states = buildStates(themeName, overrides);
    this.fromAppearance = { ...this.blended };
    this.toAppearance = { ...this.states[this.currentName] };
    this.transitionElapsed = 0;
  }
}
