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

        if console_output:
            console_handler = logging.StreamHandler(stream=sys.stdout)
            console_handler.setFormatter(formatter)
            root_logger.addHandler(console_handler)

        _is_configured = True
        root_logger.info(
            "Logging initialisiert (Level=%s, Verzeichnis=%s)",
            level_name,
            logs_dir,
        )


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
