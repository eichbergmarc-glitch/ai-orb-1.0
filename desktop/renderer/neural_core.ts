/**
 * neural_core.ts – der atmende Nervenkern.
 *
 * Vorbild ist eine Beschreibung, die der Benutzer mitgebracht hat: ein
 * leuchtender Nervenkern aus durchscheinenden Fäden, fliessenden Häuten
 * und winzigen, untereinander verbundenen Teilchen. Er liegt zusammen-
 * gezogen in der Mitte, dehnt sich wie ein Atemzug nach aussen, wobei
 * Wellen in langsamen Bögen durch die Fäden laufen, und zieht sich wieder
 * genau in seine Ausgangslage zurück – ein Kreis ohne Schnitt.
 *
 * ## Warum es wirklich ein Kreis ist und nicht bloss ungefähr
 *
 * Das ist die eine Eigenschaft, an der so etwas steht oder fällt, und man
 * bekommt sie nicht durch Sorgfalt, sondern durch die Wahl der Formel.
 * Alles Zeitabhängige hier hängt an `sin` oder `cos` einer Zeit, die durch
 * die Atemdauer geteilt ist – und an nichts sonst. Damit ist der Zustand
 * nach sechs Sekunden nicht ähnlich dem Anfangszustand, sondern
 * derselbe, bis auf die letzte Stelle.
 *
 * Die Wellen, die durch die Fäden laufen, sind derselbe Fall: Es sind
 * genau zwei je Atemzug. Eine krumme Zahl – zweieinhalb Wellen – ergäbe
 * einen Sprung an der Nahtstelle, und zwar einen, den man nur alle sechs
 * Sekunden sieht und deshalb beim Zusehen kaum findet.
 *
 * Ausgenommen davon ist einzig, was die Stimme tut: Sie soll den Kern
 * gerade nicht im Takt lassen, sondern stören. Ein Atemzug, der beim
 * Sprechen unbeirrt weiterläuft, wirkt wie eine Anzeige, nicht wie ein
 * Lebewesen.
 *
 * ## Woraus er besteht
 *
 * Drei Lagen, jede mit einer Aufgabe:
 *
 *   1. Die Fäden. Vom Zentrum nach aussen, dabei um ihre eigene Richtung
 *      gewunden. Zusammengezogen sind sie eng gerollt, ausgedehnt strecken
 *      sie sich – das ist der Unterschied zwischen einem Ball, der grösser
 *      wird, und etwas, das sich entfaltet.
 *
 *   2. Die Häute. Zwei durchscheinende Schalen, die versetzt zueinander
 *      atmen. Sie tragen kaum Form bei, aber sie geben dem Licht ein
 *      Volumen, in dem es sich verteilen kann – ohne sie sähe man Linien
 *      im Nichts.
 *
 *   3. Die Teilchen. Sie sitzen auf den Fäden und leuchten auf, wenn eine
 *      Welle sie erreicht. Sie sind es, die aus Fäden ein Netz machen:
 *      Man sieht, dass etwas weitergereicht wird.
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
 * der bestehende Bloom-Effekt. Die Bahnen und Helligkeiten rechnet die
 * CPU. Das ist nicht die elegante Lösung, aber es ist die, die man sieht –
 * und ein Effekt, den niemand sieht, ist kein Effekt.
 */

import * as THREE from "three";

/**
 * Die Dauer eines vollständigen Atemzugs in Sekunden.
 *
 * Sechs Sekunden sind langsamer, als es sich beim Lesen anhört – und
 * genau darum geht es. Ein schnellerer Kern wirkt aufgeregt; dieser soll
 * ruhen und dabei leben.
 */
const ATEM_DAUER = 6.0;

/**
 * So viele Wellen laufen je Atemzug durch die Fäden.
 *
 * Eine GANZE Zahl, und das ist keine Geschmacksfrage: Bei zweieinhalb
 * Wellen springt das Bild an der Nahtstelle des Kreises.
 */
const WELLEN_JE_ATEM = 2;

/** So viele Fäden gehen vom Zentrum aus. */
const FAEDEN = 28;

