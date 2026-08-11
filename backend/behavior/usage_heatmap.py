"""Nutzungs-Heatmap des Bildschirms (Phase 16).

Der Orb soll nicht nur wissen, wo Platz ist, sondern wo für *diesen*
Benutzer gerade am wenigsten Störung entsteht. Das ist ein Unterschied: Eine
freie Fläche kann trotzdem die sein, in der man ständig die Maus führt.

Dieses Modul führt deshalb Buch darüber, wo tatsächlich gearbeitet wird.
Der Bildschirm wird in ein Raster geteilt, und jede Zelle sammelt Gewicht
aus vier Quellen – Mausbewegung, Klicks, Texteingabe und aktive Fenster.
Klicks und Eingaben zählen dabei deutlich mehr als bloßes Vorbeifahren: Wo
geklickt wird, ist etwas Wichtiges, wo die Maus nur durchzieht, nicht
unbedingt.

Zwei Vorkehrungen halten das brauchbar:

**Langsame Aktualisierung.** Die Vorgabe verlangt ausdrücklich, dass die
Karte nicht auf jede kleine Bewegung reagiert. Eingehende Meldungen werden
deshalb gesammelt und nur in Abständen verrechnet.

**Vergessen.** Die Gewichte klingen ab. Wer seinen Arbeitsplatz umstellt,
soll nicht monatelang mit der alten Karte leben.

Es werden keine Inhalte erfasst – nur Koordinaten und Zeitpunkte. Die
Lernfunktion lässt sich abschalten und die Daten löschen.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any

from backend.config import get_config
from backend.system.logging_setup import get_logger
from backend.utils.store import JsonStore

logger = get_logger(__name__)

#: In wie viele Zellen je Achse der Bildschirm geteilt wird.
GRID = 12

#: Gewicht der einzelnen Quellen. Ein Klick wiegt so viel wie zwanzig
#: Mausbewegungen – dort geschieht etwas, hier fährt nur der Zeiger vorbei.
WEIGHT_MOVE = 0.05
WEIGHT_CLICK = 1.0
WEIGHT_TYPING = 1.5
WEIGHT_WINDOW = 0.6
WEIGHT_ORB_MOVED_AWAY = 3.0

#: Halbwertszeit der Gewichte in Tagen.
HALF_LIFE_DAYS = 14.0

#: Wie oft die gesammelten Meldungen verrechnet werden, in Sekunden.
FLUSH_INTERVAL = 20.0


@dataclass
class Cell:
    """Eine Zelle des Rasters."""

    key: str
    weight: float = 0.0
    clicks: int = 0
    typing: int = 0
    moves: int = 0
    orb_rejections: int = 0
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "weight": round(self.weight, 3),
            "clicks": self.clicks,
            "typing": self.typing,
            "moves": self.moves,
            "orb_rejections": self.orb_rejections,
            "updated_at": self.updated_at,
        }


class UsageHeatmap:
    """Führt Buch darüber, wo auf dem Bildschirm gearbeitet wird."""

    def __init__(self, *, store_filename: str = "usage_heatmap.json") -> None:
        config = get_config()

        self._enabled = bool(config.get("smart_desktop.learn_behavior", True))
        self._store = JsonStore(store_filename, default={"cells": {}, "monitors": {}})

        self._cells: dict[str, Cell] = {}
        self._pending: dict[str, float] = {}
        self._last_flush = time.time()
        self._samples = 0

        self._load()

    def _load(self) -> None:
        for raw in (self._store.get("cells", {}) or {}).values():
            key = str(raw.get("key", ""))
            if not key:
                continue
            self._cells[key] = Cell(
                key=key,
                weight=float(raw.get("weight", 0.0)),
                clicks=int(raw.get("clicks", 0)),
                typing=int(raw.get("typing", 0)),
                moves=int(raw.get("moves", 0)),
                orb_rejections=int(raw.get("orb_rejections", 0)),
                updated_at=float(raw.get("updated_at", time.time())),
            )

    def _save(self) -> None:
        self._store.set("cells", {key: cell.to_dict() for key, cell in self._cells.items()})

    @property
    def enabled(self) -> bool:
        """Ob gelernt wird."""

        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        """Schaltet das Lernen ein oder aus."""

        self._enabled = enabled
        if not enabled:
            self._pending.clear()
        logger.info("Nutzungs-Heatmap %s.", "eingeschaltet" if enabled else "ausgeschaltet")

    # --- Rasterung ---------------------------------------------------------------------

    @staticmethod
    def cell_key(
        x: float, y: float, screen_width: float, screen_height: float, monitor: int = 0
    ) -> str:
        """Bestimmt die Zelle zu einem Punkt.

        Relativ zur Bildschirmgröße, nicht in Bildpunkten: Sonst wäre die
        Karte nach jedem Auflösungswechsel wertlos, und bei mehreren
        Monitoren mit verschiedenen Größen von vornherein.
        """

        width = max(1.0, screen_width)
        height = max(1.0, screen_height)

        column = min(GRID - 1, max(0, int(x / width * GRID)))
        row = min(GRID - 1, max(0, int(y / height * GRID)))
        return f"{monitor}:{column}:{row}"

    @staticmethod
    def cell_center(key: str, screen_width: float, screen_height: float) -> tuple[float, float]:
        """Der Mittelpunkt einer Zelle in Bildpunkten."""

        try:
            _, column, row = key.split(":")
            column_index = int(column)
            row_index = int(row)
        except (ValueError, IndexError):
            return screen_width / 2, screen_height / 2

        return (
            (column_index + 0.5) / GRID * screen_width,
            (row_index + 0.5) / GRID * screen_height,
        )

    # --- Melden -------------------------------------------------------------------------

    def record_mouse(
        self, x: float, y: float, *, screen_width: float, screen_height: float, monitor: int = 0
    ) -> None:
        """Meldet eine Mausposition."""

        self._add(self.cell_key(x, y, screen_width, screen_height, monitor), WEIGHT_MOVE, "moves")

    def record_click(
        self, x: float, y: float, *, screen_width: float, screen_height: float, monitor: int = 0
    ) -> None:
        """Meldet einen Klick."""

        self._add(self.cell_key(x, y, screen_width, screen_height, monitor), WEIGHT_CLICK, "clicks")

    def record_typing(
        self, x: float, y: float, *, screen_width: float, screen_height: float, monitor: int = 0
    ) -> None:
        """Meldet eine Texteingabe an einer Stelle.

        Dort steht ein Eingabefeld, und das ist der empfindlichste Ort auf
        dem ganzen Bildschirm – wer den Orb dorthin setzt, verdeckt genau
        das, worauf der Benutzer gerade schaut.
        """

        self._add(
            self.cell_key(x, y, screen_width, screen_height, monitor), WEIGHT_TYPING, "typing"
        )

    def record_window(
        self,
        *,
        left: float,
        top: float,
        width: float,
        height: float,
        screen_width: float,
        screen_height: float,
        monitor: int = 0,
    ) -> None:
        """Meldet die Fläche eines aktiven Fensters.

        Alle Zellen unter dem Fenster bekommen Gewicht – aber weniger als
        ein Klick, denn ein Fenster ist groß und meist nur an wenigen
        Stellen wirklich in Gebrauch.
        """

        if width <= 0 or height <= 0:
            return

        start_column = max(0, int(left / max(1.0, screen_width) * GRID))
        end_column = min(GRID - 1, int((left + width) / max(1.0, screen_width) * GRID))
        start_row = max(0, int(top / max(1.0, screen_height) * GRID))
        end_row = min(GRID - 1, int((top + height) / max(1.0, screen_height) * GRID))

        cells = max(1, (end_column - start_column + 1) * (end_row - start_row + 1))
        share = WEIGHT_WINDOW / math.sqrt(cells)

        for column in range(start_column, end_column + 1):
            for row in range(start_row, end_row + 1):
                self._add(f"{monitor}:{column}:{row}", share, "")

    def record_orb_moved_away(
        self, x: float, y: float, *, screen_width: float, screen_height: float, monitor: int = 0
    ) -> None:
        """Meldet, dass der Benutzer den Orb von hier weggezogen hat.

        Das wiegt am schwersten. Es ist die einzige Meldung, in der der
        Benutzer ausdrücklich sagt: Hier stört er.
        """

        self._add(
            self.cell_key(x, y, screen_width, screen_height, monitor),
            WEIGHT_ORB_MOVED_AWAY,
            "orb_rejections",
        )
        # Eine so deutliche Aussage wird sofort verrechnet, nicht erst beim
        # nächsten Sammellauf.
        self.flush(force=True)

    def _add(self, key: str, weight: float, counter: str) -> None:
        """Sammelt eine Meldung."""

        if not self._enabled:
            return

        self._pending[key] = self._pending.get(key, 0.0) + weight
        self._samples += 1

        if counter:
            cell = self._cells.setdefault(key, Cell(key=key))
            setattr(cell, counter, getattr(cell, counter, 0) + 1)

        if time.time() - self._last_flush > FLUSH_INTERVAL:
            self.flush()

    def flush(self, *, force: bool = False) -> int:
        """Verrechnet die gesammelten Meldungen.

        Returns:
            Wie viele Zellen sich geändert haben.
        """

        if not self._pending and not force:
            return 0

        now = time.time()
        self._decay(now)

        changed = 0
        for key, weight in self._pending.items():
            cell = self._cells.setdefault(key, Cell(key=key))
            cell.weight += weight
            cell.updated_at = now
            changed += 1

        self._pending.clear()
        self._last_flush = now

        # Zellen ohne nennenswertes Gewicht entfernen, damit die Datei nicht
        # mit Rauschen volläuft.
        self._cells = {
            key: cell for key, cell in self._cells.items() if cell.weight > 0.02
        }

        self._save()
        return changed

    def _decay(self, now: float) -> None:
        """Lässt alte Gewichte abklingen."""

        half_life = HALF_LIFE_DAYS * 86400.0
        for cell in self._cells.values():
            elapsed = max(0.0, now - cell.updated_at)
            if elapsed > 3600.0:
                cell.weight *= math.pow(0.5, elapsed / half_life)
                cell.updated_at = now

    # --- Abfragen -------------------------------------------------------------------------

    def disturbance_at(
        self, x: float, y: float, *, screen_width: float, screen_height: float, monitor: int = 0
    ) -> float:
        """Wie störend der Orb an dieser Stelle wäre.

        Returns:
            Ein Wert von 0.0 (unbedenklich) bis 1.0 (die am stärksten
            genutzte Stelle des Bildschirms).
        """

        if not self._cells:
            return 0.0

        key = self.cell_key(x, y, screen_width, screen_height, monitor)
        cell = self._cells.get(key)
        if cell is None:
            return 0.0

        highest = max((item.weight for item in self._cells.values()), default=0.0)
        if highest <= 0.0:
            return 0.0

        return min(1.0, cell.weight / highest)

    def quiet_spots(
        self, *, screen_width: float, screen_height: float, monitor: int = 0, limit: int = 5
    ) -> list[dict[str, Any]]:
        """Die ruhigsten Stellen des Bildschirms.

        Randbereiche werden bevorzugt, wie die Vorgabe es verlangt: Ein
        freier Fleck mitten im Bild ist selten wirklich frei – dort fällt
        gleich wieder etwas hin.
        """

        highest = max((cell.weight for cell in self._cells.values()), default=0.0) or 1.0
        candidates: list[tuple[float, str, float, float]] = []

        for column in range(GRID):
            for row in range(GRID):
                key = f"{monitor}:{column}:{row}"
                cell = self._cells.get(key)
                usage = (cell.weight / highest) if cell else 0.0

                # Randnähe: 0 in der Mitte, 1 ganz außen.
                edge = max(
                    abs(column - (GRID - 1) / 2) / ((GRID - 1) / 2),
                    abs(row - (GRID - 1) / 2) / ((GRID - 1) / 2),
                )

                # Wenig Nutzung zählt doppelt so viel wie Randnähe.
                score = (1.0 - usage) * 2.0 + edge

                x, y = self.cell_center(key, screen_width, screen_height)
                candidates.append((score, key, x, y))

        candidates.sort(key=lambda item: item[0], reverse=True)

        return [
            {
                "key": key,
                "x": round(x),
                "y": round(y),
                "score": round(score, 3),
                "disturbance": round(
                    self.disturbance_at(
                        x, y, screen_width=screen_width, screen_height=screen_height, monitor=monitor
                    ),
                    3,
                ),
            }
            for score, key, x, y in candidates[:limit]
        ]

    def busiest(self, limit: int = 5) -> list[dict[str, Any]]:
        """Die am stärksten genutzten Zellen."""

        ordered = sorted(self._cells.values(), key=lambda cell: cell.weight, reverse=True)
        return [cell.to_dict() for cell in ordered[:limit]]

    def grid_snapshot(self, monitor: int = 0) -> list[list[float]]:
        """Die Karte als Raster, zum Anzeigen.

        Werte von 0.0 bis 1.0, zeilenweise von oben nach unten.
        """

        highest = max((cell.weight for cell in self._cells.values()), default=0.0) or 1.0
        return [
            [
                round(
                    (self._cells[f"{monitor}:{column}:{row}"].weight / highest)
                    if f"{monitor}:{column}:{row}" in self._cells
                    else 0.0,
                    3,
                )
                for column in range(GRID)
            ]
            for row in range(GRID)
        ]

    # --- Verwaltung -----------------------------------------------------------------------

    def clear(self) -> int:
        """Löscht die Karte."""

        count = len(self._cells)
        self._cells.clear()
        self._pending.clear()
        self._save()
        logger.info("Die Nutzungs-Heatmap wurde gelöscht (%d Zellen).", count)
        return count

    def status(self) -> dict[str, Any]:
        """Statusangaben für die Transparenzansicht."""

        return {
            "enabled": self._enabled,
            "cells": len(self._cells),
            "samples": self._samples,
            "pending": len(self._pending),
            "grid": GRID,
            "half_life_days": HALF_LIFE_DAYS,
            "busiest": self.busiest(3),
            "note": (
                "Erfasst werden nur Koordinaten und Zeitpunkte, keine Inhalte. "
                "Die Karte lässt sich jederzeit löschen."
            ),
        }
