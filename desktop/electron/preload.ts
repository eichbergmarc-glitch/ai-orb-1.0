/**
 * preload.ts – Die abgesicherte Brücke zwischen Haupt- und Renderer-Prozess.
 *
 * Läuft in einem isolierten Kontext (`contextIsolation: true`,
 * `nodeIntegration: false`) und stellt der Orb-Oberfläche ausschließlich
 * eine minimale, ausdrücklich freigegebene API zur Verfügung.
 *
 * Der Renderer erhält keinerlei Zugriff auf Node.js, das Dateisystem oder
 * Electron-Interna – nur auf die hier über `contextBridge` freigegebenen
 * Funktionen.
 */

import { contextBridge, ipcRenderer } from "electron";

/** Ein Ereignis, das vom Backend über den Hauptprozess weitergereicht wird. */
export interface BackendEvent {
  event: string;
  payload: Record<string, unknown>;
}

const api = {
  /**
   * Liefert die geladene `config.yaml` als Objekt.
   *
   * Der Renderer liest dadurch dieselben Einstellungen wie das Backend,
   * ohne selbst auf das Dateisystem zugreifen zu müssen.
   */
  getConfig: (): Promise<Record<string, unknown>> => ipcRenderer.invoke("config:get"),

  /** Liefert die Basis-URL des lokalen Backends. */
  getBackendUrl: (): Promise<string> => ipcRenderer.invoke("backend:url"),

  /**
   * Registriert einen Rückruf für Ereignisse, die der Hauptprozess an die
   * Oberfläche weiterreicht (z. B. Zustandsanforderungen der Smart Desktop
   * Engine).
   */
  onBackendEvent: (callback: (event: BackendEvent) => void): void => {
    ipcRenderer.on("backend:event", (_ipcEvent, data: BackendEvent) => {
      callback(data);
    });
  },

  /**
   * Registriert einen Rückruf für Positionsänderungen des Orb innerhalb
   * des Fensters.
   *
   * Der Orb bewegt sich über die Grafikkarte innerhalb eines größeren,
   * unsichtbaren Fensters. Das ist flüssig – im Gegensatz zum Verschieben
   * eines transparenten Fensters, das unter Windows sichtbar ruckelt.
   *
   * @param callback Erhält den Zielversatz in Pixeln, gemessen von der
   *   Fenstermitte, sowie die Angabe, ob der Versatz ohne Animation
   *   übernommen werden soll (nötig, wenn zugleich das Fenster
   *   umgesetzt wurde – der Orb bleibt dadurch optisch stehen).
   */
  onOrbOffset: (
    callback: (offset: { x: number; y: number; immediate: boolean }) => void
  ): void => {
    ipcRenderer.on("orb:offset", (_ipcEvent, data) => {
      callback(data as { x: number; y: number; immediate: boolean });
    });
  },

  /**
   * Meldet dem Hauptprozess, wo sich der Orb innerhalb des Fensters
   * gerade befindet. Nötig, damit die Platzierungslogik mit der echten
   * Bildschirmposition rechnet und nicht mit der Fenstermitte.
   */
  reportOrbOffset: (x: number, y: number): void => {
    ipcRenderer.send("orb:offset-report", { x, y });
  },

  /** Globale Mausposition, auch wenn der Zeiger ausserhalb des Orb-Fensters liegt. */
  onGlobalPointer: (callback: (position: { x: number; y: number }) => void): void => {
    ipcRenderer.on("pointer:global", (_event, data) => {
      callback(data as { x: number; y: number });
    });
  },

  /** Fuehrt eine Aktion des sichtbaren Ringmenues im Hauptprozess aus. */
  performMenuAction: (action: string): void => {
    ipcRenderer.send("orb:menu-action", { action });
  },

  /**
   * Verschiebt das Fenster um ein Delta.
   *
   * Wird während einer Ziehbewegung fortlaufend aufgerufen.
   */
  moveWindowBy: (dx: number, dy: number): void => {
    ipcRenderer.send("window:move-by", { dx, dy });
  },

  /**
   * Speichert die aktuelle Fensterposition.
   *
   * @param manual `true`, wenn der Benutzer den Orb selbst gezogen hat –
   *   solche Positionen erhalten im Lernsystem ein höheres Gewicht.
   */
  commitWindowPosition: (manual: boolean): void => {
    ipcRenderer.send("window:commit-position", { manual });
  },

  /** Zeigt das native Kontextmenü an der Zeigerposition. */
  showContextMenu: (): void => {
    ipcRenderer.send("orb:context-menu");
  },

  /** Löst die in `config.yaml` festgelegte Doppelklick-Aktion aus. */
  triggerDoubleClickAction: (): void => {
    ipcRenderer.send("orb:double-click");
  },

  /**
   * Schaltet um, ob das Fenster Mausereignisse annimmt.
   *
   * Außerhalb des sichtbaren Orb bleibt das Fenster durchlässig, damit der
   * Benutzer ungehindert auf darunterliegende Programme klicken kann.
   */
  setIgnoreMouseEvents: (ignore: boolean): void => {
    ipcRenderer.send("window:ignore-mouse", { ignore });
  },

  /** Haelt den Orb waehrend Menue, Chat oder Hover an seiner Position. */
  setInteractionLock: (active: boolean, reason: string): void => {
    ipcRenderer.send("window:interaction-lock", { active, reason });
  },

  /** Gibt dem Chat voruebergehend Tastaturfokus und gibt ihn danach frei. */
  setChatFocus: (active: boolean): void => {
    ipcRenderer.send("window:chat-focus", { active });
  },

  /**
   * Meldet dem Hauptprozess, ob der Orb gerade spricht.
   *
   * Nur während des Sprechens fängt der Hauptprozess die Unterbrechungs-
   * Taste ab. Ausserhalb bleibt sie dem Benutzer für alles andere.
   */
  setSpeaking: (speaking: boolean): void => {
    ipcRenderer.send("voice:speaking", { speaking });
  },

  /** Aktualisiert die separate Lehrtafel einer laufenden Vorlesung. */
  showLectureVisual: (payload: {
    path?: string;
    title?: string;
    topic?: string;
    caption?: string;
    kind?: string;
    // Ohne dieses Feld kam die Darstellungsart nie im Fenster an. Das
    // Backend schickte sie seit jeher mit; auf dem Weg durch Renderer und
    // Bruecke fiel sie heraus, und die Tafel zeigte deshalb IMMER die
    // schlichte Uebersicht - auch dort, wo eine fachliche Gliederung
    // vorlag.
    layout?: string;
    summary?: Array<{ title?: string; text?: string }>;
    generation?: number;
  }): void => {
    ipcRenderer.send("lecture-visual:show", payload);
  },
};

const flipperCenterApi = {
  status: () => ipcRenderer.invoke("flipper:status"),
  openQFlipper: () => ipcRenderer.invoke("flipper:open-qflipper"),
  chooseApp: () => ipcRenderer.invoke("flipper:choose-app"),
};

/** Der Typ der freigegebenen Schnittstelle. */
export type AiOrbApi = typeof api;

contextBridge.exposeInMainWorld("aiOrb", api);
contextBridge.exposeInMainWorld("flipperCenter", flipperCenterApi);
