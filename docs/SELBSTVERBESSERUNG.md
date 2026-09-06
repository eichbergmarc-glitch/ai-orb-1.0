# Selbstverbesserung

## Was schon da war

Der Orb hat die Selbstverbesserung vollständig: fünfzehn Module in
`backend/evolution`. Codeanalyse, Architekturprüfung, Fehlersuche in den
Protokollen, Ideengenerator, Patchbau in einer Arbeitskopie, Testlauf,
Review, Risikobewertung, Freigabe, Rücknahme. Dazu die vier Endpunkte in
der API: `analyze`, `report`, `apply`, `undo`.

Alles gebaut, alles benutzbar – und nie benutzt.

## Was gefehlt hat

Das Einfachste: **Niemand hat es je aufgerufen.** `EvolutionEngine.analyze()`
wird an keiner Stelle des Orb gerufen. Es gab keinen Zeitplan, keinen
Auslöser, keinen Knopf. Die Maschine stand, weil niemand den Schlüssel
gedreht hat.

Und es gab keinen Ort, an dem man einen Vorschlag hätte annehmen können.
`POST /evolution/apply` verlangt `{"confirmed": true}` – aber es gab keine
Oberfläche, die das schickt.

Zwei Teile also, sonst nichts:

`werkzeug/selbstverbesserung.py` dreht den Schlüssel. Einmal pro Nacht.

`ipad/web/vorschlaege.html` ist der Ort für die Entscheidung. Auf dem iPad,
mit einem Tippen.

## Der Nachtlauf

Um drei Uhr nachts läuft die Selbstanalyse. Der Ideengenerator liefert
mehr, als sich in einer Nacht abarbeiten lässt; die Reihenfolge entscheidet
deshalb, ob der Lauf nützt. Sie ist: **Fehler, Leistung, Tests,
Dokumentation.**

Fehler zuerst, weil das echte Probleme aus dem Betrieb sind statt
vermuteter – der `bug_detector` liest die Protokolle. Dokumentation zuletzt,
weil sie risikoarm ist und sich gut als Prüfstein eignet: Wenn die
Vorschläge dort schon nicht taugen, taugen sie anderswo erst recht nicht.

Diese Reihenfolge überstimmt die Bewertung des Ideengenerators. Eine
hochbewertete Dokumentationsidee kommt nach einer niedrig bewerteten
Fehleridee.

Drei eigene Grenzen setzt der Lauf:

Ein **Zeitbudget** von 45 Minuten. Ein Nachtlauf, der bis zum Mittag
rechnet, ist keiner.

**Höchstens drei Patches je Nacht.** Zehn Vorschläge, die niemand liest,
sind schlechter als zwei, die jemand liest.

Und er **übernimmt nichts**. Gearbeitet wird ausschließlich in der
Arbeitskopie; an den produktiven Dateien ändert der Lauf nichts. Nie.

## Die Freigabe

Auf dem iPad unter *Einstellungen → Vorschläge des Orb*. Je Patch stehen
dort: was er tut, warum, das Testergebnis, das Review, das Risiko, die
gemessene Wirkung – und was der Review offengelassen hat. Ein Tippen auf
*Übernehmen* schickt `confirmed: true`, ein Tippen auf *Letzte Übernahme
rückgängig* dreht es zurück.

Die Unsicherheiten stehen bewusst mit dabei. Ein Patch, bei dem der Review
anmerkt „zwei Tests decken den Fall nur mittelbar ab", ist etwas anderes
als einer ohne Anmerkung, auch wenn beide grün sind.

## Wie aus einer Idee Code wird

Der erste Nachtlauf hat gezeigt, woran es hing: Alle elf Ideen des
Ideengenerators waren Beschreibungen ohne Codeänderung, und die Hälfte
nannte nicht einmal eine Datei. „Wartbarkeit der Architektur verbessern"
lässt sich nicht patchen; „159 überlange Funktionen aufteilen" auch nicht,
weil es eine Sammlung ist und kein Ort.

`werkzeug/patchschmied.py` schließt die Lücke. Er sucht seine Ziele selbst,
und zwar solche, die einen Ort haben:

**Aus den Protokollen.** Wiederkehrende Ausnahmen mit Rückverfolgung. Der
letzte Rahmen innerhalb des Projekts sagt, welche Datei und welche Funktion
es angeht. Eine Fehlermeldung ohne Rückverfolgung nennt kein Ziel und wird
übergangen – lieber nichts vorschlagen als ins Blaue.

