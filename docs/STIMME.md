# Die Stimme des Orb

AI-Orb kann mit verschiedenen Stimmen sprechen. Es gibt dabei einen echten
Zielkonflikt, den man kennen sollte: **Eine Stimme kann natürlich sein oder
vollständig lokal – beides zugleich geht nur begrenzt.**

## Die lokalen Stimmen (kostenlos, nichts verlässt den Rechner)

Voreingestellt ist **Piper** mit der deutschen Stimme `de_DE-thorsten-high`.
Das ist die natürlichste Stimme, die lokal und gratis zu haben ist. Sie
klingt gut, aber man hört ihr an, dass sie aus dem Rechner kommt.

Zwei Regler in `config.yaml` unter `voice.output.piper` beeinflussen, wie
lebendig sie klingt:

- `noise_w` gibt der Sprache Rhythmus statt Gleichtakt.
- `noise_scale` gibt ihr Ausdruck.

Höhere Werte klingen weniger monoton; zu hohe machen die Stimme unruhig.
Die Vorgaben (0.9 und 0.72) sind ein warmer Mittelweg.

Fällt Piper aus, spricht AI-Orb über die **Windows-Sprachausgabe** (SAPI) –
immer verfügbar, aber deutlich mechanischer.

## Die Cloud-Stimmen (natürlich, dafür geht der Text ins Netz)

Wer eine Stimme will, die wirklich wie ein Mensch klingt, kommt an einem
Netzdienst nicht vorbei. AI-Orb unterstützt zwei, und beide sind eine
bewusste Entscheidung: Der zu sprechende Text wird an einen fremden Server
geschickt.

### SpeechGen.io

1. Lege ein Konto auf `speechgen.io` an. Unter **API** findest du deinen
   **Token** und die **E-Mail** deines Kontos.
2. Trage beides in die `.env` ein:

       SPEECHGEN_TOKEN=...
       SPEECHGEN_EMAIL=...

3. Wähle in `config.yaml` unter `voice.output.speechgen.voice` eine deutsche
   Stimme (den Namen, wie SpeechGen ihn in seiner Stimmenliste führt).
4. Setze `speechgen` in `voice.output.engines` an die **erste** Stelle:

       engines:
         - "speechgen"
         - "piper"
         - "sapi"

Ohne Zugangsdaten bleibt SpeechGen still, und Piper übernimmt – du kannst
also gefahrlos umstellen und bei fehlender Verbindung weiterarbeiten.

### ElevenLabs

Ebenfalls unterstützt, gleiches Prinzip: `ELEVENLABS_API_KEY` in die `.env`,
eine `voice_id` in `config.yaml`, `elevenlabs` in die Engine-Liste.

## Welche soll ich nehmen?

- **Nichts soll den Rechner verlassen, kostenlos:** Piper high (Vorgabe).
- **So natürlich wie möglich, Netz ist in Ordnung:** SpeechGen oder
  ElevenLabs.

Die Reihenfolge in `voice.output.engines` ist zugleich die Rückfallkette:
Was zuerst steht und einsatzbereit ist, spricht; fällt es aus, kommt das
nächste. So klingt AI-Orb im besten Fall natürlich und verstummt im
schlechtesten trotzdem nie.
