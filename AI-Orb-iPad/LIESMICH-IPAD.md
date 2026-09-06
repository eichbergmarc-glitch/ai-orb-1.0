# AI-Orb auf dem iPad — die geänderten Dateien

Stand: 27.08.2026

Dieses Archiv enthält alle Dateien, die für den iPad-Zugang neu
entstanden oder geändert worden sind. Die Ordnerstruktur entspricht dem
Projekt: Das Archiv lässt sich über einen Projektordner entpacken und
ersetzt dann genau diese Dateien.

**Auf dem Rechner `C:\Users\info\AI-Orb` sind sie bereits eingespielt.**
Dieses Paket ist die Sicherung und der Weg auf einen zweiten Rechner.

## Nicht enthalten

Die Datei `.env` — dort stehen die Zugangsschlüssel und das Losungswort.
Sie gehört nicht in ein Archiv, das den Rechner verlässt. Enthalten ist
nur `.env.example` mit leeren Platzhaltern.

## Neu

| Datei | Wofür |
|---|---|
| `IPAD-EINRICHTEN.bat` | Ein Doppelklick: Heimnetz freigeben, Firewall öffnen, Losungswort anlegen. Holt sich selbst Administratorrechte. |
| `FERNZUGANG.bat` | Derselbe Vorgang über Tailscale — für unterwegs und für HTTPS. |
| `scripts/fernzugang.py` | Die Arbeit hinter beiden Dateien. Schreibt alles nach `logs/ipad-einrichtung.txt`. |
| `desktop/renderer/web-bridge.js` | Ersetzt im Browser die Electron-Brücke `window.aiOrb`. Ohne sie startet der Renderer außerhalb von Electron nicht. |
| `tests/backend/test_oberflaeche_ausliefern.py` | 19 Tests: Auslieferung, Zugangsschutz, Anmeldeformular. |

## Geändert

| Datei | Was |
|---|---|
| `backend/api/http_server.py` | Liefert die Oberfläche aus und prüft den Zugang fremder Geräte. |
| `backend/api/server.py` | Findet den Ordner der gebauten Oberfläche. |
| `backend/launcher/health_check.py` | `0.0.0.0` ist keine Adresse zum Verbinden. |
| `desktop/electron/main.ts` | Dieselbe Unterscheidung an vier Stellen. |
| `desktop/renderer/index.html` | Ansichtsfenster für Tablet und Handy, `connect-src 'self'`, lädt die Web-Brücke. |
| `desktop/renderer/preview-bridge.js` | Meldet sich nur noch bei ausdrücklicher Vorschau. |
| `desktop/styles/orb.css` | Hintergrund im Browser, kein Gummiband-Scrollen, Rechner-Menüpunkte ausgeblendet. |
| `scripts/copy-assets.js` | Kopiert die Web-Brücke mit. |
| `config.yaml` | `backend.static_dir`. |
| `.env.example` | `AI_ORB_WEB_TOKEN`. |

## Zwei Fallen, die im Code jetzt entschärft sind

**`127.0.0.1` heißt nicht „vertrauenswürdig".** `tailscale serve`
verbindet sich selbst von `127.0.0.1` aus. Ohne Unterscheidung wäre der
Zugangsschutz ausgerechnet hinter dem Tunnel wirkungslos gewesen. Als
„dieser Rechner" zählt nur, was von `127.0.0.1` **ohne**
`X-Forwarded-For` kommt.

**`0.0.0.0` ist keine Adresse, an die man sich verbindet.** Es sagt, wo
gelauscht wird. Electron und der Startcheck lasen `backend.host` und
bauten daraus ihre Verbindungsadresse — mit `0.0.0.0` in der
Konfiguration hätte der Orb auf dem Rechner selbst seinen eigenen Kern
nicht mehr gefunden, und zwar genau ab dem Moment, in dem der Fernzugang
fertig eingerichtet ist.

## Auf einem zweiten Rechner

1. Archiv über den Projektordner entpacken.
2. `ORB-STARTEN.bat` — baut die Oberfläche neu.
3. `IPAD-EINRICHTEN.bat` — legt dort ein eigenes Losungswort an.
