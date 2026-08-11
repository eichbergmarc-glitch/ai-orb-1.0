/**
 * energy_vortex.ts – der Wirbel aus Lichtbahnen und Nebel.
 *
 * Vorbild ist eine Vorlage, die der Benutzer gezeigt hat. Ihre eigene
 * Beschreibung nennt den Kern der Sache: „a swirling storm of neon light
 * and energy".
 *
 * ## Warum die Vorgänger nicht danach aussahen
 *
 * Das ist die Lehre aus mehreren Anläufen, und sie ist keine Kleinigkeit.
 * Ich hatte den Ring als KURVE gebaut – eine geschlossene Linie, die sich
 * verformt – und sie immer organischer gemacht: mehr Oberwellen, atmende
 * Stärken, wandernde Phasen. Es half nichts, und es konnte nichts helfen.
 *
 * Das Vorbild ist kein verformter Ring. Es ist ein Sturm: sehr viele
 * einzelne Lichtspuren auf Spiralbahnen. Der Kreis entsteht erst daraus,
 * dass sich diese Bahnen in einem Band häufen. Eine glatte Kurve kann so
 * etwas nicht werden, gleich wie viele Oberwellen man darauflegt – es war
 * die falsche Bauart und nicht die falsche Einstellung.
 *
 * ## Woraus er besteht
 *
 * Drei Lagen, jede mit einer Aufgabe:
 *
 *   1. Die Lichtbahnen. Sie kreisen um die Mitte, werden nach innen
 *      gezogen und entstehen aussen neu. Gezeichnet wird nicht der Punkt,
 *      sondern die Strecke zwischen seinem Ort jetzt und vor einem
 *      Augenblick: Ein Punkt zeigt, WO etwas ist, ein Strich zeigt, WOHIN
 *      es geht.
 *
 *   2. Der Nebel um den Ring. Eine weite, weiche Wolke in einem dritten
 *      Farbton, nach aussen weich verblassend.
 *
 *   3. Der Kern in der Mitte. Dort, wo im Vorbild das Logo steht.
 *
 * ## Was „organisch" hier heisst
 *
 * Nicht mehr Zufall – Zufall sieht aus wie Rauschen. Alle drei Lagen
 * laufen durch dasselbe langsam wandernde Strömungsfeld, eine Summe von
 * Sinuswellen über dem ORT. Das ist der entscheidende Unterschied: Ein
 * Versatz je Teilchen lässt jedes für sich zappeln; ein Feld über dem Ort
 * verzieht benachbarte Bahnen GEMEINSAM. Wo es gerade nach aussen drückt,
 * wölbt sich der ganze Wirbel dort nach aussen, und einen Moment später
 * woanders. Das ist der Unterschied zwischen Rauch und Konfetti.
 *
 * Dazu ändert jede Bahn ihr Tempo, statt gleichmässig zu kreisen. Dadurch
 * scheren sie auseinander und ziehen sich wieder zusammen – daraus
 * entstehen die dichten und dünnen Stellen, die man in echtem Rauch sieht.
 *
 * ## Warum das ohne eigenen Shader auskommt
 *
 * Ein früherer Kern war ein gerechneter Kristallhaufen – schön gedacht,
 * aber er erschien auf dem Rechner des Benutzers nie. Die Ursache lag
 * nicht im Aussehen, sondern in der Übersetzung: Was three.js für eigene
 * Shader zulässt, ist enger, als es beim Schreiben scheint, und ein
 * Shader, der nicht übersetzt wird, zeichnet nichts – ohne Fehlerbild,
 * einfach gar nichts.
 *
 * Hier wird deshalb nur benutzt, was in dieser Anwendung nachweislich
 * ankommt: gewöhnliche Geometrie, Standardmaterialien, Vertexfarben und
 * der bestehende Bloom-Effekt. Der Bloom ist übrigens der Grund, warum das
 * überhaupt nach Neon aussehen kann: Neon ist nicht eine Farbe, sondern
 * helles Licht, das in seine Umgebung ausblutet.
 */

import * as THREE from "three";

/** So viele Lichtbahnen bilden den Wirbel. */
const BAHNEN = 820;

/**
 * In so viele Stücke ist die Spur einer Bahn unterteilt.
 *
 * Fünf genügen. Die Spur ist kurz, und mehr Stücke machen sie nicht
 * runder, sondern nur teurer – bei 820 Bahnen zählt jedes Stück achthundert
 * Mal.
 */
const GLIEDER = 5;

/** So viele Flecken bilden den Nebel um den Ring. */
const NEBEL = 380;

/** So viele Flecken bilden den Kern in der Mitte. */
const KERN = 240;

/** Wo eine Bahn nach innen verschwindet. */
const R_INNEN = 0.34;

