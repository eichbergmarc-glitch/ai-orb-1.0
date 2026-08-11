# Installation

Stand: Version 0.4.0

## Für dich: der kurze Weg

Du hast das Projekt als Quellcode. Daraus wird in zwei Schritten eine
gewöhnliche Windows-Anwendung.

**Schritt 1 – Aufräumen.** Doppelklick auf `AUFRAEUMEN.bat`. Das entfernt,
was von der alten skriptbasierten Arbeitsweise übrig ist: die
Python-Umgebung, die Node-Pakete, alte Builds, Reparaturskripte, Patches.
Deine Erinnerungen, Einstellungen und Zugangsdaten bleiben; die neue Fassung
übernimmt sie beim ersten Start.

**Schritt 2 – Bauen.** Doppelklick auf `BUILD-INSTALLER.bat`. Das erzeugt
`dist-installer\AI-Orb-Setup.exe`. Beim ersten Mal dauert es etwa fünfzehn
Minuten und lädt rund 700 MB — dabei entsteht unter anderem eine eigene
Python-Runtime, die später mit ausgeliefert wird.

Danach hast du eine Installationsdatei. Doppelklick, und AI-Orb ist
installiert. Im Startmenü steht „AI-Orb"; ein Klick, und der Orb erscheint.

Gebraucht wird zum **Bauen** Node.js und eine Internetverbindung. Zum
**Benutzen** nichts davon.

## Warum das Bauen nicht schon geschehen ist

Ein Windows-Installationspaket lässt sich nur unter Windows erzeugen. Das
liegt am Format: NSIS erstellt eine ausführbare Datei mit
Windows-Ressourcen, und dafür braucht es Windows-Werkzeuge. Ich habe
deshalb alles vorbereitet, was sich vorbereiten lässt — die Konfiguration,
das Installationsskript, das Icon, den Launcher — und den einen Schritt, der
Windows verlangt, in eine Datei gepackt, die du anklickst.

## Was der Installer tut

    AI-Orb-Setup.exe
        ↓
    System und Windows-Fassung prüfen
        ↓
    Läuft AI-Orb noch? Dann sauber beenden
        ↓
    Programm nach C:\Users\<du>\AppData\Local\Programs\AI-Orb
        ↓
    Mitgelieferte Python-Runtime, Electron, Sprachpakete
        ↓
    Benutzerordner unter %APPDATA%\AI-Orb anlegen
        ↓
    Startmenü-Eintrag mit AI-Orb-Icon
        ↓
    Desktop-Verknüpfung (abwählbar)
        ↓
    Autostart (nicht vorgewählt)
        ↓
    Uninstaller registrieren
        ↓
    Fertig

Der Benutzer installiert nichts von Hand: kein Python, kein Node.js, kein
npm, kein pip, keine virtuelle Umgebung. Nichts davon muss er kennen.

## Was beim Klick geschieht

    Startmenü → AI-Orb
        ↓
    Electron startet (das ist der Launcher)
        ↓
    Ladebildschirm erscheint
        ↓
    Python-Kern wird gestartet
        ↓
    Startprüfung: Windows, Runtime, Verzeichnisse, Konfiguration,
    Port, Backend, ProviderManager, Ollama, Audio, Whisper,
    Kokoro, Memory, Desktop, Human Experience
        ↓
    Dienstüberwachung beginnt
        ↓
    Ladebildschirm schließt, der Orb erscheint
        ↓
    „Hallo Orb."

Auf einem eingerichteten Rechner dauert das wenige Sekunden. Beim ersten
Start kommt das Laden der Sprachmodelle dazu.

## Wo was liegt

Programmdateien und Benutzerdaten sind getrennt. Das ist Voraussetzung
dafür, dass ein Update nichts löscht und eine Deinstallation zwischen
„Programm entfernen" und „Daten löschen" unterscheiden kann.

