/**
 * orb.ts – Der Orb als dreidimensionales Energieobjekt.
 *
 * Im Inneren steckt ein Kristallhaufen: zwei Dutzend Knollen und Facetten,
 * die ineinanderfliessen, atmen und ihre Farbe langsam wandern lassen.
 * Vorbild ist eine Animation, die der Benutzer mitgebracht hat.
 *
 * Der Haufen ist keine Geometrie, sondern eine Formel – er wird für jeden
 * Bildpunkt ausgerechnet (siehe shaders/cluster.glsl). Das ist keine
 * Spielerei: Zwei Dutzend Körper, die verschmelzen und dabei ihre Grösse
 * ändern, wären als Dreiecksnetz in jedem Bild neu zu bauen.
 *
 * Alles bewegt sich gegeneinander, und das ist der ganze Trick des
 * räumlichen Eindrucks: Der Haufen taumelt um eine wandernde Achse, die
 * Kugel darum dreht sich um eine andere, die Aura läuft beiden entgegen.
 * Bewegungen, die nie im selben Takt laufen, lassen sich nicht mehr als
 * flaches Bild lesen.
 *
 * Die Bestandteile:
 *
 * - **Haufen**: der Kern, gerechnet statt gebaut
 * - **Smoke**: ein volumetrischer Nebel, der ihn umgibt
 * - **Shell**: eine leuchtende Hülle mit Fresnel-Effekt – die Kugel
 * - **Aura**: eine größere, weichere Außenhülle
 * - **Partikel**: eine umkreisende Partikelwolke
 * - **Licht**: eine Punktlichtquelle im Inneren
 *
 * Dieses Modul ist ausschließlich für den Aufbau und die Aktualisierung
 * zuständig. Zustände, Animation und Interaktion liegen in eigenen Modulen.
 */
import * as THREE from "three";

import {
  createAuraMaterial,
  createClusterMaterial,
  createCoreMaterial,
  createParticleMaterial,
  createShellMaterial,
  createSmokeMaterial,
} from "./effects";
import { ZweiPunkte, type ZweiPunkteOptionen } from "./zwei_punkte";
import type { StateAppearance } from "./states";

/**
 * Radius der Trägerhülle des Kristallhaufens.
 *
 * Sie wird nie selbst sichtbar – sie liefert nur die Fläche, auf der der
 * Shader rechnet. Sie muss den Haufen sicher umschliessen: Seine Körper
 * reichen bis etwa 0.60 vom Mittelpunkt, beim Sprechen dehnt er sich um
 * ein Fünftel – zusammen also knapp 0.89. Ragte er über die Hülle hinaus,
 * würde er am Rand abgeschnitten; wäre die Hülle grösser als die Aura
 * (1.05), läge er beim Zeichnen vor ihr statt in ihr.
 */
const CLUSTER_HULL = 0.90;

/**
 * Wie weit der Haufen höchstens aus der Mitte wandert.
 *
 * Deutlich weniger als beim früheren Würfel: Der Haufen füllt die Kugel
 * fast aus. Wanderte er so weit wie ein kleiner Körper, stiesse er durch
 * die Hülle. Es geht hier nicht mehr um ein Umhertreiben, sondern nur noch
 * darum, dass er nie ganz stillsteht.
 */
const CLUSTER_DRIFT = 0.06;

/** Konfiguration des Orb-Aufbaus. */
export interface OrbOptions {
  /** Anzahl der Partikel in der Aura. */
  particleCount: number;
  /** Ob Partikel überhaupt erzeugt werden. */
  particlesEnabled: boolean;
  /** Geometrie-Auflösung des Kerns (wird bei schwacher Leistung gesenkt). */
  detail: number;
  /** Ob der gerechnete Kristallhaufen benutzt wird (siehe Konstruktor). */
  clusterEnabled: boolean;
  /** Die vom Benutzer veränderbaren Animationswerte (aus orb.animation). */
  animation?: ZweiPunkteOptionen;
}

/**
 * Baut den Orb auf und hält alle seine Bestandteile zusammen.
 */
