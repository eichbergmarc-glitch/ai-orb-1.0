"""Zentrale Event-Namen des AI-Orb Event Bus.

Jedes Event, das über den Event Bus veröffentlicht wird, sollte einen Namen
aus dieser Datei verwenden (oder, falls ein neues Modul ein neues Event
benötigt, hier ergänzt werden). Namenskonvention: ``<bereich>.<ereignis>``
in der Vergangenheits- oder Zustandsform, analog zur Beispiel-Liste aus der
Architekturvorgabe.
"""

from __future__ import annotations

# --- System ------------------------------------------------------------
SYSTEM_READY = "system.ready"
SYSTEM_SHUTDOWN = "system.shutdown"
SYSTEM_ERROR = "system.error"

# --- Audio (vorbereitet für spätere Phasen) -----------------------------
AUDIO_RECORDED = "audio.recorded"
SPEECH_TRANSCRIBED = "speech.transcribed"

# --- KI-Anfragen (vorbereitet für spätere Phasen) -----------------------
AI_REQUEST = "ai.request"
AI_RESPONSE = "ai.response"

# --- Längere Arbeiten / Fortschritt ------------------------------------
TASK_STARTED = "task.started"
TASK_PROGRESS = "task.progress"
TASK_FINISHED = "task.finished"

# --- Sprachausgabe (vorbereitet für spätere Phasen) ---------------------
TTS_STARTED = "tts.started"
TTS_FINISHED = "tts.finished"

# --- Fenster / Orb -------------------------------------------------------
WINDOW_POSITION_CHANGED = "window.position.changed"
ORB_STATE_CHANGED = "orb.state.changed"
ORB_ACTIVATED = "orb.activated"
ORB_CONTEXT_MENU_REQUESTED = "orb.context_menu.requested"
ORB_MENU_REQUESTED = "orb.menu.requested"
ORB_CHAT_REQUESTED = "orb.chat.requested"
ORB_QUIT_REQUESTED = "orb.quit.requested"
ORB_ACTION_TRIGGERED = "orb.action.triggered"

# --- Vorlesung / Lehrtafel ----------------------------------------------
LECTURE_VISUAL_CHANGED = "lecture.visual.changed"

# --- Verhalten (vorbereitet für spätere Phasen) -------------------------
BEHAVIOR_UPDATED = "behavior.updated"

# --- Plugins (vorbereitet für spätere Phasen) ---------------------------
PLUGIN_LOADED = "plugin.loaded"
PLUGIN_UNLOADED = "plugin.unloaded"

# --- Frontend-Verbindung --------------------------------------------------
CLIENT_CONNECTED = "client.connected"
CLIENT_DISCONNECTED = "client.disconnected"

ALL_EVENTS = tuple(
    value
    for name, value in globals().items()
    if name.isupper() and isinstance(value, str)
)
