# AI-Orb — Architektur (Stand 01.09.2026)

Geschrieben für eine KI, die an diesem Projekt arbeiten soll. Alle Angaben
sind am Quelltext auf diesem Rechner geprüft, nicht aus der Dokumentation
übernommen. Wo die vorhandene Doku veraltet ist, steht es am Ende.

Umfang: ~287 Module, ~87.000 Zeilen Python im Backend, dazu eine
Electron-Oberfläche. Sprache im Code: Deutsch (Bezeichner, Kommentare,
Log-Ausgaben). Wer hier arbeitet, schreibt deutsche Kommentare.

---

## 1. Was der Orb ist

Ein lokal laufender Sprachassistent mit Dauerpräsenz: eine schwebende Kugel
auf dem Desktop, die zuhört, antwortet, spricht und auf dem Rechner handelt
(Dateien, Programme, Browser, Mail, Kalender). Fachlicher Schwerpunkt des
Benutzers: Geschichte, Philosophie, Linguistik — daher ein eigener
Professor-/Mentor-Modus.

Vier Grundregeln, die der Aufbau durchhält:

1. **Ein Ort für jede Entscheidung.** Module reden nicht direkt miteinander,
   sondern über das Cognitive Core oder den Event Bus.
2. **Keine hartkodierten Einstellungen.** Alles steht in `config.yaml` und
   wird über `backend/config/config_loader.py` gelesen. Modellnamen,
   Zeitlimits, Schwellwerte — nichts davon im Code.
3. **Daten bleiben lokal.** Geschrieben wird nach `data/` bzw. in das
   Benutzerdatenverzeichnis (`backend/utils/paths.py`).
4. **Alles asynchron.** Der ganze Kern läuft auf EINER asyncio-Loop in einem
   eigenen Thread. Blockierendes geht in Worker-Threads.

---

## 2. Prozesse und Einstiegspunkte

```
ORB-STARTEN.bat
  └─ runtime/python/python.exe -m backend.main [--launcher|--check]
       ├─ backend/launcher/launcher.py     Startprüfung, Dienstüberwachung
       │    ├─ health_check.py             Startbericht (Phase-59-Format)
       │    ├─ supervisor.py               Wächter: Dienste neu starten
       │    └─ ollama_service.py           lokales Modell hochfahren
       ├─ backend/runtime.py               DER KERN (Singleton, get_runtime())
       └─ backend/api/http_server.py       HTTP + SSE für die Oberfläche
desktop/electron + desktop/renderer      Electron-Oberfläche (die Kugel)
```

* `backend/runtime.py` ist die Montagehalle: ~1400 Zeilen, baut in
  `__init__` alle Bauteile in **sieben Schichten** (Kommentare
  `# --- Schicht N` im Code) und startet in `_boot()` die Hintergrundläufe.
* `Runtime.start()` legt einen Thread an, darin eine neue Event-Loop, darin
  `_boot()`. `Runtime.run(coro)` reicht Coroutinen aus fremden Threads
  (HTTP-Server) auf diese Loop.
* Die Oberfläche spricht **HTTP + Server-Sent-Events** mit dem Backend
  (`backend/api/server.py`: `SseBroker`, `ApiRouter`). Kein WebSocket.

---

## 3. Die sieben Schichten (Reihenfolge = Abhängigkeitsrichtung)

| # | Schicht | Bauteile | Ort |
|---|---------|----------|-----|
| 0 | Sicherheit | `SecurityEngine`, `ConsentManager`, `PathGuard`, `AuditLog`, `permissions.py` | `backend/security/` |
| 1 | Gedächtnis & Wissen | `MemoryEngine`, `KnowledgeBase`, `KnowledgeGraph`, `PreferenceLearner`, `FlashcardDeck`, `StudyPlanner` | `backend/memory/`, `knowledge/`, `graph/`, `learning/` |
| 2 | Modelle & Orchestrierung | `ProviderManager`, `ProviderHealth`, `Orchestrator`, `ConversationManager`, `IntentClassifier`, `TaskRouter` | `backend/orchestrator/` |
| 3 | Cognitive Core | `CognitiveCore` — Zerlegung in Teilaufgaben, Projektkontext, Transparenz | `backend/cognitive/` |
| 4 | Selbstverbesserung, Skills, Agenten | `EvolutionEngine`, `DesktopControl`, `BehaviorEngine`, `ResearchEngine`, `AgentManager`, `SkillManager` | `backend/evolution/`, `agents/`, `skills/`, `research/` |
| 5 | Werkzeuge & Plugins | `ToolRegistry`, `ToolEngine`, ~26 Werkzeugmodule, `PluginManager` | `backend/tools/`, `plugins/` |
| 6 | Präsenz, Sprache, Bild | `PresenceEngine`, `VisionEngine`, `VoicePipeline`, `TtsManager`, `AudioCapture` | `backend/presence/`, `vision/`, `voice/`, `tts/`, `audio/` |

