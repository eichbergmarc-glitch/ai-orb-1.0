/**
 * zwei_punkte.ts – zwei Punkte, die einander umkreisen und verschmelzen.
 *
 * Der Benutzer hat diese Darstellung genau beschrieben und in der Vorschau
 * abgenommen: Ein roter und ein blauer Punkt drehen sich umeinander – nie
 * im selben Takt, die Richtung wechselt von selbst. Denkt oder spricht der
 * Orb, ziehen sie sich an und verschmelzen zu einem Nebel, in dem sich die
 * Farben mischen; danach trennen sie sich wieder.
 *
 * ## Warum die Punkte Wolken sind
 *
 * Jeder Punkt besteht aus weichen Flecken, nicht aus einer Scheibe. Nur so
 * kann das Verschmelzen aussehen wie Nebel, der sich vermischt – zwei
 * harte Kugeln könnten nur ineinander verschwinden. Ein sehr kleiner
 * Innenkern gibt der Mitte Halt, ohne das Nebelhafte zu nehmen; das war
 * die Fassung, die der Benutzer nach zwei Anläufen als „perfekt" abnahm:
 * die erste Gestalt, nur heller.
 *
 * ## Warum der Drehsinn am Lorenz-System hängt
 *
 * Zufall sieht nicht nach Unvorhersehbarkeit aus, sondern nach Zittern.
 * Das Lorenz-System ist deterministisch, begrenzt, und kehrt trotzdem nie
 * in denselben Zustand zurück: Es kreist um den einen Flügel, springt auf
 * den anderen – und WANN, ist nicht vorhersagbar. Durch die Trägheit kommt
 * der Wechsel als Schwung an: Der Punkt wird langsamer, steht fast, zieht
 * dann in die Gegenrichtung an.
 *
 * ## Warum die Farben je Fleck mischen
 *
 * Beim Verschmelzen wandert die Farbe JEDES Fleckens einzeln von Rot bzw.
 * Blau über Violett zur anderen Seite – abhängig davon, wo er in der
 * Wolke steht. Dadurch entstehen Schlieren, wie wenn zwei farbige Nebel
 * ineinanderziehen, statt eines Farbwechsels auf Knopfdruck. Rot steht
 * als Farbton 1.0 und nicht als 0.0, damit der Weg von Blau (0.62) nach
 * Rot über Violett führt und nicht über Grün.
 *
 * ## Was aus den Vorgängern gelernt ist
 *
 * Kein eigener Shader – three.js übersetzt ihn als GLSL ES 1.00, und was
 * dort nicht erlaubt ist, scheitert lautlos. Und jede Punktgrösse wird mit
 * dem Weltmassstab multipliziert: `PointsMaterial.size` wird von der
 * Skalierung der Elterngruppe NICHT erfasst – ohne diese Multiplikation
 * war der Vorgänger im Orb ein Schmier, in dem nichts zu erkennen war.
 */

import * as THREE from "three";

/**
 * Der Grundabstand der beiden Punkte von Mitte zu Mitte.
 *
 * Etwas grösser als in der Vorschau (0.55): Bei der jetzigen Zielgrösse
 * von ~1 cm je Punkt lägen sie sonst fast aneinander. 0.68 lässt im
 * getrennten Zustand einen sichtbaren Spalt.
 */
const ABSTAND = 0.68;

/** Der Radius einer einzelnen Punktwolke. */
const PUNKT_R = 0.16;

/**
 * Die Lagen einer Wolke – grosse Flecken tragen den Hof, kleine die
 * Dichte, die vierte ist der winzige Innenkern.
 *
 * Genau die Zahlen der abgenommenen Vorschau. Ein früherer Anlauf machte
 * die Wolken dichter und den Kern dick – der Benutzer wollte die erste
 * Gestalt zurück, nur heller. Heller wird es über `deckung` und die
 * Leuchtkraft im Lauf, nicht über die Form.
 */
const LAGEN = [
  { zahl: 10, groesse: 0.42, weite: 1.15, deckung: 0.32 },
  { zahl: 16, groesse: 0.22, weite: 0.85, deckung: 0.46 },
  { zahl: 22, groesse: 0.1, weite: 0.55, deckung: 0.68 },
  { zahl: 6, groesse: 0.055, weite: 0.16, deckung: 0.85 },
];

