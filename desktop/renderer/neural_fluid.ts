/**
 * neural_fluid.ts – der Orb als lebendiges Nervengeflecht.
 *
 * Das ist die Fassung, die in der Vorschau entstanden ist und die der
 * Benutzer freigegeben hat. Sie besteht aus drei Dingen und ganz bewusst
 * aus keinem vierten:
 *
 *   1. **Das Synapsennetz im Inneren** – Knoten, jeder mit seinen nächsten
 *      Nachbarn verbunden, und über jede Verbindung LÄUFT ein Lichtpunkt.
 *      Kommt er an einem Knoten an, leuchtet der auf, und weil dort mehrere
 *      Verbindungen hängen, läuft das Licht von da weiter.
 *   2. **Das Leuchten in der Mitte** – kein Körper, sondern viele kleine
 *      weiche Flecken, die driften.
 *   3. **Der Nebel ringsum** – dieselben Flecken, nur grösser, blasser und
 *      weiter gestreut, nach aussen ohne Grenze verblassend.
 *
 * ## Warum keine Hülle mehr
 *
 * Der Benutzer hat dreimal denselben Einwand erhoben: der Kreis um die
 * Kugel sei nicht schön, nicht organisch. Ich habe zweimal an
 * Einstellungen gedreht, wo die Bauart falsch war.
 *
 * Ein Netz auf einer Kugel hat einen kreisrunden Umriss, und **das lässt
 * sich nicht wegstimmen**. Man kann es dünner machen, durchsichtiger, mit
 * Beulen versehen – der Umriss bleibt ein Kreis, weil eine Kugel von jeder
 * Seite als Kreis erscheint. Dasselbe gilt für jedes einzelne Ding, dessen
 * Form aus einer Formel kommt: Eine Formel erzeugt einen regelmässigen
 * Rand.
 *
 * Nebel kann, was eine Hülle nicht kann: **aufhören, ohne aufzuhören**.
 * Ein Netz endet dort, wo seine letzte Linie endet, und diese Stelle sieht
 * man. Nebel wird nach aussen einfach dünner, bis nichts mehr da ist; eine
 * Grenze gibt es nirgends. Deshalb steht hier Nebel und keine Hülle.
 *
 * ## Warum das ohne eigenen Shader auskommt
 *
 * Aus demselben Grund wie bei den Kugeln zuvor: three.js übersetzt eigene
 * Shader als GLSL ES 1.00, und was dort nicht erlaubt ist, scheitert
 * lautlos – es wird nichts gezeichnet, ohne Fehlermeldung. Benutzt wird
 * hier nur, was in dieser Anwendung nachweislich ankommt:
 * `LineBasicMaterial`, `PointsMaterial`, Vertexfarben, additives Zeichnen
 * und der bestehende Bloom-Durchgang.
 *
 * ## Warum alles an einer Grundperiode hängt
 *
 * Jede feldgetriebene Frequenz ist ein ganzzahliges Vielfaches von
 * `OM = 2π/T`. Nur dadurch kehrt die Verformung nach `T` Sekunden EXAKT in
 * ihren Anfangszustand zurück – nicht ungefähr. Eine Schleife, die
 * „ungefähr" schliesst, hat einen sichtbaren Sprung, und den sieht man
 * jedes Mal.
 */

import * as THREE from "three";

/**
 * Die Grundgrösse, an der alles andere hängt.
 *
 * In der Vorschau stand hier 0.62, bei einer Kamera, die 1.66 Einheiten
 * Bildhöhe zeigt. Das Orb-Fenster schneidet dagegen bei etwa 1.34 ab –
 * darüber hinaus zeichnet niemand mehr.
 *
 * Der Nebel reicht bis `KERN_R * 2.9`, und er darf am Fensterrand nicht
 * mehr zu sehen sein: Ein Nebel, der abgeschnitten wird, hat genau die
 * Kante, wegen der die Hülle weichen musste. Bei 0.44 ist seine Dichte
 * dort auf sechs Prozent gefallen und der äusserste Fleck sitzt bei 1.28.
 */
const KERN_R = 0.44;

/** Die Grundperiode in Sekunden – nach ihr kehrt alles exakt zurück. */
const T = 9.0;
const OM = (Math.PI * 2.0) / T;

/** Die Obergrenze für alles, was gezeichnet wird (siehe KERN_R). */
const HARTE_DECKE = 1.34;

/**
 * Knoten des inneren Netzes, Nachbarn je Knoten, Glieder je Verbindung.
 *
 * Deutlich weniger als in der Vorschau (dort 92 Knoten mit je drei
 * Nachbarn), und der Grund ist keine Geschmacksfrage, sondern Arithmetik.
 *
 * Die Vorschau lief auf 600 Bildpunkten. Der Orb ist bei `orb.scale: 0.20`
 * etwa 63 Bildpunkte gross, das Netz darin rund 27. Zweiundneunzig Knoten
 * haetten dort keine drei Bildpunkte Abstand voneinander - man saehe kein
 * Netz, sondern einen Fleck. Was auf 600 Punkten filigran wirkt, ist auf
 * 27 Punkten Matsch.
 *
 * Mit 34 Knoten und je zwei Nachbarn bleibt etwa ein Bildpunkt Abstand je
 * Kante mehr als das Doppelte - genug, dass man die Leitungen einzeln
 * sieht und der Lichtpunkt darauf ablesbar wandert.
 */
