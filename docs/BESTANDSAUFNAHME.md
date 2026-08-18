# Bestandsaufnahme: Warum der Orb schlechter wirkt - und was zu tun ist

Stand 17.08.2026, abends. Grundlage sind ausschliesslich die Messwerte und
Protokolle deines Rechners vom 14. bis 17.08. - kein Eindruck, keine
Vermutung.

---

## 1. Der Befund in Zahlen

Aus dem Laufzeitprotokoll (`TURN_LATENCY`), Median je Tag:

| Tag    | beantwortet | Hören (s) | Denken (s) | gesamt (s) | ignorierte Äußerungen |
|--------|------------:|----------:|-----------:|-----------:|----------------------:|
| 14.08. | 46          | 5,4       | 9,8        | 31,7       | 600 von 646 (93 %)    |
| 15.08. | 51          | 4,8       | 3,6        | 42,3       | 127 von 178 (71 %)    |
| 16.08. | 10          | 6,8       | 4,4        | 45,9       | 180 von 190 (95 %)    |
| 17.08. | 24          | 8,3       | 1,3        | 46,3       | 36 von 60 (60 %)      |

Drei Dinge springen heraus, und sie decken sich genau mit deinem Eindruck:

**Erstens: Das Ohr ist das Problem, nicht der Kopf.** Das Denken ist
schnell geworden (9,8 → 1,3 s). Das Hören ist langsamer geworden
(5,4 → 8,3 s) - und das ist der Teil, den du bei JEDER Frage wartest.

**Zweitens: Der Orb verarbeitet fast nur Müll.** An jedem Tag waren
60-95 % aller Äußerungen, die er voll transkribiert hat, am Ende
wegzuwerfen: eigene Lautsprecherstimme, Fernseher, Gesprächsfetzen,
abgelaufene Fenster. Jede davon kostete 5-8 Sekunden Rechenzeit - Zeit,
in der DEINE Sätze in der Schlange standen. Das ist die Wurzel von
„er hört nicht richtig zu": Er hört zu viel und kommt nicht dazu,
das Richtige zu verstehen. (Der schlimmste Fall stand am 17.08. im
Protokoll: Dein klar verstandener Satz wartete 194 Sekunden.)

**Drittens: Die Antworten wurden insgesamt langsamer** (31,7 → 46,3 s).
Ein Teil davon ist gewollt (die Suche liefert jetzt wirklich etwas statt
in zwei Sekunden mit 403 zu scheitern), ein Teil ist Sprechzeit - und ein
Teil ist von mir eingebaute Vorab-Maschinerie, die bei jeder passenden
Frage läuft, ob sie gebraucht wird oder nicht.

## 2. Die Schwachstellen, nach Gewicht geordnet

