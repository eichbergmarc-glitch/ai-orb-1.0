# Anforderungsprüfung AI-Orb

Stand: 07.08.2026 · Version 0.2.2 · geprüft gegen die beiden Spezifikationsdateien (v2 Phasen 1–24, v3 Phasen 1–6)

## Vorbemerkung, die ich dir schulde

Die Spezifikationsdatei zu Version 2, die du mir zu Beginn hochgeladen hast, war
in meiner Ansicht **nach 2000 Zeilen abgeschnitten** – mitten in Phase 5. Ich habe
bis zu deiner letzten Nachricht also nur die Phasen 1 bis 5 gekannt und alles,
was ich gebaut habe, an diesem Ausschnitt ausgerichtet. Erst der vollständige
Text in deiner letzten Nachricht hat die Phasen 6 bis 24 sichtbar gemacht.

Das erklärt die Lücke, entschuldigt sie aber nicht vollständig: Ich hätte merken
müssen, dass eine Datei, die mitten im Satz endet, unvollständig ist, und hätte
nachfragen müssen. Habe ich nicht. Die folgende Aufstellung ist deshalb bewusst
streng – ich zähle nichts als erfüllt, was ich nicht im Code nachweisen kann.

## Die kurze Antwort

**Nein, es sind nicht alle Anforderungen erfüllt.**

Von den 24 Phasen der Version 2 sind 8 vollständig umgesetzt, 6 teilweise und
10 gar nicht. Die 6 Phasen der Version 3 sind umgesetzt.

Besonders wichtig: **Die Sprachsteuerung funktioniert nicht.** Du hast sie
mehrfach als zentrale Funktion bezeichnet. Die Bausteine liegen im Projekt,
aber sie sind nicht miteinander und nicht mit dem Rest verbunden. Das Weckwort
„Hallo Orb" wird deshalb weiterhin nicht erkannt, und der Orb spricht nicht.

## Version 2 – Phase für Phase

### Vollständig umgesetzt

**Phase 1 – Fundament und Architektur.** Event-Bus mit Wildcard-Abonnements,
Konfiguration aus `config.yaml`, Geheimnisse ausschließlich aus `.env`,
Logging-Aufbau, eine einzige asyncio-Schleife in einem eigenen Thread,
HTTP-Server mit Server-Sent-Events. Nachweisbar in `backend/events/`,
`backend/config/`, `backend/system/`, `backend/runtime.py`, `backend/api/`.

**Phase 2 – Orb-Grundlage.** Electron-Fenster, rahmenlos, transparent, immer im
Vordergrund, Three.js-Darstellung mit Shadern. In `desktop/electron/` und
`desktop/renderer/`.

**Phase 3 – Bewegung und Verhalten.** Zustände (ruhend, zuhörend, denkend,
sprechend, beschäftigt, Fehler, Schlaf) mit weichen Übergängen, Atmen,
Ausweichbewegung ohne Sprünge, keine festen Bildschirmkoordinaten. In
`desktop/renderer/states.ts`, `movement.ts`, `backend/behavior/behavior_engine.py`.

**Phase 4 – Memory Engine.** Fünf Gedächtnisarten, semantische Suche über
TF/Kosinus mit Stammformbildung, Zusammenfassung, Index. In `backend/memory/`.

**Phase 5 – Cognitive Core.** Arbeitsgedächtnis, Ziele, Aufgaben, Planer,
Entscheidungen, Reflexion, Kontext. In `backend/cognitive/`.

**Phase 6 – Skills Engine.** Registry, Loader, Validator, Berechtigungen,
Installer, Updater, Marktplatz, Dokumentation, Manager – neun Module, dazu die
Endpunkte `/skills`, `/skills/install`, `/skills/permission` und weitere. In
`backend/skills/`.

**Phase 7 – Planner Engine.** Aufgabenanalyse, Planerzeugung, Strategiewahl,
Entscheidungsbaum, Ausführungssteuerung, Prüfung, Verlässlichkeitsschätzung,
Reflexion. In `backend/reasoning/` und `backend/cognitive/planner.py`.

**Phase 11 – AI Provider Engine.** Anbieterabstraktion, Gesundheitsüberwachung,
Ausweichkette, vier Anbieter (`claude_code` über dein Max-Abonnement, `claude`
über die Messages-API, `ollama`, `hermes`). Kein Modellname steht im Code, alle
kommen aus `config.yaml`. In `backend/orchestrator/`.

### Teilweise umgesetzt

**Phase 8 – Security und Permissions Engine.** `backend/security/` enthält nur
eine leere Modulhülle. Es gibt Berechtigungen für Skills
(`backend/skills/skill_permissions.py`), aber keine zentrale Sicherheitsschicht,
kein Prüfprotokoll, keine Sandbox, keinen durchgängigen Zustimmungsdialog. Die
Sicherheitsregeln aus der Spezifikation – keine automatischen Änderungen an
produktiven Dateien, keine Systembefehle direkt aus dem Orchestrator – sind
derzeit durch die Architektur eingehalten, aber nicht technisch erzwungen.

