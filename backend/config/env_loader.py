"""Liest die Datei ``.env`` ohne externe Abhängigkeit.

AI-Orb speichert Zugangsdaten niemals in ``config.yaml``, sondern in einer
Datei ``.env`` im Projekt-Root. Dieses Modul liest sie beim Start ein und
stellt die Werte als Umgebungsvariablen bereit, aus denen die Provider ihre
Schlüssel beziehen.

Bewusst mit der Standardbibliothek umgesetzt: Eine zusätzliche Abhängigkeit
nur zum Lesen von Schlüssel-Wert-Paaren wäre eine unnötige Fehlerquelle bei
der Installation.

Bereits gesetzte Umgebungsvariablen werden **nicht** überschrieben. Wer
einen Schlüssel in der Systemumgebung hinterlegt hat, behält damit die
Kontrolle; die Datei dient nur als bequeme Voreinstellung.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from backend.utils.paths import get_env_path

# Bewusst der Standard-Logger statt backend.system.logging_setup: Jenes
# Modul liest seinerseits die Konfiguration und würde hier zu einem
# zirkulären Import führen. Über den Namensraum "ai_orb." greifen dennoch
# dieselben Handler, sobald das Logging eingerichtet ist.
logger = logging.getLogger(f"ai_orb.{__name__}")


def parse_env_text(text: str) -> dict[str, str]:
    """Zerlegt den Inhalt einer ``.env``-Datei in Schlüssel-Wert-Paare.

    Unterstützt Kommentarzeilen, leere Zeilen, ein vorangestelltes
    ``export`` sowie Werte in einfachen oder doppelten Anführungszeichen.
    Zeilen ohne Gleichheitszeichen werden übergangen.

    Args:
        text: Der Inhalt der Datei.

    Returns:
        Die gefundenen Schlüssel-Wert-Paare.
    """

    values: dict[str, str] = {}

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()

        key, separator, value = line.partition("=")
        if not separator:
            continue

        key = key.strip()
        if not key:
            continue

        value = value.strip()
        # Ein Kommentar hinter einem unquotierten Wert wird abgeschnitten.
        if value and value[0] not in "\"'":
            value = value.split(" #", 1)[0].strip()
        elif len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]

        values[key] = value

    return values


def load_env_file(path: Path | None = None, *, override: bool = False) -> list[str]:
    """Lädt ``.env`` in die Umgebungsvariablen des Prozesses.

    Args:
        path: Pfad zur Datei. Standard ist ``.env`` im Projekt-Root.
        override: Wenn ``True``, werden bereits gesetzte Umgebungsvariablen
            überschrieben. Standard ist ``False``, damit die Systemumgebung
            Vorrang behält.

    Returns:
        Die Namen der tatsächlich gesetzten Variablen. Leere Werte werden
        übergangen, damit ein unausgefüllter Platzhalter aus der Vorlage
        keinen echten Schlüssel verdeckt.
    """

    env_path = path or get_env_path()

    if not env_path.exists():
        logger.debug("Keine .env gefunden (%s) – das ist kein Fehler.", env_path)
        return []

    try:
        text = env_path.read_text(encoding="utf-8")
    except OSError as error:
        logger.warning(".env konnte nicht gelesen werden: %s", error)
        return []

    applied: list[str] = []
    for key, value in parse_env_text(text).items():
        if not value:
            continue
        if not override and os.environ.get(key):
            continue
        os.environ[key] = value
        applied.append(key)

    if applied:
        # Die Namen werden protokolliert, die Werte selbstverständlich nicht.
        logger.info("Aus .env übernommen: %s", ", ".join(sorted(applied)))

    return applied
