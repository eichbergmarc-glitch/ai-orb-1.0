# Umsetzung der 21 Phasen

Stand: 07.08.2026 · Version 0.4.0

Diese Übersicht ordnet jede Phase aus der Builder-Prompt-Sammlung dem Code
zu, der sie umsetzt. Wo etwas bewusst anders oder eingeschränkt gelöst ist,
steht der Grund dabei.

## Phase 1 – Projektgrundlage

Umgesetzt in `backend/config/`, `backend/system/logging_setup.py`,
`backend/events/`, `backend/runtime.py`, `backend/api/`.

Zentrale Konfiguration in `config.yaml`, Geheimnisse ausschließlich in
`.env`, rotierende Protokolldateien, ein Event-Bus als einziges
Verständigungsmittel zwischen den Modulen, geordnetes Starten und
Herunterfahren, eine lokale HTTP-Schnittstelle mit Server-Sent-Events zur
Oberfläche.

Eine Abweichung: In der Vorgabe steht Linux als Zielplattform, du hast aber
ausdrücklich Windows verlangt. Der Code läuft plattformübergreifend; nur
die Fenstersteuerung, die Windows-Sprachausgabe und die Startskripte sind
Windows-spezifisch, und alle drei melden auf anderen Systemen im Klartext,
dass sie dort nicht arbeiten.

## Phase 2 – Whisper Speech-to-Text

`backend/whisper/transcriber.py`, `backend/audio/audio_capture.py`,
`backend/audio/vad.py`.

Das Modell wird verzögert geladen und im Hintergrund vorgewärmt, damit der
Start nicht wartet. Die Erkennung läuft in einem Worker-Thread, sodass die
Oberfläche nie einfriert. Leere Aufnahmen werden über die
Sprachaktivitätserkennung schon vorher aussortiert. Fehlt `faster-whisper`,
sagt das Modul das mit Installationsanweisung – der Orb stürzt nicht ab,
sondern läuft ohne Spracheingabe weiter.

## Phase 3 – KI-Provider

`backend/ai/provider_registry.py`, `backend/ai/provider_factory.py`,
`backend/orchestrator/provider_manager.py`, `backend/orchestrator/providers/`.

Vier Anbieter: `claude_code` (deine Claude-Code-Befehlszeile, also dein
Abonnement), `claude` (Messages-API), `ollama` (lokal), `hermes`
(OpenAI-kompatibel). Gesundheitsprüfung, selbsttätiges Umschalten,
einheitliche Fehlerbehandlung.

Auf deinen Wunsch ist `claude_code` als primärer Anbieter eingetragen und
Hermes nur noch als Möglichkeit dokumentiert.

## Phase 4 – Kokoro Voice

`backend/tts/`.

Kokoro ist umgesetzt (`kokoro_engine.py`), aber **nicht** als Voreinstellung.
Der Grund ist sachlich: Kokoro ist auf Englisch, Spanisch, Französisch,
Hindi, Italienisch, Japanisch, Portugiesisch und Chinesisch trainiert –
Deutsch gehört nicht dazu. Deutscher Text käme mit hörbar fremdem Akzent.

Deshalb ist die Reihenfolge Piper → SAPI → Kokoro. Piper hat sehr gute
deutsche Stimmen und läuft ebenfalls lokal; die Windows-Sprachausgabe ist
immer da und braucht keine Installation. Die Reihenfolge steht in
`config.yaml` unter `voice.output.engines` und lässt sich jederzeit ändern.

Abschnittsweise Wiedergabe, Zwischenspeicher, keine überlappenden
Wiedergaben, Unterbrechen, Lautstärke und Geschwindigkeit einstellbar –
alles wie verlangt.

## Phase 5 – Multi-Agent-System

`backend/agents/` mit Registry, Router, Scheduler, Dispatcher, Result
Merger und den Standardagenten. Ein Fehler eines Agenten bricht den Orb
nicht ab.

