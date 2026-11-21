"""AI-Orb Sprachserver: Kartoffelbox (deutsches Chatterbox) auf einer Colab-GPU.

17.11.2026 - Marc will eine eigene Stimme mit einem eigenen Sprachmodell,
das auf Google Colab (Gratis, T4) laeuft.

Was dieser Server tut
---------------------
* Laedt **Kartoffelbox** (SebastianBodza/Kartoffelbox-v0.1, Stand v0.2): ein
  auf ~600k deutschen Saetzen nachtrainiertes Chatterbox mit einstellbarer
  Ausdrucksstaerke und Stimmuebernahme.
* Uebernimmt die Stimme aus Marcs Referenzaufnahme (einmal vorbereitet,
  danach fuer jeden Satz wiederverwendet - das spart Zeit je Satz).
* Antwortet auf ``POST /tts`` mit einer WAV-Datei - genau das, was
  ``backend/tts/remote_tts_engine.py`` im Orb erwartet.
* Uebersetzt die Laut-Tags des Orb in die Laute, die Kartoffelbox kennt:
  ``<lachen>`` -> ``<haha>``, ``<schmunzeln>`` -> ``<chuckle>``,
  ``<hmm>`` -> ``<hmm_neugierig>`` usw. (Vorschau-Funktion des Modells:
  klingt mal besser, mal schlechter.)
* Die Gefuehlslage des Orb steuert die Ausdrucksstaerke, das Tempo die
  CFG-Gewichtung (weniger Gewichtung = ruhigeres, bedaechtigeres Sprechen).

Gestartet wird er vom Colab-Notebook als eigener Prozess - damit stoeren
die Paketversionen des Modells nicht den Notebook-Kern.

Umgebung:
    ORB_REFERENZ   Pfad zur Referenzaufnahme (WAV, 24 kHz mono)
    HF_TOKEN       Hugging-Face-Zugang (Kartoffelbox ist zugangsbeschraenkt)
    ORB_TOKEN      optional: verlangt "Authorization: Bearer <token>"
    ORB_PORT       Port (Vorgabe 8800)
"""

from __future__ import annotations

import io
import os
import re
import threading
import time

import soundfile as sf
import torch
import uvicorn
from fastapi import FastAPI, Header, HTTPException, Response
from huggingface_hub import snapshot_download
from pydantic import BaseModel, Field

MODELL_REPO = "SebastianBodza/Kartoffelbox-v0.1"
PORT = int(os.environ.get("ORB_PORT", "8800"))
REFERENZ = os.environ.get("ORB_REFERENZ", "").strip()
TOKEN = os.environ.get("ORB_TOKEN", "").strip()

#: Laute des Orb -> Laute, die Kartoffelbox v0.2 gelernt hat.
LAUTE = {
    "lachen": "<haha>",
    "schmunzeln": "<chuckle>",
    "hmm": "<hmm_neugierig>",
    "oh": "<ohhh>",
    "wow": "<wow>",
    "ach": "<aaach>",
    "seufzen": "<aaach>",
}
_LAUT_TAG = re.compile(r"<\s*(" + "|".join(LAUTE) + r")\s*/?\s*>", re.IGNORECASE)
#: Alles andere, was nach Markup aussieht, wird nie gesprochen.
_REST_TAG = re.compile(r"</?\s*[a-zA-Z_]+[^<>]{0,40}>")

#: Gefuehlslage des Orb -> Ausdrucksstaerke (Chatterbox: 0.25 ruhig ... 1.0 dramatisch).
AUSDRUCK = {
    "neutral": 0.50, "freundlich": 0.55, "aufmerksam": 0.50, "nachdenklich": 0.42,
    "erfreut": 0.68, "bedauernd": 0.45, "dringlich": 0.62, "leise": 0.38,
    "friendly": 0.55, "curious": 0.58, "thinking": 0.42, "happy": 0.68,
    "calm": 0.40, "warning": 0.62, "error": 0.45,
}

print("[stimme] Lade Kartoffelbox ...", flush=True)
import perth  # noqa: E402

# Das Wasserzeichen braucht pkg_resources (setuptools). Fehlt es, ist
# PerthImplicitWatermarker None und Chatterbox stuerzt beim Laden ab (19.11.2026).
if getattr(perth, "PerthImplicitWatermarker", None) is None:
    print("[stimme] Wasserzeichen nicht verfuegbar - spreche ohne.", flush=True)
    perth.PerthImplicitWatermarker = perth.DummyWatermarker
from chatterbox.tts import ChatterboxTTS  # noqa: E402 - erst nach der Meldung
from safetensors.torch import load_file  # noqa: E402

