# Was in diesem Stand behoben wurde

Stand: 7. August 2026, abends · Alle 265 Tests bestehen · Alle Importe auflösbar

Dieses Dokument listet nicht Funktionen auf, sondern Fehler — und was sie
verursacht haben. Es steht hier, weil mehrere davon sich als etwas ganz
anderes zeigten, als sie waren, und das beim nächsten Mal Zeit sparen soll.

## Der Orb war zu groß

**Zu sehen war:** eine große schwarze Scheibe, in deren Mitte ein
pulsierender Punkt in der richtigen Größe saß.

**Tatsächlich:** Der Orb war nie zu groß. Der letzte Renderdurchgang
blendet das Bild zum Rand hin kreisförmig aus und nahm dafür den
Alphakanal als Maß für Durchsichtigkeit. Der stimmt an dieser Stelle
nicht mehr: Sobald das Bild durch den `EffectComposer` läuft, füllt der
Bloom-Durchgang die gesamte Fläche mit voller Deckung. Multipliziert man
das mit einer runden Ausblendung, entsteht genau diese Scheibe — so groß
wie das Fenster, also 520 Pixel.

Die Deckung kommt jetzt aus der Helligkeit. Der Orb leuchtet, der
Hintergrund ist schwarz; der hellste Farbkanal ist damit das ehrlichere
Maß dafür, ob an einer Stelle etwas ist.

*Datei:* `desktop/renderer/effects.ts`

## Der Orb reagierte nicht auf „Hallo Orb"

**Im Protokoll stand:**

    Zustimmung angefragt: voice möchte 'microphone' –
    Dauerhaft auf das Weckwort 'Hallo Orb' hören.

Danach nichts mehr.

**Tatsächlich:** Der Kern fragt vor dem Zugriff aufs Mikrofon um
Erlaubnis, wartet und wertet Schweigen als Nein — so verlangt es die
Sicherheitsvorgabe. Nur hörte niemand zu. Die Frage ging in den
Ereignisbus, die Frist lief ab, und heraus kam ein Nein, das nie jemand
ausgesprochen hatte. Die Spracherkennung war nie kaputt.

Electron fragt den Kern jetzt regelmäßig nach offenen Fragen und stellt
jede als gewöhnliches Windows-Fenster dar. Voreingestellt ist „Ablehnen".

*Dateien:* `desktop/electron/consent.ts` (neu), `desktop/electron/main.ts`

## In der installierten Fassung fand nichts sich selbst

In `main.ts` stand:

    const PROJECT_ROOT = path.resolve(__dirname, "..", "..", "..", "..");

Im Quellordner stimmt das. In der installierten Fassung liegt `main.js`
in `app.asar` — einem Archiv. Vier Ebenen darüber landet man im Archiv
selbst. Von dort gibt es keine `config.yaml`, keinen `runtime`-Ordner und
kein Verzeichnis, in dem ein Prozess starten könnte.

Die Folge waren drei Fehler auf einmal: Der Orb nahm überall
Vorgabewerte statt der Konfiguration, der Python-Kern kam nie hoch, und
ohne Kern gab es kein Weckwort.

Die Pfadauflösung liegt jetzt in einer eigenen Datei, als Gegenstück zu
`backend/utils/paths.py`. Beide Seiten müssen zur selben Antwort kommen.

*Dateien:* `desktop/electron/paths.ts` (neu), `desktop/electron/main.ts`,
`package.json`, `build/installer.nsh`

## Die Startprüfung stürzte in ihrer letzten Zeile ab

`UnicodeEncodeError` beim Zeichen `✓`. Die Windows-Konsole arbeitet mit
`cp1252`; was sich darin nicht abbilden lässt, führt nicht zu einem
Ersatzzeichen, sondern zum Abbruch. Ausgerechnet der Bericht, der melden
soll, dass alles in Ordnung ist, brachte den Aufruf zum Absturz —
nachdem alle Prüfungen längst erfolgreich durchgelaufen waren.

*Datei:* `backend/main.py`

## Der Kern fand sein eigenes Paket nicht

Liegt eine `._pth`-Datei vor, läuft Python im isolierten Modus: Weder das
aktuelle Verzeichnis noch `PYTHONPATH` werden berücksichtigt. Der
Suchpfad steht dann ausschließlich in dieser Datei. `-m backend.main`
wäre unabhängig vom Startverzeichnis gescheitert.

