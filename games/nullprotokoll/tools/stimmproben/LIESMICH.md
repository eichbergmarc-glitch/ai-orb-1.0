# Eigene Stimmen klonen

XTTS-v2 kann eine Stimme aus einer kurzen Aufnahme nachbilden. Lege dafür je
Rolle eine Datei in diesen Ordner:

```text
gedanke_w.wav    innerer Monolog der weiblichen Spielfigur
gedanke_m.wav    innerer Monolog der männlichen Spielfigur
juna.wav         Dr. Juna Falk
samir.wav        Samir Dastan
funk.wav         unbekannte Funkstimme
```

Fehlt eine Datei, nimmt der Renderer stattdessen eine im Modell mitgelieferte
Studiostimme. Du kannst also einzeln nachrüsten und musst nicht alle fünf auf
einmal aufnehmen.

## Was eine gute Sprachprobe ausmacht

- **6 bis 15 Sekunden.** Länger bringt nichts, kürzer wird instabil.
- **Nur eine Person**, kein Hall, keine Musik, kein Tastaturklicken.
- **Zusammenhängend gesprochen**, nicht aus Schnipseln zusammengesetzt.
- **In der Tonlage, die im Spiel herauskommen soll.** Der Klon übernimmt
  Tempo, Höhe und Sprechhaltung der Probe. Für den inneren Monolog also ruhig
  und nah sprechen, nicht vorlesen.
- **Deutsch.** Andere Sprachen funktionieren, färben aber den Akzent ein.
- WAV, Mono, ab 22050 Hz. Andere Formate wandelt der Renderer nicht um –
  nimm sonst kurz `ffmpeg -i deine.mp3 -ac 1 -ar 24000 juna.wav`.

Ein brauchbarer Probetext, der genug Lautvielfalt enthält:

> Zwischen zwei Atemzügen wird mir klar, dass ich diesen Raum schon einmal
> gesehen habe. Die Anzeige über der Tür zählt rückwärts, und niemand hier
> hat mir bisher erklärt, warum mein Name im System steht.

## Wem die Stimme gehört

Nimm ausschließlich deine eigene Stimme oder eine, für die dir eine Erlaubnis
vorliegt. Das Modell selbst steht unter der Coqui Public Model License und ist
nur für nicht-kommerzielle Nutzung freigegeben.

## Danach

```powershell
.\STIMMEN_RENDERN.bat --force --only juna
```

`--force` überschreibt die bereits gerenderten Zeilen dieser Rolle, `--only`
beschränkt den Lauf. Ohne beides werden nur fehlende Zeilen ergänzt.