/** Wie viele Stationen jeder Schweif hat. */
const SCHWEIF = 26;

/** Die Farbtöne (siehe Modulkommentar: Rot als 1.0, nicht 0.0). */
const TON_ROT = 1.0;
const TON_BLAU = 0.62;

/** Ein einfacher, wiederholbarer Zufall – nur für den Aufbau, nie im Lauf. */
function zufall(saat: number): () => number {
  let s = saat >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 4294967296;
  };
}

/** Eine Lage weicher Flecken beider Wolken. */
interface Lage {
  geometrie: THREE.BufferGeometry;
  material: THREE.PointsMaterial;
  punkte: THREE.Points;
  pos: Float32Array;
  col: Float32Array;
  ruhe: Float32Array;
  phase: Float32Array;
  /** 0 = roter Punkt, 1 = blauer Punkt. */
  seite: Float32Array;
  /** Wie früh dieser Fleck beim Verschmelzen die Farbe wechselt. */
  neigung: Float32Array;
  zahl: number;
  grund: number;
  groesse: number;
  weite: number;
}

/**
 * Die vom Benutzer per Sprache veränderbaren Werte.
 *
 * Sie kommen aus `orb.animation` in der config.yaml und werden beim
 * Aufbau gelesen. Jeder ist optional: Fehlt einer, gilt die abgenommene
 * Vorgabe (die Konstanten oben). So kann eine unvollständige oder alte
 * config die Animation nie kaputtmachen – sie sieht dann aus wie zuvor.
 */
export interface ZweiPunkteOptionen {
  abstand?: number;
  punktGroesse?: number;
  verschmelzen?: number;
  schweifLaenge?: number;
  tempo?: number;
  helligkeit?: number;
  farbeA?: number;
  farbeB?: number;
}

/**
 * Die zwei Punkte.
 *
 * Die Schnittstelle ist dieselbe wie bei den Vorgängern (`NeuralFluid`,
 * `DualOrbit`) – `orb.ts` muss nur den Namen austauschen.
 */
export class ZweiPunkte {
  /** Die Gruppe, die alles enthält. */
  public readonly group: THREE.Group;

  private readonly lagen: Lage[] = [];
  private readonly scheinTex: THREE.Texture;

  // --- Die Schweife --------------------------------------------------------
  private readonly schweifPos: Float32Array;
  private readonly schweifCol: Float32Array;
  private readonly schweifG: THREE.BufferGeometry;
  private readonly schweifMat: THREE.PointsMaterial;
  private readonly schweifPunkte: THREE.Points;
  // Der durchgehende Faden – eine Linie durch dieselben Orte. Der
  // Benutzer wollte, dass die Kugeln Streifen ziehen; Punkte allein
  // wirken wie eine Perlenkette, erst die Linie ist eine Spur.
  private readonly fadenCol: Float32Array;
  private readonly fadenG: THREE.BufferGeometry;
  private readonly fadenMat: THREE.LineBasicMaterial;
  private readonly fadenLinien: THREE.LineSegments;
  private readonly spurA: Array<{ x: number; y: number; z: number }> = [];
  private readonly spurB: Array<{ x: number; y: number; z: number }> = [];

  // --- Das Lorenz-System ---------------------------------------------------
  private lx = 0.9;
  private ly = 1.2;
  private lz = 22.0;

  // --- Zustand -------------------------------------------------------------
  private stimme = 0.0;
  private staerke = 1.0;
  /** Die geglättete Ansage „es wird gesprochen" bzw. „gedacht". */
  private sprechen = 0.0;
  private denken = 0.0;
  private aufbau = 0.0;
  /** Die eigene Uhr – diese Darstellung braucht keine exakte Schleife. */
  private t = 0.0;

  private winkel = 0.0;
  private dreh = 1.4;
  private misch = 0.0;

  // --- Die veränderbaren Werte (aus orb.animation) -------------------------
  private readonly abstandBasis: number;
  private readonly punktGroesse: number;
  private readonly verschmelzen: number;
  private readonly schweif: number;
  private readonly tempo: number;
  private readonly helligkeit: number;
  private readonly tonA: number;
  private readonly tonB: number;
  private abstand: number;

