/**
 * consent.ts – zeigt Zustimmungsfragen des Kerns und beantwortet sie.
 *
 * ## Warum es diese Datei braucht
 *
 * Die Sicherheitsschicht des Kerns fragt, bevor etwas geschieht, das über
 * das Antworten hinausgeht. Sie veröffentlicht die Frage, wartet auf eine
 * Antwort und wertet Schweigen als Nein – das ist so gewollt und richtig.
 *
 * Nur hörte bisher niemand zu. Die Frage ging in den Ereignisbus, der
 * Kern wartete, die Zeit lief ab, und das Ergebnis war ein Nein, das nie
 * jemand ausgesprochen hatte. Im Protokoll stand:
 *
 *     Zustimmung angefragt: voice möchte 'microphone' –
 *     Dauerhaft auf das Weckwort 'Hallo Orb' hören.
 *
 * Danach nichts mehr. Der Orb reagierte nicht auf das Weckwort, und es sah
 * aus, als sei die Spracherkennung kaputt. Sie war es nicht: Sie hatte um
 * Erlaubnis gebeten und keine bekommen.
 *
 * Diese Datei schließt die Lücke. Sie fragt den Kern regelmäßig nach
 * offenen Fragen und stellt jede davon als Fenster dar.
 *
 * ## Warum ein Systemfenster und keine eigene Oberfläche im Orb
 *
 * Der Orb ist klein, durchscheinend, ohne Fokus und weicht der Maus aus.
 * Eine Frage, auf die es ankommt, hat dort nichts zu suchen – man würde
 * sie übersehen oder aus Versehen wegklicken. Ein gewöhnliches
 * Windows-Fenster erzwingt eine Entscheidung, sieht aus wie das, was es
 * ist, und lässt sich nicht übersehen.
 */

import { BrowserWindow, dialog } from "electron";
import * as http from "http";

/** Eine offene Frage des Kerns. */
interface PendingRequest {
  request_id: string;
  actor: string;
  permission: string;
  detail: string;
  risk: string;
  remembering_allowed: boolean;
}

/** Abstand der Abfragen. */
const POLL_INTERVAL_MS = 1200;

/** Klartext für die Risikostufen. */
const RISK_LABELS: Record<string, string> = {
  safe: "unbedenklich",
  moderate: "mit Bedacht",
  high: "weitreichend",
  critical: "schwerwiegend",
};

/**
 * Fragt den Kern nach offenen Zustimmungsfragen und beantwortet sie.
 */
export class ConsentBridge {
  private timer: NodeJS.Timeout | null = null;

  /** Fragen, für die bereits ein Fenster offen steht. */
  private readonly inFlight = new Set<string>();

  constructor(
    private readonly host: string,
    private readonly port: number,
    private readonly parent: () => BrowserWindow | null
  ) {}

  /** Beginnt zu lauschen. */
  public start(): void {
    if (this.timer !== null) {
      return;
    }
    this.timer = setInterval(() => {
      void this.poll();
    }, POLL_INTERVAL_MS);
  }

  /** Hört auf zu lauschen. */
  public stop(): void {
    if (this.timer !== null) {
      clearInterval(this.timer);
      this.timer = null;
    }
  }

  /** Holt die offenen Fragen und stellt neue dar. */
  private async poll(): Promise<void> {
    const pending = await this.fetchPending();

    for (const request of pending) {
      if (this.inFlight.has(request.request_id)) {
        continue;
      }
      this.inFlight.add(request.request_id);
      void this.ask(request);
    }
  }

  /** Stellt eine Frage und schickt die Antwort zurück. */
  private async ask(request: PendingRequest): Promise<void> {
    const buttons = request.remembering_allowed
      ? ["Erlauben", "Immer erlauben", "Ablehnen"]
      : ["Erlauben", "Ablehnen"];

    const denyIndex = buttons.length - 1;
    const riskLabel = RISK_LABELS[request.risk] ?? request.risk;

    const parent = this.parent();

    try {
      const options = {
        type: "question" as const,
        buttons,
        // Voreingestellt ist das Ablehnen. Wer aus Gewohnheit die
        // Eingabetaste drückt, soll nichts erlauben, was er nicht gelesen
        // hat.
        defaultId: denyIndex,
        cancelId: denyIndex,
        noLink: true,
        title: "AI-Orb fragt um Erlaubnis",
        message: `${request.actor} möchte: ${request.permission}`,
        detail:
          `${request.detail}\n\n` +
          `Einstufung: ${riskLabel}\n\n` +
          (request.remembering_allowed
            ? "„Immer erlauben“ merkt die Antwort. Widerrufen kannst du sie " +
              "jederzeit über das Kontextmenü des Orb."
            : "Diese Erlaubnis wird nicht gemerkt und jedes Mal neu erfragt."),
      };

      const result =
        parent !== null && !parent.isDestroyed()
          ? await dialog.showMessageBox(parent, options)
          : await dialog.showMessageBox(options);

      const granted = result.response !== denyIndex;
      const remember = request.remembering_allowed && result.response === 1;

      await this.resolve(request.request_id, granted, remember);
    } catch (error) {
      // Konnte die Frage nicht gestellt werden, wird sie abgelehnt.
      // Nicht antworten wäre bequemer, führte aber nach Ablauf der Frist
      // zum selben Ergebnis – nur später und ohne Begründung.
      console.error("[AI-Orb] Zustimmungsfrage fehlgeschlagen:", error);
      await this.resolve(request.request_id, false, false);
    } finally {
      this.inFlight.delete(request.request_id);
    }
  }

  /** Holt die Liste der offenen Fragen. */
  private fetchPending(): Promise<PendingRequest[]> {
    return new Promise((resolve) => {
      const request = http.get(
        { host: this.host, port: this.port, path: "/security/consent", timeout: 2000 },
        (response) => {
          let body = "";
          response.on("data", (chunk) => {
            body += chunk;
          });
          response.on("end", () => {
            try {
              const parsed = JSON.parse(body) as { pending?: PendingRequest[] };
              resolve(Array.isArray(parsed.pending) ? parsed.pending : []);
            } catch {
              resolve([]);
            }
          });
        }
      );

      // Ein nicht erreichbarer Kern ist hier kein Fehler, sondern der
      // Normalfall vor dem Start und nach dem Beenden.
      request.on("error", () => resolve([]));
      request.on("timeout", () => {
        request.destroy();
        resolve([]);
      });
    });
  }

  /** Schickt die Antwort an den Kern. */
  private resolve(requestId: string, granted: boolean, remember: boolean): Promise<void> {
    return new Promise((resolve) => {
      const payload = JSON.stringify({
        request_id: requestId,
        granted,
        remember,
        reason: granted ? "Vom Benutzer erlaubt." : "Vom Benutzer abgelehnt.",
      });

      const request = http.request(
        {
          host: this.host,
          port: this.port,
          path: "/security/consent",
          method: "POST",
          timeout: 3000,
          headers: {
            "Content-Type": "application/json",
            "Content-Length": Buffer.byteLength(payload),
          },
        },
        (response) => {
          response.resume();
          response.on("end", () => resolve());
        }
      );

      request.on("error", () => resolve());
      request.on("timeout", () => {
        request.destroy();
        resolve();
      });

      request.write(payload);
      request.end();
    });
  }
}
