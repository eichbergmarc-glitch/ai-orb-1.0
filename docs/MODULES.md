# Module von AI-Orb

Diese Übersicht listet alle Module mit ihrer Verantwortlichkeit. Jede Datei
besitzt zusätzlich einen ausführlichen Docstring, der die Details erklärt.

## backend/utils – Grundlagen

`paths.py` löst alle Projektpfade auf, damit die Wurzel an genau einer
Stelle bestimmt wird. `store.py` stellt den atomaren JSON-Speicher bereit:
Er schreibt über eine temporäre Datei und benennt sie erst danach um, sodass
ein Absturz während des Schreibens keine Datei beschädigen kann.
`text.py` liefert Tokenisierung mit deutscher und englischer Stoppwortliste,
eine Wortstammnäherung, Kosinus-Ähnlichkeit und eine extraktive
Zusammenfassung – alles ohne externe Bibliotheken, damit AI-Orb auch ohne
Embedding-Modelle semantisch suchen kann.

## backend/config, backend/system, backend/events – Systemschicht

`config/config_loader.py` liest `config.yaml` und bietet Zugriff über
punktgetrennte Pfade. `system/logging_setup.py` richtet das Logging ein:
jedes Modul erhält eine eigene rotierende Datei, zusätzlich läuft alles in
`logs/system.log` zusammen. `system/desktop_control.py` ist die einzige
Stelle, die Programme startet; sie arbeitet mit einer Allowlist und
verlangt für das Beenden fremder Programme eine ausdrückliche Bestätigung.
`events/event_bus.py` implementiert den asynchronen Publish/Subscribe-Bus
inklusive Wildcard-Abonnement, über das der API-Server alle Ereignisse an
die Oberfläche weiterreicht.

## backend/memory – Memory Engine

`memory_store.py` verwaltet die Einträge und deren Persistenz,
`memory_index.py` hält einen invertierten Token-Index für die schnelle
Vorauswahl, `memory_search.py` bewertet Treffer aus Ähnlichkeit,
Wichtigkeit, Aktualität und Nutzungshäufigkeit.

Darauf setzen die fachlichen Sichten auf: `conversation_memory.py` für
verdichtete Gesprächszusammenfassungen, `user_memory.py` für das
Benutzerprofil mit Arbeitszeiten und Programmnutzung, `knowledge_memory.py`
für Sachwissen samt Wissensgraph, `task_memory.py` für Aufgaben.
`summary_engine.py` fasst zusammen – mit Sprachmodell, wenn verfügbar, sonst
rein lokal.

`memory_engine.py` ist die Memory API. Sie entscheidet, ob eine Information
überhaupt gespeichert wird, verstärkt wiederholt auftretende Informationen
statt Duplikate anzulegen und lässt unwichtige Einträge über die Zeit an
Gewicht verlieren.

## backend/orchestrator – Orchestrierung und Modelle

`intent_classifier.py` ordnet Eingaben einem von über zwanzig Intents zu –
vollständig lokal über gewichtete Schlüsselwörter und Muster. Das ist die
Grundlage dafür, dass "Firefox starten" ohne Sprachmodell auskommt.
`task_router.py` leitet Aufgaben an lokale Module oder an den Provider
weiter. `conversation_manager.py` verwaltet Verlauf und Kontextfenster und
verdichtet ältere Abschnitte automatisch.

`provider_manager.py` wählt den Provider, überwacht ihn über
`provider_health.py` und schaltet automatisch um: Ist Hermes nicht
erreichbar, übernimmt Ollama; kommt Hermes zurück, wird je nach
Konfiguration sofort oder erst nach Ende der Unterhaltung zurückgewechselt.
Der Kontext geht dabei nie verloren. `providers/` enthält die
Basisschnittstelle und die beiden Implementierungen.

`orchestrator.py` verbindet all das zum Ablauf einer Anfrage.

## backend/cognitive – Cognitive Core

