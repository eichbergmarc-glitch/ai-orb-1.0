/**
 * main.ts – Einstiegspunkt der Orb-Oberfläche.
 *
 * Verbindet alle Renderer-Module miteinander: Rendering, Orb-Geometrie,
 * Zustandsmaschine, Präsenz-Engine, Interaktion, Animationsschleife und die
 * Verbindung zum Backend.
 *
 * Die Oberfläche besteht ausschließlich aus dem Orb – es gibt keine
 * sichtbaren Schaltflächen, keine Fensterrahmen und keine
 * Browseroberfläche.
 */

import * as THREE from "three";

import { AnimationLoop } from "./animation";
import { BackendClient, type BackendEvent } from "./api";
import { EnergyOrb } from "./energy_orb";
import { InteractionController } from "./interaction";
import { Orb } from "./orb";
import { MovementEngine } from "./movement";
import { PresenceEngine } from "./presence";
import { OrbRenderer } from "./renderer";
import { ORB_STATES, StateMachine, type OrbStateName, type StateAppearance } from "./states";

/** Die von `preload.ts` bereitgestellte, abgesicherte Schnittstelle. */
interface AiOrbBridge {
  getConfig(): Promise<Record<string, unknown>>;
  onBackendEvent(callback: (event: BackendEvent) => void): void;
  onOrbOffset(
    callback: (offset: { x: number; y: number; immediate: boolean }) => void
  ): void;
  reportOrbOffset(x: number, y: number): void;
  moveWindowBy(dx: number, dy: number): void;
  commitWindowPosition(manual: boolean): void;
  showContextMenu(): void;
  triggerDoubleClickAction(): void;
  setIgnoreMouseEvents(ignore: boolean): void;
  setSpeaking(speaking: boolean): void;
  getBackendUrl(): Promise<string>;
}

declare global {
  interface Window {
    aiOrb: AiOrbBridge;
  }
}

/** Liest einen verschachtelten Wert aus der Konfiguration. */
function readConfig<T>(config: Record<string, unknown>, path: string, fallback: T): T {
  const parts = path.split(".");
  let current: unknown = config;
  for (const part of parts) {
    if (typeof current !== "object" || current === null || !(part in current)) {
      return fallback;
    }
    current = (current as Record<string, unknown>)[part];
  }
  return (current as T) ?? fallback;
}

/**
 * Baut die gesamte Oberfläche auf und startet sie.
 */
