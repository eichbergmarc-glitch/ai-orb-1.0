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

/** Die möglichen Zustände des Orb.
 *
 * Die ersten sieben sind die bestehenden Namen, die das Backend seit jeher
 * meldet - sie bleiben unverändert gültig. Die fünf neuen kommen mit dem
 * Energy-Orb dazu: executing, waiting, success, warning, offline.
 */
export type OrbStateName =
  | "idle"
  | "listening"
  | "thinking"
  | "speaking"
  | "busy"
  | "error"
  | "sleep"
  | "executing"
  | "waiting"
  | "success"
  | "warning"
  | "offline";

/** Alle Zustände in fester Reihenfolge. */
export const ORB_STATES: OrbStateName[] = [
  "idle",
  "listening",
  "thinking",
  "speaking",
  "busy",
  "error",
  "sleep",
  "executing",
  "waiting",
  "success",
  "warning",
  "offline",
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

  // --- Energy-Orb: die neuen, ebenfalls weich interpolierten Werte --------

  /** Tempo der Energiebahnen (1.0 = ruhig). */
  ringSpeed: number;
  /** Helligkeit der Energiebahnen. */
  ringIntensity: number;
  /** Tempo der Partikel auf den Bahnen. */
  particleSpeed: number;
  /** Wie stark die innere Plasmaschicht arbeitet. */
  energyFlow: number;
  /** Zusätzliches Glühen des Kerns. */
  coreGlow: number;
  /** Augen: Öffnung/Größe (1.0 = normal, 0 = geschlossen). */
  eyeOpen: number;
  /** Augen: unterer Bogen – freundlicher Ausdruck (0..1). */
  eyeHappy: number;
  /** Augen: oben abgeflacht – fokussiert (0..1). */
  eyeSquint: number;
  /** Augen: nach innen geneigt – Fehlerausdruck (0..1). */
  eyeAngry: number;
  /** Augen: Leuchtkraft (1.0 = normal, gedimmt < 0.5). */
  eyeBright: number;
  /** Blendet die Augen in ein Fragezeichen um (Warten auf Eingabe). */
  eyeQuestion: number;
  /** Blendet die Augen in ein Ausrufezeichen um (Warnung). */
  eyeAlert: number;
  /** Leichte Asymmetrie und angehobener Blick (Neugier). */
  eyeCurious: number;
  /** Weit geöffneter, runder Ausdruck (Überraschung). */
  eyeSurprised: number;
  /** Gegensinnige Augenhöhe (Unsicherheit/Nachdenklichkeit). */
  eyeUncertain: number;
}

/**
 * Die Energy-Orb-Vorgaben, mit denen ALTE Zustandsdefinitionen (etwa
 * Überschreibungen aus einer config.yaml von vor dem Umbau) aufgefüllt
 * werden. So kann eine unvollständige Überschreibung die Anzeige nicht
 * kaputtmachen.
 */
const ENERGY_DEFAULTS = {
  ringSpeed: 1.0,
  ringIntensity: 1.0,
  particleSpeed: 1.0,
  energyFlow: 1.0,
  coreGlow: 0.6,
  eyeOpen: 1.0,
  eyeHappy: 0.0,
  eyeSquint: 0.0,
  eyeAngry: 0.0,
  eyeBright: 1.0,
  eyeQuestion: 0.0,
  eyeAlert: 0.0,
  eyeCurious: 0.0,
  eyeSurprised: 0.0,
  eyeUncertain: 0.0,
} as const;

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
 * Grün, nach dem Referenzbild des Energy-Orb-Umbaus: Grün heißt hier
 * „ich höre dich" – aufmerksam und freundlich, nicht alarmiert. Der Kern
 * ist kräftig, der Schein hell, damit die Kugel auch vor dunklem
 * Hintergrund nicht absäuft.
 */
export const LISTENING_COLOR = { core: 0x2fd06a, glow: 0xa8ffcd };

/**
 * Die Farbe beim Nachdenken.
 *
 * Violett, nach dem Referenzbild: Denken ist sichtbar etwas anderes als
 * Zuhören (grün) und Arbeiten (orange). Ein einziger Farbton für alles
 * würde die Auskunft verschenken, welcher Vorgang gerade läuft.
 */
export const THINKING_COLOR = { core: 0x8a4dff, glow: 0xd3b4ff };