/** In so viele Stücke ist jeder Faden unterteilt. */
const GLIEDER = 22;

/** So viele Teilchen sitzen auf den Fäden. */
const TEILCHEN = 340;

/** Der Radius im zusammengezogenen Zustand. */
const ENG = 0.34;

/**
 * Der Radius im ausgedehnten Zustand.
 *
 * Er endet bei 1.12 und nicht weiter draussen, und das ist keine
 * Feinheit, sondern die Grösse des Orb. Die bestehende Aura kreist
 * zwischen 0.85 und 1.40; wer darüber hinausgeht, macht den Orb beim
 * Ausatmen sichtbar grösser als beim Einatmen, und das Fenster schneidet
 * ihn ab.
 */
const WEIT = 1.12;

/** Die Farbe der Mitte – zwischen Kern- und Scheinfarbe gemischt. */
const VIOLETT = new THREE.Color(0x8a5cff);

/**
 * Ein einfacher, wiederholbarer Zufall.
 *
 * Math.random() wäre bei jedem Start ein anderer Kern. Das klingt nach
 * Abwechslung, ist aber beim Suchen von Fehlern lästig: Sieht etwas falsch
 * aus, will man genau dasselbe noch einmal sehen.
 */
function zufall(saat: number): () => number {
  let s = saat >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 4294967296;
  };
}

/**
 * Der atmende Nervenkern.
 *
 * Er dreht sich zusätzlich langsam um eine wandernde Achse. Eine feste
 * Achse liesse ihn um einen sichtbaren Pol kreisen und immer dieselbe
 * Seite zeigen – wie ein Karussell. So kommt nach und nach alles zum
 * Vorschein, ohne dass die Drehung selbst auffiele.
 */
export class NeuralCore {
  /** Die Gruppe, die alles enthält. */
  public readonly group: THREE.Group;

  private readonly faeden: THREE.LineSegments;
  private readonly teilchen: THREE.Points;
  private readonly haeute: THREE.Mesh[] = [];

  private readonly fadenMaterial: THREE.LineBasicMaterial;
  private readonly teilchenMaterial: THREE.PointsMaterial;
  private readonly hautMaterialien: THREE.MeshBasicMaterial[] = [];

  private readonly fadenOrte: Float32Array;
  private readonly fadenFarben: Float32Array;
  private readonly teilchenOrte: Float32Array;
  private readonly teilchenFarben: Float32Array;

  // Für jeden Faden: seine Grundrichtung und zwei Querrichtungen dazu.
  // Mit diesen dreien lässt sich die Windung um die eigene Achse legen,
  // ohne je eine Matrix zu brauchen.
  private readonly richtung: Float32Array;
  private readonly quer1: Float32Array;
  private readonly quer2: Float32Array;
  /** Wie oft sich ein Faden auf seinem Weg nach aussen windet. */
  private readonly windung: Float32Array;
  /** Wo seine Windung beginnt – sonst lägen alle gleich. */
  private readonly versatz: Float32Array;

  // Für jedes Teilchen: auf welchem Faden es sitzt und wo darauf.
  private readonly teilchenFaden: Int32Array;
  private readonly teilchenStelle: Float32Array;
  private readonly teilchenAbdrift: Float32Array;

  /** Die drei Farben: innen, Mitte, aussen. */
  private readonly innen = new THREE.Color(0x35e0ff);
  private readonly mitte = new THREE.Color(0x8a5cff);
  private readonly aussen = new THREE.Color(0xfff0e0);

  private readonly achse = new THREE.Vector3();

  private stimme = 0.0;
  private staerke = 1.0;
  private sichtbareTeilchen = TEILCHEN;
  /** Wo im Atemzug wir stehen (0 bis 1) – mitgeführt, nicht gerechnet. */
  private takt = 0.0;