**Aus dem Quelltext.** Funktionen ohne Dokumentation, Funktionen über
achtzig Zeilen. Selbst gesucht über den Syntaxbaum, nicht aus dem
Sammelbefund übernommen.

### Eine Funktion auf einmal

Das Modell bekommt nie eine ganze Datei zu sehen und schreibt nie eine ganze
Datei. Es bekommt genau eine Funktion, das Problem dazu, und liefert genau
diese Funktion zurück. Ersetzt wird über den Syntaxbaum.

Das ist die eigentliche Absicherung, nicht eine Bequemlichkeit. Ein Modell
dieser Größe schreibt zuverlässig Unsinn, sobald es viel auf einmal soll.
Auf eine Funktion begrenzt, lässt sich jede Antwort streng prüfen:

* Ist die Antwort überhaupt gültiges Python?
* Ist es genau eine Funktion – nicht zwei, nicht Fließtext?
* Heißt sie noch so? Hat sie dieselben Parameter?
* Ist sie nicht ins Dreifache gewachsen?
* Ist die Datei danach noch übersetzbar?
* Ist außerhalb dieser einen Funktion wirklich nichts angerührt?

Fällt eine dieser Fragen negativ aus, wird verworfen. **Das ist der
Normalfall, nicht die Ausnahme** – und danach kommen erst die Tests und das
Review der Engine.

Geprüft wurde jede dieser Sperren einzeln: umbenannte Funktion, erfundener
Parameter, zwei Funktionen statt einer, Syntaxfehler, reiner Fließtext,
zweihundert Zeilen Füllwerk. Alle sechs fallen durch. Und der Fall, an dem
sich solche Werkzeuge gern verschlucken – zwei gleichnamige Funktionen in
einer Datei, eine als Methode, eine daneben –, trifft die richtige und lässt
die andere unberührt.

## Was ehrlich dazugehört

Die meisten Antworten des Modells werden verworfen werden. Das ist so
gewollt. Ein Nachtlauf, der von zwanzig Versuchen einen brauchbaren Patch
übriglässt, hat gut gearbeitet – nicht schlecht.

Und: Ein grüner Testlauf heißt nicht, dass eine Änderung gut ist. Er heißt,
dass sie nichts kaputtgemacht hat, was geprüft wird. Genau deshalb liegt
die Entscheidung bei dir und nicht beim Orb.

Der nützlichste erste Schritt ist deshalb nicht mehr Autonomie, sondern
mehr Tests. Schwerpunkt drei im Nachtlauf arbeitet genau daran – und macht
damit das Tor stabiler, durch das alle späteren Patches müssen.

## Zuerst nachsehen, ob es überhaupt Ziele gibt

`SELBSTVERBESSERUNG.bat`, Punkt 0 – oder von Hand:

    python werkzeug\selbstverbesserung.py --ziele

Zwei Sekunden, ohne das Modell zu bemühen. Es zeigt, welche konkreten
Stellen der Patchschmied findet: aus den Protokollen und aus dem Quelltext.
Steht dort nichts aus den Protokollen, fehlen in `logs\*.log` die
Rückverfolgungen – ohne eine Zeile der Form `File "...", line N, in ...`
nennt ein Fehlereintrag keinen Ort, und geraten wird nicht.

Findet er nichts, wäre ein Lauf mit `--patches` umsonst. Findet er etwas,
weißt du vorher, woran gearbeitet wird.

## Warum der Patchschmied zuerst nichts fand

Gebaut war er, gelaufen ist er nie. `--ziele` kam nie zum Ende, und ein
Werkzeug, das nichts findet und nichts sagt, sieht aus wie eines, das
nichts zu tun hat. Vier Ursachen, jede für sich unscheinbar:

**Der Durchlauf ging durch alles.** Gesucht wurde mit `rglob("*.py")` über
den ganzen Ordner, und die Tabu-Liste wurde erst *danach* angewandt. Unter
`runtime` liegt ein vollständiger Python-Unterbau, daneben `node_modules`,
und in `games/nullprotokoll/.tools` ein Godot-Werkzeugkasten mit fast
neuntausend Dateien. Alle wurden eingesammelt, um dann verworfen zu werden.
Jetzt wird beim Gehen abgeschnitten: 310 eigene Dateien statt 8989, unter
einer Sekunde statt Minuten.

