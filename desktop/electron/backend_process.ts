/**
 * backend_process.ts – startet und überwacht den Python-Kern (Phasen 45, 47, 58).
 *
 * In der installierten Fassung gibt es keine PowerShell-Skripte mehr, die
 * jemand anklickt: Electron ist das Programm, das Windows startet, und es
 * bringt den Python-Kern selbst hoch.
 *
 * Der Python-Interpreter wird in dieser Reihenfolge gesucht:
 *
 *   1. die mitgelieferte Runtime unter `runtime/python/`,
 *   2. eine Projektumgebung unter `.venv/`,
 *   3. ein System-Python.
 *
 * Der erste Fall ist der Normalfall nach der Installation und der Grund,
 * warum der Benutzer nie „python is not recognized" zu sehen bekommt. Die
 * beiden anderen sind für die Entwicklung.
 *
 * Das Fenster des Kindprozesses bleibt unsichtbar. Ein Assistent, der beim
 * Start ein schwarzes Konsolenfenster aufblitzen lässt, wirkt wie ein
 * Bastelprojekt – und die Vorgabe verlangt ausdrücklich, dass der Launcher
 * keine sichtbare Kommandozeile benötigt.
 */

import { ChildProcess, spawn } from "child_process";
import { existsSync } from "fs";
import * as http from "http";
import * as path from "path";

/** Wie der Kern gefunden und gestartet wurde. */
export interface BackendLaunchInfo {
  /** Der verwendete Python-Interpreter. */
  executable: string;
  /** Woher er stammt. */
  origin: "mitgeliefert" | "projektumgebung" | "system";
  /** Der Projektordner, aus dem gestartet wurde. */
  workingDirectory: string;
}

/** Ein Fortschrittsschritt, wie ihn der Ladebildschirm anzeigt. */
export interface BackendProgress {
  step: string;
  detail: string;
  ok: boolean;
}

/** Wie lange auf die Betriebsbereitschaft gewartet wird. */
const READY_TIMEOUT_MS = 180_000;

/** Abstand der Bereitschaftsprüfungen. */
const POLL_INTERVAL_MS = 400;

/**
 * Sucht den Python-Interpreter.
 *
 * @param appRoot Der Ordner, in dem AI-Orb installiert ist.
 * @returns Der Interpreter samt Herkunft, oder `null`.
 */
export function findPython(appRoot: string): BackendLaunchInfo | null {
  const candidates: Array<{ file: string; origin: BackendLaunchInfo["origin"] }> = [
    // Die mitgelieferte Runtime. Nach der Installation der Normalfall.
    { file: path.join(appRoot, "runtime", "python", "python.exe"), origin: "mitgeliefert" },
    { file: path.join(appRoot, "runtime", "python", "bin", "python3"), origin: "mitgeliefert" },
    // Eine Projektumgebung – beim Entwickeln.
    { file: path.join(appRoot, ".venv", "Scripts", "python.exe"), origin: "projektumgebung" },
    { file: path.join(appRoot, ".venv", "bin", "python"), origin: "projektumgebung" },
  ];

  for (const candidate of candidates) {
    if (existsSync(candidate.file)) {
      return { executable: candidate.file, origin: candidate.origin, workingDirectory: appRoot };
    }
  }

  // Letzter Ausweg: ein Python aus dem PATH. Ob es existiert, zeigt sich
  // erst beim Starten – deshalb wird hier nichts versprochen.
  return {
    executable: process.platform === "win32" ? "python.exe" : "python3",
    origin: "system",
    workingDirectory: appRoot,
  };
}

/**
 * Startet den Python-Kern und wartet, bis er antwortet.
 */
export class BackendProcess {
  private child: ChildProcess | null = null;
  private readonly appRoot: string;
  private readonly host: string;
  private readonly port: number;
  private launchInfo: BackendLaunchInfo | null = null;
  private lastError = "";