`cognitive_core.py` ist das zentrale Gehirn und die einzige Stelle, über die
Module miteinander sprechen. `working_memory.py` hält das Kurzzeitgedächtnis
mit Ablaufzeit, `long_term_memory.py` bietet die kategorisierte Sicht auf das
dauerhafte Wissen. `context_manager.py` verwaltet Projekt-, Arbeits-,
Gesprächs- und Lernkontext strikt getrennt.

`goal_manager.py` verwaltet Ziele über vier Zeithorizonte mit Status,
Priorität, Fortschritt und nächsten Schritten. `task_manager.py`
strukturiert Aufgaben und zerlegt bekannte Aufgabenarten selbstständig.
`project_manager.py` steuert die Project Intelligence Engine an.

`decision_engine.py` klärt vor jeder Antwort die sechs Leitfragen,
`planner.py` erzeugt Schrittfolgen, `reflection_engine.py` wertet
abgeschlossene Aufgaben aus, `reasoning_context.py` trennt Fakten,
Annahmen, Vermutungen, Interpretationen und Quellen voneinander.
`orchestrator.py` verteilt zusammengesetzte Aufgaben auf Fach-Engines.

## backend/reasoning – Denken vor dem Antworten

`task_analyzer.py` erstellt das Task Profile mit Art, Komplexität,
Dringlichkeit, Risiko, benötigten Informationen und Zeitaufwand.
`strategy_selector.py` wählt die Strategie und bevorzugt dabei solche, die
sich laut Reflexion bereits bewährt haben. `plan_generator.py` erzeugt den
Plan – aber nur, wenn die Komplexität ihn rechtfertigt.

`confidence_estimator.py` berechnet die interne Sicherheit und gibt sie
ausschließlich als Kategorie nach außen, niemals als Prozentwert.
`decision_tree.py` bildet den vorgegebenen Entscheidungsbaum ab.
`verification_engine.py` sucht Widersprüche und prüft Belege.
`execution_manager.py` führt Desktop-Aktionen mit vollständiger
Ablaufkontrolle und Alternativen aus. `reflection_manager.py` begleitet
Aufgaben und stößt die Nachbetrachtung an. `reasoning_engine.py` verbindet
alles zum Denkvorgang.

## backend/projects – Project Intelligence

`project_detector.py` erkennt anhand des Verzeichnisinhalts, ob es sich um
ein Software-, Schreib-, Forschungs- oder Dokumentenprojekt handelt – und
sagt ausdrücklich, wenn es sich nicht sicher ist. `project_memory.py`
speichert je Projekt Beschreibung, Notizen, Literatur, Dateien,
Gliederungen, Entscheidungen und offene Fragen.

`document_tracker.py` verfolgt Dokumente über Prüfsummen und erkennt neue
Versionen, `dependency_graph.py` baut den Projektgraphen aus Dokumenten,
Literatur, Aufgaben, Kapiteln, Quellen und Fragestellungen.
`workspace_manager.py` merkt sich den Arbeitszustand – Browser-Tabs nur mit
ausdrücklicher Zustimmung. `session_manager.py` regelt Arbeitsbeginn und
-ende, `milestone_manager.py` verwaltet Phasen und Fristen und erinnert nur,
wenn die Erinnerung aktiviert wurde. `project_context.py` und
`project_summary.py` liefern den Projektbezug für Antworten und die Antwort
auf "Woran arbeite ich gerade?". `project_engine.py` bündelt alles.

## backend/agents – Multi-Agent-System

`base_agent.py` definiert die gemeinsame Schnittstelle,
`standard_agents.py` die zehn Agenten: Conversation, Reasoning, Research,
History, Coding, Desktop, Vision, Voice, Memory und Evolution. Jeder besitzt
eigene Prompts, eigene Werkzeuge und eigene Regeln.

