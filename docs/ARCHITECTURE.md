# Architektur von AI-Orb

Dieses Dokument beschreibt den Aufbau von AI-Orb: die Schichten, die
Kommunikationswege zwischen ihnen und die Regeln, die für alle Module
gelten.

## Grundregeln

Vier Regeln bestimmen den gesamten Aufbau und gelten ausnahmslos.

Erstens: Alle Module kommunizieren ausschließlich über das Cognitive Core
oder den Event Bus. Es gibt keine direkte Kommunikation zwischen
Fachmodulen. Die Review Engine der Evolution Engine prüft neue Änderungen
ausdrücklich auf Verstöße gegen diese Regel.

Zweitens: Es gibt keine hartkodierten Konfigurationswerte. Jede Einstellung
steht in `config.yaml` und wird über den `ConfigLoader` gelesen. Das gilt
insbesondere für Modellnamen: Weder `ling-3.0-flash:free` noch
`llama3.1:8b` steht irgendwo im Quellcode.

Drittens: Alle Daten bleiben lokal. AI-Orb schreibt ausschließlich in das
Verzeichnis `data/`. Eine Übertragung an externe Dienste findet nur statt,
wenn der Benutzer einer konkreten Übertragung zustimmt – das betrifft
ausschließlich die Anfragen an den Online-Provider Hermes, sofern dieser
konfiguriert ist.

Viertens: Alles arbeitet asynchron. Der gesamte kognitive Teil läuft auf
einer einzigen asyncio-Event-Loop in einem eigenen Thread. Blockierende
Aufrufe – etwa HTTP-Anfragen an Sprachmodelle – werden in Worker-Threads
ausgelagert. Die Oberfläche wird dadurch niemals blockiert.

## Die Schichten

AI-Orb besteht aus fünf Schichten, die von unten nach oben aufeinander
aufbauen. Jede Schicht kennt nur die Schichten unter sich.

Die **Datenschicht** umfasst `backend/utils` und `backend/memory`. Hier
liegen der atomare JSON-Speicher, die Pfadauflösung, die Textverarbeitung
sowie die vollständige Memory Engine mit Working, Conversation, User,
Knowledge und Task Memory. Sämtliche Persistenz von AI-Orb läuft über diese
Schicht.

Die **Systemschicht** umfasst `backend/config`, `backend/system` und
`backend/events`. Sie stellt Konfiguration, Logging, den zentralen Event Bus
und die kontrollierte Desktop-Steuerung bereit. Die Desktop-Steuerung ist
die einzige Stelle im gesamten Backend, die Programme startet oder Dateien
öffnet; sie arbeitet ausschließlich mit einer Allowlist aus `config.yaml`.

Die **KI-Schicht** umfasst `backend/orchestrator`. Sie enthält die
Intent-Klassifikation, das Task-Routing, die Gesprächsverwaltung und den
Provider Manager mit automatischer Umschaltung zwischen dem netzbasierten
Primärmodell und dem lokalen Offline-Fallback. Der Orchestrator entscheidet
insbesondere, ob eine Aufgabe überhaupt ein Sprachmodell benötigt.

Die **kognitive Schicht** umfasst `backend/cognitive`, `backend/reasoning`
und `backend/projects`. Hier liegt das Cognitive Core – das zentrale Gehirn,
über das alle anderen Module kommunizieren –, die vollständige Reasoning-
und Planning-Engine sowie die Project Intelligence Engine mit
Projekterkennung, Projektgedächtnis, Dokumentverfolgung und Sitzungen.

Die **Erweiterungsschicht** umfasst `backend/agents`, `backend/skills` und
`backend/evolution`. Sie enthält das Multi-Agent-System mit zehn
spezialisierten Agenten, das Skill- und Plugin-System sowie die Evolution
Engine für die kontrollierte Selbstverbesserung.

Darüber liegt die **Desktop-Schicht** in `desktop/`: der Electron-Hauptprozess
mit Fenster- und Monitorverwaltung sowie der Smart Desktop Engine, und der
Renderer mit der Three.js-Orb-Engine.

## Der Weg einer Anfrage

Eine Benutzereingabe durchläuft immer denselben Weg. Die Oberfläche sendet
sie per HTTP an `POST /ask`. Der API-Server reicht sie threadsicher an die
Runtime weiter, die sie auf der Kern-Loop an das Cognitive Core übergibt.

Das Cognitive Core bestimmt zunächst den aktiven Projektkontext und lässt
die Absicht klassifizieren. Der kognitive Orchestrator zerlegt
zusammengesetzte Anfragen und ordnet Teilaufgaben Engines zu. Die Decision
Engine klärt, welche Module gebraucht werden, ob Internet nötig ist, ob
lokal gearbeitet werden kann und ob eine Rückfrage sinnvoll ist.

