# Anfrageverarbeitung: Befunde, Änderungen, offene Risiken

Stand 01.09.2026. Grundlage: der gelesene Quelltext, `config.yaml`, die
Testsuite und `logs/system.log` — nicht `docs/ARCHITECTURE.md`, die in den
Details veraltet ist (fünf statt sieben Schichten, „Hermes" als Provider).

## Ausgangsmessung

`pytest tests/backend` vor der Arbeit: **1821 bestanden, 6 rot.** Alle sechs
waren schon vorher rot und liegen an der Linux-Prüfumgebung, nicht am Code:

| Test | Grund |
|---|---|
| 5× `test_voice_and_tts` (chatterbox, pocket_tts) | `ModuleNotFoundError: torch` — auf Windows installiert |
| `test_kalender::…kalenderzone_wird_dynamisch_uebernommen` | Python 3.10 versteht `fromisoformat` mit `Z` nicht; ab 3.11 gelöst |

## Befundplan

**P0 — stille Fehlentscheidungen.** Drei Tore beendeten Anfragen, ohne dass
irgendwo stand warum: der Router (`handled_locally` als Tatsache statt als
Einschätzung), das Schlüsselwort-Tor für Werkzeuge, der Professor-Modus ohne
definiertes Ende. Dazu: abgewiesene Werkzeuge nur als Log-Warnung, und
ungültige Werkzeugaufrufe wurden stillschweigend zurechtgebogen.

**P1 — Beobachtbarkeit und Sicherheit.** Kein Zug liess sich im Protokoll
von Anfang bis Ende verfolgen. `security.mode: offen` stand als beiläufige
Warnung im Log.

**P2 — Modularisierung.** `runtime.py` (1.400 Zeilen) und
`voice_pipeline.py` (3.800 Zeilen) aufteilen. **Bewusst nicht durchgeführt**
— siehe „Offene Risiken".

## Was geändert wurde

### Tor 4 — der Router entscheidet nicht mehr endgültig

`RouteResult` trägt jetzt `status`, `begruendung`, `konfidenz` und
`rueckfall_erlaubt`; `handled_locally` bleibt als schmale Fassade, damit
bestehende Aufrufer unverändert laufen. Neu ist `ist_endgueltig`, und genau
das fragt der Orchestrator jetzt.

`TaskRouter._bewerten` lässt eine lokale Zuordnung zurückfallen, wenn sie
sich selbst unsicher ist **und** ihr Modul nur Auskunft gibt. Handelnde
Module (Programm starten, Terminal, Browser) setzen `rueckfall_erlaubt`
nicht — eine ausgeführte Aktion wiederholt man nicht.

Die Auskunfts-Handler in `cognitive_core` (Aufgaben, Projekte, Transparenz)
melden ihre Konfidenz über `_auskunft_konfidenz`: Verlangt der Satz eine
Handlung, ist sie 0.15 und liegt damit unter der Rückfallschwelle.

### Tor 5 — der Professor hat jetzt ein Ende

`ProfessorSession` führt den Fachzustand ausdrücklich: `_letzte_fachaeusserung`,
`_verlassen(grund)`, `zustand()`. Drei Wege hinaus:

1. **Zeitablauf** — `studium.professor_zeitablauf_sekunden` (900).
2. **Themenwechsel** — ein fachfremder Handlungsauftrag.
3. **Abschluss** — der laufende Vorgang endet.

Der Themenwechsel wird nicht über eine neue Schlüsselwortliste erkannt,
sondern über dieselbe Fähigkeitsentscheidung wie Tor 4 und Tor 6.

### Tor 6 — Fähigkeitsentscheidung statt Schlüsselwort-Tor

Neu: `backend/orchestrator/faehigkeiten.py`. Statt „ein Verb aus einer Liste
muss vorkommen" zahlen mehrere Signale auf eine Konfidenz ein
(Handlungsverb, Auftragswendung, eigenes Umfeld, Aktualität, Browserbefehl,
Selbstdiagnose, ein wirklich angemeldeter Werkzeugname; Konversationswendungen
zahlen negativ ein). Die Voreinstellung ist umgedreht: **im Zweifel mit
Werkzeugen.** Vorlesungsabschnitte behalten ihr bisheriges Verhalten.

Dieselbe Entscheidung beantwortet alle drei Tore, damit derselbe Satz nicht
an drei Stellen verschieden beurteilt wird.

### Werkzeuge: Abweisungen sind Startfehler

`ToolRegistry` sammelt Abweisungen mit Grund (`abgewiesene()`). `runtime`
trägt sie in `startfehler` ein und meldet sie als ERROR;
`health_check.check_werkzeuge` **registriert jetzt wirklich**, statt nur die
gebaute Liste anzusehen — ein falscher Berechtigungsname macht die
Startprüfung damit nachweisbar rot.

### Werkzeugaufrufe: Schema statt Zurechtbiegen

`pruefe_aufruf` validiert die Hülle: `werkzeug` muss eine nicht-leere
Zeichenkette sein, `argumente` fehlen oder ein Objekt sein (eine
JSON-Zeichenkette wird einmal nachgelesen). Ungültiges wird **nicht
ausgeführt**; das Modell bekommt den Grund wörtlich zurück und
`tools.reparatur_versuche` Versuche, danach eine ehrliche Absage.
`parse_tool_calls` bleibt als Fassade.

### Korrelations-Kennung

Nicht neu erfunden: `TurnTrace.turn_id` gab es schon, wurde aber nirgends
mitgeschrieben. Sie steht jetzt an Tor 4, Tor 5, Tor 6 und an jedem
Werkzeugeinsatz. Getippte Anfragen bekommen im Orchestrator eine eigene.

### Sicherheit

`security.mode: offen` meldet sich beim Start als achtzeiliger ERROR-Block
und steht in `SecurityEngine.status()`. `config/schema.py` kennt jetzt die
erlaubten Werte — ein Tippfehler hält den Start an, statt stillschweigend
ausgelegt zu werden. Die Einstellung selbst wurde **nicht** geändert.

## Neue Konfigurationswerte

| Schlüssel | Vorgabe | Wirkung |
|---|---|---|
| `routing.werkzeug_schwelle` | 0.45 | ab welcher Konfidenz ein Satz als Handlungsauftrag gilt |
| `routing.werkzeuge_im_zweifel` | true | umgedrehte Voreinstellung; `false` stellt das alte Verhalten her |
| `routing.min_konfidenz` | 0.4 | darunter beendet eine lokale Auskunft den Zug nicht |
| `tools.reparatur_versuche` | 1 | Versuche für einen ungültigen Werkzeugaufruf |
| `studium.professor_zeitablauf_sekunden` | 900 | Zeitablauf des Fachmodus; 0 schaltet ihn ab |
| `voice.spoken_max_tokens_mit_werkzeugen` | 320 | Antwortgrenze, wenn ein Werkzeugaufruf hineinpassen muss |

## Verhaltensänderungen

* Gesprochene Züge ohne erkennbares Handlungsverb bekommen jetzt Werkzeuge.
  Das kostet Kontext und kann Antworten leicht verlangsamen; ohne es waren
  Auftragsfortsetzungen nicht ausführbar.
* Eine gesprochene Antwort **mit** Werkzeugen war bisher unbegrenzt lang.
  Sie ist jetzt auf 320 Tokens begrenzt — sonst hätte die umgedrehte
  Voreinstellung dazu geführt, dass der Orb wieder Vorträge hält.
* Aufgaben-, Projekt- und Transparenzauskünfte können an das Modell
  zurückfallen. Bei ausdrücklichen Listenfragen ändert sich nichts.
* Ein ungültiger Werkzeugaufruf wird nicht mehr mit leeren Argumenten
  ausgeführt.

## Offene Risiken und notwendige manuelle Prüfungen

1. **P2 (Aufteilung von `runtime.py` und `voice_pipeline.py`) ist nicht
   durchgeführt.** Der Auftrag selbst sagt „erst nach Absicherung durch
   Tests". Die Absicherung ist mit dieser Arbeit begonnen, aber
   `voice_pipeline.py` hat weiterhin ungelesene Bereiche (Diktat,
   Vorlesung, Tagebuch). Eine Aufteilung jetzt wäre eine Umbauarbeit ohne
   Netz.
2. **Am laufenden Orb nachgestellt ist nichts.** Alle Belege stammen aus
   Quelltext, Tests und Protokoll. Die Tore sind mit einer echten
   Korrelations-Kennung durchgespielt (siehe unten), aber nicht im Betrieb.
3. **Die Schwellen sind gesetzt, nicht gemessen.** 0.45 und 0.4 sind
   plausible Anfangswerte. Ob sie stimmen, zeigt erst das Protokoll: Die
   Begründung steht in jeder Tor-Zeile und lässt sich auswerten.
4. **`security.mode: offen` gilt weiterhin.** Damit greift die Sperre für
   kritische Vorabfreigaben nicht — `require()` kehrt vorher zurück. Das
   ist die ausdrückliche Entscheidung des Benutzers und wurde nicht
   angerührt; sie sollte vor dem nächsten unbeaufsichtigten Nachtlauf
   überprüft werden.
5. **Manuell zu prüfen nach einem Neustart:** ein gesprochener
   Wohnungssuchauftrag (Tor 4 und 6), eine Fachfrage gefolgt von einem
   fachfremden Auftrag (Tor 5), und ein Blick in `logs/system.log`, ob
   dieselbe Kennung durch alle drei Zeilen läuft.

## Belegte Tor-Beispiele (dieselbe Kennung, ein Zug)

Satz: *„Ich wiederhole die Aufgabe, suche nach einer Wohnung maximal 1100 Fr.
in der Region Solothurn und zeige mir die Ergebnisse im Browser an."* — genau
der Satz, der am 31.08.2026 als Aufgabenstatistik endete.

```
[b572cacacf] Tor 4 Router: Intent 'aufgabe' an Modul 'ai_provider'
    (lokal=False, status=unsicher, Konfidenz 0.15, Rueckfall=True) -
    Konfidenz 0.15 unter 0.40 - die lokale Auskunft aus 'tasks' wird nicht
    als Antwort genommen, der Hauptweg uebernimmt
[b572cacacf] Tor 5 Professor verlaesst den Fachmodus
    (Fach: geschichte, Modus: quellenkritik) - fachfremder Handlungsauftrag.
[b572cacacf] Tor 6 Modellkontext: 4 Nachrichten, 21665 Zeichen,
    Wunschprovider=standard, Werkzeuge=True (deutlicher Auftrag:
    handlungsverb, auftragswendung, aktualitaet, Konfidenz 1.00)
```

Zum Vergleich dieselben drei Stellen am 31.08.2026, vor der Änderung:

```
12:45:17  Intent 'aufgabe' an Modul 'tasks' geleitet (lokal=True).
12:38:59  Der Professor übernimmt (Fach: geschichte, Modus: erklaeren).
12:39:05  Modellkontext: 4 Nachrichten, 21665 Zeichen, Werkzeuge=False.
```
