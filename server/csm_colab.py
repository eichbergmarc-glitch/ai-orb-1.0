"""CSM-1B in Google Colab starten – mit öffentlicher Adresse für AI-Orb.

So bekommst du die „Miles“-Stimme flüssig, ohne eine eigene GPU: Colab
stellt eine, dieser Code startet den Server darauf und öffnet einen Tunnel,
der ihm eine im Internet erreichbare Adresse gibt. Diese Adresse trägst du
in AI-Orb ein.

## Schritt für Schritt

1. Öffne https://colab.research.google.com und lege ein neues Notebook an.
2. Menü „Laufzeit“ → „Laufzeittyp ändern“ → als Hardwarebeschleuniger
   **GPU** wählen (T4 genügt).
3. Kopiere den INHALT dieser Datei in eine Zelle und führe sie aus.
4. Nach ein paar Minuten erscheint eine Zeile wie:

       ======> Trage diese Adresse in AI-Orb ein: https://xxxx.trycloudflare.com

   Diese Adresse kommt in AI-Orbs config.yaml unter
   voice.output.remote.endpoint, und "remote" setzt du in
   voice.output.engines an die erste Stelle.
5. Solange das Colab-Fenster offen und die Zelle läuft, spricht AI-Orb mit
   der CSM-Stimme. Schließt du Colab, fällt AI-Orb auf die lokale Stimme
   zurück.

## Ehrlich zu den Grenzen von Gratis-Colab

Colab trennt die Sitzung nach einigen Stunden und bei Leerlauf, und in
Stoßzeiten ist manchmal keine GPU frei. Zum Ausprobieren ist das ideal;
für den täglichen, verlässlichen Betrieb mietet man besser eine kleine
GPU-Instanz und lässt dort csm_tts_server.py laufen.
"""

# =============================================================================
# Ab hier: in eine Colab-Zelle kopieren.
# =============================================================================

# --- 1. Pakete -------------------------------------------------------------
# !pip install -q fastapi uvicorn nest-asyncio soundfile "transformers>=4.52" torch

import os
import secrets
import subprocess
import threading
import time

# Ein zufälliger Token, damit nicht Fremde deinen Server benutzen.
os.environ["REMOTE_TTS_TOKEN"] = secrets.token_urlsafe(16)
print("Dein Zugangstoken (auch in AI-Orbs .env als REMOTE_TTS_TOKEN eintragen):")
print("   ", os.environ["REMOTE_TTS_TOKEN"])

# --- 2. Server im Hintergrund starten --------------------------------------
# Es wird derselbe Server benutzt wie außerhalb von Colab. Lege die Datei
# csm_tts_server.py daneben (z. B. per Upload) oder füge ihren Inhalt in eine
# eigene Zelle ein und importiere ihn.

def _run_server() -> None:
    import uvicorn

    from csm_tts_server import app  # setzt csm_tts_server.py im selben Ordner voraus

    uvicorn.run(app, host="0.0.0.0", port=8800, log_level="warning")


threading.Thread(target=_run_server, daemon=True).start()
print("Server startet, Modell wird geladen … (einige Minuten)")

# --- 3. Öffentlichen Tunnel öffnen -----------------------------------------
# cloudflared braucht keine Anmeldung und gibt eine trycloudflare.com-Adresse.
subprocess.run(
    "wget -q -O cloudflared "
    "https://github.com/cloudflare/cloudflared/releases/latest/download/"
    "cloudflared-linux-amd64 && chmod +x cloudflared",
    shell=True,
)


def _open_tunnel() -> None:
    process = subprocess.Popen(
        ["./cloudflared", "tunnel", "--url", "http://localhost:8800"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    for line in process.stdout:  # type: ignore[union-attr]
        if "trycloudflare.com" in line:
            for token in line.split():
                if token.startswith("https://") and "trycloudflare.com" in token:
                    print("\n======> Trage diese Adresse in AI-Orb ein:", token, "\n")


# Erst dem Server Zeit zum Laden geben, dann den Tunnel öffnen.
time.sleep(20)
threading.Thread(target=_open_tunnel, daemon=True).start()

print("Läuft. Halte diese Zelle offen, solange du die Stimme nutzen willst.")
while True:
    time.sleep(60)