Anschließend baut das Core den Reasoning Context auf: passende
Gedächtniseinträge, Benutzerangaben und Projektwissen, jeweils mit ihrer
Wissensart gekennzeichnet. Die Reasoning Engine analysiert die Aufgabe
(Task Profile), wählt eine Strategie, erstellt bei ausreichender Komplexität
einen Plan, bewertet die Sicherheit und durchläuft den Entscheidungsbaum.

Erst danach wird gehandelt. Kann die Aufgabe lokal erledigt werden – etwa
"Firefox starten", "Woran arbeite ich gerade?" oder "Welche Aufgaben sind
offen?" –, geschieht das ohne jede Modellanfrage. Andernfalls geht die
Anfrage samt aufbereitetem Kontext an den Provider Manager.

Nach der Antwort prüft die Verification Engine auf Widersprüche und
Belegbarkeit, der Reflection Manager führt die Nachbetrachtung durch, und
das Ergebnis geht zurück an die Oberfläche. Parallel dazu veröffentlicht der
Event Bus jeden Schritt, sodass der Orb sichtbar mitwechselt: er denkt,
spricht, wartet oder meldet einen Fehler.

## Die Brücke zur Oberfläche

Backend und Oberfläche sind zwei getrennte Prozesse. Sie sprechen
ausschließlich über den lokalen HTTP-Server auf `127.0.0.1`, der bewusst
allein mit der Python-Standardbibliothek umgesetzt ist: keine
Web-Framework-Abhängigkeit, keine kompilierten Pakete, keine
Installationshürden unter Windows.

Vom Frontend zum Backend führen gewöhnliche POST-Anfragen. Vom Backend zum
Frontend führt ein Server-Sent-Events-Kanal unter `GET /events`, an den
jedes Event des Event Bus automatisch weitergereicht wird. Bricht die
Verbindung ab, verbindet sich die Oberfläche selbstständig neu und zeigt in
der Zwischenzeit den Fehlerzustand.

Der Renderer besitzt keinerlei Zugriff auf Node.js, das Dateisystem oder
Electron-Interna. Die einzige Verbindung ist die in `preload.ts` über
`contextBridge` freigegebene Schnittstelle mit acht Funktionen.

## Erweiterbarkeit

Neue Fähigkeiten kommen auf drei Wegen hinzu, ohne den Kern zu verändern.

Ein neuer **KI-Provider** implementiert `BaseProvider`, wird in
`PROVIDER_TYPES` eingetragen und in `config.yaml` konfiguriert. Der
Orchestrator bleibt unverändert.

Ein neuer **Agent** erbt von `BaseAgent`, wird über `AgentManager.add_agent`
registriert und muss den Selbsttest bestehen. Seine Fähigkeiten landen
automatisch in der Capability Registry.

Ein neuer **Skill** ist ein eigenständiges Verzeichnis mit `skill.json`,
`skill.py`, Tests und Dokumentation. Er wird geprüft, dem Benutzer samt
seiner Berechtigungen vorgelegt, nach Bestätigung installiert und dynamisch
geladen. Der Kern muss dafür nicht neu gebaut werden.

Ein neuer **Intent** wird über `IntentClassifier.register_intent` ergänzt,
ein neuer **Task-Handler** über `TaskRouter.register`.

## Umsetzungsstand

Die folgende Übersicht ordnet die Vorgaben aus beiden Lastenheften den
Modulen zu.

| Phase | Inhalt | Modul |
| --- | --- | --- |
| v2‑1 | Architektur, Event Bus, Config, Logging | `backend/events`, `backend/config`, `backend/system` |
| v2‑2 | Orb-Oberfläche, Zustände, Interaktion | `desktop/renderer`, `desktop/electron` |
| v2‑3 | Smart Desktop Engine, Lernsystem | `desktop/electron/desktop_manager.ts`, `backend/behavior` |
| v2‑4 | Orchestrator, Provider Manager | `backend/orchestrator` |
| v2‑5 | Memory Engine | `backend/memory` |
| v3‑1 | Cognitive Core, Ziele, Aufgaben, Kontexte | `backend/cognitive` |
| v3‑2 | Reasoning, Planung, Entscheidungen | `backend/reasoning` |
| v3‑3 | Project Intelligence Engine | `backend/projects` |
| v3‑4 | Evolution Engine | `backend/evolution` |
| v3‑5 | Multi-Agent-System | `backend/agents` |
| v3‑6 | Skill- und Plugin-System | `backend/skills` |

Nicht enthalten sind Spracheingabe (Whisper), Sprachausgabe (Kokoro) und
Bildschirmauswertung (Vision/OCR). Für alle drei existieren die
Architekturpositionen, die Agenten und die Ereignisnamen; die eigentlichen
Fähigkeiten werden über das Skill-System nachgerüstet, weil sie große
Modelldateien und plattformabhängige Bibliotheken benötigen. Die
betreffenden Agenten melden ausdrücklich, dass die Komponente fehlt, statt
stillschweigend nichts zu tun.