/**
 * Wo eine Bahn neu entsteht.
 *
 * Zusammen mit dem Nebel darüber bestimmt dieser Wert die Grösse des Orb.
 * Die bestehende Aura kreist zwischen 0.85 und 1.40; was darüber
 * hinausgeht, schneidet das Fenster ab.
 */
const R_AUSSEN = 1.10;

/** Wo sich die Bahnen häufen – dort entsteht der Ring. */
const BAND_MITTE = 0.78;

/** Wie breit dieses Band ist. Enger heisst mehr Ring, weiter mehr Sturm. */
const BAND_BREITE = 0.26;

/** Dauer eines Herzschlags in Sekunden. */
const PULS_DAUER = 2.2;

/**
 * Dauer eines vollstaendigen Atemzugs in Sekunden.
 *
 * Sechs, wie vom Benutzer verlangt. Der Atem ist der langsame Bogen unter
 * allem: zusammengezogen, dann nach aussen wie ein Atemzug, dann genau in
 * die Ausgangslage zurueck. Weil er an einem Kosinus haengt und an nichts
 * sonst, ist der Zustand nach sechs Sekunden nicht aehnlich dem Anfang,
 * sondern derselbe.
 */
const ATEM_DAUER = 6.0;

/**
 * Wie weit sich der Wirbel beim Ausatmen oeffnet.
 *
 * Zusammengezogen misst er 0.58 seiner vollen Weite, ausgedehnt die volle.
 * Weniger Unterschied faellt nicht auf, mehr laesst ihn beim Einatmen zu
 * einem Punkt zusammenfallen - und ein Ring, der verschwindet, ist kein
 * Atmen mehr, sondern ein Blinken.
 */
const ATEM_ENGE = 0.58;

/**
 * Der Farbabstand zwischen Ring, Kern und Nebel (Anteil des Farbkreises).
 *
 * Ein Drittel. Zwei Farben wären ein Gegensatz, drei ergeben einen
 * Verlauf – und der Nebel liegt auf der anderen Seite des Rings als der
 * Kern, sodass die drei Lagen auch farblich auseinanderzuhalten sind.
 */
const FARBABSTAND = 0.32;

/**
 * Ab hier wird der Abstand vom Mittelpunkt weich abgefangen.
 *
 * Atem, Stimme, Ranke und Herzschlag koennen rein rechnerisch alle
 * gleichzeitig nach aussen zeigen. Das kommt selten vor, aber "selten" ist
 * kein Argument, wenn das Fenster abschneidet.
 */
const WEICHE_DECKE = 1.00;

/**
 * Und hierueber kommt nichts.
 *
 * Nicht hart abgeschnitten, sondern asymptotisch: Zwischen beiden Werten
 * wird die Ueberschreitung zusammengedrueckt. Ein hartes Kappen ergaebe
 * eine Kreiskante, an der sich alle Bahnen sammeln - und die faellt sofort
 * auf. Gedrueckt sieht es aus, als stiessen sie an etwas an, und das ist
 * bei einem Wirbel eher ein Gewinn.
 */
const HARTE_DECKE = 1.36;

/** Drueckt einen Abstand unter die Decke, ohne ihn zu kappen. */
function gedeckelt(r: number): number {
  if (r <= WEICHE_DECKE) {
    return r;
  }
  const spielraum = HARTE_DECKE - WEICHE_DECKE;
  return WEICHE_DECKE + spielraum * (1.0 - Math.exp(-(r - WEICHE_DECKE) / spielraum));
}

/** Ein einfacher, wiederholbarer Zufall. */
function zufall(saat: number): () => number {
  let s = saat >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 4294967296;
  };
}

/** Zwei Glocken ergeben einen Herzschlag: Schlag, Nachschlag, Ruhe. */
function herzschlag(phase: number): number {
  return Math.min(1.0, glocke(phase, 0.0, 0.055) + glocke(phase, 0.17, 0.075) * 0.62);
}

/** Eine Glocke, die einmal um die Phase herumreicht. */
function glocke(phase: number, mitte: number, breite: number): number {
  let d = Math.abs(phase - mitte);
  if (d > 0.5) {
    d = 1.0 - d;
  }
  return Math.exp(-(d * d) / (breite * breite));
}

/**
 * Der Energiewirbel.
 *
 * Er ist nur leicht gekippt und dreht sich nicht frei: Ein Wirbel, der
 * sich frei dreht, ist die halbe Zeit über eine Ellipse und einen
 * Wimpernschlag lang ein Strich. Als Ring erkennbar bleibt er nur, wenn er
 * dem Betrachter zugewandt bleibt.
 */
export class EnergyVortex {
  /** Die Gruppe, die alles enthält. */
  public readonly group: THREE.Group;

