/**
 * dual_orbit.ts – zwei Kugeln, die einander umkreisen, und nie zweimal gleich.
 *
 * Der Benutzer wollte zwei Kugeln, die sich umeinander bewegen – „aber
 * nicht immer in der gleichen Reihenfolge, sondern immer unterschiedlich",
 * mit Farben, die sich dynamisch verändern, und einem Nebel darum herum.
 *
 * ## Warum kein Zufall
 *
 * Zufall ist das Naheliegende und das Falsche. Er sieht nicht nach
 * Unvorhersehbarkeit aus, sondern nach Zittern: Jedes Bild springt die
 * Bahn ein Stück, es entsteht kein Zusammenhang, und was man sieht, ist
 * Rauschen. Das Auge erkennt den Unterschied zwischen „ich kann nicht
 * vorhersagen, wohin es geht" und „es geht nirgendwohin" sofort.
 *
 * Geführt wird die Bewegung stattdessen von einem **Lorenz-System** –
 * denselben drei Gleichungen, die das Wetter unvorhersagbar machen:
 *
 *     dx = σ(y − x)
 *     dy = x(ρ − z) − y
 *     dz = xy − βz
 *
 * Es ist vollkommen deterministisch und kehrt trotzdem nie in denselben
 * Zustand zurück. Dabei bleibt es in einem begrenzten Bereich: Die Bahn
 * läuft nicht davon, sie kommt nur nie an.
 *
 * Der eigentliche Gewinn liegt in den zwei Flügeln des Attraktors. Das
 * System kreist eine Weile um den einen, springt dann auf den anderen –
 * und WANN, ist nicht vorhersagbar. Aus diesen Sprüngen wird hier das
 * Umschlagen der ganzen Bahnebene, also genau das, was man als „jetzt
 * macht es etwas anderes" wahrnimmt.
 *
 * ## Woraus es besteht
 *
 * Vier Lagen:
 *
 *   1. Zwei Kugeln, jede eine Wolke aus Punkten auf eigenen kleinen
 *      Bahnen. Eine Fläche wäre ein Ball; eine Wolke lebt.
 *   2. Ihre Schweife – die Strecke, die sie gerade zurückgelegt haben.
 *   3. Der Nebel ringsum, in einem eigenen Farbton, nach aussen weich
 *      verblassend.
 *   4. Die Farben selbst, die mit der Lorenz-Bahn wandern und ineinander
 *      übergehen, wenn sich die Kugeln nähern.
 *
 * ## Warum das ohne eigenen Shader auskommt
 *
 * Ein früherer Kern war ein gerechneter Kristallhaufen – schön gedacht,
 * aber er erschien auf dem Rechner des Benutzers nie. Was three.js für
 * eigene Shader zulässt, ist enger, als es beim Schreiben scheint, und ein
 * Shader, der nicht übersetzt wird, zeichnet nichts – ohne Fehlerbild,
 * einfach gar nichts. Hier wird nur benutzt, was in dieser Anwendung
 * nachweislich ankommt.
 */

import * as THREE from "three";

/** So viele Punkte bildet jede der beiden Kugeln. */
const JE_KUGEL = 320;

/**
 * So viele Glieder hat ein Schweif.
 *
 * Der Schweif wird aus den zuletzt zurueckgelegten Orten gebaut - ein
 * Glied je Bild. Bei 60 Bildern in der Sekunde entspricht die Zahl also
 * unmittelbar einer Zeitspanne: 120 Glieder sind zwei Sekunden Bahn.
 *
 * Das ist der Punkt, an dem sich entscheidet, ob man die BAHN sieht oder
 * nur einen Strich hinter der Kugel. Mit einer knappen halben Sekunde
 * sieht man, dass sie sich bewegt; mit zwei Sekunden sieht man, WIE - die
 * Schleife, die sie gerade zieht, steht als Ganzes im Bild, und wenn das
 * Lorenz-System auf seinen anderen Fluegel springt, sieht man den Knick.
 */
const SCHWEIF = 120;

