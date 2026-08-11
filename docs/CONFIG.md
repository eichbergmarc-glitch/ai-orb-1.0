# Konfiguration von AI-Orb

Alle Einstellungen stehen in `config.yaml` im Projekt-Root. Es gibt keine
hartkodierten Werte im Quellcode – insbesondere keine Modellnamen.

Geheimnisse gehören nicht in diese Datei, sondern in `.env` (Vorlage:
`.env.example`). In `config.yaml` steht lediglich der **Name** der
Umgebungsvariablen, aus der ein Schlüssel gelesen wird.

## app

`name`, `version` und `language` beschreiben die Anwendung.
`environment` schaltet zwischen `development` und `production`: In der
Entwicklungsumgebung sind die Entwicklerwerkzeuge im Kontextmenü verfügbar.

## logging

`level` steuert die Ausführlichkeit (`DEBUG` bis `CRITICAL`).
`max_file_size_mb` und `backup_count` steuern die Rotation, `console_output`
die zusätzliche Ausgabe auf der Konsole. Jedes Modul schreibt zusätzlich in
eine eigene Datei unter `logs/`.

## backend

`host` und `port` bestimmen, wo der lokale Server lauscht. Ist der Port
belegt, meldet das Startskript dies verständlich, statt stillschweigend zu
scheitern. `events_path` ist der Pfad des Ereigniskanals.

## window

Diese Werte bestimmen, dass der Orb kein gewöhnliches Fenster ist:
`frameless`, `transparent`, `always_on_top`, `skip_taskbar`, `has_shadow`,
`movable` und `resizable`. `width` und `height` legen die Fenstergröße fest,
`gpu_acceleration` schaltet die Hardwarebeschleunigung.

`start_position` steuert den Start: `remembered` nutzt die zuletzt
gespeicherte Position, sofern der zugehörige Monitor noch angeschlossen ist;
`center` beginnt immer neu.

## orb

`theme` wählt eines der sechs Farbthemen: `blue`, `purple`, `green`, `red`,
`white` oder `cyber`. `target_fps` legt die angestrebte Bildrate fest,
`adaptive_quality` schaltet die automatische Qualitätsanpassung.

`bloom_strength`, `bloom_radius` und `bloom_threshold` steuern das Leuchten.
`particles_enabled` und `particle_count` die Partikel-Aura.
`presence_motion` schaltet Atmung und Mikrobewegungen – ist es aus, steht
der Orb ruhiger, wirkt aber weniger lebendig.

## states

Je Zustand lassen sich `speed`, `particle_intensity` und `light_intensity`
überschreiben. Die Farben ergeben sich aus dem gewählten Theme.

## interaction

`double_click_action` legt fest, was ein Doppelklick auslöst:
`open_settings` öffnet `config.yaml`, `toggle_listen` schaltet den
Zuhörzustand um, `none` deaktiviert die Aktion. `hover_glow_radius` steuert,
ab welchem Abstand das Leuchten verstärkt wird.

## ai

`provider` steht auf `auto` für die automatische Wahl; alternativ lässt sich
fest `claude_code`, `claude`, `ollama` oder `hermes` eintragen.

Unter `primary` und `fallback` steht jeweils mindestens `engine`, `model`
und `timeout`. Welche weiteren Felder gelten, hängt vom Provider ab.

`auto_switch` schaltet den automatischen Wechsel, `switch_immediately`
entscheidet, ob sofort oder erst nach Ende der Unterhaltung zurückgewechselt
wird. `preserve_context` hält den Kontext beim Wechsel,
`health_check_interval` legt den Prüfabstand in Sekunden fest.

### claude_code – Claude über dein Abonnement (Voreinstellung)

Nutzt die lokal installierte Claude-Code-Befehlszeile und damit dein Pro-
oder Max-Abonnement. **Es wird kein API-Schlüssel benötigt.**

Voraussetzung ist, dass Claude Code installiert ist und du dich einmalig
angemeldet hast: im Terminal `claude` eingeben und der Anmeldung mit deinem
Abo folgen. Ob es geklappt hat, prüfst du mit `claude --version`.

`model` nimmt die stabilen Kurznamen `sonnet`, `opus` oder `haiku`. Diese
bleiben auch dann gültig, wenn neue Modellversionen erscheinen – deshalb
sind sie einem konkreten Modellnamen vorzuziehen.

`executable` kann leer bleiben; AI-Orb sucht die Befehlszeile selbst, auch
an den üblichen Installationsorten außerhalb des PATH. `extra_args` erlaubt
zusätzliche Argumente, wird aber normalerweise nicht gebraucht.

AI-Orb ruft die Befehlszeile in einem eigenen, leeren Arbeitsverzeichnis
unter `data/claude_workspace` auf. Dadurch durchsucht Claude Code nicht
versehentlich deine Projektdateien, sondern beantwortet ausschließlich die
gestellte Frage. Ein etwaiger `ANTHROPIC_API_KEY` wird für diesen Aufruf
bewusst aus der Umgebung entfernt, damit nicht versehentlich über die API
abgerechnet wird statt über dein Abo.

Ist die Nutzungsgrenze deines Abonnements erreicht, meldet der Provider das
im Klartext, und AI-Orb wechselt automatisch auf das lokale Modell.

### claude – Claude über die API (getrennte Abrechnung)

Spricht die Anthropic Messages API direkt an. Dafür ist ein **API-Schlüssel**
von `console.anthropic.com` nötig; ein Pro- oder Max-Abonnement genügt
**nicht**, da API-Nutzung getrennt abgerechnet wird.