async function bootstrap(): Promise<void> {
  const canvas = document.getElementById("orb-canvas") as HTMLCanvasElement | null;
  if (canvas === null) {
    throw new Error("Das Canvas-Element wurde nicht gefunden.");
  }

  const config = (await window.aiOrb.getConfig()) ?? {};
  const backendUrl = await window.aiOrb.getBackendUrl();

  // --- Konfigurationswerte ------------------------------------------------
  const theme = readConfig(config, "orb.theme", "blue");
  const targetFps = readConfig(config, "orb.target_fps", 60);
  const adaptiveQuality = readConfig(config, "orb.adaptive_quality", true);
  const particlesEnabled = readConfig(config, "orb.particles_enabled", true);
  // Der gerechnete Kristallhaufen im Inneren. Auf false gestellt kommt der
  // schlichte Kern zurueck - der Rueckweg, falls ein Grafiktreiber den
  // aufwendigen Shader nicht uebersetzt.
  const clusterEnabled = readConfig(config, "orb.cluster", true) !== false;
  const particleCount = readConfig(config, "orb.particle_count", 260);
  const presenceEnabled = readConfig(config, "orb.presence_motion", true);
  // Grundgröße des Orb, unabhängig von der Fenstergröße. Das Fenster ist
  // bewusst größer – es ist der Bewegungsraum, nicht der Orb.
  //
  // Der Rückfallwert ist derselbe wie in der mitgelieferten config.yaml.
  // Vorher stand hier 0.5, also mehr als das Doppelte der Vorgabe: Konnte
  // die Konfiguration nicht gelesen werden, erschien ein riesiger Orb –
  // und das sah nach einem Fehler in der Darstellung aus, obwohl es einer
  // beim Finden einer Datei war.
  const orbScale = readConfig(config, "orb.scale", 0.2);
  const movementSpeed = readConfig<string>(config, "smart_desktop.movement_speed", "medium");
  const stateOverrides = readConfig<Record<string, Partial<StateAppearance>>>(config, "states", {});

  document.body.dataset.theme = theme;

  // --- Rendering ----------------------------------------------------------
  const renderer = new OrbRenderer(canvas, {
    bloomStrength: readConfig(config, "orb.bloom_strength", 1.35),
    bloomRadius: readConfig(config, "orb.bloom_radius", 0.55),
    bloomThreshold: readConfig(config, "orb.bloom_threshold", 0.15),
    maxPixelRatio: 2,
  });

  // Die veränderbaren Animationswerte aus orb.animation. Fehlt einer,
  // fällt die Animation auf ihre abgenommene Vorgabe zurück – die config
  // kann die Anzeige also nicht kaputtmachen.
  const animation = {
    abstand: readConfig<number | undefined>(config, "orb.animation.abstand", undefined),
    punktGroesse: readConfig<number | undefined>(config, "orb.animation.punkt_groesse", undefined),
    verschmelzen: readConfig<number | undefined>(config, "orb.animation.verschmelzen", undefined),
    schweifLaenge: readConfig<number | undefined>(config, "orb.animation.schweif_laenge", undefined),
    tempo: readConfig<number | undefined>(config, "orb.animation.tempo", undefined),
    helligkeit: readConfig<number | undefined>(config, "orb.animation.helligkeit", undefined),
    farbeA: readConfig<number | undefined>(config, "orb.animation.farbe_a", undefined),
    farbeB: readConfig<number | undefined>(config, "orb.animation.farbe_b", undefined),
  };

  // Der Energy-Orb ist die neue Anzeige (lebendiges Energie-Wesen mit
  // Kern, Plasma, Energiebahnen und Augen). `orb.energie: false` in der
  // config.yaml holt die bisherige Anzeige zurück - der Rückweg, falls ein
  // Grafiktreiber die neuen Shader nicht übersetzt.
  const energieAktiv = readConfig(config, "orb.energie", true) !== false;

  const orb = energieAktiv
    ? new EnergyOrb(
        { tempo: animation.tempo, helligkeit: animation.helligkeit },
        renderer.renderer.getPixelRatio()
      )
    : new Orb(
        { particleCount, particlesEnabled, detail: 4, clusterEnabled, animation },
        renderer.renderer.getPixelRatio()
      );
  const energyOrb = orb instanceof EnergyOrb ? orb : null;

  // Der Orb hängt in einer Trägergruppe: Die Präsenz-Engine bewegt den Orb
  // selbst (Atmen, Mikrobewegungen), die Bewegungs-Engine den Träger
  // (Ausweichen). Beides überlagert sich dadurch sauber.
  const carrier = new THREE.Group();
  carrier.add(orb.group);
  if (energyOrb !== null) {
    // Der Boden-Glow hängt am Träger, nicht am Orb: Er darf nicht
    // mitschweben - erst dadurch liest das Auge die Schwebehöhe.
    carrier.add(energyOrb.groundGroup);
  }
  renderer.scene.add(carrier);

  const movement = new MovementEngine(movementSpeed);
  movement.reset({ x: 0, y: 0 });

  /**
   * Umrechnung von Bildschirmpixeln in Weltkoordinaten.
   *
   * Die sichtbare Höhe der Szene ergibt sich aus Blickwinkel und Abstand
   * der Kamera; daraus folgt, wie viele Welteinheiten einem Pixel
   * entsprechen.
   */
  const worldPerPixel = (): number => {
    const visibleHeight =
      2 * renderer.camera.position.z * Math.tan((renderer.camera.fov * Math.PI) / 360);
    return visibleHeight / Math.max(1, window.innerHeight);
  };

  window.aiOrb.onOrbOffset(({ x, y, immediate }) => {
    if (immediate) {
      movement.reset({ x, y });
    } else {
      movement.moveTo({ x, y }, "easeInOut");
    }
  });

  // --- Zustände und Präsenz -------------------------------------------------
  const transitionSeconds = readConfig(config, "orb.transition_seconds", 0.9);
  const states = new StateMachine(theme, stateOverrides, transitionSeconds);
  const presence = new PresenceEngine({}, presenceEnabled);

  // --- Backend ---------------------------------------------------------------
  const backend = new BackendClient(backendUrl);
  backend.connect(readConfig(config, "backend.events_path", "/events"));

  backend.onConnectionChange((connected) => {
    // Kein Backend heisst OFFLINE, nicht Fehler: Der Orb lebt weiter,
    // nur sichtbar gedimmt - er sieht nicht aus, als wäre er abgestürzt.
    states.setState(connected ? "idle" : "offline");
  });

  // Der Sprechpegel, den der Kern meldet. Er wird hier nur eingesammelt;
  // geglaettet und in Bewegung uebersetzt wird er im Orb selbst.
  let stimmpegel = 0.0;

  backend.onEvent((event) => {
    stimmpegel = pegelAus(event, stimmpegel);
    handleBackendEvent(event, states);
  });
  window.aiOrb.onBackendEvent((event) => {
    stimmpegel = pegelAus(event, stimmpegel);
    handleBackendEvent(event, states);
  });

  // --- Interaktion ------------------------------------------------------------
  let hoverBoost = 1.0;
  let dragging = false;

  const interaction = new InteractionController(
    canvas,
    {
      onActivate: () => {
        loop.noteActivity();
        states.setState(states.current === "listening" ? "idle" : "listening");
        void backend.reportInteraction("aktivieren");
      },
      onContextMenu: () => {
        loop.noteActivity();
        window.aiOrb.showContextMenu();
        void backend.reportInteraction("kontextmenü");
      },
      onDoubleClick: () => {
        loop.noteActivity();
        window.aiOrb.triggerDoubleClickAction();
        void backend.reportInteraction("doppelklick");
      },
      onDragStart: () => {
        dragging = true;
        loop.noteActivity();
        states.setState("busy");
      },
      onDrag: (dx, dy) => {
        window.aiOrb.moveWindowBy(dx, dy);
      },
      onDragEnd: () => {
        dragging = false;
        // Eine bewusst gewählte Position wiegt im Lernsystem schwerer.
        window.aiOrb.commitWindowPosition(true);
        states.setState("idle");
      },
      onHover: (hovering) => {
        hoverBoost = hovering ? 1.12 : 1.0;
        if (hovering) {
          loop.noteActivity();
        }
      },
    },
    {
      // Die Trefferfläche folgt der tatsächlichen Größe des Orb, nicht der
      // des Fensters – sonst würde das ganze (viel größere) Fenster auf
      // Klicks reagieren.
      hitRadius: () => (1.05 * orbScale * states.appearance.scale) / worldPerPixel(),
    }
  );

  // --- Animationsschleife --------------------------------------------------------
  const loop = new AnimationLoop(
    {
      update: (elapsed, delta) => {
        states.update(delta);
        const appearance = states.appearance;

        // Die Zustandsgeschwindigkeit gilt dem *Inneren*, nicht dem Körper.
        //
        // Vorher skalierte sie die gesamte Animation – und wurde dabei
        // zweimal angewandt: einmal in `scaledElapsed`, und im
        // Eigenbewegungsmodul noch einmal als eigener Faktor. Beim
        // Zuhören (Geschwindigkeit 1.35) schwebte und atmete der Orb
        // dadurch nicht 1.35-fach, sondern 1.82-fach so schnell, beim
        // Denken (1.6) sogar 2.56-fach. Aus einem ruhigen Schweben wurde
        // ein Zittern.
        //
        // Der Körper läuft deshalb jetzt in Echtzeit: Schweben, Atmen und
        // die kleinen Eigenbewegungen bleiben in jedem Zustand gleich
        // ruhig. Schneller wird nur der Nebel im Inneren – dort gehört
        // die Aufregung hin.
        const scaledElapsed = elapsed * appearance.speed;

        presence.update(orb.group, elapsed, delta, 1.0);

        // Ausweichbewegung: rein grafisch, dadurch flüssig.
        const position = movement.update(delta);
        if (position !== null) {
          const scale = worldPerPixel();
          // Bildschirm-Y zeigt nach unten, Welt-Y nach oben.
          carrier.position.set(position.x * scale, -position.y * scale, 0);
          // Trefferfläche und Hauptprozess müssen wissen, wo der Orb steht.
          interaction.setOrbOffset(position.x, position.y);
          window.aiOrb.reportOrbOffset(position.x, position.y);
        }

        // Grundgröße × Zustandsgröße × Atmung × Hover.
        //
        // Die Atmung bekommt bewusst `elapsed` und nicht `scaledElapsed`:
        // Ein Mensch, der aufmerksam zuhört, atmet nicht schneller. Er
        // wird ruhiger.
        orb.setBaseScale(
          orbScale * appearance.scale * presence.breathScale(elapsed) * hoverBoost
        );
        orb.applyAppearance(appearance);
        orb.setVoiceLevel(stimmpegel);
        if (energyOrb !== null) {
          // Der Boden-Glow atmet mit der Schwebehöhe der Präsenz-Engine.
          energyOrb.setFloatHeight(presence.currentOffset.y);
        }
        orb.update(scaledElapsed, delta, appearance);

        // Der Pegel verfaellt von selbst. Bleibt die naechste Meldung aus -
        // weil das Sprechen endet oder die Verbindung stockt -, laeuft der
        // Orb sonst weiter, als spraeche er noch.
        stimmpegel = Math.max(0.0, stimmpegel - delta * 1.8);

        renderer.post.setBloomStrength(appearance.bloomStrength * (dragging ? 0.85 : 1.0));
      },
      render: () => renderer.render(),
      onQualityChange: (level) => {
        renderer.setQuality(level);
        orb.setQuality(level);
      },
    },
    { targetFps, adaptiveQuality }
  );

  loop.start();

  // Beim Wechsel in den Schlafzustand keine Interaktion mehr annehmen,
  // damit ein versehentlicher Klick den Orb nicht weckt.
  //
  // Zusätzlich löst der Wechsel in bestimmte Zustände einen kurzen
  // Lichtimpuls aus (Energie sammelt sich -> Kern leuchtet -> Welle nach
  // außen) - dezent beim Aufwachen, deutlich beim Erfolg, warm beim Fehler.
  const eintrittsImpulse: Partial<Record<OrbStateName, number>> = {
    listening: 0.45,
    success: 1.0,
    error: 0.8,
    warning: 0.5,
  };
  let successRueckkehr: number | undefined;
  states.onChange((state) => {
    interaction.setEnabled(state !== "sleep");
    void backend.reportState(state);

    const impuls = eintrittsImpulse[state];
    if (energyOrb !== null && impuls !== undefined) {
      energyOrb.flash(impuls);
    }
    // Erfolg ist eine kurze Bestätigung von etwa einer Sekunde, danach
    // kehrt der Orb von selbst weich in den Ruhezustand zurück.
    if (state === "success") {
      window.clearTimeout(successRueckkehr);
      successRueckkehr = window.setTimeout(() => {
        if (states.current === "success") {
          states.setState("idle");
        }
      }, 1150);
    }
  });

  // --- Subtile Mausreaktion --------------------------------------------------
  // Der Blick der Augen folgt der Maus minimal; ein Klick gibt einen
  // kleinen Energieimpuls. Der Orb jagt der Maus nicht hinterher.
  if (energyOrb !== null) {
    window.addEventListener("pointermove", (ev) => {
      const dx = (ev.clientX - window.innerWidth / 2) / (window.innerWidth / 2);
      const dy = -(ev.clientY - window.innerHeight / 2) / (window.innerHeight / 2);
      const nah = Math.hypot(dx, dy) < 0.6;
      energyOrb.setPointer(dx, dy, nah);
    });
    canvas.addEventListener("pointerdown", () => {
      energyOrb.flash(0.35);
    });
  }

  // --- Entwickler-Testmodus ---------------------------------------------------
  // Strg+Alt+1..9 schaltet die Zustände von Hand durch, unabhängig vom
  // Backend - so lässt sich die Animation für sich prüfen. Strg+Alt+0
  // zeigt den aktuellen Zustand in der Konsole.
  const debugZustaende: OrbStateName[] = [
    "idle", "listening", "thinking", "executing", "waiting",
    "success", "warning", "error", "offline",
  ];
  window.addEventListener("keydown", (ev) => {
    if (!ev.ctrlKey || !ev.altKey) {
      return;
    }
    const ziffer = Number.parseInt(ev.key, 10);
    if (Number.isInteger(ziffer) && ziffer >= 1 && ziffer <= debugZustaende.length) {
      states.setState(debugZustaende[ziffer - 1]);
      console.info(`[AI-Orb] Testmodus: Zustand '${debugZustaende[ziffer - 1]}'.`);
    } else if (ev.key === "0") {
      console.info(`[AI-Orb] Zustand: '${states.current}'.`, ORB_STATES);
    }
  });

  // Der Orb reagiert nur dort auf die Maus, wo er tatsächlich sichtbar ist;
  // der übrige Fensterbereich bleibt für Klicks durchlässig.
  window.addEventListener("pointermove", () => {
    window.aiOrb.setIgnoreMouseEvents(!interaction.isHovering && !dragging);
  });

  window.addEventListener("beforeunload", () => {
    loop.stop();
    backend.close();
    orb.dispose();
    renderer.dispose();
  });
}