  /**
   * Die letzten Zeilen der Fehlerausgabe des Kerns.
   *
   * Der Grund für diese Liste: Stirbt der Kern, meldete sich bisher der
   * `exit`-Behandler mit "Der Kern wurde unerwartet beendet (Code 1)" –
   * und überschrieb damit genau die Zeile, die den Grund nannte. Der
   * Benutzer sah, *dass* etwas schiefging, nie *was*. Eine Feststellung
   * ohne Erkenntnis.
   */
  private readonly errorLines: string[] = [];
  private stopping = false;
  private restarts = 0;

  /**
   * @param appRoot Installationsordner von AI-Orb.
   * @param host Adresse, auf der der Kern lauscht.
   * @param port Port des Kerns.
   */
  constructor(appRoot: string, host: string, port: number) {
    this.appRoot = appRoot;
    this.host = host;
    this.port = port;
  }

  /** Wie der Kern gestartet wurde. */
  public get info(): BackendLaunchInfo | null {
    return this.launchInfo;
  }

  /** Die zuletzt aufgetretene Meldung. */
  public get error(): string {
    return this.lastError;
  }

  /** Ob der Prozess läuft. */
  public get isRunning(): boolean {
    return this.child !== null && this.child.exitCode === null && !this.child.killed;
  }

  /**
   * Startet den Kern.
   *
   * @param onOutput Wird für jede Ausgabezeile aufgerufen – für das Protokoll.
   * @returns Ob der Prozess gestartet werden konnte.
   */
  public start(onOutput?: (line: string, isError: boolean) => void): boolean {
    if (this.isRunning) {
      return true;
    }

    const info = findPython(this.appRoot);
    if (info === null) {
      this.lastError =
        "Es wurde kein Python gefunden. Die Installation ist unvollständig – " +
        "eine Neuinstallation behebt das.";
      return false;
    }
    this.launchInfo = info;

    try {
      this.child = spawn(info.executable, ["-m", "backend.main", "--launcher"], {
        cwd: info.workingDirectory,
        // Kein Fenster: Der Benutzer soll keine Kommandozeile sehen.
        windowsHide: true,
        env: {
          ...process.env,
          PYTHONUNBUFFERED: "1",
          // Damit Umlaute in den Meldungen nicht zerfallen.
          PYTHONIOENCODING: "utf-8",
          // Der Programmordner muss im Suchpfad stehen, sonst findet
          // "-m backend.main" sein Paket nicht.
          //
          // Bei der mitgelieferten Runtime wird das hier ignoriert – eine
          // embeddable-Fassung mit ._pth-Datei laeuft isoliert und liest
          // PYTHONPATH nicht. Dort sorgt der Eintrag "..\.." in der
          // ._pth-Datei dafuer. Diese Zeile gilt den beiden anderen
          // Faellen: einer Projektumgebung und einem System-Python.
          PYTHONPATH: info.workingDirectory,
        },
        stdio: ["ignore", "pipe", "pipe"],
      });
    } catch (error) {
      this.lastError = `Der Kern ließ sich nicht starten: ${String(error)}`;
      this.child = null;
      return false;
    }

    this.child.stdout?.on("data", (chunk: Buffer) => {
      for (const line of chunk.toString("utf-8").split("\n")) {
        if (line.trim()) {
          onOutput?.(line.trimEnd(), false);
        }
      }
    });

    this.child.stderr?.on("data", (chunk: Buffer) => {
      for (const line of chunk.toString("utf-8").split("\n")) {
        if (line.trim()) {
          const text = line.trimEnd();
          this.lastError = text;

          // Python schreibt auch Protokollzeilen auf die Fehlerausgabe.
          // Die sind hier uninteressant; gesucht ist der Absturz.
          if (!/\|\s+(INFO|DEBUG|WARNING)\s+\|/.test(text)) {
            this.errorLines.push(text);
            if (this.errorLines.length > 25) {
              this.errorLines.shift();
            }
          }

          onOutput?.(text, true);
        }
      }
    });

    this.child.on("exit", (code, signal) => {
      if (!this.stopping) {
        // Die gesammelte Fehlerausgabe anhängen, nicht ersetzen. Der
        // Beendigungscode sagt, dass etwas schiefging; erst die letzten
        // Zeilen sagen, was.
        const reason = this.describeExit();
        this.lastError =
          `Der Kern wurde unerwartet beendet (Code ${code ?? "?"}` +
          `${signal ? `, Signal ${signal}` : ""}).` +
          (reason ? `\n\n${reason}` : "");
      }
      this.child = null;
    });

    this.child.on("error", (error) => {
      this.lastError = this.describeSpawnError(error);
      this.child = null;
    });

    return true;
  }

