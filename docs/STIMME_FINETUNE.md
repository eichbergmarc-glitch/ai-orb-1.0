# Eine eigene, menschliche Stimme – finetunen und klonen

Diese Seite beantwortet zwei Wünsche, die zusammengehören:

* „Können wir unseren Thorsten finetunen?“
* „Gibt es eine lokale Stimme, die wir anhand einer Referenzstimme so
  menschlich wie möglich machen können – und die trotzdem flüssig ist?“

Die ehrliche Antwort vorweg: Es gibt keine Stimme, die gleichzeitig
*maximal menschlich*, *lokal auf einem gewöhnlichen Notebook* und *sofort
flüssig* ist. Man wählt zwei der drei. Darum stehen hier drei Wege, nach
diesem Kompromiss geordnet.

## Weg 1 – Thorsten finetunen (lokal, gratis, eigene Stimme)

Finetuning macht Thorsten **nicht** allgemein natürlicher. Die Technik
hinter Piper (VITS) hat eine Qualitätsobergrenze, und `thorsten-high`
schöpft sie bereits aus. Auf denselben Thorsten-Daten weiterzutrainieren
bringt nichts.

Wofür Finetuning **wirklich** gut ist: eine **eigene** Stimme. Man startet
beim fertigen Thorsten und biegt ihn mit eigenen Aufnahmen auf eine andere
Stimme um – die eigene oder eine bestimmte Sprecherin. Weil man nicht bei
null anfängt, reichen dafür schon rund 100 saubere Sätze.

Das Ergebnis läuft danach lokal und kostenlos wie Thorsten, klingt aber
nach der neuen Stimme – in Piper-Qualität, nicht wie ein Mensch im Raum.

Die vollständige Schritt-für-Schritt-Anleitung mit Colab-Zellen liegt in
`server/piper_finetune_colab.py`. Das Ergebnis (zwei Dateien:
`meine-stimme.onnx` und `meine-stimme.onnx.json`) legst du nach
`models/piper/` und trägst in `config.yaml` unter `voice.output.piper.voice`
den Namen `meine-stimme` ein.

## Weg 2 – Referenzstimme klonen mit XTTS v2 (am menschlichsten, braucht GPU)

Wenn das Ziel „so menschlich wie möglich, geklont aus einer Referenz“ ist,
ist **XTTS v2** (Coqui) die beste lokal betreibbare Wahl für Deutsch:

* Es **klont aus wenigen Sekunden** Referenzaufnahme (etwa 6–10 Sekunden
  sauberes Audio genügen) – kein Training nötig, nur eine Beispieldatei.
* Es klingt deutlich menschlicher als Piper: echte Betonung, Atem, Wärme.
* Es spricht Deutsch von Haus aus.

Der Haken ist die Geschwindigkeit. Flüssig ist XTTS v2 nur auf einer GPU
(Echtzeitfaktor ~0,3, also schneller als in Echtzeit). Auf reiner CPU ist
es um ein Vielfaches langsamer und für ein Gespräch nicht brauchbar –
derselbe Kompromiss wie bei CSM-1B (siehe `docs/STIMME_CSM.md`).

**Wie es in AI-Orb passt – ohne neuen Code.** AI-Orb spricht bereits mit
jedem Server, der Text entgegennimmt und eine WAV-Datei zurückgibt: die
`RemoteTtsEngine` (`backend/tts/remote_tts_engine.py`). Ein XTTS-Server
muss nur die gleiche kleine Schnittstelle bedienen wie der mitgelieferte
CSM-Server (`POST /tts` mit `{"text": ...}` → WAV-Bytes). Dann trägst du
seine Adresse in `config.yaml` unter `voice.output.remote.endpoint` ein und
setzt `remote` in `voice.output.engines` an die erste Stelle – exakt wie
beim CSM-Weg. Fällt der Server aus, spricht AI-Orb automatisch wieder mit
dem lokalen Thorsten.

Ein XTTS-Server ist in wenigen Zeilen gebaut:

```python
# xtts_server.py  – Gegenstelle zur RemoteTtsEngine, wie csm_tts_server.py
# pip install fastapi uvicorn TTS soundfile torch
import io, os, soundfile as sf
from fastapi import FastAPI, Response
from pydantic import BaseModel
from TTS.api import TTS

REFERENZ = os.environ.get("XTTS_REFERENCE", "referenz.wav")  # 6-10 s Beispiel
tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to(
    "cuda" if os.environ.get("CUDA_VISIBLE_DEVICES") is not None else "cpu"
)

class Req(BaseModel):
    text: str
    speaker: int = 0
    speed: float = 1.0

app = FastAPI()

@app.post("/tts")
def tts_ep(req: Req) -> Response:
    wav = tts.tts(text=req.text, speaker_wav=REFERENZ, language="de", speed=req.speed)
    buf = io.BytesIO(); sf.write(buf, wav, 24000, format="WAV", subtype="PCM_16")
    return Response(content=buf.getvalue(), media_type="audio/wav")
```

Denselben Colab-/GPU-Weg wie für CSM (`server/csm_colab.py`) kannst du
nutzen, um diesen Server öffentlich erreichbar zu machen – einfach dort
`csm_tts_server` durch `xtts_server` ersetzen.

## Weg 3 – CSM-1B („wie Miles“, am natürlichsten, nur auf GPU flüssig)

Wenn es genau die „Miles“-Stimme sein soll, ist CSM-1B der Weg. Er ist in
`docs/STIMME_CSM.md` und `server/csm_tts_server.py` beschrieben. Auch hier
gilt: flüssig nur mit GPU, lokal auf dem Notebook zu langsam.

## Kurz entschieden

| Du willst … | Nimm | Läuft flüssig auf |
| --- | --- | --- |
| eine eigene Stimme, lokal & gratis | Weg 1 (Piper-Finetune) | CPU |
| aus einer Referenz geklont, sehr menschlich | Weg 2 (XTTS v2) | GPU |
| genau die „Miles“-Stimme | Weg 3 (CSM-1B) | GPU |

Für den täglichen, flüssigen Betrieb ohne eigene GPU mietet man eine kleine
GPU-Instanz (wenige Euro) und lässt dort den XTTS- oder CSM-Server laufen.
AI-Orb bleibt davon unberührt: Es schickt Text, bekommt Sprache – und
fällt bei jedem Aussetzer auf die lokale Stimme zurück.