Grösste Pakete nach Zeilen: `tools` (9.9k), `orchestrator` (7.0k), `voice`
(5.6k), `tts` (4.8k), `evolution` (4.4k), `studium` (4.3k).

---

## 4. Der Weg einer gesprochenen Frage

Das ist der wichtigste Pfad. Fast jeder Fehler des Orb sitzt an einem der
**Tore** darin — Stellen, an denen eine Anfrage stillschweigend abbiegt.

```
Mikrofon
 └─ audio/audio_capture.py      VAD, schneidet Äusserungen (silence_ms,
    (eigener Thread)            max_utterance_seconds, preroll)
       │  parallel: Stop-Späher — 600-ms-Fenster WÄHREND der Orb spricht
       ▼
 whisper/transcriber.py         faster-whisper, eigene Reihen-Sperre,
                                verfallen_nach = Riegel gegen Warteschlangen
       ▼
 voice/voice_pipeline.py        (3.800 Zeilen, das komplexeste Modul)
   ├─ Tor 1: _ist_geplapper / _ist_whisper_phantom → verwerfen
   ├─ Tor 2: Sprechererkennung (speaker_id) → wer redet da?
   ├─ Tor 3: schlafend/wach, Weckwort, freie Ansprache
   └─ _handle_while_awake
       ▼
 cognitive/cognitive_core.py    zerlegt ggf. in Teilaufgaben
       ▼
 orchestrator/orchestrator.py :: handle()
   ├─ IntentClassifier          Schlüsselwörter + Muster → Intent
   ├─ TaskRouter.route()        ►► Tor 4 ◄◄ handled_locally=True beendet
   │                            hier ALLES: kein Modell, keine Werkzeuge
   ├─ agents/history_agent/bridge.py  ►► Tor 5 ◄◄ Professor übernimmt
   ├─ _answer_with_model()
   │    ├─ Gedächtniskontext, Vorabsuche bei "Aktuellem"
   │    ├─ ►► Tor 6 ◄◄ model_tools_available =
   │    │      tools_available and not vorlesungssegment
   │    │      and preferred_spoken is None
   │    │      and (not spoken or braucht_werkzeuge(text)
   │    │           or braucht_aktuelles(text))
   │    ├─ ProviderManager.chat/chat_stream
   │    └─ ToolEngine-Schleife (max_rounds)
   └─ asyncio.wait_for(ai.answer_timeout_seconds)  Gesamtfrist
       ▼
 orchestrator/speech_stream.py  Satz für Satz an die Ausgabe
       ▼
 tts/tts_manager.py → Engine-Reihe → audio/player.py
```

**Merksatz für Fehlersuche:** Wenn der Orb „nichts tut", steht die Ursache
fast immer an Tor 4, 5 oder 6 — und immer im Protokoll:

* `Intent 'X' an Modul 'Y' geleitet (lokal=True)` → Tor 4 hat geschluckt.
* `Der Professor übernimmt (Fach: …)` → Tor 5.
* `Modellkontext: … Werkzeuge=False` → Tor 6; das Modell hatte keine
  Werkzeuge und konnte gar nicht handeln.

---

## 5. Die Anbieterkette

`backend/orchestrator/provider_manager.py` (1.200 Zeilen) ist der Verteiler.

* **Rollen:** `ai.primary`, `ai.fallback`, `ai.additional.*` aus der
  `config.yaml`. Gebaut über `backend/ai/provider_factory.py`.
* **Reihenfolge** (`_provider_order`): aktiver → primärer → konfigurierte
  Ausweichliste → Rückfall. Quoten-Sperrfristen und bekannt gestörte
  Anbieter rücken ans Ende, fliegen aber nie raus.
