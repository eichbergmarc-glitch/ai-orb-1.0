# NULLPROTOKOLL – Das Erwachen

Ein gesprochen gesteuertes Ego-Adventure für Windows. Der Prolog **„Acht Sekunden Licht"** ist auf etwa 30–45 Minuten ausgelegt und erzählt eine eigenständige Mystery-/Techno-Thriller-Geschichte über den Infrastrukturknoten ASTER-4 und die KI MIRA.

Du siehst die sieben Räume aus den Augen deiner Figur. Die Kamera geht mit, wenn du dich bewegst, und fährt an das Objekt heran, das du ansprichst. Die Figur selbst bekommst du nur in Zwischensequenzen zu sehen – dort dann formatfüllend.

Gesteuert wird mit der Stimme: Halte `T` gedrückt und sag, was du tun willst. Maus und Tastatur funktionieren unverändert weiter.

```text
„bewege dich zum Medizinschrank“     Figur läuft hin, mehr nicht
„öffne den Medizinschrank“           Figur läuft hin und öffnet
„rede mit Juna“                      Gespräch beginnen
„antwort zwei“                       Antwortmöglichkeit wählen
„sieh dich um“                       Raum wird beschrieben und vorgelesen
```

## Direkt starten

Auf diesem Rechner liegt die portable Godot-Testversion bereits im ignorierten Ordner `.tools/`. Ein Doppelklick genügt:

```text
STARTEN.bat
```

Das startet, falls eingerichtet, zuerst die lokale Spracherkennung und danach das Spiel. Alternativ `project.godot` in Godot 4.7 importieren und `F5` drücken.

Es werden keine Online-Dienste benötigt. Spracherkennung und Sprachausgabe laufen vollständig auf diesem Rechner; es wird zu keinem Zeitpunkt Audio verschickt. Spielstände liegen lokal unter `%APPDATA%\Godot\app_userdata\NULLPROTOKOLL – Das Erwachen`.

## Sprache einrichten

Ton und Raumatmosphäre sind bereits enthalten. Sprachausgabe und Spracherkennung werden getrennt eingerichtet, weil sie unterschiedlich viel Zeit kosten.

### Stimmen einrichten (XTTS-v2)

```powershell
.\SETUP_STIMMEN.ps1
```

Richtet Python, PyTorch und coqui-tts in `.tools\speech\xtts-venv` ein, erkennt eine NVIDIA-Grafikkarte und rendert am Ende acht Zeilen je Rolle als Hörprobe. Erst wenn dir die Stimme zusagt, läuft der vollständige Durchgang:

```powershell
.\STIMMEN_RENDERN.bat
```

Der Lauf ist wiederaufnehmbar. Ein Abbruch mit Strg+C kostet nichts – beim nächsten Start werden nur die fehlenden Zeilen ergänzt. Auf einer Grafikkarte dauert alles zusammen etwa eine halbe Stunde, auf der CPU mehrere Stunden.

**Eigene Stimme klonen.** XTTS bildet eine Stimme aus sechs bis fünfzehn Sekunden Aufnahme nach. Lege je Rolle eine WAV-Datei nach `tools\stimmproben\`; ohne eigene Aufnahme wird eine im Modell mitgelieferte Studiostimme verwendet. Einzelheiten in `tools\stimmproben\LIESMICH.md`.

XTTS-v2 steht unter der Coqui Public Model License und ist nur für nicht-kommerzielle Nutzung freigegeben.

### Spracherkennung einrichten (whisper.cpp)

```powershell
.\SETUP_SPRACHE.ps1 -SkipVoice
```

Holt whisper.cpp und das Erkennungsmodell (`small`, etwa 470 MB). `-Model base` ist kleiner und schneller, `-Model medium` genauer.

Beides ist optional: ohne Erkennung steuerst du mit Maus und Tastatur, ohne gerenderte Stimmen bleiben die Figuren still und der Text steht weiterhin im Protokoll.

## Wer spricht womit

| Rolle | Quelle |
|---|---|
| Gedanken und eigene Repliken | XTTS-v2, vorgerendert, weiblich oder männlich passend zur Figur |
| Dr. Juna Falk, Samir, Funkstimme | XTTS-v2, vorgerendert, je eigene Stimme |
| MIRA und Stationsansagen | Windows-Sprachausgabe, live |

Die Zuordnung steht in `tools\voice_config.json` und lässt sich pro Rolle ändern – Studiostimme, Tempo oder eine eigene Sprachprobe zum Klonen.

Eine Zeile wird über den SHA-256-Hash ihres Textes gefunden. Fehlt die Datei, schweigt die Figur: die Windows-Sprachausgabe als Ersatz einzuschieben klingt mitten in einer Szene schlechter als gar keine Stimme. Wer sie trotzdem will, schaltet in den Einstellungen „Ersatzstimme des Systems" ein. MIRA und die Stationsansagen sind davon ausgenommen – sie sprechen bewusst live und synthetisch, weil das zu ihnen gehört.

Als Alternative liegt `tools\render_voice.py` bei; das rendert dieselben Zeilen mit Piper. Piper ist kleiner und schneller, klingt aber deutlich synthetischer.

## Bedienung

| Eingabe | Funktion |
|---|---|
| `T` halten und sprechen | Befehl geben |
| `V` | freihändiges Zuhören ein- und ausschalten |
| `R` | letzte Zeile wiederholen |
| Linksklick auf Boden | zu diesem Punkt gehen |
| Linksklick auf Objekt | hingehen und untersuchen, nehmen, benutzen oder sprechen |
| `I` / `J` | Inventar / Journal |
| `H` | Objekte im Bild nummerieren |
| `Esc` | Overlay schließen oder Pause öffnen |

Sag „was kann ich sagen", um die vollständige Befehlsübersicht im Spiel zu öffnen.

### Was die Sprachsteuerung versteht

Der Parser trennt bewusst zwischen Hingehen und Handeln, erkennt Ordnungszahlen („antwort zwei", „wähle die erste"), deutsche Verschmelzungen („benutze die Folie **am** Terminal") und findet Objekte auch über verkürzte Namen – „Schrank" trifft den „Medizinschrank". Wird ein Befehl nicht verstanden, sagt das Spiel es und ändert nichts.

## Enthaltener Umfang

- sieben vollständig verknüpfte Schauplätze in Ego-Perspektive mit Kamerafahrt, Kopfbewegung, Atem, Vignette und Filmkorn
- Zwischensequenzen mit formatfüllenden Porträts an den Wendepunkten der Geschichte
- Sprachsteuerung mit lokalem Whisper, Maus und Tastatur weiterhin gleichwertig
- gesprochene Gedanken, Figurenstimmen und Systemstimme
- sieben nahtlose Raumatmosphären und elf Effektgeräusche, vollständig synthetisiert
- drei zentrale Figuren, 24 Gegenstände, sieben Kombinationen
- Charakterwahl weiblich/männlich, freier Name, drei Eigenschaftspunkte
- verzweigte Dialoge mit Bedingungen, Vertrauen und Rückbezügen
- pro Spielstand deterministische Zufallsereignisse über einen gespeicherten Seed
- vier Prologausgänge; drei immer erreichbar, einer verborgen
- Speichern, Laden, Autosave, Kontrollpunkt vor der Schlussentscheidung
- Textskalierung, hoher Kontrast, reduzierte Bewegung, Vollbild, Lautstärken je Bus

## Projektstruktur

```text
data/
  items.json             Gegenstandsdefinitionen
  recipes.json           Kombinationsrezepte
  dialogues.json         Dialoggraphen
  prologue.json          Orte, Hotspots, Ereignisse, Wege und Enden
  spatial_layouts.json   Laufbereiche, Hitboxen und Annäherungspunkte
  cutscenes.json         Zwischensequenzen
