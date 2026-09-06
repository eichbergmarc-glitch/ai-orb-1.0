/** Ein beständig aktualisiertes Bildfenster für laufende Vorlesungen. */

import { BrowserWindow, screen } from "electron";
import * as fs from "fs";
import * as path from "path";

export interface LectureVisualPayload {
  path?: string;
  title?: string;
  topic?: string;
  caption?: string;
  kind?: string;
  layout?: "overview" | "enumeration" | "timeline" | "comparison" | string;
  summary?: Array<{ title?: string; text?: string }>;
  generation?: number;
}

export interface LectureVisualBounds {
  x: number;
  y: number;
  width: number;
  height: number;
}

const MAX_IMAGE_BYTES = 16 * 1024 * 1024;
const MIME: Record<string, string> = {
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".png": "image/png",
  ".webp": "image/webp",
  ".gif": "image/gif",
  ".bmp": "image/bmp",
};

export class LectureVisualWindow {
  private window: BrowserWindow | null = null;
  private latestGeneration = 0;
  private renderSerial = 0;

  public constructor(
    private readonly onVisibilityChanged?: (
      visible: boolean,
      bounds?: LectureVisualBounds,
    ) => void,
  ) {}

  /** Zeigt ein Bild oder ersetzt das vorige im bereits offenen Fenster. */
  public async show(payload: LectureVisualPayload, parent?: BrowserWindow | null): Promise<void> {
    const generation = Number(payload.generation ?? 0);
    if (generation > 0 && generation < this.latestGeneration) return;

    const rawPath = String(payload.path ?? "").trim();
    let image = "";
    if (rawPath) {
      const imagePath = path.resolve(rawPath);
      const extension = path.extname(imagePath).toLowerCase();
      const mime = MIME[extension];
      if (!mime) {
        console.warn(`[AI-Orb] Vorlesungsbild hat kein erlaubtes Bildformat: ${imagePath}`);
      } else {
        try {
          const stat = await fs.promises.stat(imagePath);
          if (!stat.isFile() || stat.size < 1 || stat.size > MAX_IMAGE_BYTES) {
            console.warn(`[AI-Orb] Vorlesungsbild hat eine unzulässige Größe: ${imagePath}`);
          } else {
            const bytes = await fs.promises.readFile(imagePath);
            image = `data:${mime};base64,${bytes.toString("base64")}`;
          }
        } catch (error) {
          console.warn(`[AI-Orb] Vorlesungsbild ist nicht lesbar: ${imagePath}`, error);
        }
      }
    }

    const summary = (Array.isArray(payload.summary) ? payload.summary : [])
      .map((item) => ({
        title: trimText(String(item?.title ?? "Orientierung"), 70),
        text: trimText(String(item?.text ?? ""), 300),
      }))
      .filter((item) => item.text.length > 0)
      // Vier kompakte Karten passen auch auf einem 1280x800-Bildschirm
      // vollständig neben das Foto. Eine fünfte Karte erzwang bislang eine
      // Scrollleiste und lenkte vom gesprochenen Vortrag ab.
      .slice(0, 4);
    if (!image && summary.length === 0) return;

    if (generation > 0) this.latestGeneration = generation;
    const serial = ++this.renderSerial;
    const target = this.ensureWindow(parent);
    const title = trimText(payload.title || payload.topic || "Bild zur Vorlesung", 140);
    const topic = trimText(payload.topic || "Laufende Vorlesung", 180);
    const caption = trimText(payload.caption || "", 800);
    // Bekannte Arten durchlassen, alles andere auf die Uebersicht
    // zurueckfallen lassen. Vorher wurde hier alles ausser "enumeration"
    // plattgemacht - neue Arten waeren stillschweigend verschwunden.
    const erlaubt = ["enumeration", "timeline", "comparison"];
    const layout = erlaubt.includes(String(payload.layout ?? ""))
      ? String(payload.layout)
      : "overview";
    const html = buildPage({ title, topic, caption, image, summary, layout });

    try {
      await target.loadURL(`data:text/html;base64,${Buffer.from(html, "utf8").toString("base64")}`);
      if (serial !== this.renderSerial || target.isDestroyed()) return;
      // Die Lehrtafel darf die Tastatureingabe und den Redefluss nicht an sich ziehen.
      target.showInactive();
      this.notifyVisibility(true, target.getBounds());
    } catch (error) {
      console.warn("[AI-Orb] Lehrtafel konnte nicht aktualisiert werden.", error);
    }
  }