**Phase 9 – Audio Engine.** `vad.py` (Sprachaktivitätserkennung mit
mitlaufendem Rauschpegel) und `audio_capture.py` (Mikrofonaufnahme mit
Vorlaufpuffer) sind geschrieben und dokumentiert. Es fehlen: die Wiedergabe, die
Verdrahtung in `runtime.py`, der Abschnitt in `config.yaml`, die Datei
`requirements-voice.txt`. Das Paket `sounddevice` ist nicht installiert.

**Phase 10 – Speech Recognition Engine.** `wake_word.py` (unscharfer
Abgleich auf „Hallo Orb" samt Abtrennen des nachfolgenden Befehls) und
`transcriber.py` (faster-whisper, verzögertes Laden, Ausführung im
Worker-Thread) sind geschrieben. Nicht verdrahtet, `faster-whisper` nicht
installiert. **Deshalb reagiert der Orb nicht auf das Weckwort.**

**Phase 15 – Desktop Agent Integration.** `backend/system/desktop_control.py`
kennt Fensterlagen und aktive Anwendungen, damit der Orb ausweichen kann. Eine
darüber hinausgehende Steuerung des Desktops gibt es nicht.

**Phase 16 – Production Release.** Installationsskript, Reparaturskript mit
Gegenprüfung, Startmenü-Einträge und Startskripte sind da. Es fehlen: ein
signiertes Installationspaket, automatische Aktualisierung, Absturzberichte.

**Phase 18 – Adaptive Learning.** `backend/evolution/skill_trainer.py` und die
Reflexionsmodule gehen in diese Richtung. Eine Rückkopplung, die das Verhalten
tatsächlich an dich anpasst, gibt es nicht.

**Phase 21 und 22 – Presence AI, Verhalten und Emotionssimulation.**
`behavior_engine.py` bildet Präsenz, Atmung und Zustandswechsel ab. Die in der
Spezifikation beschriebene Emotions- und Lebenssimulation reicht deutlich
weiter.

### Nicht umgesetzt

| Phase | Inhalt | Stand |
|---|---|---|
| 12 | Tool Calling Engine | kein Modul vorhanden |
| 13 | TTS und Emotion | `backend/tts/` ist eine leere Hülle |
| 14 | Plugin System | `backend/plugins/` ist eine leere Hülle |
| 17 | Vision und Computer Interaction | nicht begonnen |
| 20 | Academic Knowledge Base | nicht begonnen |
| 23 | Voice Intelligence | nicht begonnen |
| 24 | Human Experience | nicht begonnen |

Zu Phase 19 liegt mir kein verlässlicher Text vor – in meinem Auszug fehlt sie
zwischen 18 und 20. Bitte prüfe das an deiner Datei nach; ich möchte hier nichts
behaupten.

## Version 3 – Phasen 1 bis 6

Diese sind umgesetzt: Projektverwaltung (`backend/projects/`), Agentensystem
(`backend/agents/`), Selbstverbesserung mit Analyse, Patch-Erzeugung,
Prüfung und Rücknahme (`backend/evolution/`), sowie die zugehörigen
Endpunkte und die Transparenzansicht.

## Deine ausdrücklichen Einzelwünsche

| Wunsch | Stand |
|---|---|
| Claude statt Hermes, über das Max-Abonnement | erfüllt – `claude_code`-Anbieter nutzt die angemeldete CLI, ohne API-Abrechnung |
| Orb nur so groß wie ein Symbol | erfüllt – `orb.scale: 0.20` |
| Keine ruckelige Ausweichbewegung | erfüllt – der Orb bewegt sich in der Grafikkarte innerhalb eines größeren unsichtbaren Fensters, statt das Fenster selbst zu verschieben |
| Kleiner wenn ruhend, größer wenn zuhörend | erfüllt – 0,88 gegenüber 1,14, weich überblendet |
| Verknüpfung im Startmenü | erfüllt – `scripts/create-shortcut.ps1` |
| Eine Datei, die alles repariert, nur anzuklicken | erfüllt – `REPARIEREN-UND-STARTEN.bat` |
| **Weckwort „Hallo Orb", Sprachein- und -ausgabe** | **nicht erfüllt** |
| Kokoro als Sprachausgabe | nicht erfüllt |
| Weckwort dauerhaft aktiv | nicht erfüllt |

## Was zuerst getan werden sollte

Die Sprachsteuerung, weil du sie als zentrale Funktion bezeichnet hast. Dafür
fehlen konkret:

1. Sprachausgabe: Kokoro als erste Wahl, Windows-SAPI als Rückfallebene
   (Phase 13)
2. Wiedergabemodul für die erzeugte Sprache (Phase 9)
3. `voice_pipeline.py`, die Aufnahme → Erkennung → Weckwort → Antwort →
   Ausgabe zusammenführt
4. Verdrahtung in `runtime.py`, Ereignisse für die Orb-Zustände, Endpunkte
5. Abschnitt `voice` in `config.yaml` und `requirements-voice.txt`
6. Erweiterung von `REPARIEREN-UND-STARTEN.bat` um die Sprachpakete

Danach wäre Phase 8 (Sicherheit) an der Reihe, weil sie die
Sicherheitszusagen der Spezifikation technisch absichert, und Phase 12
(Tool Calling), weil ohne sie der Orb zwar antworten, aber nichts tun kann.
