# Storydaten-Format

Alle Inhaltsdateien liegen unter `data/` und verwenden UTF-8-JSON.

## Orte und Hotspots

Ein Ort in `prologue.json` besitzt mindestens:

```json
{
  "id": "beispielort",
  "title": "Angezeigter Titel",
  "subtitle": "Bereich · Ebene",
  "palette": "archive",
  "description": "Eintrittstext",
  "hotspots": [],
  "exits": []
}
```

Ein Hotspot kann Text, einmalige Folgen, Entscheidungen, einen Dialog oder gegenstandsspezifische Anwendungen enthalten:

```json
{
  "id": "locked_panel",
  "label": "Verriegeltes Panel",
  "verb": "Öffnen",
  "text": "Der Standardtext.",
  "once": true,
  "repeat_text": "Der Text nach Abschluss.",
  "conditions": {"flags_all": ["power_on"]},
  "effects": {"add_items": ["new_item"]},
  "item_uses": {
    "tool_id": {
      "text": "Erfolgreiche Anwendung.",
      "effects": {"add_flags": ["panel_open"]}
    }
  }
}
```

## Räumliche Point-and-Click-Daten

`spatial_layouts.json` hält die Darstellung bewusst von der Storylogik getrennt. Jeder Story-Ort besitzt dort ein Hintergrundbild, ein begehbares Polygon sowie dieselben Hotspot- und Exit-IDs wie `prologue.json`:

```json
{
  "background": "res://assets/backgrounds/beispielort.png",
  "walk": [[100, 820], [300, 650], [1600, 650], [1820, 820]],
  "baseline": [[100, 840], [1820, 840]],
  "entries": {"start": [420, 780], "from_nachbarort": [1500, 760]},
  "spots": {
    "locked_panel": {"r": [620, 240, 280, 350], "a": [760, 730], "cursor": "use"}
  },
  "exits": {
    "to_nachbarort": {"r": [1600, 180, 300, 600], "a": [1530, 770], "cursor": "exit"}
  }
}
```

`r` ist die Hitbox `[x, y, breite, höhe]`, `a` der begehbare Annäherungspunkt an den sichtbaren Gegenstand. Zustandsvarianten desselben Objekts verwenden dieselbe Hitbox. Optionale `actors`- und `pickup_visuals`-Layer können anhand von Storyflags oder abgeschlossenen Interaktionen ein- und ausgeblendet werden.

## Bedingungen

Unterstützte Felder:

- `flags_all`, `flags_none`
- `items_all`, `items_none`
- `puzzles_all`
- `stats_min`
- `relations_min`
- `world_min`, `world_max`, `world_equals`
- `interactions_all`

Alle Felder innerhalb eines Bedingungsobjekts sind UND-verknüpft. Alternative Wege werden als getrennte Hotspots oder Optionen modelliert.

## Folgen

Unterstützte Felder:

- `add_flags`, `remove_flags`
- `add_items`, `remove_items`
- `solve_puzzles`
- `world_delta`, `set_world`
- `relation_delta`
- `add_secrets`
- `add_journal`
- `time_cost` in Stunden
- `ending`

Notwendige Gegenstände sollten nie durch Zufallsereignisse entfernt werden. Jede gesperrte Pflichtaktion braucht einen verständlichen `blocked_text`.

## Dialoge

`dialogues.json` enthält benannte Graphen:

```json
{
  "dialog_id": {
    "start": "opening",
    "nodes": {
      "opening": {
        "speaker": "Figur",
        "text": "Dialogtext",
        "options": [
          {
            "id": "answer",
            "label": "Sichtbare Antwort",
            "player_text": "Protokollierter Spielertext",
            "next": "response",
            "conditions": {},
            "effects": {}
          }
        ]
      }
    }
  }
}
```

Eine Option benötigt entweder `next` oder `end: true`.

## Gegenstände und Rezepte

`items.json` ordnet stabilen IDs Name, Kategorie, Beschreibung und Hinweis zu. Ein Rezept in `recipes.json` besitzt genau zwei Eingaben und ein Ergebnis. Mehrteilige Konstruktionen werden als aufeinanderfolgende Zweierrezepte modelliert, damit der Kombinationsdialog eindeutig bleibt.

Nach jeder Änderung sollte `node tests/validate_story.mjs` laufen. Der Test prüft Referenzen, Mindestumfang, Ortsgraph, Dialogziele, Gegenstände, Enden und einen vollständigen Lösungspfad.