  public close(): void {
    this.renderSerial += 1;
    if (this.window !== null && !this.window.isDestroyed()) this.window.close();
    this.window = null;
  }

  private ensureWindow(parent?: BrowserWindow | null): BrowserWindow {
    if (this.window !== null && !this.window.isDestroyed()) return this.window;

    const display = screen.getDisplayNearestPoint(screen.getCursorScreenPoint());
    // Die Lehrtafel ist ein zentrales Element der Vorlesung, keine kleine
    // Bildvorschau. Auf dem typischen 1280x800-Arbeitsbereich belegt sie nun
    // rund 72 Prozent der Breite und 78 Prozent der Hoehe. Links bleibt ein
    // Streifen fuer den Orb; auf grossen Monitoren verhindert die Obergrenze,
    // dass die Darstellung unnoetig auseinandergezogen wird.
    const margin = Math.max(12, Math.round(display.workArea.width * 0.015));
    const width = Math.min(
      1060,
      Math.max(680, Math.round(display.workArea.width * 0.72)),
      display.workArea.width - margin * 2,
    );
    const height = Math.min(
      740,
      Math.max(500, Math.round(display.workArea.height * 0.78)),
      display.workArea.height - 24,
    );
    const x = display.workArea.x + display.workArea.width - width - margin;
    const y = display.workArea.y + Math.max(12, Math.round((display.workArea.height - height) / 2));

    this.window = new BrowserWindow({
      width,
      height,
      x,
      y,
      minWidth: 640,
      minHeight: 480,
      title: "AI-Orb – Lehrtafel",
      parent: parent && !parent.isDestroyed() ? parent : undefined,
      modal: false,
      show: false,
      resizable: true,
      maximizable: true,
      minimizable: true,
      alwaysOnTop: true,
      autoHideMenuBar: true,
      backgroundColor: "#06142a",
      webPreferences: {
        contextIsolation: true,
        nodeIntegration: false,
        sandbox: true,
      },
    });
    this.window.setMenu(null);
    this.window.on("closed", () => {
      this.window = null;
      this.notifyVisibility(false);
    });
    return this.window;
  }

  private notifyVisibility(visible: boolean, bounds?: LectureVisualBounds): void {
    try {
      this.onVisibilityChanged?.(visible, bounds);
    } catch (error) {
      // Fensterkoordination ist Komfortfunktion; ein Fehler darf weder die
      // Lehrtafel noch die laufende Vorlesung beenden.
      console.warn("[AI-Orb] Orb und Lehrtafel konnten nicht koordiniert werden.", error);
    }
  }
}

function trimText(value: string, max: number): string {
  const clean = String(value ?? "").replace(/\s+/g, " ").trim();
  return clean.length <= max ? clean : `${clean.slice(0, max - 1).trimEnd()}…`;
}

function escapeHtml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