* **Gesundheit** (`provider_health.py`): eigener Takt, wachsender Abstand,
  zentrale TCP-Netzprüfung vor teuren Cloud-Prüfungen.
* **Adapter** in `orchestrator/providers/`: `claude_code_provider.py`
  (Prozess-CLI, warm gehalten, liest Dateien selbst),
  `openai_compatible_provider.py` (Chat- **und** Responses-API),
  `ollama_provider.py`, `hermes_provider.py`, u. a.
* Aktuell: primär `claude_code` (sonnet, warmer Prozess), Rückfall
  `ollama` (`lfm2.5:8b`), zusätzlich `ollama_fast`, `openai_terra`.

**Falle:** Bei Reasoning-Modellen (`gpt-5*`) begrenzt `max_output_tokens`
Denken UND Antwort. `_ausgabegrenze()` rechnet deshalb eine Reserve dazu.
Ohne sie kommt `status: incomplete` ohne einen Buchstaben Text zurück.

---

## 6. Werkzeuge

* `tools/registry.py` — `ToolRegistry.register()` **weist ab**, wenn: Name
  doppelt, keine Beschreibung, oder **Berechtigung unbekannt**. Die Abweisung
  ist nur eine Log-Warnung; das Werkzeug fehlt danach lautlos.
* `tools/tool_engine.py` — eigenes **Textprotokoll** statt anbieterspezifischer
  Tool-APIs (`{"werkzeug": "...", "argumente": {...}}`), weil Claude-CLI,
  OpenAI und Ollama sich zu stark unterscheiden. Schleife mit
  `tools.max_rounds`.
* Jedes Werkzeug erbt von `tools/base_tool.py::Tool`: `name`, `description`
  (wird dem Modell wörtlich gezeigt), `permission`, `parameters`, `execute`.
* Angemeldet wird in `runtime.__init__`, Schicht 5. Wer ein Werkzeug
  hinzufügt, muss es dort registrieren — sonst existiert es für das Modell
  nicht.

---

## 7. Sicherheit

`security/permissions.py` zählt alle Berechtigungen abschliessend auf
(`KNOWN_PERMISSIONS`); vier Stufen `SAFE < MODERATE < HIGH < CRITICAL`.
Unbekanntes wird verweigert.

`SecurityEngine.require()` prüft in dieser Reihenfolge: offener Modus →
unbekannt? → in `never_allow` gesperrt? → unbedenklich oder vorab
freigegeben? → sonst fragen (`ConsentManager`, Zeitlimit, Schweigen = Nein).
Kritische Rechte lassen sich **nicht** vorab freigeben und nicht merken.

`security.mode: offen` in der `config.yaml` hebt die gesamte Prüfung auf —
das ist eine ausdrückliche Benutzerentscheidung, aber wer Sicherheitsverhalten
testet, muss sie kennen.

---

## 8. Gedächtnis und Wissen

* `memory/memory_engine.py` — Einträge mit `kind`, `tags`, `source`,
  `certainty`, Wichtigkeit; Ähnlichkeitsprüfung statt Dubletten;
  `apply_forgetting()` löscht nach Halbwertszeit, **ausser** `task` und
  `publikation`.
* `knowledge/knowledge_base.py` — Passagen mit Quellenangabe, die einzige
  zitierfähige Ablage. `SUPPORTED_SUFFIXES` inkl. `.pdf`/`.docx`.
* `graph/` — Wissensgraph; `learning/` — Vorlieben, Karteikarten
  (abgestufte Wiederholung), Lernplan; `studium/` — Landkarte der Fächer,
  Vorlesungen, Aktualisierungskreislauf.
* `research/offene_quellen.py` — GDELT, Wikipedia, OpenAlex, Crossref, RSS.
  `research/nachrichtenlauf.py` — täglicher Nachrichtenlauf.

---

## 9. Nebenläufigkeit — wer läuft wo

| Ausführungsort | Was |
|---|---|
| Kern-Loop (ein Thread) | Orchestrator, Cognitive Core, Agenten, Werkzeuge, Event Bus |
| Aufnahme-Thread | `AudioCapture._process_loop`, VAD, Stop-Späher |
| `asyncio.to_thread` | Whisper, Piper/Pocket-TTS, urllib-Aufrufe |
| eigener Prozess | Claude-Code-CLI, Ollama, Electron |
| Hintergrundaufgaben | `BackgroundTasks` in `_boot`: Wartung, Lernen, Aktualisierung, Nachrichten, Sprachstart |

