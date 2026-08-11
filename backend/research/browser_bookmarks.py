"""Liest die Favoriten aus Microsoft Edge (und verwandten Browsern).

Wer wissenschaftlich arbeitet, sammelt Quellen über Jahre: Archivbestände,
Datenbanken, Zeitschriftenportale, Nachschlagewerke, einzelne Aufsätze. Diese
Sammlung steht meist in den Browser-Favoriten und nirgends sonst. Sie ist
damit die genaueste Beschreibung dessen, womit jemand tatsächlich arbeitet –
genauer als jede Liste, die er auf Nachfrage aufschreiben würde.

Der Orb liest sie, um zu wissen, wo er nachsehen soll, wenn eine Frage in
ein Fachgebiet fällt. Ordnernamen werden dabei mitgeführt: Wer einen Ordner
„Reformation" angelegt hat, hat damit eine Aussage über seine Quellen
getroffen, die kein Titel allein hergibt.

**Gelesen wird ausschließlich.** Die Datei wird nie geschrieben und nie
verschoben; sie gehört dem Browser. Übertragen wird ohne ausdrückliche
Zustimmung ebenfalls nichts – die Favoriten eines Menschen sind eine
Aussage über ihn, und zwar eine ziemlich vollständige.

Die Datei ist gewöhnliches JSON, ohne Sperre lesbar, auch während der
Browser läuft. Chrome, Brave, Vivaldi und Opera benutzen dasselbe Format;
sie werden deshalb gleich mitgenommen, ohne dass es Mehraufwand wäre.
"""

from __future__ import annotations

import json
import os
import platform
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from backend.system.logging_setup import get_logger

logger = get_logger(__name__)


@dataclass(slots=True)
class Bookmark:
    """Ein einzelner Favorit."""

    title: str
    url: str
    #: Der Ordnerpfad, in dem er liegt – z. B. ``["Geschichte", "Reformation"]``.
    folders: list[str] = field(default_factory=list)
    #: Aus welchem Browser er stammt.
    browser: str = ""

    @property
    def folder_path(self) -> str:
        """Der Ordnerpfad als lesbare Zeichenkette."""

        return " / ".join(self.folders) if self.folders else "(oberste Ebene)"

    @property
    def domain(self) -> str:
        """Die Domain – nützlich zum Gruppieren nach Quelle."""

        rest = self.url.split("://", 1)[-1]
        return rest.split("/", 1)[0].removeprefix("www.").lower()

    def to_dict(self) -> dict[str, Any]:
        return {
            "titel": self.title,
            "url": self.url,
            "ordner": self.folder_path,
            "domain": self.domain,
            "browser": self.browser,
        }

    def matches(self, needle: str) -> bool:
        """Ob der Suchbegriff auf diesen Favoriten passt.

        Gesucht wird in Titel, Ordnerpfad und Adresse. Der Ordnerpfad ist
        dabei oft der beste Treffer: Ein Aufsatz mit dem Titel „Ein
        vergessener Streit" verrät nichts, der Ordner „Sonderwegsthese"
        alles.
        """

        haystack = f"{self.title} {self.folder_path} {self.url}".lower()
        return needle.lower().strip() in haystack


#: Browser, die das Chromium-Favoritenformat benutzen, mit ihrem Ordnernamen
#: unterhalb von %LOCALAPPDATA%.
_CHROMIUM_BROWSERS: tuple[tuple[str, str], ...] = (
    ("Microsoft Edge", "Microsoft/Edge/User Data"),
    ("Google Chrome", "Google/Chrome/User Data"),
    ("Brave", "BraveSoftware/Brave-Browser/User Data"),
    ("Vivaldi", "Vivaldi/User Data"),
    ("Opera", "Opera Software/Opera Stable"),
)


def _profile_directories(user_data: Path) -> Iterator[Path]:
    """Findet die Profilordner eines Chromium-Browsers.

    Es gibt selten nur eines. Wer beruflich und privat trennt, hat
    „Default" und „Profile 1"; wer die Arbeit eines Kollegen übernommen
    hat, unter Umständen mehr. Alle zu lesen ist billiger, als den
    richtigen zu erraten.
    """

    if not user_data.is_dir():
        return

    for entry in sorted(user_data.iterdir()):
        if not entry.is_dir():
            continue
        if entry.name == "Default" or entry.name.startswith("Profile"):
            yield entry