**S1 - Das Hören (grösster Hebel).** Whisper transkribiert alles, was das
Mikrofon liefert, in voller Qualität - auch das, was danach verworfen
wird. Die Erkennung wurde über die Tage langsamer statt schneller. Die
Riegel von heute (Verfall, Einer-nach-dem-anderen, kleines Modell während
der Ausgabe) sind drin, aber noch nicht unter Last gemessen. Dazu kommen
die Verhörer („gefattet mit Indian-Kritten" statt deiner Nachrichtenfrage):
Aus einem falsch verstandenen Satz wird eine falsch verstandene Aufgabe.

**S2 - Reden statt handeln.** Belegt vom 17.08., 21:36: Du gibst im
Textfeld einen klaren Auftrag (nach Markus Gabriel suchen, sein Wissen
einarbeiten). Das Werkzeug dafür existiert (`wissen_aneignen`). Das Modell
sucht einmal, erklärt dann, was es alles nicht kann - und auf dein
„ja, mach das" behauptet es, du hättest nie eine Aufgabe genannt. Die
bewährte Antwort darauf ist im Orb schon zweimal verbaut (Suche,
Bildschirm): Wo die Entscheidung feststeht, wird nicht das Modell
überredet, sondern der Ablauf führt das Werkzeug selbst aus.

**S3 - Tote Maschinerie kostet lebendige Zeit.** Die fünf gesperrten
Suchmaschinen (Bing, Mojeek, zweimal DuckDuckGo, Ecosia) werden bei jedem
Fehlschlag der offenen Quellen immer noch alle durchprobiert - 40
Warnungen allein am 17.08., jede Runde mehrere Sekunden, Erfolgsquote
seit Tagen null. Dasselbe Muster an kleineren Stellen: Vorab-Läufe, die
Kontext aufblähen (19-20k Zeichen je Anfrage), Nachrichtenrunden über
sechs Häuser, wo zwei gereicht hätten.

**S4 - Wortlisten als Weichen.** Ob gesucht, gehandelt, erinnert wird,
entscheiden inzwischen mehrere Stichwortlisten (braucht_aktuelles,
braucht_werkzeuge, Nachrichten, eigenes Umfeld, Füllwörter …). Jede hat
ihren Grund und ihre Tests - aber zusammen bilden sie ein Geflecht, in dem
eine ungewöhnliche Formulierung falsch abbiegt. Das ist die Quelle von
„versteht die Aufgabe falsch", wenn der Satz korrekt transkribiert wurde.

**S5 - Der Professor ist noch Kulisse.** Lehrplan, Themenwissen,
Karteikarten existieren und laufen nachts - aber im Gespräch greift das
Modell selten sicher darauf zu (S2 ist ein Beispiel). Nützlich als
Professor wird der Orb erst, wenn Wissensaufträge zuverlässig im
Speicher landen und Antworten daraus belegt schöpfen.

## 3. Der Plan - in Stufen, jede messbar

Jede Stufe hat ein Messziel. Ohne Messung keine Behauptung - dafür liegt
ab jetzt `ZEUGNIS.bat` im Ordner: Es druckt die Tabelle aus Abschnitt 1
für jeden beliebigen Tag. Vor und nach jeder Stufe einmal laufen lassen,
dann sehen wir schwarz auf weiss, ob sie hält, was sie verspricht.

**Stufe 1 - Das Ohr entlasten** (Ziel: Hören-Median unter 3 s, ignorierte
Transkriptionen um mindestens die Hälfte runter). Die heutigen Riegel
unter Last messen. Dann: Äußerungen, die das Mikrofon während der
Sprachausgabe aufnimmt, gar nicht erst voll transkribieren (nur das
Stop-Fenster); sehr kurze/leise Schnipsel vorab verwerfen; prüfen, ob die
Stimmprüfung (die vor der Erkennung läuft und Millisekunden kostet)
konsequent alles Fremde aussortiert.

**Stufe 2 - Handeln statt reden** (Ziel: ein klarer Auftrag führt in
100 % der Testfälle zum Werkzeuglauf). Den Wissensauftrag („eigne dir X
an", „merke dir das Wissen über X") als festen Ablauf verdrahten wie
Suche und Bildschirm: Der Orb startet die Einarbeitung selbst, im
Hintergrund, und sagt ehrlich zu, statt abzulehnen oder zu vergessen.
Danach dieselbe Behandlung für die übrigen wiederkehrenden Auftragsarten.

**Stufe 3 - Totes abschalten** (Ziel: Fehlschlag-Fall der Suche unter
3 s statt 10+). Die fünf gesperrten Suchmaschinen fliegen aus der Kette -
sie haben seit Tagen keinen einzigen Treffer geliefert. Nachrichtenrunde
auf die Häuser begrenzen, deren Feed antwortet. Vorab-Kontext deckeln.

**Stufe 4 - Die Weichen zusammenlegen** (Ziel: EIN geprüfter Router
statt verteilter Wortlisten, gleiche Trefferquote in den bestehenden
Tests). Erst jetzt, mit Messgerüst - vorher wäre das ein Blindumbau.

**Stufe 5 - Der Professor** (Ziel: Auf eine Fachfrage antwortet der Orb
belegt aus dem eigenen Themenwissen, und ein Wissensauftrag von heute ist
morgen abrufbar). Baut auf Stufe 2 auf.

## 4. Was ich NICHT mehr tue

Keine neue Fähigkeit, bevor die Stufen 1-3 gemessen bestanden sind. Die
Hälfte der heutigen Trägheit ist die Summe gut gemeinter Zusätze - der
Weg zurück zu „schnell und nützlich" führt über Weglassen und Messen,
nicht über die nächste Schicht.
