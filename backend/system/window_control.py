"""Fenstersteuerung (Phase 9).

Findet Fenster, holt sie in den Vordergrund, verschiebt und skaliert sie.
Damit lassen sich Aufträge wie „hol mir den Browser nach vorn" oder „leg
Editor und Browser nebeneinander" umsetzen.

Unter Windows läuft das über die Systemschnittstelle ``user32``, die über
``ctypes`` angesprochen wird. Das ist bewusst so gewählt: Es kommt ohne
zusätzliches Paket aus und ist damit sofort einsatzbereit.

Zwei Regeln gelten hier durchgehend:

**Es wird nichts geschlossen.** Ein Fenster zu schließen kann ungespeicherte
Arbeit vernichten. Dieses Modul verschiebt, skaliert und fokussiert – zum
Beenden eines Programms gibt es einen eigenen Weg, der jedes Mal einzeln zu
bestätigen ist.

**Eigene Fenster werden übergangen.** Der Orb soll sich nicht selbst
verschieben; seine Fenster erkennt er am Titel und lässt sie aus.
"""

from __future__ import annotations

import ctypes
import platform
from ctypes import wintypes
from dataclasses import dataclass
from typing import Any, Callable

from backend.system.logging_setup import get_logger

logger = get_logger(__name__)

#: Fenstertitel, die AI-Orb selbst gehören und nie angefasst werden.
OWN_WINDOW_MARKERS: frozenset[str] = frozenset({"ai-orb", "ai orb"})

#: Anzeigebefehle von ``ShowWindow``.
SW_RESTORE = 9
SW_MINIMIZE = 6
SW_MAXIMIZE = 3


@dataclass
class WindowInfo:
    """Ein Fenster auf dem Bildschirm."""

    handle: int
    title: str
    left: int
    top: int
    width: int
    height: int
    minimized: bool = False
    maximized: bool = False
    process_id: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "handle": self.handle,
            "title": self.title,
            "left": self.left,
            "top": self.top,
            "width": self.width,
            "height": self.height,
            "minimized": self.minimized,
            "maximized": self.maximized,
            "process_id": self.process_id,
        }

    @property
    def is_own(self) -> bool:
        """Ob das Fenster zu AI-Orb selbst gehört."""

        lowered = self.title.lower()
        return any(marker in lowered for marker in OWN_WINDOW_MARKERS)