## Phase 6 – Skill- und Plugin-System

`backend/skills/` (neun Module) und `backend/plugins/`.

Beide verlangen ein Manifest mit Name, Version, Beschreibung und
Berechtigungen, zeigen diese vor der Installation an und werden gegen die
Sicherheitsschicht geprüft. Ein Beispiel-Plugin liegt unter
`plugins/beispiel/`.

Offen gesagt: Python kann fremden Code im selben Prozess nicht wirklich
einsperren. Was AI-Orb tut, ist dreierlei – vor dem Laden fragen, nur die
im Manifest angemeldeten Berechtigungen zulassen, und jeden Werkzeugaufruf
über die Sicherheitsschicht führen. Das steht auch so im Zustimmungsdialog.

## Phase 7 – Personal Knowledge Graph

`backend/graph/knowledge_graph.py`.

Elf Knotenarten (Person, Ereignis, Ort, Buch, Artikel, Quelle, Projekt,
Notiz, Forschungsfrage, Dokument, Begriff) und sieben Beziehungsarten
(erwähnt, widerspricht, unterstützt, gehört zu, relevant für, zitiert,
folgt auf). Beziehungen werden in beiden Richtungen durchlaufen, sodass man
von einer Quelle aus die zitierenden Arbeiten findet.

`contradictions()` gibt alle Widersprüche zurück – für wissenschaftliches
Arbeiten der wichtigste Blick. Alles lokal, einsehbar, löschbar und
exportierbar.

## Phase 8 – Presence AI und Bildschirmplatzierung

`backend/presence/`, `backend/behavior/behavior_engine.py`,
`desktop/renderer/movement.ts`, `backend/system/desktop_control.py`.

Der Orb weicht Maus und aktivem Fenster aus, lernt manuelle Platzierungen
als Vorliebe, bewegt sich weich ohne Sprünge und arbeitet nie mit festen
Bildschirmkoordinaten. Die Bewegung läuft in der Grafikkarte innerhalb
eines größeren unsichtbaren Fensters – das war die Ursache des Ruckelns,
das du gemeldet hattest.

## Phase 9 – Bildschirm- und Desktop-Interaktion

`backend/tools/`, `backend/system/window_control.py`,
`backend/system/desktop_control.py`.

Werkzeuge mit Namen, Parameterschema, Berechtigung, Protokoll,
Fehlerbehandlung und Zeitlimit – genau wie verlangt. Fenster finden,
fokussieren, verschieben, skalieren, nebeneinanderlegen. Programme nur aus
der Liste in `config.yaml`.

Bewusst nicht umgesetzt: das Ausführen beliebiger Befehle. Die Berechtigung
`system_commands` steht in `config.yaml` unter `security.never_allow` und
wird auch mit Zustimmung nicht gewährt.

## Phase 10 – Cognitive Core

`backend/cognitive/`.

Absichtserkennung, Kontextaufbau, Gedächtnis, Schlussfolgern,
Agentenauswahl, Werkzeuge, Antwort, Sprachausgabe. Der Kern spricht kein
Sprachmodell direkt an, sondern ausschließlich über den ProviderManager.
Unsicherheit wird gekennzeichnet statt verschwiegen.

## Phase 11 – Forschung und Geschichtswissenschaft

`backend/research/`.

Quellenkritik mit den Fragen der äußeren und inneren Kritik, Unterscheidung
von Primärquelle, Forschungsliteratur und Nachschlagewerk, Prüfung von
Forschungsfragen und Thesen, Erkennung typischer Fehlschlüsse,
Gliederungsgerüste, Gegenargumente.

Der Leitsatz aus der Vorgabe ist wörtlich umgesetzt: Der Orb schreibt keine
Arbeiten. Er stellt Rückfragen und zeigt Lücken. Auf „schreib mir eine
These" kommt keine These, sondern woran eine brauchbare These zu erkennen
ist.

