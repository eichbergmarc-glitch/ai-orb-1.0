"""Startet AI-Orb aus dem Projektordner (ORB-STARTEN.bat) - ohne Fenster davor.

17.11.2026: Angelegt, damit sich der Orb aus der Ferne starten laesst
(Startmenue-Eintrag "AI-Orb Quellstart"), auch wenn niemand am PC ist.
"""

import subprocess
from pathlib import Path

projekt = Path(__file__).resolve().parents[1]
starter = projekt / "ORB-STARTEN.bat"
subprocess.Popen(
    ["cmd", "/c", "start", "AI-Orb starten", "/min", "cmd", "/c", str(starter)],
    cwd=str(projekt),
    creationflags=0x00000008 | 0x00000200,  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    close_fds=True,
)
