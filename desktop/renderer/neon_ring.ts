/**
 * neon_ring.ts – das pulsierende, sich morphende O.
 *
 * Der Benutzer wollte ein O: einen Ring in Neonfarben, der pulsiert, sich
 * morpht und sich organisch verändert – und der sich beim ersten Start aus
 * einem Nebel bildet, der sich zusammenzieht.
 *
 * ## Warum der Ring nicht aufreisst
 *
 * Das ist die eine Eigenschaft, an der ein morphender Ring steht oder
 * fällt, und man bekommt sie nicht durch Sorgfalt, sondern durch die Wahl
 * der Formel. Die Verformung ist eine Summe von Sinuswellen über dem
 * Winkel:
 *
 *     r(θ) = R · (1 + Σ aₖ · sin(kθ + ωₖt + φₖ))
 *
 * Entscheidend ist, dass jedes k eine GANZE Zahl ist. Dann gilt
 * r(θ + 2π) = r(θ) exakt, und der Ring schliesst sich – nicht ungefähr,
 * sondern bis auf die letzte Stelle. Eine krumme Zahl wie 2.5 ergäbe eine
 * Kerbe an einer festen Stelle des Rings, die mitwandert und wie ein
 * Zeichenfehler aussieht.
 *
 * Genau dasselbe gilt für die Farbe, die um den Ring wandert.
 *
 * ## Warum es fünf Bänder sind und nicht eine Linie
 *
 * Eine einzelne Linie ist ein Draht. Was ein O daraus macht, ist die
 * Dicke – und die lässt sich in WebGL nicht einfach einstellen: Die
 * Linienbreite ist auf fast allen Treibern auf einen Pixel festgenagelt,
 * ganz gleich, was man einträgt.
 *
 * Deshalb liegen hier fünf Ringe leicht versetzt übereinander, jeder mit
 * einer eigenen Phase in der Verformung. Innen sind sie hell, aussen
 * blasser. Sie kreuzen sich dabei, und diese Kreuzungen sind das
 * eigentliche Ziel: Aus fünf Linien wird ein Band, das an manchen Stellen
 * dichter ist als an anderen – lebendig statt gleichmässig.
 *
 * ## Der Wirbel am Anfang
 *
 * Vorbild ist ein „Energy Vortex", den der Benutzer gezeigt hat. Die
 * Teilchen kennen ihren Platz auf dem Ring von Anfang an; was sich über
 * die Aufbauzeit ändert, ist nur der Weg dorthin – und der wird in
 * Zylinderkoordinaten geführt, nicht geradlinig. Das ist der ganze Trick:
 * Wer zwischen zwei Punkten gerade interpoliert, bekommt einen Sog; wer
 * den Winkel getrennt vom Radius führt und ihn weiterdrehen lässt,
 * bekommt einen Wirbel.
 *
 * Draussen dreht er schnell, innen langsam, sodass er sich LEGT, statt
 * abgeschaltet zu werden. Die Tiefe fällt schneller zusammen als der
 * Radius: Der Wirbel wird erst flach und schliesst sich dann zum Ring –
 * andersherum sähe man von vorn nur einen Punkt, der grösser wird.
 *
 * Dazu bekommt jedes Teilchen einen Schweif. Er wird nicht mitgeschleppt,
 * sondern gerechnet: dieselbe Formel, einen Augenblick früher
 * ausgewertet. Am Ring fallen beide Auswertungen zusammen, die Strecke
 * wird null, und der Schweif verschwindet von selbst – ohne dass er
 * abgeschaltet werden müsste. Er ist es, der aus fliegenden Punkten
 * Energie macht: Ein Punkt zeigt, wo etwas ist, ein Strich, wohin es
 * geht.
 *
 * Der Ring selbst tritt erst hervor, wenn der Wirbel schon fast liegt.
 *
 * ## Warum das ohne eigenen Shader auskommt
 *
 * Das ist die eigentliche Entscheidung an diesem Modul, und sie ist aus
 * Schaden klug geworden. Ein früherer Kern war ein gerechneter
 * Kristallhaufen – schön gedacht, aber er erschien auf dem Rechner des
 * Benutzers nie. Die Ursache lag nicht im Aussehen, sondern in der
 * Übersetzung: Was three.js für eigene Shader zulässt, ist enger, als es
 * beim Schreiben scheint, und ein Shader, der nicht übersetzt wird,
 * zeichnet nichts – ohne Fehlerbild, einfach gar nichts.
 *
 * Hier wird deshalb nur benutzt, was in dieser Anwendung nachweislich
 * ankommt: gewöhnliche Geometrie, Standardmaterialien, Vertexfarben und
 * der bestehende Bloom-Effekt. Der Bloom ist übrigens der Grund, warum
 * das überhaupt nach Neon aussehen kann: Neon ist nicht eine Farbe,
 * sondern helles Licht, das in seine Umgebung ausblutet.
 */

import * as THREE from "three";

/** In so viele Stücke ist der Ring unterteilt. */
const SEGMENTE = 200;

/** So viele Ringe liegen übereinander und bilden das Band. */
const BAENDER = 5;

/** So viele Teilchen bilden den Wirbel und später den Saum des Rings. */
const TEILCHEN = 520;

/** So viele Teilchen bilden den Nebel im Inneren des O. */
const NEBEL = 300;

/**
 * Wie weit der Farbton des Nebels vom Ring abweicht (Anteil des Farbkreises).
 *
 * Ein Drittel, nicht die Haelfte. Die Haelfte waere die Gegenfarbe und
 * damit der groesstmoegliche Abstand - aber genau der laesst den Nebel wie
 * einen Fremdkoerper wirken, der zufaellig in der Mitte liegt. Ein Drittel
 * ist weit genug, dass man ihn als eigene Farbe liest, und nah genug, dass
 * er zum Ring gehoert.
 */
const NEBEL_VERSATZ = 0.33;

/**
 * Der Grundradius des O.
 *
 * Er ist nicht frei gewaehlt, sondern nach oben gedeckelt, und das ist
 * keine Feinheit, sondern die Groesse des Orb. Im schlimmsten Fall treffen
 * alle vier Verformungen an derselben Stelle zusammen, dazu der volle
 * Puls und die volle Stimme; dann waechst der Ring auf knapp das Doppelte.
 * Die bestehende Aura kreist bis 1.40 - was darueber hinausgeht, schneidet
 * das Fenster ab. Bei 0.70 bleibt auch dieser schlimmste Fall darunter.
 */
const RADIUS = 0.72;

/**
 * Ab hier wird der Radius weich abgefangen.
 *
 * Der Ring hat sechs Verformungen, einen Herzschlag, ein Atmen, die
 * Stimme und die Banddicke - und rein rechnerisch koennen die alle
 * gleichzeitig nach aussen zeigen. Das kommt praktisch nie vor, aber
 * "praktisch nie" ist kein Argument, wenn das Fenster abschneidet.
 */