export class Orb {
  /** Die Gruppe, die alle Bestandteile des Orb enthält. */
  public readonly group: THREE.Group;

  /** Der Kristallhaufen – der Kern, um den sich alles dreht. */
  private readonly cubeGroup: THREE.Group;
  /** Nebel, Hülle und Aura – das, was sich um den Haufen dreht. */
  private readonly sphereGroup: THREE.Group;

  private core: THREE.Mesh;
  /**
   * Ob Hülle, Aura und Nebel überhaupt gezeichnet werden.
   *
   * Beim Nervengeflecht nicht (siehe Konstruktor). Die Leistungsstufe
   * darf sie nicht wieder einschalten – sie regelt den AUFWAND und nicht,
   * was zum Bild gehört.
   */
  private gehaeuseSichtbar = true;

  /**
   * Das Nervengeflecht – gesetzt, wenn kein gerechneter Kern läuft.
   *
   * Es heisst weiterhin `neon`, weil an diesem Feld ein Dutzend Stellen
   * hängen und ein reiner Umbenennungs-Durchgang nur Gelegenheit gäbe,
   * eine davon zu vergessen.
   */
  private neon: ZweiPunkte | null = null;

  /** Die Farben des Zustands, bevor die Verfärbung darauf liegt. */
  private readonly basisKern = new THREE.Color(0x4aa3ff);
  private readonly basisSchein = new THREE.Color(0xbfe4ff);
  private readonly basisTeilchen = new THREE.Color(0xbfe4ff);
  /** Wiederverwendet – kein neuer Farbwert je Bild. */
  private readonly farbhilfe = new THREE.Color();
  private readonly hslHilfe = { h: 0, s: 0, l: 0 };
  private smoke: THREE.Mesh;
  private shell: THREE.Mesh;
  private aura: THREE.Mesh;
  private particles: THREE.Points | null = null;
  private light: THREE.PointLight;

  private coreMaterial: THREE.ShaderMaterial;
  private smokeMaterial: THREE.ShaderMaterial;
  private shellMaterial: THREE.ShaderMaterial;
  private auraMaterial: THREE.ShaderMaterial;
  private particleMaterial: THREE.ShaderMaterial | null = null;

  /**
   * Die Achse, um die sich die Kugel gerade dreht.
   *
   * Sie wird in jedem Bild neu berechnet und dabei wiederverwendet – ein
   * neuer Vektor pro Bild wären bei 60 Bildern je Sekunde 60 Objekte, die
   * die Speicherbereinigung wieder einsammeln müsste.
   */
  private readonly rotationAxis = new THREE.Vector3();
  /** Die Achse, um die der Würfel gerade taumelt. */
  private readonly tumbleAxis = new THREE.Vector3();

  /**
   * Wie laut gerade gesprochen wird (0 bis 1), geglättet.
   *
   * Roh gemeldete Pegel springen von Bild zu Bild; unmittelbar auf sie
   * abgebildet würde der Würfel zucken statt mitzuschwingen. Geglättet
   * wird deshalb ungleich: schnell hinauf, langsam hinunter – wie bei
   * einem Aussteuerungszeiger. Ein Wortanfang soll sofort zu sehen sein,
   * eine Sprechpause aber nicht sofort in sich zusammenfallen.
   */
  private voiceLevel = 0.0;
  private voiceTarget = 0.0;

  private baseScale = 1.0;
  private options: OrbOptions;

