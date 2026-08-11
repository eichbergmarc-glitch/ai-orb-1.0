# Ereignisse des Event Bus

Alle Backend-Module kommunizieren über den zentralen Event Bus. Jedes
Ereignis wird zusätzlich automatisch an die Oberfläche weitergereicht, die
daraus den sichtbaren Zustand des Orb ableitet.

Die Namen folgen dem Muster `<bereich>.<ereignis>`. Die Konstanten stehen in
`backend/events/event_types.py`; neue Ereignisse werden dort ergänzt, statt
Namen als Zeichenketten zu verstreuen.

## System

`system.ready` wird beim Start veröffentlicht und enthält Version, aktiven
Provider und die Namen aller registrierten Agenten. `system.shutdown` meldet
das geordnete Ende, `system.error` einen Systemfehler.

## Sprache und Audio

`audio.recorded` meldet eine abgeschlossene Aufnahme,
`speech.transcribed` das Ergebnis der Spracherkennung. `tts.started` und
`tts.finished` umschließen die Sprachausgabe. Diese vier Ereignisse sind
vorbereitet; die zugehörigen Fähigkeiten werden über das Skill-System
nachgerüstet.

## KI und Orchestrierung

`ai.intent.classified` enthält das Ergebnis der Intent-Klassifikation samt
Sicherheit und den ausschlaggebenden Begriffen. `ai.request` und
`ai.response` umschließen eine Modellanfrage. `ai.provider.changed` meldet
jeden Providerwechsel mit Grund – etwa `ausfall`, `primär_wieder_verfügbar`
oder `unterhaltung_beendet`.

## Cognitive Core

`cognitive.response` enthält die vollständige Antwort des Cognitive Core.
`cognitive.clarification` wird veröffentlicht, wenn der Orb eine Rückfrage
stellt, weil die Anfrage mehrdeutig war.
`cognitive.confirmation_required` meldet, dass eine Aktion als risikoreich
eingestuft wurde und erst nach Bestätigung ausgeführt wird.

## Fenster und Orb

`window.position.changed` meldet eine Positionsänderung des Fensters.
`orb.state.changed` meldet den Zustandswechsel des Orb,
`orb.activated` einen Linksklick, `orb.context_menu.requested` einen
Rechtsklick, `orb.action.triggered` eine sonstige Interaktion.

Zusätzlich sendet der Electron-Hauptprozess an die Oberfläche:
`orb.position.chosen` mit der von der Smart Desktop Engine gewählten
Position und deren Bewertung, `orb.position.committed` nach einer
Ziehbewegung, `orb.position.saved` nach dem manuellen Merken einer Position,
`orb.state.request` als Zustandsanforderung (etwa Schlafen bei Vollbild),
sowie `monitor.added` und `monitor.removed` bei Änderungen der
Monitorkonfiguration.

## Verhalten und Erweiterungen

`behavior.updated` meldet neue Erkenntnisse des Lernsystems.
`plugin.loaded` und `plugin.unloaded` melden Skills, die geladen oder
entladen wurden. Skills veröffentlichen eigene Ereignisse unter
`skill.<name>.<ereignis>`.

## Verbindung

`client.connected` und `client.disconnected` melden, wenn sich die
Oberfläche verbindet oder trennt.

## Zuordnung zu Orb-Zuständen

Die Oberfläche bildet Ereignisse auf sichtbare Zustände ab. `system.ready`
und `tts.finished` führen zu **idle**. `audio.recorded`,
`speech.transcribed`, `ai.request` und `ai.intent.classified` führen zu
**thinking**. `ai.response`, `cognitive.response` und `tts.started` führen zu
**speaking**, wobei der Orb nach etwa zweieinhalb Sekunden von selbst in den
Ruhezustand zurückkehrt. `cognitive.clarification` und
`cognitive.confirmation_required` führen zu **listening**, `system.error` zu
**error**. Ein Verbindungsabbruch zum Backend führt ebenfalls zu **error**,
eine wiederhergestellte Verbindung zurück zu **idle**.

## Eigene Ereignisse veröffentlichen

Innerhalb des Backends:

```python
from backend.events.event_bus import get_event_bus

await get_event_bus().publish("mein.ereignis", {"wert": 42})
```

Aus einem anderen Thread heraus über die Runtime:

```python
runtime.publish("mein.ereignis", {"wert": 42})
```

Abonnieren:

```python
bus.subscribe("mein.ereignis", handler)     # ein bestimmtes Ereignis
bus.subscribe(WILDCARD, handler)            # alle Ereignisse
```

Der Handler erhält ein `Event`-Objekt mit `name`, `payload` und
`timestamp` und darf synchron oder asynchron sein. Ein Fehler in einem
Handler wird protokolliert und bricht die Verteilung an die übrigen Handler
nicht ab.