const WEICHE_DECKE = 1.02;

/**
 * Und hierueber kommt er nie.
 *
 * Nicht hart abgeschnitten, sondern asymptotisch: Zwischen der weichen
 * Decke und diesem Wert wird die Ueberschreitung zusammengedrueckt, statt
 * sie zu kappen. Ein hartes Kappen ergaebe eine flache Stelle im Ring -
 * eine gerade Linie, wo eine Rundung sein muesste, und die faellt sofort
 * auf. Gedrueckt sieht es aus, als stiesse die Form an etwas an, und das
 * ist eher ein Gewinn als ein Fehler.
 */
const HARTE_DECKE = 1.40;

/**
 * Die Verformung: je ein Eintrag aus Ordnung, Stärke und Tempo.
 *
 * Die Ordnung – wie viele Ausbuchtungen der Ring bekommt – MUSS ganzzahlig
 * sein, sonst schliesst sich der Ring nicht. Die vier Ordnungen sind
 * teilerfremd gewählt (2, 3, 5, 7): Bei 2 und 4 lägen die Ausbuchtungen
 * der zweiten genau auf denen der ersten, und aus zwei Wellen würde
 * sichtbar eine einzige, stärkere.
 */
const VERFORMUNG: ReadonlyArray<readonly [number, number, number, number]> = [
  [2, 0.105, 0.21, 0.13],
  [3, 0.070, -0.29, 0.19],
  [5, 0.040, 0.17, 0.27],
  [7, 0.024, -0.13, 0.11],
  [11, 0.018, 0.23, 0.31],
  [13, 0.012, -0.19, 0.17],
];

/**
 * Wie stark die Staerke jeder Verformung selbst noch schwankt (0 bis 1).
 *
 * Das ist der Unterschied zwischen morphend und bloss rotierend. Bleiben
 * die Staerken fest, dreht sich immer dieselbe Rosette - schoen, aber nach
 * zehn Sekunden erkennt man das Muster. Schwankt jede Staerke in eigenem
 * Takt, ist die Form nie zweimal dieselbe: Mal tritt die zweizaehlige
 * Welle hervor und der Ring wird zur Acht, mal die dreizaehlige und er
 * wird zum Kleeblatt.
 *
 * Der vierte Wert jedes Eintrags oben ist das Tempo dieses Schwankens.
 */
const ATMUNG = 0.55;

/** Dauer des Aufbaus aus dem Wirbel, in Sekunden. */
const AUFBAU_DAUER = 3.2;

/** Dauer eines Herzschlags in Sekunden. */
const PULS_DAUER = 2.4;

/** Wie tief der Herzschlag den Ring aufweitet. */
const PULS_TIEFE = 0.13;

/**
 * Zwei Gloecken ergeben einen Herzschlag.
 *
 * Der Unterschied zu einem Sinus ist der ganze Punkt. Ein Sinus
 * schwillt und faellt gleichmaessig - das ist Atmung, keine Pulsation, und
 * das Auge liest es als Maschine. Ein Herzschlag hat einen kraeftigen
 * Schlag, kurz darauf einen schwaecheren, und dann eine Ruhe, die laenger
 * ist als beide zusammen. Erst diese Ruhe macht den Schlag zum Schlag:
 * Ohne Pause dazwischen gibt es nichts, wovon er sich abhebt.
 *
 * @param phase Wo im Schlag wir stehen (0 bis 1).
 */
function herzschlag(phase: number): number {
  return Math.min(1.0, glocke(phase, 0.0, 0.055) + glocke(phase, 0.17, 0.075) * 0.62);
}

/**
 * Eine Glocke, die einmal um die Phase herumreicht.
 *
 * Das Herumreichen ist noetig, damit der Schlag an der Nahtstelle nicht
 * abgeschnitten wird: Sein Anstieg liegt am Ende des vorigen Umlaufs.
 */
function glocke(phase: number, mitte: number, breite: number): number {
  let d = Math.abs(phase - mitte);
  if (d > 0.5) {
    d = 1.0 - d;
  }
  return Math.exp(-(d * d) / (breite * breite));
}

/**
 * Wie weit der Schweif eines Teilchens zurueckreicht, in Sekunden.
 *
 * Er wird nicht gespeichert, sondern gerechnet: Dieselbe Formel, einen
 * Augenblick frueher ausgewertet, ergibt den Ort von damals. Das ist der
 * Grund, warum hier nichts mitgeschleppt werden muss - und warum der
 * Schweif am Ring von selbst verschwindet, wo sich nichts mehr bewegt.
 *
 * Zu lang sieht aus wie ein Gitter aus Strichen, zu kurz wie Rauschen.
 */
const SCHWEIF_ZEIT = 0.085;

/**
 * Ein einfacher, wiederholbarer Zufall.
 *
 * Math.random() wäre bei jedem Start ein anderer Nebel. Das klingt nach
 * Abwechslung, ist aber beim Suchen von Fehlern lästig: Sieht der Aufbau
 * einmal falsch aus, will man genau denselben noch einmal sehen.
 */
function zufall(saat: number): () => number {
  let s = saat >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 4294967296;
  };
}

/** Weicher Verlauf: langsam los, zügig durch, sanft ankommen. */
function weich(t: number): number {
  const x = Math.max(0, Math.min(1, t));
  return x * x * (3.0 - 2.0 * x);
}

/**
 * Das pulsierende O.
 *
 * Es liegt fast in einer Ebene und kippt nur leicht – ein Ring, der sich
 * frei im Raum dreht, ist die halbe Zeit über eine Ellipse und einen
 * Wimpernschlag lang ein Strich. Als O erkennbar bleibt er nur, wenn er
 * dem Betrachter zugewandt bleibt.
 */
export class NeonRing {
  /** Die Gruppe, die alles enthält. */
  public readonly group: THREE.Group;

  private readonly band: THREE.LineSegments;
  private readonly teilchen: THREE.Points;
  private readonly schweif: THREE.LineSegments;
  private readonly nebel: THREE.Points;
  private readonly kernschein: THREE.Mesh;

  private readonly bandMaterial: THREE.LineBasicMaterial;
  private readonly teilchenMaterial: THREE.PointsMaterial;
  private readonly schweifMaterial: THREE.LineBasicMaterial;
  private readonly nebelMaterial: THREE.PointsMaterial;
  private readonly kernscheinMaterial: THREE.MeshBasicMaterial;

  /** Die Punkte der fünf Ringe – Zwischenergebnis, nicht gezeichnet. */
  private readonly ringOrte: Float32Array;
  /** Die Linienstücke, die daraus gebildet werden. */
  private readonly bandOrte: Float32Array;
  private readonly bandFarben: Float32Array;

  /** Die Farbe je Winkelschritt – einmal je Bild, von allen Bändern genutzt. */
  private readonly farbtafel: Float32Array;

