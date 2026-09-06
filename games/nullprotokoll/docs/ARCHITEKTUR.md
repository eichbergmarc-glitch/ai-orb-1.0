# Technisches Konzept

## Ziel

Der Vertical Slice ist ein Godot-4-Projekt in GDScript. Darstellung und Spiellogik sind bewusst getrennt: Die Oberfläche kennt keine konkreten Rätsellösungen; sie zeigt nur die von den Managersystemen gelieferten Orte, Objekte und Optionen an.

## Laufzeitfluss

```text
JSON-Storydaten
      ↓
StoryManager / DialogueManager
      ↓
EventCondition → GameManager → ConsequenceSystem
      ↓                ↓
Inventory/Puzzle   World-/Character-State
      ↓                ↓
 PointClickStage / UI + lokaler Spielstand
```

`GameManager` ist das einzige Autoload. Es koordiniert kleine, getrennt testbare Komponenten:

- `StoryManager`: lädt Orte, Hotspots, Wege und Endtexte.
- `DialogueManager`: führt verzweigte Dialogknoten aus.
- `InventoryManager`: verwaltet Gegenstände und Rezepte.
- `PuzzleManager`: speichert gelöste Rätsel-IDs.
- `EventCondition`: wertet Flags, Gegenstände, Eigenschaften, Beziehungen und Weltwerte aus.
- `ConsequenceSystem`: wendet Folgen an, ohne UI-Wissen zu benötigen.
- `SeededRandomEvent`: wählt gewichtete Ereignisse reproduzierbar aus.
- `NPSceneManager`: verwaltet aktuellen und besuchte Orte.
- `NPSaveManager`: schreibt vollständige JSON-Spielstände und den Schlusskontrollpunkt.
- `NPAudioManager`: stabile Schnittstelle für spätere Audiodateien.
- `CharacterState` und `WorldState`: erzeugen neue Zustände mit sicheren Standardwerten.

## Dynamische Handlung

Der Spielverlauf wird nicht über einen starren Szenenbaum fest verdrahtet. Jede Option kann Flags, Beziehungen, Weltwerte, Gegenstände, Geheimnisse, Journal und Zeit verändern. Spätere Hotspots und Antworten werten diese Daten aus.

Beispiele:

- Der zuerst versorgte Bereich entscheidet über Audit-Integrität oder Junas Vertrauen.
- Ein gesicherter Funkkanal schützt Samirs Informationen und ist Voraussetzung für das geheime Ende.
- Ein Selbsttest enthüllt PC-MESH, verbraucht aber das einzige Reagenz für Junas Quarantänetest.
- Das Spiegelmodul ist nur mit ausreichendem Instinkt auffindbar.
- Der gespeicherte RNG-Zustand sorgt dafür, dass Laden kein anderes Zufallsereignis erzeugt.

Kein Zufallsereignis entfernt notwendige Gegenstände oder sperrt einen Pflichtweg.

## Darstellung

`PointClickStage` verbindet hochauflösende Graphic-Novel-Hintergründe mit einer sichtbaren Spielfigur und den räumlichen Daten aus `data/spatial_layouts.json`. Die Referenzauflösung der Welt beträgt 1920×1080; die Bühne erhält dadurch unabhängig vom Fensterformat stabile Lauf-, Hitbox- und Annäherungskoordinaten.

Ein Bodenklick setzt ein Laufziel innerhalb des Raum-Polygons. Ein Objekt- oder Ausgangsklick speichert zunächst nur einen Intent; erst am zugehörigen Annäherungspunkt emittiert die Bühne das Storysignal an `GameManager`. Ein neuer Bodenklick verwirft den Intent. Figurenspiegelung, leichter Lauf-Bob, Bodenschatten und Y-abhängige Skalierung erzeugen die 2.5D-Wirkung. NPC- und Gegenstandslayer können über Flags ein- und ausgeblendet werden.

`SceneBackdrop` bleibt als leichte prozedurale Darstellung für Abschlussansichten erhalten. Das zentrale Theme definiert Farben, Abstände, Fokusrahmen und große Klickflächen; der Erzähltext bleibt in einer eigenen, ständig lesbaren Spalte.

## Speicherformat

Gespeichert werden:

- Charakterprofil und Eigenschaften
- Weltwerte, Restzeit und aktueller Ort
- Flags, Beziehungen, Geheimnisse und Journal
- Inventar und gelöste Rätsel
- besuchte Orte und abgeschlossene Interaktionen
- Storyprotokoll
- Zufalls-Seed und aktueller RNG-Zustand
- erreichter Ausgang

Ein gesonderter Kontrollpunkt entsteht beim Betreten des Relaiskerns. Dadurch können alle Schlussentscheidungen ohne erneutes Durchspielen verglichen werden.

## Ego-Perspektive