  /**
   * @param options Aufbauparameter.
   * @param pixelRatio Geräte-Pixelverhältnis (für die Partikelgröße).
   */
  constructor(options: OrbOptions, pixelRatio: number) {
    this.options = options;
    this.group = new THREE.Group();
    this.cubeGroup = new THREE.Group();
    this.sphereGroup = new THREE.Group();
    this.group.add(this.cubeGroup);
    this.group.add(this.sphereGroup);

    // --- Der Kristallhaufen ------------------------------------------------
    //
    // Der Kern ist keine Geometrie mehr, sondern eine Formel: ein Haufen
    // aus zwei Dutzend Knollen und Facetten, der für jeden Bildpunkt
    // ausgerechnet wird (siehe cluster.glsl). Als Träger dient eine
    // schlichte Kugel – sie wird nie selbst sichtbar, sie liefert nur die
    // Fläche, auf der gerechnet wird.
    //
    // Deshalb ist sie etwas grösser als der Haufen: Ragte er über sie
    // hinaus, würde er am Rand abgeschnitten.
    // Der Rückweg, falls der Haufen nicht zustande kommt.
    //
    // Er wird für jeden Bildpunkt gerechnet, und je nach Grafiktreiber
    // kann die Übersetzung eines solchen Shaders scheitern – dann wird
    // nichts gezeichnet, und der Orb hätte gar keinen Kern mehr. Mit
    // `orb.cluster: false` in der config.yaml kommt der schlichte,
    // genügsame Kern zurück, der überall läuft.
    if (options.clusterEnabled) {
      this.coreMaterial = createClusterMaterial();
      this.core = new THREE.Mesh(
        new THREE.IcosahedronGeometry(CLUSTER_HULL, 3),
        this.coreMaterial
      );
      this.cubeGroup.add(this.core);
    } else {
      // Die zwei Punkte: rot und blau, einander umkreisend, beim Denken
      // und Sprechen zu einem farbmischenden Nebel verschmelzend – vom
      // Benutzer in der Vorschau abgenommen ("das ist perfekt").
      // Gewöhnliche Punkte, kein eigener Shader: Ein gerechneter Kern
      // erschien auf dem Rechner des Benutzers nie, weil der Shader nicht
      // übersetzt wurde. Was hier steht, benutzt nur, was nachweislich
      // ankommt.
      //
      // Der schlichte Kugelkern bleibt als Material bestehen, damit die
      // Farbzuweisungen unten eine Anlaufstelle haben; sichtbar ist er
      // nicht.
      this.coreMaterial = createCoreMaterial();
      this.core = new THREE.Mesh(
        new THREE.IcosahedronGeometry(0.001, 0),
        this.coreMaterial
      );
      this.core.visible = false;
      this.cubeGroup.add(this.core);

      this.neon = new ZweiPunkte(options.animation);
      this.cubeGroup.add(this.neon.group);

      // Hülle, Aura und Nebel bleiben aus – und das ist der Kern der
      // Sache, nicht eine Sparmassnahme.
      //
      // Die Hülle ist eine Kugel mit Fresnel-Rand: Sie zeichnet genau den
      // hell umrandeten Kreis, wegen dem der Benutzer viermal
      // widersprochen hat („der Kreis um die grosse Kugel ist nicht
      // schön"). Das Nervengeflecht ist gerade deshalb so gebaut, dass es
      // keinen Umriss hat – läge die Hülle darüber, wäre der ganze Umbau
      // umsonst.
      //
      // Ausgeblendet und nicht gelöscht: Sie hängen an einem Dutzend
      // Farbzuweisungen weiter oben, und ein Ausbau wäre ein Umbau-
      // Durchgang mit einem Dutzend Gelegenheiten, etwas zu vergessen.
      // Eine Zeile wieder auf `true`, und sie sind zurück.
      this.gehaeuseSichtbar = false;
    }

    // Die umgekehrte Modellmatrix je Bild setzen.
    //
    // `onBeforeRender` ist dafür die einzige richtige Stelle: three.js ruft
    // es unmittelbar vor dem Zeichnen auf, wenn die Weltmatrix bereits
    // steht. Würde man sie in `update()` setzen, wäre sie um ein Bild
    // veraltet – der Haufen hinkte der Drehung sichtbar hinterher.
    this.core.onBeforeRender = () => {
      const uniform = this.coreMaterial.uniforms.uInvModel;
      if (uniform !== undefined) {
        uniform.value.copy(this.core.matrixWorld).invert();
      }
    };

    // --- Nebel ------------------------------------------------------------
    // Grösser als der Würfel, damit der Nebel ihn umschliesst statt ihn zu
    // verdecken. Die Geometrie ist bewusst grob (Stufe 2): Sichtbar ist
    // ohnehin nur, was der Shader im Inneren berechnet – eine feinere
    // Kugel würde nur Dreiecke kosten.
    this.smokeMaterial = createSmokeMaterial();
    this.smoke = new THREE.Mesh(
      new THREE.IcosahedronGeometry(0.72, 2),
      this.smokeMaterial
    );
    this.smoke.onBeforeRender = () => {
      const uniform = this.smokeMaterial.uniforms.uInvModel;
      if (uniform !== undefined) {
        uniform.value.copy(this.smoke.matrixWorld).invert();
      }
    };
    this.sphereGroup.add(this.smoke);

    // --- Hülle ------------------------------------------------------------
    this.shellMaterial = createShellMaterial();
    this.shell = new THREE.Mesh(
      new THREE.IcosahedronGeometry(0.78, Math.max(2, options.detail)),
      this.shellMaterial
    );
    this.sphereGroup.add(this.shell);

    // --- Aura -------------------------------------------------------------
    this.auraMaterial = createAuraMaterial();
    this.aura = new THREE.Mesh(
      new THREE.IcosahedronGeometry(1.05, Math.max(2, options.detail - 1)),
      this.auraMaterial
    );
    this.sphereGroup.add(this.aura);

    // Erst hier, weil es die drei vorher noch nicht gab: Der Konstruktor
    // entscheidet weiter oben, ob ein Gehäuse gezeichnet wird, bauen kann
    // er es aber erst an dieser Stelle.
    this.shell.visible = this.gehaeuseSichtbar;
    this.aura.visible = this.gehaeuseSichtbar;
    this.smoke.visible = this.gehaeuseSichtbar;

    // --- Partikel ---------------------------------------------------------
    // Nur, wenn ein Gehäuse gezeichnet wird.
    //
    // Das war die Ursache dafür, dass der Benutzer „immer noch die alte
    // Animation" sah: Diese Wolke aus Hunderten Partikeln lag ÜBER den
    // zwei Punkten. Sie gab es in jeder Fassung und in keiner der
    // Vorschauen, die der Benutzer abgenommen hat - und weil sie das
    // kleine Orb-Fenster füllt, während die zwei Punkte darin klein sind,
    // war sie das dominante, unveränderte Bild. Im Zwei-Punkte-Modus
    // (`gehaeuseSichtbar === false`) bleibt sie deshalb aus, und der Orb
    // zeigt genau das, was in der Vorschau stand.
    if (this.gehaeuseSichtbar && options.particlesEnabled && options.particleCount > 0) {
      this.particleMaterial = createParticleMaterial(pixelRatio);
      this.particles = this.createParticles(options.particleCount, this.particleMaterial);
      this.group.add(this.particles);
    }

    // --- Licht ------------------------------------------------------------
    this.light = new THREE.PointLight(0x4aa3ff, 2.4, 6.0, 2.0);
    this.group.add(this.light);
  }

