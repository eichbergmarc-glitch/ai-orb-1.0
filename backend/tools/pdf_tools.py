"""Erzeugt echte, durchsuchbare PDF-Dokumente ohne externen Webdienst.

Der portable Orb bringt nicht zwingend ReportLab mit. Dieses Modul schreibt
deshalb einen kleinen, standardskonformen PDF-1.4-Datenstrom selbst. Text
bleibt markier- und auslesbar; lokale Bilder werden als XObjects eingebettet.
Jeder Ziel- und Bildpfad laeuft weiterhin durch den zentralen Pfadschutz.

## Bilder an der richtigen Stelle

Bilder gehoeren dorthin, wo der Text von ihnen spricht - nicht hinten in
einen Anhang. Deshalb versteht der Inhalt eine Bildmarke::

    Die Erzeugung stieg im letzten Jahrzehnt deutlich an.

    [BILD: C:\\Users\\info\\data\\grafiken\\strom.png | Erzeugung 2015 bis 2025]

    Auffaellig ist dabei der Einbruch im Jahr 2022.

Die Marke wird durch das Bild ersetzt, der Text davor und danach bleibt, wo
er ist. Wer die alte Form benutzt und Bilder ueber den Parameter ``bilder``
mitgibt, bekommt sie weiterhin ans Ende gehaengt - beides geht nebeneinander.

## Zwei Arten von Bildern, zwei Arten der Einbettung

Fotos werden als JPEG eingebettet: Bei einer Fotografie sieht niemand den
Unterschied, und die Datei bleibt klein. Diagramme dagegen bestehen aus
scharfen Kanten und duenner Schrift, und genau das zerstoert JPEG - Zahlen
an einer Achse werden dabei unleserlich. PNG-Bilder gehen deshalb
verlustfrei hinein (Flate), auch wenn das ein paar hundert Kilobyte mehr
kostet. Ein unleserliches Diagramm waere kein gespartes Byte wert.
"""

from __future__ import annotations

import io
import re
import zlib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from backend.security.security_engine import SecurityEngine
from backend.system.logging_setup import get_logger
from backend.tools.base_tool import Tool, ToolParameter, ToolResult

logger = get_logger(__name__)

_PAGE_WIDTH = 595.28
_PAGE_HEIGHT = 841.89
_LEFT = 58.0
_RIGHT = 58.0
_BOTTOM = 58.0
_CONTENT_WIDTH = _PAGE_WIDTH - _LEFT - _RIGHT
_MAX_CONTENT = 400_000


def _plain(text: str) -> str:
    """Normalisiert Zeichen, die in Basis-PDF-Schriften Probleme machen."""

    return (
        str(text or "")
        .replace("\u2011", "-")
        .replace("\u2012", "-")
        .replace("\u2013", "-")
        .replace("\u2014", "-")
        .replace("\u2026", "...")
        .replace("\t", "    ")
    )


def _pdf_string(text: str) -> str:
    """Kodiert einen Text als PDF-Literal mit WinAnsi-Encoding."""

    raw = _plain(text).encode("cp1252", errors="replace")
    escaped: list[str] = []
    for byte in raw:
        if byte in (40, 41, 92):
            escaped.append("\\" + chr(byte))
        elif 32 <= byte <= 126:
            escaped.append(chr(byte))
        else:
            escaped.append(f"\\{byte:03o}")
    return "(" + "".join(escaped) + ")"


def _estimated_width(text: str, size: float) -> float:
    units = 0.0
    for char in text:
        if char == " ":
            units += 0.28
        elif char in "ilI.,:;!'|":
            units += 0.26
        elif char in "mwMW@%":
            units += 0.82
        elif char.isupper():
            units += 0.62
        else:
            units += 0.52
    return units * size


def _wrap(text: str, size: float, width: float) -> list[str]:
    words = _plain(text).split()
    if not words:
        return [""]
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = current + " " + word
        if _estimated_width(candidate, size) <= width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


#: Eine Bildmarke im Inhalt. Die Schreibweisen, die ein Sprachmodell
#: tatsaechlich produziert, sind alle erlaubt: BILD, Bild, bild, IMAGE, IMG,
#: Grafik - mit und ohne Doppelpunkt.
_BILDMARKE = re.compile(
    r"^\[\s*(?:bild|image|img|grafik|abbildung)\s*[:=]?\s*(.+?)\s*\]$", re.I
)

