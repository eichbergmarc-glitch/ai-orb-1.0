# AI-Orb auf dem iPad

Dieses Dokument beschreibt, wie der Orb auf dem iPad benutzbar wird, warum
der Weg so und nicht anders gewählt ist und wo seine Grenzen liegen.

## Die Ausgangslage

Der Orb ist ein Programm für Windows. Sein Backend ist Python, es lädt
Sprachmodelle über Ollama, hört mit Whisper zu, spricht mit Kokoro und
steuert den Desktop. Nichts davon läuft auf einem iPad, und nichts davon
kann dorthin umziehen: iOS erlaubt weder eigene Prozesse im Hintergrund
noch den Zugriff auf fremde Programme und Dateien.

Das ist keine schlechte Nachricht, sondern eine klare. Der Orb besteht seit
jeher aus zwei getrennten Prozessen, die ausschließlich über HTTP
miteinander reden – der Kern auf `127.0.0.1:8756`, die Oberfläche außen
herum (siehe `docs/ARCHITECTURE.md`, Abschnitt „Die Brücke zur
Oberfläche"). Genau diese Trennung wird hier ausgenutzt: Der Kern bleibt
unverändert auf dem PC, und das iPad bekommt eine zweite Oberfläche, die
über dieselbe dokumentierte API spricht.

Der Desktop-Orb läuft dabei weiter. iPad und Desktop sind zwei Fenster auf
denselben Orb, nicht zwei Orbs.

## Was hinzugekommen ist

Fünf Dinge, alle additiv. Am bestehenden Orb wurde keine Zeile geändert.

`ipad/orb_ipad_server.py` ist die Brücke. Sie liefert die Oberfläche aus,
reicht `/api/…` unverändert an das Backend weiter, hält den
Server-Sent-Events-Kanal offen und lässt niemanden ohne Schlüssel durch.
Sie benutzt ausschließlich die Standardbibliothek und liest Host und Port
des Backends aus `config.yaml` – keine hartkodierten Werte, wie im ganzen
Projekt.

`ipad/web/index.html` ist die Oberfläche selbst: eine einzige Datei mit dem
Orb als WebGL-Shader, dem Gesprächsverlauf, dem Eingabefeld und der
Sprachbedienung. Sie lädt nichts aus dem Netz nach.

`ipad/qr.py` erzeugt den QR-Code, der beim Start im Fenster steht – damit
die lange Adresse samt Schlüssel nicht auf dem iPad abgetippt werden muss.
Auch das ohne fremde Pakete, nur Standardbibliothek.

`ORB-IPAD.bat` macht die Einrichtung von selbst: Es prüft Python, prüft das
Backend, installiert Tailscale falls nötig, meldet dich an, gibt den Port im
Tailnet frei und startet die Brücke.

`ipad/orb_ipad_dienst.py` und `IPAD-DAUERHAFT.bat` machen daraus einen
Dauerzustand: Die Brücke startet dann bei der Anmeldung mit und wartet auf
den Orb. Siehe den Abschnitt „Dauerhaft, ohne jedes Mal etwas zu starten".

`ipad/token.txt` entsteht beim ersten Start und enthält den Zugangsschlüssel.

## Einrichtung

**Auf dem iPad:** Tailscale aus dem App Store laden und mit deinem Konto
anmelden. Das ist der einzige Schritt, der dort von Hand nötig ist.

**Auf dem PC:** Den Orb starten wie immer, danach `ORB-IPAD.bat`
doppelklicken. Das Fenster führt fünf Schritte aus und sagt bei jedem, was
es tut. Fehlt Tailscale, installiert es sich selbst über winget; bist du
noch nicht angemeldet, öffnet sich einmal ein Browserfenster.

Am Ende steht ein QR-Code im Fenster. Halte die Kamera des iPads darauf und
tippe auf den Hinweis, der eingeblendet wird. Safari öffnet den Orb, der
Schlüssel wandert dabei in ein Cookie – ab jetzt genügt die Adresse ohne
Anhängsel. Wer lieber tippt: Die Adresse steht direkt unter dem Code.

**Zuletzt auf den Home-Bildschirm legen.** In Safari auf *Teilen* → *Zum
Home-Bildschirm*. Der Orb bekommt ein eigenes Symbol, startet im Vollbild,
ohne Adressleiste, ohne Safari-Rahmen. Von außen ist er von einer App nicht
zu unterscheiden.

Ab dann ist der tägliche Start: PC an, Orb starten, `ORB-IPAD.bat`, auf dem
iPad das Symbol antippen.

**Wenn `tailscale serve` fehlschlägt**, fehlt fast immer nur ein Haken:
`login.tailscale.com/admin/dns` öffnen und unter „HTTPS Certificates" auf
*Enable*. Das Fenster sagt dir das auch selbst.

## Dauerhaft, ohne jedes Mal etwas zu starten

`ORB-IPAD.bat` ist der Weg fuer den ersten Versuch und fuer den Fall, dass
man zusehen will. Auf Dauer will man das nicht jedes Mal tun. Dafuer gibt
es `IPAD-DAUERHAFT.bat`.

Danach laeuft die Bruecke still im Hintergrund mit, von der Anmeldung an.
Sie wartet auf den Orb: Ist er aus, meldet sie dem iPad "keine Verbindung"
– was zutrifft. Startet der Orb, ist sie schon da. Aus deiner Sicht heisst
das: Orb starten, aufs iPad tippen, fertig.

Der naheliegende Weg waere gewesen, die Bruecke vom Startskript des Orb
aus mit aufzurufen. Der ist bewusst nicht gewaehlt. Er wuerde bedeuten, in
den Start des Orb einzugreifen – und damit koennte ein Fehler in der
Bruecke den Orb selbst am Starten hindern. Das waere ein schlechter
Tausch: Der iPad-Zugang ist eine Annehmlichkeit, der Orb ist die Sache
selbst. So wie es jetzt ist, merkt der Orb von der Bruecke nichts.

Der Begleiter kuemmert sich um das, was sonst jedes Mal anfaellt: Er gibt
den Port im Tailnet frei – mit mehreren Versuchen, weil Tailscale kurz
nach dem Anmelden manchmal noch nicht so weit ist –, er startet die
Bruecke neu, falls sie abstuerzt, und er zieht sich zurueck, wenn schon
eine laeuft. Was er tut, steht in `logs\ipad-bruecke.log`.

Nachsehen, wie es steht:

    python ipad\orb_ipad_dienst.py --zustand

Das zeigt in vier Zeilen, ob der Orb laeuft, ob die Bruecke laeuft, wie
der Rechner im Tailnet heisst und ob der Mitstart eingerichtet ist.

Zurueckgenommen wird es mit derselben Datei, Punkt 2 – oder von Hand mit
`python ipad\orb_ipad_dienst.py --entfernen`.

## Warum HTTPS nicht verhandelbar ist

iOS gibt das Mikrofon nur an Seiten frei, die über HTTPS geladen wurden.
Über eine nackte IP-Adresse im WLAN – `http://192.168.…` – bleibt das
Mikrofon stumm, ohne Fehlermeldung, ohne Nachfrage. Deshalb der Umweg über
Tailscale: `tailscale serve` stellt ein echtes Zertifikat aus, ohne dass du
dich um Zertifikate kümmern musst, und die Adresse bleibt trotzdem privat.

Wenn du den Orb nur zum Tippen brauchst und im selben WLAN bleibst, geht es
auch ohne. Dann startest du die Brücke von Hand:

    python ipad\orb_ipad_server.py --offen

Das Fenster nennt dir die WLAN-Adresse. Mikrofon und „Zum Home-Bildschirm"
funktionieren so allerdings nur eingeschränkt.

## Stimme und Gehör auf dem iPad

Whisper und Kokoro bleiben, wo sie sind: auf dem PC, für den Desktop-Orb.
Das iPad benutzt stattdessen seine eigene Spracherkennung und seine eigene
Sprachausgabe.

Das ist nicht nur der bequemere Weg, sondern der bessere. Die
Bestandsaufnahme vom 17.08. hat als größte Schwachstelle das Hören
ausgewiesen – Median 8,3 Sekunden, und 60 bis 95 Prozent aller
transkribierten Äußerungen waren am Ende wegzuwerfen. Beides entfällt hier
von selbst: Die Erkennung des iPads läuft auf dem Gerät, in Bruchteilen
einer Sekunde, und sie hört nur zu, wenn du das Mikrofon antippst. Der
Orb verarbeitet damit genau das, was du gesagt hast, und sonst nichts.

Unter *Einstellungen* lässt sich das Vorlesen abschalten und der
freihändige Betrieb einschalten – dann hört der Orb nach jeder Antwort von
selbst weiter zu.

Ein Hinweis zur Eigenart von iOS: Die Sprachausgabe wird erst nach der
ersten Berührung des Bildschirms freigegeben. Die Oberfläche stößt sie
deshalb bei deiner ersten Eingabe einmal stumm an. Beim allerersten Start
kann die erste Antwort daher stumm bleiben; ab der zweiten spricht er.

## Was der Orb auf dem iPad kann und was nicht

Er kann alles, was über die API läuft: fragen und antworten, Projekte,
Aufgaben, Ziele, Gedächtnis, Agenten, Skills. Der Zustand des Orb – denkt,
spricht, wartet, Fehler – kommt über den Ereigniskanal an und ist an der
Farbe und der Bewegung der Kugel abzulesen, genau wie auf dem Desktop.

Er kann nicht, was den PC selbst betrifft: Programme starten, Fenster
verschieben, den Bildschirm auswerten, Dateien öffnen. Diese Fähigkeiten
liegen in der Desktop-Schicht und ergeben auf einem iPad keinen Sinn.

Und er braucht den PC. Ist der Rechner aus, ist der Orb nicht erreichbar –
das iPad zeigt dann „keine Verbindung" und wartet.

## Sicherheit

Die Brücke lauscht standardmäßig nur auf `127.0.0.1`. Erreichbar wird sie
allein durch `tailscale serve`, also innerhalb deines eigenen Tailnets. Wer
nicht in deinem Tailnet ist, sieht nichts – es ist kein Port im Router
geöffnet, es gibt keinen Eintrag im offenen DNS.

Zusätzlich verlangt jede Anfrage den Schlüssel aus `ipad/token.txt`. Auch
ein anderes Gerät in deinem Tailnet kommt ohne ihn nicht durch. Willst du
den Zugang zurückziehen, lösche die Datei und starte die Brücke neu; es
entsteht ein neuer Schlüssel, und das iPad muss die Adresse einmal mit dem
neuen `?key=` aufrufen.

`ipad/token.txt` gehört in `.gitignore`.

## Wenn etwas nicht geht

Zeigt das iPad *keine Verbindung*, läuft entweder der Orb nicht oder die
Brücke nicht. `ORB-IPAD.bat` sagt dir im ersten Schritt, welches von
beidem.

Kommt eine leere Seite oder „kein gültiger Schlüssel", fehlt das Cookie.
Ruf die Adresse einmal mit `?key=…` auf.

Reagiert das Mikrofon nicht, prüfe zuerst, ob die Adresse mit `https://`
beginnt. Danach in den iPad-Einstellungen unter *Safari* → *Mikrofon* die
Freigabe erlauben.

Bleibt der Orb dunkel und der Rest der Oberfläche ist da, kann die WebGL-
Ausgabe geblockt sein. Dann hilft ein Neustart von Safari; die Bedienung
funktioniert auch ohne Bild weiter.

## Und die native App?

Eine echte iOS-App braucht einen Mac mit Xcode und ein
Apple-Entwicklerkonto; ohne beides lässt Apple keine eigene App aufs iPad.
Der Gewinn gegenüber dem hier beschriebenen Weg wäre überschaubar: eine
native App könnte im Hintergrund weiterhören, ein Weckwort erkennen und
Mitteilungen schicken. Alles andere kann diese Oberfläche schon.

Sollte einmal ein Mac verfügbar sein, ist der Schritt klein: Die Oberfläche
läuft dann unverändert in einem `WKWebView`, und nur die Sprachbedienung
wird gegen `SFSpeechRecognizer` und `AVSpeechSynthesizer` getauscht.
