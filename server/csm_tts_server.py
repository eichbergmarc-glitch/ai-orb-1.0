"""Ein kleiner TTS-Server, der CSM-1B auf einer GPU laufen lässt.

Dies ist die Gegenstelle zu :class:`backend.tts.remote_tts_engine.RemoteTtsEngine`.
Er lädt Sesames CSM-1B – die Stimme hinter „Miles“ – einmal in den Speicher
und beantwortet dann jeden POST ``/tts`` mit einer fertigen WAV-Datei.

## Wo das läuft

Nicht auf deinem Notebook. CSM-1B braucht eine GPU, um flüssig zu sein.
Zwei Orte bieten sich an:

* **Google Colab** (kostenlos, zum Ausprobieren): Eine GPU-Sitzung, dieser
  Server und ein Tunnel, der ihm eine öffentliche Adresse gibt. Gut zum
  Testen, aber Colab trennt die Sitzung nach einer Weile und bei Leerlauf –
  für den Dauerbetrieb also nichts.
* **Ein gemieteter GPU-Server** (wenige Euro, für den täglichen Gebrauch):
  läuft stabil und ist wirklich flüssig.

## Abhängigkeiten

    pip install fastapi uvicorn torch transformers soundfile

CSM-1B wird beim ersten Start von Hugging Face geladen (einige GB). Auf
Colab ist das in Minuten erledigt.

## Start

    python csm_tts_server.py

Standardmäßig lauscht er auf Port 8800. Setze die Umgebungsvariable
``REMOTE_TTS_TOKEN``, wenn nur AI-Orb ihn benutzen können soll – derselbe
Wert gehört dann in die ``.env`` von AI-Orb.

Eine Colab-Fassung mit öffentlichem Tunnel liegt als ``csm_colab.py`` bei.
"""

from __future__ import annotations

import io
import os

# --- Abhängigkeiten, mit verständlicher Meldung bei Fehlen ------------------
try:
    import soundfile as sf
    import torch
    from fastapi import FastAPI, Header, HTTPException, Response
    from fastapi.middleware.cors import CORSMiddleware
    from pydantic import BaseModel
    from transformers import AutoProcessor, CsmForConditionalGeneration
except ImportError as error:  # pragma: no cover - nur auf dem Server relevant
    raise SystemExit(
        "Es fehlen Pakete. Installiere sie mit:\n"
        "    pip install fastapi uvicorn torch transformers soundfile\n"
        f"(fehlend: {error.name})"
    )


MODEL_ID = os.environ.get("CSM_MODEL_ID", "sesame/csm-1b")
SAMPLE_RATE = 24000  # CSM-1B erzeugt Audio mit 24 kHz.
AUTH_TOKEN = os.environ.get("REMOTE_TTS_TOKEN", "").strip()


class TtsRequest(BaseModel):
    """Was AI-Orb schickt. Nur ``text`` ist Pflicht."""

    text: str
    speaker: int = 0
    speed: float = 1.0


print(f"Lade {MODEL_ID} … (beim ersten Mal dauert das)")
_device = "cuda" if torch.cuda.is_available() else "cpu"
if _device == "cpu":
    print(
        "WARNUNG: Keine GPU gefunden. CSM-1B läuft auf der CPU sehr langsam – "
        "für den flüssigen Betrieb wird eine GPU gebraucht."
    )

_processor = AutoProcessor.from_pretrained(MODEL_ID)
_model = CsmForConditionalGeneration.from_pretrained(MODEL_ID, device_map="auto")
print(f"Bereit auf {_device}.")


app = FastAPI(title="AI-Orb CSM-1B TTS")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _synthesize(text: str, speaker: int) -> bytes:
    """Erzeugt Sprache und gibt sie als WAV-Bytes zurück."""

    # CSM erwartet die Sprecher-Kennung dem Text vorangestellt: „[0]…“.
    prompt = f"[{speaker}]{text}"
    inputs = _processor(prompt, add_special_tokens=True).to(_model.device)

    with torch.no_grad():
        audio = _model.generate(**inputs, output_audio=True)

    # generate() liefert eine Liste von Wellenformen (eine je Eingabe).
    waveform = audio[0] if isinstance(audio, (list, tuple)) else audio
    samples = waveform.detach().to("cpu").float().numpy().squeeze()

    buffer = io.BytesIO()
    sf.write(buffer, samples, SAMPLE_RATE, format="WAV", subtype="PCM_16")
    return buffer.getvalue()


@app.get("/health")
def health() -> dict[str, object]:
    return {"ok": True, "model": MODEL_ID, "device": _device}


@app.post("/tts")
def tts(request: TtsRequest, authorization: str = Header(default="")) -> Response:
    """Erzeugt Sprache für einen Satz und gibt WAV zurück."""

    if AUTH_TOKEN:
        expected = f"Bearer {AUTH_TOKEN}"
        if authorization != expected:
            raise HTTPException(status_code=401, detail="Falscher oder fehlender Token.")

    text = request.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Kein Text.")

    try:
        wav = _synthesize(text, request.speaker)
    except Exception as error:  # noqa: BLE001 - eine Fehlermeldung ist besser als ein Absturz.
        raise HTTPException(status_code=500, detail=f"Erzeugung fehlgeschlagen: {error}")

    return Response(content=wav, media_type="audio/wav")


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "8800"))
    uvicorn.run(app, host="0.0.0.0", port=port)
