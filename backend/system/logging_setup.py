"""Zentrales Logging-System von AI-Orb.

Jedes Modul besitzt sein eigenes benanntes Logger-Objekt (sichtbar am
Modulnamen in jeder Log-Zeile), gleichzeitig schreiben alle Module
zusätzlich in ein gemeinsames Systemlog (``logs/system.log``). Die
Konfiguration (Level, Rotation, Konsolenausgabe) stammt ausschließlich aus
``config.yaml``.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
import threading

from backend.config import get_config
from backend.utils.paths import get_logs_dir

_setup_lock = threading.Lock()
_is_configured = False

_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)-28s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging() -> None:
    """Konfiguriert das zentrale Logging genau einmal pro Prozess.

    Liest Level, Zielverzeichnis, Rotationsgröße, Anzahl der Backups und ob
    zusätzlich auf der Konsole geloggt werden soll aus dem Abschnitt
    ``logging`` in ``config.yaml``. Wiederholte Aufrufe sind sicher (No-Op),
    sodass Module ``setup_logging()`` unbesorgt bei ihrem Import aufrufen
    dürfen.
    """

    global _is_configured
    if _is_configured:
        return

    with _setup_lock:
        if _is_configured:
            return

        config = get_config()
        log_section = config.section("logging")

        level_name = str(log_section.get("level", "INFO")).upper()
        level = getattr(logging, level_name, logging.INFO)
        max_bytes = int(log_section.get("max_file_size_mb", 5)) * 1024 * 1024
        backup_count = int(log_section.get("backup_count", 5))
        console_output = bool(log_section.get("console_output", True))

        logs_dir = get_logs_dir()
        formatter = logging.Formatter(fmt=_LOG_FORMAT, datefmt=_DATE_FORMAT)

        root_logger = logging.getLogger("ai_orb")
        root_logger.setLevel(level)
        root_logger.propagate = False

        # Zentrales Systemlog (gemeinsam für alle Module).
        system_handler = logging.handlers.RotatingFileHandler(
            logs_dir / "system.log",
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        system_handler.setFormatter(formatter)
        root_logger.addHandler(system_handler)

        # Die Startmeldung geht in die Datei, nicht auf den Bildschirm.
        #
        # Sie stand bisher am Anfang JEDER Ausgabe - auch der von
        # "python -m backend.lernen.messen --bericht", die reines JSON sein
        # soll. Am 01.09.2026 begann die Berichtsdatei des ersten echten
        # Messlaufs mit "Logging initialisiert ..." und liess sich nicht
        # einlesen. Im Systemprotokoll steht sie weiterhin, und dort gehoert
        # sie hin: Sie interessiert bei der Fehlersuche, nicht beim Lesen
        # eines Messberichts.
        _is_configured = True
        root_logger.info(
            "Logging initialisiert (Level=%s, Verzeichnis=%s)",
            level_name,
            logs_dir,
        )

        if console_output:
            console_handler = logging.StreamHandler(stream=_konsolenstrom())
            console_handler.setFormatter(formatter)
            root_logger.addHandler(console_handler)


def _konsolenstrom():
    """Macht die Standardausgabe unicodefest - vor allem unter Windows.

    Sobald die Ausgabe dort in eine Datei umgeleitet wird, verwendet Python
    die Gebietsschema-Kodierung (cp1252). Ein einziges Zeichen ausserhalb
    davon laesst dann den Protokollaufruf mit ``UnicodeEncodeError``
    abbrechen - beim echten Messlauf am 01.09.2026 belegt an der Meldung
    "Providerwechsel: None \u2192 claude_code". Die Messung lief weiter,
    aber jede solche Meldung warf einen Stapelauszug in die Ausgabe und
    machte das Protokoll unlesbar.

    Zwei Stufen, beide ohne Nebenwirkung, wenn sie nicht greifen:
    erst auf UTF-8 umstellen, ersatzweise wenigstens die Fehlerbehandlung
    auf "ersetzen" setzen. Ein Strom ohne ``reconfigure`` (etwa ein
    umgelenkter Testpuffer) bleibt unangetastet.
    """

    strom = sys.stdout
    umstellen = getattr(strom, "reconfigure", None)
    if umstellen is None:
        return strom
    try:
        umstellen(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001 - Protokollierung darf nie der Grund sein.
        try:
            umstellen(errors="replace")
        except Exception:  # noqa: BLE001
            pass
    return strom


def get_logger(module_name: str) -> logging.Logger:
    """Gibt einen benannten Logger für ``module_name`` zurück.

    Ruft bei Bedarf automatisch :func:`setup_logging` auf, damit jedes Modul
    unabhängig von der Startreihenfolge korrekt konfiguriertes Logging
    erhält. Zusätzlich zum zentralen Systemlog erhält jedes Modul eine
    eigene rotierende Log-Datei unter ``logs/<modulname>.log``.

    Args:
        module_name: Vollqualifizierter Modulname, üblicherweise
            ``__name__`` des aufrufenden Moduls.

    Returns:
        logging.Logger: Konfigurierter Logger.
    """

    setup_logging()

    logger = logging.getLogger(f"ai_orb.{module_name}")

    # Eigene Log-Datei pro Modul nur einmal anlegen.
    has_module_handler = any(
        isinstance(handler, logging.handlers.RotatingFileHandler)
        and getattr(handler, "_ai_orb_module", None) == module_name
        for handler in logger.handlers
    )

    if not has_module_handler:
        config = get_config()
        log_section = config.section("logging")
        max_bytes = int(log_section.get("max_file_size_mb", 5)) * 1024 * 1024
        backup_count = int(log_section.get("backup_count", 5))

        logs_dir = get_logs_dir()
        safe_name = module_name.replace(".", "_")
        file_handler = logging.handlers.RotatingFileHandler(
            logs_dir / f"{safe_name}.log",
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setFormatter(
            logging.Formatter(fmt=_LOG_FORMAT, datefmt=_DATE_FORMAT)
        )
        file_handler._ai_orb_module = module_name  # type: ignore[attr-defined]
        logger.addHandler(file_handler)
        logger.propagate = True

    return logger