  private readonly spuren: THREE.LineSegments;
  private readonly nebel: THREE.Points;
  private readonly kern: THREE.Points;

  private readonly spurMaterial: THREE.LineBasicMaterial;
  private readonly nebelMaterial: THREE.PointsMaterial;
  private readonly kernMaterial: THREE.PointsMaterial;

  private readonly spurOrte: Float32Array;
  private readonly spurFarben: Float32Array;
  private readonly nebelOrte: Float32Array;
  private readonly nebelFarben: Float32Array;
  private readonly kernOrte: Float32Array;
  private readonly kernFarben: Float32Array;

  // Für jede Lichtbahn.
  private readonly winkel: Float32Array;
  private readonly radius: Float32Array;
  private readonly hoehe: Float32Array;
  private readonly tempo: Float32Array;
  private readonly laenge: Float32Array;
  private readonly glanz: Float32Array;
  private readonly eigenart: Float32Array;

  // Für den Nebel.
  private readonly nBahn: Float32Array;
  private readonly nWinkel: Float32Array;
  private readonly nHoehe: Float32Array;
  private readonly nTempo: Float32Array;
  private readonly nPhase: Float32Array;

  // Für den Kern.
  private readonly kBahn: Float32Array;
  private readonly kHoehe: Float32Array;
  private readonly kTempo: Float32Array;
  private readonly kPhase: Float32Array;

  /** Der Farbton, um den herum sich alles spannt. */
  private neonTon = 0.52;
  private neonHelle = 0.52;

  private stimme = 0.0;
  private staerke = 1.0;
  private takt = 0.0;
  /** Wo im Atemzug wir stehen (0 bis 1) - mitgefuehrt, nicht gerechnet. */
  private atemTakt = 0.0;
  /** Die aktuelle Weite, damit alle drei Lagen zusammen atmen. */
  private weite = 1.0;
  private aufbau = 0.0;

  private sichtbareBahnen = BAHNEN;
  private sichtbarerNebel = NEBEL;

  private readonly streich = new THREE.Color();
  private readonly hsl = { h: 0, s: 0, l: 0 };
  private readonly stroem = { x: 0, y: 0, z: 0 };
  private readonly p1 = { x: 0, y: 0, z: 0 };
  private readonly p2 = { x: 0, y: 0, z: 0 };
  private readonly wuerfel = zufall(20260810);