#: Woran eine Bildmarke als solche erkennbar ist: Dahinter steht ein Pfad.
#: Ohne diese zweite Pruefung wuerde eine Zeile wie "[Bild der Lage]" aus dem
#: Dokument verschwinden, statt gedruckt zu werden.
_SIEHT_NACH_PFAD_AUS = re.compile(
    r"\.(?:png|jpe?g|gif|bmp|webp|tiff?)\s*(?:\||$)", re.I
)


def _bildmarke_teilen(inhalt: str) -> tuple[str, str]:
    """Trennt Pfad und Bildunterschrift einer Bildmarke.

    Getrennt wird am senkrechten Strich. Nicht am Komma und nicht am
    Semikolon: In einem Windows-Pfad kommt beides vor, und ein Pfad, der
    an ``C:`` abgeschnitten wird, findet nie eine Datei.
    """

    if "|" in inhalt:
        pfad, _, beschriftung = inhalt.partition("|")
        return pfad.strip().strip('"').strip("'"), beschriftung.strip()
    return inhalt.strip().strip('"').strip("'"), ""


def _slug(text: str) -> str:
    value = _plain(text).lower()
    value = re.sub(r"[^a-z0-9äöüß]+", "-", value).strip("-")
    return (value[:55].strip("-") or "ai-orb-dokument")


@dataclass
class _Page:
    commands: list[str] = field(default_factory=list)
    images: set[str] = field(default_factory=set)