/** So viele Flecken bilden den Nebel ringsum. */
const NEBEL = 420;

/** Der Grundabstand der beiden Kugeln von der Mitte. */
const ABSTAND = 0.52;

/** Wie weit ein Punkt von seiner Kugelmitte abschweift. */
const KUGEL_RADIUS = 0.20;

/**
 * Die Obergrenze für alles, was gezeichnet wird.
 *
 * Die bestehende Aura kreist bis 1.40; was darüber hinausgeht, schneidet
 * das Fenster ab. Der Nebel verblasst zusätzlich weich nach aussen, damit
 * er nirgends eine Kante hat.
 */
const HARTE_DECKE = 1.34;

// --- Das Lorenz-System ---------------------------------------------------------
const SIGMA = 10.0;
const RHO = 28.0;
const BETA = 8.0 / 3.0;

/** Ein einfacher, wiederholbarer Zufall – nur für den Aufbau, nie im Lauf. */
function zufall(saat: number): () => number {
  let s = saat >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 4294967296;
  };
}

/**
 * Zwei Kugeln in einer Bahn, die sich nie wiederholt.
 */
export class DualOrbit {
  /** Die Gruppe, die alles enthält. */
  public readonly group: THREE.Group;

  private readonly kugelA: THREE.Points;
  private readonly kugelB: THREE.Points;
  private readonly schweifA: THREE.LineSegments;
  private readonly schweifB: THREE.LineSegments;
  private readonly nebel: THREE.Points;

  private readonly kugelMaterial: THREE.PointsMaterial;
  private readonly schweifMaterial: THREE.LineBasicMaterial;
  private readonly nebelMaterial: THREE.PointsMaterial;

  private readonly aOrte: Float32Array;
  private readonly aFarben: Float32Array;
  private readonly bOrte: Float32Array;
  private readonly bFarben: Float32Array;
  private readonly saOrte: Float32Array;
  private readonly saFarben: Float32Array;
  private readonly sbOrte: Float32Array;
  private readonly sbFarben: Float32Array;
  private readonly nOrte: Float32Array;
  private readonly nFarben: Float32Array;

  // Für jeden Punkt einer Kugel: seine kleine Eigenbahn.
  private readonly kBahn: Float32Array;
  private readonly kTempo: Float32Array;
  private readonly kPhase: Float32Array;
  private readonly kNeigung: Float32Array;

  // Für jeden Nebelfleck.
  private readonly nBahn: Float32Array;
  private readonly nWinkel: Float32Array;
  private readonly nHoehe: Float32Array;
  private readonly nTempo: Float32Array;
  private readonly nPhase: Float32Array;

  /** Der Zustand des Lorenz-Systems. */
  private lx = 0.9;
  private ly = 1.2;
  private lz = 22.0;

  /** Die zurückgelegten Orte der beiden Kugeln – für die Schweife. */
  private readonly spurA: THREE.Vector3[] = [];
  private readonly spurB: THREE.Vector3[] = [];

  private neonTon = 0.55;
  private stimme = 0.0;
  private staerke = 1.0;
  private winkel = 0.0;
  /** Die geglaetteten Groessen – sie folgen der Lorenz-Bahn mit Traegheit. */
  private abstand = ABSTAND;
  private drehTempo = 0.75;
  private aufbau = 0.0;
  private sichtbarerNebel = NEBEL;

  // Wiederverwendet – kein neues Objekt je Bild.
  private readonly streich = new THREE.Color();
  private readonly hsl = { h: 0, s: 0, l: 0 };
  private readonly achse = new THREE.Vector3(0, 1, 0);
  private readonly zielAchse = new THREE.Vector3(0, 1, 0);
  private readonly quer1 = new THREE.Vector3();
  private readonly quer2 = new THREE.Vector3();
  private readonly hilf = new THREE.Vector3();
  private readonly mitteA = new THREE.Vector3();
  private readonly mitteB = new THREE.Vector3();