GERAET = "cuda" if torch.cuda.is_available() else "cpu"
HF_TOKEN = os.environ.get("HF_TOKEN") or None
VOLLSTAENDIG = ("t3_cfg.safetensors", "ve.safetensors", "s3gen.safetensors", "tokenizer.json")


def modell_laden() -> ChatterboxTTS:
    """Laedt Kartoffelbox auf zwei Wegen - der zweite ist der aus der Modellkarte.

    1. Das Repo enthaelt seit v0.2 alle Dateien im Chatterbox-Aufbau ->
       ``from_local``.
    2. Fehlt etwas oder passt es nicht: das Grundmodell von Resemble laden
       und nur das deutsche T3 hineinsetzen (so steht es auf der Modellkarte).
    """
    try:
        ordner = snapshot_download(
            MODELL_REPO, token=HF_TOKEN,
            allow_patterns=["*.safetensors", "*.safetensor", "*.json", "*.pt"],
        )
    except Exception as fehler:  # noqa: BLE001
        text = str(fehler)
        if "401" in text or "403" in text or "gated" in text.lower():
            raise SystemExit(
                "[stimme] FEHLER: Kein Zugriff auf Kartoffelbox. Auf "
                "https://huggingface.co/SebastianBodza/Kartoffelbox-v0.1 eingeloggt die "
                "Bedingungen akzeptieren und pruefen, dass das Secret HF_TOKEN zu diesem Konto gehoert."
            ) from fehler
        raise
    vorhanden = set(os.listdir(ordner))
    print(f"[stimme] Dateien im Modell: {sorted(vorhanden)}", flush=True)
    if all(name in vorhanden for name in VOLLSTAENDIG):
        try:
            m = ChatterboxTTS.from_local(ordner, GERAET)
            print("[stimme] Kartoffelbox vollstaendig geladen.", flush=True)
            return m
        except Exception as fehler:  # noqa: BLE001
            print(f"[stimme] Vollstaendiges Laden ging nicht ({fehler}) - nehme den Weg der Modellkarte.", flush=True)
    t3_datei = next((n for n in ("t3_cfg.safetensors", "t3_cfg.safetensor") if n in vorhanden), None)
    if t3_datei is None:
        raise SystemExit("[stimme] FEHLER: t3_cfg.safetensors fehlt im Kartoffelbox-Repo.")
    m = ChatterboxTTS.from_pretrained(device=GERAET)
    zustand = load_file(os.path.join(ordner, t3_datei), device="cpu")
    if "model" in zustand:
        zustand = zustand["model"][0]
    m.t3.load_state_dict(zustand)
    m.t3.to(GERAET).eval()
    print("[stimme] Grundmodell geladen, deutsches T3 eingesetzt.", flush=True)
    return m


modell = modell_laden()

# --- Schneller rechnen (19.11.2026) -------------------------------------
# Marc: zu lange Sprechpausen. Zwei Stellschrauben, beide abschaltbar:
#  * halbe Genauigkeit (fp16) per autocast - die T4 rechnet damit auf ihren
#    Tensor-Kernen ein Vielfaches schneller als in fp32;
#  * weniger Schritte im Klangdecoder (S3Gen-Flow, Vorgabe 10).
SCHNELL = os.environ.get("ORB_SCHNELL", "1") != "0" and GERAET == "cuda"

# Hoechstlaenge je Satz (19.11.2026): Chatterbox findet manchmal das Satzende
# nicht und erzeugt bis zu 1000 Tonschritte (~40 s Gebrabbel). Waehrenddessen
# wartete der Orb, lief in seine Frist und sprach 47 s lang nichts. Etwa
# 25 Schritte sind eine Sekunde; erlaubt ist gut das Doppelte der zu
# erwartenden Sprechdauer.
_GRENZE = {"schritte": 1000}
_t3_inferenz = modell.t3.inference


def _t3_begrenzt(*args, **kwargs):
    kwargs["max_new_tokens"] = min(int(kwargs.get("max_new_tokens") or 1000), _GRENZE["schritte"])
    return _t3_inferenz(*args, **kwargs)


modell.t3.inference = _t3_begrenzt


def schritte_fuer(text: str) -> int:
    sekunden = len(text) / 11.0 + 2.0      # ~11 Zeichen je Sekunde, plus Luft
    return max(60, min(1000, int(25 * sekunden * 1.3)))
CFM_SCHRITTE = int(os.environ.get("ORB_CFM_SCHRITTE", "6"))
if CFM_SCHRITTE > 0:
    _s3_inferenz = modell.s3gen.inference

    def _s3_kuerzer(*args, **kwargs):
        kwargs.setdefault("n_cfm_timesteps", CFM_SCHRITTE)
        return _s3_inferenz(*args, **kwargs)

    modell.s3gen.inference = _s3_kuerzer
