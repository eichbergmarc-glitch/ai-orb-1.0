# Projektprüfung und nächste Ausbauschritte

Stand: 13. August 2026

## Behobene Schwachstellen

- Windows konnte Python-Hilfsprogramme und die meist als `claude.cmd`
  installierte Claude-Code-Befehlszeile nicht zuverlässig über asyncio
  starten. Der Provider baut nun je Dateityp einen passenden, argumentweise
  übergebenen Prozessaufruf.
- Ein nicht lesbarer Ollama-Installationspfad ließ Status und Vorbereitung
  mit `PermissionError` abstürzen. Solche Kandidaten werden nun übersprungen.
- Sprachtests verwendeten fest `/tmp` und waren dadurch unter Windows nicht
  portabel. Sie nutzen nun die temporären Verzeichnisse von pytest.
- Mehrere alte Animationstests verlangten gleichzeitig verschiedene, längst
  abgelöste Renderer. Sie sichern jetzt, dass alte Renderer nicht mit dem
  aktiven Energy-Orb vermischt werden.
- Die Browser-Tests bilden den vorgesehenen Ausweichweg konsistent ab: Ohne
  Playwright kann eine Adresse im Standardbrowser geöffnet werden, während
  Klicken, Tippen und Lesen ehrlich als nicht verfügbar gemeldet werden.
- Die Bildschirmaufnahme verwendet die aktuelle `mss.MSS`-Schnittstelle.
- README und Konfigurationskommentare beschreiben nun den aktuellen
  Energy-Orb statt der früheren Zwei-Punkte-Animation.

## Weitere Verbesserungen

Die folgenden sechs Grundlagen wurden am 13. August 2026 umgesetzt:

- zentraler Lebenszyklusmanager für Runtime-Hintergrundaufgaben,
- Schema- und Bereichsprüfung der kritischen Konfiguration,
- deterministische visuelle Regressionstests für alle Orb-Zustände,
- lokale Diagnosekarte über das Kontextmenü,
- ereignisgesteuerter Fortschrittsring für längere Arbeiten,
- Augenparameter für Neugier, Überraschung und Unsicherheit.

Darauf aufbauend bleiben diese Vertiefungen sinnvoll:

1. Fehlertransparenz: Breite `except Exception`-Blöcke schrittweise durch
   konkrete Fehlertypen und strukturierte Diagnosedaten ersetzen. Ein
   optionaler Diagnosemodus sollte unterdrückte Ursachen sichtbar machen.
2. Lebenszyklus: Hintergrundaufgaben zentral registrieren und beim Beenden
   mit einem gemeinsamen Task-Manager abbrechen und abwarten.
3. Konfiguration: Ein maschinenlesbares Schema mit Typen, Grenzen und
   Migrationen einführen, damit fehlerhafte Werte mit Fundstelle erscheinen.
4. Renderer-Tests: Einen Headless-Screenshot-Test für jeden Orb-Zustand
   ergänzen. Strukturtests erkennen keine sichtbaren Regressionen.
5. Beobachtbarkeit: Startzeit, Antwortzeit, Provider-Wechsel, Werkzeugdauer
   und Renderer-FPS lokal in einer Diagnoseansicht zusammenfassen.

## Mögliche Erweiterungen

1. Personalisierbare Orb-Stile mit Profilen für Farbe, Intensität, Bewegung
   und reduzierte Animation.
2. Kleine lokale Statuskarte beim Rechtsklick: aktiver Provider,
   Mikrofonzustand, laufende Aufgabe, Datenschutzstatus und letzte Quelle.
3. Erweiterte emotionale Augen: Neugier, Unsicherheit, Überraschung und
   ruhige Bestätigung.
4. Visueller Fortschrittsring für lange lokale Arbeiten und Downloads,
   gekoppelt an echte Backend-Fortschrittsereignisse.
5. Exportierbare Diagnosepakete, die Geheimnisse automatisch entfernen und
   nur Versionsdaten, Konfigurationstypen und relevante Fehler enthalten.