## Phase 12 – Self-Learning

`backend/learning/preference_learner.py`, `backend/evolution/`.

Gelernt wird aus beobachtbarem Verhalten – Antwortlänge, bevorzugter Weg,
aktive Zeiten, wiederkehrende Themen –, und erst ab genügend Belegen. Aus
einer einzigen kurzen Frage folgt nichts. Die Sicherheit ist bei 0,85
gedeckelt; über einen Menschen gibt es keine Gewissheit.

Kein Produktionscode wird ohne Freigabe verändert.

## Phase 13 – Self-Code-Optimization

`backend/evolution/` mit Codeanalyse, Fehlererkennung,
Leistungsanalyse, Patch-Erzeugung, Tests, Benchmarks, Freigabe und
Rücknahme. Die produktive Codebasis wird nie automatisch verändert; alles
entsteht in `data/evolution/`.

## Phase 14 – Orb-Darstellung mit dynamischem Rauch

`desktop/shaders/smoke.glsl`, `desktop/renderer/effects.ts`,
`desktop/renderer/orb.ts`, `desktop/renderer/states.ts`.

Statt einer Oberflächentextur wird tatsächlich durch das Volumen
marschiert: Für jeden Bildpunkt verfolgt der Shader den Strahl durch die
Kugel und sammelt dabei Dichte auf. Mehrfachrauschen erzeugt grobe Schwaden
mit feiner Struktur, die Verzerrung des Raums die langsamen Wirbel. Kacheln
und harte Kanten gibt es dadurch nicht.

Zustandsabhängig: ruhig im Leerlauf (0,35), leicht aktiviert beim Zuhören
(0,7), wirbelnd beim Denken (1,55), pulsierend beim Sprechen, warmer
Warnschimmer bei einem Fehler. Alles läuft in der Grafikkarte; bei
schwacher Leistung werden zuerst die Schritte gesenkt und dann der Nebel
abgeschaltet.

## Phase 15 – Natürliche Sprachinteraktion

`backend/voice/voice_pipeline.py`.

Die vollständige Kette: Mikrofon, Sprachaktivitätserkennung, Whisper,
Weckwort, Sprachmodell, Abschnittsbildung, Sprachausgabe.

Der Orb hört auf zu sprechen, sobald du beginnst. Nach einer Antwort bleibt
er 25 Sekunden wach, sodass ein Gespräch nicht bei jeder Frage mit „Hallo
Orb" beginnen muss. Bei unsicherer Erkennung fragt er nach, statt zu raten.
Zustände: schlafend, zuhörend, denkend, sprechend, aus.

## Phase 16 – Intelligente Bildschirmwahrnehmung

`backend/behavior/usage_heatmap.py`.

Ein Raster von 12 mal 12 Zellen sammelt Gewicht aus Mausbewegung, Klicks,
Texteingaben und aktiven Fenstern. Klicks wiegen zwanzigmal so viel wie
bloßes Vorbeifahren, Texteingaben noch mehr – dort steht ein Eingabefeld.
Am schwersten wiegt, wenn du den Orb von einer Stelle weggezogen hast.

Die Karte wird nur alle zwanzig Sekunden verrechnet und klingt mit einer
Halbwertszeit von vierzehn Tagen ab. Erfasst werden ausschließlich
Koordinaten und Zeitpunkte, keine Inhalte. Abschaltbar und löschbar.

## Phase 17 – Robuste Antwortpipeline

`backend/ai/response_pipeline.py`.

Jede Anfrage bekommt eine Kennung, ein Zeitlimit und eine Prüfung ihres
Ergebnisses. Als ungültig gelten nicht nur leere Antworten, sondern auch
„undefined", „null", reine Sonderzeichen und Platzhalter – die kommen in
der Praxis häufiger vor als echte Netzwerkfehler und sind unangenehmer,
weil sie wie eine Antwort aussehen.

