"""Ein frisch gestartetes Fenster in den Vordergrund holen.

Der Benutzer hat beobachtet: Öffnet der Orb ein Programm, erscheint dessen
Fenster im Hintergrund, nicht vorn. Das liegt daran, wie der Start abläuft
– das Programm wird losgelöst gestartet (``DETACHED_PROCESS``), damit der
Orb nicht blockiert, und ein so gestarteter Prozess bekommt von Windows
NICHT automatisch den Vordergrund. Windows vergibt den Vordergrund nur an
Programme, die gerade eine Eingabe des Benutzers verarbeiten – das soll
verhindern, dass ein Hintergrundprozess sich vordrängt.

Genau diese Sperre muss hier umgangen werden, und zwar auf dem einzigen
Weg, den Windows dafür offen lässt: Man hängt den eigenen Eingabefaden
kurz an den des Vordergrundfensters an (``AttachThreadInput``). Für die
Dauer dieser Verbindung gilt man als „derselbe" Faden und darf den
Vordergrund weiterreichen. Danach wird die Verbindung wieder gelöst.

Alles hier ist Windows-eigen und über ``ctypes`` erreichbar – es wird
nichts installiert. Auf anderen Systemen tut das Modul nichts.
"""

from __future__ import annotations

import sys
import threading
import time

from backend.system.logging_setup import get_logger

logger = get_logger(__name__)


#: Wie lange höchstens auf das Fenster des neuen Prozesses gewartet wird.
#:
#: Ein Programm braucht nach dem Start einen Moment, bis sein Fenster
#: steht – bei einem Browser können das ein, zwei Sekunden sein. Wer zu
#: früh aufgibt, holt ein Fenster nach vorn, das es noch gar nicht gibt.
_WARTEN_S = 6.0

#: Wie oft in dieser Zeit nachgesehen wird.
_TAKT_S = 0.15


def in_den_vordergrund(pid: int, *, timeout: float = _WARTEN_S) -> None:
    """Holt das Hauptfenster eines Prozesses nach vorn – im Hintergrund.

    Läuft in einem eigenen Faden, weil auf das Fenster gewartet werden
    muss und der Aufrufer (die Werkzeugschleife) währenddessen nicht
    stehen soll. Schlägt etwas fehl, bleibt es beim alten Verhalten – das
    Fenster ist dann eben im Hintergrund, was kein Absturz ist, sondern
    nur unschön.
    """

    if not sys.platform.startswith("win"):
        return
    if pid <= 0:
        return

    faden = threading.Thread(
        target=_arbeite, args=(int(pid), float(timeout)), daemon=True
    )
    faden.start()


def _arbeite(pid: int, timeout: float) -> None:
    try:
        import ctypes
        from ctypes import wintypes
    except Exception:  # noqa: BLE001 - ohne ctypes kein Vordergrund, aber kein Absturz.
        return

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    # Die Signaturen setzen, sonst schneidet ctypes auf 32 Bit ab und die
    # Fensterkennungen (Zeiger) werden auf einem 64-Bit-System zerstört.
    user32.EnumWindows.argtypes = [ctypes.c_void_p, wintypes.LPARAM]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetWindow.restype = wintypes.HWND

    ziel = _warte_auf_fenster(user32, kernel32, pid, timeout)
    if not ziel:
        logger.debug("Kein Fenster von PID %s gefunden – bleibt im Hintergrund.", pid)
        return

    _hebe_hervor(user32, kernel32, ziel)


def _warte_auf_fenster(user32, kernel32, pid, timeout):
    """Sucht das sichtbare Hauptfenster des Prozesses, bis es erscheint."""

    import ctypes
    from ctypes import wintypes

    GW_OWNER = 4
    frist = time.monotonic() + timeout

    gefunden = {"hwnd": None}

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _pruefe(hwnd, _lparam):
        besitzer = wintypes.DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(besitzer))
        if besitzer.value != pid:
            return True
        if not user32.IsWindowVisible(hwnd):
            return True
        # Nur echte Hauptfenster: Ein Fenster mit „Besitzer" ist ein
        # Dialog oder ein Werkzeugkasten, nicht das Programmfenster selbst.
        if user32.GetWindow(hwnd, GW_OWNER):
            return True
        gefunden["hwnd"] = hwnd
        return False  # gefunden – Aufzählung abbrechen

    while time.monotonic() < frist:
        gefunden["hwnd"] = None
        user32.EnumWindows(_pruefe, 0)
        if gefunden["hwnd"]:
            return gefunden["hwnd"]
        time.sleep(_TAKT_S)
    return None


def _hebe_hervor(user32, kernel32, hwnd) -> None:
    """Bringt ein bekanntes Fenster nach vorn – mit dem AttachThreadInput-Trick."""

    import ctypes
    from ctypes import wintypes

    SW_RESTORE = 9
    SW_SHOW = 5

    user32.GetForegroundWindow.restype = wintypes.HWND
    vordergrund = user32.GetForegroundWindow()

    eigenerFaden = kernel32.GetCurrentThreadId()
    zielFaden = user32.GetWindowThreadProcessId(hwnd, None)
    vorderFaden = (
        user32.GetWindowThreadProcessId(vordergrund, None) if vordergrund else 0
    )

    # Ein minimiertes Fenster erst wiederherstellen, sonst holt man ein
    # Symbol in der Leiste nach vorn und sieht weiterhin nichts.
    user32.ShowWindow(hwnd, SW_RESTORE)
    user32.ShowWindow(hwnd, SW_SHOW)

    angehaengt = []
    try:
        # An BEIDE fremden Fäden anhängen: an den des bisherigen
        # Vordergrunds (dessen „Recht" man übernimmt) und an den des
        # Zielfensters (dem man es gibt).
        for fremd in {zielFaden, vorderFaden} - {eigenerFaden, 0}:
            if user32.AttachThreadInput(eigenerFaden, fremd, True):
                angehaengt.append(fremd)

        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        user32.SetActiveWindow(hwnd)
    finally:
        for fremd in angehaengt:
            user32.AttachThreadInput(eigenerFaden, fremd, False)

    logger.info("Fenster in den Vordergrund geholt.")