*Dateien:* `scripts/prepare-runtime.ps1`, `desktop/electron/backend_process.ts`

## Der Bau brach ab, ohne den Grund zu nennen

Drei getrennte Ursachen:

`$ErrorActionPreference = "Stop"` macht zusammen mit `2>&1` jede Ausgabe
eines Programms auf der Fehlerausgabe zu einem abbrechenden Fehler. Ein
Import-Test, der fehlschlagen *darf*, beendete damit das ganze Skript.

Die Node.js-Prüfung verließ sich auf `$LASTEXITCODE`. Ruft man ein
Programm auf, das nicht existiert, wird diese Variable nicht gesetzt —
sie behält den Wert des letzten Befehls, der wirklich lief.

Und `installer.nsh` enthielt drei Stellen, die den NSIS-Übersetzer
abbrechen ließen: eine eigene Laufprüfung, die `tasklist` von Hand
zerlegte; ein Autostart-Kästchen, das bereits gesetzte Vorgaben neu
definierte (in NSIS ein Fehler, kein Überschreiben); und `${GetSize}` ohne
das nötige `!insertmacro` und ohne den `un.`-Vorsatz für den
Deinstallationsteil.

Der Autostart steht jetzt im Kontextmenü des Orb — dort, wo man ihn auch
wieder abwählen kann. Ein Kästchen im Installationsprogramm sieht man
genau einmal.

Ausserdem schreibt der Bau jetzt alles mit, in `AI-Orb-Build-Log.txt`.

*Dateien:* `scripts/prepare-runtime.ps1`, `scripts/build-installer.ps1`,
`build/installer.nsh`, `desktop/electron/main.ts`

## Ein gescheiterter Bau blieb unbemerkt

Die Startdatei prüfte nur, *ob* `main.js` existiert. Eine Datei aus einem
geglückten Bau von vorgestern erfüllt diese Bedingung auch dann noch,
wenn der heutige Bau abgestürzt ist. Der Orb startete daraufhin mit altem
Code, und der Übersetzungsfehler blieb unsichtbar.

Der alte Build wird jetzt vor dem Bauen gelöscht, der Rückgabewert von
npm ausgewertet, und bei einem Fehlschlag startet der Orb nicht.

*Datei:* `ORB-STARTEN.bat`

## Der Kern starb an einem aufgelegten Hörer

**Im Protokoll stand:**

    ConnectionAbortedError: [WinError 10053] Eine bestehende Verbindung
    wurde softwaregesteuert durch den Hostcomputer abgebrochen

**Tatsächlich:** Electron fragt den Kern im Sekundentakt nach seinem
Zustand, und jede Frage hat eine Frist. Läuft sie ab, schließt Electron
die Verbindung — der Server schreibt dann in ein totes Rohr.

Das allein wäre harmlos. Der Fehler lag eine Ebene darüber: Der Versand
der Antwort stand mit im `try` des Handlers. Brach die Verbindung beim
Schreiben ab, landete man im `except` und versuchte dort, eine 500 über
*dieselbe tote Leitung* zu schicken. Diese zweite Ausnahme fing niemand
mehr; sie stieg bis in den `socketserver` auf und riss den Kern mit.

Rechnen und Senden sind jetzt getrennt. Ein Verbindungsabbruch gilt als
das, was er ist: ein Umstand, kein Fehler.

*Datei:* `backend/api/http_server.py`

## „Prüfe die Internetverbindung" war geraten

Es gibt keine Internetprüfung. Der Satz war Teil eines vorformulierten
Textes für den Fall, dass gar nichts geht — eine Vermutung, die sich als
Befund ausgab. Wer daraufhin sein Netz prüft, sucht an der falschen
Stelle.

Die Meldung nennt jetzt den Fehler des letzten Versuchs.

*Datei:* `backend/ai/response_pipeline.py`

## Der Grund war ermittelt und trotzdem unsichtbar

Warum Claude Code nicht erreichbar ist, wurde festgestellt, aufgeschrieben
— und auf `debug` protokolliert, während die Anzeige auf `info` steht. Der
Benutzer sah nur „Ich kann kein Sprachmodell erreichen".

