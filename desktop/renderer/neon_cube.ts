/**
 * neon_cube.ts – der Würfel, der sich aus einem Sandsturm bildet.
 *
 * Zwei Vorbilder stecken darin, beide vom Benutzer gebracht:
 *
 *   1. „Imaginary Neon Cube" – ein Würfel, dessen Kanten leuchten. Ergänzt
 *      um den Wunsch, dass die Linien pulsieren und glühen wie die
 *      Synapsen eines Gehirns.
 *
 *   2. „Sand Whirlwind Intro" – ein Wirbel aus Sand, der sich sammelt,
 *      dreht und dabei allmählich eine Bühne bildet. Genau so entsteht der
 *      Würfel hier beim Start: aus Körnern, die von aussen hereinwirbeln
 *      und sich auf den Kanten niederlassen.
 *
 * ## Wie das Feuern entsteht
 *
 * Nicht dadurch, dass ganze Kanten heller und dunkler werden – das sähe
 * aus wie eine Lichterkette. Über jede Kante läuft stattdessen ein
 * Lichtpunkt, und was man sieht, ist seine Spur. Dafür ist jede Kante in
 * viele kurze Stücke unterteilt, und jedem Stück wird in jedem Bild eine
 * eigene Helligkeit gegeben: hell dort, wo das Signal gerade ist, dunkler
 * mit dem Abstand davon.
 *
 * Die acht Ecken sind die Knoten. Sie leuchten auf, wenn ein Signal
 * ankommt, und verglimmen langsam – dieses Nachglühen ist das, was den
 * Eindruck erzeugt, dass etwas weitergereicht wird und nicht bloss blinkt.
 *
 * ## Wie der Sturm entsteht
 *
 * Jedes Korn kennt von Anfang an seinen Platz: einen zufälligen Punkt auf
 * einer der zwölf Kanten. Was sich über die Aufbauzeit ändert, ist nur der
 * Weg dorthin – und der wird in Zylinderkoordinaten gerechnet, nicht
 * geradlinig. Das ist der ganze Trick: Wer zwischen zwei Punkten gerade
 * interpoliert, bekommt einen Sog; wer den Winkel getrennt vom Radius
 * führt und ihn weiterdrehen lässt, bekommt einen Wirbel.
 *
 * Die Drehung ist draussen schnell und wird langsamer, je näher ein Korn
 * seinem Platz kommt. So legt sich der Sturm, statt abgeschaltet zu
 * werden. Danach hören die Körner nicht auf: Sie zittern weiter und
 * driften langsam – ein Bild, das völlig stillsteht, wirkt eingefroren,
 * nicht fertig.
 *
 * ## Warum das ohne eigenen Shader auskommt
 *
 * Das ist die eigentliche Entscheidung an diesem Modul, und sie ist aus
 * Schaden klug geworden. Der Vorgänger war ein gerechneter Kristallhaufen –
 * schön gedacht, aber er erschien auf dem Rechner des Benutzers nie. Die
 * Ursache lag nicht im Aussehen, sondern in der Übersetzung: Was three.js
 * für eigene Shader zulässt, ist enger, als es beim Schreiben scheint, und
 * ein Shader, der nicht übersetzt wird, zeichnet nichts – ohne Fehlerbild,
 * einfach gar nichts.
 *
 * Hier wird deshalb nur benutzt, was in dieser Anwendung nachweislich
 * ankommt: gewöhnliche Geometrie, Standardmaterialien, Vertexfarben und
 * der bestehende Bloom-Effekt. Die Helligkeiten und die Sandbahnen rechnet
 * die CPU – bei rund tausend Punkten je Bild ist das nichts.
 *
 * Weniger kunstvoll, aber es kommt an. Ein Effekt, den niemand sieht, ist
 * kein Effekt.
 */

import * as THREE from "three";

/** Kantenlänge des Würfels. */
const KANTE = 0.60;