class _Layout:
    """Sehr kleine Satzengine fuer gegliederte A4-Dokumente."""

    def __init__(self, title: str) -> None:
        self.title = _plain(title).strip() or "AI-Orb Dokument"
        self.pages: list[_Page] = []
        #: Name -> (Daten, Breite, Hoehe, Filter). Filter ist ``DCTDecode``
        #: fuer Fotos und ``FlateDecode`` fuer verlustfreie Diagramme.
        self.images: dict[str, tuple[bytes, int, int, str]] = {}
        #: Bildmarken, die auf keine lesbare Datei zeigten.
        self.fehlende_bilder: list[str] = []
        self.y = 0.0
        self._new_page(first=True)

    @property
    def page(self) -> _Page:
        return self.pages[-1]

    def _new_page(self, *, first: bool = False) -> None:
        page = _Page()
        self.pages.append(page)
        if first:
            page.commands.extend(
                [
                    "0.025 0.075 0.16 rg 0 742 595.28 99.89 re f",
                    "0.05 0.72 0.95 rg 0 736 595.28 6 re f",
                ]
            )
            title_lines = _wrap(self.title, 22, _CONTENT_WIDTH)
            y = 798.0
            for line in title_lines[:3]:
                self._text(line, _LEFT, y, 22, bold=True, color=(1, 1, 1))
                y -= 27
            self.y = min(718.0, y - 18)
        else:
            page.commands.extend(
                [
                    "0.025 0.075 0.16 rg 0 802 595.28 39.89 re f",
                    "0.05 0.72 0.95 rg 0 798 595.28 4 re f",
                ]
            )
            header = self.title if len(self.title) <= 72 else self.title[:69] + "..."
            self._text(header, _LEFT, 817, 10, bold=True, color=(1, 1, 1))
            self.y = 775.0

    def _text(
        self,
        text: str,
        x: float,
        y: float,
        size: float,
        *,
        bold: bool = False,
        color: tuple[float, float, float] = (0.08, 0.12, 0.20),
    ) -> None:
        font = "F2" if bold else "F1"
        r, g, b = color
        self.page.commands.append(
            f"BT /{font} {size:.2f} Tf {r:.3f} {g:.3f} {b:.3f} rg "
            f"1 0 0 1 {x:.2f} {y:.2f} Tm {_pdf_string(text)} Tj ET"
        )

    def _ensure(self, height: float) -> None:
        if self.y - height < _BOTTOM:
            self._new_page()

    def gap(self, amount: float = 8.0) -> None:
        self._ensure(amount)
        self.y -= amount

    def heading(self, text: str, *, level: int = 2) -> None:
        size = 17.0 if level <= 1 else 14.0
        lines = _wrap(text, size, _CONTENT_WIDTH)
        height = len(lines) * (size + 5) + 13
        self._ensure(height)
        self.y -= 5
        # Dezenter visueller Abschnittsmarker.
        self.page.commands.append(
            f"0.05 0.72 0.95 rg {_LEFT:.2f} {self.y - height + 12:.2f} 3.5 "
            f"{height - 12:.2f} re f"
        )
        for line in lines:
            self._text(line, _LEFT + 12, self.y, size, bold=True, color=(0.02, 0.20, 0.36))
            self.y -= size + 5
        self.y -= 7

    def paragraph(self, text: str, *, bullet: str = "") -> None:
        size = 10.5
        indent = 17.0 if bullet else 0.0
        lines = _wrap(text, size, _CONTENT_WIDTH - indent)
        line_height = 15.0
        total_height = max(1, len(lines)) * line_height + 5.0

        # Kurze Absaetze bleiben zusammen. Sehr lange Absaetze werden dagegen
        # zeilenweise umbrochen; ein Vorab-Umbruch des gesamten Absatzes wuerde
        # die angefangene Seite leer lassen und den Text danach bis in den
        # Fussbereich zeichnen.
        if total_height <= (_PAGE_HEIGHT - 2 * _BOTTOM):
            self._ensure(total_height)

        bullet_pending = bool(bullet)
        for line in lines:
            self._ensure(line_height)
            if bullet_pending:
                self._text(
                    bullet,
                    _LEFT,
                    self.y,
                    size,
                    bold=True,
                    color=(0.02, 0.45, 0.72),
                )
                bullet_pending = False
            self._text(line, _LEFT + indent, self.y, size)
            self.y -= line_height
        self.gap(5.0)

    def add_image(self, path: Path, *, caption: str = "") -> None:
        try:
            from PIL import Image, ImageOps

            with Image.open(path) as opened:
                verlustfrei = (opened.format or "").upper() in ("PNG", "GIF", "BMP")
                image = ImageOps.exif_transpose(opened).convert("RGB")
                image.thumbnail((1500, 1000))
                pixel_width, pixel_height = image.size
                if verlustfrei:
                    # Diagramme: scharfe Kanten, duenne Schrift. JPEG wuerde
                    # genau daraus Matsch machen.
                    data = zlib.compress(image.tobytes(), 6)
                    filter_name = "FlateDecode"
                else:
                    buffer = io.BytesIO()
                    image.save(buffer, format="JPEG", quality=88, optimize=True)
                    data = buffer.getvalue()
                    filter_name = "DCTDecode"
        except Exception as error:  # noqa: BLE001 - ein Bild darf nicht das PDF verhindern.
            logger.warning("Bild fuer PDF nicht lesbar (%s): %s", path, error)
            self.fehlende_bilder.append(str(path))
            return

        name = f"Im{len(self.images) + 1}"
        self.images[name] = (data, pixel_width, pixel_height, filter_name)
        width = min(_CONTENT_WIDTH, 420.0)
        height = width * pixel_height / max(1, pixel_width)
        if height > 360.0:
            height = 360.0
            width = height * pixel_width / max(1, pixel_height)
        caption_height = 28.0 if caption else 8.0
        # Passt das Bild nicht mehr aufs Blatt, aber es ist noch ein
        # ordentlicher Rest frei, dann lieber kleiner setzen als eine halb
        # leere Seite zu hinterlassen. Erst wenn wirklich wenig uebrig ist,
        # wird umbrochen.
        frei = self.y - _BOTTOM - caption_height
        if height > frei and frei >= 200.0:
            width *= frei / height
            height = frei
        else:
            self._ensure(height + caption_height)
        x = _LEFT + (_CONTENT_WIDTH - width) / 2
        self.y -= height
        self.page.commands.append(
            f"q {width:.2f} 0 0 {height:.2f} {x:.2f} {self.y:.2f} cm /{name} Do Q"
        )
        self.page.images.add(name)
        if caption:
            self.y -= 14
            for line in _wrap(caption, 8.5, _CONTENT_WIDTH):
                self._text(line, _LEFT, self.y, 8.5, color=(0.30, 0.34, 0.40))
                self.y -= 11
        self.y -= 10

    def render_content(
        self,
        content: str,
        *,
        bild_aufloeser: Callable[[str], Path | None] | None = None,
    ) -> None:
        """Setzt den Inhalt - Ueberschriften, Absaetze, Listen und Bildmarken.

        Args:
            content: Der Text, gern mit einfachen Markdown-Zeichen.
            bild_aufloeser: Wird fuer jede Bildmarke ``[BILD: ...]`` gerufen
                und gibt den geprueften Pfad zurueck oder ``None``. Ohne
                Aufloeser bleiben Bildmarken einfach stehen - dieses Modul
                soll nicht selbst entscheiden, welcher Pfad gelesen werden
                darf.
        """

        paragraph: list[str] = []

        def flush() -> None:
            if paragraph:
                self.paragraph(" ".join(paragraph))
                paragraph.clear()

        for raw_line in _plain(content).splitlines():
            line = raw_line.strip()
            if not line:
                flush()
                self.gap(4)
                continue

            marke = _BILDMARKE.match(line)
            if (
                marke
                and bild_aufloeser is not None
                and _SIEHT_NACH_PFAD_AUS.search(marke.group(1))
            ):
                flush()
                roh, beschriftung = _bildmarke_teilen(marke.group(1))
                pfad = bild_aufloeser(roh)
                if pfad is None:
                    self.fehlende_bilder.append(roh)
                else:
                    self.add_image(pfad, caption=beschriftung or pfad.stem)
                continue

            heading = re.match(r"^(#{1,3})\s+(.+)$", line)
            if heading:
                flush()
                self.heading(heading.group(2), level=len(heading.group(1)))
                continue
            bullet = re.match(r"^[-*•]\s+(.+)$", line)
            numbered = re.match(r"^(\d+[.)])\s+(.+)$", line)
            if bullet or numbered:
                flush()
                if bullet:
                    self.paragraph(bullet.group(1), bullet="•")
                else:
                    self.paragraph(numbered.group(2), bullet=numbered.group(1))
                continue
            paragraph.append(line)
        flush()

    def finish(self) -> None:
        total = len(self.pages)
        for index, page in enumerate(self.pages, start=1):
            page.commands.append("0.82 0.87 0.91 RG 58 47 m 537 47 l S")
            previous = self.pages[-1]
            self.pages[-1] = page
            self._text(
                f"AI-Orb  |  Seite {index} von {total}",
                _LEFT,
                31,
                8,
                color=(0.35, 0.40, 0.47),
            )
            self.pages[-1] = previous