const INNEN_N = 22;
const INNEN_K = 2;
const FASER_G = 7;

/**
 * Wie weit das Netz nach aussen reicht, in Vielfachen von `KERN_R`.
 *
 * Weiter als zuvor (1.15), und der Grund ist nicht Grösse, sondern
 * TRENNUNG: Das Leuchten in der Mitte ist ein additiver Schein, und ein
 * heller Schein an derselben Stelle wie eine dünne Linie frisst die Linie
 * auf. Nicht weil die Linie zu dunkel wäre - sondern weil an dieser Stelle
 * ohnehin schon alles hell ist.
 *
 * Deshalb rückt das Netz nach aussen und der Schein nach innen. Erst
 * dadurch liegen die Leitungen dort, wo der Hintergrund dunkel ist, und
 * erst dort kann man sie sehen.
 */
const INNEN_R = 1.35;

/**
 * Die drei Nebellagen.
 *
 * Drei und nicht eine, weil sich die Grösse eines Punktes ohne eigenen
 * Shader nur für alle zugleich einstellen lässt – und weil echter Nebel
 * nicht aus gleich grossen Teilen besteht.
 *
 * Zahl und Deckung steigen miteinander: Eine Lage, die man stärker deckt,
 * ohne mehr Flecken hineinzugeben, wird fleckig statt dicht.
 */
const NEBEL_LAGEN = [
  { zahl: 90, groesse: KERN_R * 1.9, weite: 2.9, deckung: 0.13 },
  { zahl: 110, groesse: KERN_R * 1.05, weite: 2.3, deckung: 0.155 },
  { zahl: 140, groesse: KERN_R * 0.55, weite: 1.8, deckung: 0.175 },
];

/**
 * Die drei Lagen des Leuchtens in der Mitte.
 *
 * Die grossen tragen den Hof, die kleinen die Dichte in der Mitte.
 */
const GLUT_LAGEN = [
  { zahl: 22, groesse: KERN_R * 0.80, weite: 0.58, deckung: 0.20 },
  { zahl: 34, groesse: KERN_R * 0.42, weite: 0.38, deckung: 0.27 },
  { zahl: 44, groesse: KERN_R * 0.20, weite: 0.22, deckung: 0.40 },
];

/** Ein einfacher, wiederholbarer Zufall – nur für den Aufbau, nie im Lauf. */
function zufall(saat: number): () => number {
  let s = saat >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 4294967296;
  };
}

/** Eine Verbindung zwischen zwei Knoten des inneren Netzes. */
interface Faser {
  a: number;
  b: number;
  /** Wo der Lichtpunkt gerade steht (0 bis 1). */
  stand: number;
  tempo: number;
  richtung: number;
  /** Der Stützpunkt der Krümmung. */
  bogen: THREE.Vector3;
}

/** Eine Lage weicher Flecken – Nebel oder Leuchten. */
interface Lage {
  geometrie: THREE.BufferGeometry;
  material: THREE.PointsMaterial;
  punkte: THREE.Points;
  pos: Float32Array;
  col: Float32Array;
  ruhe: Float32Array;
  phase: Float32Array;
  zahl: number;
  grund: number;
  groesse: number;
  weite: number;
}

/**
 * Das Nervengeflecht.
 *
 * Die Schnittstelle ist genau dieselbe wie beim Vorgänger `DualOrbit` –
 * `orb.ts` muss deshalb nur den Namen austauschen.
 */
export class NeuralFluid {
  /** Die Gruppe, die alles enthält. */
  public readonly group: THREE.Group;

  // --- Das Netz im Inneren -------------------------------------------------
  private readonly innenOrt: THREE.Vector3[] = [];
  private readonly innenFasern: Faser[] = [];
  private readonly innenRuhe: Float32Array;
  private readonly innenPos: Float32Array;
  private readonly innenFarbe: Float32Array;
  private readonly innenG: THREE.BufferGeometry;
  private readonly innenMaterial: THREE.LineBasicMaterial;
  private readonly innenLinien: THREE.LineSegments;

  private readonly innenKnPos: Float32Array;
  private readonly innenKnFarbe: Float32Array;
  private readonly innenKnG: THREE.BufferGeometry;
  private readonly innenKnMaterial: THREE.PointsMaterial;
  private readonly innenKnoten: THREE.Points;
  /** Wie hell ein Knoten gerade nachglüht (klingt ab). */
  private readonly innenGlut: Float32Array;

  // --- Nebel und Leuchten --------------------------------------------------
  private readonly nebelLagen: Lage[] = [];
  private readonly glutLagen: Lage[] = [];
  private readonly scheinTex: THREE.Texture;

  // --- Zustand -------------------------------------------------------------
  /** Der Farbton des Zustands – von `setColors` gesetzt. */
  private zustandTon = 0.86;
  private stimme = 0.0;
  private staerke = 1.0;
  /** Die geglättete Ansage „es wird gerade gesprochen". */
  private sprechen = 0.0;
  /** Die geglättete Ansage „es wird gerade nachgedacht". */
  private denken = 0.0;
  /** Der Anlauf nach dem Start. */
  private aufbau = 0.0;
  /** Die eigene Uhr – sie läuft in `T` um, damit die Schleife schliesst. */
  private t = 0.0;

