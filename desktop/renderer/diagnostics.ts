import type { BackendClient } from "./api";
import type { AnimationLoop } from "./animation";

type Status = Record<string, any>;

export class DiagnosticsPanel {
  private readonly panel: HTMLElement;
  private readonly content: HTMLElement;
  private timer: number | undefined;

  constructor(private readonly backend: BackendClient, private readonly loop: AnimationLoop) {
    this.panel = document.getElementById("diagnostics") as HTMLElement;
    this.content = document.getElementById("diagnostics-content") as HTMLElement;
    document.getElementById("diagnostics-close")?.addEventListener("click", () => this.hide());
  }

  public toggle(): void {
    if (this.panel.hidden) this.show(); else this.hide();
  }

  public show(): void {
    this.panel.hidden = false;
    window.aiOrb.setIgnoreMouseEvents(false);
    void this.refresh();
    window.clearInterval(this.timer);
    this.timer = window.setInterval(() => void this.refresh(), 2000);
  }

  public hide(): void {
    this.panel.hidden = true;
    window.clearInterval(this.timer);
    this.timer = undefined;
  }

  private row(label: string, value: string, ok = true): string {
    const safe = (text: string) => text.replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c] ?? c));
    return `<span class="diagnostics__label">${safe(label)}</span><span class="diagnostics__value ${ok ? "diagnostics__ok" : "diagnostics__warn"}">${safe(value)}</span>`;
  }

  private async refresh(): Promise<void> {
    const status = await this.backend.get<Status>("/status");
    if (status === null) {
      this.content.innerHTML = this.row("Backend", "nicht erreichbar", false);
      return;
    }
    const providers = status.providers ?? {};
    const voice = status.voice ?? {};
    const tts = voice.tts ?? {};
    const tools = status.tools ?? {};
    const tasks = Array.isArray(status.background_tasks) ? status.background_tasks : [];
    this.content.innerHTML = [
      this.row(
        "Betriebsmodus",
        providers.offline
          ? "Offline · ausdrücklich gewählt"
          : providers.temporary_local_fallback
            ? "Automatik · vorübergehend lokaler Ersatz"
            : "Automatik · Cloud bevorzugt",
        Boolean(providers.active),
      ),
      this.row("Provider", `${providers.active ?? "–"}${providers.active_model ? ` · ${providers.active_model}` : ""}`, Boolean(providers.active)),
      this.row(
        "Stimme",
        tts.active_engine === "chatterbox"
          ? `lokaler ElevenLabs-Klon${tts.clone_model ? ` · ${tts.clone_model}` : ""}`
          : tts.active_engine === "elevenlabs"
            ? "ElevenLabs · Original"
            : tts.active_engine
              ? `${tts.active_engine} · Ersatzstimme`
              : "noch nicht verwendet",
        !providers.offline || tts.active_engine === "chatterbox" || !tts.active_engine,
      ),
      this.row("Mikrofon", voice.running ? `aktiv · ${voice.state}` : (voice.enabled ? "bereit" : "deaktiviert"), !voice.last_error),
      this.row("Hintergrundaufgaben", String(tasks.length), true),
      this.row("Werkzeuge", `${tools.total_calls ?? 0} Aufrufe · ${tools.failed_calls ?? 0} Fehler`, (tools.failed_calls ?? 0) === 0),
      this.row("Renderer", `${this.loop.fps.toFixed(0)} FPS · Qualität ${this.loop.quality}`, this.loop.fps >= 24),
      this.row("Laufzeit", `${Math.floor((status.uptime_seconds ?? 0) / 60)} min`, true),
    ].join("");
  }
}
