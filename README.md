# AI-Orb

Ein Desktop-Assistent für Windows, der als kleiner schwebender Orb auf dem
Bildschirm sitzt, auf Zuruf hört und antwortet. Er läuft lokal auf deinem
Rechner; nur die Anfragen an das Sprachmodell gehen nach außen – und wenn
kein Internet da ist oder Claudes Kontingent erschöpft ist, übernimmt ein
lokales Modell.

Version 0.26.17

## Loslegen

Du hast das Projekt als Quellcode. Zwei Wege führen zum laufenden Orb:

**Direkt aus dem Quellordner** (der einfachste Weg):

1. **`ORB-STARTEN.bat`** — holt beim ersten Mal die Python-Runtime und die
   Node-Pakete und startet den Orb. Danach genügt die Verknüpfung
   „AI-Orb (lokal)".

**Oder als installierte Anwendung:**

1. **`BUILD-INSTALLER.bat`** — erzeugt `AI-Orb-Setup.exe`. Beim ersten Mal
   etwa fünfzehn Minuten.
2. Doppelklick auf `AI-Orb-Setup.exe`. AI-Orb steht danach im Startmenü.

Zum **Bauen** brauchst du Node.js und Internet. Ausführlich in
`docs/INSTALLATION.md`.

### Zusätzlich einrichten (optional, einmalig mit Internet)

    OFFLINE-EINRICHTEN.bat    holt das lokale Modell (Ollama) und die
                              Offline-Stimme (Piper) – für den Betrieb
                              ohne Internet und bei erschöpftem Kontingent
    BROWSER-EINRICHTEN.bat    richtet die Browsersteuerung ein (Playwright),
                              damit der Orb ein echtes Browserfenster
                              bedienen kann

## Sprechen

Sag **„Hallo Orb"** (oder einfach **„Orb"**). Der Orb wacht auf, meldet sich
kurz und hört zu. Du kannst die Frage gleich anhängen: „Hallo Orb, wie spät
ist es?" – dann musst du nicht zweimal sprechen.

Nach einer Antwort bleibt er eine Weile wach; in dieser Zeit brauchst du das
Weckwort nicht zu wiederholen. Fängst du an zu sprechen, während er
antwortet, hört er auf. Mit „Danke" oder „Das war's" schläft er wieder ein.

Solange das Weckwort nicht gefallen ist, wird nichts weitergegeben und
nichts gespeichert. Die Aufnahmen werden nach der Erkennung gelöscht. Er
antwortet nur auf deine Stimme (Sprechererkennung, einlernbar).

## Was der Orb kann

**Antworten** über Claude – mit deinem Pro- oder Max-Abonnement, ohne
API-Schlüssel. Ist das Kontingent erschöpft oder fällt das Internet aus,
wechselt er auf ein lokales Modell (Ollama, `llama3.1:8b`) und bleibt für
eine Sperrfrist dort, statt bei jeder Frage erneut ins Limit zu laufen.

**Sprechen und zuhören**, online über ElevenLabs, offline über Piper – die
Spracherkennung (Whisper) läuft ohnehin lokal.

**Im Internet suchen und Webseiten lesen** – über mehrere unabhängige
Suchmaschinen, mit mehreren Quellen nebeneinander für eine ausgewogene
Sicht.

**Einen echten Browser bedienen** (nach `BROWSER-EINRICHTEN.bat`): eine
Seite öffnen, scrollen, klicken, in Felder tippen, Formulare abschicken –
in einem eigenen Profil, in dem deine Anmeldungen erhalten bleiben.

**Etwas tun**: Uhrzeit, Rechnen, Dateien lesen und suchen, Ordner
auflisten, Programme aus der freigegebenen Liste starten, Fenster
fokussieren und nebeneinanderlegen. Alles, was über Lesen hinausgeht,
fragt vorher.

**Auf den Bildschirm sehen**, wenn du ihn darum bittest – ein Standbild
wird ausgewertet und beschrieben.

**Sich merken**, worüber ihr gesprochen habt, an welchen Projekten du
arbeitest und was du dir notiert hast; **Wissen verknüpfen** in einem Netz
aus Personen, Quellen und Fragen; **beim Lernen helfen** mit Karteikarten
und Lernplänen; **wissenschaftlich mitdenken** mit Quellenkritik und
Gegenargumenten.

