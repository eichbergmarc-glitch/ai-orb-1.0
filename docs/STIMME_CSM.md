# Deutsche Ausdrucksstimme für AI-Orb

AI-Orb verwendet **Chatterbox Multilingual V3** als deutschfähiges
Sprachmodell. Es erzeugt die Prosodie selbst – also Satzmelodie, Betonung,
Rhythmus und Sprechfluss – und kann mit einer autorisierten Referenzaufnahme
eine konsistente Sprecheridentität übernehmen.

Das englische Modell `sesame/csm-1b` ist nicht die richtige Wahl für
zuverlässige deutsche Aussprache. Das Colab-Notebook startet deshalb
Chatterbox Multilingual V3 auf einer GPU.

## Einmalige Einrichtung

1. Öffne `server/AI_Orb_CSM_1B_Colab.ipynb` in Google Colab.
2. Wähle **Laufzeit → Laufzeittyp ändern → GPU** und führe alle Zellen
   nacheinander aus.
3. Optional: Aktiviere in Zelle 3 `REFERENZ_VERWENDEN` und lade eine
   saubere deutsche Aufnahme deiner eigenen Stimme oder einer Stimme hoch,
   für deren Nachbildung du ausdrücklich berechtigt bist.
4. Lass die letzte Zelle laufen. Sie gibt eine öffentliche
   `trycloudflare.com`-Adresse und einen geheimen Token aus.
5. Trage die Adresse in `config.yaml` unter
   `voice.output.remote.endpoint` ein.
6. Trage den Token als `REMOTE_TTS_TOKEN` in die lokale `.env`-Datei ein.
   Der Token darf nicht in Git eingecheckt oder öffentlich geteilt werden.
7. Starte AI-Orb neu.

Die Konfiguration priorisiert nun `remote`, dann das lokale
`chatterbox`, danach die bisherigen Anbieter. Solange der Endpoint leer
oder nicht erreichbar ist, wird die Remote-Stimme übersprungen. Chatterbox
lokal benötigt das Paket `chatterbox-tts` und eine Referenzdatei unter
`data/voice/orb-reference.wav`; fehlt diese oder das Paket, geht die
bestehende Anbieter-Kette weiter.

## Stimmenidentität und Dynamik

- Die Pipeline übergibt pro Satz die erkannte Gefühlslage.
- Das Notebook übersetzt die deutschen Orb-Emotionen (freundlich,
  aufmerksam, nachdenklich, erfreut, bedauernd, dringlich, leise) in
  Chatterbox-Ausdrucksstärke.
- Eine Referenzaufnahme hält die Klangfarbe über mehrere Sätze hinweg
  konsistent.
- Die Satzaufteilung und Vorproduktion im Orb bleiben bestehen, damit der
  nächste Satz während der Wiedergabe vorbereitet werden kann.
- Nutze eine kurze, saubere Referenzaufnahme ohne Musik, Hall oder weitere
  Sprecher. Die Referenz ist optional.

## Betrieb und Fehlerfälle

Google-Colab-Sitzungen und kostenlose Tunnel-Adressen sind nicht dauerhaft.
Wenn die GPU-Sitzung endet, starte das Notebook erneut und aktualisiere
gegebenenfalls den Endpoint in `config.yaml`. Bis dahin verwendet AI-Orb
seine verfügbaren Rückfallanbieter. Der Orb bleibt dadurch sprechfähig,
aber die Klangfarbe kann sich beim Wechsel des Anbieters ändern.

Für dauerhaften Betrieb empfiehlt sich ein ständig verfügbarer GPU-Host
mit HTTPS-Endpunkt und festem Token. Teile den Token nicht und verwende
keine ungeschützte öffentliche TTS-Instanz.

## Modellhinweis

- `sesame/csm-1b`: englisch ausgerichtet; nicht für zuverlässiges Deutsch.
- `Chatterbox Multilingual V3`: mehrsprachig einschließlich Deutsch,
  regelbare Ausdrucksstärke und optionale Referenzstimme.
- Ausdruck entsteht über Prosodie und Referenzstimme; native englische
  Regie-Tags wie `[laugh]` sind nicht automatisch auf Deutsch verfügbar.
