"""AI-Orb Backend.

Das Backend bildet die System- und Datenschicht von AI-Orb. Es stellt
Konfiguration, Logging, den zentralen Event Bus sowie den lokalen
REST-/WebSocket-Server bereit, über den das Electron-Frontend (Desktop
Layer) mit dem Backend kommuniziert.

Umgesetzt sind beide Lastenhefte: AI-Orb v2 (Phasen 1 bis 5) und AI-Orb v3
(Phasen 1 bis 6). Neue Fähigkeiten werden über das Skill-System ergänzt,
ohne bestehende Module zu verändern.
"""

__version__ = "0.26.17"
