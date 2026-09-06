# Der Orb im Betrieb — was die Protokolle sagen

**6. September 2026.** Grundlage: 192 Protokolldateien, 18,3 MB, Zeitraum
14. August bis heute. **6.593 aufgezeichnete Dialogzüge**, davon 694
beantwortet. Kein Befund hier stammt aus dem Quelltext — jeder hat einen
Zeitstempel aus deinem eigenen Betrieb.

---

## Die Lage in Zahlen

| | |
|---|---|
| Aufgezeichnete Dialogzüge | 6.593 |
| Davon beantwortet | 694 (10,5 %) |
| Davon wirklich **gesprochen** | 413 |
| Median vom Redeende bis zum ersten hörbaren Wort | **11,8 s** |
| p90 | 25,0 s |
| Verstandene Äusserungen seit dem 31.08. | 177 |

Der Median hat sich über drei Wochen **nicht verbessert**: 16,0 s am 14.08.,
12,2 s am 31.08., 11,0 s am 02.09. Was in dieser Zeit behoben wurde, hat die
Zahl der unnötigen Züge gesenkt (1.235 am 17.08. gegen 63 heute), nicht die
Wartezeit des Benutzers.

---

## Wo die Zeit hingeht

413 beantwortete und wirklich gesprochene Züge, Abstand zwischen den Marken:

| Stufe | Median | p90 | Anteil |
|---|---|---|---|
| **Sprachausgabe bis hörbar** | **5,67 s** | 18,55 s | **41,5 %** |
| **Erkennung (Redeende → Text)** | **5,05 s** | 9,49 s | **37,0 %** |
| Modell bis erstes Wort | 2,76 s | 8,23 s | 20,2 % |
| Übergabe an den Orchestrator | 0,11 s | 1,63 s | 0,8 % |
| Kontext und Werkzeuge | 0,07 s | 6,25 s | 0,5 % |
| Absicht und Route | 0,00 s | 0,01 s | 0,0 % |

**Die Sprachausgabe ist der grösste Posten** — grösser als das Hören, das
bisher immer im Mittelpunkt stand, und doppelt so gross wie das Denken.
Untersucht wurde sie bisher nicht. Denken, Routen und Werkzeugwahl
zusammen kosten weniger als eine halbe Sekunde; dort ist nichts zu holen.

---

## Die Befunde, nach Gewicht

### 1. Zwei von fünf Antworten werden nie gesprochen

**281 von 694** beantworteten Zügen erreichen `answer_dispatched`, aber nie
`answer_audible`. Der Orb hat gedacht, formuliert, eine Antwort erzeugt — und
der Benutzer hört nichts.

Entscheidend: **nur 4 dieser 281 kamen überhaupt bis zum fertigen Ton.** Der
Abbruch liegt also vor der Sprachsynthese, nicht beim Abspielen.

Das zieht sich gleichmässig durch alle drei Wochen — 15 am 14.08., 38 am
17.08., 33 am 24.08., 22 am 31.08., 5 heute. Es ist kein Ausreisser, es ist
der Normalzustand. Acht Mal steht dazu im Klartext:
`Die Sprachausgabe ist fehlgeschlagen: Kein Verfahren konnte sprechen.`

Der grösste Einzelbefund. Bisher in keinem Bericht.

### 2. Claude Code ist für den Orb weiterhin nicht angemeldet

Heute um 15:19:33, nach deiner Anmeldung und nach dem Neustart:

    Claude Code ist nicht angemeldet. Ich fuehre es fuer 15 Minuten
    als nicht verfuegbar und arbeite solange mit dem lokalen Modell weiter.

Die heute eingebaute Erkennung greift also genau wie vorgesehen — aber die
Anmeldung, die du gemacht hast, kommt beim Orb nicht an. Der Verdacht liegt
bei der Umgebung des Unterprozesses: `_build_environment` entfernt
absichtlich `ANTHROPIC_API_KEY`, und Claude Code läuft in einem eigenen,
leeren Arbeitsverzeichnis (`data\claude_workspace`). Wo die Anmeldung
abgelegt ist und ob dieser Prozess sie sieht, ist der nächste Schritt.

**Zu prüfen:** ein Terminal öffnen, in `C:\Users\info\AI-Orb\data\claude_workspace`
wechseln und dort `claude -p "sag hallo"` ausführen. Antwortet es dort nicht,
liegt es am Arbeitsverzeichnis oder der Umgebung — nicht an deiner Anmeldung.

### 3. Das lokale Modell bekommt den vollen Wolkenkontext

    15:21:18  Tor 6 Modellkontext: 6 Nachrichten, 23.683 Zeichen
    15:20:33  Provider 'ollama' lieferte noch keinen Text
              (Keine Antwortverbindung innerhalb von 60 s)

Und das, obwohl `lfm2.5:8b` um 15:18:29 vorgewärmt gemeldet wurde. Das
Vorwärmen war nicht das Problem: Der Kontext ist es.

Über die letzten sieben Tage: **Median 21.985 Zeichen, Maximum 31.556** — rund
5.500 Token, die ein 8-Milliarden-Modell auf der CPU erst einlesen muss,
bevor das erste Wort fällt.

`_messages_for_provider` kürzt nur, wo es konfiguriert ist:

| Anbieter | recent_messages | max_input_characters |
|---|---|---|
| `ollama_fast` | 4 | 6.000 |
| `ollama_richter` | 4 | 24.000 |
| **`ollama` (der Rückfall)** | **—** | **—** |

Ausgerechnet der Anbieter, der einspringen soll, wenn die Cloud ausfällt,
bekommt als einziger lokaler Anbieter alles. Das ist eine Zeile in der
`config.yaml`.