**Die Tabu-Liste galt in jeder Tiefe.** Sie meinte die Ordner oben im
Projekt – `audio` mit den Klangproben, `data`, `tests`. Sie traf aber auch
`backend/audio/`. Und dort liegt `audio_capture.py`, der häufigste Fehler
überhaupt: vierzehn Mal „Das Mikrofon konnte nicht geöffnet werden" – genau
der Befund, der im Nachtlauf seit Tagen ganz oben stand und für den es nie
einen Patch gab. Er wurde lautlos übergangen. Jetzt gilt die Liste oben,
und quer durch alle Tiefen nur noch `__pycache__`, `node_modules` und alles,
was mit einem Punkt beginnt.

**Die Pfade in den Protokollen sind Windows-Pfade.** Wer sie mit `Path`
einliest, bekommt anderswo einen einzigen langen Dateinamen. Und selbst
gelesen zeigten sie auf den Ordner, in dem der Fehler *einmal* auftrat –
nicht zwingend auf den, der gerade untersucht wird. Jetzt wird an beiden
Strichen getrennt und der Weg unterhalb des Projektnamens auf die eigene
Wurzel bezogen. Eine Kopie im Projekt (`AI-Orb-iPad`) zählt nicht mit.

**Gleichnamige Methoden belegten alle drei Nachtpatches.** In
`grafik_tools.py` haben drei Klassen je eine Methode `execute`; alle drei
kamen als eigene Ziele. Drei Versuche, eine Datei – und bei gleichnamigen
Funktionen ist die Ersetzung ohnehin der heikelste Fall. Jetzt bleibt je
Datei das stärkste Ziel.

Festgehalten ist das in `tests/backend/test_patchschmied.py`. Die Tests
prüfen nicht, dass der Patchschmied *etwas* findet, sondern dass er genau
diese vier Dinge nicht wieder verliert.

Was jetzt gefunden wird: sieben Ziele aus den Protokollen, angeführt vom
Mikrofonfehler mit vierzehn Vorfällen, dazu `gmail/oauth.py`,
`kalender/client.py`, `system/task_manager.py` und
`tts/supertonic_engine.py`; und fünfzehn aus dem Quelltext.

## Den Lauf aus der Ferne anstoßen

Der Nachtlauf braucht Ollama, und Ollama läuft auf dem Rechner. Wer nicht
davorsitzt, kann keinen Doppelklick machen – aber eine Datei in den Ordner
legen kann auch jemand aus der Ferne. Genau dafür gibt es den Wächter
schon, und er nimmt jetzt einen dritten Auftrag an:

    SELBSTVERBESSERUNG-BITTE.txt      der volle Lauf mit Patches
    SELBSTVERBESSERUNG-BITTE.txt      mit dem Wort "nur-ziele" darin:
                                      nur zeigen, woran gearbeitet würde

Der Lauf startet nebenher. Ein Lauf mit Patches darf drei Viertelstunden
brauchen, und solange soll der Wächter trotzdem auf einen Neustart
reagieren können. Solange einer läuft, wird kein zweiter gestartet;
`WAECHTER-LAEUFT.txt` sagt, ob gerade einer läuft.

Und der Wächter erneuert sich selbst: Ändert sich sein Programm, übergibt
er an die neue Fassung und tritt ab – nur nicht mitten in einem Nachtlauf.
Sonst müsste jemand am Rechner sitzen, um eine Änderung am Wächter wirksam
zu machen, und genau dafür gibt es ihn ja nicht.

Dieses eine Mal geht das noch nicht von selbst, weil die laufende Fassung
die Erneuerung noch nicht kennt: `WAECHTER-ERNEUERN.bat` beendet die alten
Wächter dieses Ordners und startet genau einen neuen. Danach nicht mehr
nötig.

## Einrichten

`SELBSTVERBESSERUNG.bat`. Punkt 1 sieht einmal durch, ohne etwas zu ändern
– ein guter erster Blick darauf, was der Orb über sich selbst weiß. Punkt 3
richtet den Nachtlauf ein, als Aufgabe des angemeldeten Benutzers, ohne
Administratorrechte und ohne Dienst. Läuft der Rechner um drei nicht, holt
Windows die Aufgabe beim nächsten Anmelden nach.

Mitgeschrieben wird nach `logs\selbstverbesserung.log`, der letzte Bericht
liegt als `data\evolution\letzter-lauf.json`, der Verlauf als
`verlauf.jsonl` – damit sich später zeigen lässt, ob die Wartbarkeit über
die Wochen wirklich steigt.