export const THEMES: Record<string, { base: number; accent: number; deep: number }> = {
  blue: { base: 0x4aa3ff, accent: 0xbfe4ff, deep: 0x0d3a72 },
  purple: { base: 0xa46bff, accent: 0xe2ccff, deep: 0x3a1a6b },
  green: { base: 0x3fdd90, accent: 0xc6ffe6, deep: 0x0c4a30 },
  yellow: { base: 0xffd327, accent: 0xfff3a6, deep: 0x6b4e05 },
  orange: { base: 0xff921f, accent: 0xffd09a, deep: 0x692400 },
  pink: { base: 0xff3ca6, accent: 0xffbde1, deep: 0x68103f },
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

  // Die Zustandsfarben folgen dem Referenzbild des Energy-Orb: Zuhören ist
  // grün, Denken violett, Arbeiten orange, Erfolg grün mit freundlichen
  // Augen, Warnung bernstein, Fehler rot, Offline grau. Die Farben sind
  // eine Auskunft über den Zustand und deshalb themeunabhängig; nur Ruhe-
  // und Sprechzustand tragen das gewählte Theme.
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
      // Ruhig genug, um es stundenlang anzusehen: langsame Bahnen, wenig
      // Partikel, schwaches Leuchten. "Er wartet entspannt."
      ringSpeed: 0.6,
      ringIntensity: 0.7,
      particleSpeed: 0.6,
      energyFlow: 0.65,
      coreGlow: 0.5,
      eyeOpen: 1.0,
      eyeHappy: 0.0,
      eyeSquint: 0.0,
      eyeAngry: 0.0,
      eyeBright: 0.9,
      eyeQuestion: 0.0,
      eyeAlert: 0.0,
      eyeCurious: 0.18,
      eyeSurprised: 0.0,
      eyeUncertain: 0.0,
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
      scale: 1.08,
      // Der Nebel wirbelt lebhafter – die Bewegung wandert nach innen.
      smokeTurbulence: 1.15,
      smokeDensity: 1.15,
      smokePulse: 0.0,
      smokeWarning: 0.0,
      // Weich beschleunigt, Augen größer und aufmerksamer.
      ringSpeed: 1.1,
      ringIntensity: 1.0,
      particleSpeed: 1.15,
      energyFlow: 1.0,
      coreGlow: 0.8,
      // Wie in der Referenz: schmale, nach innen geneigte Augen. Der Orb
      // wirkt konzentriert auf die Stimme und nicht bloss ueberrascht.
      eyeOpen: 0.68,
      eyeHappy: 0.0,
      eyeSquint: 0.72,
      eyeAngry: 0.72,
      eyeBright: 1.15,
      eyeQuestion: 0.0,
      eyeAlert: 0.0,
      eyeCurious: 0.0,
      eyeSurprised: 0.0,
      eyeUncertain: 0.0,
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
      // "Energie wird intern verarbeitet": Plasma und Kern arbeiten
      // sichtbar, die Bahnen laufen schneller, einzelne werden heller.
      ringSpeed: 1.5,
      ringIntensity: 1.15,
      particleSpeed: 1.5,
      energyFlow: 1.5,
      coreGlow: 0.95,
      eyeOpen: 0.72,
      eyeHappy: 0.68,
      eyeSquint: 0.22,
      eyeAngry: 0.0,
      eyeBright: 1.0,
      eyeQuestion: 0.0,
      eyeAlert: 0.0,
      eyeCurious: 0.0,
      eyeSurprised: 0.0,
      eyeUncertain: 0.55,
    },
    speaking: {
      coreColor: theme.base,
      glowColor: theme.accent,
      particleColor: theme.accent,
      speed: 1.5,
      particleIntensity: 1.0,
      lightIntensity: 1.4,
      pulseAmount: 0.18,
      auraScale: 1.2,
      bloomStrength: 1.35,
      scale: 1.05,
      smokeTurbulence: 0.95,
      smokeDensity: 1.1,
      smokePulse: 1.0,
      smokeWarning: 0.0,
      ringSpeed: 1.2,
      ringIntensity: 1.1,
      particleSpeed: 1.2,
      energyFlow: 1.2,
      coreGlow: 0.9,
      eyeOpen: 1.05,
      eyeHappy: 0.25,
      eyeSquint: 0.0,
      eyeAngry: 0.0,
      eyeBright: 1.1,
      eyeQuestion: 0.0,
      eyeAlert: 0.0,
      eyeCurious: 0.0,
      eyeSurprised: 0.0,
      eyeUncertain: 0.0,
    },
    busy: {
      // Auch beim Arbeiten rot – und aus demselben Grund wie beim Denken:
      //
      // „Beschäftigt" ist die Auskunft, auf die es ankommt. Blieb der Orb
      // hier blau, sah Arbeiten aus wie Nichtstun, und man fragte sich, ob
      // die Anweisung überhaupt angekommen ist. Der Nebel wirbelt dabei
      // kräftiger als beim Denken: Es ist derselbe Zustand, nur mit mehr
      // Getriebe dahinter.
      // busy = die Drag-/Übergangsvariante des Arbeitens: dieselbe
      // Orange-Energie wie executing, nur eine Spur zurückgenommen.
      coreColor: 0xff8a2f,
      glowColor: 0xffc891,
      particleColor: 0xffb35c,
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
      ringSpeed: 1.4,
      ringIntensity: 1.1,
      particleSpeed: 1.4,
      energyFlow: 1.25,
      coreGlow: 0.8,
      // Beim Arbeiten dominiert die orange Energie. Die Augen ziehen sich
      // fast ganz zurueck, genau wie in der Referenzsequenz.
      eyeOpen: 0.08,
      eyeHappy: 0.0,
      eyeSquint: 0.3,
      eyeAngry: 0.0,
      eyeBright: 1.0,
      eyeQuestion: 0.0,
      eyeAlert: 0.0,
      eyeCurious: 0.0,
      eyeSurprised: 0.0,
      eyeUncertain: 0.12,
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
      // Deutlich anders, aber weiterhin minimalistisch: geneigte,
      // schmalere Augen, ruhiger Energiefluss - kein hektisches Blinken.
      ringSpeed: 0.7,
      ringIntensity: 0.8,
      particleSpeed: 0.7,
      energyFlow: 0.8,
      coreGlow: 0.7,
      eyeOpen: 0.62,
      eyeHappy: 0.0,
      eyeSquint: 0.72,
      eyeAngry: 1.0,
      eyeBright: 1.1,
      eyeQuestion: 0.0,
      eyeAlert: 0.0,
      eyeCurious: 0.0,
      eyeSurprised: 0.0,
      eyeUncertain: 0.0,
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
      ringSpeed: 0.25,
      ringIntensity: 0.3,
      particleSpeed: 0.25,
      energyFlow: 0.3,
      coreGlow: 0.25,
      // Augen geschlossen - er schläft.
      eyeOpen: 0.05,
      eyeHappy: 0.85,
      eyeSquint: 0.0,
      eyeAngry: 0.0,
      eyeBright: 0.35,
      eyeQuestion: 0.0,
      eyeAlert: 0.0,
      eyeCurious: 0.0,
      eyeSurprised: 0.0,
      eyeUncertain: 0.0,
    },

    // --- Die fünf neuen Zustände des Energy-Orb ---------------------------

    executing: {
      // Orange Energie, die nach außen fließt: "Der Orb arbeitet gerade."
      coreColor: 0xff8a2f,
      glowColor: 0xffd9a8,
      particleColor: 0xffb35c,
      speed: 1.7,
      particleIntensity: 1.0,
      lightIntensity: 1.25,
      pulseAmount: 0.10,
      auraScale: 1.1,
      bloomStrength: 1.25,
      scale: 1.02,
      smokeTurbulence: 1.4,
      smokeDensity: 1.1,
      smokePulse: 0.0,
      smokeWarning: 0.0,
      ringSpeed: 1.9,
      ringIntensity: 1.2,
      particleSpeed: 1.9,
      energyFlow: 1.3,
      coreGlow: 0.85,
      eyeOpen: 0.9,
      eyeHappy: 0.0,
      eyeSquint: 0.85,
      eyeAngry: 0.0,
      eyeBright: 0.18,
      eyeQuestion: 0.0,
      eyeAlert: 0.0,
      eyeCurious: 0.0,
      eyeSurprised: 0.0,
      eyeUncertain: 0.0,
    },
    waiting: {
      // "Ich warte auf dich": deutlich beruhigt, aufmerksame Augen,
      // einzelne langsame Lichtimpulse über pulseAmount.
      coreColor: 0x3f8fdd,
      glowColor: 0xa8dcff,
      particleColor: 0x9fd0ff,
      speed: 0.7,
      particleIntensity: 0.35,
      lightIntensity: 1.0,
      pulseAmount: 0.09,
      auraScale: 1.0,
      bloomStrength: 1.05,
      scale: 1.0,
      smokeTurbulence: 0.4,
      smokeDensity: 0.8,
      smokePulse: 0.0,
      smokeWarning: 0.0,
      ringSpeed: 0.45,
      ringIntensity: 0.75,
      particleSpeed: 0.5,
      energyFlow: 0.5,
      coreGlow: 0.65,
      eyeOpen: 1.0,
      eyeHappy: 0.0,
      eyeSquint: 0.0,
      eyeAngry: 0.0,
      eyeBright: 1.1,
      eyeQuestion: 1.0,
      eyeAlert: 0.0,
      eyeCurious: 0.0,
      eyeSurprised: 0.0,
      eyeUncertain: 0.65,
    },
    success: {
      // Kurz und elegant: grün, freundliche Augen; den eigentlichen
      // Impuls (sammeln -> aufleuchten -> Welle) löst main.ts über
      // flash() aus. Kein Feuerwerk.
      coreColor: 0x35d97a,
      glowColor: 0xbcffd9,
      particleColor: 0x7dffb5,
      speed: 1.1,
      particleIntensity: 0.7,
      lightIntensity: 1.3,
      pulseAmount: 0.06,
      auraScale: 1.1,
      bloomStrength: 1.3,
      scale: 1.05,
      smokeTurbulence: 0.6,
      smokeDensity: 0.9,
      smokePulse: 0.0,
      smokeWarning: 0.0,
      ringSpeed: 0.9,
      ringIntensity: 1.05,
      particleSpeed: 0.9,
      energyFlow: 0.9,
      coreGlow: 0.9,
      eyeOpen: 1.0,
      eyeHappy: 1.0,
      eyeSquint: 0.0,
      eyeAngry: 0.0,
      eyeBright: 1.2,
      eyeQuestion: 0.0,
      eyeAlert: 0.0,
      eyeCurious: 0.0,
      eyeSurprised: 0.0,
      eyeUncertain: 0.0,
    },
    warning: {
      // Warme Akzentfarbe, leicht unruhiger Fluss, subtiler Puls -
      // kein aggressives Blinken (smokeWarning pulsiert langsam).
      coreColor: 0xffb340,
      glowColor: 0xffe3b0,
      particleColor: 0xffd27d,
      speed: 1.0,
      particleIntensity: 0.6,
      lightIntensity: 1.15,
      pulseAmount: 0.12,
      auraScale: 1.05,
      bloomStrength: 1.1,
      scale: 1.0,
      smokeTurbulence: 0.9,
      smokeDensity: 1.0,
      smokePulse: 0.0,
      smokeWarning: 0.6,
      ringSpeed: 0.9,
      ringIntensity: 1.0,
      particleSpeed: 1.1,
      energyFlow: 1.0,
      coreGlow: 0.8,
      eyeOpen: 1.0,
      eyeHappy: 0.0,
      eyeSquint: 0.25,
      eyeAngry: 0.0,
      eyeBright: 1.15,
      eyeQuestion: 0.0,
      eyeAlert: 1.0,
      eyeCurious: 0.0,
      eyeSurprised: 0.55,
      eyeUncertain: 0.0,
    },
    offline: {
      // Sofort erkennbar, aber weiterhin lebendig - nicht abgestürzt:
      // deutlich weniger Glühen, langsame Bahnen, gedimmte Augen.
      coreColor: 0x5a6b7d,
      glowColor: 0x9fb2c4,
      particleColor: 0x7d8fa1,
      speed: 0.5,
      particleIntensity: 0.15,
      lightIntensity: 0.5,
      pulseAmount: 0.04,
      auraScale: 0.9,
      bloomStrength: 0.6,
      scale: 0.9,
      smokeTurbulence: 0.25,
      smokeDensity: 0.6,
      smokePulse: 0.0,
      smokeWarning: 0.0,
      ringSpeed: 0.3,
      ringIntensity: 0.45,
      particleSpeed: 0.3,
      energyFlow: 0.35,
      coreGlow: 0.3,
      eyeOpen: 0.08,
      eyeHappy: 0.0,
      eyeSquint: 0.65,
      eyeAngry: 0.0,
      eyeBright: 0.4,
      eyeQuestion: 0.0,
      eyeAlert: 0.0,
      eyeCurious: 0.0,
      eyeSurprised: 0.0,
      eyeUncertain: 0.25,
    },
  };

  const result = {} as Record<OrbStateName, OrbState>;
  for (const name of ORB_STATES) {
    // ENERGY_DEFAULTS zuerst: Sollte eine (etwa ältere) Überschreibung
    // einen Zustand unvollständig definieren, fehlen der Anzeige nie Werte.
    result[name] = { name, ...ENERGY_DEFAULTS, ...defaults[name], ...(overrides[name] ?? {}) };
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

    // Generisch statt handgepflegt: Jede Zahl wird linear überblendet,
    // Farben kanalweise. Ein neuer Zustandswert kann so nie vergessen
    // werden - genau daran ist die alte, handgeschriebene Liste beim
    // Erweitern zweimal fast gescheitert.
    const blended = {} as Record<string, number>;
    const from = this.fromAppearance as unknown as Record<string, number>;
    const to = this.toAppearance as unknown as Record<string, number>;
    for (const key of Object.keys(to)) {
      const target = to[key];
      const source = from[key] ?? target;
      if (typeof target !== "number") {
        continue;
      }
      blended[key] = key.endsWith("Color")
        ? lerpColor(source, target, amount)
        : lerp(source, target, amount);
    }
    this.blended = blended as unknown as StateAppearance;
  }

  /** Wechselt das Theme zur Laufzeit, ohne den Zustand zu verlieren. */
  public setTheme(themeName: string, overrides: Record<string, Partial<StateAppearance>> = {}): void {
    this.states = buildStates(themeName, overrides);
    this.fromAppearance = { ...this.blended };
    this.toAppearance = { ...this.states[this.currentName] };
    this.transitionElapsed = 0;
  }
}