  /**
   * Fasst zusammen, was der Kern zuletzt von sich gegeben hat.
   *
   * Bei einem Python-Absturz ist die letzte Zeile der Rückverfolgung die
   * aussagekräftigste – dort steht der Ausnahmetyp mitsamt Meldung.
   * Darüber stehen die Dateien, in denen es geschah; auch die sind
   * nützlich, aber nur, wenn man weiterlesen will.
   */
  private describeExit(): string {
    if (this.errorLines.length === 0) {
      return "";
    }

    const meaningful = this.errorLines.filter((line) => line.trim().length > 0);
    const last = meaningful[meaningful.length - 1] ?? "";

    // Eine Ausnahmezeile sieht aus wie "ModuleNotFoundError: No module ...".
    const isException = /^[A-Za-z_.]*(Error|Exception|Interrupt)\b/.test(last.trim());

    if (isException) {
      const hint = this.explainCommonFailure(last);
      return hint ? `${last.trim()}\n\n${hint}` : last.trim();
    }

    return meaningful.slice(-6).join("\n");
  }

  /**
   * Übersetzt die häufigsten Abstürze in einen Rat.
   *
   * Ein Ausnahmename ist für den, der ihn geschrieben hat, eine Auskunft.
   * Für alle anderen ist er eine Zeichenfolge.
   */
  private explainCommonFailure(line: string): string {
    if (/ModuleNotFoundError|ImportError/.test(line)) {
      const match = /No module named ['"]([^'"]+)['"]/.exec(line);
      const moduleName = match ? match[1] : "";

      if (moduleName === "backend") {
        return (
          "Der Kern findet sein eigenes Paket nicht. Der Suchpfad der " +
          "mitgelieferten Runtime stimmt nicht – scripts\\prepare-runtime.ps1 " +
          "erneut ausführen behebt das."
        );
      }
      return (
        `Das Paket ${moduleName || "eines der benötigten"} fehlt in der ` +
        "Runtime. scripts\\prepare-runtime.ps1 erneut ausführen."
      );
    }

    if (/UnicodeEncodeError|UnicodeDecodeError/.test(line)) {
      return (
        "Ein Zeichen ließ sich nicht ausgeben. Das liegt an der Codepage " +
        "der Konsole, nicht an AI-Orb."
      );
    }

    if (/PermissionError/.test(line)) {
      return (
        "Ein Zugriff wurde verweigert. Häufig ein Virenschutz oder ein " +
        "Ordner, in den nicht geschrieben werden darf."
      );
    }

    if (/OSError.*(10048|Address already in use)/i.test(line)) {
      return "Port 8756 ist belegt. Läuft AI-Orb bereits?";
    }

    return "";
  }

  /**
   * Übersetzt einen Startfehler in etwas Verständliches.
   *
   * `ENOENT` heißt für Node „Datei nicht gefunden" – für den Benutzer heißt
   * es, dass die Installation unvollständig ist. Diesen Unterschied zu
   * übersetzen ist der ganze Zweck dieser Methode.
   */
  private describeSpawnError(error: NodeJS.ErrnoException): string {
    if (error.code === "ENOENT") {
      return (
        `Python wurde nicht gefunden (${this.launchInfo?.executable ?? "?"}). ` +
        "Die Installation ist unvollständig. Installiere AI-Orb neu."
      );
    }
    if (error.code === "EACCES") {
      return (
        "Der Zugriff auf die Python-Runtime wurde verweigert. Prüfe, ob ein " +
        "Virenschutz sie blockiert."
      );
    }
    return `Der Kern ließ sich nicht starten: ${error.message}`;
  }

