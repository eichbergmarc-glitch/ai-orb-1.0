# Das lokale Sprachmodell

## Was „nicht erreichbar" alles heißen kann

Sechs verschiedene Dinge, und sie sehen von außen gleich aus:

Ollama ist nicht installiert. Ollama ist installiert, aber der Dienst läuft
nicht. Der Dienst läuft, aber das Modell ist nie heruntergeladen worden. Das
Modell ist da, heißt aber anders als in `config.yaml` steht. Der Abschnitt
`ai.fallback` fehlt in `config.yaml` ganz. Oder alles ist in Ordnung, und nur
die erste Antwort dauert so lange, dass es wie ein Ausfall wirkt.

`SPRACHMODELL-REPARIEREN.bat` geht die Kette in sechs Schritten durch,
repariert unterwegs, was sich reparieren lässt, und stellt dem Modell am
Ende eine echte Frage. Es zeigt die Antwort und die gemessene Zeit. Was
danach dasteht, gilt.

## Der Punkt, der am häufigsten übersehen wird

Ein Modell, das erst beim ersten Satz von der Platte in den Arbeitsspeicher
geladen wird, braucht dafür je nach Größe zehn bis sechzig Sekunden. Genau
die erlebt man als „nicht erreichbar" – der Orb schweigt, und irgendwann
gibt man auf, bevor die Antwort kommt.

Schritt 5 holt das Modell deshalb vorher ins Gedächtnis und hält es dort
(`keep_alive: 30m`). Die erste echte Frage ist danach so schnell wie jede
weitere.

## Offline heißt nicht automatisch offline

Der Orb fragt `ai.primary` zuerst und nimmt `ai.fallback`, wenn das
misslingt. Bei dir steht vorn ein Anbieter aus dem Netz. Ohne Internet
wartet der Orb also erst dessen Zeitlimit ab – bei dreißig Sekunden heißt
das dreißig Sekunden Stille vor **jeder** Antwort –, und erst danach fragt
er das lokale Modell.

Für den Offline-Betrieb ist das die falsche Reihenfolge. Punkt 3 im Menü
dreht sie um: Das lokale Modell steht vorn, der Netzanbieter bleibt als
Rückfall erhalten. Punkt 4 stellt es zurück. Beides mit Sicherung nach
`config.yaml.vor-ollama`.

Der Orb muss danach neu gestartet werden.

## Die Modellnamen

`backend/launcher/ollama_service.py` nennt als eingebauten Vorgabewert
`lfm2.5:8b`. In `config.yaml` unter `ai.fallback.model` steht, was wirklich
gilt – der Code setzt nach der Projektvorgabe keinen Modellnamen selbst.
Prüfe, dass dort das Modell steht, das du tatsächlich geladen hast.

Der Abgleich ist nachsichtig: Wer `llama3.1:8b` einträgt, ist auch mit
`llama3.1:8b-instruct-q4_0` zufrieden. Das Werkzeug sagt dir, wenn der
eingetragene und der tatsächliche Name auseinandergehen.

## Wenn es weiter hängt

Jeder Lauf schreibt `ollama-diagnose.txt`. Darin steht die HALT-Zeile mit
dem Grund und der Meldung des jeweiligen Programms.
