# Der Hänger bei der Suche

## Was los war

Die Websuche in `backend/tools/web_tools.py` hatte kein Gesamt-Zeitlimit.
Sie hatte nur Einzelfristen, und die addierten sich.

`search_web` versuchte die Zugänge nacheinander: für jede Suchmaschine
jede Anfragevariante, jede mit zwölf Sekunden Geduld. Bei zwei Maschinen
und zwei Varianten sind das achtundvierzig Sekunden, bevor die Funktion
aufgibt. Davor liefen noch bis zu acht Sekunden für die offenen Quellen.

Darüber liegt `mehrquellensuche`. Sie ruft `search_web` **einmal je Haus**
auf, vier gleichzeitig. Bei acht Häusern sind das zwei Runden – also im
schlechten Fall über zwei Minuten, in denen der Benutzer eine stumme Kugel
ansieht. Genau das ist der Hänger.

## Die Stelle, an der es nicht nur langsam war

Eine Zeile war schlimmer als langsam:

```python
raw = response.read()
```

Ohne Größenangabe liest das, solange die Gegenseite sendet. Und das
Zeitlimit von `urlopen` gilt **je Datenpaket**, nicht für die ganze
Übertragung. Eine Gegenstelle, die alle zwei Sekunden ein Byte schickt,
verletzt damit formal nie eine Frist – und hält den Faden beliebig lange
fest. Kein Zeitlimit greift dort, weil ja nie etwas ausbleibt.

Das ist kein erfundener Fall. Genau so verhalten sich Hotspot-
Anmeldeseiten, überlastete Zwischenspeicher und Sperrseiten, die eine
Verbindung offen halten, statt sie zu schließen.

Nachgestellt und gemessen: Mit einer solchen Gegenstelle lief die Suche
nach 45 Sekunden noch immer, ohne dass ein Ende absehbar war.

## Was geändert wurde

Zwei Funktionen, sonst nichts.

**`_fetch`** bekommt eine Frist für die *gesamte* Übertragung und eine
Obergrenze für ihre Größe. Gelesen wird jetzt mit `read1` statt `read` –
`read` kehrt erst zurück, wenn die verlangte Menge beisammen ist, und
genau deshalb kam die Fristprüfung vorher nie an die Reihe.

**`search_web`** bekommt ein Gesamtbudget und fragt die Suchmaschinen
gleichzeitig statt nacheinander. Nacheinander war hier nie ein Gewinn: Die
Maschinen wissen nichts voneinander, und keine wird besser dadurch, dass
eine andere vorher gescheitert ist.

Die Rangfolge der Maschinen bleibt erhalten – aber nicht um jeden Preis.
Hängt die erste und antwortet die zweite sofort, wäre es unsinnig, die
fertige Antwort zurückzuhalten. Deshalb die *Rangfrist*: Sobald eine
Maschine etwas Brauchbares hat, bekommen die besser platzierten noch zwei
Komma fünf Sekunden, und dann wird geliefert, was da ist.

Weil `search_web` unter allen anderen Suchwegen liegt – `mehrquellensuche`,
`favoriten_suche`, die Suchmasken der Fachportale –, wirkt die Grenze
überall, ohne dass dort etwas geändert werden musste.

## Gemessen

Zwei Suchmaschinen, nachgestellt: eine, die tropft, und eine, die gar
nicht antwortet.

| Fall | vorher | nachher |
|---|---|---|
| beide antworten | 0,2 s | 0,2 s |
| die erstplatzierte hängt | nach 45 s abgebrochen, kein Ende absehbar | 2,7 s |
| die zweitplatzierte hängt | 0,2 s | 0,2 s |
| beide hängen | nach 45 s abgebrochen, kein Ende absehbar | 8,2 s, dann ein ehrlicher Suchfehler |

Der gute Fall wird nicht langsamer. Der schlechte Fall hört auf, ein
Hänger zu sein.

## Die drei Zahlen

Sie stehen als Konstanten über `_fetch` und lassen sich dort ändern.

`_ANFRAGE_ZEITLIMIT = 8.0` – wie lange *eine* Netzanfrage dauern darf.
Zwölf waren zu großzügig; was eine Suchmaschine nach acht Sekunden nicht
geliefert hat, liefert sie meist gar nicht.

`_ANTWORT_HOECHSTENS = 3_000_000` – wie groß eine Antwort höchstens sein
darf. Eine Suchtrefferseite liegt bei einigen hunderttausend Zeichen; drei
Millionen sind reichlich Luft und trotzdem eine Grenze.

`_SUCH_GESAMTBUDGET = 20.0` – die eigentliche Zusage an den Benutzer: Nach
dieser Zeit kommt eine Antwort, notfalls die, dass nichts zu finden war.

## Einspielen

`SUCHE-BESCHLEUNIGEN.bat` doppelklicken. Es prüft zuerst und fragt dann
nach, bevor es etwas ändert. Von Hand geht es auch:

    python werkzeug\suche_beschleunigen.py --pruefen
    python werkzeug\suche_beschleunigen.py
    python werkzeug\suche_beschleunigen.py --rueckgaengig

Vor der Änderung entsteht `backend\tools\web_tools.py.vor-zeitbudget`.
Nach der Änderung wird die Datei neu eingelesen; misslingt das, wird die
Sicherung sofort zurückgespielt – es kann nichts halb geändert
zurückbleiben. Der Orb muss neu gestartet werden, damit es wirkt.

Nachmessen mit `python werkzeug\suche_zeitprobe.py`. Am besten einmal
vorher und einmal nachher.

## Was damit *nicht* behoben ist

Die Trefferqualität. Wenn Bing und Yahoo abweisen und die offenen Quellen
nichts Passendes haben, kommt weiterhin nichts – nur eben schnell und mit
einer Begründung statt nach einer Minute Stille. Woran es im Einzelfall
liegt, zeigt `SUCHE-PRUEFEN.bat`: Es fragt jede Quelle einzeln und nennt
den Grund im Klartext.

Ebenfalls unberührt: `offene_quellen.py`. Das Modul hat sein eigenes
Budget von acht Sekunden und fragt seine Quellen bereits gleichzeitig –
dort war der Hänger nicht.