Fällt eine Stufe aus, greift die nächste. Fallen alle aus, kommt ein
verständlicher Satz statt eines leeren Feldes. Es gibt keinen unbehandelten
Fehler.

## Phase 18 – Lernassistent

`backend/learning/flashcards.py`, `backend/learning/study_plan.py`.

Karteikarten mit abgestuften Wiederholungen nach dem SM-2-Verfahren: Was
sitzt, wird selten abgefragt, was wackelt, häufig. Vier Bewertungsstufen
statt richtig/falsch, weil der Unterschied zwischen „mit Mühe erinnert" und
„sofort gewusst" für die Terminplanung der wichtigste ist.

Lernpläne bis zu einem Termin verteilen Schwieriges zuerst und lassen den
letzten Tag für Wiederholung frei. Reicht die Zeit nicht, wird das gesagt
statt beschönigt. Der Fortschritt wird nicht geschätzt, sondern an den
zugehörigen Karteikarten gemessen.

## Phase 19 – Workflow Engine

`backend/workflows/`.

Abläufe mit Namen, Schritten, Bedingungen, Berechtigungen,
Fehlerbehandlung, Wiederholungen und Zeitlimit. Ergebnisse fließen über
`{{schritt.name}}` in spätere Schritte. Für jeden Schritt ist festgelegt,
was bei einem Fehlschlag geschieht: abbrechen, überspringen oder
wiederholen.

Pausierbar und abbrechbar – aber nur zwischen den Schritten, nicht mitten
in einem. Ein Werkzeugaufruf, der zur Hälfte abgebrochen wird, hinterlässt
einen Zustand, den niemand versteht.

## Phase 20 – Startstabilität und Provider-Refactoring

`backend/ai/` als einzige Anlaufstelle für alles, was mit dem Sprachmodell
zu tun hat: Verzeichnis, Fabrik, Antwortpipeline, Manager. Die Fabrik prüft
schon beim Bauen, ob Modellname und Schlüssel vorhanden sind, und nennt
fehlende Angaben mit dem Ort, an den sie gehören.

`ProviderFactory.diagnose()` schreibt beim Start im Klartext, welche
Anbieter einsatzbereit sind – wer dort liest, dass der Rückfallanbieter
fehlt, weiß es, bevor das Internet ausfällt.

## Phase 21 – Ein-Kommando-Upgrade

`upgrade.py`.

    python upgrade.py sprint01
    python upgrade.py --list
    python upgrade.py --rollback

Zustand prüfen, sichern, Fassung feststellen, einspielen, Abhängigkeiten
prüfen, Tests laufen lassen, bei Fehlern zurücknehmen. Gesichert wird als
vollständige Dateikopie und nicht über Git – wer AI-Orb als Zip
heruntergeladen hat, hat kein Git-Verzeichnis und braucht die Rücknahme am
dringendsten.

---

## Was bewusst nicht umgesetzt ist

**Beliebige Systembefehle.** Die Vorgabe verlangt ausdrücklich, dass das
Modell keine willkürlichen Shell-Befehle ausführt. `system_commands` steht
deshalb in `security.never_allow` und wird auch mit Zustimmung verweigert.

**Automatisches Schließen von Programmen.** `terminate_process` ist als
kritisch eingestuft und jedes Mal einzeln zu bestätigen; die
Fenstersteuerung schließt grundsätzlich nichts.

**Automatische Installation von Abhängigkeiten.** Auch das ist eine
Vorgabe. Was fehlt, wird gemeldet, nicht heimlich nachinstalliert – mit der
einen Ausnahme des Reparaturskripts, das du selbst anklickst.

**Übertragung von Quellcode an externe Dienste.** `send_code_external`
steht ebenfalls in `security.never_allow`.

---

# Phasen 41 bis 63 – Windows One-Click Installation

Stand: Version 0.4.0. Die ausführliche Anleitung steht in
`docs/INSTALLATION.md`.

