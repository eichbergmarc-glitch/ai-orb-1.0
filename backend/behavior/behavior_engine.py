"""Behavior Engine – lernt das Verhalten des Benutzers.

Beobachtet werden bevorzugte Orb-Positionen, Arbeitszeiten,
Programmverwendung und Mausaktivität. Aus diesen Daten entsteht eine
Gewichtung, mit der die Smart Desktop Engine im Frontend bessere
Platzierungsentscheidungen trifft.

Alle Daten werden ausschließlich lokal in ``data/user_behavior.json``
gespeichert. Es werden keine Inhalte erfasst – nur Positionen, Zeiten und
Programmnamen.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any

from backend.system.logging_setup import get_logger
from backend.utils.store import JsonStore

logger = get_logger(__name__)

#: Auflösung des Positionsrasters: Der Bildschirm wird in Zellen dieser
#: Größe (in Prozent der Bildschirmbreite/-höhe) eingeteilt.
_GRID_STEPS = 10

#: Gewicht, das eine manuelle Platzierung durch den Benutzer erhält. Eine
#: bewusste Entscheidung wiegt deutlich schwerer als eine automatische.
_MANUAL_WEIGHT = 5.0
_AUTOMATIC_WEIGHT = 1.0

#: Halbwertszeit der Gewichte in Tagen.
_HALF_LIFE_DAYS = 30.0


@dataclass
class PositionPreference:
    """Die gelernte Vorliebe für eine Bildschirmzone."""

    cell: str
    monitor: int
    weight: float = 0.0
    manual_count: int = 0
    automatic_count: int = 0
    last_used: float = field(default_factory=time.time)
    programs: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "cell": self.cell,
            "monitor": self.monitor,
            "weight": round(self.weight, 3),
            "manual_count": self.manual_count,
            "automatic_count": self.automatic_count,
            "last_used": self.last_used,
            "programs": {name: round(value, 2) for name, value in self.programs.items()},
        }


class BehaviorEngine:
    """Lernt und bewertet Positionsvorlieben des Benutzers."""

    def __init__(self, filename: str = "user_behavior.json") -> None:
        self._store = JsonStore(
            filename,
            default={
                "positions": {},
                "working_hours": {},
                "programs": {},
                "mouse": {"samples": 0, "average_speed": 0.0},
                "history": [],
            },
        )

    # --- Beobachtung ---------------------------------------------------------

    def record_position(
        self,
        *,
        x: float,
        y: float,
        screen_width: float,
        screen_height: float,
        monitor: int = 0,
        manual: bool = False,
        program: str | None = None,
    ) -> PositionPreference:
        """Vermerkt eine Orb-Position.

        Args:
            x: Horizontale Position in Pixeln.
            y: Vertikale Position in Pixeln.
            screen_width: Breite des Monitors.
            screen_height: Höhe des Monitors.
            monitor: Index des Monitors.
            manual: Ob der Benutzer den Orb selbst dorthin gezogen hat.
                Manuelle Platzierungen erhalten ein deutlich höheres
                Gewicht.
            program: Das zu diesem Zeitpunkt aktive Programm.

        Returns:
            Die aktualisierte Vorliebe für diese Bildschirmzone.
        """

        cell = self._cell_for(x, y, screen_width, screen_height)
        key = f"{monitor}:{cell}"

        positions = dict(self._store.get("positions", {}) or {})
        raw = positions.get(key, {})
        preference = PositionPreference(
            cell=cell,
            monitor=monitor,
            weight=float(raw.get("weight", 0.0)),
            manual_count=int(raw.get("manual_count", 0)),
            automatic_count=int(raw.get("automatic_count", 0)),
            last_used=float(raw.get("last_used", time.time())),
            programs=dict(raw.get("programs", {}) or {}),
        )

        increment = _MANUAL_WEIGHT if manual else _AUTOMATIC_WEIGHT
        preference.weight += increment
        preference.last_used = time.time()
        if manual:
            preference.manual_count += 1
        else:
            preference.automatic_count += 1

        if program:
            preference.programs[program] = float(preference.programs.get(program, 0.0)) + increment

        positions[key] = preference.to_dict()
        self._store.set("positions", positions)

        self._append_history(
            {
                "at": time.time(),
                "cell": cell,
                "monitor": monitor,
                "manual": manual,
                "program": program,
            }
        )

        if manual:
            logger.info(
                "Manuelle Orb-Position gelernt: Zelle %s auf Monitor %d.", cell, monitor
            )
        return preference

    def record_activity(self, *, program: str | None = None, hour: int | None = None) -> None:
        """Vermerkt Arbeitszeit und Programmverwendung."""

        current_hour = hour if hour is not None else time.localtime().tm_hour
        hours = dict(self._store.get("working_hours", {}) or {})
        key = str(max(0, min(23, int(current_hour))))
        hours[key] = int(hours.get(key, 0)) + 1

        updates: dict[str, Any] = {"working_hours": hours}
        if program:
            programs = dict(self._store.get("programs", {}) or {})
            programs[program] = int(programs.get(program, 0)) + 1
            updates["programs"] = programs

        self._store.update(updates)

    def record_mouse(self, speed: float) -> None:
        """Vermerkt die Mausgeschwindigkeit für die Ausweichlogik."""

        mouse = dict(self._store.get("mouse", {}) or {})
        samples = int(mouse.get("samples", 0)) + 1
        average = float(mouse.get("average_speed", 0.0))
        mouse["average_speed"] = average + (speed - average) / samples
        mouse["samples"] = samples
        self._store.set("mouse", mouse)

    # --- Bewertung -------------------------------------------------------------

    def preference_score(
        self,
        *,
        x: float,
        y: float,
        screen_width: float,
        screen_height: float,
        monitor: int = 0,
        program: str | None = None,
    ) -> float:
        """Bewertet eine Position anhand des gelernten Verhaltens.

        Returns:
            Ein Wert zwischen 0.0 und 1.0. Höhere Werte bedeuten, dass der
            Benutzer den Orb dort bevorzugt.
        """

        cell = self._cell_for(x, y, screen_width, screen_height)
        key = f"{monitor}:{cell}"
        positions = self._store.get("positions", {}) or {}
        raw = positions.get(key)
        if not raw:
            return 0.0

        weight = self._decayed_weight(raw)
        if program:
            program_weight = float((raw.get("programs", {}) or {}).get(program, 0.0))
            weight += program_weight * 0.5

        maximum = self._maximum_weight()
        if maximum <= 0:
            return 0.0
        return max(0.0, min(1.0, weight / maximum))

    def favourite_positions(self, limit: int = 5) -> list[dict[str, Any]]:
        """Die vom Benutzer am häufigsten gewählten Zonen."""

        positions = self._store.get("positions", {}) or {}
        entries = [
            {**raw, "key": key, "effective_weight": self._decayed_weight(raw)}
            for key, raw in positions.items()
        ]
        entries.sort(key=lambda entry: entry["effective_weight"], reverse=True)
        return entries[:limit]

    def working_zones(self) -> list[str]:
        """Die Zonen, in denen der Benutzer überwiegend arbeitet."""

        positions = self._store.get("positions", {}) or {}
        if not positions:
            return []
        weights = {key: self._decayed_weight(raw) for key, raw in positions.items()}
        average = sum(weights.values()) / len(weights)
        return sorted(key for key, weight in weights.items() if weight > average)

    def top_programs(self, limit: int = 5) -> list[tuple[str, int]]:
        """Die am häufigsten genutzten Programme."""

        programs = self._store.get("programs", {}) or {}
        ranked = sorted(programs.items(), key=lambda item: int(item[1]), reverse=True)
        return [(name, int(count)) for name, count in ranked[:limit]]

    def snapshot(self) -> dict[str, Any]:
        """Vollständige Sicht auf die gelernten Daten (Transparenzansicht)."""

        return {
            "favourite_positions": self.favourite_positions(),
            "working_zones": self.working_zones(),
            "top_programs": self.top_programs(),
            "working_hours": self._store.get("working_hours", {}),
            "mouse": self._store.get("mouse", {}),
            "history_entries": len(self._store.get("history", []) or []),
            "storage_path": str(self._store.path),
        }

    def reset(self) -> None:
        """Löscht alle gelernten Verhaltensdaten."""

        self._store.clear()
        logger.info("Verhaltensdaten wurden zurückgesetzt.")

    # --- Hilfsfunktionen ----------------------------------------------------------

    @staticmethod
    def _cell_for(x: float, y: float, width: float, height: float) -> str:
        """Ordnet eine Pixelposition einer Rasterzelle zu."""

        if width <= 0 or height <= 0:
            return "0,0"
        column = min(_GRID_STEPS - 1, max(0, int(x / width * _GRID_STEPS)))
        row = min(_GRID_STEPS - 1, max(0, int(y / height * _GRID_STEPS)))
        return f"{column},{row}"

    @staticmethod
    def _decayed_weight(raw: dict[str, Any]) -> float:
        """Berechnet das durch Zeitablauf verringerte Gewicht."""

        weight = float(raw.get("weight", 0.0))
        age_days = max(0.0, (time.time() - float(raw.get("last_used", time.time()))) / 86400.0)
        return weight * math.pow(0.5, age_days / _HALF_LIFE_DAYS)

    def _maximum_weight(self) -> float:
        positions = self._store.get("positions", {}) or {}
        if not positions:
            return 0.0
        return max(self._decayed_weight(raw) for raw in positions.values())

    def _append_history(self, entry: dict[str, Any]) -> None:
        history = list(self._store.get("history", []) or [])
        history.append(entry)
        if len(history) > 1000:
            history = history[-1000:]
        self._store.set("history", history)
