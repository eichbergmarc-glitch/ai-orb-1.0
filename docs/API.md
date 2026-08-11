# Die lokale API von AI-Orb

Das Backend stellt einen HTTP-Server bereit, der ausschließlich auf
`127.0.0.1` lauscht. Host und Port stehen in `config.yaml` unter `backend`;
voreingestellt ist `http://127.0.0.1:8756`.

Der Server verwendet nur die Python-Standardbibliothek. Alle Antworten sind
JSON. Vom Backend zur Oberfläche läuft zusätzlich ein
Server-Sent-Events-Kanal.

## Ereigniskanal

`GET /events` öffnet einen dauerhaften Server-Sent-Events-Strom. Jedes
Ereignis des Event Bus wird automatisch weitergereicht:

```
data: {"event": "cognitive.response", "payload": {...}}
```

Alle 15 Sekunden sendet der Server einen Keep-Alive-Kommentar, damit die
Verbindung nicht wegen Untätigkeit geschlossen wird. Bricht sie dennoch ab,
verbindet sich die Oberfläche selbstständig neu.

## Status und Diagnose

`GET /health` liefert `{"status": "ok", "version": "0.1.0"}`. Das
Startskript wartet auf diesen Endpunkt, bevor es die Oberfläche startet.

`GET /status` liefert den vollständigen Systemstatus mit Cognitive Core,
Agenten, Skills, Verhaltensdaten und Evolution Engine.

`GET /config` liefert die geladene `config.yaml`, damit die Oberfläche
dieselben Einstellungen liest wie das Backend.

## Gespräch

`POST /ask` mit `{"text": "..."}` verarbeitet eine Benutzereingabe über das
Cognitive Core. Die Antwort enthält den Antworttext, den erkannten Intent,
ob ein Sprachmodell genutzt wurde, Provider und Modell, die
Sicherheitskategorie, die gewählte Strategie, ob eine Bestätigung nötig ist,
etwaige Hinweise, die beteiligten Bereiche und das aktive Projekt.

`POST /conversation/end` beendet die Unterhaltung und legt eine
Zusammenfassung im Conversation Memory ab. `GET /conversation/history`
liefert den bisherigen Verlauf.

## Projekte

`GET /projects` listet alle Projekte mit der Zahl offener Aufgaben.
`POST /projects/create` legt eines an (`name`, optional `path` und `kind`).
`POST /projects/activate` aktiviert es über `project_id` oder `name` und
startet eine Arbeitssitzung.

`POST /projects/detect` untersucht ein Verzeichnis. Ist die Erkennung
unsicher, antwortet der Endpunkt mit `requires_confirmation` und einer
Rückfrage, statt zu raten; mit `{"confirmed": true}` wird das Projekt dann
angelegt.

`GET /projects/summary` beantwortet "Woran arbeite ich gerade?".
`POST /projects/graph` liefert den Projektgraphen als Knoten und Kanten.
`POST /projects/delete` entfernt ein Projekt samt allem zugehörigen Wissen.

## Aufgaben und Ziele

`GET /tasks` liefert Übersicht und Liste. `POST /tasks/add` legt eine
Aufgabe an; mit `{"decompose": true}` zerlegt der Orb sie selbstständig in
Teilschritte, sofern er ein passendes Muster kennt.
`POST /tasks/status` setzt den Status auf `offen`, `in_bearbeitung`,
`blockiert` (mit `reason`) oder `erledigt`.

`GET /goals` liefert die Zielübersicht, `POST /goals/add` legt ein Ziel mit
Zeithorizont und Priorität an.

## Gedächtnis

`GET /memory` liefert Statistik und Einträge, `POST /memory/search` sucht
semantisch, `POST /memory/edit` ändert einen Eintrag, `POST /memory/delete`
löscht ihn endgültig. Diese vier Endpunkte setzen die Transparenzanforderung
um: Der Benutzer kann sein Gedächtnis vollständig einsehen, bearbeiten und
löschen.

## Orb und Verhalten

`POST /orb/state` meldet einen Zustandswechsel, `POST /orb/interaction` eine
Benutzerinteraktion.

`POST /behavior/position` meldet eine Orb-Position an das Lernsystem. Das
Feld `manual` unterscheidet dabei, ob der Benutzer den Orb selbst dorthin
gezogen hat – solche Positionen erhalten das fünffache Gewicht.
`POST /behavior/score` fragt die gelernte Bewertung einer Kandidatenposition
ab; die Smart Desktop Engine nutzt das für ihr Scoring.
`POST /behavior/activity` vermerkt Programmnutzung, `GET /behavior` liefert
alle gelernten Daten.

## Agenten, Skills, Evolution

`GET /agents` liefert alle Agenten mit Fähigkeiten, Rechten und Kennzahlen.
`GET /agents/explain` beantwortet "Welche Agenten hast du genutzt und
warum?".

`GET /skills` liefert den Zustand des Skill-Systems, `GET /skills/catalog`
den lokalen Katalog. `POST /skills/prepare` prüft einen Skill und liefert
den Installationsvorschlag samt Berechtigungen zurück, **ohne** etwas zu
installieren. `POST /skills/install` installiert ihn erst mit
`{"confirmed": true}`. `POST /skills/activate` und
`POST /skills/deactivate` schalten ihn um, `POST /skills/permission` ändert
einzelne Rechte.

`POST /evolution/analyze` startet die Selbstanalyse,
`GET /evolution/report` beantwortet die Transparenzfragen zu gefundenen
Verbesserungen, bereiten Patches, durchgeführten Tests und bestehenden
Risiken. `POST /evolution/apply` übernimmt einen Patch – nur mit
`{"confirmed": true}`. `POST /evolution/undo` macht die letzte Änderung
rückgängig.

## Fehlerbehandlung

Unbekannte Pfade beantwortet der Server mit `404` und
`{"error": "not_found", "path": "..."}`. Fehler in einem Endpunkt führen zu
`500` mit `{"error": "internal_error", "detail": "..."}` und einem
vollständigen Eintrag im Log – ein fehlerhafter Aufruf beendet den Server
niemals.

Ungültiges JSON im Anfragekörper wird als leeres Objekt behandelt, damit
eine fehlerhafte Anfrage nicht zum Absturz führt.
