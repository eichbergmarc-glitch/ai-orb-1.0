/**
 * renderer.ts – Aufbau von Szene, Kamera und WebGL-Renderer.
 *
 * Dieses Modul ist ausschließlich für das Rendering zuständig: Es erzeugt
 * den WebGL-Kontext mit transparentem Hintergrund, richtet Kamera und
 * Beleuchtung ein und stellt den Nachbearbeitungs-Stapel bereit.
 *
 * Es kennt weder Zustände noch Interaktion noch Animation.
 */

import * as THREE from "three";

import { createPostProcessing, type PostProcessing } from "./effects";

/** Optionen für den Aufbau der Szene. */
export interface SceneOptions {
  bloomStrength: number;
  bloomRadius: number;
  bloomThreshold: number;
  maxPixelRatio: number;
}

/** Bündelt alle Rendering-Bestandteile. */
export class OrbRenderer {
  public readonly scene: THREE.Scene;
  public readonly camera: THREE.PerspectiveCamera;
  public readonly renderer: THREE.WebGLRenderer;
  public readonly post: PostProcessing;

  private canvas: HTMLCanvasElement;
  private readonly maxPixelRatio: number;

  /**
   * @param canvas Das Canvas-Element, in das gerendert wird.
   * @param options Bloom- und Qualitätsparameter aus `config.yaml`.
   */
  constructor(canvas: HTMLCanvasElement, options: SceneOptions) {
    this.canvas = canvas;
    this.maxPixelRatio = Math.max(1, Math.min(2, options.maxPixelRatio));

    this.renderer = new THREE.WebGLRenderer({
      canvas,
      alpha: true,
      antialias: true,
      // Electron komponiert das transparente Fenster asynchron mit dem
      // Desktop. Ohne erhaltenen Zeichenpuffer kann es dabei genau zwischen
      // WebGL-Clear und Present lesen: Der komplette Orb fehlt dann fuer ein
      // Bild. Das ist das vom Benutzer beobachtete Vollbild-Flackern.
      preserveDrawingBuffer: true,
      premultipliedAlpha: true,
      powerPreference: "high-performance",
    });
    // Vollständig transparenter Hintergrund: kein Schwarz, kein Weiß.
    this.renderer.setClearColor(0x000000, 0);
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, this.maxPixelRatio));
    this.renderer.setSize(window.innerWidth, window.innerHeight, false);
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.15;

    this.scene = new THREE.Scene();
    this.scene.background = null;

    this.camera = new THREE.PerspectiveCamera(
      45,
      window.innerWidth / Math.max(1, window.innerHeight),
      0.1,
      100
    );
    this.camera.position.set(0, 0, 4.2);

    // Sehr dezente Grundbeleuchtung: Der Orb leuchtet überwiegend selbst.
    const ambient = new THREE.AmbientLight(0xffffff, 0.18);
    this.scene.add(ambient);

    const rim = new THREE.DirectionalLight(0xffffff, 0.35);
    rim.position.set(2, 3, 4);
    this.scene.add(rim);

    this.post = createPostProcessing(this.renderer, this.scene, this.camera, {
      strength: options.bloomStrength,
      radius: options.bloomRadius,
      threshold: options.bloomThreshold,
    });

    window.addEventListener("resize", () => this.handleResize());
  }

  /** Passt Renderer und Kamera an die Fenstergröße an. */
  public handleResize(): void {
    const width = window.innerWidth;
    const height = Math.max(1, window.innerHeight);

    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(width, height, false);
    this.post.setSize(width, height);
  }

  /**
   * Senkt oder erhöht die Renderauflösung zur Leistungsanpassung.
   *
   * @param level 0 = niedrig, 1 = mittel, 2 = hoch.
   */
  public setQuality(level: number): void {
    const ratios = [
      1.0,
      Math.min(1.35, window.devicePixelRatio, this.maxPixelRatio),
      Math.min(window.devicePixelRatio, this.maxPixelRatio),
    ];
    this.renderer.setPixelRatio(ratios[Math.max(0, Math.min(2, level))]);
    this.handleResize();
  }

  /** Rendert ein Bild über den Nachbearbeitungs-Stapel. */
  public render(): void {
    this.post.render();
  }

  /** Gibt alle GPU-Ressourcen frei. */
  public dispose(): void {
    this.renderer.dispose();
  }

  /** Das verwendete Canvas-Element. */
  public get element(): HTMLCanvasElement {
    return this.canvas;
  }
}
