"""Lädt und stellt die zentrale ``config.yaml`` bereit.

Gemäß Architekturvorgabe enthält AI-Orb keine hartkodierten
Konfigurationswerte im Quellcode. Jedes Modul, das Einstellungen benötigt,
fragt diese ausschließlich über :func:`get_config` bzw. die Klasse
:class:`ConfigLoader` ab.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import yaml

from backend.config.schema import validate_config
from backend.utils.paths import get_config_path


class ConfigError(RuntimeError):
    """Wird ausgelöst, wenn ``config.yaml`` fehlt oder ungültig ist."""


class ConfigLoader:
    """Lädt ``config.yaml`` und stellt typsicheren, geschachtelten Zugriff
    auf die enthaltenen Werte bereit.

    Die Klasse ist bewusst zustandsbehaftet (liest die Datei einmalig beim
    ersten Zugriff und cached das Ergebnis), bietet aber :meth:`reload`, um
    Änderungen zur Laufzeit übernehmen zu können.
    """

    def __init__(self, config_path: Path | None = None) -> None:
        self._config_path = config_path or get_config_path()
        self._data: dict[str, Any] = {}
        self._lock = threading.RLock()
        self.reload()

    def reload(self) -> None:
        """Liest ``config.yaml`` erneut von der Festplatte ein.

        Raises:
            ConfigError: Wenn die Datei nicht existiert oder kein gültiges
                YAML-Mapping auf oberster Ebene enthält.
        """

        if not self._config_path.exists():
            raise ConfigError(
                f"Konfigurationsdatei nicht gefunden: {self._config_path}"
            )

        try:
            with self._config_path.open("r", encoding="utf-8") as handle:
                loaded = yaml.safe_load(handle)
        except yaml.YAMLError as error:
            mark = getattr(error, "problem_mark", None)
            location = f" Zeile {mark.line + 1}, Spalte {mark.column + 1}" if mark else ""
            raise ConfigError(f"config.yaml ist ungueltig ({location.strip()}): {error}") from error

        if loaded is None:
            loaded = {}

        if not isinstance(loaded, dict):
            raise ConfigError(
                "config.yaml muss auf oberster Ebene ein Mapping (Schlüssel/"
                "Wert-Paare) enthalten."
            )

        errors = validate_config(loaded)
        if errors:
            details = "\n  - ".join(errors)
            raise ConfigError(f"Ungueltige Einstellungen in {self._config_path}:\n  - {details}")

        with self._lock:
            self._data = loaded

    def get(self, dotted_key: str, default: Any = None) -> Any:
        """Liest einen Wert über einen punktgetrennten Pfad.

        Beispiel: ``config.get("window.width", 220)`` liest
        ``data["window"]["width"]``.

        Args:
            dotted_key: Punktgetrennter Pfad zum gewünschten Wert.
            default: Rückgabewert, falls der Pfad nicht existiert.

        Returns:
            Der gefundene Wert oder ``default``.
        """

        parts = dotted_key.split(".")
        with self._lock:
            current: Any = self._data
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return default
        return current

    def section(self, name: str) -> dict[str, Any]:
        """Gibt einen kompletten Konfigurationsabschnitt als Dict zurück.

        Args:
            name: Name des Abschnitts auf oberster Ebene (z. B. ``"window"``).

        Returns:
            Das Abschnitts-Dict, oder ein leeres Dict, falls nicht vorhanden.
        """

        with self._lock:
            value = self._data.get(name, {})
        return value if isinstance(value, dict) else {}

    @property
    def raw(self) -> dict[str, Any]:
        """Gibt eine flache Kopie der vollständigen Konfiguration zurück."""

        with self._lock:
            return dict(self._data)

    @property
    def path(self) -> Path:
        """Absoluter Pfad zur geladenen ``config.yaml``."""

        return self._config_path


_instance_lock = threading.Lock()
_instance: ConfigLoader | None = None


def get_config() -> ConfigLoader:
    """Gibt die prozessweite :class:`ConfigLoader`-Singleton-Instanz zurück.

    Die Instanz wird beim ersten Aufruf erzeugt (und ``config.yaml`)
    eingelesen) und anschließend wiederverwendet, damit alle Module
    konsistente Konfigurationswerte sehen.
    """

    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = ConfigLoader()
    return _instance