def _bookmark_files() -> Iterator[tuple[str, Path]]:
    """Findet alle Favoritendateien auf diesem Rechner."""

    if platform.system() != "Windows":
        # Unter Linux/macOS liegen sie anderswo. AI-Orb ist für Windows
        # gebaut; hier still nichts zu liefern ist ehrlicher, als einen
        # Pfad zu raten.
        return

    local = os.environ.get("LOCALAPPDATA", "")
    if not local:
        return

    base = Path(local)
    for name, relative in _CHROMIUM_BROWSERS:
        for profile in _profile_directories(base / relative):
            candidate = profile / "Bookmarks"
            if candidate.is_file():
                label = name if profile.name == "Default" else f"{name} ({profile.name})"
                yield label, candidate


def _walk(node: dict[str, Any], folders: list[str], browser: str) -> Iterator[Bookmark]:
    """Läuft den Favoritenbaum ab."""

    node_type = node.get("type")

    if node_type == "url":
        url = str(node.get("url", "")).strip()
        # javascript:-Lesezeichen und leere Einträge sind keine Quellen.
        if url and not url.lower().startswith("javascript:"):
            yield Bookmark(
                title=str(node.get("name", "")).strip() or url,
                url=url,
                folders=list(folders),
                browser=browser,
            )
        return

    if node_type == "folder" or "children" in node:
        name = str(node.get("name", "")).strip()
        # Die drei Wurzeln („Bookmarks bar", „Other bookmarks", „Mobile")
        # sind Verwaltung, keine Ordnung des Benutzers.
        deeper = folders if not name or not folders and name in _ROOT_NAMES else [*folders, name]
        for child in node.get("children", []) or []:
            if isinstance(child, dict):
                yield from _walk(child, deeper, browser)


#: Namen der technischen Wurzelordner, die keine Aussage des Benutzers sind.
_ROOT_NAMES = {
    "Bookmarks bar",
    "Favoritenleiste",
    "Other bookmarks",
    "Weitere Favoriten",
    "Mobile bookmarks",
    "Mobile Favoriten",
    "Synced Bookmarks",
}


def read_bookmarks(*, limit: int = 5000) -> list[Bookmark]:
    """Liest alle Favoriten dieses Rechners.

    Args:
        limit: Obergrenze. Wer zehntausend Favoriten hat, braucht sie
            nicht alle auf einmal – und ein Modellkontext erst recht nicht.

    Returns:
        Die gefundenen Favoriten. Eine leere Liste, wenn keiner der
        unterstützten Browser installiert ist; das ist kein Fehler.
    """

    found: list[Bookmark] = []

    for browser, path in _bookmark_files():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            logger.warning("Favoriten aus %s nicht lesbar: %s", browser, error)
            continue

        roots = raw.get("roots", {})
        if not isinstance(roots, dict):
            continue

        for root in roots.values():
            if isinstance(root, dict):
                found.extend(_walk(root, [], browser))

        if len(found) >= limit:
            break

    # Doppelte Adressen zusammenführen: Wer eine Quelle in zwei Browsern
    # hat, hat sie einmal.
    seen: set[str] = set()
    unique: list[Bookmark] = []
    for bookmark in found:
        key = bookmark.url.rstrip("/").lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(bookmark)

    logger.info("%d Favoriten gelesen.", len(unique))
    return unique[:limit]


def search_bookmarks(needle: str, *, limit: int = 25) -> list[Bookmark]:
    """Sucht in den Favoriten.

    Args:
        needle: Der Suchbegriff. Leer liefert die ersten Einträge.
        limit: Höchstzahl der Treffer.
    """

    bookmarks = read_bookmarks()
    if not needle.strip():
        return bookmarks[:limit]

    hits = [bookmark for bookmark in bookmarks if bookmark.matches(needle)]

    # Treffer im Ordnernamen zuerst: Sie sind die verlässlichere Aussage
    # über das Thema als ein zufälliges Wort im Titel.
    hits.sort(key=lambda bookmark: (needle.lower() not in bookmark.folder_path.lower(),))
    return hits[:limit]


def folder_overview() -> dict[str, int]:
    """Wie viele Favoriten je Ordner – ein Bild der Arbeitsschwerpunkte.

    Nützlich, wenn der Orb wissen will, womit sich jemand beschäftigt,
    ohne dass er danach fragen muss.
    """

    counts: dict[str, int] = {}
    for bookmark in read_bookmarks():
        counts[bookmark.folder_path] = counts.get(bookmark.folder_path, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: item[1], reverse=True))


def describe() -> dict[str, Any]:
    """Was gefunden wurde – für die Transparenzansicht."""

    sources = [{"browser": name, "datei": str(path)} for name, path in _bookmark_files()]
    return {
        "quellen": sources,
        "anzahl": len(read_bookmarks()) if sources else 0,
        "hinweis": (
            "Es wird ausschließlich gelesen. Favoriten werden nicht "
            "übertragen, solange du nicht ausdrücklich zustimmst."
        ),
    }