Dasselbe Muster war zuvor schon zweimal aufgetreten: beim Bau-Protokoll
und bei der Abbruchmeldung des Kerns. Eine Auskunft, die niemand liest,
ist keine.

Zusätzlich: Die Prüfung rief `claude --version` auf. Das funktioniert auch
ohne Anmeldung — die Startprüfung meldete deshalb „verfügbar", während die
eigentliche Anfrage scheiterte.

*Datei:* `backend/orchestrator/providers/claude_code_provider.py`

## Eine Abbruchmeldung überschrieb ihre eigene Ursache

Starb der Kern, meldete der `exit`-Behandler „Der Kern wurde unerwartet
beendet (Code 1)" — und überschrieb damit genau die Zeile, die den Grund
nannte. Man sah, *dass* etwas schiefging, nie *was*.

Electron sammelt die Fehlerausgabe jetzt, hängt sie an statt sie zu
ersetzen, übersetzt die häufigsten Ausnahmen in einen Rat und schreibt
alles nach `%APPDATA%\AI-Orb\logs\kern-start.log`.

*Datei:* `desktop/electron/backend_process.ts`, `desktop/electron/main.ts`

## Historical Professor & Mentor Engine (neu)

Ein persönlicher akademischer Mentor für Geschichtswissenschaft, umgesetzt
als eigener Agent unter `backend/agents/history_agent/`. Kein Chatbot mit
Professorentonfall: Der Kern ist eine Entscheidung, die *nicht* dem
Sprachmodell überlassen ist – ob überhaupt geantwortet oder sokratisch
zurückgefragt wird. Ein Modell, das gebeten wird, „sokratisch zu lehren",
verfällt nach drei Zügen darauf, die Lösung mitzuliefern; ein Regelwerk
vergisst das nicht.

Enthalten: langfristiges Lernprofil mit Spaced Repetition, sokratischer
Modus, Prüfungssimulation mit adaptiver Schwierigkeit, Forschungsfragen-
Prüfung, Quellenkritik-Raster, Debatte mit Rollenwechsel, Arbeitsbetreuung
über Monate, Anachronismus-Erkennung. 27 eigene Tests.

## Multi-Provider und ModelRouter (neu)

Vier Anbieter ergänzt (OpenAI, Ollama Cloud, LM Studio, llama.cpp) über
einen gemeinsamen OpenAI-kompatiblen Adapter – die bestehende Provider-
Architektur wurde erweitert, nicht ersetzt. Dazu der ModelRouter, der je
Aufgabe wählt: lokal wenn möglich, Cloud wenn nötig, Datenschutz über
allem. Schlüssel kommen ausschließlich aus der Umgebung, nie aus der
Konfiguration. 18 eigene Tests.

## Edge-Favoriten (neu)

Ein Werkzeug, das die Browser-Favoriten liest (Edge, Chrome, Brave,
Vivaldi, Opera) – für Recherchen, weil die über Jahre gesammelten
Favoriten die genaueste Beschreibung der eigenen Quellen sind. Wird nur
gelesen, nie übertragen.

## Gmail-Agent (neu)

Mails lesen, suchen, zusammenfassen, vorlesen, beantworten und senden –
über OAuth2, sodass das Passwort nur bei Google eingegeben wird, nie bei
AI-Orb. Das Zugriffstoken liegt verschlüsselt in den Benutzerdaten,
außerhalb von Git.

Das Herzstück ist die Sendesperre aus Abschnitt 36: „Der Orb darf niemals
ungefragt eine Mail senden." Sie ist nicht als Bitte ans Sprachmodell
umgesetzt, sondern als Ablauf, an dem kein Modell vorbeikommt – Entwurf,
Vorlesen, Bestätigung, senden. Ohne Entwurf kein Senden, ohne kritische
Zustimmung kein Senden, und nach dem Senden sendet ein zweites „ja" nichts
noch einmal. Neun Tests sichern genau das ab, keiner spricht ein echtes
Postfach an. Einrichtung in `docs/GMAIL.md`.

## Unterbrechen per "stop" statt Selbst-Unterbrechung (neu)

