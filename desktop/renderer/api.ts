/**
 * api.ts – Die Verbindung des Orb zum Backend.
 *
 * Der Renderer spricht niemals direkt mit dem Dateisystem oder dem
 * Betriebssystem. Alle Anfragen laufen über den lokalen HTTP-Server des
 * Backends; Ereignisse kommen über einen Server-Sent-Events-Kanal zurück.
 *
 * Die Verbindung ist ausfallsicher: Bricht sie ab, wird automatisch erneut
 * verbunden, und der Orb wechselt sichtbar in den Fehlerzustand.
 */

/** Ein vom Backend gesendetes Ereignis. */
export interface BackendEvent {
  event: string;
  payload: Record<string, unknown>;
}

/** Die Antwort des Cognitive Core auf eine Eingabe. */
export interface AskResponse {
  response: string;
  intent: string;
  used_llm: boolean;
  provider: string | null;
  model: string | null;
  confidence: string;
  strategy: string;
  requires_confirmation: boolean;
  question: string;
  notices: string[];
  engines: string[];
  project_id: string | null;
  duration_seconds: number;
}

/**
 * Client für die lokale Backend-API.
 */
export class BackendClient {
  private baseUrl: string;
  private eventSource: EventSource | null = null;
  private listeners: ((event: BackendEvent) => void)[] = [];
  private connectionListeners: ((connected: boolean) => void)[] = [];
  private reconnectDelay = 1000;
  private connected = false;

  /**
   * @param baseUrl Basis-URL des Backends, z. B. `http://127.0.0.1:8756`.
   */
  constructor(baseUrl: string) {
    this.baseUrl = baseUrl.replace(/\/$/, "");
  }

  /** Ob die Ereignisverbindung derzeit steht. */
  public get isConnected(): boolean {
    return this.connected;
  }

  /**
   * Baut die Ereignisverbindung auf und hält sie offen.
   *
   * @param eventsPath Pfad des Ereigniskanals (Standard `/events`).
   */
  public connect(eventsPath = "/events"): void {
    this.close();

    const source = new EventSource(`${this.baseUrl}${eventsPath}`);
    this.eventSource = source;

    source.onopen = () => {
      this.connected = true;
      this.reconnectDelay = 1000;
      this.notifyConnection(true);
    };

    source.onmessage = (message: MessageEvent<string>) => {
      try {
        const parsed = JSON.parse(message.data) as BackendEvent;
        for (const listener of this.listeners) {
          listener(parsed);
        }
      } catch {
        // Fehlerhafte Nachrichten werden verworfen, ohne die Verbindung
        // zu gefährden.
      }
    };

    source.onerror = () => {
      this.connected = false;
      this.notifyConnection(false);
      source.close();
      this.eventSource = null;
      // Wartezeit verdoppeln, höchstens 15 Sekunden.
      window.setTimeout(() => this.connect(eventsPath), this.reconnectDelay);
      this.reconnectDelay = Math.min(15000, this.reconnectDelay * 2);
    };
  }

  /** Schließt die Ereignisverbindung. */
  public close(): void {
    this.eventSource?.close();
    this.eventSource = null;
    this.connected = false;
  }

  /** Registriert einen Callback für Backend-Ereignisse. */
  public onEvent(listener: (event: BackendEvent) => void): void {
    this.listeners.push(listener);
  }

  /** Registriert einen Callback für Verbindungsänderungen. */
  public onConnectionChange(listener: (connected: boolean) => void): void {
    this.connectionListeners.push(listener);
  }

  private notifyConnection(connected: boolean): void {
    for (const listener of this.connectionListeners) {
      listener(connected);
    }
  }

  /**
   * Führt eine GET-Anfrage aus.
   *
   * @param path Endpunktpfad.
   * @returns Die Antwort als Objekt, oder `null` bei einem Fehler.
   */
  public async get<T = Record<string, unknown>>(path: string): Promise<T | null> {
    try {
      const response = await fetch(`${this.baseUrl}${path}`);
      if (!response.ok) {
        return null;
      }
      return (await response.json()) as T;
    } catch {
      return null;
    }
  }

  /**
   * Führt eine POST-Anfrage aus.
   *
   * @param path Endpunktpfad.
   * @param body Die zu sendenden Daten.
   * @returns Die Antwort als Objekt, oder `null` bei einem Fehler.
   */
  public async post<T = Record<string, unknown>>(
    path: string,
    body: Record<string, unknown> = {}
  ): Promise<T | null> {
    try {
      const response = await fetch(`${this.baseUrl}${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!response.ok) {
        return null;
      }
      return (await response.json()) as T;
    } catch {
      return null;
    }
  }

  /** Sendet eine Benutzereingabe an das Cognitive Core. */
  public async ask(text: string): Promise<AskResponse | null> {
    return this.post<AskResponse>("/ask", { text });
  }

  /** Meldet einen Zustandswechsel des Orb an das Backend. */
  public async reportState(state: string): Promise<void> {
    await this.post("/orb/state", { state });
  }

  /** Meldet eine Benutzerinteraktion an das Backend. */
  public async reportInteraction(kind: string, details: Record<string, unknown> = {}): Promise<void> {
    await this.post("/orb/interaction", { kind, ...details });
  }

  /** Meldet eine Orb-Position an das Lernsystem. */
  public async reportPosition(position: {
    x: number;
    y: number;
    screen_width: number;
    screen_height: number;
    monitor: number;
    manual: boolean;
    program?: string;
  }): Promise<void> {
    await this.post("/behavior/position", position as unknown as Record<string, unknown>);
  }

  /** Fragt die Bewertung einer Kandidatenposition ab. */
  public async positionScore(position: {
    x: number;
    y: number;
    screen_width: number;
    screen_height: number;
    monitor: number;
  }): Promise<number> {
    const result = await this.post<{ score: number }>(
      "/behavior/score",
      position as unknown as Record<string, unknown>
    );
    return result?.score ?? 0;
  }
}