/**
 * Übersetzt Backend-Ereignisse in Zustände des Orb.
 *
 * Dadurch spiegelt der Orb sichtbar wider, was das Backend gerade tut.
 */
/**
 * Liest den Sprechpegel aus einem Ereignis.
 *
 * Der Kern meldet ihn waehrend der Sprachausgabe fortlaufend. Alles andere
 * laesst den bisherigen Wert unberuehrt - ein Ereignis ohne Pegel ist kein
 * Pegel von null, sondern schlicht keine Auskunft.
 */
function pegelAus(event: BackendEvent, bisher: number): number {
  if (event.event !== "voice.level") {
    return bisher;
  }
  const roh = (event.payload as { level?: unknown } | undefined)?.level;
  if (typeof roh !== "number" || !Number.isFinite(roh)) {
    return bisher;
  }
  return Math.max(0.0, Math.min(1.0, roh));
}

function handleBackendEvent(event: BackendEvent, states: StateMachine): void {
  // Der Orb hat seine eigene Animation geändert (Werte oder Code) und
  // will, dass die Anzeige neu lädt. `location.reload()` lädt index.html
  // neu – und damit die frisch geschriebene config UND eine eventuell neu
  // gebaute renderer.js. Das ist der ganze Trick, mit dem der Benutzer die
  // Animation dem Orb erklären kann, statt Dateien von Hand zu ändern.
  if (event.event === "orb.oberflaeche.neu_laden") {
    window.setTimeout(() => window.location.reload(), 150);
    return;
  }

  const mapping: Record<string, OrbStateName> = {
    "system.ready": "idle",
    "audio.recorded": "thinking",
    "speech.transcribed": "thinking",
    "ai.request": "thinking",
    "ai.intent.classified": "thinking",
    "ai.response": "speaking",
    "cognitive.response": "speaking",
    "cognitive.clarification": "listening",
    // Der Orb wartet sichtbar auf den Benutzer, wenn eine Freigabe oder
    // Bestätigung aussteht - das ist WAITING, nicht Zuhören.
    "cognitive.confirmation_required": "waiting",
    "security.consent.requested": "waiting",
    "security.consent.resolved": "idle",
    "tts.started": "speaking",
    // Nach der Antwort eine ruhige Bestätigung (Erfolgsimpuls), dann kehrt
    // der Orb von selbst in den Ruhezustand zurück (siehe onChange).
    "tts.finished": "success",
    "system.error": "error",
  };

  const next = mapping[event.event];
  if (next !== undefined) {
    states.setState(next);
    // Den Hauptprozess ueber das Sprechen unterrichten, damit er die
    // Unterbrechungs-Taste nur waehrend der Sprachausgabe abfaengt.
    if (event.event === "tts.started") {
      window.aiOrb.setSpeaking(true);
    } else if (event.event === "tts.finished") {
      window.aiOrb.setSpeaking(false);
    }
    // Nach einer Antwort kehrt der Orb von selbst in den Ruhezustand zurück.
    if (next === "speaking") {
      window.setTimeout(() => {
        if (states.current === "speaking") {
          states.setState("idle");
        }
      }, 2600);
    }
  }
}

bootstrap().catch((error: unknown) => {
  // Ein Fehler beim Start darf nicht stillschweigend passieren: Er wird
  // protokolliert und ist über die Entwicklerwerkzeuge einsehbar.
  console.error("[AI-Orb] Die Oberfläche konnte nicht gestartet werden:", error);
});