  constructor() {
    this.group = new THREE.Group();

    // --- Die Lichtbahnen ---------------------------------------------------
    this.spurOrte = new Float32Array(BAHNEN * GLIEDER * 2 * 3);
    this.spurFarben = new Float32Array(BAHNEN * GLIEDER * 2 * 3);

    const spurGeometrie = new THREE.BufferGeometry();
    spurGeometrie.setAttribute("position", new THREE.BufferAttribute(this.spurOrte, 3));
    spurGeometrie.setAttribute("color", new THREE.BufferAttribute(this.spurFarben, 3));

    this.spurMaterial = new THREE.LineBasicMaterial({
      vertexColors: true,
      transparent: true,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    this.spuren = new THREE.LineSegments(spurGeometrie, this.spurMaterial);
    this.spuren.frustumCulled = false;
    this.group.add(this.spuren);

    this.winkel = new Float32Array(BAHNEN);
    this.radius = new Float32Array(BAHNEN);
    this.hoehe = new Float32Array(BAHNEN);
    this.tempo = new Float32Array(BAHNEN);
    this.laenge = new Float32Array(BAHNEN);
    this.glanz = new Float32Array(BAHNEN);
    this.eigenart = new Float32Array(BAHNEN);
    for (let i = 0; i < BAHNEN; i++) {
      this.gebaeren(i, true);
    }

    // --- Der Nebel um den Ring ---------------------------------------------
    this.nebelOrte = new Float32Array(NEBEL * 3);
    this.nebelFarben = new Float32Array(NEBEL * 3);
    this.nBahn = new Float32Array(NEBEL);
    this.nWinkel = new Float32Array(NEBEL);
    this.nHoehe = new Float32Array(NEBEL);
    this.nTempo = new Float32Array(NEBEL);
    this.nPhase = new Float32Array(NEBEL);

    for (let i = 0; i < NEBEL; i++) {
      // Um das Band herum verteilt, nicht gleichmässig über die Fläche:
      // Der Nebel soll den Ring UMGEBEN und nicht die Mitte zustellen.
      this.nBahn[i] = 0.60 + this.wuerfel() * 0.58;
      this.nWinkel[i] = this.wuerfel() * Math.PI * 2.0;
      this.nHoehe[i] = (this.wuerfel() - 0.5) * 0.52;
      this.nTempo[i] = 0.10 + this.wuerfel() * 0.22;
      this.nPhase[i] = this.wuerfel() * Math.PI * 2.0;
    }

    const nebelGeometrie = new THREE.BufferGeometry();
    nebelGeometrie.setAttribute("position", new THREE.BufferAttribute(this.nebelOrte, 3));
    nebelGeometrie.setAttribute("color", new THREE.BufferAttribute(this.nebelFarben, 3));

    this.nebelMaterial = new THREE.PointsMaterial({
      // Gross und blass: Was Nebel ausmacht, sind weite, schwache Flecken,
      // die sich überlagern. Kleine helle Punkte wären Sterne.
      size: 0.150,
      vertexColors: true,
      transparent: true,
      opacity: 0.30,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
      sizeAttenuation: true,
    });
    this.nebel = new THREE.Points(nebelGeometrie, this.nebelMaterial);
    this.nebel.frustumCulled = false;
    this.group.add(this.nebel);

    // --- Der Kern ----------------------------------------------------------
    this.kernOrte = new Float32Array(KERN * 3);
    this.kernFarben = new Float32Array(KERN * 3);
    this.kBahn = new Float32Array(KERN);
    this.kHoehe = new Float32Array(KERN);
    this.kTempo = new Float32Array(KERN);
    this.kPhase = new Float32Array(KERN);

    for (let i = 0; i < KERN; i++) {
      // Die Wurzel verteilt gleichmässig über die FLÄCHE. Ohne sie klumpte
      // alles in der Mitte, weil eine Kreisfläche aussen mehr Platz hat.
      this.kBahn[i] = Math.sqrt(this.wuerfel()) * 0.30;
      this.kHoehe[i] = (this.wuerfel() - 0.5) * 0.22;
      this.kTempo[i] = 0.35 + this.wuerfel() * 0.55;
      this.kPhase[i] = this.wuerfel() * Math.PI * 2.0;
    }

    const kernGeometrie = new THREE.BufferGeometry();
    kernGeometrie.setAttribute("position", new THREE.BufferAttribute(this.kernOrte, 3));
    kernGeometrie.setAttribute("color", new THREE.BufferAttribute(this.kernFarben, 3));

    this.kernMaterial = new THREE.PointsMaterial({
      size: 0.075,
      vertexColors: true,
      transparent: true,
      opacity: 0.5,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
      sizeAttenuation: true,
    });
    this.kern = new THREE.Points(kernGeometrie, this.kernMaterial);
    this.kern.frustumCulled = false;
    this.group.add(this.kern);
  }

  /**
   * Übernimmt die Farben des Zustands.
   *
   * Neon ist keine bestimmte Farbe, sondern eine Machart: voll gesättigt,
   * hell, und in eine dunkle Umgebung ausblutend. Deshalb wird hier nicht
   * die Zustandsfarbe übernommen, sondern nur ihr FARBTON – Sättigung und
   * Helligkeit setzt dieses Modul selbst. Sonst ergäbe ein blasses Theme
   * einen blassen Wirbel, und das wäre kein Neon mehr.
   *
   * Was bleibt, ist die Auskunft: Im Ruhezustand steht der Farbton auf
   * Blaugrün, beim Arbeiten auf Rot, und die drei Lagen spannen sich um
   * ihn herum.
   */
  public setColors(kern: THREE.Color, schein: THREE.Color, staerke: number): void {
    kern.getHSL(this.hsl);
    let ton = this.hsl.h;

    // Eine sehr blasse Zustandsfarbe hat keinen verlässlichen Farbton – bei
    // Grau ist er beliebig. Dann bleibt der bisherige stehen, statt dass
    // der Wirbel bei jedem Bild die Farbe wechselt.
    if (this.hsl.s < 0.08) {
      schein.getHSL(this.hsl);
      ton = this.hsl.s >= 0.08 ? this.hsl.h : this.neonTon;
    }

    this.neonTon = ton;
    this.staerke = staerke;
    this.neonHelle = 0.46 + staerke * 0.10;
  }

  /** Meldet, wie laut gerade gesprochen wird (0 bis 1, bereits geglättet). */
  public setVoiceLevel(pegel: number): void {
    this.stimme = Math.max(0, Math.min(1, pegel));
  }

  /** Lässt den Wirbel von vorn anlaufen. */
  public restartIntro(): void {
    this.aufbau = 0.0;
  }

  /**
   * Dreht den Wirbel weiter.
   *
   * @param elapsed Laufzeit in Sekunden.
   * @param delta Zeit seit dem letzten Bild.
   * @param tempo Geschwindigkeit des Zustands.
   */
  public update(elapsed: number, delta: number, tempo: number): void {
    // Der Aufbau: Der Wirbel setzt sich in Gang, statt fertig dazustehen.
    this.aufbau = Math.min(2.5, this.aufbau + delta);
    const anlauf = Math.min(1.0, this.aufbau / 2.0);

    // Der Takt wird mitgeführt, nicht aus der Laufzeit gerechnet: Aus
    // elapsed * tempo folgte sonst ein Sprung, sobald sich das Tempo
    // ändert – und das tut es bei jedem Zustandswechsel.
    this.takt = (this.takt + (delta * tempo) / PULS_DAUER) % 1.0;
    this.atemTakt = (this.atemTakt + (delta * tempo) / ATEM_DAUER) % 1.0;

    // Der Atem. Ein Kosinus und sonst nichts - das ist der Grund, warum
    // der Kreis wirklich geschlossen ist und nicht bloss annaehernd.
    const atem = 0.5 - 0.5 * Math.cos(this.atemTakt * Math.PI * 2.0);

    // Beim Sprechen dehnt er sich ueber das Ausatmen hinaus. Die Stimme
    // soll den Atem stoeren, nicht ersetzen: Ein Atemzug, der beim
    // Sprechen unbeirrt weiterlaeuft, wirkt wie eine Anzeige.
    this.weite = ATEM_ENGE + (1.0 - ATEM_ENGE) * atem + this.stimme * 0.16;

    this.bahnenSetzen(elapsed, delta, tempo, anlauf, atem);
    this.nebelSetzen(elapsed, anlauf);
    this.kernSetzen(elapsed, anlauf);

    this.group.rotation.x = -0.34 + Math.sin(elapsed * 0.17) * 0.10;
    this.group.rotation.z = Math.sin(elapsed * 0.11) * 0.08;
  }

  // --- Innenleben --------------------------------------------------------------

  /** Gibt einer Bahn einen neuen Anfang. */
  private gebaeren(i: number, ueberall: boolean): void {
    this.winkel[i] = this.wuerfel() * Math.PI * 2.0;
    // Beim ersten Bild überall, sonst hätte man einen Ring, der von aussen
    // hereinfällt, statt eines schon laufenden Sturms.
    this.radius[i] = ueberall
      ? R_INNEN + this.wuerfel() * (R_AUSSEN - R_INNEN)
      : R_AUSSEN - this.wuerfel() * 0.12;
    this.hoehe[i] = (this.wuerfel() - 0.5) * 0.34;
    this.tempo[i] = 0.85 + this.wuerfel() * 0.75;
    this.laenge[i] = 0.045 + this.wuerfel() * 0.075;
    this.glanz[i] = 0.35 + this.wuerfel() * 0.65;
    this.eigenart[i] = this.wuerfel() * Math.PI * 2.0;
  }

  /**
   * Das Strömungsfeld.
   *
   * Eine Summe von Sinuswellen über dem ORT, nicht über der Nummer des
   * Teilchens. Das ist der ganze Unterschied: Ein Versatz je Teilchen
   * ergibt Rauschen, weil jedes für sich zappelt. Ein Feld über dem Ort
   * verzieht benachbarte Bahnen GEMEINSAM – und genau daran erkennt das
   * Auge Rauch statt Konfetti.
   */
  private stroemung(x: number, y: number, z: number, e: number): void {
    this.stroem.x =
      Math.sin(y * 2.3 + e * 0.51) * 0.085 + Math.sin(z * 3.1 - e * 0.33) * 0.050;
    this.stroem.y =
      Math.sin(z * 2.7 - e * 0.44) * 0.085 + Math.sin(x * 3.3 + e * 0.29) * 0.050;
    this.stroem.z =
      Math.sin(x * 2.1 + e * 0.37) * 0.055 + Math.sin(y * 2.9 - e * 0.41) * 0.038;
  }

  /**
   * Wo eine Bahn vor `zurueck` Sekunden stand.
   *
   * Die Spur wird nicht mitgeschleppt, sondern gerechnet: dieselbe Formel,
   * mehrmals mit kleinem Zeitversatz ausgewertet. Die Strömung wirkt dabei
   * auf den FERTIGEN Ort – so folgt die ganze Spur derselben Verwerfung und
   * knickt nicht in der Mitte ab.
   */
  private ortAuf(
    i: number,
    zurueck: number,
    e: number,
    tmp: number,
    ziel: { x: number; y: number; z: number }
  ): void {
    const r0 = this.radius[i];
    const w = this.winkel[i] - zurueck * tmp * (1.55 - r0 * 0.75);
    const r = (r0 + zurueck * 0.16) * this.weite;

    // Die Ranke.
    //
    // Ohne sie ist die Bahn ein Kreisbogen, dem ein Versatz aufgeprägt
    // wird – und ein verschobener Kreis bleibt sichtbar ein Kreis. Hier
    // schwingt der Radius ENTLANG der Bahn, also über dem Winkel: Daraus
    // wird ein Weg, der sich windet, statt einer Linie, die zittert.
    //
    // Zwei ungleiche Wellen, damit sich kein Muster einstellt, und beide
    // wachsen nach aussen: Innen liegt der Wirbel eng, aussen fasert er in
    // Ranken auf. Genau so verhält sich auch Rauch, der sich von einer
    // Quelle löst.
    const ranke =
      1.0 +
      (Math.sin(w * 2.0 + e * 0.47 + this.eigenart[i]) * 0.115 +
        Math.sin(w * 3.0 - e * 0.31 + this.eigenart[i] * 1.6) * 0.070) *
        (0.35 + r0 * 0.9);

    const wall = ranke + Math.sin(e * 0.9 + i * 0.37 - zurueck * 2.0) * 0.055;
    const weit = gedeckelt(r * wall);

    const x = Math.cos(w) * weit;
    const y = Math.sin(w) * weit;

    // Die Höhe schwingt ebenfalls über dem Winkel – sonst bliebe der
    // Wirbel eine flache Scheibe mit welligem Rand.
    const z =
      this.hoehe[i] * weit +
      Math.sin(w * 2.0 - e * 0.39 + this.eigenart[i]) * 0.075 * r +
      Math.sin(e * 1.1 + i * 0.21) * 0.02;

    this.stroemung(x, y, z, e - zurueck);
    ziel.x = x + this.stroem.x;
    ziel.y = y + this.stroem.y;
    ziel.z = z + this.stroem.z;
  }

  /** Dreht die Lichtbahnen weiter und zeichnet ihre Spuren. */
  private bahnenSetzen(
    elapsed: number,
    delta: number,
    tempo: number,
    anlauf: number,
    atem: number
  ): void {
    const anzahl = this.sichtbareBahnen;
    let p = 0;

    for (let i = 0; i < anzahl; i++) {
      // Jede Bahn ändert ihr Tempo, statt gleichmässig zu kreisen. Dadurch
      // scheren sie auseinander und ziehen sich wieder zusammen – daraus
      // entstehen die dichten und dünnen Stellen von echtem Rauch.
      const tmp =
        this.tempo[i] *
        (1.0 +
          Math.sin(elapsed * 0.63 + this.eigenart[i]) * 0.42 +
          Math.sin(elapsed * 0.21 + this.eigenart[i] * 1.7) * 0.22) *
        (1.0 + this.stimme * 0.9);

      // Der Herzschlag an DIESER Stelle des Wirbels. Er läuft einmal je
      // Puls herum, statt überall gleichzeitig zu geschehen – das ist der
      // Unterschied zwischen einem Wirbel, der als Ganzes grösser wird,
      // und einem, durch den eine Welle hindurchgeht.
      let stelle = (this.takt - this.winkel[i] / (Math.PI * 2.0)) % 1.0;
      if (stelle < 0) {
        stelle += 1.0;
      }
      const schub = herzschlag(stelle);

      this.winkel[i] += delta * tmp * tempo * (1.55 - this.radius[i] * 0.75);

      // Der Sog nach innen. Ohne ihn kreisen die Bahnen bloss – mit ihm
      // wird etwas hineingezogen, und genau das ist ein Wirbel.
      //
      // Er ist nicht gleichmässig, und das ist der Punkt: Der Herzschlag
      // drückt die Bahnen kurz nach aussen, und beim Ausatmen lässt der
      // Sog nach. Ein gleichmässiger Sog ergibt einen Trichter mit
      // konstantem Durchsatz – man sieht ihm an, dass er gerechnet ist.
      const sog =
        (0.055 + (this.radius[i] - R_INNEN) * 0.075) * (1.25 - 0.5 * atem) -
        schub * 0.30;
      this.radius[i] -= delta * tempo * sog;

      if (this.radius[i] <= R_INNEN) {
        this.gebaeren(i, false);
      } else if (this.radius[i] > R_AUSSEN) {
        // Der Schub kann eine Bahn über den Rand tragen. Sie dort zu
        // kappen gäbe eine sichtbare Kante; sie bleibt einfach liegen.
        this.radius[i] = R_AUSSEN;
      }

      const schlag = schub;

      // Wie nah die Bahn am Band liegt, in dem sich der Ring bildet.
      // Das Band, in dem sich die Bahnen häufen und aus dem der Ring
      // entsteht, wandert mit dem Atem nach aussen und wieder herein.
      const band = Math.exp(
        -Math.pow((this.radius[i] - BAND_MITTE) / BAND_BREITE, 2)
      );

      const ton =
        this.neonTon +
        0.30 * Math.sin(this.winkel[i] + elapsed * 0.25) +
        0.18 * Math.sin(this.radius[i] * 7.0 - elapsed * 0.4);

      const hell =
        (0.30 + band * 0.9 + schlag * 0.9) *
        this.glanz[i] *
        anlauf *
        (0.6 + this.staerke * 0.4);

      this.streich.setHSL(
        (((ton + schlag * 0.05) % 1.0) + 1.0) % 1.0,
        1.0 - schlag * 0.2,
        Math.min(0.92, this.neonHelle + schlag * 0.22 + this.stimme * 0.12)
      );

      for (let s = 0; s < GLIEDER; s++) {
        this.ortAuf(i, this.laenge[i] * (s / GLIEDER), elapsed, tmp, this.p1);
        this.ortAuf(i, this.laenge[i] * ((s + 1) / GLIEDER), elapsed, tmp, this.p2);

        // Nach hinten verglühen: sonst wären es Striche, keine Spuren.
        const f0 = hell * (1.0 - s / GLIEDER);
        const f1 = hell * (1.0 - (s + 1) / GLIEDER);

        this.spurOrte[p * 3 + 0] = this.p1.x;
        this.spurOrte[p * 3 + 1] = this.p1.y;
        this.spurOrte[p * 3 + 2] = this.p1.z;
        this.spurFarben[p * 3 + 0] = this.streich.r * f0;
        this.spurFarben[p * 3 + 1] = this.streich.g * f0;
        this.spurFarben[p * 3 + 2] = this.streich.b * f0;
        p += 1;

        this.spurOrte[p * 3 + 0] = this.p2.x;
        this.spurOrte[p * 3 + 1] = this.p2.y;
        this.spurOrte[p * 3 + 2] = this.p2.z;
        this.spurFarben[p * 3 + 0] = this.streich.r * f1;
        this.spurFarben[p * 3 + 1] = this.streich.g * f1;
        this.spurFarben[p * 3 + 2] = this.streich.b * f1;
        p += 1;
      }
    }

    // Was nicht gezeichnet wird, wird schwarz – auf die Zahl der Punkte in
    // der Geometrie lässt sich nicht ohne Neubau einwirken.
    for (let k = p * 3; k < this.spurFarben.length; k++) {
      this.spurFarben[k] = 0;
    }

    (this.spuren.geometry.getAttribute("position") as THREE.BufferAttribute).needsUpdate =
      true;
    (this.spuren.geometry.getAttribute("color") as THREE.BufferAttribute).needsUpdate =
      true;
  }

  /** Legt den Nebel um den Ring. */
  private nebelSetzen(elapsed: number, anlauf: number): void {
    const anzahl = this.sichtbarerNebel;

    // Der Nebel liegt auf der anderen Seite des Rings als der Kern: Zwei
    // Farben wären ein Gegensatz, drei ergeben einen Verlauf. Und der
    // Abstand wandert langsam, statt festzustehen – ein Nebel mit fester
    // Farbe ist ein gefärbter Schleier.
    const wandel =
      -FARBABSTAND + Math.sin(elapsed * 0.083) * 0.09 + Math.sin(elapsed * 0.041 + 1.3) * 0.05;

    for (let i = 0; i < anzahl; i++) {
      const w = this.nWinkel[i] + elapsed * this.nTempo[i];
      // Der Nebel atmet mit dem Ring - aber traeger, als hinge er ihm
      // nach. Zwei Lagen, die genau gleich atmen, wirken wie eine.
      const atmen =
        (0.72 + 0.28 * this.weite) *
        (1.0 + Math.sin(elapsed * 0.37 + this.nPhase[i]) * 0.10);

      // Auch hier schwingt der Radius ueber dem Winkel: Der Nebel bekommt
      // dadurch Schwaden statt einer gleichmaessigen Wolke.
      const schwade =
        1.0 + Math.sin(w * 2.0 + elapsed * 0.23 + this.nPhase[i]) * 0.16;

      let x = Math.cos(w) * this.nBahn[i] * atmen * schwade;
      let y = Math.sin(w) * this.nBahn[i] * atmen * schwade;
      let z = this.nHoehe[i] * atmen + Math.sin(elapsed * 0.5 + this.nPhase[i]) * 0.05;

      // Derselbe Zug wie bei den Bahnen, nur kräftiger: Nebel gibt nach.
      this.stroemung(x, y, z, elapsed);
      x += this.stroem.x * 2.1;
      y += this.stroem.y * 2.1;
      z += this.stroem.z * 2.1;

      this.nebelOrte[i * 3 + 0] = x;
      this.nebelOrte[i * 3 + 1] = y;
      this.nebelOrte[i * 3 + 2] = z;

      // Nach aussen weich verblassen, damit er nirgends eine Kante hat –
      // und damit er nicht über den Rand des Fensters hinausragt.
      const weg = Math.sqrt(x * x + y * y);
      const rand = Math.exp(-Math.pow(Math.max(0, weg - 0.92) / 0.32, 2));
      const dichte = Math.exp(-Math.pow((weg - 0.90) / 0.40, 2)) * rand;

      const eigen = Math.sin(elapsed * 0.19 + this.nPhase[i] * 2.3) * 0.06;
      this.streich.setHSL(
        (((this.neonTon + wandel + eigen) % 1.0) + 1.0) % 1.0,
        0.92,
        0.40 + this.stimme * 0.12
      );

      const d = dichte * 0.85 * anlauf * (0.55 + this.staerke * 0.45);
      this.nebelFarben[i * 3 + 0] = this.streich.r * d;
      this.nebelFarben[i * 3 + 1] = this.streich.g * d;
      this.nebelFarben[i * 3 + 2] = this.streich.b * d;
    }

    for (let i = anzahl; i < NEBEL; i++) {
      this.nebelFarben[i * 3 + 0] = 0;
      this.nebelFarben[i * 3 + 1] = 0;
      this.nebelFarben[i * 3 + 2] = 0;
    }

    (this.nebel.geometry.getAttribute("position") as THREE.BufferAttribute).needsUpdate =
      true;
    (this.nebel.geometry.getAttribute("color") as THREE.BufferAttribute).needsUpdate =
      true;
  }

  /** Legt den Kern in die Mitte. */
  private kernSetzen(elapsed: number, anlauf: number): void {
    const wandel =
      FARBABSTAND + Math.sin(elapsed * 0.11) * 0.10 + Math.sin(elapsed * 0.047 + 2.3) * 0.055;

    for (let i = 0; i < KERN; i++) {
      // Innen schneller als aussen – das unterscheidet einen Wirbel von
      // einer sich drehenden Scheibe.
      const innen = 1.0 - this.kBahn[i] * 0.7;
      const w = this.kPhase[i] + elapsed * this.kTempo[i] * innen * 0.9;
      const r =
        this.kBahn[i] *
        (0.68 + 0.32 * this.weite) *
        (1.0 + Math.sin(elapsed * 0.55 + this.kPhase[i] * 1.7) * 0.22);

      const x = Math.cos(w) * r;
      const y = Math.sin(w) * r;
      const z = this.kHoehe[i] + Math.sin(elapsed * 0.8 + this.kPhase[i]) * 0.04;

      this.stroemung(x, y, z, elapsed);
      this.kernOrte[i * 3 + 0] = x + this.stroem.x * 0.5;
      this.kernOrte[i * 3 + 1] = y + this.stroem.y * 0.5;
      this.kernOrte[i * 3 + 2] = z + this.stroem.z * 0.5;

      const eigen = Math.sin(elapsed * 0.23 + this.kPhase[i] * 2.7) * 0.055;
      this.streich.setHSL(
        (((this.neonTon + wandel + eigen) % 1.0) + 1.0) % 1.0,
        0.95,
        0.42 + this.stimme * 0.16
      );

      const d = (1.0 - (this.kBahn[i] / 0.30) * 0.65) * 0.9 * anlauf;
      this.kernFarben[i * 3 + 0] = this.streich.r * d;
      this.kernFarben[i * 3 + 1] = this.streich.g * d;
      this.kernFarben[i * 3 + 2] = this.streich.b * d;
    }

    (this.kern.geometry.getAttribute("position") as THREE.BufferAttribute).needsUpdate =
      true;
    (this.kern.geometry.getAttribute("color") as THREE.BufferAttribute).needsUpdate = true;
  }

  /** Passt den Aufwand an die Leistungsstufe an. */
  public setQuality(level: number): void {
    // Die Bahnen sind der teuerste Posten und werden zuerst gekürzt – aber
    // nie unter ein Drittel: Zu wenige Bahnen sind kein sparsamerer Sturm,
    // sondern ein paar kreisende Striche.
    this.sichtbareBahnen =
      level >= 2 ? BAHNEN : level >= 1 ? Math.floor(BAHNEN * 0.55) : Math.floor(BAHNEN * 0.33);

    // Der Nebel kostet vor allem Füllrate, weil seine Flecken gross sind
    // und sich überlagern.
    this.sichtbarerNebel =
      level >= 2 ? NEBEL : level >= 1 ? Math.floor(NEBEL * 0.5) : 0;

    this.kern.visible = level >= 1;
  }

  /** Gibt alle GPU-Ressourcen frei. */
  public dispose(): void {
    this.spuren.geometry.dispose();
    this.nebel.geometry.dispose();
    this.kern.geometry.dispose();
    this.spurMaterial.dispose();
    this.nebelMaterial.dispose();
    this.kernMaterial.dispose();
  }
}