**Regel:** Der Aufnahme-Thread darf nie warten. Er reicht per
`asyncio.run_coroutine_threadsafe` an die Kern-Loop weiter.

---

## 10. Konfiguration

`config.yaml` im Projektwurzelverzeichnis, gelesen über
`get_config()` (Singleton, gecacht, `reload()` vorhanden).
`config/schema.py` validiert nur bekannte Fehler — unbekannte Schlüssel sind
erlaubt. **Eine Änderung an der `config.yaml` wirkt erst nach einem
Neustart des Orb.**

Die wichtigsten Bereiche: `ai` (Anbieter, Fristen), `voice` (`input`
Erkennung, `output` Stimmen), `security`, `tools`, `browser`, `recherche`,
`nachrichten`, `studium`, `memory`, `launcher`.

---

## 11. Selbstverbesserung

`evolution/evolution_engine.py` — analysiert, schlägt Patches vor, testet
sie, bewertet und legt sie zur Freigabe vor. Feste Regeln: keine
automatische Änderung produktiver Dateien, keine automatische Installation,
Wiederherstellungspunkte in `data/rollback/`. Die Freigabe hängt an
`security.require("modify_own_code")` — kritisch, also nicht vorab
freigebbar.

Skills (`skills/`) sind eigene, deklarierte Fähigkeiten mit Manifest und
Berechtigungen; Plugins (`plugins/`) sind fremder Code im selben Prozess —
das Modul benennt ausdrücklich, dass Python das nicht wirklich einsperren
kann, und setzt stattdessen auf Freigabe, Sichtbarkeit und Protokoll.

---

## 12. Invarianten und Fallen (aus echter Fehlersuche)

1. **Ein abgewiesenes Werkzeug meldet sich nur im Log.** Falscher
   Berechtigungsname = Werkzeug fehlt lautlos. (`internet` statt `network`
   kostete drei Wochen Websuche.)
2. **`handled_locally=True` beendet den Zug.** Ein Schlüsselwort im Satz
   kann eine Handlungsanfrage in eine lokale Auskunft umlenken.
3. **Gesprochene Züge bekommen Werkzeuge nur über ein Schlüsselwort-Tor**
   (`braucht_werkzeuge`/`braucht_aktuelles`). Fehlt das Verb, kann das
   Modell nicht handeln, sagt aber nicht warum.
4. **Der Professor bleibt „busy"** und zieht Folgeäusserungen ins Fach,
   auch nach Themenwechsel.
5. **Whisper erfindet auf Stille** („Untertitel im Auftrag des ZDF") und
   blutet aus dem `initial_prompt` (Eigennamen tauchen als Erkennung auf).
6. **`max_output_tokens` bei Reasoning-Modellen** siehe Abschnitt 5.
7. **Testdoppel maskieren fehlende Felder.** `_pending_stop_window` wurde
   gelesen, nie angelegt — der Test setzte es auf seinem Doppel selbst.
   Prüfe bei „nie angelegt"-Verdacht `inspect.getsource(Klasse.__init__)`.
8. **Die Unit-Tests prüfen Teile, nicht den Zusammenbau.** 1826 grüne Tests
   und trotzdem keine Websuche, kein Browser, keine Karteikarten-Werkzeuge.
   Wer hier etwas ändert, prüft am Protokoll (`logs/system.log`), nicht nur
   an pytest.
9. **Nichts wird ohne Protokoll behauptet.** Jedes Modul loggt nach
   `logs/<modulname>.log` **und** nach `logs/system.log`.

---

## 13. Wo die vorhandene Dokumentation nicht mehr stimmt

`docs/ARCHITECTURE.md` (11.08.2026) beschreibt **fünf** Schichten; der Code
hat sieben. Sie nennt „Hermes" als Online-Provider — der ist längst durch
Claude Code / OpenAI / Ollama ersetzt. Die Grundregeln in ihr gelten
weiterhin. `docs/MODULES.md`, `docs/API.md`, `docs/EVENTS.md`,
`docs/SELBSTVERBESSERUNG.md`, `docs/SKILLS.md` sind ergänzend brauchbar.

Aktuelle Bestandsaufnahmen: `BESTANDSAUFNAHME.md` (Befunde),
`BEHOBEN-2026-08-31.md` (was davon behoben ist, mit Begründungen).
