"""Pfadschutz – begrenzt jeden Dateizugriff auf freigegebene Ordner.

Die Vorgabe lautet: keine automatische Änderung an produktiven Dateien, und
Suche nur in ausdrücklich genannten Verzeichnissen. Dieses Modul setzt das
technisch durch, statt sich auf die Gutmütigkeit der aufrufenden Module zu
verlassen.

Zwei Angriffe werden ausdrücklich abgewehrt. Erstens der Ausbruch über
``..`` oder über einen absoluten Pfad – dagegen hilft, jeden Pfad vor dem
Vergleich vollständig aufzulösen. Zweitens der Ausbruch über eine
Verknüpfung, die aus einem freigegebenen Ordner hinauszeigt – dagegen hilft,
dass ``Path.resolve`` Verknüpfungen mit auflöst und der Vergleich damit auf
dem tatsächlichen Ziel stattfindet.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from backend.system.logging_setup import get_logger

logger = get_logger(__name__)

#: Dateiendungen, die auch in freigegebenen Ordnern nicht geschrieben werden.
#: Ausführbares soll nicht durch AI-Orb entstehen können.
BLOCKED_WRITE_SUFFIXES: frozenset[str] = frozenset(
    {".exe", ".dll", ".sys", ".bat", ".cmd", ".ps1", ".msi", ".scr", ".com", ".vbs"}
)

#: Dateinamen, die weder gelesen noch geschrieben werden – auch dann nicht,
#: wenn sie in einem freigegebenen Ordner liegen.
BLOCKED_NAMES: frozenset[str] = frozenset({".env", "id_rsa", "id_ed25519", ".npmrc", ".netrc"})


#: Die bekannten persönlichen Ordner, unter ihren deutschen und englischen
#: Namen. Rechts stehen die Ordnernamen, unter denen sie im Heimatordner
#: liegen können, und die GUID, unter der Windows selbst danach gefragt
#: werden kann.
#:
#: Warum das nötig ist: Fragt jemand "zeig mir, was in meinem
#: Dokumente-Ordner liegt", ruft das Modell ``ordner_auflisten`` mit dem
#: blossen Wort ``Dokumente`` auf. Ein blosser Name ist ein relativer Pfad,
#: und der wurde bis zum 01.09.2026 gegen das Arbeitsverzeichnis aufgeloest -
#: also gegen den Programmordner. Im echten Messlauf kam dabei
#: ``WinError 3: Das System kann den angegebenen Pfad nicht finden:
#: 'C:\Users\info\AI-Orb\Dokumente'`` heraus.
#:
#: Die Reihenfolge der Aufloesung ist wichtig: Ein relativer Pfad, den es
#: im Arbeitsverzeichnis WIRKLICH gibt, bleibt ein Projektpfad. Erst wenn
#: es ihn dort nicht gibt, wird nach dem persoenlichen Ordner gesucht.
#: Sonst wuerde ein Projektordner namens "Bilder" ploetzlich woanders
#: hinzeigen.
BEKANNTE_ORDNER: dict[str, tuple[str, tuple[str, ...]]] = {
    "dokumente": ("{FDD39AD0-238F-46AF-ADB4-6C85480369C7}", ("Documents", "Dokumente")),
    "documents": ("{FDD39AD0-238F-46AF-ADB4-6C85480369C7}", ("Documents", "Dokumente")),
    "downloads": ("{374DE290-123F-4565-9164-39C4925E467B}", ("Downloads",)),
    "download": ("{374DE290-123F-4565-9164-39C4925E467B}", ("Downloads",)),
    "bilder": ("{33E28130-4E1E-4676-835A-98395C3BC3BB}", ("Pictures", "Bilder")),
    "fotos": ("{33E28130-4E1E-4676-835A-98395C3BC3BB}", ("Pictures", "Bilder")),
    "pictures": ("{33E28130-4E1E-4676-835A-98395C3BC3BB}", ("Pictures", "Bilder")),
    "musik": ("{4BD8D571-6D19-48D3-BE97-422220080E43}", ("Music", "Musik")),
    "music": ("{4BD8D571-6D19-48D3-BE97-422220080E43}", ("Music", "Musik")),
    "videos": ("{18989B1D-99B5-455B-841C-AB7C74E4DDFC}", ("Videos",)),
    "schreibtisch": ("{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}", ("Desktop", "Schreibtisch")),
    "desktop": ("{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}", ("Desktop", "Schreibtisch")),
}


def _windows_bekannter_ordner(guid: str) -> Path | None:
    """Fragt Windows selbst, wo ein persönlicher Ordner liegt.

    Der Umweg über die Systemauskunft ist kein Selbstzweck: Auf Rechnern
    mit OneDrive liegt "Dokumente" nicht unter ``%USERPROFILE%\Documents``,
    sondern in einem umgeleiteten OneDrive-Ordner, dessen Name auch noch
    vom Konto abhängt. Nur Windows weiss verlässlich, wo er steht.
    """

    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class _GUID(ctypes.Structure):
            _fields_ = [
                ("Data1", wintypes.DWORD),
                ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD),
                ("Data4", ctypes.c_ubyte * 8),
            ]

        kennung = _GUID()
        if ctypes.windll.ole32.CLSIDFromString(guid, ctypes.byref(kennung)) != 0:
            return None
        zeiger = ctypes.c_wchar_p()
        ergebnis = ctypes.windll.shell32.SHGetKnownFolderPath(
            ctypes.byref(kennung), 0, None, ctypes.byref(zeiger)
        )
        if ergebnis != 0 or not zeiger.value:
            return None
        pfad = Path(zeiger.value)
        ctypes.windll.ole32.CoTaskMemFree(zeiger)
        return pfad
    except Exception:  # noqa: BLE001 - eine Pfadfrage darf nichts reissen.
        logger.debug("Windows-Ordnerauskunft nicht verfuegbar.", exc_info=True)
        return None


def bekannten_ordner_finden(name: str) -> Path | None:
    """Sucht den persönlichen Ordner zu einem Namen wie ``"Dokumente"``.

    Returns:
        Der Ordner, oder ``None``, wenn der Name keiner ist oder es ihn auf
        diesem Rechner nicht gibt.
    """

    schluessel = str(name or "").strip().strip("\"'").lower()
    eintrag = BEKANNTE_ORDNER.get(schluessel)
    if eintrag is None:
        return None
    guid, ordnernamen = eintrag

    vom_system = _windows_bekannter_ordner(guid)
    if vom_system is not None and vom_system.is_dir():
        return vom_system

    try:
        heim = Path.home()
    except (OSError, RuntimeError):
        return None

    # Erst unmittelbar im Heimatordner, dann in einem OneDrive-Ordner -
    # dessen Name traegt oft den Firmen- oder Kontonamen ("OneDrive -
    # Persoenlich"), deshalb ein Muster statt eines festen Namens.
    orte: list[Path] = [heim]
    try:
        orte.extend(sorted(p for p in heim.glob("OneDrive*") if p.is_dir()))
    except OSError:
        pass
    for ort in orte:
        for ordnername in ordnernamen:
            kandidat = ort / ordnername
            if kandidat.is_dir():
                return kandidat
    return None


@dataclass
class PathDecision:
    """Das Ergebnis einer Pfadprüfung."""

    allowed: bool
    #: Der aufgelöste Pfad; bei Ablehnung der ursprünglich angefragte.
    path: Path
    #: Warum abgelehnt wurde – im Klartext für den Benutzer.
    reason: str = ""


class PathGuard:
    """Prüft, ob ein Pfad innerhalb der freigegebenen Ordner liegt."""

    def __init__(self, roots: list[str] | None = None, *, unrestricted: bool = False) -> None:
        """
        Args:
            roots: Freigegebene Ordner. ``~`` wird aufgelöst. Nicht
                vorhandene Ordner werden übergangen, ohne dass das ein
                Fehler wäre – ein Benutzer hat vielleicht kein
                ``Documents``-Verzeichnis.
        """

        #: Alles erlaubt – gesetzt über ``security.mode: offen``.
        #:
        #: Eine ausdrückliche Entscheidung des Benutzers. Der Wächter
        #: bleibt im Aufrufweg stehen und protokolliert weiter; er sagt nur
        #: zu allem ja. Ihn ganz zu entfernen hätte bedeutet, jede
        #: aufrufende Stelle umzubauen – und beim Zurückschalten wieder.
        self._unrestricted = unrestricted

        self._roots: list[Path] = []
        for entry in roots or []:
            try:
                resolved = Path(os.path.expanduser(str(entry))).resolve()
            except (OSError, RuntimeError):
                continue
            if resolved.is_dir():
                self._roots.append(resolved)

    @property
    def roots(self) -> list[Path]:
        """Die tatsächlich vorhandenen freigegebenen Ordner."""

        return list(self._roots)

    def describe_roots(self) -> list[str]:
        """Die freigegebenen Ordner als Text, für die Anzeige."""

        return [str(root) for root in self._roots]

    def _resolve(self, candidate: str | Path) -> Path | None:
        """Löst einen Pfad vollständig auf - auch einen blossen Ordnernamen.

        Drei Stufen, in dieser Reihenfolge:

        1. ``~`` auflösen und den Pfad vollständig auflösen. Ein absoluter
           Pfad und ein relativer, den es im Arbeitsverzeichnis wirklich
           gibt, sind damit fertig - Projektpfade verhalten sich wie zuvor.
        2. Gibt es das Aufgelöste nicht und war die Angabe relativ, wird
           ihr erstes Stück als persönlicher Ordner gedeutet
           (``Dokumente``, ``Downloads``, ``Bilder`` …). Der Rest wird
           angehängt, damit auch ``Dokumente/Rechnungen`` ankommt.
        3. Bleibt auch das erfolglos, gilt wieder Stufe 1 - damit die
           Fehlermeldung den Pfad nennt, den der Aufrufer gemeint hat.
        """

        text = str(candidate).strip().strip('"')
        try:
            aufgeloest = Path(os.path.expanduser(text)).resolve()
        except (OSError, RuntimeError, ValueError):
            return None

        if aufgeloest.exists():
            return aufgeloest

        roh = Path(os.path.expanduser(text))
        if roh.is_absolute() or not roh.parts:
            return aufgeloest

        persoenlich = bekannten_ordner_finden(roh.parts[0])
        if persoenlich is None:
            return aufgeloest

        try:
            ziel = persoenlich.joinpath(*roh.parts[1:]).resolve()
        except (OSError, RuntimeError, ValueError):
            return aufgeloest
        logger.debug("'%s' als persoenlicher Ordner gedeutet: %s", text, ziel)
        return ziel

    def _offen(self, candidate: str | Path) -> PathDecision:
        """Die Antwort im offenen Modus – erlaubt, aber trotzdem aufgelöst.

        Der aufgelöste Pfad ist hier kein Beiwerk: Jede aufrufende Stelle
        erwartet ein ``Path`` und arbeitet damit weiter (``is_file()``,
        ``read_text()``). Vorher stand hier die blosse Zeichenkette – im
        offenen Modus scheiterte deshalb jedes Werkzeug, das den Pfad
        benutzte, an einem AttributeError statt an einer Pfadfrage.

        Auch ``~`` und relative Angaben werden aufgelöst. Wer den Modus
        aufmacht, will keine Pfadprüfung – aber er will trotzdem, dass
        „~/Desktop/notiz.txt" dort landet, wo er es erwartet.
        """

        resolved = self._resolve(candidate)
        if resolved is None:
            return PathDecision(False, Path(str(candidate)), "Der Pfad ist ungültig.")
        return PathDecision(True, resolved, "Offener Modus – jeder Pfad ist erlaubt.")

    def check_read(self, candidate: str | Path) -> PathDecision:
        """Prüft, ob eine Datei gelesen werden darf."""

        if self._unrestricted:
            return self._offen(candidate)

        resolved = self._resolve(candidate)
        if resolved is None:
            return PathDecision(False, Path(str(candidate)), "Der Pfad ist ungültig.")

        if resolved.name.lower() in BLOCKED_NAMES:
            return PathDecision(
                False,
                resolved,
                "Diese Datei enthält typischerweise Zugangsdaten und ist gesperrt.",
            )

        if not self._roots:
            return PathDecision(
                False,
                resolved,
                "Es ist kein Ordner freigegeben. Trage einen unter "
                "'desktop.file_search_roots' in config.yaml ein.",
            )

        for root in self._roots:
            if resolved == root or root in resolved.parents:
                return PathDecision(True, resolved)

        return PathDecision(
            False,
            resolved,
            "Der Pfad liegt außerhalb der freigegebenen Ordner: "
            + ", ".join(self.describe_roots()),
        )

    def check_write(self, candidate: str | Path) -> PathDecision:
        """Prüft, ob eine Datei geschrieben werden darf.

        Strenger als das Lesen: Ausführbares ist auch in freigegebenen
        Ordnern gesperrt, und in den Projektordner von AI-Orb selbst wird
        nicht geschrieben.
        """

        if self._unrestricted:
            return self._offen(candidate)

        decision = self.check_read(candidate)
        if not decision.allowed:
            return decision

        resolved = decision.path

        if resolved.suffix.lower() in BLOCKED_WRITE_SUFFIXES:
            return PathDecision(
                False,
                resolved,
                f"Dateien vom Typ '{resolved.suffix}' werden nicht geschrieben, "
                "weil sie ausführbar sind.",
            )

        project_root = Path(__file__).resolve().parents[2]
        if resolved == project_root or project_root in resolved.parents:
            return PathDecision(
                False,
                resolved,
                "In den eigenen Programmordner schreibt AI-Orb nicht. "
                "Änderungen am eigenen Code laufen ausschließlich über die "
                "Evolution Engine mit ausdrücklicher Freigabe.",
            )

        return PathDecision(True, resolved)

    def check_directory(self, candidate: str | Path) -> PathDecision:
        """Prüft, ob ein Ordner aufgelistet werden darf."""

        if self._unrestricted:
            return self._offen(candidate)

        decision = self.check_read(candidate)
        if not decision.allowed:
            return decision
        if not decision.path.is_dir():
            return PathDecision(False, decision.path, "Das ist kein Ordner.")
        return decision

    def status(self) -> dict[str, object]:
        """Statusangaben für die Transparenzansicht."""

        return {
            "roots": self.describe_roots(),
            "blocked_write_suffixes": sorted(BLOCKED_WRITE_SUFFIXES),
            "blocked_names": sorted(BLOCKED_NAMES),
        }