`api_key_env` nennt die Umgebungsvariable mit dem Schlüssel (Voreinstellung
`ANTHROPIC_API_KEY`); der Schlüssel selbst gehört in `.env`.
`max_tokens` begrenzt die Antwortlänge.

`model` kann auf `auto` stehen – dann ermittelt AI-Orb beim ersten Aufruf
selbst das neueste passende Modell und bleibt dadurch auch nach
Modellwechseln funktionsfähig. `fallback_model` greift, falls die Abfrage
der Modellliste scheitert.

### ollama – lokal und offline

`base_url` ist die Adresse des lokalen Ollama-Servers, `model` das dort
installierte Modell. Es wird kein Schlüssel benötigt, und es verlässt kein
Datum deinen Rechner.

### hermes – OpenAI-kompatibler Dienst

Bleibt für OpenRouter und ähnliche Dienste erhalten. Felder: `base_url`,
`api_key_env`, `app_title`.

### Was passiert ohne alles?

Ist Claude nicht erreichbar und läuft auch Ollama nicht, funktionieren alle
lokalen Fähigkeiten weiterhin: Projekte, Aufgaben, Ziele, Gedächtnis,
Transparenzauskünfte und das Starten freigegebener Programme. Nur
inhaltliche Fragen brauchen ein Modell.

## conversation

`system_prompt` ist der Text, der jeder Modellanfrage vorangestellt wird.
`max_messages`, `max_context_tokens` und `keep_recent_messages` steuern, ab
wann der Verlauf verdichtet wird und wie viele Nachrichten unverändert
erhalten bleiben.

## memory

`min_content_length` legt fest, ab welcher Länge eine Aussage überhaupt
gespeichert werden kann. `forgetting_enabled`, `forget_half_life_days` und
`forget_threshold` steuern das Vergessen: Nach der Halbwertszeit hat ein
Eintrag die Hälfte seines Gewichts verloren; fällt es unter die Schwelle und
wurde der Eintrag nie abgerufen, wird er entfernt. Aufgaben unterliegen dem
Vergessen nicht.

## desktop

`applications` ist die Allowlist. AI-Orb startet ausschließlich Programme,
die hier eingetragen sind; freie Kommandozeilen aus Benutzereingaben werden
niemals ausgeführt. Jeder Eintrag hat `command`, optional `aliases` und
`args`.

`allow_process_termination` ist standardmäßig aus. Selbst wenn es
eingeschaltet wird, verlangt das Beenden eines Programms zusätzlich eine
ausdrückliche Bestätigung.

`file_search_roots` begrenzt die Dateisuche. Außerhalb dieser Verzeichnisse
sucht AI-Orb nicht.

## smart_desktop

Dieser Abschnitt ist in der Vorlage noch nicht enthalten und kann bei Bedarf
ergänzt werden. Unterstützt werden `enabled`, `avoid_mouse`,
`avoid_active_window`, `learn_behavior`, `movement_speed` (`slow`, `medium`,
`fast`), `heatmap_resolution`, `monitor_support` und `fullscreen_sleep`.
Ohne diesen Abschnitt gelten die Voreinstellungen aus
`desktop/electron/desktop_manager.ts`.

## workspace

`track_browser_tabs` ist standardmäßig aus: Browser-Tabs werden nur mit
ausdrücklicher Zustimmung erfasst. `restore_on_open` steuert, ob beim Öffnen
eines Projekts nach der Wiederherstellung des Arbeitszustands gefragt wird.

## cognitive und reasoning

`working_memory_ttl` und `working_memory_max_items` begrenzen das
Kurzzeitgedächtnis. `plan_from_complexity` legt fest, ab welcher Komplexität
ein vollständiger Plan erstellt wird – einfache Aufgaben werden bewusst
nicht verkompliziert. `communicate_uncertainty` und `confirm_risky_actions`
steuern, ob Unsicherheiten mitgeteilt und riskante Aktionen bestätigt werden
müssen.

## reflection

`store_insights` steuert, ob sachliche Erkenntnisse aus der Nachbetrachtung
langfristig gespeichert werden. Personenbezogene Schlussfolgerungen werden
in keinem Fall gespeichert. `max_history` begrenzt den Umfang.

## agents

`lazy_start` startet Agenten nur bei Bedarf, `max_parallel` begrenzt die
gleichzeitige Arbeit, `timeout` setzt das Zeitlimit je Agent.

## skills

`directory` legt fest, wo installierte Skills liegen.
`require_confirmation` ist standardmäßig an: Ohne Bestätigung wird nichts
installiert. `restricted_permissions` listet Rechte, die als besonders
weitreichend gelten und beim Benutzer ausdrücklich hervorgehoben werden.

## evolution

`workspace_directory` ist der Ort der isolierten Arbeitskopien.
`require_user_approval` ist standardmäßig an. `auto_install_dependencies`
und `allow_external_code_transfer` sind standardmäßig aus – AI-Orb
installiert nichts eigenmächtig und überträgt keinen Quellcode nach außen.

`max_function_lines`, `max_module_lines` und `max_complexity` sind die
Schwellwerte der Codeanalyse.

Für den optionalen fortgeschrittenen Modus lässt sich zusätzlich
`auto_apply_rules` ergänzen:

```yaml
evolution:
  require_user_approval: false
  auto_apply_rules:
    enabled: true
    max_risk: "gering"
    max_files: 1
```

Auch dann werden ausschließlich Änderungen übernommen, die alle Tests, das
Review und den Leistungsvergleich bestanden haben.

## Änderungen übernehmen

Die meisten Werte wirken beim nächsten Start. Der `ConfigLoader` bietet
`reload()`, sodass künftige Ausbaustufen Einstellungen auch zur Laufzeit
übernehmen können, ohne dass sich am Zugriffsweg etwas ändert.
