"""Berechtigungsmodell.

Jede Fähigkeit, die AI-Orb über das reine Antworten hinaus hat, ist an eine
Berechtigung gebunden. Die Berechtigungen sind hier abschließend aufgezählt –
ein Modul kann sich keine neue ausdenken, denn eine unbekannte Berechtigung
gilt als verweigert.

Die Einstufung folgt einem einfachen Gedanken: Wie schwer wiegt es, wenn
diese Fähigkeit missbraucht wird? Etwas zu lesen ist zurücknehmbar, etwas zu
löschen nicht. Danach richtet sich, ob eine Zustimmung nötig ist und ob sie
für die Zukunft gemerkt werden darf.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class RiskLevel(Enum):
    """Wie schwer eine Aktion wiegt."""

    #: Rein lesend, ohne Wirkung nach außen.
    SAFE = "unbedenklich"
    #: Wirkt nach außen, ist aber zurücknehmbar.
    MODERATE = "abwaegbar"
    #: Verändert das System oder gibt Daten preis, schwer zurücknehmbar.
    HIGH = "heikel"
    #: Nicht zurücknehmbar. Jedes Mal einzeln zu bestätigen.
    CRITICAL = "kritisch"


@dataclass(frozen=True)
class Permission:
    """Eine einzelne Berechtigung."""

    #: Eindeutiger Name, wie er in Manifesten und Konfiguration steht.
    name: str
    #: Was die Berechtigung erlaubt – wird dem Benutzer wörtlich angezeigt.
    description: str
    #: Die Einstufung.
    risk: RiskLevel
    #: Ob eine einmal erteilte Zustimmung gemerkt werden darf.
    #: Bei kritischen Aktionen niemals.
    remembering_allowed: bool = True

    @property
    def requires_consent(self) -> bool:
        """Ob vor der Ausführung gefragt werden muss."""

        return self.risk is not RiskLevel.SAFE

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "description": self.description,
            "risk": self.risk.value,
            "requires_consent": self.requires_consent,
            "remembering_allowed": self.remembering_allowed,
        }


def _permission(
    name: str,
    description: str,
    risk: RiskLevel,
    *,
    remembering_allowed: bool = True,
) -> Permission:
    return Permission(
        name=name,
        description=description,
        risk=risk,
        remembering_allowed=remembering_allowed and risk is not RiskLevel.CRITICAL,
    )


#: Alle bekannten Berechtigungen. Was hier nicht steht, ist verboten.
KNOWN_PERMISSIONS: dict[str, Permission] = {
    permission.name: permission
    for permission in (
        _permission(
            "read_files",
            "Dateien in den freigegebenen Ordnern lesen",
            RiskLevel.MODERATE,
        ),
        _permission(
            "write_files",
            "Dateien in den freigegebenen Ordnern anlegen und ändern",
            RiskLevel.HIGH,
        ),
        _permission(
            "delete_files",
            "Dateien löschen",
            RiskLevel.CRITICAL,
        ),
        _permission(
            "list_directory",
            "Ordnerinhalte auflisten",
            RiskLevel.MODERATE,
        ),
        _permission(
            "search_files",
            "In den freigegebenen Ordnern nach Dateien suchen",
            RiskLevel.MODERATE,
        ),
        _permission(
            "launch_application",
            "Ein Programm aus der freigegebenen Liste starten",
            RiskLevel.HIGH,
        ),
        _permission(
            "terminate_process",
            "Ein laufendes Programm beenden",
            RiskLevel.CRITICAL,
        ),
        _permission(
            "system_commands",
            "Beliebige Systembefehle ausführen",
            RiskLevel.CRITICAL,
        ),
        _permission(
            "microphone",
            "Das Mikrofon abhören",
            RiskLevel.HIGH,
        ),
        _permission(
            "camera",
            "Die Kamera verwenden",
            RiskLevel.HIGH,
        ),
        _permission(
            "screen_capture",
            "Den Bildschirminhalt aufnehmen",
            RiskLevel.HIGH,
        ),
        _permission(
            "network",
            "Verbindungen ins Internet aufbauen",
            RiskLevel.HIGH,
        ),
        _permission(
            "send_code_external",
            "Quellcode an einen externen Dienst übertragen",
            RiskLevel.CRITICAL,
        ),
        _permission(
            "modify_own_code",
            "Den eigenen Quellcode verändern",
            RiskLevel.CRITICAL,
        ),
        _permission(
            "install_dependencies",
            "Zusätzliche Softwarepakete installieren",
            RiskLevel.CRITICAL,
        ),
        _permission(
            "read_clipboard",
            "Die Zwischenablage lesen",
            RiskLevel.HIGH,
        ),
        _permission(
            "read_memory",
            "Auf das Gedächtnis von AI-Orb zugreifen",
            RiskLevel.SAFE,
        ),
        _permission(
            "read_bookmarks",
            "Die Browser-Favoriten lesen (fuer Recherchen)",
            RiskLevel.MODERATE,
        ),
        _permission(
            "read_email",
            "E-Mails lesen, suchen und zusammenfassen",
            RiskLevel.HIGH,
        ),
        _permission(
            "send_email",
            "Eine E-Mail versenden",
            RiskLevel.CRITICAL,
        ),
        _permission(
            "read_time",
            "Datum und Uhrzeit abfragen",
            RiskLevel.SAFE,
        ),
        _permission(
            "compute",
            "Rechnen und Text umformen",
            RiskLevel.SAFE,
        ),
    )
}


def get_permission(name: str) -> Permission | None:
    """Sucht eine Berechtigung. Unbekannte Namen ergeben ``None``."""

    return KNOWN_PERMISSIONS.get(name.strip().lower())


def describe(names: list[str]) -> list[dict[str, object]]:
    """Beschreibt mehrere Berechtigungen für die Anzeige.

    Unbekannte Namen erscheinen ausdrücklich als unbekannt, statt still
    zu verschwinden – der Benutzer soll sehen, wenn etwas Fremdes verlangt
    wird.
    """

    result: list[dict[str, object]] = []
    for name in names:
        permission = get_permission(name)
        if permission is None:
            result.append(
                {
                    "name": name,
                    "description": "Unbekannte Berechtigung – wird verweigert",
                    "risk": RiskLevel.CRITICAL.value,
                    "requires_consent": True,
                    "remembering_allowed": False,
                    "unknown": True,
                }
            )
        else:
            result.append(permission.to_dict())
    return result


def highest_risk(names: list[str]) -> RiskLevel:
    """Die höchste Einstufung einer Menge von Berechtigungen."""

    order = [RiskLevel.SAFE, RiskLevel.MODERATE, RiskLevel.HIGH, RiskLevel.CRITICAL]
    highest = RiskLevel.SAFE
    for name in names:
        permission = get_permission(name)
        # Unbekanntes gilt als kritisch.
        level = permission.risk if permission is not None else RiskLevel.CRITICAL
        if order.index(level) > order.index(highest):
            highest = level
    return highest