### 4. Der Nachrichtenlauf hat noch nie etwas geliefert

Zehn Läufe, drei Themen, dreissig Versuche, **null Treffer**:

    Zum Thema 'Politik'    kam nichts (10x)
    Zum Thema 'Wirtschaft' kam nichts (10x)
    Zum Thema 'Weltlage'   kam nichts (10x)

Immer derselbe Grund: `<urlopen error _ssl.c:989: The handshake operation
timed out>`. Der Lauf existiert seit dem 31.08. und ist damit von „gibt es
nicht" auf „gibt es, tut aber nichts" gewechselt. Für den Benutzer ist das
dasselbe.

Sichtbar wird es auch im Gespräch: Auf *„Kannst du mir bitte die News des
Tages zusammenfassen?"* antwortete der Orb heute um 15:20:43 wörtlich
*„Leider habe ich keinen direkten Zugang zu Echtzeit-Nachrichten."* — obwohl
eine Mehrquellensuche lief und ein Nachrichtenlauf eingebaut ist.

### 5. Die Websuche trifft zu oft daneben

Warnungen der letzten sieben Tage:

    55x  Suche ueber Bing gescheitert: nur themenfremde Treffer
    42x  Websuche nur ueber den Notweg beantwortet
    34x  Suche ueber Yahoo gescheitert: Yahoo antwortete mit 500

Das Werkzeug meldet den Fehlschlag sauber und weicht aus — aber der Notweg
ist in 42 Fällen das Ergebnis gewesen, das der Benutzer bekam.

### 6. Das Sicherheitsbanner macht die echten Fehler unsichtbar

**1.408 Fehlerzeilen in sieben Tagen** stammen aus einer einzigen Quelle: dem
Banner, das `security.mode: offen` bei jedem Start 32 Mal meldet. Echte
Fehler in derselben Zeit: rund zwanzig.

Wer die Protokolle durchsieht, sieht zu 98 % dieselbe Meldung. Das ist der
Grund, warum Befund 1 drei Wochen lang niemandem aufgefallen ist. Ein
Warnhinweis, der bei jedem Start 32 Zeilen schreibt, warnt niemanden mehr.

### 7. Der Stop-Späher erfindet Wörter

Heute um 15:21:00, bei einer langen Antwort:

    Stop-Späher: 39 Hörfenster, davon 3 mit Text
    – Hallo Orb. | Ich bin bei der Welt. Ich bin bei der We | Ich will ja nicht.

Die Fenster kosten seit heute Nachmittag nur noch 0,1 s statt bis zu 14,4 s —
das ist behoben. Ihr *Inhalt* ist es nicht: Der Orb hört seine eigene Stimme
und macht daraus Text, der nie gesprochen wurde. Solange keines dieser
erfundenen Wörter „stopp" lautet, passiert nichts. Es ist eine Notbremse,
die auf Zufall wartet.

---

## Was ich geprüft und wieder verworfen habe

Damit es niemand ein zweites Mal untersucht:

* **Die CPU-Kollision zwischen Whisper und Ollama.** War meine eigene
  Vermutung von heute Mittag. Widerlegt: In den fünfzehn Sekunden, in denen
  ein Hörfenster 14,4 s brauchte, steht im Protokoll keine einzige andere
  Zeile. Die Ursache lag im Erkenner selbst und ist behoben.
* **`AttributeError: '_Ergebnis' object has no attribute 'confidence'`,
  26 Tracebacks.** Sieht aktuell aus, ist es nicht: alle vom 13.08. Die
  Tracebackzeilen tragen keinen Zeitstempel und rutschen bei einer naiven
  Datumsfilterung in jeden Zeitraum.
* **Cloudflare-Fehlerseiten im Sprachausgabe-Protokoll**, 99 Zeilen HTML.
  Vom 22.08., als noch eine Fernstimme über einen `trycloudflare`-Tunnel im
  Einsatz war. Die steht heute nicht mehr in der Kette. Geblieben ist die
  Unart, eine ganze Fehlerseite ungekürzt ins Protokoll zu schreiben.
* **`ollama_richter` beantwortete 116 Anfragen**, obwohl er laut
  `config.yaml` nur für Messläufe gedacht ist. Alle 116 am 01.09. — dem
  Messtag. Kein Befund.

---

## Reihenfolge

Nicht nach Schwere sortiert, sondern danach, was das nächste erst messbar
macht.

1. **Befund 6 zuerst.** Solange 98 % der Fehlerzeilen aus einem Banner
   stammen, findet man den nächsten Befund 1 wieder erst in drei Wochen.
   Eine Zeile Arbeit.
2. **Befund 1** — zwei von fünf Antworten stumm. Der grösste Einzelposten
   für den Benutzer, und der einzige, bei dem er gar nichts bekommt.
3. **Befund 2 und 3 zusammen** — die Antwortkette. Ohne Anmeldung fällt
   alles auf ein lokales Modell, das am Kontext erstickt. Beide für sich
   klein, zusammen der Unterschied zwischen 3 und 90 Sekunden.
4. **Die Sprachausgabe messen** (Befund aus der Tabelle, 41,5 %). Bisher hat
   sie niemand angesehen; es gibt keine einzige Zeile im Protokoll, die sagt,
   wie lange eine Synthese dauert. Erst messen, dann verbessern.
5. **Befund 4 und 5** — Nachrichten und Suche. Funktionslücken, keine
   Störungen. Sie warten, bis der Weg darunter trägt.
6. **Befund 7** zuletzt. Er kostet nichts mehr und wartet auf einen Zufall,
   der in drei Wochen nicht eingetreten ist.
