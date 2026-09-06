# Deutsche Ausdrucksstimme über einen GPU-Server

Das frei verfügbare `sesame/csm-1b` ist ein englisches Modell. Es erzeugt
ausdrucksstarke Gesprächssprache, spricht deutschen Text aber nicht
zuverlässig deutsch aus. AI-Orb verwendet für Deutsch deshalb **Chatterbox
Multilingual V3** von Resemble AI. Das Modell unterstützt Deutsch offiziell,
bietet regelbare Ausdrucksstärke und kann eine erlaubte Referenzstimme
übernehmen.

Die Orb-Schnittstelle bleibt dieselbe: Der Text wird satzweise an einen
geschützten GPU-Server geschickt, während die nächste Passage bereits
vorbereitet wird. Der Orb übermittelt zusätzlich seinen Gefühlszustand, damit
ruhige, freundliche, neugierige, fröhliche und warnende Sätze unterschiedlich
klingen.

## Google Colab

1. Öffne `server/AI_Orb_CSM_1B_Colab.ipynb` in Google Colab.
2. Aktiviere unter **Laufzeit → Laufzeittyp ändern** eine GPU.
3. Führe die fünf Codezellen von oben nach unten aus.
4. Die letzte Zelle zeigt eine `trycloudflare.com`-Adresse und einen
   Zugangstoken. Sie muss aktiv bleiben.
5. Trage die Adresse unter `voice.output.remote.endpoint` in `config.yaml`
   und den Token als `REMOTE_TTS_TOKEN` in `.env` ein. `remote` gehört an die
   erste Stelle von `voice.output.engines`.

Eine deutsche Referenzaufnahme ist optional. Verwende ausschließlich deine
eigene Stimme oder Material, für dessen Nachbildung du eine ausdrückliche
Erlaubnis hast.

## Verhalten bei einer Trennung

Kostenlose Colab-Laufzeiten und ihre Tunnel-Adressen sind nicht dauerhaft.
Wenn der Server schläft oder getrennt wird, fällt AI-Orb automatisch auf
ElevenLabs, Piper oder Windows-SAPI zurück. Der Orb verstummt dadurch nicht.

## Technischer Unterschied

- CSM-1B: englisch, sehr gesprächsnah, für zuverlässiges Deutsch ungeeignet.
- Chatterbox Multilingual V3: 23+ Sprachen einschließlich Deutsch,
  Voice-Cloning und einstellbare Ausdrucksstärke.
- Die deutsche Open-Source-Variante unterstützt nicht sämtliche nativen
  englischen Regie-Tags wie `[laugh]`. Natürlichkeit entsteht hier über
  Prosodie, Satzrhythmus, Orb-Emotionen und eine passende Referenzstimme.