  /**
   * Erzeugt die Partikelwolke.
   *
   * Jedes Partikel erhält einen eigenen Startwinkel, Bahnradius und eine
   * eigene Geschwindigkeit, damit die Aura nie gleichförmig wirkt.
   */
  private createParticles(count: number, material: THREE.ShaderMaterial): THREE.Points {
    const geometry = new THREE.BufferGeometry();

    const positions = new Float32Array(count * 3);
    const seeds = new Float32Array(count);
    const radii = new Float32Array(count);
    const speeds = new Float32Array(count);

    for (let index = 0; index < count; index += 1) {
      positions[index * 3 + 0] = 0;
      positions[index * 3 + 1] = 0;
      positions[index * 3 + 2] = 0;

      seeds[index] = Math.random();
      radii[index] = 0.85 + Math.random() * 0.55;
      speeds[index] = 0.25 + Math.random() * 0.7;
    }

    geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    geometry.setAttribute("aSeed", new THREE.BufferAttribute(seeds, 1));
    geometry.setAttribute("aRadius", new THREE.BufferAttribute(radii, 1));
    geometry.setAttribute("aSpeed", new THREE.BufferAttribute(speeds, 1));

    return new THREE.Points(geometry, material);
  }

  /**
   * Übernimmt das Erscheinungsbild eines Zustands.
   *
   * Wird in jedem Bild aufgerufen, damit auch laufende Zustandsübergänge
   * flüssig dargestellt werden.
   *
   * @param appearance Die aktuell wirksamen Zustandswerte.
   */
  public applyAppearance(appearance: StateAppearance): void {
    const core = new THREE.Color(appearance.coreColor);
    const glow = new THREE.Color(appearance.glowColor);
    const particle = new THREE.Color(appearance.particleColor);

    this.coreMaterial.uniforms.uColorInner.value.copy(glow);
    this.coreMaterial.uniforms.uColorOuter.value.copy(core);
    this.coreMaterial.uniforms.uIntensity.value = appearance.lightIntensity;

    // Der Haufen bekommt zusätzlich die Unruhe des Zustands – im
    // Ruhezustand wimmelt er langsam, beim Arbeiten deutlich lebhafter.
    if (this.coreMaterial.uniforms.uTurbulence !== undefined) {
      this.coreMaterial.uniforms.uTurbulence.value = appearance.smokeTurbulence;
    }

    this.neon?.setColors(core, glow, appearance.lightIntensity);

    // Die Farben des Zustands werden hier nur GEMERKT, nicht endgültig
    // gesetzt: Der Nebel um den Orb verfärbt sich zusätzlich langsam, und
    // das geschieht in jedem Bild (siehe nebelVerfaerben). Stünde die
    // Verfärbung hier, käme sie nur bei einem Zustandswechsel zustande –
    // also alle paar Minuten einmal.
    this.basisKern.copy(core);
    this.basisSchein.copy(glow);
    this.basisTeilchen.copy(particle);

    // Der Nebel bekommt seine Bewegung aus dem Zustand: ruhig im
    // Leerlauf, wirbelnd beim Denken, pulsierend beim Sprechen.
    this.smokeMaterial.uniforms.uColorInner.value.copy(glow);
    this.smokeMaterial.uniforms.uColorOuter.value.copy(core);
    this.smokeMaterial.uniforms.uIntensity.value = appearance.lightIntensity;
    this.smokeMaterial.uniforms.uTurbulence.value = appearance.smokeTurbulence;
    this.smokeMaterial.uniforms.uDensity.value = appearance.smokeDensity;
    this.smokeMaterial.uniforms.uPulse.value = appearance.smokePulse;
    this.smokeMaterial.uniforms.uWarning.value = appearance.smokeWarning;

    this.shellMaterial.uniforms.uColor.value.copy(core);
    this.shellMaterial.uniforms.uGlowColor.value.copy(glow);
    this.shellMaterial.uniforms.uIntensity.value = appearance.lightIntensity;

    this.auraMaterial.uniforms.uColor.value.copy(core);
    this.auraMaterial.uniforms.uGlowColor.value.copy(glow);
    this.auraMaterial.uniforms.uIntensity.value = appearance.lightIntensity * 0.6;

    this.aura.scale.setScalar(appearance.auraScale);

    if (this.particleMaterial !== null) {
      this.particleMaterial.uniforms.uColor.value.copy(particle);
      this.particleMaterial.uniforms.uIntensity.value = appearance.particleIntensity;
      this.particleMaterial.uniforms.uSpread.value = appearance.auraScale;
    }

    this.light.color.copy(core);
    this.light.intensity = 2.4 * appearance.lightIntensity;
  }

