"""Kompaktes Schema fuer sicherheits- und laufzeitkritische Einstellungen."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Rule:
    types: tuple[type, ...]
    minimum: float | None = None
    maximum: float | None = None
    choices: frozenset[Any] | None = None


RULES: dict[str, Rule] = {
    "app.environment": Rule((str,), choices=frozenset({"development", "production"})),
    "backend.host": Rule((str,)),
    "backend.port": Rule((int,), 1, 65535),
    "window.width": Rule((int,), 160, 4096),
    "window.height": Rule((int,), 160, 4096),
    "window.start_position": Rule((str,), choices=frozenset({"remembered", "center"})),
    "orb.scale": Rule((int, float), 0.05, 1.0),
    "orb.transition_seconds": Rule((int, float), 0.05, 10.0),
    "orb.target_fps": Rule((int,), 15, 240),
    "orb.bloom_strength": Rule((int, float), 0.0, 3.0),
    "orb.bloom_radius": Rule((int, float), 0.0, 1.0),
    "orb.bloom_threshold": Rule((int, float), 0.0, 1.0),
    "orb.particle_count": Rule((int,), 0, 5000),
    "interaction.double_click_action": Rule(
        (str,), choices=frozenset({"open_settings", "toggle_listen", "none"})
    ),
    "smart_desktop.movement_speed": Rule(
        (str,), choices=frozenset({"slow", "medium", "fast"})
    ),
    "smart_desktop.evaluation_interval_ms": Rule((int,), 100, 60000),
    "agents.max_parallel": Rule((int,), 1, 32),
    "agents.timeout": Rule((int, float), 1, 3600),
    "security.consent_timeout_seconds": Rule((int, float), 5, 3600),
    "voice.follow_up_seconds": Rule((int, float), 0, 600),
    "voice.barge_in_hold_ms": Rule((int,), 50, 5000),
    "browser.zeitlimit_ms": Rule((int,), 1000, 300000),
    "tools.max_rounds": Rule((int,), 1, 30),
}


def _read(data: dict[str, Any], path: str) -> tuple[bool, Any]:
    current: Any = data
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return False, None
        current = current[part]
    return True, current


def validate_config(data: dict[str, Any]) -> list[str]:
    """Liefert konkrete Fehler; unbekannte und fehlende Werte bleiben erlaubt."""

    errors: list[str] = []
    for path, rule in RULES.items():
        exists, value = _read(data, path)
        if not exists:
            continue
        # bool ist in Python ein int, in einer YAML-Konfiguration aber keine
        # sinnvolle Pixelzahl oder Portnummer.
        if isinstance(value, bool) and bool not in rule.types:
            valid_type = False
        else:
            valid_type = isinstance(value, rule.types)
        if not valid_type:
            names = "/".join(item.__name__ for item in rule.types)
            errors.append(f"{path}: erwartet {names}, erhalten {type(value).__name__}")
            continue
        if rule.minimum is not None and value < rule.minimum:
            errors.append(f"{path}: {value!r} liegt unter dem Minimum {rule.minimum:g}")
        if rule.maximum is not None and value > rule.maximum:
            errors.append(f"{path}: {value!r} liegt ueber dem Maximum {rule.maximum:g}")
        if rule.choices is not None and value not in rule.choices:
            choices = ", ".join(sorted(map(str, rule.choices)))
            errors.append(f"{path}: {value!r} ist ungueltig; erlaubt: {choices}")

    states = data.get("states", {})
    if isinstance(states, dict):
        for name, values in states.items():
            if not isinstance(values, dict):
                errors.append(f"states.{name}: erwartet Mapping")
                continue
            scale = values.get("scale")
            if scale is not None and (
                isinstance(scale, bool)
                or not isinstance(scale, (int, float))
                or not 0.1 <= scale <= 2.0
            ):
                errors.append(f"states.{name}.scale: erwartet Zahl zwischen 0.1 und 2.0")
    return errors