class WindowControl:
    """Steuert Fenster auf dem Desktop."""

    def __init__(self) -> None:
        self._is_windows = platform.system() == "Windows"
        self._user32: Any | None = None

        if self._is_windows:
            try:
                self._user32 = ctypes.WinDLL("user32", use_last_error=True)
            except (OSError, AttributeError):
                logger.exception("Die Fenstersteuerung ließ sich nicht laden.")
                self._user32 = None

    # --- Verfügbarkeit -------------------------------------------------------------

    def is_available(self) -> bool:
        """Ob Fenster gesteuert werden können."""

        return self._user32 is not None

    def unavailable_reason(self) -> str:
        """Warum nicht, im Klartext."""

        if not self._is_windows:
            return (
                "Die Fenstersteuerung ist derzeit nur unter Windows umgesetzt. "
                f"Dieses System meldet sich als {platform.system()}."
            )
        return "Die Windows-Systemschnittstelle 'user32' ließ sich nicht laden."

    # --- Auflisten ------------------------------------------------------------------

    def list_windows(self, *, visible_only: bool = True) -> list[WindowInfo]:
        """Listet die offenen Fenster auf.

        Fenster ohne Titel werden übergangen: Windows führt Dutzende
        unsichtbarer Hilfsfenster, die für den Benutzer nicht existieren und
        die Liste unbrauchbar machen würden.
        """

        if self._user32 is None:
            return []

        found: list[WindowInfo] = []

        # Der Rückruftyp muss am Leben bleiben, solange er aufgerufen wird –
        # deshalb wird er hier lokal gehalten und nicht wegoptimiert.
        callback_type = ctypes.WINFUNCTYPE(
            wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
        )

        def collect(handle: int, _: int) -> bool:
            try:
                if visible_only and not self._user32.IsWindowVisible(handle):
                    return True

                length = self._user32.GetWindowTextLengthW(handle)
                if length <= 0:
                    return True

                buffer = ctypes.create_unicode_buffer(length + 1)
                self._user32.GetWindowTextW(handle, buffer, length + 1)
                title = buffer.value.strip()
                if not title:
                    return True

                rectangle = wintypes.RECT()
                if not self._user32.GetWindowRect(handle, ctypes.byref(rectangle)):
                    return True

                process_id = wintypes.DWORD()
                self._user32.GetWindowThreadProcessId(handle, ctypes.byref(process_id))

                found.append(
                    WindowInfo(
                        handle=int(handle),
                        title=title,
                        left=rectangle.left,
                        top=rectangle.top,
                        width=rectangle.right - rectangle.left,
                        height=rectangle.bottom - rectangle.top,
                        minimized=bool(self._user32.IsIconic(handle)),
                        maximized=bool(self._user32.IsZoomed(handle)),
                        process_id=int(process_id.value),
                    )
                )
            except Exception:  # noqa: BLE001 - ein Fenster darf die Liste nicht kippen.
                logger.debug("Ein Fenster ließ sich nicht auslesen.", exc_info=True)

            return True

        try:
            self._user32.EnumWindows(callback_type(collect), 0)
        except Exception:  # noqa: BLE001
            logger.exception("Die Fensterliste ließ sich nicht erstellen.")

        return found

    def find(self, needle: str, *, include_own: bool = False) -> list[WindowInfo]:
        """Sucht Fenster, deren Titel einen Text enthält.

        Sortiert nach Güte des Treffers: Wer „Firefox" sagt, meint das
        Fenster, dessen Titel mit Firefox anfängt, nicht irgendeines, in dem
        das Wort vorkommt.
        """

        term = needle.strip().lower()
        if len(term) < 2:
            return []

        scored: list[tuple[int, WindowInfo]] = []
        for window in self.list_windows():
            if window.is_own and not include_own:
                continue

            title = window.title.lower()
            if term == title:
                scored.append((3, window))
            elif title.startswith(term) or title.endswith(term):
                scored.append((2, window))
            elif term in title:
                scored.append((1, window))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [window for _, window in scored]

    def active_window(self) -> WindowInfo | None:
        """Das Fenster, in dem gerade gearbeitet wird."""

        if self._user32 is None:
            return None

        handle = self._user32.GetForegroundWindow()
        if not handle:
            return None

        for window in self.list_windows():
            if window.handle == int(handle):
                return window
        return None

    # --- Steuern ---------------------------------------------------------------------

    def focus(self, window: WindowInfo | int) -> tuple[bool, str]:
        """Holt ein Fenster in den Vordergrund."""

        handle = self._handle_of(window)
        if handle is None:
            return False, self.unavailable_reason()

        try:
            # Ein minimiertes Fenster muss erst wiederhergestellt werden,
            # sonst holt SetForegroundWindow einen unsichtbaren Rahmen nach
            # vorn.
            if self._user32.IsIconic(handle):
                self._user32.ShowWindow(handle, SW_RESTORE)

            if self._user32.SetForegroundWindow(handle):
                return True, "Das Fenster ist im Vordergrund."

            # Windows verweigert den Wechsel, wenn die Anfrage nicht vom
            # aktiven Prozess kommt. Das ist eine Schutzmaßnahme gegen
            # Fenster, die sich aufdrängen – hier wird sie nicht umgangen.
            return False, (
                "Windows hat den Wechsel abgelehnt. Das geschieht, wenn gerade "
                "in einem anderen Fenster gearbeitet wird. Klicke das Fenster "
                "einmal an oder versuche es gleich noch einmal."
            )
        except Exception as error:  # noqa: BLE001
            logger.exception("Das Fenster ließ sich nicht in den Vordergrund holen.")
            return False, f"Es ist ein Fehler aufgetreten: {error}"

    def move(
        self,
        window: WindowInfo | int,
        *,
        left: int,
        top: int,
        width: int = 0,
        height: int = 0,
    ) -> tuple[bool, str]:
        """Verschiebt und skaliert ein Fenster."""

        handle = self._handle_of(window)
        if handle is None:
            return False, self.unavailable_reason()

        current = self._geometry(handle)
        if current is None:
            return False, "Die Fenstergröße ließ sich nicht auslesen."

        target_width = width if width > 0 else current[2]
        target_height = height if height > 0 else current[3]

        # Ein Fenster kleiner als 200 mal 100 ist praktisch unbedienbar.
        target_width = max(200, target_width)
        target_height = max(100, target_height)

        try:
            if self._user32.IsZoomed(handle):
                # Ein maximiertes Fenster lässt sich nicht verschieben; es
                # muss zuerst zurückgesetzt werden.
                self._user32.ShowWindow(handle, SW_RESTORE)

            success = self._user32.MoveWindow(
                handle, int(left), int(top), int(target_width), int(target_height), True
            )
        except Exception as error:  # noqa: BLE001
            logger.exception("Das Fenster ließ sich nicht verschieben.")
            return False, f"Es ist ein Fehler aufgetreten: {error}"

        if not success:
            return False, "Windows hat das Verschieben abgelehnt."

        return True, (
            f"Das Fenster steht jetzt bei {left}, {top} und ist "
            f"{target_width} mal {target_height} Bildpunkte groß."
        )

    def minimize(self, window: WindowInfo | int) -> tuple[bool, str]:
        """Legt ein Fenster in die Taskleiste."""

        handle = self._handle_of(window)
        if handle is None:
            return False, self.unavailable_reason()

        self._user32.ShowWindow(handle, SW_MINIMIZE)
        return True, "Das Fenster ist minimiert."

    def maximize(self, window: WindowInfo | int) -> tuple[bool, str]:
        """Vergrößert ein Fenster auf den ganzen Bildschirm."""

        handle = self._handle_of(window)
        if handle is None:
            return False, self.unavailable_reason()

        self._user32.ShowWindow(handle, SW_MAXIMIZE)
        return True, "Das Fenster ist maximiert."

    def restore(self, window: WindowInfo | int) -> tuple[bool, str]:
        """Stellt ein Fenster auf seine vorherige Größe zurück."""

        handle = self._handle_of(window)
        if handle is None:
            return False, self.unavailable_reason()

        self._user32.ShowWindow(handle, SW_RESTORE)
        return True, "Das Fenster ist wiederhergestellt."

    # --- Anordnen ------------------------------------------------------------------------

    def tile(self, titles: list[str], *, monitor_width: int = 0, monitor_height: int = 0) -> dict[str, Any]:
        """Legt mehrere Fenster nebeneinander.

        Bis zu zwei Fenster werden nebeneinander gestellt, drei bis vier im
        Viereck. Mehr wird abgelehnt – ab fünf Fenstern ist jedes zu klein,
        um damit zu arbeiten.
        """

        if self._user32 is None:
            return {"ok": False, "message": self.unavailable_reason()}

        if not 2 <= len(titles) <= 4:
            return {
                "ok": False,
                "message": "Es lassen sich zwei bis vier Fenster nebeneinander legen.",
            }

        width = monitor_width or self._screen_width()
        height = monitor_height or self._screen_height()

        if not width or not height:
            return {"ok": False, "message": "Die Bildschirmgröße ließ sich nicht ermitteln."}

        # Etwas Platz für die Taskleiste lassen.
        usable_height = int(height * 0.94)

        if len(titles) == 2:
            areas = [(0, 0, width // 2, usable_height), (width // 2, 0, width // 2, usable_height)]
        else:
            half_width = width // 2
            half_height = usable_height // 2
            areas = [
                (0, 0, half_width, half_height),
                (half_width, 0, half_width, half_height),
                (0, half_height, half_width, half_height),
                (half_width, half_height, half_width, half_height),
            ][: len(titles)]

        placed: list[str] = []
        missing: list[str] = []

        for title, (left, top, area_width, area_height) in zip(titles, areas):
            windows = self.find(title)
            if not windows:
                missing.append(title)
                continue

            window = windows[0]
            success, _ = self.move(
                window, left=left, top=top, width=area_width, height=area_height
            )
            if success:
                placed.append(window.title)
            else:
                missing.append(title)

        message = f"{len(placed)} Fenster angeordnet."
        if missing:
            message += " Nicht gefunden: " + ", ".join(missing) + "."

        return {"ok": bool(placed), "placed": placed, "missing": missing, "message": message}

    # --- Hilfen ---------------------------------------------------------------------------

    def _handle_of(self, window: WindowInfo | int) -> int | None:
        """Holt die Fensterkennung und prüft die Verfügbarkeit."""

        if self._user32 is None:
            return None
        handle = window.handle if isinstance(window, WindowInfo) else int(window)
        return handle if handle else None

    def _geometry(self, handle: int) -> tuple[int, int, int, int] | None:
        """Liest Lage und Größe eines Fensters."""

        rectangle = wintypes.RECT()
        try:
            if not self._user32.GetWindowRect(handle, ctypes.byref(rectangle)):
                return None
        except Exception:  # noqa: BLE001
            return None
        return (
            rectangle.left,
            rectangle.top,
            rectangle.right - rectangle.left,
            rectangle.bottom - rectangle.top,
        )

    def _screen_width(self) -> int:
        return int(self._user32.GetSystemMetrics(0)) if self._user32 else 0

    def _screen_height(self) -> int:
        return int(self._user32.GetSystemMetrics(1)) if self._user32 else 0

    def screen_size(self) -> tuple[int, int]:
        """Die Größe des Hauptbildschirms."""

        return self._screen_width(), self._screen_height()

    def status(self) -> dict[str, Any]:
        """Statusangaben für die Transparenzansicht."""

        available = self.is_available()
        return {
            "available": available,
            "reason": "" if available else self.unavailable_reason(),
            "platform": platform.system(),
            "window_count": len(self.list_windows()) if available else 0,
            "screen": {"width": self._screen_width(), "height": self._screen_height()},
            "note": "Fenster werden nie geschlossen – nur verschoben, skaliert und fokussiert.",
        }