**Seine eigene Animation ändern** – auf Zuruf. „Mach die Punkte größer",
„andere Farben", „langsamer": Er passt die Werte an und lädt die Anzeige
neu. Für größere Wünsche schreibt er den Animationscode selbst um und baut
die Oberfläche neu.

**Abläufe wiederholen**: Was du einmal als Workflow gespeichert hast,
startest du später mit einem Satz.

## Wie er sich verhält

Der Orb ist so groß wie ein Desktopsymbol. Er zieht sich zusammen, wenn er
nichts zu tun hat, und richtet sich auf, wenn er zuhört. Ein dunkler
Energiekern, organische Lichtbahnen und ausdrucksstarke Augen zeigen seine
Zustände: aufmerksam beim Zuhören, konzentriert beim Denken, freundlich bei
Erfolg, warnend oder deutlich verändert bei einem Fehler.

Er weicht deiner Maus und dem aktiven Fenster aus, weich und ohne Sprünge.
Ziehst du ihn weg, merkt er sich das. Nachts ist er gedämpft und spricht
nicht von sich aus; er lernt deine Zeiten.

## Einstellen

Alles steht in **`config.yaml`**, jeder Eintrag mit einem Kommentar dazu.
Ein paar Stellen, die man häufig ändern will:

    orb.scale                     Größe des Orb
    voice.wake_word.phrases       Womit du ihn ansprichst
    voice.speaker.max_threshold   Wie streng die Sprechererkennung ist
    voice.output.engines          Welche Stimme, in welcher Reihenfolge
    ai.fallback.model             Das lokale Offline-Modell
    ai.primary.limit_cooldown_minutes  Sperrfrist bei erschöpftem Kontingent
    browser.*                     Die Browsersteuerung
    personality                   Wie förmlich, wie ausführlich
    security.never_allow          Was er auch mit Zustimmung nie tut

Zugangsdaten gehören **nicht** hierher, sondern in `.env`. Eine Vorlage
liegt als `.env.example` bereit.

## Sicherheit

Alles, was über das Antworten hinausgeht, läuft über eine einzige Stelle –
`backend/security/`. Kein Modul entscheidet selbst, ob es etwas darf.

- Was du nicht ausdrücklich erlaubst, geschieht nicht.
- Geheimnisse stehen ausschließlich in `.env`, nie im Quellcode.
- Was tatsächlich geschehen ist, steht im Prüfprotokoll.
- Alle Daten bleiben auf deinem Rechner. Es gibt keine Cloud und keine
  selbsttätige Übertragung.

## Wenn etwas nicht geht

**`DIAGNOSE.bat`** — Doppelklick. Ändert nichts, sieht nur nach und legt
einen Bericht ab: wo AI-Orb installiert ist, welche `config.yaml` wirklich
wirksam ist, welche Pakete fehlen, ob ein Antwortgeber erreichbar ist.

Der Ladebildschirm zeigt beim Start jeden Schritt und bleibt bei einem
Fehler stehen – mit der Begründung, nicht nur mit einem Kreuz. Das
laufende Protokoll steht in `AI-Orb-Start-Log.txt`.

## Aufbau

    backend/          Python: Denken, Sprache, Werkzeuge, Sicherheit
      ai/             Sprachmodell-Anbieter und Antwortpipeline
      orchestrator/   Anbieterwahl und Rückfall (Claude, Ollama)
      security/       Berechtigungen, Zustimmung, Prüfprotokoll
      voice/          Sprachpipeline und Sprechererkennung
      audio/          Mikrofon, Sprachaktivität, Wiedergabe
      whisper/        Spracherkennung und Weckwort
      tts/            Sprachausgabe (ElevenLabs, Piper, SAPI, Kokoro)
      tools/          Werkzeuge, die das Modell aufrufen kann
      browser/        Browsersteuerung (Playwright)
      vision/         Bildschirm ansehen
      animation/      Selbständige Änderung der eigenen Animation
      cognitive/ memory/ graph/ knowledge/ research/ learning/
      agents/ skills/ plugins/ evolution/

    desktop/          Electron und Three.js: der Orb selbst
      renderer/       Energy-Orb, Zustandsaugen und Animation

    docs/             Installation, Konfiguration, Phasen

## Tests

    python -m pytest

Der Testlauf umfasst mehrere hundert automatische Prüfungen.

## Lizenz

MIT. Siehe `LICENSE`.