export function buildPage(data: {
  title: string;
  topic: string;
  caption: string;
  image: string;
  summary: Array<{ title: string; text: string }>;
  layout: "overview" | "enumeration" | "timeline" | "comparison" | string;
}): string {
  const zeitleiste = data.layout === "timeline" && data.summary.length >= 2;
  const vergleich = data.layout === "comparison" && data.summary.length >= 2;

  // Drei Kartenformen statt einer.
  //
  // Bisher wurde jeder Inhalt in dieselbe nummerierte Liste gegossen. Eine
  // Abfolge von Jahren und zwei gegeneinander stehende Positionen verlieren
  // dabei genau das, was sie ausmacht: die Reihenfolge und die
  // Gegenueberstellung. Beides sieht man in einem Bild sofort und muss es
  // in einer Liste erst wieder zusammensuchen.
  let cards: string;
  if (zeitleiste) {
    // Die Marken kommen in einen eigenen Behaelter. Nur so laesst sich die
    // Linie GENAU von der ersten bis zur letzten Marke ziehen - haengt sie
    // am ganzen Kasten, laeuft sie oben an der Ueberschrift vorbei und
    // unten ins Leere.
    cards =
      '<div class="strang">' +
      data.summary
        .map(
          (item) =>
            `<article class="marke"><div class="jahr">${escapeHtml(item.title)}</div>` +
            `<p>${escapeHtml(item.text)}</p></article>`,
        )
        .join("") +
      "</div>";
  } else if (vergleich) {
    cards = data.summary
      .map((item, index) => {
        const rolle = index === 0 ? "links" : index === 1 ? "rechts" : "streit";
        return (
          `<article class="seite ${rolle}"><h2>${escapeHtml(item.title)}</h2>` +
          `<p>${escapeHtml(item.text)}</p></article>`
        );
      })
      .join("");
  } else {
    cards = data.summary
      .map((item, index) => `<article><div class="number">${index + 1}</div><div><h2>${escapeHtml(item.title)}</h2><p>${escapeHtml(item.text)}</p></div></article>`)
      .join("");
  }

  const photo = data.image
    ? `<figure><img src="${data.image}" alt="${escapeHtml(data.title)}"></figure>`
    : "";
  const structured = data.layout === "enumeration";
  const visualClass = [
    "visual",
    data.image ? "has-photo" : "overview-only",
    structured ? "structured" : "",
    zeitleiste ? "zeitleiste" : "",
    vergleich ? "vergleich" : "",
  ].filter(Boolean).join(" ");
  const overviewTitle = zeitleiste
    ? "Im zeitlichen Verlauf"
    : vergleich
      ? "Zwei Positionen"
      : structured
        ? "Die vollständige Fachstruktur"
        : "Auf einen Blick";
  return `<!doctype html>
<html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<style>
  :root { color-scheme: dark; font-family: Inter, "Segoe UI", sans-serif; }
  * { box-sizing: border-box; }
  body { margin: 0; height: 100vh; overflow: hidden; color: #f2faff; background:
    radial-gradient(circle at 78% 12%, rgba(40,137,255,.27), transparent 40%),
    linear-gradient(145deg, #020b18, #071d3a 62%, #020b19); }
  main { height: 100vh; display: grid; grid-template-rows: auto minmax(0, 1fr) auto;
    padding: 13px 14px; gap: 8px; }
  header { min-width: 0; }
  .eyebrow { color: #66e2ff; font-size: 12px; font-weight: 750; letter-spacing: .12em;
    text-transform: uppercase; margin-bottom: 4px; }
  h1 { margin: 0; color: #fff; font-size: clamp(22px, 2.8vw, 34px); line-height: 1.08;
    text-shadow: 0 2px 18px rgba(60,190,255,.18); }
  .visual { min-height: 0; display: grid; gap: 10px; }
  .visual.has-photo { grid-template-columns: minmax(0, 1.5fr) minmax(285px, .82fr); }
  /* Bei expliziten Aufzaehlungen sind die benannten Punkte der Lehrstoff,
     nicht bloss eine Randnotiz zum Foto. Deshalb bekommen die Karten hier
     bewusst mehr Platz als ein beliebiges Begleitbild. */
  .visual.has-photo.structured { grid-template-columns: minmax(260px, .78fr) minmax(440px, 1.22fr); }
  .visual.overview-only { grid-template-columns: minmax(0, 1fr); }
  figure { margin: 0; min-height: 0; border: 2px solid rgba(82,216,255,.58); border-radius: 18px;
    overflow: hidden; display: grid; place-items: center; background: #010711;
    box-shadow: 0 20px 70px rgba(0,0,0,.58), inset 0 0 44px rgba(39,126,255,.12),
      0 0 24px rgba(49,170,255,.10); }
  img { width: 100%; height: 100%; object-fit: contain; display: block;
    filter: saturate(1.08) contrast(1.05) brightness(1.04); }
  aside { min-height: 0; overflow: hidden; border: 1px solid rgba(73,169,255,.32);
    border-radius: 16px; padding: 9px; background: rgba(4,19,41,.82);
    display: grid; align-content: start; gap: 7px; }
  aside > h2 { margin: 0; color: #66e2ff; font-size: 15px;
    letter-spacing: .06em; text-transform: uppercase; }
  article { min-height: 0; display: grid; grid-template-columns: 28px minmax(0,1fr); gap: 8px;
    padding: 8px; border-radius: 11px; background: rgba(13,48,87,.74);
    border-left: 4px solid #32bfff; }
  article:nth-of-type(3n+1) { border-left-color: #8b6cff; }
  article:nth-of-type(3n+2) { border-left-color: #31d9ad; }
  .number { width: 26px; height: 26px; border-radius: 50%; display: grid;
    place-items: center; color: #041225; background: #66e2ff; font-weight: 850; }
  article h2 { margin: 0 0 3px; font-size: clamp(14px, 1.45vw, 18px); color: #fff; }
  article p { margin: 0; font-size: clamp(12px, 1.18vw, 15px); line-height: 1.25;
    color: #d6e7f5; }
  .overview-only aside { grid-template-columns: repeat(2, minmax(0, 1fr)); align-content: center;
    padding: 14px; }
  .overview-only aside > h2 { grid-column: 1 / -1; font-size: 17px; }
  .structured aside { grid-template-columns: repeat(2, minmax(0, 1fr));
    grid-template-rows: auto repeat(2, minmax(0, 1fr)); align-content: stretch;
    padding: 12px; gap: 9px; }
  .structured aside > h2 { grid-column: 1 / -1; font-size: 16px; }
  .structured article { align-content: start; padding: 11px; }
  .structured article h2 { font-size: clamp(15px, 1.6vw, 20px); }
  .structured article p { font-size: clamp(13px, 1.3vw, 16px); line-height: 1.35; }

  /* --- Zeitleiste ------------------------------------------------------
     Eine durchgehende Linie und Marken darauf. Die Linie ist der ganze
     Punkt: Sie zeigt, dass die Punkte eine Reihenfolge haben, und das
     sieht das Auge, bevor es das erste Wort gelesen hat. */
  .zeitleiste aside { grid-template-columns: minmax(0,1fr); padding: 14px 12px;
    gap: 10px; align-content: center; }
  .zeitleiste .strang { position: relative; display: grid; gap: 10px;
    padding-left: 26px; }
  .zeitleiste .strang::before { content: ""; position: absolute;
    left: 4px; top: 14px; bottom: 14px; width: 2px;
    background: linear-gradient(180deg, rgba(102,226,255,.25), #66e2ff 12%,
      #3a7fe0 80%, rgba(58,127,224,.25)); }
  .zeitleiste article.marke { position: relative; display: block;
    background: rgba(13,48,87,.66); border-left: none; padding: 8px 11px; }
  .zeitleiste article.marke::before { content: ""; position: absolute;
    left: -27px; top: 13px; width: 10px; height: 10px; border-radius: 50%;
    background: #66e2ff; box-shadow: 0 0 0 3px rgba(102,226,255,.22); }
  .zeitleiste .jahr { color: #66e2ff; font-weight: 800; font-size: clamp(13px,1.3vw,17px);
    letter-spacing: .04em; margin-bottom: 2px; }

  /* --- Gegenueberstellung ----------------------------------------------
     Zwei Spalten nebeneinander, der Streitpunkt darunter ueber die volle
     Breite. Nebeneinander ist hier keine Platzfrage: Ein Vergleich, der
     untereinander steht, ist wieder eine Liste. */
  .vergleich aside { grid-template-columns: repeat(2, minmax(0,1fr));
    grid-auto-rows: minmax(0, auto); align-content: center; padding: 12px; gap: 10px; }
  .vergleich aside > h2 { grid-column: 1 / -1; }
  .vergleich article.seite { display: block; padding: 11px; border-left: 4px solid #32bfff; }
  .vergleich article.rechts { border-left-color: #8b6cff; }
  .vergleich article.streit { grid-column: 1 / -1; border-left-color: #66e2ff;
    background: rgba(6,28,54,.9); }
  .vergleich article.seite h2 { font-size: clamp(14px,1.5vw,19px); color: #fff;
    margin-bottom: 4px; }
  .vergleich article.streit h2 { color: #66e2ff; font-size: 14px;
    text-transform: uppercase; letter-spacing: .07em; }

  footer { color: #c2d4e4; font-size: 12px; line-height: 1.25; min-height: 15px;
    overflow: hidden; white-space: nowrap; text-overflow: ellipsis;
    text-shadow: 0 1px 4px #000; }
  @media (max-width: 760px) {
    .visual.has-photo { grid-template-columns: 1fr; grid-template-rows: minmax(220px, 1.2fr) minmax(0, 1fr); }
    .overview-only aside { grid-template-columns: 1fr; }
    .structured aside { grid-template-columns: repeat(2, minmax(0, 1fr));
      grid-template-rows: auto repeat(2, minmax(0, 1fr)); }
  }
</style></head><body><main>
  <header><div class="eyebrow">${escapeHtml(data.topic)}</div><h1>${escapeHtml(data.title)}</h1></header>
  <section class="${visualClass}">${photo}<aside><h2>${overviewTitle}</h2>${cards}</aside></section>
  <footer>${escapeHtml(data.caption)}</footer>
</main></body></html>`;
}