  private readonly teilchenOrte: Float32Array;
  private readonly teilchenFarben: Float32Array;
  private readonly schweifOrte: Float32Array;
  private readonly schweifFarben: Float32Array;
  private readonly nebelOrte: Float32Array;
  private readonly nebelFarben: Float32Array;
  /** Fuer jedes Nebelteilchen: Bahn, Hoehe, Tempo und Phase. */
  private readonly nebelBahn: Float32Array;
  private readonly nebelHoehe: Float32Array;
  private readonly nebelTempo: Float32Array;
  private readonly nebelPhase: Float32Array;
  /** Wo auf dem Ring ein Teilchen sitzt (Winkelschritt, gebrochen). */
  private readonly teilchenStelle: Float32Array;
  /** Wie weit neben dem Ring – daraus wird der Saum. */
  private readonly teilchenAbstand: Float32Array;
  /** Woher es kommt: Richtung und Weite im Nebel. */
  private readonly nebelRichtung: Float32Array;
  private readonly nebelWeite: Float32Array;
  /** Wann es aufbricht – nicht alle gleichzeitig, sonst ist es eine Front. */
  private readonly nebelVerzug: Float32Array;

  /** Der Mittelton der Neonfarben, als Farbton auf dem Farbkreis. */
  private neonTon = 0.5;
  /**
   * Wie weit die Farben um den Mittelton streuen.
   *
   * Ein Drittel des Farbkreises nach jeder Seite. Damit laeuft das Band
   * durch zwei Dritteln aller Farbtoene - bei Blau als Mitte also von
   * Gruen ueber Blau und Violett bis Magenta. Der volle Kreis waere
   * verlockend, ergaebe aber einen Regenbogen, und ein Regenbogen sieht
   * nicht nach Energie aus, sondern nach Dekoration: Weil alle Farben
   * vorkommen, sagt keine mehr etwas.
   */
  private neonSpanne = 0.33;
  private neonHelle = 0.62;

  private stimme = 0.0;
  private staerke = 1.0;
  private aufbau = 0.0;
  /** Wo im Herzschlag wir stehen (0 bis 1) - mitgefuehrt, nicht gerechnet. */
  private pulsTakt = 0.0;
  private sichtbareBaender = BAENDER;
  private sichtbareTeilchen = TEILCHEN;

  /** Wiederverwendet – kein neues Objekt je Punkt. */
  private readonly streich = new THREE.Color();
  private readonly hsl = { h: 0, s: 0, l: 0 };
  private readonly jetzt = { x: 0, y: 0, z: 0 };
  private readonly davor = { x: 0, y: 0, z: 0 };
  private readonly nebelfarbe = new THREE.Color();
  private sichtbarerNebel = NEBEL;

