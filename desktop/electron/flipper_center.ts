import { BrowserWindow, dialog, shell } from "electron";
import { execFile } from "child_process";
import * as fs from "fs";
import * as path from "path";

export interface FlipperStatus {
  connected: boolean; port: string | null; deviceName: string | null;
  serial: string | null; qFlipperInstalled: boolean; wifiBoardConnected: boolean;
}

const QFLIPPER = "C:\\Program Files\\qFlipper\\qFlipper.exe";

function powershell(script: string): Promise<string> {
  return new Promise((resolve) => execFile(
    "powershell.exe", ["-NoProfile", "-NonInteractive", "-Command", script],
    { windowsHide: true, timeout: 8_000 },
    (error, stdout) => resolve(error ? "" : stdout.trim()),
  ));
}

export async function readFlipperStatus(): Promise<FlipperStatus> {
  const script = [
    "$items=Get-CimInstance Win32_PnPEntity -ErrorAction SilentlyContinue|Where-Object{$_.PNPDeviceID -match 'VID_0483&PID_5740|VID_303A'}|Select-Object Name,PNPDeviceID,Status;",
    "$ports=Get-CimInstance Win32_SerialPort -ErrorAction SilentlyContinue|Where-Object{$_.PNPDeviceID -match 'VID_0483&PID_5740|VID_303A'}|Select-Object DeviceID,Name,PNPDeviceID;",
    "@{items=$items;ports=$ports}|ConvertTo-Json -Depth 4 -Compress",
  ].join(" ");
  const raw = await powershell(script);
  let data: any = {};
  try { data = JSON.parse(raw); } catch { data = {}; }
  const items = Array.isArray(data.items) ? data.items : data.items ? [data.items] : [];
  const ports = Array.isArray(data.ports) ? data.ports : data.ports ? [data.ports] : [];
  const flipper = items.find((x: any) => String(x.PNPDeviceID).includes("VID_0483&PID_5740"));
  const esp = items.find((x: any) => String(x.PNPDeviceID).includes("VID_303A"));
  const flipperPort = ports.find((x: any) => String(x.PNPDeviceID).includes("VID_0483&PID_5740"));
  const serialMatch = String(flipper?.PNPDeviceID ?? "").match(/\\(FLIP_[^\\]+)/i);
  return {
    connected: Boolean(flipper), port: flipperPort?.DeviceID ?? null,
    deviceName: flipper?.Name ?? null, serial: serialMatch?.[1] ?? null,
    qFlipperInstalled: fs.existsSync(QFLIPPER), wifiBoardConnected: Boolean(esp),
  };
}

export class FlipperCenter {
  private window: BrowserWindow | null = null;
  constructor(private readonly rendererDir: string) {}

  show(): void {
    if (this.window && !this.window.isDestroyed()) { this.window.show(); this.window.focus(); return; }
    this.window = new BrowserWindow({
      width: 1180, height: 780, minWidth: 900, minHeight: 620,
      title: "Flipper Control Center", backgroundColor: "#071019", autoHideMenuBar: true,
      webPreferences: { preload: path.join(__dirname, "preload.js"), contextIsolation: true, nodeIntegration: false, sandbox: false },
    });
    void this.window.loadFile(path.join(this.rendererDir, "flipper-center.html"));
    this.window.on("closed", () => { this.window = null; });
    this.window.webContents.setWindowOpenHandler(({ url }) => {
      if (/^https:\/\//i.test(url)) void shell.openExternal(url);
      return { action: "deny" };
    });
  }

  close(): void { this.window?.close(); this.window = null; }
  launchQFlipper(): boolean { if (!fs.existsSync(QFLIPPER)) return false; void shell.openPath(QFLIPPER); return true; }
  async chooseApp(): Promise<string | null> {
    if (!this.window || this.window.isDestroyed()) return null;
    const result = await dialog.showOpenDialog(this.window, {
      title: "Flipper-App auswählen", properties: ["openFile"],
      filters: [{ name: "Flipper-App", extensions: ["fap"] }],
    });
    return result.canceled ? null : result.filePaths[0] ?? null;
  }
}