`agent_registry.py` verwaltet und testet sie, `capability_registry.py` hält
fest, wer was kann und welche Rechte er hat. `agent_router.py` entscheidet,
welche Agenten gebraucht werden, in welcher Reihenfolge und was parallel
laufen darf. `agent_scheduler.py` führt den Plan aus, mit Zeitlimit und
Ersatzagenten. `result_merger.py` führt die Ergebnisse zusammen, erkennt
Konflikte und entfernt Doppelungen. `agent_metrics.py` erfasst Kennzahlen,
`task_dispatcher.py` und `agent_manager.py` bilden die Klammer.

## backend/skills – Skill- und Plugin-System

`skill_registry.py` führt alle installierten Skills mit Status, Version und
Berechtigungen. `skill_validator.py` prüft vor der Installation
Kompatibilität, Abhängigkeiten, Berechtigungen, Sicherheitsrisiken und
Tests – und analysiert dafür den Quellcode des Skills.
`skill_permissions.py` verwaltet die neun Berechtigungsarten,
`skill_installer.py` führt den vorgegebenen Installationsablauf durch,
`skill_updater.py` prüft Updates und ermöglicht Rollbacks,
`skill_loader.py` lädt Skills dynamisch und stellt ihnen die Skill-API
bereit, `skill_documentation.py` erzeugt die Dokumentation,
`skill_marketplace.py` verwaltet den lokalen Katalog.

## backend/evolution – Selbstverbesserung

`code_analyzer.py`, `architecture_analyzer.py` und `performance_analyzer.py`
untersuchen Modulgrößen, Komplexität, Dokumentation, Testabdeckung,
Kopplung, Zyklen, blockierende Aufrufe und Speicherrisiken.
`bug_detector.py` liest die Logs, gruppiert ähnliche Fehler und priorisiert
sie. `idea_generator.py` leitet daraus begründete Vorschläge ab.

`patch_generator.py` erzeugt Änderungen ausschließlich in einer isolierten
Arbeitskopie mit eigenem Git-Branch. `testing_engine.py` führt Syntax-,
Unit-, Integrations-, Regressions-, Leistungs- und Sicherheitsprüfungen aus.
`benchmark_engine.py` vergleicht alte und neue Version.
`review_engine.py` prüft Lesbarkeit, Architektur, Sicherheit,
Dokumentation, Tests und Abwärtskompatibilität und kennzeichnet, was es
nicht sicher beurteilen kann. `release_manager.py` schlägt nur geprüfte
Änderungen vor, `rollback_manager.py` sichert vorher jede betroffene Datei.
`skill_trainer.py` erzeugt vollständige Skill-Gerüste.

## desktop/electron – Hauptprozess

`main.ts` erzeugt das transparente, rahmenlose Fenster, liest `config.yaml`
mit einem eigenen, abhängigkeitsfreien Parser und registriert die
IPC-Handler. `preload.ts` ist die abgesicherte Brücke zum Renderer.
`window_manager.ts` verwaltet Position und Persistenz,
`monitor_manager.ts` erkennt Monitore samt Hotplug,
`placement_engine.ts` bewertet Positionen nach dem vorgegebenen
Scoring-Modell, `desktop_manager.ts` verbindet beides zur Smart Desktop
Engine.

## desktop/renderer – Die Orb-Engine

`renderer.ts` baut Szene, Kamera und WebGL-Kontext auf. `orb.ts` erzeugt
Kern, Hülle, Aura, Partikel und Licht. `effects.ts` liefert die
Shader-Materialien und den Bloom-Stapel samt weicher Randausblendung.
`states.ts` implementiert die sieben Zustände mit weichen Übergängen und die
sechs Themes. `presence.ts` sorgt für Atmung und Mikrobewegungen,
`movement.ts` für weiche Wege ohne Sprünge, `interaction.ts` für Klick,
Rechtsklick, Hover, Drag und Doppelklick. `animation.ts` steuert die
Bildrate und die automatische Qualitätsanpassung, `api.ts` die Verbindung
zum Backend, `main.ts` verbindet alles.