  // Wiederverwendet – kein neues Objekt je Bild.
  private readonly farbe = new THREE.Color();
  private readonly weltMassstab = new THREE.Vector3(1, 1, 1);

  constructor(opt: ZweiPunkteOptionen = {}) {
    // Zuerst die Werte – die Feldgrössen weiter unten hängen an `schweif`.
    // Jeder mit `??` auf die abgenommene Vorgabe zurückfallend.
    this.abstandBasis = _zahl(opt.abstand, ABSTAND, 0.2, 1.4);
    this.punktGroesse = _zahl(opt.punktGroesse, 1.0, 0.35, 3.0);
    this.verschmelzen = _zahl(opt.verschmelzen, 1.15, 0.4, 3.5);
    this.schweif = Math.round(_zahl(opt.schweifLaenge, SCHWEIF, 6, 120));
    this.tempo = _zahl(opt.tempo, 1.0, 0.2, 4.0);
    this.helligkeit = _zahl(opt.helligkeit, 1.0, 0.4, 2.5);
    this.tonA = _zahl(opt.farbeA, TON_ROT, 0.0, 1.0);
    this.tonB = _zahl(opt.farbeB, TON_BLAU, 0.0, 1.0);
    this.abstand = this.abstandBasis;

    this.group = new THREE.Group();
    const w = zufall(20260816);
    this.scheinTex = this.scheinBild();

    for (const l of LAGEN) {
      const gesamt = l.zahl * 2;
      const pos = new Float32Array(gesamt * 3);
      const col = new Float32Array(gesamt * 3);
      const ruhe = new Float32Array(gesamt * 3);
      const phase = new Float32Array(gesamt);
      const seite = new Float32Array(gesamt);
      const neigung = new Float32Array(gesamt);
      for (let i = 0; i < gesamt; i++) {
        // Die dritte Wurzel verteilt gleichmässig über das Volumen – ohne
        // sie sässen fast alle Flecken aussen und die Wolke wäre hohl.
        const r = Math.cbrt(w()) * PUNKT_R * this.punktGroesse * l.weite;
        const z = w() * 2 - 1;
        const phi = w() * Math.PI * 2;
        const sq = Math.sqrt(Math.max(0, 1 - z * z));
        ruhe[i * 3] = Math.cos(phi) * sq * r;
        ruhe[i * 3 + 1] = Math.sin(phi) * sq * r;
        ruhe[i * 3 + 2] = z * r * 0.8;
        phase[i] = w() * Math.PI * 2;
        seite[i] = i < l.zahl ? 0 : 1;
        neigung[i] = w();
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
        sizeAttenuation: true,
      });
      const punkte = new THREE.Points(geometrie, material);
      this.group.add(punkte);
      this.lagen.push({
        geometrie,
        material,
        punkte,
        pos,
        col,
        ruhe,
        phase,
        seite,
        neigung,
        zahl: gesamt,
        grund: l.deckung,
        groesse: l.groesse,
        weite: l.weite,
      });
    }

    // Die Schweife: je Punkt eine Kette verblassender Flecken auf seinen
    // letzten Orten. So sieht man nicht nur, DASS sich etwas dreht,
    // sondern welche Schleife es gerade zieht.
    this.schweifPos = new Float32Array(this.schweif * 2 * 3);
    this.schweifCol = new Float32Array(this.schweif * 2 * 3);
    this.schweifG = new THREE.BufferGeometry();
    this.schweifG.setAttribute(
      "position",
      new THREE.BufferAttribute(this.schweifPos, 3)
    );
    this.schweifG.setAttribute(
      "color",
      new THREE.BufferAttribute(this.schweifCol, 3)
    );
    this.schweifMat = new THREE.PointsMaterial({
      size: 0.07,
      map: this.scheinTex,
      vertexColors: true,
      transparent: true,
      opacity: 0.5,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
      sizeAttenuation: true,
    });
    this.schweifPunkte = new THREE.Points(this.schweifG, this.schweifMat);
    this.group.add(this.schweifPunkte);