assets/
  backgrounds/           sieben Raumgrafiken
  characters/            Figurenvarianten und NPCs
  audio/ambience/        sieben Raumschleifen
  audio/sfx/             elf Effektgeräusche
  voice/                 vorgerenderte Sprachzeilen (entsteht beim Setup)
scripts/core/            Story, Zustand, Inventar, Speichern, Ton, Stimme, Sprachbefehle
scripts/ui/              Oberfläche, Ego-Bühne, Zwischensequenzen
tools/
  generate_audio.py      erzeugt Atmosphären und Effekte neu
  render_voice_xtts.py   rendert die Sprachzeilen mit XTTS-v2 vor
  render_voice.py        Alternative: dieselben Zeilen mit Piper
  voice_config.json      welche Stimme welche Rolle spricht
  stimmproben/           eigene Sprachproben zum Klonen
  parser_probe.py        spielt Formulierungen gegen die Befehlsgrammatik durch
tests/
  validate_story.mjs     Daten, Referenzen, Erreichbarkeit, Ton und Sequenzen
  test_runner.gd         kompletter Godot-Integrationspfad
  point_click_runner.gd  Bewegung, Kameraumrechnung, Intent-Abbruch, Assets
  voice_runner.gd        Sprachbefehle, Sprachschlüssel, Klangdateien
```

## Tests

Doppelklick auf `TESTEN.bat`, oder einzeln:

```powershell
node .\tests\validate_story.mjs
& '.\.tools\godot\bin\Godot_v4.7.2-stable_win64_console.exe' --headless --path . --scene res://tests/voice_runner.tscn
```

Die Tests spielen einen vollständigen Pfad bis zum verborgenen Ausgang, prüfen die vier Kernkombinationen, Speichern/Laden, den Entscheidungskontrollpunkt, die Bewegung samt Kameraumrechnung sowie 28 gesprochene Befehle gegen die echten Objektbezeichnungen.

Formulierungen lassen sich ohne Godot durchspielen:

```powershell
python .\tools\parser_probe.py .
```

## Windows-EXE exportieren

1. In Godot **Editor → Exportvorlagen verwalten** öffnen und passende Vorlagen installieren.
2. **Projekt → Exportieren**, Preset **Windows Desktop** wählen, exportieren.

Die Vorgabe schreibt nach `exports/NULLPROTOKOLL-Das-Erwachen.exe`. Die Spracherkennung liegt bewusst außerhalb der EXE, weil das Modell mehrere hundert Megabyte groß ist; `.tools\speech\` muss also mitgeliefert werden.

## Inhalt erweitern

Texte, Orte, Dialoge, Gegenstände, Rezepte und Zwischensequenzen liegen getrennt vom Programmcode in JSON. Neue Inhalte lassen sich ohne Änderung der Managersysteme ergänzen; ein erneuter Lauf von `SETUP_SPRACHE.ps1` rendert nur die neu hinzugekommenen Zeilen. Details in [docs/STORY_FORMAT.md](docs/STORY_FORMAT.md) und [docs/ARCHITEKTUR.md](docs/ARCHITEKTUR.md).

## Noch bewusst offen

Kapitel 1–3, Lokalisierung und signierte Windows-Installer gehören nicht zum angeforderten Prologumfang. Die Raumgrafiken sind weiterhin die ursprünglichen Totalen; die Ego-Perspektive entsteht durch den Kameraausschnitt. Für ganz nahe Objektaufnahmen wären eigene Detailbilder auf Augenhöhe der nächste Schritt.
