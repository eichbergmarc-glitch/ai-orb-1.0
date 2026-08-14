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
import {
  EnergyOrb,
  type OrbEmotionName,
  type OrbVisualStyle,
} from "./energy_orb";
import { DiagnosticsPanel } from "./diagnostics";
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
  onGlobalPointer(callback: (position: { x: number; y: number }) => void): void;
  performMenuAction(action: string): void;
  moveWindowBy(dx: number, dy: number): void;
  commitWindowPosition(manual: boolean): void;
  showContextMenu(): void;
  triggerDoubleClickAction(): void;
  setIgnoreMouseEvents(ignore: boolean): void;
  setInteractionLock(active: boolean, reason: string): void;
  setChatFocus(active: boolean): void;
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
  const idleFps = readConfig(config, "orb.idle_fps", targetFps);
  const adaptiveQuality = readConfig(config, "orb.adaptive_quality", true);
  const particlesEnabled = readConfig(config, "orb.particles_enabled", true);
  // Der gerechnete Kristallhaufen im Inneren. Auf false gestellt kommt der
  // schlichte Kern zurueck - der Rueckweg, falls ein Grafiktreiber den
  // aufwendigen Shader nicht uebersetzt.
  const clusterEnabled = readConfig<boolean>(config, "orb.cluster", true) !== false;
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
  const orbScale = readConfig(config, "orb.scale", 0.28);
  const movementSpeed = readConfig<string>(config, "smart_desktop.movement_speed", "medium");
  const stateOverrides = readConfig<Record<string, Partial<StateAppearance>>>(config, "states", {});

  document.body.dataset.theme = theme;

  // --- Rendering ----------------------------------------------------------
  const renderer = new OrbRenderer(canvas, {
    bloomStrength: readConfig(config, "orb.bloom_strength", 0.62),
    bloomRadius: readConfig(config, "orb.bloom_radius", 0.35),
    bloomThreshold: readConfig(config, "orb.bloom_threshold", 0.42),
    // Bei einem sichtbaren Orb von rund 90 Pixeln ist mehr als 1,5-fache
    // Renderauflösung optisch ohne Nutzen, vervielfacht aber die Kosten des
    // Bloom-Effekts und kann auf integrierten GPUs Frames auslassen.
    maxPixelRatio: readConfig(config, "orb.max_pixel_ratio", 1.5),
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
  const energieAktiv = readConfig<boolean>(config, "orb.energie", true) !== false;

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
  const orbMenu = document.getElementById("orb-menu") as HTMLElement | null;
  const orbInfo = document.getElementById("orb-info") as HTMLElement | null;
  const chatPanel = document.getElementById("chat-panel") as HTMLElement | null;
  const chatMessages = document.getElementById("chat-messages") as HTMLElement | null;
  const chatForm = document.getElementById("chat-form") as HTMLFormElement | null;
  const chatInput = document.getElementById("chat-input") as HTMLInputElement | null;

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
  let renderedOrbOffset = { x: 0, y: 0 };

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
  let progressHideTimer: number | undefined;

  const handleProgress = (event: BackendEvent): void => {
    if (energyOrb === null || !event.event.startsWith("task.")) return;
    if (event.event === "task.started") {
      energyOrb.setProgress(0.0, true);
      if (orbInfo !== null) orbInfo.textContent = "Arbeite …";
      return;
    }
    if (event.event === "task.progress") {
      const raw = Number(event.payload.progress ?? event.payload.percent);
      energyOrb.setProgress(Number.isFinite(raw) ? (raw > 1 ? raw / 100 : raw) : 0.0, !Number.isFinite(raw));
      if (orbInfo !== null && Number.isFinite(raw)) {
        orbInfo.textContent = `${Math.round((raw > 1 ? raw / 100 : raw) * 100)} %`;
      }
      return;
    }
    if (event.event === "task.finished") {
      energyOrb.setProgress(1.0);
      if (orbInfo !== null) orbInfo.textContent = event.payload.ok === false ? "Fehler" : "Fertig";
      window.clearTimeout(progressHideTimer);
      progressHideTimer = window.setTimeout(() => energyOrb.setProgress(null), 550);
    }
  };

  backend.onEvent((event) => {
    stimmpegel = pegelAus(event, stimmpegel);
    handleProgress(event);
    handleEmotionEvent(event, energyOrb);
    handleProfessorEvent(event, energyOrb);
    handleBackendEvent(event, states);
  });
  window.aiOrb.onBackendEvent((event) => {
    stimmpegel = pegelAus(event, stimmpegel);
    handleProgress(event);
    handleEmotionEvent(event, energyOrb);
    handleProfessorEvent(event, energyOrb);
    handleBackendEvent(event, states);
  });

  // --- Interaktion ------------------------------------------------------------
  let hoverBoost = 1.0;
  let dragging = false;
  let menuOpen = false;
  let chatOpen = false;
  let lastMousePassthrough: boolean | null = null;

  const setMousePassthrough = (ignore: boolean): void => {
    if (ignore === lastMousePassthrough) return;
    lastMousePassthrough = ignore;
    window.aiOrb.setIgnoreMouseEvents(ignore);
  };

  const updateOverlayInput = (): void => {
    setMousePassthrough(!menuOpen && !chatOpen && !dragging);
  };

  const showMenu = (show: boolean): void => {
    menuOpen = show;
    if (orbMenu !== null) orbMenu.hidden = !show;
    window.aiOrb.setInteractionLock(show, "menu");
    updateOverlayInput();
  };

  const handleVoiceMenu = (event: BackendEvent): void => {
    if (event.event !== "orb.menu.requested") return;
    const action = String(event.payload.action ?? "open");
    showMenu(action !== "close");
    loop.noteActivity();
  };
  backend.onEvent(handleVoiceMenu);
  window.aiOrb.onBackendEvent(handleVoiceMenu);

  const showChat = (show: boolean): void => {
    chatOpen = show;
    if (chatPanel !== null) chatPanel.hidden = !show;
    window.aiOrb.setChatFocus(show);
    window.aiOrb.setInteractionLock(show, "chat");
    updateOverlayInput();
    if (show) {
      window.setTimeout(() => {
        chatInput?.focus();
        chatInput?.select();
      }, 40);
    }
  };

  const addChatMessage = (text: string, kind: "user" | "orb" | "pending"): HTMLDivElement | null => {
    if (chatMessages === null) return null;
    const message = document.createElement("div");
    message.className = `chat-message chat-message--${kind}`;
    message.textContent = text;
    chatMessages.appendChild(message);
    chatMessages.scrollTop = chatMessages.scrollHeight;
    return message;
  };

  const orbHitRadiusPixels = (): number =>
    (1.05 * orbScale * states.appearance.scale) / worldPerPixel();

  const interaction = new InteractionController(
    canvas,
    {
      onActivate: () => {
        loop.noteActivity();
        energyOrb?.react("click");
        // Ein UI-Klick ist noch kein Sprachzustand. Listening wird erst
        // durch das Mikrofon/Backend gesetzt; sonst können überlappende
        // Klick- und Kontextmenüereignisse die Anzeige hektisch toggeln.
        void backend.reportInteraction("aktivieren");
      },
      onContextMenu: () => {
        loop.noteActivity();
        showMenu(!menuOpen);
        // Das Oeffnen des lokalen Menues ist kein Denk-, Sprach- oder
        // Arbeitsauftrag. Es bleibt deshalb vollstaendig im Renderer und
        // darf keine Backend-Zustandsfolge ausloesen.
      },
      onDoubleClick: () => {
        loop.noteActivity();
        energyOrb?.setEmotion("surprised", 2.0);
        window.aiOrb.triggerDoubleClickAction();
        void backend.reportInteraction("doppelklick");
      },
      onDragStart: () => {
        dragging = true;
        loop.noteActivity();
      },
      onDrag: (dx, dy) => {
        window.aiOrb.moveWindowBy(dx, dy);
      },
      onDragEnd: () => {
        dragging = false;
        // Eine bewusst gewählte Position wiegt im Lernsystem schwerer.
        window.aiOrb.commitWindowPosition(true);
      },
      onHover: (hovering) => {
        hoverBoost = hovering ? 1.12 : 1.0;
        window.aiOrb.setInteractionLock(hovering, "pointer");
        if (hovering) {
          loop.noteActivity();
        }
      },
    },
    {
      // Die Trefferfläche folgt der tatsächlichen Größe des Orb, nicht der
      // des Fensters – sonst würde das ganze (viel größere) Fenster auf
      // Klicks reagieren.
      hitRadius: orbHitRadiusPixels,
    }
  );

  orbMenu?.querySelectorAll<HTMLButtonElement>("button[data-action]").forEach((button) => {
    button.addEventListener("click", () => {
      const action = button.dataset.action ?? "";
      loop.noteActivity();
      energyOrb?.react("click");
      if (action === "chat") {
        showChat(true);
        showMenu(false);
        return;
      }
      if (action === "screenshot") {
        states.setState("thinking");
        void backend.ask("Mach einen Screenshot und beschreibe kurz, was darauf zu sehen ist.");
      } else {
        window.aiOrb.performMenuAction(action);
      }
      void backend.reportInteraction(`menü:${action}`);
      showMenu(false);
    });
  });

  document.getElementById("chat-close")?.addEventListener("click", () => showChat(false));
  chatForm?.addEventListener("submit", (event) => {
    event.preventDefault();
    const text = chatInput?.value.trim() ?? "";
    if (text === "") return;
    if (chatInput !== null) chatInput.value = "";
    addChatMessage(text, "user");
    const pending = addChatMessage("AI-Orb denkt nach …", "pending");
    states.setState("thinking");
    void backend.ask(text).then((answer) => {
      pending?.remove();
      if (answer === null) {
        addChatMessage("Ich konnte das Backend gerade nicht erreichen.", "orb");
        states.setState("offline");
        return;
      }
      addChatMessage(answer.response, "orb");
      states.setState("success");
      chatInput?.focus();
    });
  });

  // --- Animationsschleife --------------------------------------------------------
  const loop = new AnimationLoop(
    {
      update: (elapsed, delta) => {
        states.update(delta);
        const appearance = states.appearance;

        // Die Zustandsgeschwindigkeit gilt dem *Inneren*, nicht dem Körper.
        //
        // Vorher skalierte sie die gesamte Animation – und wurde dabei
        // zweimal angewandt: einmal über eine skalierte absolute Zeit, und im
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
        presence.update(orb.group, elapsed, delta, 1.0);

        // Ausweichbewegung: rein grafisch, dadurch flüssig.
        const position = movement.update(delta);
        if (position !== null) {
          renderedOrbOffset = { x: position.x, y: position.y };
          orbMenu?.style.setProperty("--orb-x", `${position.x}px`);
          orbMenu?.style.setProperty("--orb-y", `${position.y}px`);
          const scale = worldPerPixel();
          // Bildschirm-Y zeigt nach unten, Welt-Y nach oben.
          carrier.position.set(position.x * scale, -position.y * scale, 0);
          // Trefferfläche und Hauptprozess müssen wissen, wo der Orb steht.
          interaction.setOrbOffset(position.x, position.y);
          window.aiOrb.reportOrbOffset(position.x, position.y);
        }

        // Grundgröße × Zustandsgröße × Atmung × Hover.
        //
        // Die Atmung bekommt bewusst die unveränderte reale Laufzeit:
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
        // Die absolute Zeit darf nie mit einem gerade überblendeten
        // Zustands-Tempo multipliziert werden. Nach längerer Laufzeit würde
        // schon eine kleine Tempoänderung die Ringe sichtbar vorspringen
        // lassen. Der Energy-Orb integriert seine Zustandstempi selbst.
        orb.update(elapsed, delta, appearance);

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
    { targetFps, idleFps, adaptiveQuality }
  );

  const diagnostics = new DiagnosticsPanel(backend, loop);
  backend.onEvent((event) => {
    if (event.event === "ui.diagnostics.toggle") diagnostics.toggle();
  });

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
    const automaticStyles: Record<OrbStateName, OrbVisualStyle> = {
      idle: "standard", listening: "nature", thinking: "galactic",
      speaking: "standard", busy: "fire", error: "fire", sleep: "minimal",
      executing: "fire", waiting: "ice", success: "nature",
      warning: "fire", offline: "minimal",
    };
    energyOrb?.setVisualStyle(automaticStyles[state]);
    energyOrb?.setState(state);
    if (orbInfo !== null) {
      const labels: Record<OrbStateName, string> = {
        idle: "Bereit", listening: "Hört zu", thinking: "Denkt nach",
        speaking: "Antwortet", busy: "Bewegt", error: "Fehler", sleep: "Schläft",
        executing: "Arbeitet", waiting: "Wartet", success: "Erfolg",
        warning: "Warnung", offline: "Offline",
      };
      orbInfo.textContent = labels[state];
    }

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
  // Der Blick der Augen folgt der Maus sichtbar; ein Klick gibt einen
  // kleinen Energieimpuls. Normiert wird relativ zur sichtbaren Orb-Groesse
  // und zu seiner bewegten Position, nicht zum viel groesseren Fenster.
  if (energyOrb !== null) {
    const updateGaze = (x: number, y: number): void => {
      const centerX = window.innerWidth / 2 + renderedOrbOffset.x;
      const centerY = window.innerHeight / 2 + renderedOrbOffset.y;
      const gazeRange = Math.max(44, orbHitRadiusPixels() * 1.35);
      const dx = (x - centerX) / gazeRange;
      const dy = -(y - centerY) / gazeRange;
      energyOrb.setPointer(dx, dy, true);
    };
    window.aiOrb.onGlobalPointer((position) => updateGaze(position.x, position.y));
    window.addEventListener("pointermove", (ev) => updateGaze(ev.clientX, ev.clientY));
    canvas.addEventListener("pointerdown", () => {
      energyOrb.react("click");
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
    setMousePassthrough(!interaction.isHovering && !dragging && !menuOpen && !chatOpen);
  });

  window.addEventListener("beforeunload", () => {
    window.aiOrb.setInteractionLock(false, "menu");
    window.aiOrb.setInteractionLock(false, "chat");
    window.aiOrb.setInteractionLock(false, "pointer");
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

function handleEmotionEvent(event: BackendEvent, orb: EnergyOrb | null): void {
  if (orb === null) return;
  const aliases: Record<string, OrbEmotionName> = {
    friendly: "friendly", freundlich: "friendly",
    curious: "curious", neugierig: "curious",
    surprised: "surprised", überrascht: "surprised", ueberrascht: "surprised",
    thoughtful: "thoughtful", nachdenklich: "thoughtful",
    joyful: "joyful", fröhlich: "joyful", froehlich: "joyful",
    relaxed: "relaxed", entspannt: "relaxed",
  };
  if (event.event === "orb.emotion.changed" || event.event === "presence.emotion.changed") {
    const raw = String(event.payload.emotion ?? event.payload.mood ?? "").toLowerCase();
    const emotion = aliases[raw];
    if (emotion !== undefined) orb.setEmotion(emotion);
  }
}

/** ProfessorSession entscheidet fachlich; der Renderer zeichnet nur. */
function handleProfessorEvent(event: BackendEvent, orb: EnergyOrb | null): void {
  if (orb === null || event.event !== "orb.professor.changed") return;
  const active = (event.payload as { active?: unknown } | undefined)?.active;
  orb.setProfessorMode(active === true);
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

  // Ein Entwicklungsauftrag dauert deutlich länger als eine normale
  // Antwort. Seine Phasen bleiben deshalb sichtbar: Planung denkt,
  // Patch/Test arbeitet, erfolgreiche Übernahme bestätigt grün.
  if (event.event === "orb.entwicklung.status") {
    const phase = String(
      (event.payload as { phase?: unknown } | undefined)?.phase ?? "",
    );
    const developmentStates: Record<string, OrbStateName> = {
      planung: "thinking",
      patch: "executing",
      tests: "executing",
      fertig: "success",
    };
    const next = developmentStates[phase];
    if (next !== undefined) states.setState(next);
    return;
  }

  // Zweiter, direkter Weg für den Sprachzustand. Das Backend sendet zwar
  // zusätzlich orb.state.changed, aber die Augen/Farben dürfen nicht von
  // genau einem Ereignisnamen abhängen, falls ein Client beim Neuverbinden
  // eine Meldung verpasst.
  if (event.event === "voice.state.changed") {
    const requested = (event.payload as { orb_state?: unknown } | undefined)?.orb_state;
    if (typeof requested === "string" && ORB_STATES.includes(requested as OrbStateName)) {
      states.setState(requested as OrbStateName);
    }
    return;
  }

  // Eine Antwort besteht intern aus mehreren TTS-Abschnitten. Erfolg wird
  // deshalb erst einmal am Ende der GESAMTEN Antwort gezeigt.
  if (event.event === "voice.response.finished") {
    const completed = (event.payload as { completed?: unknown } | undefined)?.completed;
    states.setState(completed === false ? "error" : "success");
    return;
  }

  if (event.event === "tts.finished") {
    window.aiOrb.setSpeaking(false);
    const final = (event.payload as { final?: unknown } | undefined)?.final;
    const completed = (event.payload as { completed?: unknown } | undefined)?.completed;
    if (final !== false) {
      states.setState(completed === false ? "error" : "success");
    }
    return;
  }

  // Direkte Zustandsmeldungen waren bisher nur eine Einbahnstrasse vom
  // Renderer zum Backend. Dadurch konnte weder die API noch ein Werkzeug
  // WAITING, WARNING oder ERROR sichtbar aktivieren. Den gemeldeten Namen
  // jetzt validiert zurueck in die Zustandsmaschine uebernehmen.
  if (event.event === "orb.state.changed" || event.event === "orb.state.request") {
    const requested = (event.payload as { state?: unknown } | undefined)?.state;
    if (typeof requested === "string" && ORB_STATES.includes(requested as OrbStateName)) {
      states.setState(requested as OrbStateName);
    }
    return;
  }

  // Ein beendeter Task ist nicht automatisch erfolgreich. Das Backend
  // liefert das Ergebnis bereits als `ok`; erst dessen Auswertung macht
  // die gruene Bestaetigung beziehungsweise die roten Fehleraugen wahr.
  if (event.event === "task.finished") {
    const ok = (event.payload as { ok?: unknown } | undefined)?.ok;
    states.setState(ok === false ? "error" : "success");
    return;
  }

  // Eine verweigerte oder abgelaufene Freigabe ist eine Warnung, kein
  // technischer Fehler. Genau hier erscheint das orange Ausrufezeichen.
  if (event.event === "security.consent.resolved") {
    const granted = (event.payload as { granted?: unknown } | undefined)?.granted;
    states.setState(granted === false ? "warning" : "idle");
    return;
  }

  const mapping: Record<string, OrbStateName> = {
    "system.ready": "idle",
    "audio.recorded": "thinking",
    "speech.transcribed": "thinking",
    "ai.request": "thinking",
    "ai.intent.classified": "thinking",
    "ai.response": "speaking",
    "task.started": "executing",
    "task.progress": "executing",
    "task.failed": "error",
    "action.failed": "error",
    "system.warning": "warning",
    "cognitive.response": "speaking",
    "cognitive.clarification": "listening",
    // Der Orb wartet sichtbar auf den Benutzer, wenn eine Freigabe oder
    // Bestätigung aussteht - das ist WAITING, nicht Zuhören.
    "cognitive.confirmation_required": "waiting",
    "security.consent.requested": "waiting",
    "security.consent.revoked": "warning",
    "tts.started": "speaking",
    // Nach der Antwort eine ruhige Bestätigung (Erfolgsimpuls), dann kehrt
    // der Orb von selbst in den Ruhezustand zurück (siehe onChange).
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
  }
}

bootstrap().catch((error: unknown) => {
  // Ein Fehler beim Start darf nicht stillschweigend passieren: Er wird
  // protokolliert und ist über die Entwicklerwerkzeuge einsehbar.
  console.error("[AI-Orb] Die Oberfläche konnte nicht gestartet werden:", error);
});