def _build_pdf(layout: _Layout, *, title: str) -> bytes:
    """Baut Objektstruktur, Streams und XRef-Tabelle."""

    layout.finish()
    objects: list[bytes | None] = [None]

    def reserve() -> int:
        objects.append(None)
        return len(objects) - 1

    catalog_id = reserve()
    pages_id = reserve()
    font_regular_id = reserve()
    font_bold_id = reserve()
    info_id = reserve()

    image_ids: dict[str, int] = {name: reserve() for name in layout.images}
    content_ids = [reserve() for _ in layout.pages]
    page_ids = [reserve() for _ in layout.pages]

    objects[font_regular_id] = (
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
        b"/Encoding /WinAnsiEncoding >>"
    )
    objects[font_bold_id] = (
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold "
        b"/Encoding /WinAnsiEncoding >>"
    )
    for name, (data, width, height, filter_name) in layout.images.items():
        objects[image_ids[name]] = (
            f"<< /Type /XObject /Subtype /Image /Width {width} /Height {height} "
            f"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /{filter_name} "
            f"/Length {len(data)} >>\nstream\n".encode("ascii")
            + data
            + b"\nendstream"
        )

    for index, page in enumerate(layout.pages):
        stream = ("\n".join(page.commands) + "\n").encode("ascii")
        objects[content_ids[index]] = (
            f"<< /Length {len(stream)} >>\nstream\n".encode("ascii")
            + stream
            + b"endstream"
        )
        xobjects = " ".join(
            f"/{name} {image_ids[name]} 0 R" for name in sorted(page.images)
        )
        resources = (
            f"/Font << /F1 {font_regular_id} 0 R /F2 {font_bold_id} 0 R >>"
            + (f" /XObject << {xobjects} >>" if xobjects else "")
        )
        objects[page_ids[index]] = (
            f"<< /Type /Page /Parent {pages_id} 0 R "
            f"/MediaBox [0 0 {_PAGE_WIDTH:.2f} {_PAGE_HEIGHT:.2f}] "
            f"/Resources << {resources} >> /Contents {content_ids[index]} 0 R >>"
        ).encode("ascii")

    kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
    objects[pages_id] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode("ascii")
    objects[catalog_id] = f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode("ascii")
    objects[info_id] = (
        f"<< /Title {_pdf_string(title)} /Author {_pdf_string('AI-Orb')} "
        f"/Creator {_pdf_string('AI-Orb PDF-Werkzeug')} >>"
    ).encode("ascii")

    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for object_id in range(1, len(objects)):
        offsets.append(len(output))
        output.extend(f"{object_id} 0 obj\n".encode("ascii"))
        output.extend(objects[object_id] or b"<<>>")
        output.extend(b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(objects)}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        f"trailer\n<< /Size {len(objects)} /Root {catalog_id} 0 R "
        f"/Info {info_id} 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode("ascii")
    )
    return bytes(output)