  constructor() {
    this.group = new THREE.Group();

    const wuerfel = zufall(20260808);

    this.richtung = new Float32Array(FAEDEN * 3);
    this.quer1 = new Float32Array(FAEDEN * 3);
    this.quer2 = new Float32Array(FAEDEN * 3);
    this.windung = new Float32Array(FAEDEN);
    this.versatz = new Float32Array(FAEDEN);

    const gold = Math.PI * (3.0 - Math.sqrt(5.0));
    for (let f = 0; f < FAEDEN; f++) {
      // Die Richtungen liegen nach dem goldenen Winkel auf der Kugel.
      // Gleichmässige Winkelabstände ergäben sichtbare Reihen und zwei
      // kahle Pole; diese Verteilung hat keine bevorzugte Richtung.
      const y = 1.0 - (2.0 * f + 1.0) / FAEDEN;
      const r = Math.sqrt(Math.max(0.0, 1.0 - y * y));
      const phi = f * gold;
      const dx = Math.cos(phi) * r;
      const dy = y;
      const dz = Math.sin(phi) * r;

      this.richtung[f * 3 + 0] = dx;
      this.richtung[f * 3 + 1] = dy;
      this.richtung[f * 3 + 2] = dz;

      // Zwei Querrichtungen dazu. Der Hilfsvektor wird gewechselt, wenn er
      // fast parallel zur Richtung läge – sonst wäre das Kreuzprodukt
      // beinahe null und die Windung entartete zu einer Geraden.
      const hx = Math.abs(dy) < 0.9 ? 0.0 : 1.0;
      const hy = Math.abs(dy) < 0.9 ? 1.0 : 0.0;
      let ax = dy * 0.0 - dz * hy;
      let ay = dz * hx - dx * 0.0;
      let az = dx * hy - dy * hx;
      let laenge = Math.sqrt(ax * ax + ay * ay + az * az) || 1.0;
      ax /= laenge;
      ay /= laenge;
      az /= laenge;

      const bx = dy * az - dz * ay;
      const by = dz * ax - dx * az;
      const bz = dx * ay - dy * ax;

      this.quer1[f * 3 + 0] = ax;
      this.quer1[f * 3 + 1] = ay;
      this.quer1[f * 3 + 2] = az;
      this.quer2[f * 3 + 0] = bx;
      this.quer2[f * 3 + 1] = by;
      this.quer2[f * 3 + 2] = bz;

      // Ganze Windungen, damit ein Faden in sich geschlossen aussieht,
      // und je Faden verschieden viele, damit kein Muster entsteht.
      this.windung[f] = 1.0 + Math.floor(wuerfel() * 3.0);
      this.versatz[f] = wuerfel() * Math.PI * 2.0;
    }

    // --- Die Fäden ---------------------------------------------------------
    const fadenPunkte = FAEDEN * GLIEDER * 2;
    this.fadenOrte = new Float32Array(fadenPunkte * 3);
    this.fadenFarben = new Float32Array(fadenPunkte * 3);

    const fadenGeometrie = new THREE.BufferGeometry();
    fadenGeometrie.setAttribute("position", new THREE.BufferAttribute(this.fadenOrte, 3));
    fadenGeometrie.setAttribute("color", new THREE.BufferAttribute(this.fadenFarben, 3));

    this.fadenMaterial = new THREE.LineBasicMaterial({
      vertexColors: true,
      transparent: true,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    this.faeden = new THREE.LineSegments(fadenGeometrie, this.fadenMaterial);
    this.faeden.frustumCulled = false;
    this.group.add(this.faeden);

    // --- Die Häute ---------------------------------------------------------
    //
    // Zwei Schalen, sehr durchsichtig und additiv überlagert. Einzeln
    // sieht man keine; zusammen mit dem Bloom ergeben sie das weiche
    // Volumen, in dem sich das Licht verteilt. Ohne sie hingen die Fäden
    // im Nichts.
    for (let i = 0; i < 2; i++) {
      const material = new THREE.MeshBasicMaterial({
        color: 0x35e0ff,
        transparent: true,
        opacity: i === 0 ? 0.055 : 0.032,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
        side: THREE.DoubleSide,
      });
      const haut = new THREE.Mesh(new THREE.IcosahedronGeometry(1.0, 3), material);
      this.hautMaterialien.push(material);
      this.haeute.push(haut);
      this.group.add(haut);
    }

    // --- Die Teilchen ------------------------------------------------------
    this.teilchenOrte = new Float32Array(TEILCHEN * 3);
    this.teilchenFarben = new Float32Array(TEILCHEN * 3);
    this.teilchenFaden = new Int32Array(TEILCHEN);
    this.teilchenStelle = new Float32Array(TEILCHEN);
    this.teilchenAbdrift = new Float32Array(TEILCHEN);

    for (let i = 0; i < TEILCHEN; i++) {
      this.teilchenFaden[i] = Math.floor(wuerfel() * FAEDEN) % FAEDEN;
      // Nach aussen dichter: Die Wurzel verteilt gleichmässig über die
      // Länge statt gleichmässig über den Parameter. Ohne sie klumpten
      // alle Teilchen in der Mitte, wo die Fäden ohnehin zusammenlaufen.
      this.teilchenStelle[i] = Math.sqrt(wuerfel()) * 0.98 + 0.02;
      this.teilchenAbdrift[i] = wuerfel() * Math.PI * 2.0;
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
      size: 0.030,
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
  }

  /**
   * Übernimmt die Farben des Zustands.
   *
   * Die drei Farben des Kerns stammen nicht aus einer festen Palette,
   * sondern werden aus dem Zustand abgeleitet – sonst bliebe der Kern
   * blaugrün, wenn der Orb längst rot arbeitet, und die Farbe wäre keine
   * Auskunft mehr, sondern Schmuck.
   *
   * @param kern Die Grundfarbe. Im Ruhezustand blaugrün, beim Arbeiten rot.
   * @param schein Die helle Farbe – der warme Schein der Wellenkämme.
   * @param staerke Wie hell insgesamt.
   */
  public setColors(kern: THREE.Color, schein: THREE.Color, staerke: number): void {
    this.innen.copy(kern);
    // Die Mitte liegt zwischen der Zustandsfarbe und einem festen
    // Violett. Im Ruhezustand ergibt das den blauvioletten Übergang der
    // Vorlage, beim Arbeiten ein tiefes Purpurrot – in beiden Fällen ein
    // Verlauf und keine einzelne Farbe.
    this.mitte.copy(kern).lerp(VIOLETT, 0.55);
    this.aussen.copy(schein);
    this.staerke = staerke;

    for (const material of this.hautMaterialien) {
      material.color.copy(kern).lerp(schein, 0.3);
    }
  }

  /**
   * Meldet, wie laut gerade gesprochen wird.
   *
   * @param pegel Zwischen 0 und 1, bereits geglättet.
   */
  public setVoiceLevel(pegel: number): void {
    this.stimme = Math.max(0, Math.min(1, pegel));
  }

  /**
   * Atmet, lässt die Wellen laufen und dreht den Kern.
   *
   * @param elapsed Laufzeit in Sekunden.
   * @param delta Zeit seit dem letzten Bild.
   * @param tempo Geschwindigkeit des Zustands.
   */
  public update(elapsed: number, delta: number, tempo: number): void {
    // Der Takt wird MITGEFÜHRT, nicht aus der Laufzeit gerechnet.
    //
    // Das ist keine Umständlichkeit, sondern die Behebung eines echten
    // Fehlers. Aus `elapsed * tempo / ATEM_DAUER` folgt: Sobald sich das
    // Tempo ändert – und das tut es bei jedem Zustandswechsel, von 1.0 im
    // Ruhezustand auf 1.6 beim Denken –, springt der Takt schlagartig auf
    // einen ganz anderen Wert. Nach zwanzig Sekunden Laufzeit wäre das ein
    // Sprung über mehrere Atemzüge hinweg: Der Kern zuckt, sobald man ihn
    // anspricht.
    //
    // Aufaddiert kann das nicht passieren. Das Tempo ändert dann die
    // Geschwindigkeit des Atems, nicht seine Phase – und genau das ist
    // gemeint.
    this.takt = (this.takt + (delta * tempo) / ATEM_DAUER) % 1.0;
    const takt = this.takt;

    // Der Atem. Ein Kosinus und sonst nichts – das ist der Grund, warum
    // der Kreis wirklich geschlossen ist und nicht bloss annähernd.
    const atem = 0.5 - 0.5 * Math.cos(takt * Math.PI * 2.0);

    // Die Stimme stört den Atem, statt ihn zu ersetzen: Beim Sprechen
    // dehnt sich der Kern über das Ausatmen hinaus. Ein Atemzug, der beim
    // Sprechen unbeirrt weiterläuft, wirkt wie eine Anzeige.
    const weite = ENG + (WEIT - ENG) * atem + this.stimme * 0.22;

    // Zusammengezogen sind die Fäden eng gerollt, ausgedehnt strecken sie
    // sich. Das ist der Unterschied zwischen einem Ball, der grösser wird,
    // und etwas, das sich entfaltet.
    const rollung = 0.42 - 0.30 * atem;

    // Die Wellenfront. Ganzzahlig viele Wellen je Atemzug, sonst springt
    // das Bild an der Nahtstelle.
    const front = (takt * WELLEN_JE_ATEM) % 1.0;
    const breite = 0.26;

    this.faedenSetzen(takt, weite, rollung, front, breite, atem);
    this.teilchenSetzen(takt, weite, rollung, front, breite);
    this.haeuteSetzen(takt, atem, weite);
    // Einzig die Drehung bekommt die rohe Laufzeit: Sie ist absichtlich
    // nicht Teil der Schleife, weil eine Drehung ohne Naht ohnehin keine
    // sichtbare Naht hat.
    this.drehen(elapsed, delta, tempo);
  }

  // --- Innenleben --------------------------------------------------------------

  /** Rechnet den Ort eines Punktes auf einem Faden. */
  private ortAuf(
    f: number,
    u: number,
    takt: number,
    weite: number,
    rollung: number,
    ziel: { x: number; y: number; z: number }
  ): void {
    // Der Abstand vom Zentrum. Der Exponent unter eins drängt die Punkte
    // nach aussen, sodass die Fäden nicht in der Mitte verklumpen.
    const r = weite * Math.pow(u, 0.78);

    // Der Winkel der Windung. Die Zeit läuft hier mit, aber langsam und
    // im Takt des Atems – so kriecht die Windung, statt zu rotieren.
    const w =
      this.versatz[f] +
      u * this.windung[f] * Math.PI * 2.0 +
      Math.sin(takt * Math.PI * 2.0) * 0.6;

    // Die Auslenkung quer zur Richtung wächst mit dem Abstand: Am
    // Ansatzpunkt liegen alle Fäden zusammen, aussen fächern sie auf.
    const a = rollung * r * Math.sin(u * Math.PI);
    const s = Math.sin(w) * a;
    const c = Math.cos(w) * a;

    ziel.x = this.richtung[f * 3 + 0] * r + this.quer1[f * 3 + 0] * s + this.quer2[f * 3 + 0] * c;
    ziel.y = this.richtung[f * 3 + 1] * r + this.quer1[f * 3 + 1] * s + this.quer2[f * 3 + 1] * c;
    ziel.z = this.richtung[f * 3 + 2] * r + this.quer1[f * 3 + 2] * s + this.quer2[f * 3 + 2] * c;
  }

  /** Ein wiederverwendeter Behälter – kein neues Objekt je Punkt. */
  private readonly hier = { x: 0, y: 0, z: 0 };

  /** Legt die Fäden neu und färbt sie nach der Welle. */
  private faedenSetzen(
    takt: number,
    weite: number,
    rollung: number,
    front: number,
    breite: number,
    atem: number
  ): void {
    const grund = 0.10 + this.staerke * 0.05;
    const kamm = 0.75 + this.staerke * 0.30 + this.stimme * 0.85;
    // Ausgedehnt leuchtet er stärker als zusammengezogen – das Ausatmen
    // ist der helle Teil des Zyklus.
    const gesamt = 0.55 + 0.45 * atem;

    let punkt = 0;
    for (let f = 0; f < FAEDEN; f++) {
      for (let g = 0; g < GLIEDER; g++) {
        for (let ende = 0; ende < 2; ende++) {
          const u = (g + ende) / GLIEDER;
          this.ortAuf(f, u, takt, weite, rollung, this.hier);

          this.fadenOrte[punkt * 3 + 0] = this.hier.x;
          this.fadenOrte[punkt * 3 + 1] = this.hier.y;
          this.fadenOrte[punkt * 3 + 2] = this.hier.z;

          // Der Abstand zur Wellenfront, einmal herum gedacht: So reisst
          // die Welle nicht ab, wenn sie am äusseren Ende ankommt und
          // innen wieder beginnt.
          let ab = Math.abs(u - front);
          if (ab > 0.5) {
            ab = 1.0 - ab;
          }
          const naehe = Math.exp(-(ab * ab) / (breite * breite));
          const hell = (grund + kamm * naehe) * gesamt;

          // Die Farbe wandert über die Länge: innen die Kernfarbe, in der
          // Mitte violett, aussen der warme Schein. Auf dem Wellenkamm
          // zieht sie zusätzlich zum Hellen – Licht, das hell genug ist,
          // verliert seine Farbe, und das Auge erwartet das.
          let r: number;
          let g2: number;
          let b: number;
          if (u < 0.5) {
            const t = u * 2.0;
            r = this.innen.r + (this.mitte.r - this.innen.r) * t;
            g2 = this.innen.g + (this.mitte.g - this.innen.g) * t;
            b = this.innen.b + (this.mitte.b - this.innen.b) * t;
          } else {
            const t = (u - 0.5) * 2.0;
            r = this.mitte.r + (this.aussen.r - this.mitte.r) * t;
            g2 = this.mitte.g + (this.aussen.g - this.mitte.g) * t;
            b = this.mitte.b + (this.aussen.b - this.mitte.b) * t;
          }
          const weiss = naehe * 0.45;
          r += (this.aussen.r - r) * weiss;
          g2 += (this.aussen.g - g2) * weiss;
          b += (this.aussen.b - b) * weiss;

          this.fadenFarben[punkt * 3 + 0] = r * hell;
          this.fadenFarben[punkt * 3 + 1] = g2 * hell;
          this.fadenFarben[punkt * 3 + 2] = b * hell;
          punkt += 1;
        }
      }
    }

    (this.faeden.geometry.getAttribute("position") as THREE.BufferAttribute).needsUpdate =
      true;
    (this.faeden.geometry.getAttribute("color") as THREE.BufferAttribute).needsUpdate =
      true;
  }

  /** Setzt die Teilchen auf ihre Fäden und lässt sie mit der Welle aufleuchten. */
  private teilchenSetzen(
    takt: number,
    weite: number,
    rollung: number,
    front: number,
    breite: number
  ): void {
    const anzahl = this.sichtbareTeilchen;

    for (let i = 0; i < anzahl; i++) {
      const u = this.teilchenStelle[i];
      this.ortAuf(this.teilchenFaden[i], u, takt, weite, rollung, this.hier);

      // Ein kleines Eigenleben, damit sie nicht wie aufgefädelt wirken.
      // Es hängt am Atemtakt und bleibt damit Teil des geschlossenen
      // Kreises.
      const zittern =
        Math.sin(takt * Math.PI * 4.0 + this.teilchenAbdrift[i]) *
        (0.012 + this.stimme * 0.030);

      this.teilchenOrte[i * 3 + 0] = this.hier.x + zittern;
      this.teilchenOrte[i * 3 + 1] = this.hier.y - zittern;
      this.teilchenOrte[i * 3 + 2] = this.hier.z + zittern;

      let ab = Math.abs(u - front);
      if (ab > 0.5) {
        ab = 1.0 - ab;
      }
      const naehe = Math.exp(-(ab * ab) / (breite * breite));
      const hell = (0.22 + naehe * (1.15 + this.stimme * 0.7)) * (0.55 + this.staerke * 0.45);

      // Die Teilchen tragen die helle Farbe: Sie sind die Knoten des
      // Netzes, und was weitergereicht wird, soll heller sein als das,
      // worüber es läuft.
      const t = Math.min(1.0, u * 1.4);
      this.teilchenFarben[i * 3 + 0] =
        (this.mitte.r + (this.aussen.r - this.mitte.r) * t) * hell;
      this.teilchenFarben[i * 3 + 1] =
        (this.mitte.g + (this.aussen.g - this.mitte.g) * t) * hell;
      this.teilchenFarben[i * 3 + 2] =
        (this.mitte.b + (this.aussen.b - this.mitte.b) * t) * hell;
    }

    // Was nicht gezeichnet wird, wird schwarz – auf die Zahl der Punkte in
    // der Geometrie lässt sich nicht ohne Neubau einwirken.
    for (let i = anzahl; i < TEILCHEN; i++) {
      this.teilchenFarben[i * 3 + 0] = 0;
      this.teilchenFarben[i * 3 + 1] = 0;
      this.teilchenFarben[i * 3 + 2] = 0;
    }

    (
      this.teilchen.geometry.getAttribute("position") as THREE.BufferAttribute
    ).needsUpdate = true;
    (this.teilchen.geometry.getAttribute("color") as THREE.BufferAttribute).needsUpdate =
      true;
  }

  /** Lässt die beiden Häute versetzt zueinander atmen. */
  private haeuteSetzen(takt: number, atem: number, weite: number): void {
    for (let i = 0; i < this.haeute.length; i++) {
      // Versetzt, nicht gleich: Zwei Schalen, die synchron atmen, sehen
      // aus wie eine dicke. Der Versatz von einem Viertel Atemzug lässt
      // sie ineinander laufen, und daraus entsteht die Tiefe.
      const eigen =
        0.5 - 0.5 * Math.cos((takt - i * 0.25) * Math.PI * 2.0);
      const gross = weite * (0.62 + i * 0.28) * (0.88 + 0.24 * eigen);
      this.haeute[i].scale.setScalar(gross);

      // Sie drehen sich gegeneinander – so wandern die Aufhellungen ihrer
      // Überlagerung, statt an derselben Stelle zu stehen.
      const drall = takt * Math.PI * 2.0 * (i === 0 ? 0.5 : -0.35);
      this.haeute[i].rotation.set(drall * 0.6, drall, drall * 0.3);

      this.hautMaterialien[i].opacity =
        (i === 0 ? 0.055 : 0.032) * (0.6 + 0.4 * atem + this.stimme * 0.5);
    }
  }

  /** Die langsame Drehung um eine wandernde Achse. */
  private drehen(elapsed: number, delta: number, tempo: number): void {
    this.achse.set(
      Math.sin(elapsed * 0.17) + 0.4,
      Math.cos(elapsed * 0.13 + 0.7),
      Math.sin(elapsed * 0.21 + 2.2)
    );
    if (this.achse.lengthSq() <= 1e-6) {
      return;
    }
    this.achse.normalize();

    // Deutlich langsamer als beim Würfel: Der Kern soll atmen, und eine
    // schnelle Drehung überlagerte genau das, worauf es ankommt.
    const schwung = 0.16 * tempo * (1.0 + this.stimme * 1.2);
    this.faeden.rotateOnAxis(this.achse, delta * schwung);
    this.teilchen.quaternion.copy(this.faeden.quaternion);
  }

  /** Passt den Aufwand an die Leistungsstufe an. */
  public setQuality(level: number): void {
    this.sichtbareTeilchen =
      level >= 2 ? TEILCHEN : level >= 1 ? Math.floor(TEILCHEN * 0.5) : Math.floor(TEILCHEN * 0.2);

    // Die äussere Haut entfällt zuerst: Sie trägt am wenigsten Form und
    // kostet am meisten Füllrate, weil sie den grössten Teil des Bildes
    // bedeckt.
    if (this.haeute.length > 1) {
      this.haeute[1].visible = level >= 1;
    }
    if (this.haeute.length > 0) {
      this.haeute[0].visible = level >= 1;
    }
  }

  /** Gibt alle GPU-Ressourcen frei. */
  public dispose(): void {
    this.faeden.geometry.dispose();
    this.teilchen.geometry.dispose();
    this.fadenMaterial.dispose();
    this.teilchenMaterial.dispose();
    for (const haut of this.haeute) {
      haut.geometry.dispose();
    }
    for (const material of this.hautMaterialien) {
      material.dispose();
    }
  }
}
