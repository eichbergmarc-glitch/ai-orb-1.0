# Die CSM-1B-Stimme ("wie Miles") über einen GPU-Server

CSM-1B von Sesame ist die Stimme hinter „Miles" – natürlich, lebendig, kaum
von einem Menschen zu unterscheiden. Der Haken, den du schon bemerkt hast:
Auf einem gewöhnlichen Rechner ist sie zu langsam. Sie braucht eine
Grafikkarte.

Die Lösung ist eine Arbeitsteilung. Das Modell läuft dort, wo eine GPU ist;
AI-Orb schickt ihm nur den Text und bekommt fertige Sprache zurück. Und weil
AI-Orb Satz für Satz schickt und den nächsten Satz schon anfordert, während
der aktuelle spricht, fühlt es sich flüssig an – vorausgesetzt, der Server
hat eine GPU.

## Zwei Wege, den Server zu betreiben

### Zum Ausprobieren: Google Colab (kostenlos)

1. Öffne `server/csm_colab.py` und folge der Anleitung oben in der Datei:
   neues Colab-Notebook, GPU als Laufzeit, den Code in eine Zelle, ausführen.
2. Nach ein paar Minuten zeigt Colab eine Adresse
   (`https://….trycloudflare.com`) und einen Zugangstoken.
3. Trage in AI-Orb ein:
   - `config.yaml` → `voice.output.remote.endpoint`: die Adresse
   - `config.yaml` → `voice.output.engines`: `remote` an die erste Stelle
   - `.env` → `REMOTE_TTS_TOKEN`: den Token aus Colab
4. AI-Orb neu starten. Solange das Colab-Fenster offen ist, hörst du CSM.

Ehrlich zu den Grenzen: Gratis-Colab trennt die Sitzung nach einigen Stunden
und bei Leerlauf, und manchmal ist keine GPU frei. Zum Ausprobieren ideal,
für den Dauerbetrieb nicht.

### Für den täglichen Gebrauch: eine gemietete GPU

Eine kleine GPU-Instanz (bei den üblichen Cloud-Anbietern wenige Euro, oft
stundenweise abrechenbar) läuft stabil und ist wirklich flüssig. Dort:

    pip install fastapi uvicorn torch transformers soundfile
    REMOTE_TTS_TOKEN=deintoken python server/csm_tts_server.py

Dann die feste Adresse dieser Instanz als `endpoint` eintragen.

## Wenn der Server nicht läuft

Nichts geht kaputt. Ist der `endpoint` leer oder der Server nicht
erreichbar, spricht AI-Orb über die lokale Thorsten-Stimme weiter. Die
CSM-Stimme ist eine Zugabe, kein Muss – der Orb verstummt nie, nur weil ein
Server schläft.

## Kurz: Flüssig ja, aber nur mit GPU

Auf einer GPU (auch der T4 in Gratis-Colab) erzeugt CSM einen Satz in
Sekundenbruchteilen, und die Satz-für-Satz-Vorbereitung von AI-Orb
verbirgt selbst diese kurze Wartezeit. Ohne GPU ist es unbrauchbar langsam –
dann bleib bei Thorsten.