  constructor() {
    this.group = new THREE.Group();

    // --- Das Band ----------------------------------------------------------
    this.ringOrte = new Float32Array(BAENDER * SEGMENTE * 3);
    this.bandOrte = new Float32Array(BAENDER * SEGMENTE * 2 * 3);
    this.bandFarben = new Float32Array(BAENDER * SEGMENTE * 2 * 3);
    this.farbtafel = new Float32Array(SEGMENTE * 3);

    const bandGeometrie = new THREE.BufferGeometry();
    bandGeometrie.setAttribute("position", new THREE.BufferAttribute(this.bandOrte, 3));
    bandGeometrie.setAttribute("color", new THREE.BufferAttribute(this.bandFarben, 3));

    this.bandMaterial = new THREE.LineBasicMaterial({
      vertexColors: true,
      transparent: true,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    this.band = new THREE.LineSegments(bandGeometrie, this.bandMaterial);
    this.band.frustumCulled = false;
    this.group.add(this.band);

    // --- Die Teilchen ------------------------------------------------------
    this.teilchenOrte = new Float32Array(TEILCHEN * 3);
    this.teilchenFarben = new Float32Array(TEILCHEN * 3);
    this.teilchenStelle = new Float32Array(TEILCHEN);
    this.teilchenAbstand = new Float32Array(TEILCHEN);
    this.nebelRichtung = new Float32Array(TEILCHEN * 3);
    this.nebelWeite = new Float32Array(TEILCHEN);
    this.nebelVerzug = new Float32Array(TEILCHEN);

    const wuerfel = zufall(20260809);
    for (let i = 0; i < TEILCHEN; i++) {
      this.teilchenStelle[i] = wuerfel() * SEGMENTE;

      // Der Abstand vom Ring ist nach innen wie nach aussen möglich und in
      // der Mitte am dichtesten: Das Quadrat drängt die meisten Teilchen
      // nah an den Ring, sodass er einen Saum bekommt und keine Wolke.
      const seite = wuerfel() < 0.5 ? -1.0 : 1.0;
      const naehe = wuerfel();
      this.teilchenAbstand[i] = seite * naehe * naehe * 0.16;

      // Die Nebelrichtung gleichverteilt auf der Kugel. Über den Kosinus
      // des Polarwinkels statt über den Winkel selbst – sonst sammelten
      // sich die Teilchen an den Polen.
      const z = wuerfel() * 2.0 - 1.0;
      const r = Math.sqrt(Math.max(0.0, 1.0 - z * z));
      const phi = wuerfel() * Math.PI * 2.0;
      this.nebelRichtung[i * 3 + 0] = Math.cos(phi) * r;
      this.nebelRichtung[i * 3 + 1] = Math.sin(phi) * r;
      // Der Nebel ist flach gedrückt: Der Ring liegt in einer Ebene, und
      // ein kugelrunder Nebel zöge sich sichtbar aus der Tiefe zusammen –
      // von vorn gesehen also aus dem Nichts.
      this.nebelRichtung[i * 3 + 2] = z * 0.45;

      this.nebelWeite[i] = 0.75 + wuerfel() * 0.65;
      this.nebelVerzug[i] = wuerfel() * 0.4;
    }

    const teilchenGeometrie = new THREE.BufferGeometry();
    teilchenGeometrie.setAttribute(
      "position",
      new THREE.BufferAttribute(this.teilchenOrte, 3)
    );
    teilchenGeometrie.setAttribute(
      "color",
      new THREE.BufferAttribute(this.teilchenFarben, 3)
    );

    this.teilchenMaterial = new THREE.PointsMaterial({
      size: 0.026,
      vertexColors: true,
      transparent: true,
      opacity: 0.95,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
      sizeAttenuation: true,
    });
    this.teilchen = new THREE.Points(teilchenGeometrie, this.teilchenMaterial);
    this.teilchen.frustumCulled = false;
    this.group.add(this.teilchen);

    // --- Die Schweife ------------------------------------------------------
    //
    // Je Teilchen ein Strich vom Jetzt zum Davor. Sie sind es, die aus
    // fliegenden Punkten Energie machen: Ein Punkt zeigt, WO etwas ist,
    // ein Strich zeigt, WOHIN es geht.
    this.schweifOrte = new Float32Array(TEILCHEN * 2 * 3);
    this.schweifFarben = new Float32Array(TEILCHEN * 2 * 3);

    const schweifGeometrie = new THREE.BufferGeometry();
    schweifGeometrie.setAttribute(
      "position",
      new THREE.BufferAttribute(this.schweifOrte, 3)
    );
    schweifGeometrie.setAttribute(
      "color",
      new THREE.BufferAttribute(this.schweifFarben, 3)
    );

    this.schweifMaterial = new THREE.LineBasicMaterial({
      vertexColors: true,
      transparent: true,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    this.schweif = new THREE.LineSegments(schweifGeometrie, this.schweifMaterial);
    this.schweif.frustumCulled = false;
    this.group.add(this.schweif);

    // --- Der Nebel in der Mitte --------------------------------------------
    //
    // Ein O ist ein Loch, und ein Loch ist leer. Was dem Bild fehlte, war
    // etwas, worum der Ring herum ist - sonst schwebt er im Nichts. Der
    // Nebel fuellt die Mitte, ohne sie zu verschliessen: Er ist duenn genug,
    // dass man hindurchsieht, und in einer anderen Farbe als der Ring,
    // damit beides nicht verschwimmt.
    this.nebelOrte = new Float32Array(NEBEL * 3);
    this.nebelFarben = new Float32Array(NEBEL * 3);
    this.nebelBahn = new Float32Array(NEBEL);
    this.nebelHoehe = new Float32Array(NEBEL);
    this.nebelTempo = new Float32Array(NEBEL);
    this.nebelPhase = new Float32Array(NEBEL);

    for (let i = 0; i < NEBEL; i++) {
      // Die Wurzel verteilt gleichmaessig ueber die FLAECHE. Ohne sie
      // klumpte alles in der Mitte, weil eine Kreisflaeche nach aussen hin
      // mehr Platz hat als innen.
      this.nebelBahn[i] = Math.sqrt(wuerfel()) * 0.62;
      this.nebelHoehe[i] = (wuerfel() - 0.5) * 0.30;
      // Innen schneller als aussen - das ist es, was einen Wirbel von
      // einer sich drehenden Scheibe unterscheidet.
      this.nebelTempo[i] = 0.35 + wuerfel() * 0.55;
      this.nebelPhase[i] = wuerfel() * Math.PI * 2.0;
    }

    const nebelGeometrie = new THREE.BufferGeometry();
    nebelGeometrie.setAttribute("position", new THREE.BufferAttribute(this.nebelOrte, 3));
    nebelGeometrie.setAttribute("color", new THREE.BufferAttribute(this.nebelFarben, 3));

    this.nebelMaterial = new THREE.PointsMaterial({
      // Deutlich groesser als die Ringteilchen und viel blasser: Was
      // Nebel ausmacht, sind grosse, schwache Flecken, die sich
      // ueberlagern. Kleine helle Punkte waeren Sterne.
      size: 0.085,
      vertexColors: true,
      transparent: true,
      opacity: 0.42,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
      sizeAttenuation: true,
    });
    this.nebel = new THREE.Points(nebelGeometrie, this.nebelMaterial);
    this.nebel.frustumCulled = false;
    this.group.add(this.nebel);

    // Ein weicher Schein dahinter, damit der Nebel einen Koerper hat und
    // nicht nur aus einzelnen Flecken besteht.
    this.kernscheinMaterial = new THREE.MeshBasicMaterial({
      transparent: true,
      opacity: 0.05,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
      side: THREE.DoubleSide,
    });
    this.kernschein = new THREE.Mesh(
      new THREE.IcosahedronGeometry(1.0, 3),
      this.kernscheinMaterial
    );
    this.group.add(this.kernschein);
  }

  /**
   * Übernimmt die Farben des Zustands.
   *
   * Neon ist keine bestimmte Farbe, sondern eine Machart: voll gesättigt,
   * hell, und in eine dunkle Umgebung ausblutend. Deshalb wird hier nicht
   * die Zustandsfarbe übernommen, sondern nur ihr FARBTON – Sättigung und
   * Helligkeit setzt dieses Modul selbst. Sonst ergäbe ein blasses Theme
   * ein blasses O, und das wäre dann kein Neon mehr.
   *
   * Was bleibt, ist die Auskunft: Im Ruhezustand steht der Farbton auf
   * Blaugrün, beim Arbeiten auf Rot, und das Band spannt sich um ihn
   * herum.
   *
   * @param kern Die Grundfarbe des Zustands.
   * @param schein Die helle Farbe des Zustands.
   * @param staerke Wie hell insgesamt.
   */
  public setColors(kern: THREE.Color, schein: THREE.Color, staerke: number): void {
    kern.getHSL(this.hsl);
    this.neonTon = this.hsl.h;

    // Eine sehr blasse Zustandsfarbe hat keinen verlässlichen Farbton –
    // bei Grau ist er beliebig. In dem Fall bleibt der bisherige stehen,
    // statt dass das O bei jedem Bild die Farbe wechselt.
    if (this.hsl.s < 0.08) {
      schein.getHSL(this.hsl);
      if (this.hsl.s >= 0.08) {
        this.neonTon = this.hsl.h;
      }
    }

    this.staerke = staerke;
    this.neonHelle = 0.52 + staerke * 0.10;
  }

  /**
   * Meldet, wie laut gerade gesprochen wird.
   *
   * @param pegel Zwischen 0 und 1, bereits geglättet.
   */
  public setVoiceLevel(pegel: number): void {
    this.stimme = Math.max(0, Math.min(1, pegel));
  }

  /** Lässt den Nebel noch einmal von vorn zusammenlaufen. */
  public restartIntro(): void {
    this.aufbau = 0.0;
  }

  /**
   * Pulsiert, morpht und zieht beim ersten Mal den Nebel zusammen.
   *
   * @param elapsed Laufzeit in Sekunden.
   * @param delta Zeit seit dem letzten Bild.
   * @param tempo Geschwindigkeit des Zustands.
   */
  public update(elapsed: number, delta: number, tempo: number): void {
    this.aufbau = Math.min(AUFBAU_DAUER + 1.0, this.aufbau + delta);
    const fortschritt = Math.min(1.0, this.aufbau / AUFBAU_DAUER);

    // Der Herzschlag wird MITGEFUEHRT, nicht aus der Laufzeit gerechnet.
    // Aus elapsed * tempo folgte sonst: Sobald sich das Tempo aendert -
    // und das tut es bei jedem Zustandswechsel -, springt der Schlag
    // mitten hinein.
    this.pulsTakt = (this.pulsTakt + (delta * tempo) / PULS_DAUER) % 1.0;

    // Ein ruhiges Atmen darunter, damit zwischen den Schlaegen nichts
    // stillsteht. Der Schlag selbst liegt nicht hier, sondern im Ring -
    // dort LAEUFT er um, statt ueberall gleichzeitig zu geschehen.
    const atem = Math.sin(elapsed * 0.55 * tempo) * 0.030;
    const weite = RADIUS * (1.0 + atem + this.stimme * 0.20);

    // Beim Sprechen morpht er stärker. Das ist der Grund, warum das O
    // überhaupt mit der Stimme verbunden ist: Ein Bild, das sich synchron
    // zum Klang verändert, ordnet das Auge derselben Ursache zu.
    const kraft = 1.0 + this.stimme * 1.35;

    // Der Mittelpunkt wandert langsam. Eine Summe von Sinuswellen ist um
    // den Ursprung immer ausgewogen, und Ausgewogenheit ist genau das,
    // was an einer gerechneten Form kuenstlich wirkt: Nichts Lebendiges
    // ist um seinen eigenen Mittelpunkt symmetrisch.
    const mx = Math.sin(elapsed * 0.13) * 0.055 + Math.sin(elapsed * 0.31 + 2.0) * 0.022;
    const my = Math.sin(elapsed * 0.17 + 1.2) * 0.055 + Math.sin(elapsed * 0.27) * 0.022;

    this.ringSetzen(elapsed, tempo, weite, kraft, mx * weite, my * weite);
    this.farbenSetzen(elapsed, tempo, fortschritt);
    this.bandSetzen();
    this.teilchenSetzen(elapsed, fortschritt);
    this.nebelSetzen(elapsed, tempo, weite, fortschritt);

    // Ein leichtes Kippen, damit das O im Raum steht und nicht aufgeklebt
    // wirkt – aber wenig genug, dass es ein O bleibt und keine Ellipse.
    this.group.rotation.x = Math.sin(elapsed * 0.23) * 0.20;
    this.group.rotation.y = Math.sin(elapsed * 0.19 + 1.1) * 0.24;
    this.group.rotation.z = Math.sin(elapsed * 0.11) * 0.10;
  }

  // --- Innenleben --------------------------------------------------------------

  /** Rechnet die Punkte der fünf Ringe. */
  private ringSetzen(
    elapsed: number,
    tempo: number,
    weite: number,
    kraft: number,
    mx: number,
    my: number
  ): void {
    for (let b = 0; b < BAENDER; b++) {
      // Die Bänder liegen versetzt und morphen leicht gegeneinander. Der
      // Versatz in der Phase ist wichtiger als der im Radius: Ohne ihn
      // blieben es fünf parallele Linien, mit ihm kreuzen sie sich.
      const spreizung = (b - (BAENDER - 1) * 0.5) / ((BAENDER - 1) * 0.5);
      const phase = spreizung * 0.55;

      for (let s = 0; s < SEGMENTE; s++) {
        const anteil = s / SEGMENTE;
        const theta = anteil * Math.PI * 2.0;

        // Der Schlag LAEUFT um den Ring, statt ueberall gleichzeitig zu
        // geschehen. Das ist der Unterschied zwischen einem Ring, der
        // groesser und kleiner wird, und einem, durch den etwas
        // hindurchgeht.
        //
        // Der Versatz betraegt ueber einen vollen Umlauf genau EINEN
        // Schlag. Nur deshalb schliesst sich der Ring: Die Phase am Ende
        // ist um 1 verschoben, und der Herzschlag hat die Periode 1.
        let lokal = (this.pulsTakt - anteil) % 1.0;
        if (lokal < 0) {
          lokal += 1.0;
        }
        const schlag = herzschlag(lokal);

        // Die Dicke des Bandes schwankt um den Ring herum. Gleichmaessig
        // gespreizte Baender lesen sich als gezeichnete Flaeche; hier
        // schwillt das Band an manchen Stellen an und wird an anderen zur
        // Linie. Ganzzahlige Ordnungen, also geschlossen.
        const dicke =
          0.55 +
          0.45 * Math.sin(2.0 * theta + elapsed * 0.31) +
          0.30 * Math.sin(3.0 * theta - elapsed * 0.19);
        const radiusFaktor = 1.0 + spreizung * 0.055 * (0.6 + Math.abs(dicke));

        let r = 1.0 + PULS_TIEFE * schlag;
        for (let v = 0; v < VERFORMUNG.length; v++) {
          const ordnung = VERFORMUNG[v][0];
          const staerke = VERFORMUNG[v][1];
          const lauf = VERFORMUNG[v][2];
          const puls = VERFORMUNG[v][3];

          // Die Staerke atmet mit. Sie haengt NUR an der Zeit und nicht am
          // Winkel - deshalb bleibt der Ring geschlossen, obwohl sich seine
          // Form staendig aendert.
          const lebend =
            staerke *
            (1.0 - ATMUNG + ATMUNG * (0.5 + 0.5 * Math.sin(elapsed * puls + v * 2.1)));

          // Die Phase WANDERT, statt gleichmaessig fortzuschreiten.
          //
          // Ein linear wachsender Winkel dreht das Muster - und eine sich
          // drehende Rosette erkennt das Auge nach wenigen Sekunden als
          // starren Koerper, ganz gleich wie verwickelt sie ist. Eine
          // Summe langsamer Sinuswellen laesst sie stattdessen vor- und
          // zurueckkriechen: Sie kommt nie an und wiederholt sich nie
          // sichtbar.
          const wandern =
            Math.sin(elapsed * lauf * 0.7 * tempo) * 2.4 +
            Math.sin(elapsed * lauf * 0.27 * tempo + 1.7) * 3.6 +
            elapsed * lauf * 0.20 * tempo;

          r += lebend * kraft * Math.sin(ordnung * theta + wandern + phase);
        }
        r *= weite * radiusFaktor;

        // Die weiche Decke. Unterhalb passiert nichts; darueber naehert
        // sich der Wert der harten Decke an, ohne sie je zu erreichen.
        if (r > WEICHE_DECKE) {
          const spielraum = HARTE_DECKE - WEICHE_DECKE;
          r = WEICHE_DECKE + spielraum * (1.0 - Math.exp(-(r - WEICHE_DECKE) / spielraum));
        }

        // Eine leichte Auslenkung aus der Ebene, ebenfalls ganzzahlig in
        // der Ordnung. Sie gibt dem O eine Tiefe, ohne dass es aufhört,
        // ein O zu sein.
        const z =
          Math.sin(3.0 * theta - elapsed * 0.24 * tempo + phase) *
          weite *
          0.10 *
          kraft;

        const k = (b * SEGMENTE + s) * 3;
        this.ringOrte[k + 0] = Math.cos(theta) * r + mx;
        this.ringOrte[k + 1] = Math.sin(theta) * r + my;
        this.ringOrte[k + 2] = z;
      }
    }
  }

  /** Legt die Neonfarben für einen Umlauf fest. */
  private farbenSetzen(elapsed: number, tempo: number, fortschritt: number): void {
    // Solange der Nebel läuft, ist das Band kaum da. Es tritt hervor, wie
    // sich der Nebel zusammenzieht – das ist es, was den Aufbau zum
    // Entstehen macht statt zum Einblenden. Quadratisch, damit das Band
    // spät kommt und der Nebel die erste Sekunde für sich hat.
    const vorhang = fortschritt * fortschritt;
    const helligkeit = (0.55 + 0.45 * this.stimme) * vorhang;

    for (let s = 0; s < SEGMENTE; s++) {
      const anteil = s / SEGMENTE;
      const theta = anteil * Math.PI * 2.0;

      // Derselbe Schlag wie im Ring, an derselben Stelle: Was sich
      // aufweitet, leuchtet auch. Zwei getrennte Vorgaenge - hier heller,
      // dort weiter - liest das Auge als zwei Ursachen; derselbe Wert an
      // beiden Stellen macht daraus einen einzigen Puls, der durchlaeuft.
      let lokal = (this.pulsTakt - anteil) % 1.0;
      if (lokal < 0) {
        lokal += 1.0;
      }
      const schlag = herzschlag(lokal);

      // Der Farbton wandert um den Ring – zweimal herum, in ganzen
      // Wellen, damit er sich schliesst. Dazu ein langsamer Umlauf mit
      // der Zeit: So kriecht die Farbe um das O, statt zu stehen.
      // Drei Wellen statt zwei, alle ganzzahlig: So schliesst sich auch
      // der Farbverlauf, und es entstehen mehr Uebergaenge, ohne dass
      // Streifen sichtbar werden.
      const ton =
        this.neonTon +
        this.neonSpanne * Math.sin(1.0 * theta + elapsed * 0.35 * tempo) +
        this.neonSpanne * 0.50 * Math.sin(2.0 * theta - elapsed * 0.22 * tempo) +
        this.neonSpanne * 0.28 * Math.sin(3.0 * theta + elapsed * 0.14 * tempo);

      // Volle Sättigung, hohe Helligkeit: Das ist es, was Neon ausmacht.
      // Der Bloom macht daraus den Schein. Auf dem Schlag geht die
      // Helligkeit weiter hoch - und der Farbton dort ein Stueck mit, weil
      // heisses Licht seine Farbe verschiebt und das Auge das erwartet.
      this.streich.setHSL(
        (((ton + schlag * 0.06) % 1.0) + 1.0) % 1.0,
        1.0 - schlag * 0.18,
        Math.min(0.92, this.neonHelle + this.stimme * 0.12 + schlag * 0.20)
      );

      const hell = helligkeit * (1.0 + schlag * 0.85);
      this.farbtafel[s * 3 + 0] = this.streich.r * hell;
      this.farbtafel[s * 3 + 1] = this.streich.g * hell;
      this.farbtafel[s * 3 + 2] = this.streich.b * hell;
    }
  }

  /** Baut aus den Ringpunkten die Linienstücke – geschlossen. */
  private bandSetzen(): void {
    let punkt = 0;
    for (let b = 0; b < BAENDER; b++) {
      // Das innerste Band ist das hellste. Nach aussen wird es blasser,
      // und daraus entsteht der Eindruck eines Glimmens statt einer
      // Zeichnung.
      const mitte = (BAENDER - 1) * 0.5;
      const rand = Math.abs(b - mitte) / mitte;
      let gewicht = 1.0 - rand * 0.62;
      if (b >= this.sichtbareBaender) {
        gewicht = 0.0;
      }

      for (let s = 0; s < SEGMENTE; s++) {
        // Der Umlauf schliesst sich hier, im Modulo: Das letzte Stück
        // verbindet den letzten Punkt mit dem ersten. Ohne das bliebe das
        // O an einer Stelle offen – ein C.
        const a = (b * SEGMENTE + s) * 3;
        const c = (b * SEGMENTE + ((s + 1) % SEGMENTE)) * 3;

        for (const q of [a, c]) {
          this.bandOrte[punkt * 3 + 0] = this.ringOrte[q + 0];
          this.bandOrte[punkt * 3 + 1] = this.ringOrte[q + 1];
          this.bandOrte[punkt * 3 + 2] = this.ringOrte[q + 2];
          punkt += 1;
        }

        const f0 = s * 3;
        const f1 = ((s + 1) % SEGMENTE) * 3;
        const ziel = (punkt - 2) * 3;
        this.bandFarben[ziel + 0] = this.farbtafel[f0 + 0] * gewicht;
        this.bandFarben[ziel + 1] = this.farbtafel[f0 + 1] * gewicht;
        this.bandFarben[ziel + 2] = this.farbtafel[f0 + 2] * gewicht;
        this.bandFarben[ziel + 3] = this.farbtafel[f1 + 0] * gewicht;
        this.bandFarben[ziel + 4] = this.farbtafel[f1 + 1] * gewicht;
        this.bandFarben[ziel + 5] = this.farbtafel[f1 + 2] * gewicht;
      }
    }

    (this.band.geometry.getAttribute("position") as THREE.BufferAttribute).needsUpdate =
      true;
    (this.band.geometry.getAttribute("color") as THREE.BufferAttribute).needsUpdate =
      true;
  }

  /**
   * Rechnet, wo ein Teilchen zu einem Zeitpunkt und Fortschritt steht.
   *
   * Ausgelagert, weil es zweimal je Bild gebraucht wird: einmal für das
   * Jetzt und einmal für einen Augenblick davor. Aus der Strecke zwischen
   * beiden wird der Schweif – die Bewegungsspur, die aus fliegenden
   * Punkten Energie macht.
   */
  private wirbelOrt(
    i: number,
    elapsed: number,
    eigen: number,
    zx: number,
    zy: number,
    zz: number,
    ziel: { x: number; y: number; z: number }
  ): void {
    if (eigen >= 1.0) {
      ziel.x = zx;
      ziel.y = zy;
      ziel.z = zz;
      return;
    }

    // Gerechnet wird in Zylinderkoordinaten um die Achse des Rings:
    // Radius, Winkel und Tiefe getrennt. Das ist der ganze Unterschied
    // zwischen Sog und Wirbel – zwischen zwei Punkten gerade zu
    // interpolieren ergäbe einen Trichter aus Strichen.
    const dx = this.nebelRichtung[i * 3 + 0];
    const dy = this.nebelRichtung[i * 3 + 1];
    const dz = this.nebelRichtung[i * 3 + 2];

    const startWinkel = Math.atan2(dy, dx);
    const startRadius = this.nebelWeite[i] * Math.sqrt(dx * dx + dy * dy);
    const startTiefe = dz * this.nebelWeite[i];

    const zielWinkel = Math.atan2(zy, zx);
    const zielRadius = Math.sqrt(zx * zx + zy * zy);

    // Draussen dreht der Wirbel schnell, innen langsam. So LEGT sich der
    // Wirbel, statt abgeschaltet zu werden – und das ist der Unterschied
    // zwischen einem Aufbau und einem Schnitt.
    const drall = 2.4 + (1.0 - eigen) * 5.5;
    const winkel =
      startWinkel + (zielWinkel - startWinkel) * eigen + elapsed * drall * 0.32;

    // Der Bauch: Die Teilchen kommen nicht schnurgerade herein, sondern
    // holen erst nach aussen aus. Ein Wirbel saugt nicht, er reisst mit.
    const bauch = Math.sin(eigen * Math.PI) * 0.16;
    const radius = startRadius + (zielRadius - startRadius) * eigen + bauch;

    // Die Tiefe fällt schneller zusammen als der Radius: Der Wirbel wird
    // erst flach und schliesst sich dann zum Ring. Andersherum sähe man
    // von vorn nur einen Punkt, der grösser wird.
    const flach = eigen * eigen;
    const tiefe = startTiefe + (zz - startTiefe) * flach;

    ziel.x = Math.cos(winkel) * radius;
    ziel.y = Math.sin(winkel) * radius;
    ziel.z = tiefe;
  }

  /** Zieht den Wirbel zusammen und legt die Teilchen an den Ring. */
  private teilchenSetzen(elapsed: number, fortschritt: number): void {
    const anzahl = this.sichtbareTeilchen;
    const mitte = Math.floor((BAENDER - 1) * 0.5);

    for (let i = 0; i < anzahl; i++) {
      // Der Platz auf dem Ring: zwischen zwei Ringpunkten interpoliert,
      // damit die Teilchen nicht auf den Segmentgrenzen kleben.
      const stelle = this.teilchenStelle[i];
      const s0 = Math.floor(stelle) % SEGMENTE;
      const s1 = (s0 + 1) % SEGMENTE;
      const t = stelle - Math.floor(stelle);

      const a = (mitte * SEGMENTE + s0) * 3;
      const c = (mitte * SEGMENTE + s1) * 3;

      let zx = this.ringOrte[a + 0] + (this.ringOrte[c + 0] - this.ringOrte[a + 0]) * t;
      let zy = this.ringOrte[a + 1] + (this.ringOrte[c + 1] - this.ringOrte[a + 1]) * t;
      let zz = this.ringOrte[a + 2] + (this.ringOrte[c + 2] - this.ringOrte[a + 2]) * t;

      // Der Saum: nach innen oder aussen versetzt, entlang der Richtung
      // vom Mittelpunkt weg. Das ist bei einem Ring dieselbe Richtung wie
      // die Normale, solange er nicht zu stark verformt ist – und billiger
      // als eine echte Normale.
      const laenge = Math.sqrt(zx * zx + zy * zy) || 1.0;
      const ab = this.teilchenAbstand[i];
      zx += (zx / laenge) * ab;
      zy += (zy / laenge) * ab;

      // Ein feines Zittern, damit der Saum nicht wie aufgefädelt wirkt.
      const leben = 0.006 + this.stimme * 0.030;
      zx += Math.sin(elapsed * 2.9 + i * 1.7) * leben;
      zy += Math.sin(elapsed * 3.3 + i * 0.9) * leben;
      zz += Math.sin(elapsed * 2.5 + i * 2.3) * leben;

      // Der eigene Fortschritt – wer später aufbricht, kommt später an.
      // Das macht aus einer Front einen Wirbel.
      const eigen = weich(
        (fortschritt - this.nebelVerzug[i]) / (1.0 - this.nebelVerzug[i])
      );
      const vorher = weich(
        (fortschritt - SCHWEIF_ZEIT / AUFBAU_DAUER - this.nebelVerzug[i]) /
          (1.0 - this.nebelVerzug[i])
      );

      this.wirbelOrt(i, elapsed, eigen, zx, zy, zz, this.jetzt);
      this.wirbelOrt(i, elapsed - SCHWEIF_ZEIT, vorher, zx, zy, zz, this.davor);

      this.teilchenOrte[i * 3 + 0] = this.jetzt.x;
      this.teilchenOrte[i * 3 + 1] = this.jetzt.y;
      this.teilchenOrte[i * 3 + 2] = this.jetzt.z;

      // Der Schweif: vom Jetzt zurück zum Davor. Am Ring fallen beide
      // zusammen und die Strecke wird zu null – der Schweif verschwindet
      // also von selbst, ohne dass er abgeschaltet werden müsste.
      this.schweifOrte[i * 6 + 0] = this.jetzt.x;
      this.schweifOrte[i * 6 + 1] = this.jetzt.y;
      this.schweifOrte[i * 6 + 2] = this.jetzt.z;
      this.schweifOrte[i * 6 + 3] = this.davor.x;
      this.schweifOrte[i * 6 + 4] = this.davor.y;
      this.schweifOrte[i * 6 + 5] = this.davor.z;

      // Im Wirbel sind die Teilchen matt und breit gestreut; am Ring
      // leuchten sie. Ganz verschwinden dürfen sie danach nicht, sonst
      // fehlte dem O der Saum, aus dem es gekommen ist.
      const hell = (0.30 + eigen * 0.85) * (0.55 + this.staerke * 0.45);
      const f = (s0 * 3) % (SEGMENTE * 3);
      const cr = this.farbtafel[f + 0] * hell + 0.03;
      const cg = this.farbtafel[f + 1] * hell + 0.03;
      const cb = this.farbtafel[f + 2] * hell + 0.05;

      this.teilchenFarben[i * 3 + 0] = cr;
      this.teilchenFarben[i * 3 + 1] = cg;
      this.teilchenFarben[i * 3 + 2] = cb;

      // Der Schweif verglüht nach hinten: vorn so hell wie das Teilchen,
      // hinten dunkel. Sonst wären es Striche und keine Spuren.
      this.schweifFarben[i * 6 + 0] = cr * 0.9;
      this.schweifFarben[i * 6 + 1] = cg * 0.9;
      this.schweifFarben[i * 6 + 2] = cb * 0.9;
      this.schweifFarben[i * 6 + 3] = 0;
      this.schweifFarben[i * 6 + 4] = 0;
      this.schweifFarben[i * 6 + 5] = 0;
    }

    // Was nicht gezeichnet wird, wird schwarz – auf die Zahl der Punkte in
    // der Geometrie lässt sich nicht ohne Neubau einwirken.
    for (let i = anzahl; i < TEILCHEN; i++) {
      this.teilchenFarben[i * 3 + 0] = 0;
      this.teilchenFarben[i * 3 + 1] = 0;
      this.teilchenFarben[i * 3 + 2] = 0;
      for (let k = 0; k < 6; k++) {
        this.schweifFarben[i * 6 + k] = 0;
      }
    }

    (
      this.teilchen.geometry.getAttribute("position") as THREE.BufferAttribute
    ).needsUpdate = true;
    (this.teilchen.geometry.getAttribute("color") as THREE.BufferAttribute).needsUpdate =
      true;
    (
      this.schweif.geometry.getAttribute("position") as THREE.BufferAttribute
    ).needsUpdate = true;
    (this.schweif.geometry.getAttribute("color") as THREE.BufferAttribute).needsUpdate =
      true;
  }

  /** Legt den Nebel in die Mitte des O. */
  private nebelSetzen(
    elapsed: number,
    tempo: number,
    weite: number,
    fortschritt: number
  ): void {
    // Der Nebel kommt spaeter als das Band: erst der Wirbel, dann der
    // Ring, dann fuellt sich die Mitte. Die dritte Potenz sorgt dafuer,
    // dass er wirklich zuletzt erscheint und nicht mit dem Ring zusammen.
    const vorhang = fortschritt * fortschritt * fortschritt;
    const anzahl = this.sichtbarerNebel;

    // Der Farbton des Nebels weicht vom Ring ab - das ist der ganze Punkt.
    // Volle Saettigung, aber weniger hell als der Ring: Nebel leuchtet
    // nicht, er streut. Waere er gleich hell, verschwaende der Ring darin.
    // Und der Nebel VERFAERBT sich, statt eine feste Farbe zu haben.
    //
    // Ein Nebel mit fester Farbe ist ein gefaerbter Fleck; einer, dessen
    // Farbe langsam durchzieht, wirkt wie etwas, in dem sich etwas
    // abspielt. Der Versatz schwankt dafuer um seinen Mittelwert, in zwei
    // ungleichen Takten - ein einzelner waere wieder ein erkennbares Hin
    // und Her.
    //
    // Der Abstand zum Ring bleibt dabei gross genug: Bei einem Mittel von
    // einem Drittel und einem Ausschlag von zusammen 0.155 faellt er nie
    // unter ein Sechstel des Farbkreises. Darunter verschwaemme beides.
    const wandel =
      NEBEL_VERSATZ +
      Math.sin(elapsed * 0.11) * 0.10 +
      Math.sin(elapsed * 0.047 + 2.3) * 0.055;

    this.nebelfarbe.setHSL(
      (((this.neonTon + wandel) % 1.0) + 1.0) % 1.0,
      0.95,
      0.42 + this.stimme * 0.16
    );

    for (let i = 0; i < anzahl; i++) {
      // Innen dreht der Nebel schneller als aussen. Das ist es, was einen
      // Wirbel von einer sich drehenden Scheibe unterscheidet - eine
      // Scheibe erkennt man sofort als starren Koerper.
      const bahn = this.nebelBahn[i];
      const innen = 1.0 - bahn * 0.7;
      const winkel =
        this.nebelPhase[i] + elapsed * this.nebelTempo[i] * innen * tempo * 0.7;

      // Und er wallt: Der Radius jedes Teilchens schwankt langsam in
      // eigenem Takt. Ohne das waere es ein Muster aus Punkten auf
      // Kreisbahnen, und Muster liest das Auge sofort als Mechanik.
      const wallen =
        1.0 + Math.sin(elapsed * 0.55 + this.nebelPhase[i] * 1.7) * 0.22;
      const r = bahn * weite * wallen * (1.0 + this.stimme * 0.18);

      this.nebelOrte[i * 3 + 0] = Math.cos(winkel) * r;
      this.nebelOrte[i * 3 + 1] = Math.sin(winkel) * r;
      this.nebelOrte[i * 3 + 2] =
        this.nebelHoehe[i] * weite +
        Math.sin(elapsed * 0.8 + this.nebelPhase[i]) * 0.04;

      // Zur Mitte hin dichter. Der Nebel soll einen Kern haben und nicht
      // an der Innenkante des Rings am hellsten sein.
      const dichte = (1.0 - bahn * 0.65) * (0.55 + this.staerke * 0.45) * vorhang;

      // Nicht alle Flecken haben denselben Ton. Eine einzige Farbe fuer
      // den ganzen Nebel ergaebe eine flache Scheibe; hier liegt ueber
      // dem Wandern noch eine Streuung von Fleck zu Fleck, die selbst
      // langsam durchzieht. Das ist es, was Schwaden ergibt statt Flaeche.
      const eigen =
        Math.sin(elapsed * 0.23 + this.nebelPhase[i] * 2.7) * 0.055 +
        Math.sin(elapsed * 0.09 + this.nebelPhase[i]) * 0.045;
      this.streich.setHSL(
        (((this.neonTon + wandel + eigen) % 1.0) + 1.0) % 1.0,
        0.95,
        0.42 + this.stimme * 0.16
      );

      this.nebelFarben[i * 3 + 0] = this.streich.r * dichte;
      this.nebelFarben[i * 3 + 1] = this.streich.g * dichte;
      this.nebelFarben[i * 3 + 2] = this.streich.b * dichte;
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

    // Der Schein dahinter atmet mit und bleibt INNERHALB des Rings: Waere
    // er groesser, laege ein Schleier ueber dem Band und die Farben des
    // Rings verwaschen.
    this.kernschein.scale.setScalar(
      weite * 0.66 * (1.0 + Math.sin(elapsed * 0.6) * 0.06 + this.stimme * 0.14)
    );
    this.kernscheinMaterial.color.copy(this.nebelfarbe);
    this.kernscheinMaterial.opacity = 0.05 * vorhang * (1.0 + this.stimme * 0.8);
  }

  /** Passt den Aufwand an die Leistungsstufe an. */
  public setQuality(level: number): void {
    // Die äusseren Bänder entfallen zuerst: Sie tragen den Schein, aber
    // das O bleibt ohne sie ein O. Mindestens eines bleibt immer stehen –
    // ohne Band gäbe es nichts mehr zu sehen.
    this.sichtbareBaender = level >= 2 ? BAENDER : level >= 1 ? 3 : 1;
    this.sichtbareTeilchen =
      level >= 2 ? TEILCHEN : level >= 1 ? Math.floor(TEILCHEN * 0.5) : Math.floor(TEILCHEN * 0.2);

    // Der Nebel kostet am meisten Fuellrate, weil seine Flecken gross sind
    // und sich ueberlagern. Auf der untersten Stufe faellt er ganz weg -
    // das O bleibt ohne ihn ein O.
    this.sichtbarerNebel = level >= 2 ? NEBEL : level >= 1 ? Math.floor(NEBEL * 0.45) : 0;
    this.kernschein.visible = level >= 1;
  }

  /** Gibt alle GPU-Ressourcen frei. */
  public dispose(): void {
    this.band.geometry.dispose();
    this.teilchen.geometry.dispose();
    this.schweif.geometry.dispose();
    this.nebel.geometry.dispose();
    this.kernschein.geometry.dispose();
    this.bandMaterial.dispose();
    this.teilchenMaterial.dispose();
    this.schweifMaterial.dispose();
    this.nebelMaterial.dispose();
    this.kernscheinMaterial.dispose();
  }
}
