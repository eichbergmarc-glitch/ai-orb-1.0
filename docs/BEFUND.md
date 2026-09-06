# Befund vom 3. September 2026 — Vorlesungen

Untersucht wurde der Stand deines Rechners, wie er am 26.08.2026 in Drive
liegt: `backend/studium/vorlesungs_session.py` (26.08., 19:40) zusammen mit
`data/vorlesung.json` und den Protokollen desselben Laufs.

## Was in der Datei steht — und was daraus folgt

In `data/vorlesung.json` steht dein Auftrag vom 26.08. und daneben, was der
Orb daraus gemacht hat:

```
auftrag : "ich möchte gerne dass du mir die einführungsvorlesung über die
           geschichtswissenschaft hältst und zwar über das mittelalter"
thema   : "die geschichtswissenschaft haeltst und zwar ueber das mittelalter"
```

Und der Auszug des letzten Abschnitts handelt von **Ägypten, dem Pharao und
der Maat** — nicht vom Mittelalter. Zwei Abschnitte lang hat der Orb eine
allgemeine Einführung in die Geschichtswissenschaft gehalten und bei den
Hochkulturen begonnen.

Das ist kein Zufall und keine Laune des Sprachmodells. Es sind drei Fehler
in der Themenerkennung, die zusammenfallen:

1. **Das Verb der Bitte bleibt im Thema stehen.** Die Erkennung schneidet
   den Satz hinter „Vorlesung über“ ab und trennt danach nur an einer kurzen
   Liste von Wörtern (`mach`, `fahre`, `halte`, `bis`, `ohne`). „hältst“
   steht nicht darin — also bleibt es im Thema.
2. **Die Einengung geht verloren.** „und zwar über das Mittelalter“ wird
   nicht als Präzisierung erkannt, sondern als Teil desselben Wortbreis.
3. **Die Umlaute sind weg.** Die Erkennung arbeitet auf dem normalisierten
   Text. Aus „Französische Revolution“ wird „franzoesische revolution“ — und
   genau dieser Text steht danach im Auftrag an das Sprachmodell.

## Der Fehler, den du gemeldet hast

> „der orb kann keine neue vorlesung beginnen er knüpft einfach dort an wo
> er war“

Die Ursache steht in `befehl()`. Damit ein Satz überhaupt als Beginn einer
Vorlesung gilt, muss er entweder mit einem Befehlswort anfangen
(`halte`, `starte`, `beginne`, `mach`, `gib`, `gestalte`) oder eine von
genau drei Wendungen enthalten: „ich möchte“, „ich will“, „bitte“.

Ich habe zwanzig Sätze durchgerechnet, mit denen ein Mensch eine Vorlesung
verlangt. **Zehn davon erkennt der heutige Stand nicht.** Sie fallen durch
und laufen als gewöhnliche Frage weiter — mit dem gesamten bisherigen
Vorlesungsverlauf im Gespräch. Das Sprachmodell tut dann genau das, was
naheliegt: Es macht weiter.

Nicht erkannt werden unter anderem:

```
Ich hätte gerne eine Vorlesung über Astrophysik
Kannst du mir eine Vorlesung über Kant halten?
Lass uns eine Vorlesung über Statistik machen
Neue Vorlesung über Thermodynamik
Wir machen jetzt eine Vorlesung über römisches Recht
Halte mir bitte einen Vortrag über Immanuel Kant
```

Bemerkenswert: **„Neue Vorlesung“ ist im ganzen Programmtext kein Begriff.**
Es gibt keine einzige Stelle, die das Wort „neu“ auswertet.

## Der Fehler in die andere Richtung

Vier Sätze ohne jeden Vorlesungsbezug lösen heute eine Vorlesung aus, weil
die lose Regel `fahr…fort` / `mach…weiter` das Wort „Vorlesung“ gar nicht
verlangt:

```
Fahre mit dem Programm fort      -> fortsetzen
Mach mit der Datei weiter        -> fortsetzen
Ich mache das später weiter      -> fortsetzen
Mach das Licht aus und dann weiter -> fortsetzen
```

## Der dritte Befund: abgebrochene Vorlesungen

`logs/backend_studium_vorlesungs_session.log` zeigt sechsmal denselben
Abbruch:

```
Vorlesung pausiert: Die Modellantwort war kein brauchbarer Abschnitt
  ('Diese Aktion kann nicht rückgängig gemacht werden. Soll ich sie
    wirklich ausführen?')
  ('Ich habe nicht erkannt, welches Programm beendet werden soll.')
  ('Das Tagebuch ist aufgeschlagen (2 Eintraege, …)')
```

Der Auftrag für einen Vorlesungsabschnitt läuft durch denselben Weg wie
jede andere Frage — einschließlich Werkzeugen und Rückfragen. Antwortet
dieser Weg mit einer Rückfrage oder einem Werkzeugergebnis, ist das kein
Abschnitt, und die Vorlesung pausiert. Dass sie pausiert statt Unsinn zu
speichern, ist richtig; dass es überhaupt passieren kann, ist der Fehler.
**Das ist noch nicht behoben** — es sitzt in der Sprachpipeline, nicht in
diesem Modul. Der Prüfstand meldet es, sobald es wieder auftritt.

## Messung: vorher / nachher

61 Sätze, davon 24 mit erwartetem Thema:

|                                   | heute | nach der Reparatur |
|-----------------------------------|-------|--------------------|
| Befehl falsch erkannt             | 24    | **0**              |
| Thema falsch erkannt              | 24    | **0**              |

Der Satz vom 26.08. ergibt danach:

```
befehl : start
thema  : 'Geschichtswissenschaft, Schwerpunkt Mittelalter'
```