class CreatePdfTool(Tool):
    """Erzeugt aus gegliedertem Text und lokalen Bildern eine PDF-Datei."""

    name = "pdf_erstellen"
    description = (
        "Erstellt eine professionell formatierte, durchsuchbare PDF-Datei aus "
        "einem Titel und dem vollstaendigen Inhalt. Benutze dieses Werkzeug "
        "immer, wenn der Benutzer eine PDF anfordert. Der Inhalt darf einfache "
        "Markdown-Ueberschriften und Listen enthalten. "
        "BILDER: Schreibe eine Zeile [BILD: pfad | Bildunterschrift] an genau "
        "die Stelle im Inhalt, an der das Bild stehen soll. Die Pfade bekommst "
        "du von 'diagramm_zeichnen' (Zahlen anschaulich machen), 'bild_suchen' "
        "(echte Fotos mit Lizenznachweis) oder 'bild_erzeugen' (Illustrationen). "
        "Alternativ hinten anhaengen ueber den Parameter 'bilder'. "
        "Ist kein Zielpfad angegeben, wird die PDF automatisch im "
        "Dokumente-Ordner unter AI-Orb gespeichert."
    )
    permission = "write_files"
    parameters = (
        ToolParameter("titel", "string", "Titel des PDF-Dokuments."),
        ToolParameter("inhalt", "string", "Vollstaendiger gegliederter Inhalt."),
        ToolParameter(
            "pfad", "string", "Optionaler Zielpfad mit .pdf-Endung.",
            required=False, default="",
        ),
        ToolParameter(
            "quellen", "string", "Optionale Quellenangaben, eine pro Zeile.",
            required=False, default="",
        ),
        ToolParameter(
            "bilder", "array", "Optionale Liste lokaler Bildpfade.",
            required=False, default=[],
        ),
        ToolParameter(
            "ueberschreiben", "boolean", "Bestehende PDF ersetzen.",
            required=False, default=False,
        ),
    )

    def __init__(self, security: SecurityEngine) -> None:
        self._security = security

    @staticmethod
    def _default_path(title: str) -> Path:
        home = Path.home()
        bases = (
            home / "OneDrive" / "Dokumente",
            home / "Documents",
            home / "Desktop",
        )
        base = next((candidate for candidate in bases if candidate.is_dir()), bases[1])
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        return base / "AI-Orb" / f"{_slug(title)}-{timestamp}.pdf"

    def _bild_aufloesen(self, roh: str) -> Path | None:
        """Prueft einen Bildpfad und sucht ihn notfalls.

        Ein Sprachmodell tippt Pfade gern aus dem Gedaechtnis ab und
        vertauscht dabei einen Ordner oder ein Leerzeichen. Deshalb wird der
        Dateiname zweitens gesucht, bevor das Bild aufgegeben wird - genau
        wie beim Lesen von Dateien.
        """

        text = (roh or "").strip().strip('"').strip("'")
        if not text:
            return None

        entscheidung = self._security.paths.check_read(text)
        if entscheidung.allowed and entscheidung.path.is_file():
            return entscheidung.path

        try:
            from backend.tools.datei_finden import datei_finden

            gefunden, _ = datei_finden(text)
        except Exception:  # noqa: BLE001 - die Suche ist eine Zugabe, keine Pflicht.
            return None
        if gefunden is None:
            return None

        zweite = self._security.paths.check_read(str(gefunden))
        if zweite.allowed and zweite.path.is_file():
            logger.info("Bildpfad korrigiert: '%s' -> '%s'.", text, zweite.path)
            return zweite.path
        return None

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        title = _plain(arguments.get("titel", "")).strip()
        content = _plain(arguments.get("inhalt", "")).strip()
        sources = _plain(arguments.get("quellen", "")).strip()
        if not title:
            return ToolResult.failure("Der PDF-Titel fehlt.")
        if len(content) < 40:
            return ToolResult.failure("Der Inhalt ist zu kurz fuer ein sinnvolles PDF.")
        if len(content) > _MAX_CONTENT:
            return ToolResult.failure(
                f"Der Inhalt ist zu lang (Grenze: {_MAX_CONTENT} Zeichen)."
            )

        requested = str(arguments.get("pfad", "") or "").strip()
        path = Path(requested) if requested else self._default_path(title)
        if path.suffix.lower() != ".pdf":
            path = path.with_suffix(".pdf")
        decision = self._security.paths.check_write(path)
        if not decision.allowed:
            return ToolResult.failure(decision.reason)
        path = decision.path
        if path.exists() and not bool(arguments.get("ueberschreiben", False)):
            return ToolResult.failure(
                f"Die PDF gibt es bereits: {path}. Setze 'ueberschreiben' auf true."
            )

        layout = _Layout(title)
        # Bildmarken im Inhalt aufloesen. Der Pfadschutz bleibt dabei bei
        # diesem Werkzeug: Die Satzengine soll nicht entscheiden duerfen,
        # welche Datei gelesen wird.
        layout.render_content(content, bild_aufloeser=self._bild_aufloesen)

        raw_images = arguments.get("bilder") or []
        if isinstance(raw_images, (str, Path)):
            raw_images = [raw_images]
        for item in list(raw_images)[:12]:
            caption = ""
            image_text = item
            if isinstance(item, dict):
                image_text = item.get("pfad") or item.get("path") or ""
                caption = str(item.get("beschriftung") or item.get("caption") or "")
            gefunden = self._bild_aufloesen(str(image_text))
            if gefunden is None:
                layout.fehlende_bilder.append(str(image_text))
                continue
            layout.add_image(gefunden, caption=caption or gefunden.stem)
        ignored_images = layout.fehlende_bilder

        if sources:
            layout.heading("Quellen", level=2)
            for line in sources.splitlines():
                if line.strip():
                    layout.paragraph(line.strip(), bullet="•")

        try:
            payload = _build_pdf(layout, title=title)
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(path.suffix + ".tmp")
            temporary.write_bytes(payload)
            temporary.replace(path)
        except OSError as error:
            return ToolResult.failure(f"Die PDF liess sich nicht speichern: {error}")
        except Exception as error:  # noqa: BLE001
            logger.exception("PDF-Erzeugung fehlgeschlagen.")
            return ToolResult.failure(f"Die PDF-Erzeugung ist fehlgeschlagen: {error}")

        note = ""
        if ignored_images:
            # Beim Namen nennen, nicht nur zaehlen: Wer erfaehrt, WELCHES
            # Bild fehlt, kann es beim naechsten Versuch richtig angeben.
            note = (
                f" Nicht gefunden und deshalb ausgelassen: "
                f"{', '.join(ignored_images[:4])}"
                + (" …" if len(ignored_images) > 4 else "")
                + "."
            )
        bilder = len(layout.images)
        if bilder:
            note = f" {bilder} Bild(er) eingebettet." + note

        logger.info(
            "PDF erzeugt: %s (%d Seiten, %d Bilder, %d Bytes).",
            path, len(layout.pages), bilder, len(payload),
        )
        return ToolResult.success(
            f"Die PDF wurde erstellt: {path} ({len(layout.pages)} Seiten).{note}",
            path=str(path),
            pages=len(layout.pages),
            bytes=len(payload),
            images=bilder,
            ignored_images=ignored_images,
        )


def build_pdf_tools(security: SecurityEngine) -> list[Tool]:
    return [CreatePdfTool(security)]
