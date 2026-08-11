# Changelog

Alle nennenswerten Änderungen an AI-Orb werden in dieser Datei dokumentiert.
Das Format orientiert sich an [Keep a Changelog](https://keepachangelog.com/de/1.0.0/),
die Versionierung folgt [Semantic Versioning](https://semver.org/lang/de/).

## [0.4.0] – Eine Installationsdatei, ein Klick

Umsetzung der Phasen 41 bis 63: AI-Orb wird als gewöhnliche
Windows-Anwendung ausgeliefert. Der Benutzer installiert nichts von Hand –
kein Python, kein Node.js, kein pip, kein npm, keine Kommandozeile.

### Installation (Phasen 41, 42, 46, 47, 48, 60)

- `BUILD-INSTALLER.bat` erzeugt mit einem Doppelklick
  `dist-installer\AI-Orb-Setup.exe`.
- electron-builder mit NSIS, deutschsprachig, mit Uninstaller.
- `scripts/prepare-runtime.ps1` stellt eine eigene Python-Runtime aus der
  embeddable-Fassung zusammen und legt sie ins Paket. Damit sieht der
  Benutzer nie „python is not recognized".
- Sprachpakete und Modelle sind Bestandteil des Pakets beziehungsweise
  werden beim ersten Gebrauch nachgeladen.

### Launcher und Startablauf (Phasen 43, 44, 45, 59)

- `backend/launcher/` mit Startprüfung, Ollama-Anbindung und
  Dienstüberwachung.
- `desktop/electron/backend_process.ts` startet den Python-Kern aus
  Electron heraus, ohne sichtbares Konsolenfenster.
- `desktop/electron/splash.ts` zeigt während des Starts jeden Schritt.
- Vierzehn Startprüfungen in der Form aus der Vorgabe. Jede liefert bei
  einem Fehler den Grund und den nächsten Schritt, nicht nur ein Kreuz.
- `python -m backend.main --check` prüft ohne zu starten.

### Datentrennung (Phase 52)

- `backend/utils/paths.py` unterscheidet Programmordner und Benutzerordner.
- Benutzerdaten unter `%APPDATA%\AI-Orb`, Sprachmodelle unter
  `%LOCALAPPDATA%\AI-Orb\cache`, Programm unter
  `%LOCALAPPDATA%\Programs\AI-Orb`.
- In den Programmordner wird nie geschrieben.
- Daten einer früheren Quellinstallation werden beim ersten Start
  übernommen – kopiert, nicht verschoben, und nichts wird überschrieben.
- Im Quellbetrieb bleibt alles beisammen wie bisher.

### Absturzbehandlung (Phase 58)

- `backend/launcher/supervisor.py` erkennt Ausfälle und startet neu, mit
  wachsendem Abstand und einer Obergrenze.
- Ein Dienst, der fünf Minuten stabil lief, gilt wieder als gesund.
- Entbehrliche Ausfälle beenden AI-Orb nicht: Sprachausgabe weg heißt
  Antwort als Text, Claude weg heißt Ollama, Ollama weg heißt Claude.

### Ollama (Phase 49)

- Wird auch gefunden, wenn es nicht im PATH steht.
- Wird ohne Fenster gestartet, das Modell geprüft, der Ladestand gemeldet.
- Nicht umgesetzt und mit Grund: das ungefragte Installieren von Ollama
  und das ungefragte Laden des fünf Gigabyte großen Modells.

### Update und Deinstallation (Phasen 55, 56, 57)

- Ein Update ersetzt nur den Programmordner. Gedächtnis, Einstellungen,
  Projekte, Wissensnetz und Positionsdaten bleiben.
- Der Uninstaller trennt „Programm entfernen" von „Benutzerdaten löschen".
  Gefragt wird nur, wenn Daten da sind; die Frage nennt den Umfang und wird
  zweimal gestellt.
- Autostart ist abwählbar und wird beim Deinstallieren immer entfernt.

### Icon (Phase 53)

- `build/icon.ico` in sieben Größen von 16 bis 256 Bildpunkten, dazu
  Einzel-PNGs. Kein generisches Electron-Symbol.

### Aufräumen

- `AUFRAEUMEN.bat` entfernt die alte skriptbasierte Installation:
  `.venv`, `node_modules`, alte Builds, Reparaturskripte, Patches.
  Erinnerungen, Einstellungen und Zugangsdaten bleiben, sofern nicht
  ausdrücklich anders verlangt.

### Entfernt

- `REPARIEREN-UND-STARTEN.bat`, `install.ps1`, `start.ps1`, `rebuild.ps1`
  und die übrigen Skripte der bisherigen Arbeitsweise. Sie werden von
  Installer und Launcher abgelöst.

### Behoben

- `VoicePipeline.is_ready()` ersetzt eine Textprüfung, die „noch nicht
  einsatzbereit" für einsatzbereit hielt.
- `HealthReport.degraded` erkannte eine Warnung nicht als Einschränkung,
  weil eine Warnung den Start nicht blockiert.
- `Runtime.is_running()` prüft jetzt die Event-Loop und nicht nur den
  Thread. Ein abgestürzter Kern hinterließ sonst einen Thread, der lebendig
  aussah und nichts mehr tat.

## [0.3.0] – Alle 21 Phasen umgesetzt

Vollständige Umsetzung der 21 Phasen aus der Builder-Prompt-Sammlung. Die
Zuordnung jeder Phase zum Code steht in `docs/PHASEN.md`.

### Sprachsteuerung (Phasen 2, 4, 15)

Die zentrale Funktion, die zuvor nur als unverbundene Bausteine vorlag, ist
jetzt vollständig und verdrahtet.

- `backend/voice/voice_pipeline.py` führt Aufnahme, Erkennung, Weckwort,
  Antwort und Ausgabe zusammen und ist in `runtime.py` eingebunden.
- `backend/tts/` mit drei Verfahren: Piper (auf Deutsch trainiert,
  Voreinstellung), Windows-SAPI (immer verfügbar, keine Installation),
  Kokoro (sehr natürlich, beherrscht aber kein Deutsch).
- `backend/audio/player.py` spielt blockweise ab, sodass ein Abbruch nach
  Millisekunden greift statt am Satzende.
- Wer dazwischenredet, unterbricht die Wiedergabe.
- Nach einer Antwort bleibt der Orb 25 Sekunden wach – ein Gespräch muss
  nicht bei jeder Frage mit dem Weckwort beginnen.
- Bei unsicherer Erkennung wird nachgefragt statt geraten.
- Im Schlafzustand wird nichts weitergegeben: Der Text wird auf das
  Weckwort geprüft und verworfen. Aufnahmen werden nicht aufbewahrt.

### Sicherheitsschicht

- `backend/security/` als einzige Stelle, an der über heikle Aktionen
  entschieden wird. Kein Modul entscheidet selbst.
- 19 benannte Berechtigungen mit Einstufung. Unbekanntes gilt als kritisch
  und wird verweigert.
- Schweigen zählt als Nein: Bleibt der Zustimmungsdialog unbeantwortet,
  wird nicht gehandelt.
- Kritische Aktionen können nicht gemerkt werden und sind jedes Mal neu zu
  bestätigen.
- Pfadschutz gegen Ausbruch über `..` und über Verknüpfungen; Zugangsdaten
  und ausführbare Dateien sind gesperrt.
- Prüfprotokoll in `data/security/audit.jsonl`, einsehbar über die API.
- `system_commands` und `send_code_external` stehen in `never_allow` und
  werden auch mit Zustimmung nicht gewährt.

### Werkzeuge, Plugins, Abläufe (Phasen 6, 9, 19)

- `backend/tools/` mit acht Werkzeugen. Rechenausdrücke werden über einen
  geprüften Syntaxbaum ausgewertet, nicht über `eval`.
- Die Werkzeugschleife bricht ab, wenn dasselbe zweimal aufgerufen wird.
- `backend/plugins/` mit Manifest, Freigabe und Beispiel unter
  `plugins/beispiel/`. Ein Plugin darf nur Werkzeuge anmelden, deren
  Berechtigung im Manifest steht.
- `backend/workflows/` mit Bedingungen, Wertübergabe, Fehlerregeln je
  Schritt, Pausieren und Abbrechen.

### Wissen und Forschung (Phasen 7, 11, 18)

- `backend/graph/` – Knowledge Graph mit elf Knoten- und sieben
  Beziehungsarten, Widerspruchsübersicht, Export.
- `backend/knowledge/` – Wissensbasis mit Quellenangabe.
- `backend/research/` – Quellenkritik, Thesenprüfung, Erkennung von
  Fehlschlüssen, Gliederungsgerüste. Der Orb schreibt keine Arbeiten; er
  stellt Rückfragen und zeigt Lücken.
- `backend/learning/flashcards.py` – Karteikarten mit abgestuften
  Wiederholungen nach SM-2.
- `backend/learning/study_plan.py` – Lernpläne bis zu einem Termin.

### Darstellung (Phase 14)

- `desktop/shaders/smoke.glsl` – volumetrischer Nebel im Inneren des Orb.
  Für jeden Bildpunkt wird durch die Kugel marschiert; Mehrfachrauschen und
  Raumverzerrung erzeugen Schwaden und Wirbel ohne sichtbare Kacheln.
- Zustandsabhängig: ruhig im Leerlauf, wirbelnd beim Denken, pulsierend
  beim Sprechen, warmer Warnschimmer bei einem Fehler.
- Bei schwacher Leistung werden zuerst die Schritte gesenkt, dann der Nebel
  abgeschaltet.

### Weiteres

- `backend/vision/` – Bildschirmaufnahme, lokale Texterkennung,
  Bildbeschreibung. Aufnehmen und Übertragen sind getrennte Vorgänge mit
  getrennter Zustimmung.
- `backend/presence/` – Stimmung, Tagesrhythmus, Persönlichkeit.
- `backend/behavior/usage_heatmap.py` – Nutzungskarte des Bildschirms.
- `backend/system/window_control.py` – Fenster finden, fokussieren,
  verschieben, nebeneinanderlegen. Es wird nie etwas geschlossen.
- `backend/ai/` – Anbieterverzeichnis, Fabrik mit Vorabprüfung und die
  robuste Antwortpipeline. Eine leere oder ungültige Antwort kommt nicht
  mehr durch.
- `upgrade.py` – Ein-Kommando-Upgrade mit Sicherung, Tests und
  selbsttätiger Rücknahme.
- `REPARIEREN-UND-STARTEN.bat` installiert jetzt auch die Sprachpakete und
  prüft am Ende selbst nach, ob die Sprachsteuerung bereit ist.
- 96 API-Endpunkte, 241 Tests, alle bestehen.

### Behoben

- Die Wissensbasis fand deutsche Zusammensetzungen nicht: „Sonderweg" traf
  nicht auf „Sonderwegsthese". Jetzt werden Stammformen gebildet und lange
  Wörter zusätzlich zerlegt.
- Der Lernplan legte ein Thema, das allein länger dauert als ein Lerntag,
  immer erst auf den Folgetag – heute stand dann nichts an.
- `KnowledgeGraph.connect` meldete bei einem Fehler nur, dass ein Knoten
  nicht angelegt werden konnte, nicht warum.

## [0.2.2] – Ein Klick repariert alles

### Hinzugefügt

- **`REPARIEREN-UND-STARTEN.bat`** – ein Doppelklick genügt. Die Datei
  prüft und repariert der Reihe nach: Python-Environment, fehlende
  Python-Pakete, Node-Pakete, den Build der Oberfläche, die
  Startmenü-Einträge – und startet AI-Orb anschließend.

  Jeder Schritt prüft sein Ergebnis gegen. Insbesondere wird nach dem Bauen
  nachgesehen, ob der aktuelle Code tatsächlich in den erzeugten Dateien
  steht; genau dieser stille Fehlschlag hatte zuvor dazu geführt, dass der
  Orb zu groß blieb. Schlägt etwas fehl, steht die Ursache im Klartext samt
  dem, was zu tun ist – kein Traceback, keine Rätsel.

## [0.2.1] – Symbolgröße und Build-Prüfung

### Geändert

- **Der Orb ist jetzt symbolgroß.** `orb.scale` steht auf 0.20; das ergibt
  etwa 55 Pixel im Ruhezustand, 39 im Schlaf und 72 beim Zuhören – die
  Größe eines Desktopsymbols. Die Anhaltswerte für andere Größen stehen als
  Tabelle in `config.yaml`.

### Hinzugefügt

- `rebuild.bat` und `scripts/rebuild.ps1`: löschen den alten Build, bauen
  neu und **prüfen anschließend nach**, ob der aktuelle Code tatsächlich in
  den erzeugten Dateien steht.

  Anlass: Wird `npm run build` versehentlich vor dem Einspielen eines
  Patches ausgeführt, bleibt die alte Oberfläche bestehen – und das fällt
  nicht auf, weil kein Fehler erscheint. Genau das war die Ursache dafür,
  dass der Orb nach Patch 0.2.0 zu groß blieb: Die Konfiguration war
  aktuell, die gebaute Oberfläche nicht.

## [0.2.0] – Orb-Verhalten und Startmenü

### Behoben

- **Der Orb bewegte sich ruckelig, wenn er auswich.** Bisher wurde 60-mal
  je Sekunde das Fenster verschoben; transparente Always-on-top-Fenster
  bewegen sich unter Windows dabei sichtbar stockend. Das verstieß gegen
  die Vorgabe „Keine Sprünge. Keine Teleportation." aus v2 Phase 3.

  Der Orb bewegt sich jetzt **innerhalb** eines größeren, unsichtbaren
  Fensters – gezeichnet von der Grafikkarte und dadurch flüssig. Das
  Fenster wird nur noch versetzt, wenn das Ziel außerhalb liegt; dabei wird
  der Versatz gegengerechnet, sodass der Orb optisch stehen bleibt und von
  dort weich weiterläuft. Die bereits vorhandene Bewegungs-Engine mit
  Tweening, Bézier und Federanimation ist damit erstmals wirksam.

### Hinzugefügt

- **Zustandsabhängige Größe.** Der Orb zieht sich im Ruhezustand zusammen
  (0.88), im Schlaf deutlich (0.62), und richtet sich beim Zuhören auf
  (1.14). Die Änderung läuft über dieselbe weiche Interpolation wie Farbe
  und Geschwindigkeit – ohne sichtbaren Sprung. Je Zustand in `config.yaml`
  unter `states` einstellbar.
- **Startmenü-Einträge.** `scripts/create-shortcut.ps1` legt unter „AI-Orb"
  Verknüpfungen zum Starten, Beenden, für den reinen Backend-Betrieb, für
  die Konfiguration und für die Protokolle an. Wird von `install.ps1`
  automatisch aufgerufen. Optional mit `-Autostart` (Start bei der
  Anmeldung) und `-Desktop`; `-Remove` entfernt alles wieder.
- `scripts/stop-orb.ps1` beendet gezielt die Prozesse dieses
  Projektordners – andere Python- oder Electron-Programme bleiben
  unangetastet.
- Der Abschnitt `smart_desktop` steht jetzt in `config.yaml`, statt nur
  dokumentiert zu sein.

### Geändert

- **Der Orb ist kleiner.** Neu ist `orb.scale` (Voreinstellung 0.42) – die
  sichtbare Größe ist damit unabhängig von der Fenstergröße einstellbar.
- `window.width`/`height` bedeuten jetzt den **Bewegungsraum**, nicht die
  Orb-Größe (Voreinstellung 520 statt 220).
- Die Trefferfläche für Klicks folgt der tatsächlichen Größe und Position
  des Orb, statt an der Fenstermitte zu kleben. Ein Mindestradius hält ihn
  auch im Schlafzustand bequem anklickbar.

### In Arbeit

- Spracheingabe und Sprachausgabe (Whisper, Kokoro, Weckwort „Hallo Orb")
  sind begonnen, aber noch nicht Teil dieser Fassung.

## [0.1.3] – Start der Oberfläche repariert

### Behoben

- **Die Oberfläche startete unter Windows nicht.** Das Startskript rief
  Electron über `npx` auf. `Start-Process` greift dabei die endungslose
  Datei `npx` ab – ein Shell-Skript für Git Bash – statt `npx.cmd`, und
  bricht mit „%1 ist keine zulässige Win32-Anwendung" ab. Electron wird nun
  direkt über `node_modules\electron\dist\electron.exe` gestartet, mit
  `node_modules\.bin\electron.cmd` als Ersatzweg. Fehlt beides, nennt das
  Skript den Grund und den passenden Befehl.

### Hinzugefügt

- Der Hauptprozess spiegelt Warnungen und Fehler der Oberfläche in die
  Konsole. Da das Orb-Fenster transparent ist, wäre ein Absturz im Renderer
  sonst schlicht als „nichts" sichtbar gewesen.
- Fehlgeschlagenes Laden der Oberfläche und ein beendeter Renderer werden
  ausdrücklich gemeldet, statt unbemerkt zu bleiben.

## [0.1.2] – Installation repariert

### Behoben

- **Die Installation schlug still fehl.** In `requirements.txt` standen noch
  FastAPI, uvicorn, websockets, pydantic und httpx – Reste aus dem ersten
  Entwurf, bevor der Server auf die Standardbibliothek umgestellt wurde.
  Ließ sich eines dieser Pakete auf der vorhandenen Python-Version nicht
  bauen, brach `pip install` vollständig ab, und dadurch fehlte auch das
  tatsächlich benötigte PyYAML. Das Backend stürzte beim Start mit
  `ModuleNotFoundError: No module named 'yaml'` ab.
- Das Installationsskript wertete diesen Fehler nur als Warnung. Es bricht
  jetzt hart ab, zeigt die vollständige Meldung von pip und prüft
  anschließend gegen, ob sich das Paket wirklich importieren lässt.
- Das Startskript prüft vor dem Start, ob PyYAML vorhanden ist, und nennt
  im Fehlerfall den passenden Befehl – statt eines Tracebacks.
- **Die Datei `.env` wurde von niemandem gelesen.** Ein dort hinterlegter
  `ANTHROPIC_API_KEY` wäre daher wirkungslos geblieben.

### Hinzugefügt

- `backend/config/env_loader.py`: liest `.env` mit der Standardbibliothek.
  Bereits gesetzte Umgebungsvariablen behalten Vorrang, leere Platzhalter
  aus der Vorlage überschreiben nichts. 13 zugehörige Tests.
- `requirements-dev.txt` für die Test-Pakete, damit ein Problem dort den
  normalen Betrieb nie verhindern kann.

### Geändert

- `requirements.txt` enthält nur noch `PyYAML>=6.0` – die einzige
  Abhängigkeit des Backends. Ohne feste Versionsnummer, damit die
  Installation nicht an einer fehlenden Paketfassung scheitert.

## [0.1.1] – Claude als primäres Modell

### Hinzugefügt

- Neuer Provider `claude_code`: spricht Claude über die lokal angemeldete
  Claude-Code-Befehlszeile an und nutzt damit ein **Abonnement** (Pro oder
  Max) statt eines API-Schlüssels. Läuft asynchron in einem eigenen Prozess,
  in einem leeren Arbeitsverzeichnis unter `data/claude_workspace`, damit
  keine Projektdateien mitgelesen werden.
- Neuer Provider `claude`: spricht die Anthropic Messages API direkt an.
  Beherrscht die Trennung von Systemtext und Verlauf, das Zusammenfassen
  aufeinanderfolgender gleicher Rollen und die automatische Modellwahl über
  `model: auto`.
- Verständliche Fehlermeldungen für die häufigen Fälle: fehlende Anmeldung,
  erschöpfte Nutzungsgrenze, abgelehnter API-Schlüssel, unbekanntes Modell.
- 18 zusätzliche Tests für beide Claude-Provider.

### Geändert

- `config.yaml`: `ai.primary` steht nun auf `claude_code` mit dem stabilen
  Modell-Kurznamen `sonnet`. Die Varianten für API-Schlüssel und für
  OpenAI-kompatible Dienste stehen auskommentiert daneben.
- `.env.example` erklärt den Unterschied zwischen Abonnement und
  API-Schlüssel.

### Behoben

- Zwei Build-Fehler in `desktop/electron/main.ts`: `readConfig` leitete aus
  dem Vorgabewert einen Literaltyp ab, wodurch TypeScript die Vergleiche in
  `glideTo` und in der Doppelklick-Aktion für unmöglich hielt.
- Beim Herunterfahren konnten Hintergrundaufgaben offen bleiben, wenn der
  Startvorgang noch lief. Es werden nun alle verbliebenen Aufgaben geordnet
  abgebrochen.

### Beibehalten

- Die Provider `ollama` und `hermes` bleiben unverändert verfügbar; es wurde
  nichts entfernt.

## [0.1.0] – Erste vollständige Fassung

Diese Fassung setzt beide Lastenhefte um: AI-Orb v2 (Phasen 1 bis 5) und
AI-Orb v3 (Phasen 1 bis 6).

### Grundlage und Architektur (v2 Phase 1)

- Layer-Architektur mit strikter Trennung: Daten, System, KI, Kognition,
  Erweiterungen, Desktop.
- Zentraler asynchroner Event Bus mit Wildcard-Abonnement; alle Module
  kommunizieren ausschließlich darüber oder über das Cognitive Core.
- Konfigurationssystem auf Basis von `config.yaml` – keine hartkodierten
  Werte, insbesondere keine Modellnamen.
- Logging mit eigener Datei je Modul plus zentralem Systemlog, mit Rotation.
- Lokaler HTTP-/SSE-Server ausschließlich mit der Python-Standardbibliothek,
  gebunden an `127.0.0.1`.
- Atomarer JSON-Speicher, der einen Absturz während des Schreibens übersteht.

### Orb-Oberfläche (v2 Phase 2)

- Transparentes, rahmenloses, immer im Vordergrund liegendes Fenster ohne
  Taskleisteneintrag, mit GPU-Beschleunigung.
- Orb als Energieobjekt aus Kern, Hülle, Aura, Partikeln und Licht – mit
  Fresnel-Effekt, simulierter Brechung, innerer Strömung, emissivem Material
  und additivem Blending.
- Bloom-Postprocessing mit weicher Randausblendung, sodass kein
  rechteckiger Fensterrand sichtbar ist.
- Zustandsmaschine mit sieben Zuständen (idle, listening, thinking,
  speaking, busy, error, sleep) und weichen Übergängen.
- Presence-Engine für Atmung, Schweben, Neigung und Mikrobewegungen.
- Interaktion: Linksklick, Rechtsklick, Hover, Drag, Doppelklick.
- Sechs Farbthemes: Blue, Purple, Green, Red, White, Cyber.
- Automatische Qualitätsanpassung und Energiesparen bei Inaktivität.

### Smart Desktop Engine (v2 Phase 3)

- Multi-Monitor-Unterstützung inklusive Hotplug, DPI-Skalierung und
  Monitorwechsel.
- Scoring-Modell für Positionen: freie Fläche, Abstand zur Maus, Abstand zu
  aktiven Fenstern, Benutzerpräferenz, selten genutzte Bereiche – abzüglich
  Cursornähe, Überdeckung wichtiger Bedienelemente und Vollbild.
- Weiche Bewegung über Tweening, Bézier und Federanimation; keine Sprünge.
- Lernsystem: manuell gewählte Positionen erhalten das fünffache Gewicht,
  Gewichte verlieren über die Zeit an Bedeutung.
- Ausweichen vor der Maus, Ausblenden bei Vollbild.

### Orchestrator und KI-Provider (v2 Phase 4)

- Intent-Klassifikation mit über zwanzig Intents, vollständig lokal.
- Entscheidung, ob eine Aufgabe überhaupt ein Sprachmodell benötigt.
- Task-Routing an lokale Module oder an den Provider.
- Provider Manager mit Gesundheitsüberwachung und automatischer Umschaltung
  zwischen Online- und Offline-Modell, ohne Kontextverlust.
- Erweiterbar um weitere Provider ohne Änderung am Orchestrator.

### Memory Engine (v2 Phase 5)

- Fünf Gedächtnisarten: Working, Conversation, User, Knowledge, Task.
- Entscheidung, ob eine Information überhaupt gespeichert wird.
- Semantische Suche ohne externe Embedding-Modelle.
- Gedächtnisbildung: Wiederholung verstärkt statt zu duplizieren.
- Vergessen mit konfigurierbarer Halbwertszeit.
- Wissensgraph mit Verknüpfungen zwischen Einträgen.
- Vollständige Einsicht, Bearbeitung und Löschung durch den Benutzer.

### Cognitive Core (v3 Phase 1)

- Zentrales Gehirn, über das alle Module kommunizieren.
- Working Memory mit Ablaufzeit, Long Term Memory nach Kategorien.
- Kontextmanager für Projekt-, Arbeits-, Gesprächs- und Lernkontext.
- Goal Manager mit vier Zeithorizonten, Status, Priorität und Fortschritt.
- Task Manager mit selbstständiger Zerlegung bekannter Aufgabenarten.
- Decision Engine, Planner, Reflection Engine, Reasoning Context.

### Reasoning und Planung (v3 Phase 2)

- Task Analyzer mit Art, Komplexität, Dringlichkeit, Risiko und Zeitaufwand.
- Strategy Selector, der aus vergangenen Erfolgen lernt.
- Plan Generator, der einfache Aufgaben bewusst nicht verkompliziert.
- Confidence Estimator – Kategorien statt Prozentwerte.
- Decision Tree für Antwort, Recherche, Rückfrage oder Bestätigung.
- Verification Engine für Widersprüche, Belege und Quellendokumentation.
- Execution Manager mit vollständigem Ablauf und Alternativen bei Fehlern.

### Project Intelligence (v3 Phase 3)

- Automatische Projekterkennung mit ausdrücklicher Rückfrage bei
  Unsicherheit.
- Projektgedächtnis mit Notizen, Literatur, Dateien, Gliederungen,
  Entscheidungen und offenen Fragen.
- Dokumentverfolgung mit Versionserkennung über Prüfsummen.
- Projektgraph, Workspace-Verwaltung, Sitzungen und Meilensteine.
- Projektzusammenfassung als Antwort auf „Woran arbeite ich gerade?“.

### Evolution Engine (v3 Phase 4)

- Analyse von Code, Architektur, Leistung und Fehlern.
- Begründete Verbesserungsvorschläge, Skill-Vorschläge aus beobachteter
  Nutzung.
- Patches ausschließlich in isolierter Arbeitskopie mit eigenem Git-Branch.
- Sechs Testarten vor jeder Freigabe, Benchmark-Vergleich, automatisches
  Review mit gekennzeichneten Unsicherheiten.
- Vollständiger Rollback jeder Änderung.
- Skill Trainer, der komplette Skill-Gerüste erzeugt.

### Multi-Agent-System (v3 Phase 5)

- Zehn spezialisierte Agenten mit eigenen Prompts, Werkzeugen und Regeln.
- Agent Router mit Reihenfolge- und Parallelitätsentscheidung.
- Scheduler mit Zeitlimit und Ersatzagenten bei Ausfall.
- Result Merger für Konflikterkennung und Zusammenführung.
- Capability Registry und Kennzahlen je Agent.

### Skill- und Plugin-System (v3 Phase 6)

- Dynamisches Laden ohne Neubau des Kerns.
- Prüfung auf Kompatibilität, Abhängigkeiten, Berechtigungen,
  Sicherheitsrisiken und Tests – inklusive Quellcode-Analyse.
- Berechtigungssystem mit neun Rechten, jederzeit änderbar.
- Vorgegebener Installationsablauf mit Bestätigungspflicht.
- Updates mit Rückfrage bei neuen Rechten, Rollback und Änderungshistorie.
- Lokaler Skill-Katalog mit vorbereiteten Einträgen.

### Werkzeuge und Dokumentation

- Windows-Installations- und Startskripte mit Voraussetzungsprüfung und
  verständlichen Fehlermeldungen.
- 105 Tests über alle Schichten, einschließlich Integrationstests gegen die
  laufende HTTP-API.
- Vollständige Dokumentation zu Architektur, Modulen, API, Ereignissen,
  Konfiguration und Skill-Entwicklung.

### Bekannte Einschränkungen

- Spracheingabe (Whisper), Sprachausgabe (Kokoro) und Bildschirmauswertung
  (Vision/OCR) sind vorbereitet, aber noch nicht umgesetzt; sie werden über
  das Skill-System nachgerüstet.
- Die Fenstererkennung der Smart Desktop Engine leitet belegte Bereiche aus
  der Arbeitsfläche ab. Eine genaue Aufzählung fremder Fenster erfordert
  einen zusätzlichen Skill.