if REFERENZ and os.path.exists(REFERENZ):
    modell.prepare_conditionals(REFERENZ, exaggeration=0.5)
    print(f"[stimme] Referenzstimme uebernommen: {REFERENZ}", flush=True)
else:
    print("[stimme] Keine Referenz - es spricht die eingebaute Stimme.", flush=True)

sperre = threading.Lock()
app = FastAPI(title="AI-Orb Stimme (Kartoffelbox)", docs_url=None, redoc_url=None)


class Auftrag(BaseModel):
    text: str = Field(min_length=1, max_length=800)
    speaker: int = 0
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    emotion: str = Field(default="neutral", max_length=32)


def text_vorbereiten(text: str) -> str:
    text = _LAUT_TAG.sub(lambda m: f" {LAUTE[m.group(1).lower()]} ", text)
    # Laut-Tags von Kartoffelbox selbst sollen stehen bleiben, alles andere weg.
    erlaubt = set(LAUTE.values())
    text = _REST_TAG.sub(lambda m: m.group(0) if m.group(0) in erlaubt else " ", text)
    return " ".join(text.split())


def sprechen(text: str, speed: float, emotion: str) -> tuple[bytes, float]:
    ausdruck = AUSDRUCK.get(emotion.strip().lower(), 0.5)
    if speed < 0.93:
        cfg = 0.25      # bedaechtiger
    elif speed > 1.06:
        cfg = 0.45      # zuegiger
    else:
        cfg = 0.32
    global SCHNELL
    start = time.perf_counter()
    with sperre, torch.inference_mode():
        _GRENZE["schritte"] = schritte_fuer(text)
        wav = None
        if SCHNELL:
            try:
                with torch.autocast("cuda", dtype=torch.float16):
                    wav = modell.generate(text, exaggeration=ausdruck, cfg_weight=cfg, temperature=0.65)
                if not torch.isfinite(wav).all() or float(wav.abs().max()) < 1e-4:
                    raise ValueError("fp16 lieferte keinen brauchbaren Ton")
            except Exception as fehler:  # noqa: BLE001 - dann eben in voller Genauigkeit
                print(f"[stimme] fp16 geht nicht ({fehler}) - rechne in fp32 weiter.", flush=True)
                SCHNELL = False
                wav = None
        if wav is None:
            wav = modell.generate(text, exaggeration=ausdruck, cfg_weight=cfg, temperature=0.65)
    daten = wav.squeeze().float().cpu().numpy()
    puffer = io.BytesIO()
    sf.write(puffer, daten, modell.sr, format="WAV", subtype="PCM_16")
    dauer = time.perf_counter() - start
    hoerdauer = len(daten) / modell.sr
    print(f"[stimme] {hoerdauer:.1f} s Ton in {dauer:.2f} s (Faktor {dauer / max(hoerdauer, 0.1):.2f})", flush=True)
    return puffer.getvalue(), dauer


@app.get("/health")
def health() -> dict:
    return {
        "ok": True,
        "modell": "Kartoffelbox (deutsches Chatterbox)",
        "geraet": torch.cuda.get_device_name(0) if GERAET == "cuda" else "cpu",
        "referenz": bool(REFERENZ and os.path.exists(REFERENZ)),
        "schnell": SCHNELL,
        "cfm_schritte": CFM_SCHRITTE,
    }


@app.post("/tts")
def tts(auftrag: Auftrag, authorization: str | None = Header(default=None)) -> Response:
    if TOKEN and authorization != f"Bearer {TOKEN}":
        raise HTTPException(status_code=401, detail="Falscher Zugangstoken.")
    text = text_vorbereiten(auftrag.text)
    if not text:
        raise HTTPException(status_code=400, detail="Kein Text.")
    try:
        daten, dauer = sprechen(text, auftrag.speed, auftrag.emotion)
    except Exception as fehler:  # noqa: BLE001 - als Meldung an den Orb, nicht als Absturz.
        raise HTTPException(status_code=500, detail=f"Erzeugung fehlgeschlagen: {fehler}") from fehler
    print(f"[stimme] {dauer:.2f} s fuer {len(text)} Zeichen: {text[:60]}", flush=True)
    return Response(content=daten, media_type="audio/wav")


if __name__ == "__main__":
    # Aufwaermen: der erste Satz kompiliert Kernels und dauert laenger.
    sprechen("Hallo, ich bin bereit.", 1.0, "freundlich")
    sprechen("Das ist ein zweiter, etwas laengerer Satz zum Messen der Geschwindigkeit.", 1.0, "neutral")
    print(f"[stimme] Bereit auf Port {PORT}.", flush=True)
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")