/**
 * In so viele Stücke wird jede Kante unterteilt.
 *
 * Das bestimmt, wie fein das Signal läuft. Bei zu wenigen Stücken springt
 * es sichtbar von Stück zu Stück; bei vielen wird es weich. Zwölf ist der
 * Punkt, an dem es flüssig aussieht, ohne dass die Zahl der Punkte
 * nennenswert ins Gewicht fiele (12 Kanten × 12 Stücke × 2 Enden = 288).
 */
const STUECKE = 12;

/** Wie breit die Spur eines Signals ist (Anteil einer Kantenlänge). */
const SPUR = 0.22;

/** So viele Sandkörner bilden den Wirbel. */
const KOERNER = 720;

/**
 * Wie lange der Aufbau dauert, in Sekunden.
 *
 * Kürzer wirkt wie ein Schnitt, länger wie eine Wartezeit. Bei knapp drei
 * Sekunden sieht man den Wirbel zweimal ganz herumlaufen, bevor er sich
 * legt – lang genug, dass es eine Bewegung ist, kurz genug, dass niemand
 * darauf wartet.
 */
const AUFBAU_DAUER = 2.8;

/** Die acht Ecken des Würfels. */
const ECKEN: ReadonlyArray<readonly [number, number, number]> = [
  [-1, -1, -1], [+1, -1, -1], [+1, +1, -1], [-1, +1, -1],
  [-1, -1, +1], [+1, -1, +1], [+1, +1, +1], [-1, +1, +1],
];

/** Die zwölf Kanten als Paare von Eckennummern. */
const KANTEN: ReadonlyArray<readonly [number, number]> = [
  [0, 1], [1, 2], [2, 3], [3, 0],
  [4, 5], [5, 6], [6, 7], [7, 4],
  [0, 4], [1, 5], [2, 6], [3, 7],
];

/**
 * Ein einfacher, wiederholbarer Zufall.
 *
 * Math.random() wäre bei jedem Start ein anderer Sturm. Das klingt nach
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
 * Ein Würfel, dessen Kanten feuern – gebildet aus einem Sandwirbel.
 *
 * Er taumelt um eine Achse, die selbst wandert: Eine feste Achse liesse ihn
 * um einen sichtbaren Pol kreisen und immer wieder dieselben vier Seiten
 * zeigen – wie ein Karussell. So kommen nacheinander alle sechs Flächen und
 * alle acht Ecken zum Vorschein.
 */
export class NeonCube {
  /** Die Gruppe, die alles enthält. */
  public readonly group: THREE.Group;

  private readonly linien: THREE.LineSegments;
  private readonly knoten: THREE.Points;
  private readonly sturm: THREE.Points;

  private readonly linienMaterial: THREE.LineBasicMaterial;
  private readonly knotenMaterial: THREE.PointsMaterial;
  private readonly sturmMaterial: THREE.PointsMaterial;

  private readonly linienFarben: Float32Array;
  private readonly knotenFarben: Float32Array;

  /** Die Positionen der Körner – jedes Bild neu gerechnet. */
  private readonly sandOrte: Float32Array;
  private readonly sandFarben: Float32Array;

  // Für jedes Korn: wo es herkommt, wo es hinsoll, wie es sich dreht.
  private readonly startRadius: Float32Array;
  private readonly startWinkel: Float32Array;
  private readonly startHoehe: Float32Array;
  private readonly zielRadius: Float32Array;
  private readonly zielWinkel: Float32Array;
  private readonly zielHoehe: Float32Array;
  private readonly drehung: Float32Array;
  /** Wann ein Korn losfliegt (0 bis ca. 0.35 des Aufbaus). */
  private readonly verzug: Float32Array;

  /** Wie weit ein Signal auf seiner Kante schon ist (0 bis 1). */
  private readonly signale: Float32Array;
  /** Wie schnell es läuft – je Kante verschieden. */
  private readonly tempi: Float32Array;
  /** Das Nachglühen der acht Ecken. */
  private readonly nachglut: Float32Array;