  /**
   * Aktualisiert alle zeitabhängigen Werte.
   *
   * @param elapsed Gesamtlaufzeit in Sekunden (bereits mit der
   *   Zustandsgeschwindigkeit skaliert).
   * @param delta Zeit seit dem letzten Bild in Sekunden.
   * @param appearance Die aktuell wirksamen Zustandswerte.
   */
  public update(elapsed: number, delta: number, appearance: StateAppearance): void {
    // Der Pegel folgt der Stimme: schnell hinauf, langsam hinunter.
    const anstieg = 1.0 - Math.exp(-delta * 28.0);
    const abfall = 1.0 - Math.exp(-delta * 6.0);
    this.voiceLevel +=
      (this.voiceTarget - this.voiceLevel) *
      (this.voiceTarget > this.voiceLevel ? anstieg : abfall);

    this.coreMaterial.uniforms.uTime.value = elapsed;
    // Nur der Haufen kennt den Sprechpegel; der schlichte Kern nicht.
    if (this.coreMaterial.uniforms.uPulse !== undefined) {
      this.coreMaterial.uniforms.uPulse.value = this.voiceLevel;
    }
    // Der Nebel läuft in eigener, langsamerer Zeit. Liefe er im selben Takt
    // wie der Kern, wirkte beides wie ein Stück – der räumliche Eindruck
    // entsteht gerade daraus, dass sich die Ebenen verschieden schnell
    // bewegen.
    this.smokeMaterial.uniforms.uTime.value = elapsed * 0.55;
    this.shellMaterial.uniforms.uTime.value = elapsed;
    this.auraMaterial.uniforms.uTime.value = elapsed * 0.7;

    this.nebelVerfaerben(elapsed);
    if (this.particleMaterial !== null) {
      this.particleMaterial.uniforms.uTime.value = elapsed;
    }

    // --- Der Haufen wandert -------------------------------------------------
    //
    // Drei Sinuskurven mit unteilbaren Verhältnissen (0.53, 0.37, 0.44):
    // Die Bahn schliesst sich dadurch nie zu einer sichtbaren Schleife,
    // sondern wirkt wie ein Umhertreiben. Wären die Frequenzen ganzzahlige
    // Vielfache voneinander, liefe er eine erkennbare Acht ab, und das
    // Auge hätte die Bewegung nach zwei Runden durchschaut.
    this.cubeGroup.position.set(
      Math.sin(elapsed * 0.53) * CLUSTER_DRIFT,
      Math.sin(elapsed * 0.37 + 1.1) * CLUSTER_DRIFT * 0.85,
      Math.cos(elapsed * 0.44 + 0.6) * CLUSTER_DRIFT
    );

    // --- Und taumelt dabei in alle Richtungen -------------------------------
    //
    // Nicht um eine feste Achse: Was sich nur um seine Hochachse dreht,
    // zeigt immer wieder dieselben Seiten und wirkt wie ein Karussell. Die
    // Achse wandert deshalb selbst – dadurch kommen nacheinander alle
    // Flanken des Haufens zum Vorschein, und die Bewegung wiederholt sich
    // für das Auge nie.
    //
    // Die Zahlen sind wieder unteilbar gewählt (0.21, 0.17, 0.29), damit
    // die Achse nicht in einen Takt fällt.
    this.tumbleAxis.set(
      Math.sin(elapsed * 0.21) + 0.35,
      Math.cos(elapsed * 0.17 + 0.9),
      Math.sin(elapsed * 0.29 + 2.1)
    );
    if (this.tumbleAxis.lengthSq() > 1e-6) {
      this.tumbleAxis.normalize();
      // Beim Sprechen dreht er schneller: Die Stimme treibt ihn an.
      const schwung = 0.55 * appearance.speed * (1.0 + this.voiceLevel * 1.6);
      this.core.rotateOnAxis(this.tumbleAxis, delta * schwung);
    }


    // --- Und verändert dabei seine Gestalt ----------------------------------
    //
    // Ungleichmässig in den drei Richtungen: Ein gleichmässiges Pulsieren
    // sähe aus wie Atmen, ein ungleichmässiges wie etwas, das lebt. Die
    // Stimme schlägt sich hier am deutlichsten nieder – bei jeder Silbe
    // dehnt sich der Würfel.
    if (this.neon !== null) {
      this.neon.setVoiceLevel(this.voiceLevel);
      this.neon.update(elapsed, delta, appearance.speed);
    }


    // --- Die Kugel dreht sich um den Würfel --------------------------------
    //
    // Um eine Achse, die selbst langsam wandert. Eine feste Achse liesse
    // die Kugel um einen sichtbaren Pol kreisen – das wirkt wie ein
    // Globus. Wandert die Achse, taumelt die Kugel, und erst dadurch wird
    // ihre Rundung im Raum lesbar.
    this.rotationAxis.set(
      Math.sin(elapsed * 0.13),
      Math.cos(elapsed * 0.11) * 0.8 + 0.5,
      Math.sin(elapsed * 0.07 + 1.3)
    );

    // Eine Achse der Länge null ergäbe beim Normalisieren (0,0,0), und eine
    // Drehung um nichts ergibt NaN – die Kugel verschwände dann für immer,
    // nicht nur für ein Bild. Rechnerisch trifft das fast nie ein; „fast
    // nie" ist bei 60 Bildern je Sekunde und stundenlangem Betrieb aber
    // kein Argument, sondern eine Frage der Zeit.
    if (this.rotationAxis.lengthSq() > 1e-6) {
      this.rotationAxis.normalize();
      this.sphereGroup.rotateOnAxis(this.rotationAxis, delta * 0.38 * appearance.speed);
    }

    // Die Aura läuft der Hülle bewusst entgegen: Zwei gegenläufige Lagen
    // trennen sich für das Auge, zwei gleichläufige verschmelzen.
    this.aura.rotation.z -= delta * 0.09 * appearance.speed;

    // Langsame Pulsation des gesamten Objekts.
    const pulse = 1.0 + Math.sin(elapsed * 1.15) * appearance.pulseAmount;
    this.group.scale.setScalar(this.baseScale * pulse);
  }

