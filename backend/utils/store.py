"""Persistenz-Helfer für lokal gespeicherte JSON-Daten.

Alle AI-Orb-Daten werden ausschließlich lokal im Verzeichnis ``data/``
abgelegt (siehe Datenschutzvorgabe: keine Cloud, keine automatische
Übertragung). Dieses Modul kapselt das atomare Lesen und Schreiben, damit
ein Absturz während des Schreibvorgangs keine Datei beschädigen kann.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from backend.system.logging_setup import get_logger
from backend.utils.paths import get_data_dir

logger = get_logger(__name__)


class JsonStore:
    """Einfacher, thread-sicherer JSON-Dokumentspeicher.

    Jede Instanz verwaltet genau eine Datei unterhalb von ``data/``. Der
    Inhalt wird im Speicher gehalten und bei jeder Änderung atomar auf die
    Festplatte geschrieben.
    """

    def __init__(self, filename: str, default: dict[str, Any] | None = None) -> None:
        self._path: Path = get_data_dir() / filename
        self._lock = threading.RLock()
        self._default: dict[str, Any] = default if default is not None else {}
        self._data: dict[str, Any] = {}
        self.load()

    # --- Laden / Speichern -------------------------------------------------

    def load(self) -> None:
        """Liest die Datei ein; fehlt sie oder ist sie beschädigt, wird der
        Standardinhalt verwendet."""

        with self._lock:
            if not self._path.exists():
                self._data = json.loads(json.dumps(self._default))
                return
            try:
                with self._path.open("r", encoding="utf-8") as handle:
                    loaded = json.load(handle)
                self._data = loaded if isinstance(loaded, dict) else dict(self._default)
            except (json.JSONDecodeError, OSError):
                # Beschädigte Datei nicht löschen, sondern beiseitelegen,
                # damit der Benutzer sie noch einsehen kann.
                backup = self._path.with_suffix(self._path.suffix + ".corrupt")
                try:
                    os.replace(self._path, backup)
                except OSError:
                    pass
                self._data = json.loads(json.dumps(self._default))

    def save(self) -> None:
        """Schreibt den aktuellen Inhalt atomar auf die Festplatte."""

        with self._lock:
            payload = json.dumps(self._data, ensure_ascii=False, indent=2, default=str)
            self._path.parent.mkdir(parents=True, exist_ok=True)
            handle = tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=str(self._path.parent),
                delete=False,
            )
            try:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            finally:
                handle.close()
            self._ersetzen(handle.name)

    def _ersetzen(self, quelle: str) -> None:
        """Schiebt die fertige Datei an ihren Platz - notfalls mit Geduld.

        ``os.replace`` ist unter Windows keine sichere Sache, sobald ein
        anderes Programm die Zieldatei geöffnet hält. Genau das tut
        OneDrive, während es synchronisiert, und das Projekt des Benutzers
        liegt in einem OneDrive-Ordner. In seinem Startprotokoll steht der
        Beleg:

            PermissionError: [WinError 5] Zugriff verweigert:
            'data\\tmp2jsna_dt' -> 'data\\bugs.json'

        Der Evolutions-Agent brach daran ab. Er ist nur der Erste, dem es
        auffiel - betroffen ist jede Datei, die der Orb schreibt:
        Gedächtnis, Wissensbasis, Prüfprotokoll, Lernprofil.

        Das Sperren dauert Millisekunden, nicht Sekunden. Es genügt also,
        kurz zu warten und es noch einmal zu versuchen; nach vier
        Anläufen ist etwas anderes im Argen, und dann soll der Fehler auch
        sichtbar werden.
        """

        letzter: OSError | None = None
        for versuch in range(4):
            try:
                os.replace(quelle, self._path)
                if versuch:
                    logger.info(
                        "%s liess sich erst im %d. Anlauf schreiben - "
                        "vermutlich hielt die Dateisynchronisierung sie fest.",
                        self._path.name,
                        versuch + 1,
                    )
                return
            except PermissionError as fehler:
                letzter = fehler
                time.sleep(0.08 * (versuch + 1))
            except OSError:
                raise

        with contextlib.suppress(OSError):
            os.unlink(quelle)
        logger.error(
            "%s liess sich nicht schreiben: %s. Haelt ein anderes Programm "
            "die Datei fest (OneDrive, Virenscanner, offener Editor)?",
            self._path,
            letzter,
        )
        if letzter is not None:
            raise letzter

    # --- Zugriff -----------------------------------------------------------

    def get(self, key: str, default: Any = None) -> Any:
        """Liest einen Wert auf oberster Ebene."""

        with self._lock:
            return self._data.get(key, default)

    def set(self, key: str, value: Any, *, persist: bool = True) -> None:
        """Setzt einen Wert auf oberster Ebene und speichert optional sofort."""

        with self._lock:
            self._data[key] = value
        if persist:
            self.save()

    def update(self, values: dict[str, Any], *, persist: bool = True) -> None:
        """Führt mehrere Werte auf oberster Ebene zusammen."""

        with self._lock:
            self._data.update(values)
        if persist:
            self.save()

    def delete(self, key: str, *, persist: bool = True) -> None:
        """Entfernt einen Schlüssel, falls vorhanden."""

        with self._lock:
            self._data.pop(key, None)
        if persist:
            self.save()

    def clear(self, *, persist: bool = True) -> None:
        """Setzt den Speicher auf den Standardinhalt zurück."""

        with self._lock:
            self._data = json.loads(json.dumps(self._default))
        if persist:
            self.save()

    @property
    def data(self) -> dict[str, Any]:
        """Direkter Zugriff auf das interne Dict (für komplexe Operationen).

        Änderungen an dem zurückgegebenen Objekt wirken sich direkt aus;
        anschließend muss :meth:`save` aufgerufen werden.
        """

        return self._data

    @property
    def path(self) -> Path:
        """Absoluter Pfad der verwalteten Datei."""

        return self._path