Der Orb unterbrach sich selbst: Das Mikrofon hoerte seine eigene Stimme aus
dem Lautsprecher und hielt sie fuer ein Dazwischenreden. Das akustische
Unterbrechen ist deshalb standardmaessig aus. Stattdessen hoert der Orb
waehrend des Sprechens auf das Wort "stop" (auch "stopp", "halt") und haelt
dann sofort an. Weil nur auf diese kurzen, markanten Woerter reagiert wird,
loest die eigene Antwort den Abbruch praktisch nie aus. Geprueft wird auf
ganze Woerter - "halt" schlaegt nicht in "Gehalt" an.

## ElevenLabs-Stimme (neu, optional)

Die authentische Stimme, die du wolltest ("wie Miles"): im Netz erzeugt,
deutlich natuerlicher als die lokalen Stimmen und schneller als das grosse
Piper-Modell. Eine bewusste Wahl, keine Voreinstellung - sie greift nur mit
Schluessel (ELEVENLABS_API_KEY) und gewaehlter Stimme, sonst uebernimmt
weiter Piper. Rohes PCM wird lokal als WAV verpackt, damit kein ffmpeg
noetig ist.

## Fluessigeres Sprechen (neu)

Der Orb erzeugte jeden Satz einzeln nacheinander - rechnen, abspielen,
rechnen, abspielen. Zwischen den Saetzen entstand dabei jedes Mal eine
Luecke. Jetzt wird der naechste Satz vorbereitet, waehrend der aktuelle noch
laeuft; die Luecken verschwinden. Dazu eine schnellere Stimme
(Piper "medium" statt "high") und schnelleres Zuhoeren (Whisper "base" statt
"small").

Zusaetzlich, standardmaessig AUS: ein echter Fluss-Modus
(voice.stream_speech), in dem der Orb den ersten Satz spricht, waehrend er
den Rest noch denkt - denken, sprechen, weiterdenken, weitersprechen. Er
redet dabei direkt mit dem Sprachmodell und laesst die Denkschicht aus (kein
Professor, keine Werkzeuge), deshalb nicht als Vorgabe. Die Streaming-
Grundlage steht im ProviderManager; Ollama streamt nativ.

## Nebel-Kugel ohne sichtbaren Umriss (neu)

Der helle Fresnel-Rand der Huelle zeichnete einen Kreis - den Umriss einer
Kugel. Der ist jetzt umgekehrt: dicht und leuchtend zur Mitte, weich
ausblendend zum Rand, sodass kein Umriss stehen bleibt. Der Orb liest sich
dadurch als dampfender Nebel in Kugelform statt als Ball mit Kante. Die
Farbe wechselt weiterhin mit dem Zustand.

## Programme starten funktioniert (behoben)

"Oeffne den Text-Editor" bewirkte nichts. Zwei Fehler steckten dahinter.

Erstens durchsuchte der Router die Anweisung nur nach Programm-NAMEN, nicht
nach ihren Aliasen. "Editor" ist aber ein Alias von "notepad", und
"notepad" kam im Satz nicht vor - also wurde nichts gefunden. Jetzt werden
Namen UND Aliase durchsucht, und der laengere Treffer gewinnt ("windows
terminal" bleibt nicht am blossen "terminal" haengen).

Zweitens rief das Start-Werkzeug eine Methode, die es nicht gibt
(launch_application statt launch), und scheiterte still mit einem
AttributeError - das sah fuer den Benutzer aus wie "es passiert nichts".
Behoben, mit Tests fuer beide Fehler.

## Begruessung beim Start (neu)

Wenn AI-Orb wirklich einsatzfaehig ist - alle Module geladen, Startpruefung
bestanden, Dienstueberwachung aktiv -, begruesst der Orb dich mit der
Stimme: "Guten Morgen. Ich bin bereit." Der Gruss richtet sich nach der
Tageszeit und kommt bewusst erst NACH dem Bereit-Zustand, nicht vorher.
Abschaltbar und aenderbar unter startup in der config.yaml.

## Neue Hilfsdateien

    ORB-STARTEN.bat   Runtime holen, bauen, starten. Findet den
                      Projektordner selbst, auch in OneDrive.
                      Schreibt AI-Orb-Start-Log.txt.

    DIAGNOSE.bat      Ändert nichts. Schreibt einen Bericht auf den
                      Desktop: Pfade, wirksame Konfiguration, Pakete,
                      Startprüfung, Antwortgeber, Mikrofon, Protokoll.