    // Der Faden teilt sich die Orte mit den Schweif-Punkten, hat aber
    // eigene (kräftigere) Farben. LineSegments und nicht Line: Zwei
    // getrennte Züge – einer je Punkt – dürfen nicht durch einen Sprung
    // von der einen zur anderen Kugel verbunden werden.
    this.fadenCol = new Float32Array(this.schweif * 2 * 3);
    this.fadenG = new THREE.BufferGeometry();
    this.fadenG.setAttribute(
      "position",
      new THREE.BufferAttribute(this.schweifPos, 3)
    );
    this.fadenG.setAttribute(
      "color",
      new THREE.BufferAttribute(this.fadenCol, 3)
    );
    const index: number[] = [];
    for (let k = 0; k < this.schweif - 1; k++) index.push(k, k + 1);
    for (let k = 0; k < this.schweif - 1; k++) index.push(this.schweif + k, this.schweif + k + 1);
    this.fadenG.setIndex(index);
    this.fadenMat = new THREE.LineBasicMaterial({
      vertexColors: true,
      transparent: true,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    this.fadenLinien = new THREE.LineSegments(this.fadenG, this.fadenMat);
    this.group.add(this.fadenLinien);
  }

  /** Die Textur für einen weichen Fleck – früh abfallend, lang auslaufend. */
  private scheinBild(): THREE.Texture {
    const gr = 64;
    const lw = document.createElement("canvas");
    lw.width = gr;
    lw.height = gr;
    const c2 = lw.getContext("2d");
    if (c2 !== null) {
      const v = c2.createRadialGradient(gr / 2, gr / 2, 0, gr / 2, gr / 2, gr / 2);
      v.addColorStop(0.0, "rgba(255,255,255,1)");
      v.addColorStop(0.12, "rgba(255,255,255,0.55)");
      v.addColorStop(0.32, "rgba(255,255,255,0.16)");
      v.addColorStop(0.6, "rgba(255,255,255,0.035)");
      v.addColorStop(1.0, "rgba(255,255,255,0)");
      c2.fillStyle = v;
      c2.fillRect(0, 0, gr, gr);
    }
    const tex = new THREE.CanvasTexture(lw);
    tex.needsUpdate = true;
    return tex;
  }

  /**
   * Die Weltskalierung der Gruppe.
   *
   * `PointsMaterial.size` wird von der Objektskalierung NICHT erfasst –
   * der Vertex-Shader für Punkte teilt nur durch die Tiefe. Ohne diese
   * Multiplikation behielten die Flecken ihre volle Grösse, während die
   * Positionen auf ein Sechstel schrumpfen: Jeder Fleck wäre so gross wie
   * die ganze Wolke. Genau so sah der Fehler beim Vorgänger aus.
   */
  private massstab(): number {
    this.group.updateWorldMatrix(true, false);
    this.group.getWorldScale(this.weltMassstab);
    const s = this.weltMassstab.x;
    return s > 0.0001 ? s : 1.0;
  }

  /**
   * Übernimmt die Farben des Zustands – hier bewusst NUR die Stärke.
   *
   * Rot und Blau sind keine Themenfarben, sondern der Inhalt dieser
   * Darstellung: Der Benutzer hat sie ausdrücklich verlangt („sie sollen
   * jeweils rot und blau sein"). Ein Theme, das die Töne verschöbe, würde
   * genau das zerstören – also wird nur die Leuchtstärke übernommen.
   */
  public setColors(
    kern: THREE.Color,
    schein: THREE.Color,
    staerke: number
  ): void {
    void kern;
    void schein;
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
   * @param elapsed Laufzeit in Sekunden (ungenutzt – die eigene Uhr zählt).
   * @param delta Zeit seit dem letzten Bild.
   * @param tempo Geschwindigkeit des Zustands (siehe `states.ts`).
   */
  public update(elapsed: number, delta: number, tempo: number): void {
    void elapsed;
    const dt = Math.min(0.05, Math.max(0, delta));
    this.t += dt;
    this.aufbau = Math.min(2.0, this.aufbau + dt);
    const anlauf = Math.min(1.0, this.aufbau / 1.6);
    const t = this.t;

    // --- Was gerade geschieht ----------------------------------------------
    // Kein Aufzählungswert, sondern zwei Zahlen: Zustandstempo und
    // Stimmpegel. Daraus wird TRÄGE zurückgelesen, was los ist – ein
    // Zustand, der im Bild springt, wirkt wie ein Schnitt.
    const zielSprechen = Math.min(1, this.stimme * 2.2);
    const zielDenken = Math.max(
      0,
      Math.min(1, (tempo - 1.15) / 0.45) * (1 - zielSprechen)
    );
    const tr = 1.0 - Math.exp(-dt * 3.2);
    this.sprechen += (zielSprechen - this.sprechen) * tr;
    this.denken += (zielDenken - this.denken) * tr;
    const beschaeftigt = Math.min(1, this.denken + this.sprechen);

    // --- Das Lorenz-System liefert den Drehsinn ----------------------------
    const h = Math.min(0.012, dt);
    const dx = 10.0 * (this.ly - this.lx);
    const dy = this.lx * (28.0 - this.lz) - this.ly;
    const dz = this.lx * this.ly - (8.0 / 3.0) * this.lz;
    this.lx += dx * h;
    this.ly += dy * h;
    this.lz += dz * h;

    // tanh macht aus dem wilden lx ein weiches -1..1; die zeitgeführte
    // Trägheit lässt den Richtungswechsel als Schwung ankommen statt als
    // Sprung.
    const zielDreh =
      (1.1 + 0.8 * Math.abs(Math.sin(t * 0.23))) * Math.tanh(this.lx / 6.0) * 2.2;
    this.dreh += (zielDreh * this.tempo - this.dreh) * (1 - Math.exp(-dt * 0.9));

    // --- Verschmelzen und Trennen ------------------------------------------
    const zielAbstand = this.abstandBasis * (1 - beschaeftigt) + 0.02 * beschaeftigt;
    this.abstand += (zielAbstand - this.abstand) * (1 - Math.exp(-dt * 2.2));
    this.misch += (beschaeftigt - this.misch) * (1 - Math.exp(-dt * 1.6));
    const misch = this.misch;

    // Eng = träge, wie Masse: Verschmolzen dreht das Ganze langsamer.
    this.winkel += this.dreh * dt * (0.4 + 0.6 * (this.abstand / this.abstandBasis));

    // Die Bahnebene kippt langsam – sonst sähe man einen flachen Kreisel.
    const kippA = Math.sin(t * 0.21) * 0.55 + Math.sin(t * 0.083 + 1.7) * 0.35;
    const kippB = Math.sin(t * 0.147 + 0.6) * 0.5;

    const ax = Math.cos(this.winkel);
    const ay = Math.sin(this.winkel);
    const halb = this.abstand / 2;
    const mx = Math.sin(t * 0.31) * 0.05;
    const my = Math.cos(t * 0.27) * 0.05;
    const Ax = mx + ax * halb;
    const Ay = my + ay * halb * Math.cos(kippA);
    const Az = ay * halb * Math.sin(kippA) + Math.sin(kippB) * 0.06;
    const Bx = mx - ax * halb;
    const By = my - ay * halb * Math.cos(kippA);
    const Bz = -ay * halb * Math.sin(kippA) - Math.sin(kippB) * 0.06;

    // --- Atmen und Pulsieren ------------------------------------------------
    const atem = 0.5 - 0.5 * Math.cos(t * 0.7);
    const stoss =
      Math.max(0, Math.sin(t * 8.0)) * Math.max(0, Math.sin(t * 3.1));
    const pulsTempo = 1.0 + this.denken * 4.0 + this.sprechen * 1.6;
    const weite =
      1.0 +
      this.denken * (-0.1 + 0.12 * Math.sin(t * 9.0)) +
      this.sprechen * (0.05 + 0.22 * stoss + 0.25 * this.stimme);
    const puls = 0.75 + 0.25 * Math.sin(t * pulsTempo);

    // Verschmolzen wird die eine Wolke deutlich grösser als ein einzelner
    // Punkt – zwei Nebel ergeben zusammen mehr als einer.
    //
    // Der Faktor 1.15 ist gerechnet, nicht geraten: Der Benutzer will je
    // Punkt ~1 cm und verschmolzen ~2,5 cm. Bei `misch === 1` wächst die
    // Wolke damit auf gut das Doppelte-Komma-Fünf eines einzelnen Punkts.
    const wolke = (1 + misch * this.verschmelzen) * weite;

    const mass = this.massstab();

    // --- Die Flecken --------------------------------------------------------
    for (const L of this.lagen) {
      for (let i = 0; i < L.zahl; i++) {
        const s = L.seite[i];
        const Mx = s === 0 ? Ax : Bx;
        const My = s === 0 ? Ay : By;
        const Mz = s === 0 ? Az : Bz;
        // Der Ruheort atmet und wird von einem feinen Feld verzogen,
        // damit der Nebel WABERT statt zu stehen.
        const ox = L.ruhe[i * 3] * wolke;
        const oy = L.ruhe[i * 3 + 1] * wolke;
        const oz = L.ruhe[i * 3 + 2] * wolke;
        const fx =
          Math.sin(oy * 7.0 + t * 1.9 + L.phase[i]) * 0.022 +
          Math.sin(oz * 9.0 - t * 1.3) * 0.014;
        const fy =
          Math.sin(oz * 8.0 - t * 1.7 + L.phase[i]) * 0.022 +
          Math.sin(ox * 8.5 + t * 1.1) * 0.014;
        const fz = Math.sin(ox * 7.5 + t * 2.1) * 0.018;
        const eigen = 1 + 0.16 * Math.sin(t * 1.4 + L.phase[i]);
        const x = Mx + (ox + fx) * eigen;
        const y = My + (oy + fy) * eigen;
        const z = Mz + (oz + fz) * eigen;
        L.pos[i * 3] = x;
        L.pos[i * 3 + 1] = y;
        L.pos[i * 3 + 2] = z;

        // --- Die Farbe: das Herzstück ----------------------------------
        // Getrennt: Seite 0 rot, Seite 1 blau. Beim Verschmelzen zieht
        // jeder Fleck EINZELN zur anderen Seite hinüber – wie früh, hängt
        // an seiner Mischneigung und daran, wo er in der Wolke steht. So
        // entstehen die Schlieren.
        const eigenTon = s === 0 ? this.tonA : this.tonB;
        const fremdTon = s === 0 ? this.tonB : this.tonA;
        const schliere =
          0.5 + 0.5 * Math.sin(t * 1.1 + L.neigung[i] * 6.28 + x * 3.0 + y * 2.2);
        const zug =
          misch *
          Math.min(1, Math.max(0, L.neigung[i] * 0.7 + schliere * 0.5));
        const ton = eigenTon + (fremdTon - eigenTon) * zug;
        // Heller als die erste Fassung (die Abnahme des Benutzers), aber
        // die Gestalt bleibt: satte Farbe, nur der Innenkern hellt auf.
        const kern = L.weite < 0.3 ? 1 : 0;
        const hell =
          (puls * (0.95 + 0.45 * atem) * (0.85 + 0.3 * misch) +
            this.denken * 0.1 * Math.sin(t * 11 + L.phase[i])) *
          (1.0 + kern * 0.7) *
          1.35 *
          this.helligkeit *
          anlauf *
          this.staerke;
        this.farbe.setHSL(
          ((ton % 1) + 1) % 1,
          0.95 - kern * 0.3,
          0.55 + kern * 0.18 + 0.08 * misch * schliere
        );
        L.col[i * 3] = this.farbe.r * hell;
        L.col[i * 3 + 1] = this.farbe.g * hell;
        L.col[i * 3 + 2] = this.farbe.b * hell;
      }
      (L.geometrie.getAttribute("position") as THREE.BufferAttribute).needsUpdate = true;
      (L.geometrie.getAttribute("color") as THREE.BufferAttribute).needsUpdate = true;
      L.material.size =
        L.groesse * (0.9 + 0.2 * puls) * (1 + misch * 0.3) * mass;
      L.material.opacity = L.grund * (0.85 + 0.35 * atem) * anlauf;
    }

    // --- Die Schweife -------------------------------------------------------
    this.spurA.unshift({ x: Ax, y: Ay, z: Az });
    if (this.spurA.length > this.schweif) this.spurA.pop();
    this.spurB.unshift({ x: Bx, y: By, z: Bz });
    if (this.spurB.length > this.schweif) this.spurB.pop();
    for (let k = 0; k < this.schweif; k++) {
      const a = this.spurA[Math.min(k, this.spurA.length - 1)];
      const b = this.spurB[Math.min(k, this.spurB.length - 1)];
      const q = k * 3;
      const q2 = (this.schweif + k) * 3;
      this.schweifPos[q] = a.x;
      this.schweifPos[q + 1] = a.y;
      this.schweifPos[q + 2] = a.z;
      this.schweifPos[q2] = b.x;
      this.schweifPos[q2 + 1] = b.y;
      this.schweifPos[q2 + 2] = b.z;
      // Quadratisch verblassend, und beim Verschmelzen verschwinden die
      // Schweife – ein stehender Nebel zieht keine Spur.
      const u = 1 - k / this.schweif;
      const st = u * u * 1.1 * (1 - misch) * anlauf * this.staerke;
      this.farbe.setHSL(this.tonA % 1, 0.95, 0.55);
      this.schweifCol[q] = this.farbe.r * st;
      this.schweifCol[q + 1] = this.farbe.g * st;
      this.schweifCol[q + 2] = this.farbe.b * st;
      this.farbe.setHSL(this.tonB, 0.95, 0.55);
      this.schweifCol[q2] = this.farbe.r * st;
      this.schweifCol[q2 + 1] = this.farbe.g * st;
      this.schweifCol[q2 + 2] = this.farbe.b * st;
    }
    // Der Faden nimmt die Schweiffarben, etwas kräftiger, damit die
    // Linie trägt. Die Orte teilt er sich ohnehin (dasselbe Array).
    for (let k = 0; k < this.schweif * 2; k++) {
      this.fadenCol[k * 3] = this.schweifCol[k * 3] * 1.4;
      this.fadenCol[k * 3 + 1] = this.schweifCol[k * 3 + 1] * 1.4;
      this.fadenCol[k * 3 + 2] = this.schweifCol[k * 3 + 2] * 1.4;
    }
    (this.schweifG.getAttribute("position") as THREE.BufferAttribute).needsUpdate = true;
    (this.schweifG.getAttribute("color") as THREE.BufferAttribute).needsUpdate = true;
    (this.fadenG.getAttribute("position") as THREE.BufferAttribute).needsUpdate = true;
    (this.fadenG.getAttribute("color") as THREE.BufferAttribute).needsUpdate = true;
    this.schweifMat.size = 0.07 * mass;
  }

  /**
   * Passt den Aufwand an die Leistungsstufe an.
   *
   * Die Schweife und die äusserste Hoflage kosten am meisten Füllrate –
   * sie fallen zuerst. Die Punkte selbst bleiben: ohne sie gäbe es nichts
   * mehr zu sehen.
   */
  public setQuality(level: number): void {
    this.schweifPunkte.visible = level >= 1;
    this.fadenLinien.visible = level >= 1;
    for (const L of this.lagen) {
      const anteil = level >= 1 ? 1.0 : L.weite > 1.0 ? 0.5 : 1.0;
      L.geometrie.setDrawRange(0, Math.floor(L.zahl * anteil));
    }
  }

  /** Gibt alle GPU-Ressourcen frei. */
  public dispose(): void {
    for (const L of this.lagen) {
      L.geometrie.dispose();
      L.material.dispose();
    }
    this.schweifG.dispose();
    this.schweifMat.dispose();
    this.fadenG.dispose();
    this.fadenMat.dispose();
    this.scheinTex.dispose();
  }
}

/**
 * Liest einen optionalen Wert, mit Vorgabe und Grenzen.
 *
 * Die Grenzen sind hier UND im Backend (config_schreiber) gesetzt – zwei
 * Wächter für denselben Wert. Käme über eine von Hand verpfuschte config
 * ein Unsinnswert herein, finge ihn spätestens dieser ab, statt die
 * Animation zerbröseln zu lassen.
 */
function _zahl(wert: number | undefined, vorgabe: number, min: number, max: number): number {
  if (typeof wert !== "number" || !Number.isFinite(wert)) return vorgabe;
  return Math.max(min, Math.min(max, wert));
}