## Phase 41, 42, 60 – One-Click-Installer

`package.json` (Abschnitt `build`), `build/installer.nsh`,
`scripts/build-installer.ps1`, `BUILD-INSTALLER.bat`.

electron-builder mit NSIS erzeugt eine einzige Datei `AI-Orb-Setup.exe`.
Sie prüft System und Windows-Fassung, beendet ein laufendes AI-Orb, legt
Programm und Benutzerordner an, richtet Startmenü, Desktop-Verknüpfung und
Autostart ein und registriert einen Uninstaller.

Ein Windows-Installationspaket lässt sich nur unter Windows erzeugen. Der
eine Schritt, der Windows verlangt, steckt deshalb in einer Datei zum
Anklicken.

## Phase 43, 44, 53 – Startmenü, ein Klick, Icon

`build/icon.ico` in sieben Größen von 16 bis 256 Bildpunkten, dazu
Einzel-PNGs unter `build/icons/`. Kein generisches Electron-Symbol.

Der Startmenü-Eintrag heißt „AI-Orb". Ein Klick startet Electron, das
seinerseits den Python-Kern hochfährt – kein Terminal, keine PowerShell,
kein manueller Start von Ollama oder Backend.

## Phase 45 – Launcher

`backend/launcher/launcher.py`, `desktop/electron/backend_process.ts`,
`desktop/electron/splash.ts`.

Prüft Voraussetzungen, prüft den Port, erkennt ein bereits laufendes
AI-Orb, startet Backend und Ollama, wartet auf Betriebsbereitschaft,
schreibt Protokoll und beendet alles geordnet. Der Kindprozess läuft ohne
Fenster (`windowsHide`).

Der Ladebildschirm zeigt jeden Schritt, während er geschieht.

## Phase 46, 47, 48 – Keine manuelle Abhängigkeitsinstallation

`scripts/prepare-runtime.ps1`.

Die Python-Runtime wird beim Bauen aus der embeddable-Fassung von
python.org zusammengestellt, mit pip und allen Paketen bestückt und unter
`runtime/python/` ins Paket gelegt. Electron kommt ohnehin mit.

Der Benutzer sieht deshalb nie „python is not recognized", „npm is not
recognized" oder „module not found".

Ein Detail, das leicht übersehen wird und ohne das nichts läuft: In der
embeddable-Fassung ist `site-packages` ab Werk abgeschaltet. Das Skript
passt die `._pth`-Datei entsprechend an.

## Phase 49 – Ollama

`backend/launcher/ollama_service.py`.

Findet Ollama auch dann, wenn es nicht im PATH steht (unter Windows der
Normalfall), startet den Dienst ohne Fenster, prüft das Modell und zeigt
den Ladestand.

Bewusst nicht umgesetzt: das ungefragte Installieren von Ollama und das
ungefragte Herunterladen des Modells. Ollama ist ein eigenständiges
Programm, und `llama3.1:8b` sind rund fünf Gigabyte. Beides wird angeboten
und erklärt, nicht heimlich erledigt – auch die Sicherheitsvorgabe schließt
automatische Installation von Abhängigkeiten aus.

## Phase 50 – Claude

Claude bleibt die primäre KI. Fällt sie aus, übernimmt Ollama. Welcher
Modus aktiv ist, steht im Startbericht, unter `/status` und in der
Transparenzansicht.

## Phase 51 – Whisper und Kokoro

Beide sind Bestandteil des Installationspakets: Die Pakete kommen über
`requirements-voice.txt` in die mitgelieferte Runtime, die Modelldateien
lädt AI-Orb beim ersten Gebrauch selbst nach.

## Phase 52 – Installationsverzeichnis

`backend/utils/paths.py`.

Programm unter `%LOCALAPPDATA%\Programs\AI-Orb`, Benutzerdaten unter
`%APPDATA%\AI-Orb`, Sprachmodelle unter `%LOCALAPPDATA%\AI-Orb\cache`. In
den Programmordner wird nie geschrieben.