  constructor() {
    this.group = new THREE.Group();

    const wuerfel = zufall(20260811);

    // --- Die beiden Kugeln -------------------------------------------------
    this.aOrte = new Float32Array(JE_KUGEL * 3);
    this.aFarben = new Float32Array(JE_KUGEL * 3);
    this.bOrte = new Float32Array(JE_KUGEL * 3);
    this.bFarben = new Float32Array(JE_KUGEL * 3);

    this.kBahn = new Float32Array(JE_KUGEL);
    this.kTempo = new Float32Array(JE_KUGEL);
    this.kPhase = new Float32Array(JE_KUGEL);
    this.kNeigung = new Float32Array(JE_KUGEL);
    for (let i = 0; i < JE_KUGEL; i++) {
      // Der Exponent unter eins drängt die Punkte nach innen: Eine Kugel
      // mit gleichmässig verteilten Punkten hat einen hohlen Kern und
      // sieht aus wie eine Schale.
      this.kBahn[i] = Math.pow(wuerfel(), 0.65) * KUGEL_RADIUS;
      this.kTempo[i] = 0.6 + wuerfel() * 1.7;
      this.kPhase[i] = wuerfel() * Math.PI * 2.0;
      this.kNeigung[i] = (wuerfel() - 0.5) * Math.PI;
    }

    this.kugelMaterial = new THREE.PointsMaterial({
      size: 0.052,
      vertexColors: true,
      transparent: true,
      opacity: 0.95,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
      sizeAttenuation: true,
    });
    this.kugelA = this.punkte(this.aOrte, this.aFarben, this.kugelMaterial);
    this.kugelB = this.punkte(this.bOrte, this.bFarben, this.kugelMaterial);

    // --- Die Schweife ------------------------------------------------------
    this.saOrte = new Float32Array(SCHWEIF * 2 * 3);
    this.saFarben = new Float32Array(SCHWEIF * 2 * 3);
    this.sbOrte = new Float32Array(SCHWEIF * 2 * 3);
    this.sbFarben = new Float32Array(SCHWEIF * 2 * 3);

    this.schweifMaterial = new THREE.LineBasicMaterial({
      vertexColors: true,
      transparent: true,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    this.schweifA = this.linien(this.saOrte, this.saFarben, this.schweifMaterial);
    this.schweifB = this.linien(this.sbOrte, this.sbFarben, this.schweifMaterial);

    // --- Der Nebel ---------------------------------------------------------
    this.nOrte = new Float32Array(NEBEL * 3);
    this.nFarben = new Float32Array(NEBEL * 3);
    this.nBahn = new Float32Array(NEBEL);
    this.nWinkel = new Float32Array(NEBEL);
    this.nHoehe = new Float32Array(NEBEL);
    this.nTempo = new Float32Array(NEBEL);
    this.nPhase = new Float32Array(NEBEL);

    for (let i = 0; i < NEBEL; i++) {
      // Über den ganzen Raum verteilt, auch durch die Mitte.
      //
      // Zuerst lag der Nebel als Ring um die Bahn herum. Das sah aus, als
      // stünden die Kugeln VOR einer Wolke. Damit sie DARIN schimmern,
      // muss auch dort Nebel sein, wo sie sich bewegen - dann liegen mal
      // Schwaden vor einer Kugel und mal dahinter, und genau daraus
      // entsteht das Schimmern.
      //
      // Die Wurzel verteilt gleichmässig über das Volumen: Ohne sie
      // klumpte alles in der Mitte, weil eine Kugelschale nach aussen hin
      // mehr Platz hat als innen.
      this.nBahn[i] = Math.sqrt(wuerfel()) * 1.05;
      this.nWinkel[i] = wuerfel() * Math.PI * 2.0;
      this.nHoehe[i] = (wuerfel() - 0.5) * 0.95;
      this.nTempo[i] = 0.06 + wuerfel() * 0.20;
      this.nPhase[i] = wuerfel() * Math.PI * 2.0;
    }

    this.nebelMaterial = new THREE.PointsMaterial({
      // Gross und blass: Was Nebel ausmacht, sind weite, schwache Flecken,
      // die sich überlagern. Kleine helle Punkte wären Sterne.
      size: 0.150,
      vertexColors: true,
      transparent: true,
      opacity: 0.28,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
      sizeAttenuation: true,
    });
    this.nebel = this.punkte(this.nOrte, this.nFarben, this.nebelMaterial);
  }

  private punkte(
    orte: Float32Array,
    farben: Float32Array,
    material: THREE.PointsMaterial
  ): THREE.Points {
    const geometrie = new THREE.BufferGeometry();
    geometrie.setAttribute("position", new THREE.BufferAttribute(orte, 3));
    geometrie.setAttribute("color", new THREE.BufferAttribute(farben, 3));
    const punkte = new THREE.Points(geometrie, material);
    punkte.frustumCulled = false;
    this.group.add(punkte);
    return punkte;
  }

  private linien(
    orte: Float32Array,
    farben: Float32Array,
    material: THREE.LineBasicMaterial
  ): THREE.LineSegments {
    const geometrie = new THREE.BufferGeometry();
    geometrie.setAttribute("position", new THREE.BufferAttribute(orte, 3));
    geometrie.setAttribute("color", new THREE.BufferAttribute(farben, 3));
    const linien = new THREE.LineSegments(geometrie, material);
    linien.frustumCulled = false;
    this.group.add(linien);
    return linien;
  }

  /**
   * Übernimmt die Farben des Zustands.
   *
   * Genommen wird nur der FARBTON, nicht Sättigung und Helligkeit. Sonst
   * ergäbe ein blasses Theme zwei blasse Kugeln. Was bleibt, ist die
   * Auskunft: Im Ruhezustand blaugrün, beim Arbeiten rot.
   */
  public setColors(kern: THREE.Color, schein: THREE.Color, staerke: number): void {
    kern.getHSL(this.hsl);
    if (this.hsl.s >= 0.08) {
      this.neonTon = this.hsl.h;
    } else {
      schein.getHSL(this.hsl);
      if (this.hsl.s >= 0.08) {
        this.neonTon = this.hsl.h;
      }
    }
    this.staerke = staerke;
  }

  /** Meldet, wie laut gerade gesprochen wird (0 bis 1, bereits geglättet). */
  public setVoiceLevel(pegel: number): void {
    this.stimme = Math.max(0, Math.min(1, pegel));
  }

  /** Lässt alles von vorn anlaufen. */
  public restartIntro(): void {
    this.aufbau = 0.0;
  }

  /**
   * Führt die Bahn weiter.
   *
   * @param elapsed Laufzeit in Sekunden.
   * @param delta Zeit seit dem letzten Bild.
   * @param tempo Geschwindigkeit des Zustands.
   */
  public update(elapsed: number, delta: number, tempo: number): void {
    this.aufbau = Math.min(2.0, this.aufbau + delta);
    const anlauf = Math.min(1.0, this.aufbau / 1.6);

    this.lorenz(delta * tempo);

    // Die Achse, um die sich die beiden drehen, kommt aus der Lorenz-Bahn –
    // aber sie folgt ihr TRÄGE, statt sie zu übernehmen.
    //
    // Das ist der Unterschied zwischen ruckartig und fliessend. Der
    // Lorenz-Zustand ändert sich schnell, und beim Sprung auf den anderen
    // Flügel springt er sehr schnell. Nimmt man ihn unmittelbar als Achse,
    // klappt die Bahnebene in wenigen Bildern um – das sieht aus wie ein
    // Schnitt, nicht wie eine Bewegung.
    //
    // Mit Trägheit dazwischen bleibt die Unvorhersehbarkeit erhalten, aber
    // sie erreicht das Bild als Schwung: Die Ebene legt sich in die neue
    // Lage, statt hineinzuspringen. Physikalisch gesprochen bekommt das
    // Gebilde eine Masse, und Masse ist es, was Bewegung organisch macht.
    //
    // Die Annäherung hängt an `delta` und nicht an der Bildzahl – sonst
    // bewegte sich alles auf einem schnellen Rechner anders als auf einem
    // langsamen.
    this.zielAchse.set(this.lx * 0.05, this.ly * 0.05, (this.lz - 25.0) * 0.08);
    if (this.zielAchse.lengthSq() <= 1e-6) {
      this.zielAchse.set(0, 1, 0);
    }
    this.zielAchse.normalize();

    const traegheit = 1.0 - Math.exp(-delta * 1.35);
    this.achse.lerp(this.zielAchse, traegheit);
    if (this.achse.lengthSq() <= 1e-6) {
      this.achse.copy(this.zielAchse);
    }
    this.achse.normalize();

    // Zwei Richtungen quer dazu. Der Hilfsvektor wird gewechselt, wenn er
    // fast parallel läge – sonst entartet das Kreuzprodukt zu null und die
    // Bahn klappt zu einer Linie zusammen.
    if (Math.abs(this.achse.y) < 0.9) {
      this.hilf.set(0, 1, 0);
    } else {
      this.hilf.set(1, 0, 0);
    }
    this.quer1.crossVectors(this.achse, this.hilf).normalize();
    this.quer2.crossVectors(this.achse, this.quer1).normalize();

    // Der Abstand atmet mit derselben Bahn – ebenfalls träge. Ein Abstand,
    // der dem Lorenz-Wert unmittelbar folgt, zuckt; einer mit Trägheit
    // dehnt sich und zieht sich zusammen.
    const zielAbstand =
      ABSTAND + (this.lz - 25.0) * 0.010 + Math.sin(elapsed * 0.4) * 0.05 +
      this.stimme * 0.14;
    this.abstand += (zielAbstand - this.abstand) * (1.0 - Math.exp(-delta * 2.2));
    const abstand = this.abstand;

    // Beim Sprechen kreisen sie schneller. Auch das Tempo wird geglättet:
    // |x| des Lorenz-Systems schwankt heftig, und ein Kreisen, das im
    // Takt dieser Schwankung schneller und langsamer wird, wirkt hakelig.
    const zielTempo =
      (0.75 + Math.abs(this.lx) * 0.045) * (1.0 + this.stimme * 1.1);
    this.drehTempo += (zielTempo - this.drehTempo) * (1.0 - Math.exp(-delta * 1.8));
    this.winkel += delta * tempo * this.drehTempo;

    const cw = Math.cos(this.winkel);
    const sw = Math.sin(this.winkel);

    this.mitteA
      .copy(this.quer1)
      .multiplyScalar(cw * abstand)
      .addScaledVector(this.quer2, sw * abstand);
    this.mitteB.copy(this.mitteA).multiplyScalar(-1);

    // Leicht ungleich versetzt. Zwei genau gegenüberliegende Punkte wirken
    // wie die Enden einer Hantel; ein kleiner Versatz macht daraus zwei
    // Körper, die einander umkreisen.
    this.mitteA.addScaledVector(this.achse, Math.sin(elapsed * 0.7 + 2.1) * 0.10);
    this.mitteB.addScaledVector(this.achse, Math.sin(elapsed * 0.7) * 0.10);

    // Die Farben wandern mit der Bahn – und gehen ineinander über, wenn
    // sich die Kugeln nähern. Das ist der Moment, auf den man wartet.
    const naehe = Math.exp(
      -Math.pow(this.mitteA.distanceTo(this.mitteB) / 0.55, 2)
    );
    const tonA = this.neonTon + this.lx * 0.012 + Math.sin(elapsed * 0.09) * 0.06;
    const tonB = tonA + 0.34 - naehe * 0.28 + this.ly * 0.006;

    this.kugelSetzen(this.aOrte, this.aFarben, this.kugelA, this.mitteA, tonA, elapsed, anlauf);
    this.kugelSetzen(this.bOrte, this.bFarben, this.kugelB, this.mitteB, tonB, elapsed, anlauf);

    this.schweifSetzen(this.spurA, this.saOrte, this.saFarben, this.schweifA, this.mitteA, tonA, anlauf);
    this.schweifSetzen(this.spurB, this.sbOrte, this.sbFarben, this.schweifB, this.mitteB, tonB, anlauf);

    this.nebelSetzen(elapsed, tonA, tonB, anlauf);

    this.group.rotation.y = elapsed * 0.06;
    this.group.rotation.x = Math.sin(elapsed * 0.11) * 0.18;
  }

  // --- Innenleben --------------------------------------------------------------

  /**
   * Ein Schritt des Lorenz-Systems.
   *
   * In kleinen Teilschritten gerechnet. Bei einem chaotischen System heisst
   * ein zu grober Schritt nicht „etwas ungenau", sondern „etwas völlig
   * anderes" – und bei einem sehr grossen läuft die Bahn davon, statt auf
   * dem Attraktor zu bleiben. Deshalb ist der Zeitschritt zusätzlich nach
   * oben begrenzt: Nach einem Ruckler darf nicht die ganze Bahn kippen.
   */
  private lorenz(dt: number): void {
    const schritte = 8;
    const h = (Math.min(Math.abs(dt), 0.05) / schritte) * 0.55;
    for (let i = 0; i < schritte; i++) {
      const dx = SIGMA * (this.ly - this.lx);
      const dy = this.lx * (RHO - this.lz) - this.ly;
      const dz = this.lx * this.ly - BETA * this.lz;
      this.lx += dx * h;
      this.ly += dy * h;
      this.lz += dz * h;
    }
  }

  /** Legt die Punkte einer Kugel um ihre Mitte. */
  private kugelSetzen(
    orte: Float32Array,
    farben: Float32Array,
    punkte: THREE.Points,
    mitte: THREE.Vector3,
    ton: number,
    elapsed: number,
    anlauf: number
  ): void {
    for (let i = 0; i < JE_KUGEL; i++) {
      const w = this.kPhase[i] + elapsed * this.kTempo[i];
      const r = this.kBahn[i] * (1.0 + Math.sin(elapsed * 1.3 + this.kPhase[i]) * 0.22);
      const cn = Math.cos(this.kNeigung[i]);
      const sn = Math.sin(this.kNeigung[i]);

      const x = mitte.x + Math.cos(w) * r;
      const y = mitte.y + Math.sin(w) * r * cn;
      const z = mitte.z + Math.sin(w) * r * sn;

      const weit = Math.sqrt(x * x + y * y + z * z);
      const enge = weit > HARTE_DECKE ? HARTE_DECKE / weit : 1.0;

      orte[i * 3 + 0] = x * enge;
      orte[i * 3 + 1] = y * enge;
      orte[i * 3 + 2] = z * enge;

      // Innen hell, aussen blass: So bekommt die Wolke einen Kern und
      // sieht nicht aus wie eine Schale.
      const kern = 1.0 - this.kBahn[i] / KUGEL_RADIUS;

      // Das Schimmern.
      //
      // Jeder Punkt schwankt in eigenem Takt in der Helligkeit, und die
      // Takte sind ungleich. Eine Kugel, deren Punkte alle gleich hell
      // sind, ist eine Fläche; erst wenn einzelne aufblitzen und andere
      // verlöschen, sieht es aus, als läge etwas Bewegtes davor. Zusammen
      // mit dem Nebel, der jetzt auch VOR den Kugeln liegt, ergibt das
      // den Eindruck, dass sie darin schweben.
      const flimmern =
        0.72 +
        0.28 * Math.sin(elapsed * (2.1 + this.kTempo[i] * 1.4) + this.kPhase[i] * 3.1);

      const hell =
        (0.25 + kern * 0.95) * flimmern * anlauf * (0.6 + this.staerke * 0.4);

      this.streich.setHSL(
        (((ton + kern * 0.06) % 1.0) + 1.0) % 1.0,
        0.95,
        Math.min(0.92, 0.48 + kern * 0.28 + this.stimme * 0.10)
      );
      farben[i * 3 + 0] = this.streich.r * hell;
      farben[i * 3 + 1] = this.streich.g * hell;
      farben[i * 3 + 2] = this.streich.b * hell;
    }

    (punkte.geometry.getAttribute("position") as THREE.BufferAttribute).needsUpdate = true;
    (punkte.geometry.getAttribute("color") as THREE.BufferAttribute).needsUpdate = true;
  }

  /** Zieht den Schweif hinter einer Kugel her. */
  private schweifSetzen(
    spur: THREE.Vector3[],
    orte: Float32Array,
    farben: Float32Array,
    linien: THREE.LineSegments,
    mitte: THREE.Vector3,
    ton: number,
    anlauf: number
  ): void {
    spur.unshift(mitte.clone());
    if (spur.length > SCHWEIF + 1) {
      spur.pop();
    }

    this.streich.setHSL(((ton % 1.0) + 1.0) % 1.0, 0.95, 0.55);

    for (let i = 0; i < SCHWEIF; i++) {
      const a = spur[Math.min(i, spur.length - 1)];
      const b = spur[Math.min(i + 1, spur.length - 1)];

      // Nach hinten verglühen, und zwar nicht geradlinig.
      //
      // Bei einem langen Schweif ist das entscheidend: Linear verteilt
      // liegt in der Mitte noch die halbe Helligkeit, und das Ganze wird
      // zu einem gleichmässig hellen Band, das die Kugel verdeckt. Das
      // Quadrat lässt den Anfang hell und den Rest weit auslaufen - man
      // sieht die ganze Schleife, ohne dass sie sich in den Vordergrund
      // draengt.
      const u0 = 1.0 - i / SCHWEIF;
      const u1 = 1.0 - (i + 1) / SCHWEIF;
      const f0 = u0 * u0 * 0.95 * anlauf;
      const f1 = u1 * u1 * 0.95 * anlauf;

      orte[i * 6 + 0] = a.x;
      orte[i * 6 + 1] = a.y;
      orte[i * 6 + 2] = a.z;
      orte[i * 6 + 3] = b.x;
      orte[i * 6 + 4] = b.y;
      orte[i * 6 + 5] = b.z;

      farben[i * 6 + 0] = this.streich.r * f0;
      farben[i * 6 + 1] = this.streich.g * f0;
      farben[i * 6 + 2] = this.streich.b * f0;
      farben[i * 6 + 3] = this.streich.r * f1;
      farben[i * 6 + 4] = this.streich.g * f1;
      farben[i * 6 + 5] = this.streich.b * f1;
    }

    (linien.geometry.getAttribute("position") as THREE.BufferAttribute).needsUpdate = true;
    (linien.geometry.getAttribute("color") as THREE.BufferAttribute).needsUpdate = true;
  }

  /** Legt den Nebel um die beiden Kugeln. */
  private nebelSetzen(
    elapsed: number,
    tonA: number,
    tonB: number,
    anlauf: number
  ): void {
    const anzahl = this.sichtbarerNebel;

    // Ein Ton für den ganzen Nebel, einmal je Bild gesetzt statt je Fleck.
    // Er liegt gegenüber den Kugeln auf dem Farbkreis, damit sie sich
    // davon abheben, und wandert nur ganz langsam.
    this.streich.setHSL(
      ((((tonA + tonB) * 0.5 + 0.5 + Math.sin(elapsed * 0.05) * 0.04) % 1.0) + 1.0) % 1.0,
      0.85,
      0.34 + this.stimme * 0.10
    );
    const nr = this.streich.r;
    const ng = this.streich.g;
    const nb = this.streich.b;

    for (let i = 0; i < anzahl; i++) {
      const w = this.nWinkel[i] + elapsed * this.nTempo[i];
      const wallen = 1.0 + Math.sin(elapsed * 0.33 + this.nPhase[i]) * 0.14;

      // Der Nebel wird von der Lorenz-Bahn mitgezogen, aber schwächer als
      // die Kugeln. Ein Nebel, der genau mitmacht, wirkt wie ein Anhängsel;
      // einer, der nachhinkt, wirkt wie etwas, worin sich die beiden
      // bewegen.
      const zug = 0.10;
      let x = Math.cos(w) * this.nBahn[i] * wallen + this.lx * zug * 0.05;
      let y = Math.sin(w) * this.nBahn[i] * wallen + this.ly * zug * 0.05;
      let z =
        this.nHoehe[i] * wallen +
        Math.sin(elapsed * 0.5 + this.nPhase[i]) * 0.05 +
        (this.lz - 25.0) * zug * 0.02;

      const weit = Math.sqrt(x * x + y * y + z * z);
      if (weit > HARTE_DECKE) {
        const enge = HARTE_DECKE / weit;
        x *= enge;
        y *= enge;
        z *= enge;
      }

      this.nOrte[i * 3 + 0] = x;
      this.nOrte[i * 3 + 1] = y;
      this.nOrte[i * 3 + 2] = z;

      // Nach aussen weich verblassen, damit er nirgends eine Kante hat -
      // aber ohne Loch in der Mitte: Dort bewegen sich die Kugeln, und
      // dort soll Nebel sein, damit sie darin liegen und nicht davor.
      const weg = Math.sqrt(x * x + y * y + z * z);
      const dichte = Math.exp(-Math.pow(weg / 0.82, 2)) * 0.9 + 0.10;

      // Einfarbig – und das ist eine Entscheidung, keine Vereinfachung.
      //
      // Vorher mischte jeder Fleck zwischen den Farben der beiden Kugeln.
      // Das ergab einen bunten Schleier, in dem die Kugeln untergingen:
      // Wenn die Umgebung dieselben Farben trägt wie das, was darin
      // leuchten soll, hebt sich nichts mehr ab. Ein einziger, ruhiger Ton
      // ist der Hintergrund, vor dem die beiden überhaupt erst schimmern
      // können.
      //
      // Die Helligkeit schwankt weiterhin von Fleck zu Fleck – sonst wäre
      // es eine Fläche und keine Wolke.
      const schwaden = 0.75 + Math.sin(elapsed * 0.31 + this.nPhase[i] * 1.9) * 0.25;
      const d = dichte * schwaden * 0.95 * anlauf * (0.55 + this.staerke * 0.45);
      this.nFarben[i * 3 + 0] = nr * d;
      this.nFarben[i * 3 + 1] = ng * d;
      this.nFarben[i * 3 + 2] = nb * d;
    }

    for (let i = anzahl; i < NEBEL; i++) {
      this.nFarben[i * 3 + 0] = 0;
      this.nFarben[i * 3 + 1] = 0;
      this.nFarben[i * 3 + 2] = 0;
    }

    (this.nebel.geometry.getAttribute("position") as THREE.BufferAttribute).needsUpdate = true;
    (this.nebel.geometry.getAttribute("color") as THREE.BufferAttribute).needsUpdate = true;
  }

  /** Passt den Aufwand an die Leistungsstufe an. */
  public setQuality(level: number): void {
    // Der Nebel kostet am meisten Füllrate, weil seine Flecken gross sind
    // und sich überlagern – er wird zuerst gekürzt. Die Kugeln bleiben:
    // ohne sie gäbe es nichts mehr zu sehen.
    this.sichtbarerNebel =
      level >= 2 ? NEBEL : level >= 1 ? Math.floor(NEBEL * 0.45) : 0;
    this.schweifA.visible = level >= 1;
    this.schweifB.visible = level >= 1;
  }

  /** Gibt alle GPU-Ressourcen frei. */
  public dispose(): void {
    this.kugelA.geometry.dispose();
    this.kugelB.geometry.dispose();
    this.schweifA.geometry.dispose();
    this.schweifB.geometry.dispose();
    this.nebel.geometry.dispose();
    this.kugelMaterial.dispose();
    this.schweifMaterial.dispose();
    this.nebelMaterial.dispose();
  }
}