| Was | Wo |
|---|---|
| Programm | `%LOCALAPPDATA%\Programs\AI-Orb` |
| Einstellungen, Zugangsdaten | `%APPDATA%\AI-Orb\config.yaml`, `.env` |
| Gedächtnis, Wissensnetz, Karteikarten | `%APPDATA%\AI-Orb\data\` |
| Protokolle | `%APPDATA%\AI-Orb\logs\` |
| Eigene Plugins und Skills | `%APPDATA%\AI-Orb\plugins\`, `skills\` |
| Sprachmodelle | `%LOCALAPPDATA%\AI-Orb\cache\models\` |

Die Sprachmodelle liegen bewusst im lokalen Zwischenspeicher und nicht bei
den Benutzerdaten: In einem Netzwerk wandert `%APPDATA%` mit dem
Benutzerprofil mit, und ein Modell von mehreren hundert Megabyte hat dort
nichts verloren. Es ist außerdem jederzeit wieder herunterladbar.

Läuft AI-Orb aus dem Quellordner, bleibt alles beisammen — das ist beim
Entwickeln praktisch und für einen USB-Stick brauchbar. Erkannt wird das an
der Datei `.installiert`, die der Installer anlegt.

## Aktualisieren

Ein Update ersetzt nur den Programmordner. Diese Dinge fasst es nie an:

- Gedächtnis und Gespräche
- Benutzereinstellungen
- Projekte
- Wissensnetz
- Positionsdaten
- Zugangsdaten

Für Änderungen im Quellstand gibt es zusätzlich `upgrade.py` mit Sicherung,
Tests und selbsttätiger Rücknahme.

## Deinstallieren

Windows-Einstellungen → Apps → Installierte Apps → AI-Orb → Deinstallieren.

Am Ende wird gefragt, ob auch die persönlichen Daten weg sollen. Die Frage
kommt nur, wenn überhaupt welche da sind, sie nennt den Umfang, und sie
wird zweimal gestellt. Wer „Nein" wählt, findet bei einer Neuinstallation
alles wieder vor.

Der Autostart-Eintrag wird in jedem Fall entfernt.

## Wenn etwas unklar ist: DIAGNOSE.bat

Doppelklick auf `DIAGNOSE.bat`. Die Datei ändert nichts. Sie schreibt einen
Bericht auf den Desktop, der die Fragen beantwortet, die man dem laufenden
Programm nicht ansieht:

- Wo ist AI-Orb installiert, und liegt dort alles, was hingehört?
- Welche `config.yaml` ist tatsächlich wirksam?
- Findet der Python-Kern sein eigenes Paket?
- Welche Sprachpakete fehlen?
- Ist Claude Code oder Ollama erreichbar?
- Darf AI-Orb auf das Mikrofon?
- Was steht in den letzten Protokollzeilen?

Das ist deshalb nützlich, weil ein Programm, das eine Datei nicht findet,
nicht abstürzt, sondern stillschweigend Vorgabewerte nimmt. Man sieht dann
ein Verhalten, aber nicht seinen Grund.

## Wenn beim Start etwas fehlt

Der Ladebildschirm zeigt jeden Schritt und bleibt bei einem Fehler stehen —
mit der Begründung, nicht nur mit einem Kreuz.

Fehlt etwas Entbehrliches, startet AI-Orb trotzdem und sagt, was fehlt:

- **Ollama fehlt** → AI-Orb läuft, antwortet aber nicht ohne Internet.
- **Whisper fehlt** → AI-Orb antwortet auf Getipptes, hört aber nicht zu.
- **Kein Mikrofon** → dasselbe. Prüfe Windows-Einstellungen → Datenschutz →
  Mikrofon.
- **Kokoro/Piper fehlt** → AI-Orb spricht über die Windows-Sprachausgabe.

Ohne diese kommt AI-Orb nicht hoch:

- **Runtime** → die Installation ist unvollständig, neu installieren.
- **Port belegt** → ein anderes Programm benutzt Port 8756. Läuft AI-Orb
  bereits, wird kein zweites gestartet.
- **Backend nicht ladbar** → eine Programmdatei fehlt, neu installieren.
- **Kein Sprachmodell** → weder Claude noch Ollama erreichbar. Melde dich in
  Claude Code an (`claude` im Terminal) oder installiere Ollama.

## Wenn ein Dienst abstürzt

Er wird neu gestartet, mit wachsendem Abstand: eine Sekunde, zwei, vier.
Nach der dritten vergeblichen Wiederholung wird aufgegeben und gesagt, was
fehlt.

Ein entbehrlicher Ausfall beendet AI-Orb nicht:

- Sprachausgabe fällt aus → die Antwort erscheint weiter als Text.
- Ollama fällt aus, Claude läuft → Claude wird weiter benutzt.
- Claude fällt aus → Ollama übernimmt.
- Bildverstehen fällt aus → alles Übrige läuft.

Ein Dienst, der fünf Minuten stabil gelaufen ist, gilt wieder als gesund;
seine Fehlerzählung wird zurückgesetzt. Sonst käme ein Dienst, der einmal im
Monat stolpert, nach einem Jahr an seine Grenze.

## Bauen ohne Sprachpakete

    BUILD-INSTALLER.bat /ohne-sprache

Das Paket wird deutlich kleiner. AI-Orb spricht dann über die
Windows-Sprachausgabe und reagiert nicht auf das Weckwort. Nachrüsten geht
jederzeit über den Programmordner.

## Weitere Schalter

| Aufruf | Wirkung |
|---|---|
| `AUFRAEUMEN.bat /probelauf` | zeigt nur, was geschehen würde |
| `AUFRAEUMEN.bat /auch-daten` | löscht auch Erinnerungen (zweimal bestätigt) |
| `BUILD-INSTALLER.bat /schnell` | vorhandene Python-Runtime wiederverwenden |
| `BUILD-INSTALLER.bat /neu` | alles von Grund auf neu bauen |
