# Eigene Skills für AI-Orb schreiben

Neue Fähigkeiten werden nicht in den Kern programmiert, sondern als Skills
installiert. Der Kern bleibt dabei unverändert, und Skills lassen sich
jederzeit aktivieren, deaktivieren, aktualisieren oder zurückrollen.

## Aufbau eines Skills

Ein Skill ist ein Verzeichnis mit vier Dateien:

```
mein-skill/
├── skill.json      Beschreibung, Version, Berechtigungen, Fähigkeiten
├── skill.py        Der Einstiegspunkt
├── test_skill.py   Tests
└── README.md       Dokumentation
```

Die `skill.json` beschreibt den Skill vollständig:

```json
{
  "name": "pdf-analyse",
  "version": "1.0.0",
  "description": "Liest PDFs aus und erzeugt Exzerpte.",
  "author": "Dein Name",
  "permissions": ["file_read"],
  "dependencies": ["pypdf"],
  "capabilities": ["pdf_lesen", "exzerpt"],
  "entrypoint": "skill.py",
  "min_orb_version": "0.1.0",
  "documentation": "Siehe README.md",
  "configuration": {}
}
```

Der Name darf nur Kleinbuchstaben, Ziffern, Bindestriche und Unterstriche
enthalten, die Version muss dem Muster `X.Y.Z` folgen.

## Der Einstiegspunkt

`skill.py` stellt eine Funktion `create_skill(api)` bereit, die eine
Instanz zurückgibt. Für jede Fähigkeit gibt es eine Methode
`handle_<fähigkeit>`:

```python
"""PDF-Analyse – Skill für AI-Orb."""

from __future__ import annotations

from typing import Any


class PdfAnalyseSkill:
    """Liest PDFs und erzeugt Exzerpte."""

    def __init__(self, api: Any) -> None:
        self.api = api

    def setup(self) -> None:
        """Wird beim Aktivieren aufgerufen."""
        self.api.log("PDF-Analyse aktiviert.")

    def teardown(self) -> None:
        """Wird beim Deaktivieren aufgerufen."""

    def handle_pdf_lesen(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Liest eine PDF-Datei aus."""
        self.api.require_permission("file_read")

        path = payload.get("path", "")
        # ... eigentliche Umsetzung ...
        return {"success": True, "text": "..."}


def create_skill(api: Any) -> PdfAnalyseSkill:
    """Erzeugt die Skill-Instanz."""
    return PdfAnalyseSkill(api)
```

Sowohl `setup`, `teardown` als auch die Handler dürfen asynchron sein.

## Die Skill-API

Der Skill spricht ausschließlich über das übergebene `api`-Objekt mit
AI-Orb. Direkte Systemzugriffe sind nicht vorgesehen und werden vom
Validator beanstandet.

`api.has_permission(name)` prüft eine Berechtigung,
`api.require_permission(name)` erzwingt sie und löst andernfalls einen
`PermissionError` aus. `api.log(text)` schreibt in das Skill-Log.
`api.remember(inhalt, tags=[...])` legt eine Information im Gedächtnis ab.
`await api.emit(ereignis, daten)` veröffentlicht ein Ereignis auf dem Event
Bus – es erscheint dort unter `skill.<skillname>.<ereignis>`.

## Berechtigungen

Es gibt neun Berechtigungen: `file_read`, `file_write`, `internet`,
`browser_control`, `microphone`, `camera`, `system_commands`, `database`
und `screen_capture`.

Jede muss in `skill.json` angemeldet werden. Der Validator analysiert
zusätzlich den Quellcode: Nutzt ein Skill etwa `subprocess`, ohne
`system_commands` angemeldet zu haben, wird das als Sicherheitshinweis
gemeldet.

Die in `config.yaml` unter `skills.restricted_permissions` genannten Rechte
gelten als besonders weitreichend und werden dem Benutzer bei der
Installation ausdrücklich hervorgehoben.

## Installation

Der Ablauf ist fest vorgegeben und lässt sich nicht abkürzen: Skill gefunden
→ Beschreibung anzeigen → Berechtigungen anzeigen → Benutzer bestätigt →
Installation → Tests → Aktivierung.

Über die API:

```
POST /skills/prepare   {"path": "C:\\Pfad\\zu\\mein-skill"}
POST /skills/install   {"path": "...", "confirmed": true}
POST /skills/activate  {"name": "pdf-analyse"}
```

`prepare` prüft und legt den Vorschlag vor, ohne etwas zu installieren.
Erst `install` mit `confirmed` kopiert den Skill nach `skills/`.

Fehlende Abhängigkeiten werden gemeldet, aber **niemals automatisch
installiert**. Das ist Absicht: AI-Orb installiert nichts eigenmächtig auf
deinem System.

## Ein Gerüst erzeugen lassen

AI-Orb kann ein vollständiges Skill-Gerüst selbst erzeugen – mit Manifest,
Quellcode, Tests, Dokumentation und Changelog:

```python
runtime.evolution.propose_skill("zotero")
```

Der Entwurf landet unter `data/evolution/skill_drafts/` und ist
ausdrücklich **nicht** installiert. Vorbereitete Vorlagen gibt es für
Zotero, LibreOffice, GIMP, Blender, VS Code, Docker, Git, Home Assistant und
PDF-Analyse.

## Aktualisieren und zurückrollen

`SkillUpdater.check(name, pfad)` prüft eine neue Version auf Kompatibilität,
neue Berechtigungen, Sicherheitsrisiken und einen Hauptversionssprung.
Verlangt ein Update neue Rechte oder ist es ein größeres Update, wird der
Benutzer ausdrücklich gefragt.

Vor jedem Update sichert AI-Orb die bisherige Version. `rollback(name)`
stellt sie wieder her, `history(name)` zeigt die Änderungshistorie.