  /**
   * Setzt eine zusätzliche Skalierung, z. B. für den Hover-Effekt.
   *
   * @param scale Skalierungsfaktor (1.0 = Normalgröße).
   */
  public setBaseScale(scale: number): void {
    this.baseScale = scale;
  }

  /**
   * Meldet, wie laut gerade gesprochen wird.
   *
   * Damit schwingt der Orb mit der Stimme mit, statt unabhängig von ihr
   * vor sich hin zu animieren. Der Unterschied ist grösser, als er klingt:
   * Bewegt sich ein Bild synchron zu einem Klang, ordnet das Auge beides
   * derselben Ursache zu – der Orb *spricht* dann, statt bloss zu leuchten,
   * während irgendwo Ton läuft.
   *
   * @param level Pegel zwischen 0 und 1.
   */
  public setVoiceLevel(level: number): void {
    this.voiceTarget = Math.max(0.0, Math.min(1.0, level));
  }

  /** Der aktuelle Basis-Skalierungsfaktor. */
  public get scaleFactor(): number {
    return this.baseScale;
  }

  /**
   * Passt die Detailstufe an die verfügbare Leistung an.
   *
   * @param level 0 = niedrig, 1 = mittel, 2 = hoch.
   */
  /**
   * Lässt den Nebel um den Orb langsam die Farbe wechseln.
   *
   * Ein Nebel mit fester Farbe ist ein gefärbter Schleier. Zieht die Farbe
   * dagegen langsam durch ihn hindurch, wirkt er wie etwas, in dem sich
   * etwas abspielt – und das ist der ganze Unterschied zwischen einer
   * Kulisse und einer Erscheinung.
   *
   * Verschoben wird nur der FARBTON, nicht Sättigung und Helligkeit. Wer
   * mit den Farbwerten selbst rechnet, bekommt beim Mischen zwangsläufig
   * blasse Zwischentöne – über den Farbton bleibt die Farbe kräftig,
   * ganz gleich, wo sie gerade steht.
   *
   * Die drei Ebenen bekommen verschiedene Versätze und verschiedene Takte.
   * Liefen sie gleich, verfärbte sich der Orb als Ganzes wie unter einem
   * Farbfilter; verschieden ergibt es einen Verlauf, der durch die Tiefe
   * wandert.
   *
   * Der Ausschlag ist klein gehalten (gut ein Zehntel des Farbkreises).
   * Das reicht, damit man es sieht, und ist wenig genug, dass Rot beim
   * Arbeiten rot bleibt – die Farbe ist eine Auskunft und darf nicht
   * davonwandern.
   */
  private nebelVerfaerben(elapsed: number): void {
    const zug =
      Math.sin(elapsed * 0.083) * 0.075 + Math.sin(elapsed * 0.037 + 2.1) * 0.045;

    this.tonSchieben(this.basisSchein, zug, this.farbhilfe);
    this.smokeMaterial.uniforms.uColorInner.value.copy(this.farbhilfe);
    this.auraMaterial.uniforms.uGlowColor.value.copy(this.farbhilfe);

    this.tonSchieben(this.basisKern, -zug * 0.8, this.farbhilfe);
    this.smokeMaterial.uniforms.uColorOuter.value.copy(this.farbhilfe);
    this.auraMaterial.uniforms.uColor.value.copy(this.farbhilfe);

    if (this.particleMaterial !== null) {
      this.tonSchieben(this.basisTeilchen, zug * 1.35, this.farbhilfe);
      this.particleMaterial.uniforms.uColor.value.copy(this.farbhilfe);
    }
  }

