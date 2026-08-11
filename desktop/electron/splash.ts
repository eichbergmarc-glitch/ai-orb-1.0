/**
 * splash.ts – der Ladebildschirm (Phase 45).
 *
 * Ein Start dauert je nach Rechner und Sprachmodellen einige Sekunden. In
 * dieser Zeit zeigt der Ladebildschirm, woran gerade gearbeitet wird –
 * genau in der Form, die die Vorgabe skizziert:
 *
 *     AI-Orb wird gestartet...
 *
 *     ✓ System
 *     ✓ Backend
 *     ✓ Claude
 *     ...
 *     AI-Orb bereit
 *
 * Der Nutzen ist nicht Zierde. Ein Programm, das nach dem Klick fünfzehn
 * Sekunden nichts tut, wirkt kaputt; eines, das mitzählt, wirkt beschäftigt.
 * Und geht etwas schief, steht der Grund hier, bevor irgendein Fenster
 * erscheint, das ihn verbergen könnte.
 *
 * Das Fenster ist rahmenlos, transparent und immer im Vordergrund – wie der
 * Orb selbst, damit der Übergang nicht bricht.
 */

import { BrowserWindow } from "electron";

/** Ein Schritt, wie er im Ladebildschirm erscheint. */
export interface SplashStep {
  /** Kurzname, unter dem der Schritt angesprochen wird. */
  key: string;
  /** Was angezeigt wird. */
  label: string;
}

/** Die Schritte in der Reihenfolge der Vorgabe. */
export const SPLASH_STEPS: SplashStep[] = [
  { key: "system", label: "System" },
  { key: "backend", label: "Backend" },
  { key: "claude", label: "Claude" },
  { key: "offline", label: "Offline-KI" },
  { key: "voice", label: "Voice" },
  { key: "memory", label: "Memory" },
  { key: "desktop", label: "Desktop" },
  { key: "presence", label: "Human Experience" },
];

/**
 * Der Ladebildschirm.
 *
 * Bewusst als eigenständige Seite ohne Datei auf der Festplatte: Sie wird
 * als Data-URL geladen. Damit gibt es eine Sache weniger, die beim
 * Paketieren vergessen werden kann – und der Ladebildschirm erscheint
 * garantiert, auch wenn sonst etwas fehlt.
 */
export class SplashScreen {
  private window: BrowserWindow | null = null;
  private readonly states = new Map<string, "wartend" | "laeuft" | "ok" | "fehler">();
  private message = "AI-Orb wird gestartet...";
  private failed = false;

  constructor() {
    for (const step of SPLASH_STEPS) {
      this.states.set(step.key, "wartend");
    }
  }

  /** Zeigt den Ladebildschirm. */
  public show(): void {
    if (this.window !== null) {
      return;
    }

    this.window = new BrowserWindow({
      width: 380,
      height: 320,
      frame: false,
      transparent: true,
      alwaysOnTop: true,
      skipTaskbar: false,
      resizable: false,
      center: true,
      show: false,
      hasShadow: false,
      title: "AI-Orb",
      webPreferences: { nodeIntegration: false, contextIsolation: true },
    });

    this.window.setMenu(null);
    void this.render();
    this.window.once("ready-to-show", () => this.window?.show());
  }

  /** Meldet, dass ein Schritt begonnen hat. */
  public begin(key: string): void {
    this.states.set(key, "laeuft");
    void this.render();
  }

  /**
   * Meldet, dass ein Schritt fertig ist.
   *
   * @param key Der Schritt.
   * @param ok Ob er geklappt hat.
   */
  public complete(key: string, ok = true): void {
    this.states.set(key, ok ? "ok" : "fehler");
    void this.render();
  }

  /**
   * Zeigt einen Fehler und hält den Ladebildschirm offen.
   *
   * Der Text wird in voller Länge angezeigt: Wenn etwas schiefgeht, ist
   * genau das der Moment, in dem der Benutzer die Einzelheiten braucht.
   */
  public fail(message: string): void {
    this.failed = true;
    this.message = message;
    void this.render();
  }

  /** Meldet die Betriebsbereitschaft. */
  public ready(): void {
    this.message = "AI-Orb bereit";
    void this.render();
  }

  /** Schließt den Ladebildschirm. */
  public close(): void {
    if (this.window !== null && !this.window.isDestroyed()) {
      this.window.close();
    }
    this.window = null;
  }

  /** Ob der Ladebildschirm noch offen ist. */
  public get isOpen(): boolean {
    return this.window !== null && !this.window.isDestroyed();
  }

  /** Zeichnet den aktuellen Stand. */
  private async render(): Promise<void> {
    if (this.window === null || this.window.isDestroyed()) {
      return;
    }
    await this.window.loadURL(
      "data:text/html;charset=utf-8," + encodeURIComponent(this.buildHtml())
    );
  }

  /** Baut die Seite. */
  private buildHtml(): string {
    const rows = SPLASH_STEPS.map((step) => {
      const state = this.states.get(step.key) ?? "wartend";
      const marker =
        state === "ok" ? "✓" : state === "fehler" ? "!" : state === "laeuft" ? "·" : " ";
      return `<li class="${state}"><span class="marker">${marker}</span>${step.label}</li>`;
    }).join("");

    const messageClass = this.failed ? "message error" : "message";
    const escaped = this.message
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/\n/g, "<br>");

    return `<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<title>AI-Orb</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: "Segoe UI", system-ui, sans-serif;
    background: rgba(14, 20, 32, 0.94);
    color: #dce8f7;
    border-radius: 14px;
    padding: 26px 30px;
    height: 100vh;
    overflow: hidden;
    -webkit-user-select: none;
    -webkit-app-region: drag;
  }
  h1 { font-size: 15px; font-weight: 600; letter-spacing: 0.3px; margin-bottom: 4px; }
  .subtitle { font-size: 11px; color: #7e94ae; margin-bottom: 18px; }
  ul { list-style: none; font-size: 12.5px; line-height: 1.95; }
  li { display: flex; align-items: baseline; color: #55697f; transition: color 0.2s; }
  li .marker { display: inline-block; width: 18px; font-weight: 700; }
  li.laeuft { color: #9fc4e8; }
  li.ok { color: #6fd6a2; }
  li.ok .marker { color: #6fd6a2; }
  li.fehler { color: #f0b05a; }
  li.fehler .marker { color: #f0b05a; }
  .message {
    margin-top: 16px; padding-top: 14px;
    border-top: 1px solid rgba(255, 255, 255, 0.09);
    font-size: 11.5px; color: #93a9c2; line-height: 1.55;
    max-height: 90px; overflow-y: auto;
  }
  .message.error { color: #f2a0a0; }
</style>
</head>
<body>
  <h1>AI-Orb</h1>
  <div class="subtitle">wird gestartet…</div>
  <ul>${rows}</ul>
  <div class="${messageClass}">${escaped}</div>
</body>
</html>`;
  }
}
