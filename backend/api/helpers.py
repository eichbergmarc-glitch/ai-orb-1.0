"""Hilfsfunktionen für die API-Handler zur Reduktion von Code-Redundanz.

Diese Module enthält wiederverwendbare Funktionen für häufige Muster
in API-Endpunkten, um Duplikation zu reduzieren und Performance zu
verbessern.
"""

from __future__ import annotations

from typing import Any, TypeVar, Callable


T = TypeVar("T")


def extract_string(data: dict[str, Any], key: str, default: str = "") -> str:
    """Extrahiert und normalisiert einen String aus dict-Daten.

    Schneller als wiederholte str() und .strip() Aufrufe.

    Args:
        data: Die Eingabe-Dictionary.
        key: Der Schlüssel zum Auslesen.
        default: Standardwert, wenn Schlüssel nicht existiert.

    Returns:
        Trimmed, nicht-leerer String.
    """
    value = data.get(key, default)
    if isinstance(value, str):
        return value.strip()
    return str(value).strip() if value else default


def extract_bool(data: dict[str, Any], key: str, default: bool = False) -> bool:
    """Extrahiert einen Boolean-Wert effizienter.

    Args:
        data: Die Eingabe-Dictionary.
        key: Der Schlüssel zum Auslesen.
        default: Standardwert.

    Returns:
        Boolean-Wert.
    """
    value = data.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("true", "1", "ja", "yes", "on")
    return bool(value)


def extract_int(data: dict[str, Any], key: str, default: int = 0) -> int:
    """Extrahiert einen Integer-Wert mit Fallback.

    Args:
        data: Die Eingabe-Dictionary.
        key: Der Schlüssel zum Auslesen.
        default: Standardwert bei Fehler.

    Returns:
        Integer-Wert oder default.
    """
    try:
        return int(data.get(key, default))
    except (TypeError, ValueError):
        return default


def extract_float(data: dict[str, Any], key: str, default: float = 0.0) -> float:
    """Extrahiert einen Float-Wert mit Fallback.

    Args:
        data: Die Eingabe-Dictionary.
        key: Der Schlüssel zum Auslesen.
        default: Standardwert bei Fehler.

    Returns:
        Float-Wert oder default.
    """
    try:
        return float(data.get(key, default))
    except (TypeError, ValueError):
        return default


def validate_nonempty(value: str, error_message: str) -> tuple[bool, dict[str, Any] | None]:
    """Validiert, dass ein String nicht leer ist.

    Returns:
        Tuple von (ist_gültig, error_dict oder None).
    """
    if not value or not value.strip():
        return False, {"error": "invalid", "message": error_message}
    return True, None


def safe_get_nested(data: dict[str, Any], *keys: str, default: Any = None) -> Any:
    """Sicher verschachtelte dict-Werte auslesen.

    Args:
        data: Die Basis-Dictionary.
        *keys: Die Schlüsselpfad (z.B. "user", "name").
        default: Standardwert bei Fehler.

    Returns:
        Der Wert oder default.
    """
    current = data
    for key in keys:
        if isinstance(current, dict):
            current = current.get(key)
        else:
            return default
    return current if current is not None else default