Wer AI-Orb bisher aus dem Quellordner betrieben hat, dessen Daten werden
beim ersten Start der installierten Fassung übernommen – kopiert, nicht
verschoben, und nichts wird dabei überschrieben.

## Phase 54, 55 – Desktop-Verknüpfung und Autostart

Die Startmenü-Verknüpfung entsteht immer, die Desktop-Verknüpfung ist
abwählbar, der Autostart ist nicht vorgewählt. Er lässt sich jederzeit
abschalten; beim Deinstallieren wird er in jedem Fall entfernt.

## Phase 56 – Update

Ein Update ersetzt nur den Programmordner. Gedächtnis, Einstellungen,
Projekte, Wissensnetz und Positionsdaten bleiben – das ist der Zweck der
Trennung aus Phase 52. Die Liste steht auch in `config.yaml` unter
`update.never_touch`, damit sie nachlesbar ist.

## Phase 57 – Uninstaller

`build/installer.nsh`, Makro `customUnInstall`.

Trennt „Programm entfernen" von „Benutzerdaten löschen". Gefragt wird nur,
wenn Daten vorhanden sind; die Frage nennt den Umfang und wird zweimal
gestellt. Wer verneint, findet bei einer Neuinstallation alles wieder vor.

## Phase 58 – Crash Recovery

`backend/launcher/supervisor.py`.

Ausfälle werden erkannt, protokolliert und behoben – mit wachsendem Abstand
zwischen den Versuchen und einer Obergrenze. Ein Dienst, der fünf Minuten
stabil lief, gilt wieder als gesund.

Entbehrliche Ausfälle beenden AI-Orb nicht: Sprachausgabe weg heißt Antwort
als Text, Ollama weg heißt Claude, Claude weg heißt Ollama, Bildverstehen
weg heißt alles Übrige läuft weiter.

## Phase 59 – Health Check

`backend/launcher/health_check.py`.

Vierzehn Prüfungen in der Form der Vorgabe. Jede liefert bei einem Fehler
nicht nur ein Kreuz, sondern den Grund und den nächsten Schritt.
Unterschieden wird zwischen notwendig und entbehrlich – daraus wird
„READY", „READY (eingeschränkt)" oder „NICHT BEREIT".

Abrufbar auch ohne Start: `python -m backend.main --check`.

## Phase 61 – Finaler Benutzerworkflow

    AI-Orb-Setup.exe herunterladen
        ↓ Doppelklick
    Installation läuft durch
        ↓
    Startmenü → AI-Orb
        ↓ ein Klick
    Ladebildschirm, dann der Orb
        ↓
    „Hallo Orb."

Kein `pip install`, kein `npm install`, kein `python main.py`, kein
manuelles Starten von Ollama oder Backend, keine Kommandozeile.

## Phase 62 – Entwicklungsregel

Jeder Bestandteil beantwortet die neun Fragen: Wie wird er installiert
(mitgeliefert oder über die Runtime), welche Runtime braucht er
(mitgeliefert), welche Dateien (im Paket), wie wird er gestartet (Launcher),
wie geprüft (Health Check), wie beendet (`Supervisor.stop_all`), wie
aktualisiert (Update ersetzt den Programmordner), wie deinstalliert
(Uninstaller), wie ein Fehler behandelt (Crash Recovery).

## Phase 63 – Absolutes Endergebnis

AI-Orb sieht für den Benutzer aus wie eine gewöhnliche
Windows-Anwendung. Er muss nichts über Python, Node, Electron, pip, npm,
virtuelle Umgebungen, Backend-Prozesse, Ports, Ollama, lokale Modelle oder
Abhängigkeiten wissen.

Ein Download. Eine Installation. Ein Startmenü-Icon. Ein Klick. AI-Orb
läuft.
