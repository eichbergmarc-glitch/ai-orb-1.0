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
        try:
            return Path(os.path.expanduser(str(candidate))).resolve()
        except (OSError, RuntimeError, ValueError):
            return None

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