  // Wiederverwendet – kein neues Objekt je Bild.
  private readonly farbe = new THREE.Color();
  private readonly hsl = { h: 0, s: 0, l: 0 };
  private readonly feld = { x: 0, y: 0, z: 0 };
  private readonly kernFeld = { x: 0, y: 0, z: 0 };
  /** Die Weltskalierung der Gruppe – siehe `massstab()`. */
  private readonly weltMassstab = new THREE.Vector3(1, 1, 1);
  /** Die Grundgrösse jeder Punktlage, bevor der Massstab darauf liegt. */
  private readonly innenKnGrundgroesse = KERN_R * 0.085;

  constructor() {
    this.group = new THREE.Group();
    const w = zufall(20260815);

    // ---------------------------------------------------------------------
    //  Das Netz im Inneren
    // ---------------------------------------------------------------------
    // Vorher waren das Speichen: gerade Linien vom Zentrum nach aussen.
    // Sie sahen aus wie ein Stern, und ein Stern transportiert nichts – er
    // strahlt. Ein Netz dagegen leitet.
    for (let i = 0; i < INNEN_N; i++) {
      // Die dritte Wurzel verteilt gleichmässig über das Volumen; ohne sie
      // sässen fast alle Knoten aussen und das Netz wäre eine Schale.
      const r = Math.cbrt(w()) * KERN_R * INNEN_R;
      const z = w() * 2 - 1;
      const phi = w() * Math.PI * 2;
      const sq = Math.sqrt(Math.max(0, 1 - z * z));
      this.innenOrt.push(
        new THREE.Vector3(Math.cos(phi) * sq * r, Math.sin(phi) * sq * r, z * r)
      );
    }

    for (let i = 0; i < INNEN_N; i++) {
      const nah: Array<[number, number]> = [];
      for (let j = 0; j < INNEN_N; j++) {
        if (j !== i) nah.push([this.innenOrt[i].distanceTo(this.innenOrt[j]), j]);
      }
      nah.sort((a, b) => a[0] - b[0]);
      for (let n = 0; n < INNEN_K; n++) {
        const j = nah[n][1];
        const schon = this.innenFasern.some(
          (f) => (f.a === i && f.b === j) || (f.a === j && f.b === i)
        );
        if (schon) continue;
        // Gebogen, nicht gerade: Ein Netz aus Geraden sieht aus wie ein
        // Drahtmodell; erst die Krümmung macht daraus etwas Gewachsenes.
        const mitte = this.innenOrt[i]
          .clone()
          .add(this.innenOrt[j])
          .multiplyScalar(0.5);
        const bogen = mitte.add(
          new THREE.Vector3(
            (w() - 0.5) * 0.1,
            (w() - 0.5) * 0.1,
            (w() - 0.5) * 0.1
          ).multiplyScalar(KERN_R)
        );
        this.innenFasern.push({
          a: i,
          b: j,
          stand: w(),
          tempo: 0.35 + w() * 0.9,
          richtung: w() < 0.5 ? 1 : -1,
          bogen,
        });
      }
    }

    const punkte: number[] = [];
    for (const f of this.innenFasern) {
      for (let i = 0; i < FASER_G; i++) {
        for (const u of [i / FASER_G, (i + 1) / FASER_G]) {
          const k = (1 - u) * (1 - u);
          const l = 2 * (1 - u) * u;
          const m = u * u;
          punkte.push(
            this.innenOrt[f.a].x * k + f.bogen.x * l + this.innenOrt[f.b].x * m,
            this.innenOrt[f.a].y * k + f.bogen.y * l + this.innenOrt[f.b].y * m,
            this.innenOrt[f.a].z * k + f.bogen.z * l + this.innenOrt[f.b].z * m
          );
        }
      }
    }
    this.innenRuhe = new Float32Array(punkte);
    this.innenPos = new Float32Array(punkte);
    this.innenFarbe = new Float32Array(punkte.length);
    this.innenG = new THREE.BufferGeometry();
    this.innenG.setAttribute(
      "position",
      new THREE.BufferAttribute(this.innenPos, 3)
    );
    this.innenG.setAttribute(
      "color",
      new THREE.BufferAttribute(this.innenFarbe, 3)
    );
    this.innenMaterial = new THREE.LineBasicMaterial({
      vertexColors: true,
      transparent: true,
      opacity: 1.0,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    this.innenLinien = new THREE.LineSegments(this.innenG, this.innenMaterial);
    this.group.add(this.innenLinien);

    this.innenKnPos = new Float32Array(INNEN_N * 3);
    this.innenKnFarbe = new Float32Array(INNEN_N * 3);
    this.innenGlut = new Float32Array(INNEN_N);
    this.innenKnG = new THREE.BufferGeometry();
    this.innenKnG.setAttribute(
      "position",
      new THREE.BufferAttribute(this.innenKnPos, 3)
    );
    this.innenKnG.setAttribute(
      "color",
      new THREE.BufferAttribute(this.innenKnFarbe, 3)
    );
    this.innenKnMaterial = new THREE.PointsMaterial({
      size: this.innenKnGrundgroesse,
      vertexColors: true,
      transparent: true,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
      sizeAttenuation: true,
    });
    this.innenKnoten = new THREE.Points(this.innenKnG, this.innenKnMaterial);
    this.group.add(this.innenKnoten);

    // ---------------------------------------------------------------------
    //  Die weichen Flecken
    // ---------------------------------------------------------------------
    this.scheinTex = this.scheinBild();
    for (const l of NEBEL_LAGEN) {
      this.nebelLagen.push(this.baueLage(l, 0.6, false, w));
    }
    for (const l of GLUT_LAGEN) {
      // `depthTest: false` für das Leuchten: Es sitzt in der Mitte und soll
      // durch den Nebel hindurch zu sehen sein – sonst verdeckt der vordere
      // Nebel den Kern, und der Kern ist die Auskunft.
      this.glutLagen.push(this.baueLage(l, 0.75, true, w));
    }
  }

  /**
   * Die Textur für einen weichen Fleck.
   *
   * Sehr früh abfallend und lang auslaufend. Ein linearer Verlauf hätte
   * einen erkennbaren Rand, und genau den soll keiner haben.
   */
  private scheinBild(): THREE.Texture {
    const gr = 64;
    const lw = document.createElement("canvas");
    lw.width = gr;
    lw.height = gr;
    const c2 = lw.getContext("2d");
    if (c2 !== null) {
      const v = c2.createRadialGradient(gr / 2, gr / 2, 0, gr / 2, gr / 2, gr / 2);
      v.addColorStop(0.0, "rgba(255,255,255,1)");
      v.addColorStop(0.1, "rgba(255,255,255,0.55)");
      v.addColorStop(0.28, "rgba(255,255,255,0.16)");
      v.addColorStop(0.55, "rgba(255,255,255,0.035)");
      v.addColorStop(1.0, "rgba(255,255,255,0)");
      c2.fillStyle = v;
      c2.fillRect(0, 0, gr, gr);
    }
    const tex = new THREE.CanvasTexture(lw);
    tex.needsUpdate = true;
    return tex;
  }

  /** Baut eine Lage weicher Flecken auf. */
  private baueLage(
    l: { zahl: number; groesse: number; weite: number; deckung: number },
    exponent: number,
    vorn: boolean,
    w: () => number
  ): Lage {
    const pos = new Float32Array(l.zahl * 3);
    const col = new Float32Array(l.zahl * 3);
    const ruhe = new Float32Array(l.zahl * 3);
    const phase = new Float32Array(l.zahl);
    for (let i = 0; i < l.zahl; i++) {
      // Der Exponent bestimmt, wie stark sich die Flecken zur Mitte hin
      // drängen: unter eins bleibt es locker, näher an eins wird der Kern
      // dicht.
      // Der Nebel beginnt erst ausserhalb des Netzes.
      //
      // Vorher wurden die Flecken vom Mittelpunkt an verteilt, also
      // mitten in die Leitungen hinein - und ein weicher heller Fleck vor
      // einer Linie ist das Ende der Linie. Der Nebel gehoert RINGSUM,
      // nicht hindurch. Beim Leuchten in der Mitte bleibt es beim alten:
      // das SOLL dicht sein.
      const anfang = vorn ? 0.0 : 0.5;
      const r =
        (anfang + (1 - anfang) * Math.pow(w(), exponent)) * KERN_R * l.weite;
      const z = w() * 2 - 1;
      const phi = w() * Math.PI * 2;
      const sq = Math.sqrt(Math.max(0, 1 - z * z));
      ruhe[i * 3] = Math.cos(phi) * sq * r;
      ruhe[i * 3 + 1] = Math.sin(phi) * sq * r;
      ruhe[i * 3 + 2] = z * r * (vorn ? 1.0 : 0.8);
      phase[i] = w() * Math.PI * 2;
    }
    const geometrie = new THREE.BufferGeometry();
    geometrie.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    geometrie.setAttribute("color", new THREE.BufferAttribute(col, 3));
    const material = new THREE.PointsMaterial({
      size: l.groesse,
      map: this.scheinTex,
      vertexColors: true,
      transparent: true,
      opacity: l.deckung,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
      depthTest: !vorn,
      sizeAttenuation: true,
    });
    const punkte = new THREE.Points(geometrie, material);
    this.group.add(punkte);
    return {
      geometrie,
      material,
      punkte,
      pos,
      col,
      ruhe,
      phase,
      zahl: l.zahl,
      grund: l.deckung,
      groesse: l.groesse,
      weite: l.weite,
    };
  }

  /**
   * Wie stark die Gruppe von aussen verkleinert wird.
   *
   * Das ist die Stelle, an der die erste Fassung im Orb nicht so aussah
   * wie in der Vorschau - und der Grund ist eine Eigenheit von three.js,
   * die man nicht vermutet:
   *
   *   **`PointsMaterial.size` wird von der Objektskalierung NICHT
   *   erfasst.**
   *
   * Der Vertex-Shader für Punkte setzt `gl_PointSize = size` und teilt
   * danach nur noch durch die Tiefe. Die Modellmatrix - und damit jede
   * Skalierung einer Elterngruppe - wirkt auf die POSITION der Punkte,
   * nicht auf ihre Grösse.
   *
   * Im Orb steht `orb.scale: 0.20`, mal der Zustandsgrösse also etwa
   * 0.18. Die Positionen schrumpften damit auf ein Sechstel, die weichen
   * Flecken behielten ihre volle Grösse - jeder Nebelfleck war so gross
   * wie die ganze Wolke. Was dabei herauskommt, ist kein Nebel um ein
   * Netz, sondern ein Schmier, in dem nichts mehr zu erkennen ist. Genau
   * das war zu sehen.
   *
   * Deshalb wird die Weltskalierung hier je Bild ausgelesen und auf jede
   * Punktgrösse multipliziert. Erst dadurch stimmen die Verhältnisse im
   * Orb mit denen der Vorschau überein - und sie stimmen auch dann noch,
   * wenn der Benutzer `orb.scale` ändert oder ein Zustand den Orb dehnt.
   */
  private massstab(): number {
    // Die Weltmatrix stammt sonst vom Zeichnen des VORIGEN Bildes; beim
    // allerersten wäre sie die Einheitsmatrix, und der erste Sprung fiele
    // auf. Das Nachziehen kostet ein paar Matrixmultiplikationen.
    this.group.updateWorldMatrix(true, false);
    this.group.getWorldScale(this.weltMassstab);
    const s = this.weltMassstab.x;
    return s > 0.0001 ? s : 1.0;
  }

  /**
   * Das grosse Strömungsfeld – für den Nebel.
   *
   * Es wird über die POSITION ausgewertet, nicht je Fleck. Das ist der
   * ganze Grund, warum es organisch wirkt: Benachbarte Flecken erfahren
   * fast dieselbe Verschiebung und wandern deshalb GEMEINSAM, wie Rauch.
   * Ein Versatz je Fleck ergäbe Konfetti.
   */
  private stroemung(x: number, y: number, z: number, tt: number): void {
    this.feld.x =
      Math.sin(y * 2.1 + tt * OM * 2) * 0.055 +
      Math.sin(z * 3.3 - tt * OM * 3) * 0.03;
    this.feld.y =
      Math.sin(z * 2.4 - tt * OM * 2) * 0.055 +
      Math.sin(x * 3.1 + tt * OM * 1) * 0.03;
    this.feld.z =
      Math.sin(x * 1.9 + tt * OM * 3) * 0.04 +
      Math.sin(y * 2.7 - tt * OM * 1) * 0.026;
  }

  /** Das Feld im Kern: feiner und schneller als das grosse draussen. */
  private kernStroemung(x: number, y: number, z: number, tt: number): void {
    const s = 7.5;
    this.kernFeld.x =
      Math.sin(y * s + tt * OM * 5) * 0.03 +
      Math.sin(z * s * 1.7 - tt * OM * 8) * 0.018;
    this.kernFeld.y =
      Math.sin(z * s - tt * OM * 6) * 0.03 +
      Math.sin(x * s * 1.5 + tt * OM * 4) * 0.018;
    this.kernFeld.z =
      Math.sin(x * s + tt * OM * 7) * 0.024 +
      Math.sin(y * s * 1.9 - tt * OM * 5) * 0.015;
  }

  /**
   * Übernimmt die Farben des Zustands.
   *
   * Genommen wird nur der FARBTON, nicht Sättigung und Helligkeit. Sonst
   * ergäbe ein blasses Theme ein blasses Geflecht. Was bleibt, ist die
   * Auskunft: im Ruhezustand die Themenfarbe, beim Arbeiten rot.
   */
  public setColors(kern: THREE.Color, schein: THREE.Color, staerke: number): void {
    kern.getHSL(this.hsl);
    if (this.hsl.s >= 0.08) {
      this.zustandTon = this.hsl.h;
    } else {
      schein.getHSL(this.hsl);
      if (this.hsl.s >= 0.08) {
        this.zustandTon = this.hsl.h;
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
   * Führt das Geflecht weiter.
   *
   * @param elapsed Laufzeit in Sekunden (hier nicht gebraucht – die eigene
   *   Uhr muss in `T` umlaufen, damit die Schleife exakt schliesst).
   * @param delta Zeit seit dem letzten Bild.
   * @param tempo Geschwindigkeit des Zustands (siehe `states.ts`).
   */
  public update(elapsed: number, delta: number, tempo: number): void {
    const dt = Math.min(0.05, Math.max(0, delta));
    this.t = (this.t + dt) % T;
    this.aufbau = Math.min(2.0, this.aufbau + dt);
    const anlauf = Math.min(1.0, this.aufbau / 1.6);
    const t = this.t;

    // --- Was gerade geschieht ------------------------------------------------
    //
    // Der Orb kennt keinen Aufzählungswert „denken/sprechen" an dieser
    // Stelle, sondern nur zwei Zahlen: das Tempo des Zustands und den
    // Stimmpegel. Daraus wird hier zurückgelesen, was los ist – und zwar
    // TRÄGE, weil ein Zustand, der im Bild springt, wie ein Schnitt wirkt
    // und nicht wie eine Regung.
    //
    // Die Annäherung hängt an `dt` und nicht an der Bildzahl: Sonst
    // verhielte sich alles auf einem schnellen Rechner anders als auf
    // einem langsamen.
    const zielSprechen = Math.min(1, this.stimme * 2.2);
    const zielDenken = Math.max(
      0,
      Math.min(1, (tempo - 1.15) / 0.45) * (1 - zielSprechen)
    );
    const traegheit = 1.0 - Math.exp(-dt * 3.2);
    this.sprechen += (zielSprechen - this.sprechen) * traegheit;
    this.denken += (zielDenken - this.denken) * traegheit;
    const ruhe = Math.max(0, 1 - this.sprechen - this.denken);

    // Der Massstab, mit dem jede Punktgrösse zu multiplizieren ist.
    const mass = this.massstab();
    this.innenKnMaterial.size = this.innenKnGrundgroesse * mass;

    const atem = 0.5 - 0.5 * Math.cos(t * OM);
    // Wie angestrengt es zugeht. Es multipliziert Helligkeit UND Tempo –
    // beides zusammen liest man als Anspannung, die Helligkeit allein
    // nur als „heller".
    const eifer = (1.0 + this.denken * 1.4 + this.sprechen * 0.7) * anlauf;
    const kw = KERN_R * (0.9 + atem * 0.16) * (1.0 + this.denken * 0.06);

    // --- Das Netz im Inneren -------------------------------------------------
    for (let k = 0; k < INNEN_N; k++) {
      this.innenGlut[k] = Math.max(0, this.innenGlut[k] - dt * 1.5);
    }

    const iw = kw / KERN_R;
    let ip = 0;
    for (const f of this.innenFasern) {
      let stand = f.stand + dt * f.tempo * f.richtung * eifer * 0.5;
      // Kommt der Lichtpunkt am Ende an, leuchtet der Knoten dort auf –
      // und weil an ihm mehrere Fasern hängen, läuft das Licht von da
      // weiter. Das ist der Unterschied zwischen einem beleuchteten
      // Geflecht und einem, durch das etwas hindurchgeht.
      if (stand >= 1) {
        stand -= 1;
        this.innenGlut[f.b] = 1.0;
      }
      if (stand < 0) {
        stand += 1;
        this.innenGlut[f.a] = 1.0;
      }
      f.stand = stand;

      const anregung = Math.max(this.innenGlut[f.a], this.innenGlut[f.b]);
      for (let i = 0; i < FASER_G; i++) {
        for (let ende = 0; ende < 2; ende++) {
          const u = (i + ende) / FASER_G;
          const q = ip * 3;
          let x = this.innenRuhe[q] * iw;
          let y = this.innenRuhe[q + 1] * iw;
          let z = this.innenRuhe[q + 2] * iw;
          this.kernStroemung(x, y, z, t);
          x += this.kernFeld.x * 0.5;
          y += this.kernFeld.y * 0.5;
          z += this.kernFeld.z * 0.5;
          this.innenPos[q] = x;
          this.innenPos[q + 1] = y;
          this.innenPos[q + 2] = z;

          // Die Spur des laufenden Lichtpunkts.
          let ab = Math.abs(u - stand);
          if (ab > 0.5) ab = 1 - ab;
          const naehe = Math.exp(-(ab * ab) / (0.13 * 0.13));
          // Deutlich heller als zuvor, und vor allem mit einem hoeheren
          // GRUNDWERT: Bisher war eine Leitung fast dunkel, solange kein
          // Lichtpunkt darauf lief - man sah nur wandernde Funken und
          // nicht, dass sie auf etwas wandern. Erst wenn die Leitung
          // selbst steht, liest man ein Netz.
          const hell =
            (0.42 + 1.30 * naehe) *
            (0.7 + anregung * 0.7) *
            (0.75 + 0.35 * atem) *
            eifer *
            1.7 *
            this.staerke;
          // Zum Cyan hin, wenn ein Signal darüberläuft – die Leitung
          // wechselt die Farbe dort, wo gerade etwas durchgeht.
          this.farbe.setHSL(
            (((this.zustandTon - naehe * 0.17 - anregung * 0.05) % 1) + 1) % 1,
            0.88,
            0.62 + naehe * 0.28
          );
          this.innenFarbe[q] = this.farbe.r * hell;
          this.innenFarbe[q + 1] = this.farbe.g * hell;
          this.innenFarbe[q + 2] = this.farbe.b * hell;
          ip++;
        }
      }
    }
    (this.innenG.getAttribute("position") as THREE.BufferAttribute).needsUpdate = true;
    (this.innenG.getAttribute("color") as THREE.BufferAttribute).needsUpdate = true;

    for (let k = 0; k < INNEN_N; k++) {
      let x = this.innenOrt[k].x * iw;
      let y = this.innenOrt[k].y * iw;
      let z = this.innenOrt[k].z * iw;
      this.kernStroemung(x, y, z, t);
      this.innenKnPos[k * 3] = x + this.kernFeld.x * 0.5;
      this.innenKnPos[k * 3 + 1] = y + this.kernFeld.y * 0.5;
      this.innenKnPos[k * 3 + 2] = z + this.kernFeld.z * 0.5;
      const hell =
        (0.40 + this.innenGlut[k] * 1.9) *
        (0.75 + 0.35 * atem) *
        eifer *
        1.6 *
        this.staerke;
      this.farbe.setHSL(
        (((this.zustandTon - this.innenGlut[k] * 0.16) % 1) + 1) % 1,
        0.95,
        0.55 + this.innenGlut[k] * 0.28
      );
      this.innenKnFarbe[k * 3] = this.farbe.r * hell;
      this.innenKnFarbe[k * 3 + 1] = this.farbe.g * hell;
      this.innenKnFarbe[k * 3 + 2] = this.farbe.b * hell;
    }
    (this.innenKnG.getAttribute("position") as THREE.BufferAttribute).needsUpdate = true;
    (this.innenKnG.getAttribute("color") as THREE.BufferAttribute).needsUpdate = true;

    // --- Das Leuchten in der Mitte -------------------------------------------
    //
    // Es erzählt über drei Grössen, was gerade geschieht:
    //   FARBE      – was für eine Tätigkeit es ist.
    //   TEMPO      – wie angestrengt.
    //   AUSDEHNUNG – ob sich etwas sammelt oder abgegeben wird.
    //
    // Nur die Helligkeit zu ändern wäre zu wenig: Heller kann alles
    // mögliche heissen. Erst wenn sich mehrere Dinge zugleich ändern,
    // liest man einen Zustand daraus.
    //
    // Beim Nachdenken zieht es sich ZUSAMMEN – etwas sammelt sich; beim
    // Sprechen dehnt es sich – etwas wird abgegeben.
    const glutTon =
      (((this.zustandTon +
        this.denken * -0.26 +
        this.sprechen * 0.06) %
        1) +
        1) %
      1;
    const glutTempo = ruhe * 1.0 + this.denken * 6.0 + this.sprechen * 2.4;
    const glutWeite = ruhe * 1.0 + this.denken * 0.82 + this.sprechen * 1.12;

    // Die Stösse beim Sprechen: Sie liegen auf Vielfachen von OM, damit
    // auch sie mit allem anderen zurückkehren.
    const stoss =
      this.sprechen *
      Math.max(0, Math.sin(t * OM * 8)) *
      Math.max(0, Math.sin(t * OM * 3));
    const puls =
      0.72 +
      0.28 * Math.sin(t * OM * Math.max(0.5, glutTempo)) +
      stoss * 0.55 +
      this.denken * 0.1 * Math.sin(t * OM * 11) +
      this.stimme * 0.25;

    for (const L of this.glutLagen) {
      for (let i = 0; i < L.zahl; i++) {
        let x = L.ruhe[i * 3] * glutWeite;
        let y = L.ruhe[i * 3 + 1] * glutWeite;
        let z = L.ruhe[i * 3 + 2] * glutWeite;

        // Die Flecken driften. Genau das macht den Umriss unbeschreibbar –
        // ohne Drift wäre es wieder eine feste Form, nur eine krumme.
        this.kernStroemung(x, y, z, t);
        const kraft = 1.6 * eifer;
        x += this.kernFeld.x * kraft;
        y += this.kernFeld.y * kraft;
        z += this.kernFeld.z * kraft;
        // Dazu ein eigenes Atmen je Fleck, damit sie nicht im Gleichschritt
        // wandern.
        const eigen = 1 + 0.18 * Math.sin(t * OM * 2 + L.phase[i]);
        L.pos[i * 3] = x * eigen;
        L.pos[i * 3 + 1] = y * eigen;
        L.pos[i * 3 + 2] = z * eigen;

        // Zur Mitte hin heisser: dort geht die Farbe ins Weisse.
        const weg = Math.sqrt(x * x + y * y + z * z) / KERN_R;
        const heiss = Math.max(0, 1 - weg * 1.5);
        const flimmern = 0.75 + 0.25 * Math.sin(t * OM * 3 + L.phase[i] * 2.1);
        const hell = puls * flimmern * (0.7 + 0.4 * atem);
        this.farbe.setHSL(
          (((glutTon + heiss * 0.04) % 1) + 1) % 1,
          0.95 - heiss * 0.8,
          0.48 + heiss * 0.45
        );
        L.col[i * 3] = this.farbe.r * hell;
        L.col[i * 3 + 1] = this.farbe.g * hell;
        L.col[i * 3 + 2] = this.farbe.b * hell;
      }
      (L.geometrie.getAttribute("position") as THREE.BufferAttribute).needsUpdate = true;
      (L.geometrie.getAttribute("color") as THREE.BufferAttribute).needsUpdate = true;
      L.material.size = L.groesse * glutWeite * (0.9 + 0.2 * puls) * mass;
      L.material.opacity =
        L.grund * (0.78 + 0.42 * atem) * anlauf * this.staerke;
    }

    // --- Der Nebel ringsum ---------------------------------------------------
    //
    // Er zieht träger als alles andere. Ein Nebel, der genau mitmacht,
    // wirkt wie ein Anhängsel des Kerns; einer, der nachhinkt, wirkt wie
    // etwas, worin der Kern liegt.
    for (const L of this.nebelLagen) {
      for (let i = 0; i < L.zahl; i++) {
        let x = L.ruhe[i * 3];
        let y = L.ruhe[i * 3 + 1];
        let z = L.ruhe[i * 3 + 2];

        // Eine langsame Drehung, innen schneller als aussen – sonst
        // erkennt das Auge sofort einen starren Körper.
        const rr = Math.sqrt(x * x + y * y);
        const innen = 1 - Math.min(1, rr / (KERN_R * L.weite)) * 0.6;
        const dreh = t * OM * 0.55 * innen;
        const cx = Math.cos(dreh);
        const sx = Math.sin(dreh);
        const nx = x * cx - y * sx;
        y = x * sx + y * cx;
        x = nx;

        // Und das grosse Strömungsfeld, kräftiger als beim Kern: Nebel
        // gibt nach.
        this.stroemung(x, y, z, t);
        x += this.feld.x * 2.4;
        y += this.feld.y * 2.4;
        z += this.feld.z * 2.4;
        const eigen = 1 + 0.12 * Math.sin(t * OM + L.phase[i]);
        x *= eigen;
        y *= eigen;
        z *= eigen;

        // Die harte Decke: Was über sie hinausragt, schneidet das Fenster
        // ab – und eine abgeschnittene Nebelflocke ist genau die Kante,
        // wegen der die Hülle weichen musste.
        const abstand = Math.sqrt(x * x + y * y + z * z);
        if (abstand > HARTE_DECKE) {
          const f = HARTE_DECKE / abstand;
          x *= f;
          y *= f;
          z *= f;
        }
        L.pos[i * 3] = x;
        L.pos[i * 3 + 1] = y;
        L.pos[i * 3 + 2] = z;

        // Nach aussen ausblutend, ohne Grenze. Das ist der ganze Grund,
        // warum hier Nebel steht und keine Hülle.
        const weg = Math.sqrt(x * x + y * y + z * z) / KERN_R;
        // Nach aussen ausblutend, nach innen ausgeblendet.
        //
        // Die zweite Haelfte ist neu: Ein Fleck, den die Stroemung nach
        // innen traegt, laege sonst wieder auf dem Netz. Der Uebergang ist
        // weich und die Flecken driften, deshalb entsteht dabei kein
        // sichtbarer Innenrand - und der waere ohnehin vom Kernleuchten
        // verdeckt.
        const hohl = Math.min(1, Math.max(0.06, (weg - 0.75) / 0.95));
        const dichte = Math.exp(-Math.pow(weg / 1.8, 2)) * hohl;
        const schwaden = 0.6 + 0.4 * Math.sin(t * OM * 2 + L.phase[i] * 1.7);

        // Einfarbig, wie der Benutzer es schon bei den Kugeln wollte:
        // Trägt die Umgebung dieselben Farben wie das, was darin leuchten
        // soll, hebt sich nichts mehr ab.
        this.farbe.setHSL(
          (((glutTon + 0.3) % 1) + 1) % 1,
          0.82,
          0.42 + 0.09 * atem
        );
        const d = dichte * schwaden * (0.72 + 0.48 * atem) * eifer * 1.05;
        L.col[i * 3] = this.farbe.r * d;
        L.col[i * 3 + 1] = this.farbe.g * d;
        L.col[i * 3 + 2] = this.farbe.b * d;
      }
      (L.geometrie.getAttribute("position") as THREE.BufferAttribute).needsUpdate = true;
      (L.geometrie.getAttribute("color") as THREE.BufferAttribute).needsUpdate = true;
      L.material.size = L.groesse * mass;
      L.material.opacity =
        L.grund * (0.74 + 0.46 * atem) * anlauf * this.staerke;
    }
  }

  /**
   * Passt den Aufwand an die Leistungsstufe an.
   *
   * Der Nebel kostet am meisten Füllrate, weil seine Flecken gross sind
   * und sich überlagern – er wird zuerst gekürzt. Das Netz bleibt: ohne es
   * gäbe es nichts mehr zu sehen.
   *
   * Gekürzt wird über `setDrawRange` und nicht durch Neuaufbau: Die
   * Flecken sind von innen nach aussen NICHT sortiert, aber sie sind
   * zufällig verteilt – die ersten sechzig Prozent sehen deshalb aus wie
   * ein dünnerer Nebel und nicht wie ein halber.
   */
  public setQuality(level: number): void {
    for (const L of this.nebelLagen) {
      const anteil = level >= 2 ? 1.0 : level >= 1 ? 0.5 : 0.0;
      L.punkte.visible = anteil > 0;
      L.geometrie.setDrawRange(0, Math.floor(L.zahl * anteil));
    }
    for (const L of this.glutLagen) {
      const anteil = level >= 1 ? 1.0 : 0.6;
      L.geometrie.setDrawRange(0, Math.floor(L.zahl * anteil));
    }
    this.innenKnoten.visible = level >= 1;
  }

  /** Gibt alle GPU-Ressourcen frei. */
  public dispose(): void {
    this.innenG.dispose();
    this.innenKnG.dispose();
    this.innenMaterial.dispose();
    this.innenKnMaterial.dispose();
    for (const L of [...this.nebelLagen, ...this.glutLagen]) {
      L.geometrie.dispose();
      L.material.dispose();
    }
    this.scheinTex.dispose();
  }
}