  /** Die Grundfarbe der Kanten, je Bild vom Zustand gesetzt. */
  private readonly farbe = new THREE.Color(0xe8c68a);
  /** Die Farbe der Sandkörner – heller und blasser als die Kanten. */
  private readonly sandfarbe = new THREE.Color(0xf3e0b8);
  /** Wiederverwendete Achse – kein neuer Vektor je Bild. */
  private readonly achse = new THREE.Vector3();

  private stimme = 0.0;
  private staerke = 1.0;

  /** Der Fortschritt des Aufbaus in Sekunden. */
  private aufbau = 0.0;
  /** Wie viele Körner überhaupt gezeichnet werden (Leistungsstufe). */
  private sichtbareKoerner = KOERNER;

  constructor() {
    this.group = new THREE.Group();

    const halb = KANTE * 0.5;
    const punkte: number[] = [];

    // Jede Kante in Stücke zerlegen. Jedes Stück ist eine eigene Linie mit
    // zwei Enden – nur so lässt sich die Helligkeit ENTLANG der Kante
    // verändern und nicht bloss für die Kante als Ganzes.
    for (const [a, b] of KANTEN) {
      const von = ECKEN[a];
      const bis = ECKEN[b];
      for (let i = 0; i < STUECKE; i++) {
        const u0 = i / STUECKE;
        const u1 = (i + 1) / STUECKE;
        for (const u of [u0, u1]) {
          punkte.push(
            (von[0] + (bis[0] - von[0]) * u) * halb,
            (von[1] + (bis[1] - von[1]) * u) * halb,
            (von[2] + (bis[2] - von[2]) * u) * halb
          );
        }
      }
    }

    const geometrie = new THREE.BufferGeometry();
    geometrie.setAttribute("position", new THREE.Float32BufferAttribute(punkte, 3));
    this.linienFarben = new Float32Array((punkte.length / 3) * 3);
    geometrie.setAttribute("color", new THREE.BufferAttribute(this.linienFarben, 3));

    this.linienMaterial = new THREE.LineBasicMaterial({
      vertexColors: true,
      transparent: true,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    this.linien = new THREE.LineSegments(geometrie, this.linienMaterial);
    this.group.add(this.linien);

    // --- Die Knoten --------------------------------------------------------
    const eckpunkte: number[] = [];
    for (const [x, y, z] of ECKEN) {
      eckpunkte.push(x * halb, y * halb, z * halb);
    }
    const knotenGeometrie = new THREE.BufferGeometry();
    knotenGeometrie.setAttribute(
      "position",
      new THREE.Float32BufferAttribute(eckpunkte, 3)
    );
    this.knotenFarben = new Float32Array(ECKEN.length * 3);
    knotenGeometrie.setAttribute(
      "color",
      new THREE.BufferAttribute(this.knotenFarben, 3)
    );

    this.knotenMaterial = new THREE.PointsMaterial({
      size: 0.075,
      vertexColors: true,
      transparent: true,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
      sizeAttenuation: true,
    });
    this.knoten = new THREE.Points(knotenGeometrie, this.knotenMaterial);
    this.group.add(this.knoten);

    // --- Der Sandwirbel ----------------------------------------------------
    this.sandOrte = new Float32Array(KOERNER * 3);
    this.sandFarben = new Float32Array(KOERNER * 3);
    this.startRadius = new Float32Array(KOERNER);
    this.startWinkel = new Float32Array(KOERNER);
    this.startHoehe = new Float32Array(KOERNER);
    this.zielRadius = new Float32Array(KOERNER);
    this.zielWinkel = new Float32Array(KOERNER);
    this.zielHoehe = new Float32Array(KOERNER);
    this.drehung = new Float32Array(KOERNER);
    this.verzug = new Float32Array(KOERNER);

    const wuerfel = zufall(20260808);
    for (let i = 0; i < KOERNER; i++) {
      // Das Ziel: ein zufälliger Punkt auf einer zufälligen Kante. Nicht
      // exakt darauf, sondern mit einem Hauch Streuung – ein Sandsaum, der
      // die Linie umgibt, statt sie zu verdecken.
      const kante = KANTEN[Math.floor(wuerfel() * KANTEN.length) % KANTEN.length];
      const von = ECKEN[kante[0]];
      const bis = ECKEN[kante[1]];
      const u = wuerfel();
      const zx = (von[0] + (bis[0] - von[0]) * u) * halb + (wuerfel() - 0.5) * 0.05;
      const zy = (von[1] + (bis[1] - von[1]) * u) * halb + (wuerfel() - 0.5) * 0.05;
      const zz = (von[2] + (bis[2] - von[2]) * u) * halb + (wuerfel() - 0.5) * 0.05;

      this.zielRadius[i] = Math.sqrt(zx * zx + zz * zz);
      this.zielWinkel[i] = Math.atan2(zz, zx);
      this.zielHoehe[i] = zy;

      // Der Start: draussen, ringsum verteilt, flach gestreut. Flach, weil
      // ein Sandsturm über dem Boden liegt und nicht als Kugel um etwas
      // herum – die Höhe zieht sich erst beim Einwirbeln auseinander.
      //
      // Der Radius endet bei 1.45 und nicht weiter draussen, und das ist
      // keine Feinheit, sondern die Grösse des Orb. Die bestehende Aura
      // kreist zwischen 0.85 und 1.40; wer den Sturm darüber hinaus wirft,
      // macht den Orb beim Start doppelt so gross wie danach – und das
      // Fenster schneidet ihn ab. Der Sturm gehört dorthin, wo ohnehin
      // schon etwas ist.
      this.startRadius[i] = 0.85 + wuerfel() * 0.60;
      this.startWinkel[i] = wuerfel() * Math.PI * 2.0;
      this.startHoehe[i] = (wuerfel() - 0.5) * 0.55;

      // Aussen dreht der Wirbel schneller als innen – so sieht man die
      // Schraube. Drehten alle gleich schnell, wäre es ein starrer Ring.
      this.drehung[i] = (1.5 + wuerfel() * 1.6) * (wuerfel() < 0.12 ? -0.45 : 1.0);

      // Nicht alle brechen gleichzeitig auf: Der Sturm baut sich auf.
      this.verzug[i] = wuerfel() * 0.35;
    }

    const sturmGeometrie = new THREE.BufferGeometry();
    sturmGeometrie.setAttribute("position", new THREE.BufferAttribute(this.sandOrte, 3));
    sturmGeometrie.setAttribute("color", new THREE.BufferAttribute(this.sandFarben, 3));

    this.sturmMaterial = new THREE.PointsMaterial({
      size: 0.022,
      vertexColors: true,
      transparent: true,
      opacity: 0.95,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
      sizeAttenuation: true,
    });
    this.sturm = new THREE.Points(sturmGeometrie, this.sturmMaterial);
    this.sturm.frustumCulled = false;
    this.group.add(this.sturm);

    // Jede Kante bekommt ein eigenes Tempo und einen eigenen Startpunkt.
    // Liefen alle gleich, pulsierte der Würfel im Takt wie ein Herz; hier
    // soll es wimmeln wie in einem Nervennetz.
    this.signale = new Float32Array(KANTEN.length);
    this.tempi = new Float32Array(KANTEN.length);
    for (let i = 0; i < KANTEN.length; i++) {
      this.signale[i] = (i * 0.37) % 1.0;
      this.tempi[i] = 0.35 + ((i * 7) % 11) / 11 * 0.55;
    }
    this.nachglut = new Float32Array(ECKEN.length);
  }

  /**
   * Übernimmt die Farben des Zustands.
   *
   * @param kern Die Grundfarbe (sandfarben im Ruhezustand, rot beim
   *   Arbeiten).
   * @param schein Die helle Farbe der Signale.
   * @param staerke Wie hell insgesamt.
   */
  public setColors(kern: THREE.Color, schein: THREE.Color, staerke: number): void {
    // Zwischen beiden: Die Kante trägt die Zustandsfarbe, das Signal darauf
    // ist heller. Nähme man nur die helle, wäre die Zustandsfarbe nicht
    // mehr zu erkennen – und die ist eine Auskunft, kein Schmuck.
    this.farbe.copy(kern).lerp(schein, 0.45);
    // Der Sand liegt noch näher an der hellen Farbe: Körner streuen Licht,
    // sie leuchten nicht selbst.
    this.sandfarbe.copy(kern).lerp(schein, 0.75);
    this.staerke = staerke;
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
   * Lässt den Sandsturm noch einmal von vorn beginnen.
   *
   * Gedacht für den Fall, dass der Orb neu erscheint, ohne dass die Szene
   * neu gebaut wird – dann soll er sich wieder aufbauen und nicht einfach
   * dastehen.
   */
  public restartIntro(): void {
    this.aufbau = 0.0;
  }

  /**
   * Bewegt den Würfel, wirbelt den Sand und lässt die Signale laufen.
   *
   * @param elapsed Laufzeit in Sekunden.
   * @param delta Zeit seit dem letzten Bild.
   * @param tempo Geschwindigkeit des Zustands.
   */
  public update(elapsed: number, delta: number, tempo: number): void {
    this.aufbau = Math.min(AUFBAU_DAUER + 1.0, this.aufbau + delta);
    const fortschritt = Math.min(1.0, this.aufbau / AUFBAU_DAUER);

    this.taumeln(elapsed, delta, tempo, fortschritt);
    this.feuern(delta, tempo, fortschritt);
    this.wirbeln(elapsed, fortschritt);
  }

  // --- Innenleben --------------------------------------------------------------

  /** Die Drehung um eine wandernde Achse. */
  private taumeln(
    elapsed: number,
    delta: number,
    tempo: number,
    fortschritt: number
  ): void {
    this.achse.set(
      Math.sin(elapsed * 0.23) + 0.4,
      Math.cos(elapsed * 0.19 + 0.7),
      Math.sin(elapsed * 0.31 + 2.2)
    );
    if (this.achse.lengthSq() <= 1e-6) {
      return;
    }
    this.achse.normalize();

    // Beim Sprechen dreht er schneller: Die Stimme treibt ihn an. Während
    // des Aufbaus dreht er noch kaum – erst wenn der Sand liegt, nimmt das
    // Taumeln zu. Sonst kämpften zwei Bewegungen gegeneinander und man
    // sähe weder den Wirbel noch den Würfel.
    const schwung =
      0.45 * tempo * (1.0 + this.stimme * 1.6) * (0.08 + 0.92 * fortschritt);
    this.linien.rotateOnAxis(this.achse, delta * schwung);
    this.knoten.quaternion.copy(this.linien.quaternion);
    this.sturm.quaternion.copy(this.linien.quaternion);

    // Und dehnt sich mit ihr – ungleichmässig in den drei Richtungen,
    // sonst sähe es aus wie Atmen statt wie Sprechen.
    const s = this.stimme;
    this.linien.scale.set(
      1.0 + Math.sin(elapsed * 0.9) * 0.04 + s * 0.26,
      1.0 + Math.sin(elapsed * 1.3 + 2.0) * 0.04 + s * 0.15,
      1.0 + Math.sin(elapsed * 1.1 + 4.0) * 0.04 + s * 0.21
    );
    this.knoten.scale.copy(this.linien.scale);
    this.sturm.scale.copy(this.linien.scale);
  }

  /** Lässt die Signale über die Kanten laufen und die Knoten aufleuchten. */
  private feuern(delta: number, tempo: number, fortschritt: number): void {
    // Beim Sprechen feuert das Netz schneller. Das ist der Grund, warum
    // dieser Würfel überhaupt mit der Stimme verbunden ist: Ein Bild, das
    // sich synchron zum Klang bewegt, ordnet das Auge derselben Ursache zu.
    const schub = tempo * (0.55 + this.stimme * 1.9);

    // Solange der Sand fliegt, sind die Kanten kaum da. Sie treten hervor,
    // wie sich die Körner niederlassen – das ist es, was den Aufbau zum
    // Entstehen macht statt zum Einblenden. Quadratisch, damit die Linien
    // erst spät kommen und der Wirbel die erste Sekunde für sich hat.
    const vorhang = fortschritt * fortschritt;

    const grund = (0.10 + this.staerke * 0.06) * vorhang;
    const spitze = (0.85 + this.staerke * 0.35 + this.stimme * 0.9) * vorhang;

    // Das Nachglühen der Knoten verklingt – langsam genug, dass man das
    // Weiterreichen sieht, schnell genug, dass nicht alles gleichzeitig
    // leuchtet.
    for (let k = 0; k < this.nachglut.length; k++) {
      this.nachglut[k] = Math.max(0, this.nachglut[k] - delta * 2.2);
    }

    let punkt = 0;
    for (let e = 0; e < KANTEN.length; e++) {
      let stand = this.signale[e] + delta * this.tempi[e] * schub;
      if (stand >= 1.0) {
        stand -= Math.floor(stand);
        // Angekommen: Die Ecke am Ende der Kante leuchtet auf.
        this.nachglut[KANTEN[e][1]] = 1.0;
      }
      this.signale[e] = stand;

      for (let i = 0; i < STUECKE; i++) {
        for (let ende = 0; ende < 2; ende++) {
          const u = (i + ende) / STUECKE;

          // Abstand zum Signal, einmal um die Kante herum gedacht: So
          // reisst die Spur nicht ab, wenn das Signal gerade überläuft.
          let abstand = Math.abs(u - stand);
          if (abstand > 0.5) {
            abstand = 1.0 - abstand;
          }
          const naehe = Math.exp(-(abstand * abstand) / (SPUR * SPUR));
          const hell = grund + spitze * naehe;

          this.linienFarben[punkt * 3 + 0] = this.farbe.r * hell;
          this.linienFarben[punkt * 3 + 1] = this.farbe.g * hell;
          this.linienFarben[punkt * 3 + 2] = this.farbe.b * hell;
          punkt += 1;
        }
      }
    }
    (this.linien.geometry.getAttribute("color") as THREE.BufferAttribute).needsUpdate =
      true;

    for (let k = 0; k < ECKEN.length; k++) {
      const hell = (0.18 + this.nachglut[k] * (1.1 + this.stimme * 0.8)) * vorhang;
      this.knotenFarben[k * 3 + 0] = this.farbe.r * hell;
      this.knotenFarben[k * 3 + 1] = this.farbe.g * hell;
      this.knotenFarben[k * 3 + 2] = this.farbe.b * hell;
    }
    (this.knoten.geometry.getAttribute("color") as THREE.BufferAttribute).needsUpdate =
      true;
  }

  /**
   * Wirbelt die Sandkörner – erst herein, dann als lebendiger Saum.
   *
   * Gerechnet wird in Zylinderkoordinaten: Radius, Winkel, Höhe getrennt.
   * Das ist der ganze Unterschied zwischen Sog und Wirbel – zwischen zwei
   * Punkten gerade zu interpolieren ergäbe einen Trichter aus Strichen.
   */
  private wirbeln(elapsed: number, fortschritt: number): void {
    const anzahl = this.sichtbareKoerner;

    for (let i = 0; i < anzahl; i++) {
      // Der eigene Fortschritt des Korns – wer später aufbricht, ist
      // später da. Das macht aus einer Front einen Sturm.
      const eigen = weich((fortschritt - this.verzug[i]) / (1.0 - this.verzug[i]));

      // Der Winkel wird nicht interpoliert, sondern weitergedreht: Aussen
      // schnell, innen langsam. So legt sich der Wirbel, statt anzuhalten.
      const tempo = 0.22 + (1.0 - eigen) * 1.35;
      const winkel =
        this.startWinkel[i] +
        (this.zielWinkel[i] - this.startWinkel[i]) * eigen +
        this.drehung[i] * elapsed * tempo;

      // Radius und Höhe wandern zum Ziel. Der Bauch in der Mitte
      // (`sin`-Term) lässt die Körner nicht schnurgerade hereinkommen,
      // sondern eine Schleife nach aussen ziehen – der Sturm holt aus.
      const bauch = Math.sin(eigen * Math.PI) * 0.10;
      const radius =
        this.startRadius[i] + (this.zielRadius[i] - this.startRadius[i]) * eigen + bauch;
      const hoehe =
        this.startHoehe[i] +
        (this.zielHoehe[i] - this.startHoehe[i]) * eigen +
        Math.sin(elapsed * 1.7 + i * 0.7) * 0.05 * (1.0 - eigen);

      // Und wenn alles liegt, hört es nicht auf: ein feines Zittern, das
      // mit der Stimme zunimmt. Ein Bild, das völlig stillsteht, wirkt
      // eingefroren, nicht fertig.
      const leben = eigen * (0.010 + this.stimme * 0.055);
      const zx = Math.sin(elapsed * 3.1 + i * 1.3) * leben;
      const zy = Math.sin(elapsed * 2.7 + i * 2.1) * leben;
      const zz = Math.sin(elapsed * 3.5 + i * 0.9) * leben;

      this.sandOrte[i * 3 + 0] = Math.cos(winkel) * radius + zx;
      this.sandOrte[i * 3 + 1] = hoehe + zy;
      this.sandOrte[i * 3 + 2] = Math.sin(winkel) * radius + zz;

      // Fliegender Sand ist heller als liegender: Er fängt mehr Licht und
      // markiert die Bewegung. Ganz verschwinden darf er nicht, sonst
      // fehlte dem Würfel danach der Saum, aus dem er gekommen ist.
      const hell = (0.28 + (1.0 - eigen) * 0.85) * (0.55 + this.staerke * 0.45);
      this.sandFarben[i * 3 + 0] = this.sandfarbe.r * hell;
      this.sandFarben[i * 3 + 1] = this.sandfarbe.g * hell;
      this.sandFarben[i * 3 + 2] = this.sandfarbe.b * hell;
    }

    // Was nicht gezeichnet wird, wird weit weggeschoben. Auf die Zahl der
    // Punkte in der Geometrie lässt sich nicht ohne Neubau einwirken.
    for (let i = anzahl; i < KOERNER; i++) {
      this.sandFarben[i * 3 + 0] = 0;
      this.sandFarben[i * 3 + 1] = 0;
      this.sandFarben[i * 3 + 2] = 0;
    }

    (this.sturm.geometry.getAttribute("position") as THREE.BufferAttribute).needsUpdate =
      true;
    (this.sturm.geometry.getAttribute("color") as THREE.BufferAttribute).needsUpdate =
      true;
  }

  /** Passt die Sichtbarkeit an die Leistungsstufe an. */
  public setQuality(level: number): void {
    // Der Sand kostet am meisten und wird zuerst gekürzt – aber nie ganz
    // abgeschaltet, denn er ist der Aufbau. Ein Würfel, der einfach da
    // ist, wäre ein anderer Effekt, kein sparsamerer.
    this.sichtbareKoerner =
      level >= 2 ? KOERNER : level >= 1 ? Math.floor(KOERNER * 0.5) : Math.floor(KOERNER * 0.22);

    // Die Knoten entfallen zuletzt: Sie tragen zur Tiefe bei, aber der
    // Würfel bleibt ohne sie erkennbar.
    this.knoten.visible = level >= 1;
  }

  /** Gibt alle GPU-Ressourcen frei. */
  public dispose(): void {
    this.linien.geometry.dispose();
    this.knoten.geometry.dispose();
    this.sturm.geometry.dispose();
    this.linienMaterial.dispose();
    this.knotenMaterial.dispose();
    this.sturmMaterial.dispose();
  }
}
