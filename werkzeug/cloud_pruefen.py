"""Misst OpenAI, Grok (xAI), NVIDIA, Nous (Hermes) und OpenRouter: Wer antwortet am schnellsten?

Aendert nichts. Liest die Schluessel aus .env, fragt bei jedem Dienst die
Modellliste ab und stellt jedem Kandidaten dieselbe kurze Frage im Strom.
Gemessen wird die Zeit bis zum ersten sichtbaren Wort - genau das, was sich
beim Orb als "fluessig" oder "zaeh" anfuehlt.

Ergebnis auf dem Bildschirm und in logs/cloud-pruefung.txt.
Aufruf:  runtime\\python\\python.exe werkzeug\\cloud_pruefen.py
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
ZEILEN: list[str] = []

DIENSTE = {
    "openai": {
        "url": "https://api.openai.com/v1",
        "schluessel": "OPENAI_API_KEY",
        "wunsch": ["gpt-5.6-terra", "gpt-5.6-luna", "gpt-5.5-mini", "gpt-5-mini",
                   "gpt-4.1-mini", "gpt-4o-mini", "gpt-4.1-nano"],
    },
    "grok": {
        "url": "https://api.x.ai/v1",
        "schluessel": "XAI_API_KEY",
        "wunsch": ["grok-4.3", "grok-4-fast-non-reasoning", "grok-4-1-fast-non-reasoning",
                   "grok-3-mini", "grok-3"],
        "muster": ["fast", "mini"],
    },
    "nvidia": {
        "url": "https://integrate.api.nvidia.com/v1",
        "schluessel": "NVIDIA_API_KEY",
        "wunsch": ["meta/llama-3.3-70b-instruct", "meta/llama-3.1-8b-instruct",
                   "mistralai/mistral-small-24b-instruct",
                   "nvidia/llama-3.3-nemotron-super-49b-v1", "qwen/qwen2.5-7b-instruct"],
        "muster": ["llama-3.3-70b", "llama-3.1-8b", "llama-4", "mistral-small",
                   "nemotron-nano", "gemma-3"],
    },
    "nous": {
        "url": "https://inference-api.nousresearch.com/v1",
        "schluessel": "NOUS_API_KEY",
        "wunsch": ["Hermes-4.3-36B", "Hermes-4-70B", "Hermes-4-405B"],
        # Nous fuehrt auch fremde Modelle; schnelle Kandidaten mit aufnehmen.
        "muster": ["hermes", "flash", "mini", "fast"],
    },
    "openrouter": {
        "url": "https://openrouter.ai/api/v1",
        "schluessel": "OPENROUTER_API_KEY",
        "wunsch": ["google/gemini-2.5-flash", "google/gemini-2.5-flash-lite",
                   "openai/gpt-4.1-mini", "openai/gpt-4o-mini",
                   "meta-llama/llama-3.3-70b-instruct", "openrouter/free"],
        # Ohne Guthaben gehen nur die kostenlosen Modelle.
        "muster": [":free"],
        "zuerst_muster": True,
    },
}


def sag(text: str = "") -> None:
    print(text, flush=True)
    ZEILEN.append(text)


def env_laden() -> None:
    datei = WURZEL / ".env"
    if not datei.exists():
        return
    for zeile in datei.read_text(encoding="utf-8").splitlines():
        zeile = zeile.strip()
        if not zeile or zeile.startswith("#") or "=" not in zeile:
            continue
        name, wert = zeile.split("=", 1)
        os.environ.setdefault(name.strip(), wert.strip().strip('"').strip("'"))


def kopf(schluessel: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {schluessel}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://localhost/ai-orb",
        "X-Title": "AI-Orb",
    }


def modelle(dienst: dict, schluessel: str) -> list[str]:
    anfrage = urllib.request.Request(f"{dienst['url']}/models", headers=kopf(schluessel))
    with urllib.request.urlopen(anfrage, timeout=15) as antwort:
        daten = json.loads(antwort.read().decode("utf-8"))
    return [str(m.get("id")) for m in daten.get("data", []) if m.get("id")]


def frage(dienst_name: str, dienst: dict, schluessel: str, modell: str) -> dict:
    nutzlast: dict = {
        "model": modell,
        "stream": True,
        "messages": [
            {"role": "system", "content": "Du bist Synapse, ein deutschsprachiger "
             "Assistent. Antworte in ein bis zwei kurzen Saetzen."},
            {"role": "user", "content": "Wie geht es dir heute?"},
        ],
    }
    if dienst_name == "openai":
        nutzlast["max_completion_tokens"] = 400
    else:
        nutzlast["max_tokens"] = 150
    anfrage = urllib.request.Request(
        f"{dienst['url']}/chat/completions",
        data=json.dumps(nutzlast).encode("utf-8"),
        headers=kopf(schluessel),
        method="POST",
    )
    start = time.perf_counter()
    erstes = None
    teile: list[str] = []
    with urllib.request.urlopen(anfrage, timeout=60) as antwort:
        for zeile in antwort:
            zeile = zeile.decode("utf-8", errors="replace").strip()
            if not zeile.startswith("data:"):
                continue
            roh = zeile[5:].strip()
            if roh == "[DONE]":
                break
            try:
                ereignis = json.loads(roh)
            except json.JSONDecodeError:
                continue
            for wahl in ereignis.get("choices") or []:
                stueck = (wahl.get("delta") or {}).get("content") or ""
                if stueck:
                    if erstes is None and stueck.strip():
                        erstes = time.perf_counter() - start
                    teile.append(stueck)
    return {"erstes": erstes, "gesamt": time.perf_counter() - start,
            "text": "".join(teile).strip()}


def main() -> int:
    env_laden()
    sag("Cloud-Pruefung fuer den AI-Orb  " + time.strftime("%d.%m.%Y %H:%M"))
    sag()
    bestenliste: list[tuple[float, str, str]] = []
    for name, dienst in DIENSTE.items():
        schluessel = os.environ.get(dienst["schluessel"], "").strip()
        sag(f"== {name}")
        if not schluessel:
            sag(f"  kein Schluessel ({dienst['schluessel']} fehlt in .env)")
            sag()
            continue
        try:
            liste = modelle(dienst, schluessel)
        except urllib.error.HTTPError as fehler:
            sag(f"  FEHLER HTTP {fehler.code}: "
                f"{fehler.read().decode('utf-8', errors='replace')[:200]}")
            sag()
            continue
        except Exception as fehler:  # noqa: BLE001
            sag(f"  FEHLER: {fehler}")
            sag()
            continue
        wunsch = [m for m in dienst["wunsch"] if m in liste]
        gefunden: list[str] = []
        for muster in dienst.get("muster", []):
            gefunden += [
                m for m in liste
                if muster.lower() in m.lower() and m not in gefunden and m not in wunsch
            ]
        kandidaten = (gefunden[:4] + wunsch[:2]) if dienst.get("zuerst_muster") else (wunsch + gefunden)
        kandidaten = kandidaten[:6]
        if not kandidaten:
            sag("  Beispiele aus der Liste: " + ", ".join(liste[:15]))
        sag(f"  {len(liste)} Modelle verfuegbar, geprueft: {', '.join(kandidaten) or '-'}")
        for modell in kandidaten:
            try:
                r = frage(name, dienst, schluessel, modell)
            except urllib.error.HTTPError as fehler:
                sag(f"  {modell}: HTTP {fehler.code} "
                    f"{fehler.read().decode('utf-8', errors='replace')[:150]}")
                continue
            except Exception as fehler:  # noqa: BLE001
                sag(f"  {modell}: FEHLER {fehler}")
                continue
            if r["erstes"] is None:
                sag(f"  {modell}: kein sichtbarer Text ({r['gesamt']:.1f} s)")
                continue
            sag(f"  {modell}: erstes Wort {r['erstes']:.2f} s, fertig {r['gesamt']:.2f} s"
                f" - {r['text'][:90]!r}")
            bestenliste.append((r["erstes"], name, modell))
        sag()

    sag("Rangliste (erstes Wort):")
    for platz, (zeit, name, modell) in enumerate(sorted(bestenliste), 1):
        sag(f"  {platz}. {zeit:5.2f} s  {name}: {modell}")
    ziel = WURZEL / "logs" / "cloud-pruefung.txt"
    try:
        ziel.parent.mkdir(exist_ok=True)
        ziel.write_text("\n".join(ZEILEN) + "\n", encoding="utf-8")
        sag(f"\nBericht: {ziel}")
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