Die Bühne (`scripts/ui/point_click_stage.gd`) rechnet weiterhin in stabilen
1920x1080-Designkoordinaten. Neu ist nur die Abbildung auf den Bildschirm: eine
virtuelle Kamera hält einen Ausschnitt (`_view_center`, `_view_extent`) und
füllt damit das Panel randlos. Die Laufsimulation ist unverändert – die Figur
bewegt sich nach wie vor zu einem Annäherungspunkt, und eine Aktion feuert erst
bei Ankunft. Nur gezeichnet wird sie nicht mehr.

- Ruhezustand: Blickhöhe bei 45,5 % der Bildhöhe, Ausschnitt 86 % der Fläche,
  seitlich der Figur folgend.
- Annäherung: Ausschnitt und Bildmitte wandern kontinuierlich auf das
  angesprochene Objekt zu, sodass Ankunft und Heranfahrt gleichzeitig enden.
  Der Zielausschnitt ergibt sich aus der Hitboxgröße, kleine Objekte werden
  also stärker herangeholt.
- Bewegung: Kopfnicken und Seitwärtsschwung beim Gehen, Atembewegung im Stehen,
  leichter Blickversatz zur Mausposition. Alles entfällt bei „Bewegung
  reduzieren".
- Ein Shader legt Vignette, Filmkorn und einen Atempuls darüber. Das ersetzt die
  fehlende Tiefenschärfe und kaschiert, dass die Raumgrafiken beim Heranfahren
  über ihre native Auflösung hinaus vergrößert werden.
- `design_to_local` und `local_to_design` sind die öffentliche Umkehrung der
  Kameraabbildung. Tests und Werkzeuge klicken darüber Weltpunkte an, ohne die
  Kameramathematik zu kennen.

Objektrahmen sind in der Ego-Sicht Eckwinkel statt Rechtecke, damit das Bild
nicht wie ein Diagramm wirkt. Die Spielfigur wird nur noch von
`scripts/ui/cutscene_layer.gd` gezeigt – dort formatfüllend auf 94 % der
Bildhöhe, ausgelöst durch Spielstart, Story-Flags und Enden aus
`data/cutscenes.json`.

## Ton

`NPAudioManager` ist jetzt ein Node im Szenenbaum und legt beim Start die Busse
`Musik`, `Effekte` und `Stimme` an, falls sie fehlen. Raumatmosphären werden
über zwei Spieler mit 1,8 Sekunden Überblendung gewechselt. Fehlt eine Datei,
passiert nichts – das Spiel bleibt lauffähig.

Alle Klänge sind synthetisiert (`tools/generate_audio.py`, numpy + ffmpeg). Die
Schleifen sind nahtlos: das Ende wird auf den Anfang geblendet und anschließend
eine minimale Rampe abgezogen, sodass erster und letzter Wert exakt
übereinstimmen. Alle sieben Räume liegen auf derselben Lautheit, damit
Raumwechsel nicht springen.

## Stimmen

`NPVoiceManager` mischt zwei Quellen. Vorgerenderte Piper-Dateien tragen
Gedanken, eigene Repliken und die menschlichen Figuren; die Sprachausgabe des
Betriebssystems spricht MIRA und die Stationsansagen live. Eine Zeile wird über
`voice_key()` gefunden: die ersten 16 Hexstellen des SHA-256-Hashes ihres
normalisierten Textes. Dieselbe Normalisierung steht in `tools/render_voice.py`;
weichen beide voneinander ab, findet das Spiel seine Dateien nicht mehr, und
`tests/voice_runner.gd` schlägt an.

Zeilen mit Platzhaltern (`{name}`, `{hours}`) werden bewusst nicht vorgerendert,
weil ihr Text erst zur Laufzeit entsteht. Sie laufen über die Live-Ausgabe.

## Sprachsteuerung

`NPSpeechInput` nimmt über einen eigenen Bus mit `AudioEffectCapture` auf, der
auf −80 dB steht: der Effekt greift vor der Ausgangslautstärke ab, es wird also
aufgenommen, ohne dass etwas zurückschallt. Die Aufnahme wird auf 16 kHz
gerechnet, als WAV verpackt und an einen lokalen whisper.cpp-Server auf
127.0.0.1:8099 geschickt. Es verlässt kein Audio den Rechner.

`NPCommandParser` ist reine Logik ohne Godot-Abhängigkeit und daher vollständig
testbar. Er normalisiert den Satz, faltet Umlaute nach ASCII, bestimmt die
Absicht über das früheste passende Verb und gleicht den Rest gegen die gerade
erreichbaren Objekte ab. Die Ähnlichkeit kombiniert Token-Enthaltensein (72 %)
mit Editierabstand (28 %); deutsche Komposita werden dadurch auch verkürzt
getroffen. Bewegen und Handeln sind getrennte Absichten, weil „geh zum Tisch"
und „öffne die Schublade" unterschiedliche Dinge sind.

`tools/parser_probe.py` bildet dieselbe Logik in Python nach, damit sich
Formulierungen ohne laufende Engine durchspielen lassen. Bei Abweichungen gilt
die GDScript-Fassung.