  /**
   * Wartet, bis der Kern antwortet.
   *
   * @param onProgress Wird mit dem Ladezustand aufgerufen.
   * @returns Ob der Kern bereit ist.
   */
  public async waitUntilReady(
    onProgress?: (progress: BackendProgress) => void
  ): Promise<boolean> {
    const deadline = Date.now() + READY_TIMEOUT_MS;

    while (Date.now() < deadline) {
      if (!this.isRunning && this.child === null && this.lastError) {
        // Der Prozess ist gestorben – weiter zu warten wäre sinnlos.
        return false;
      }

      const health = await this.fetchHealth();
      if (health !== null) {
        // Ein bereits laufender fremder Kern kann denselben Status liefern.
        // Genau das geschieht bei einem zweiten Orb-Start: Der neue Python-
        // Prozess verliert die Einzelinstanz-Sperre, waehrend die Abfrage
        // noch die alte Instanz auf Port 8756 erreicht. Einen Augenblick
        // warten und dann den EIGENEN Kindprozess pruefen, bevor ein zweites
        // Orb-Fenster geoeffnet wird.
        await new Promise((resolve) => setTimeout(resolve, 250));
        if (!this.isRunning) {
          if (!this.lastError) {
            this.lastError =
              "Ein anderer AI-Orb-Kern läuft bereits. Die zweite Oberfläche " +
              "wird nicht geöffnet.";
          }
          return false;
        }
        const confirmedHealth = await this.fetchHealth();
        if (confirmedHealth === null) {
          await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
          continue;
        }
        onProgress?.({ step: "Backend", detail: `Fassung ${health.version ?? "?"}`, ok: true });
        return true;
      }

      await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
    }

    this.lastError =
      `Der Kern hat nach ${READY_TIMEOUT_MS / 1000} Sekunden nicht geantwortet. ` +
      "Beim ersten Start kann das Laden der Sprachmodelle länger dauern; " +
      "prüfe das Protokoll.";
    return false;
  }

  /** Fragt den Statusendpunkt ab. */
  public fetchHealth(): Promise<{ status?: string; version?: string } | null> {
    return new Promise((resolve) => {
      const request = http.get(
        { host: this.host, port: this.port, path: "/health", timeout: 1500 },
        (response) => {
          let body = "";
          response.on("data", (chunk) => {
            body += chunk;
          });
          response.on("end", () => {
            try {
              resolve(JSON.parse(body));
            } catch {
              resolve(null);
            }
          });
        }
      );

      request.on("error", () => resolve(null));
      request.on("timeout", () => {
        request.destroy();
        resolve(null);
      });
    });
  }

  /**
   * Startet den Kern nach einem Absturz neu.
   *
   * Bewusst begrenzt: Ein Kern, der sich dreimal nicht halten lässt, hat
   * ein Problem, das ein vierter Versuch nicht löst.
   *
   * @returns Ob der Neustart geglückt ist.
   */
  public async restart(
    onOutput?: (line: string, isError: boolean) => void
  ): Promise<boolean> {
    if (this.restarts >= 3) {
      this.lastError =
        "Der Kern ist mehrfach abgestürzt und wurde nicht erneut gestartet. " +
        "Die Ursache steht im Protokoll.";
      return false;
    }

    this.restarts += 1;
    this.stop();

    // Kurz warten, damit der Port freigegeben ist.
    await new Promise((resolve) => setTimeout(resolve, 1500));

    if (!this.start(onOutput)) {
      return false;
    }
    return this.waitUntilReady();
  }

  /** Beendet den Kern geordnet. */
  public stop(): void {
    if (this.child === null) {
      return;
    }

    this.stopping = true;
    try {
      // Erst freundlich fragen.
      this.child.kill("SIGTERM");

      // Wer nach fünf Sekunden nicht gegangen ist, wird getragen.
      const child = this.child;
      setTimeout(() => {
        if (child.exitCode === null && !child.killed) {
          child.kill("SIGKILL");
        }
      }, 5000);
    } catch {
      // Ein bereits beendeter Prozess ist kein Fehler.
    }

    this.child = null;
    this.stopping = false;
  }
}