  /** Verschiebt den Farbton einer Farbe, ohne sie blass zu machen. */
  private tonSchieben(von: THREE.Color, zug: number, ziel: THREE.Color): void {
    von.getHSL(this.hslHilfe);
    // Bei fast grauen Farben ist der Farbton beliebig – ihn zu verschieben
    // ergäbe ein Flackern zwischen zufälligen Tönen statt eines Zuges.
    if (this.hslHilfe.s < 0.06) {
      ziel.copy(von);
      return;
    }
    ziel.setHSL(
      ((this.hslHilfe.h + zug) % 1.0 + 1.0) % 1.0,
      this.hslHilfe.s,
      this.hslHilfe.l
    );
  }

  public setQuality(level: number): void {
    const visibleParticles = level >= 1;
    if (this.particles !== null) {
      this.particles.visible =
        this.gehaeuseSichtbar && visibleParticles && this.options.particlesEnabled;
    }
    this.aura.visible = this.gehaeuseSichtbar && level >= 1;


    // Der Nebel ist der teuerste Bestandteil, weil für jeden Bildpunkt
    // durch das Volumen marschiert wird. Deshalb wird hier zuerst gespart:
    // erst weniger Schritte, dann ganz aus.
    this.smokeMaterial.uniforms.uSteps.value = level >= 2 ? 32 : 16;
    // Der Haufen ist der zweite teure Posten: Auch hier wird für jeden
    // Bildpunkt marschiert. Gröber statt gar nicht – ohne ihn hätte der
    // Orb keinen Kern mehr.
    this.neon?.setQuality(level);
    if (this.coreMaterial.uniforms.uSteps !== undefined) {
      this.coreMaterial.uniforms.uSteps.value = level >= 2 ? 40 : level >= 1 ? 30 : 20;
    }
    if (this.coreMaterial.uniforms.uDeform !== undefined) {
      this.coreMaterial.uniforms.uDeform.value = level >= 2 ? 0.045 : 0.02;
    }
    this.smoke.visible = this.gehaeuseSichtbar && level >= 1;
    this.shell.visible = this.gehaeuseSichtbar;
  }

  /** Gibt alle GPU-Ressourcen frei. */
  public dispose(): void {
    this.core.geometry.dispose();
    this.neon?.dispose();
    this.smoke.geometry.dispose();
    this.shell.geometry.dispose();
    this.aura.geometry.dispose();
    this.coreMaterial.dispose();
    this.smokeMaterial.dispose();
    this.shellMaterial.dispose();
    this.auraMaterial.dispose();
    if (this.particles !== null) {
      this.particles.geometry.dispose();
    }
    this.particleMaterial?.dispose();
  }
}
