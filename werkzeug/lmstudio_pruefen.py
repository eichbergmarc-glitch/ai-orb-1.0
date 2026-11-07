"""Prueft, ob LM Studio fuer den Orb bereitsteht und wie schnell es antwortet.

Aendert nichts. Liest config.yaml (ai.primary und ai.additional.lmstudio_fast),
fragt LM Studio nach den Modellen und stellt zwei kurze Fragen im Strom:

  1. kalt  - enthaelt ggf. das Laden des Modells (JIT)
  2. warm  - die Zeit, die sich im Alltag anfuehlt

Gemessen werden: Zeit bis zum ersten sichtbaren Wort, Gesamtzeit,
ungefaehre Woerter pro Sekunde, und ob das Modell trotz "thinking: false"
noch denkt. Ergebnis auf dem Bildschirm und in logs/lmstudio-pruefung.txt.

Aufruf:  runtime\\python\\python.exe werkzeug\\lmstudio_pruefen.py
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
ZEILEN: list[str] = []


def sag(text: str = "") -> None:
    print(text, flush=True)
    ZEILEN.append(text)


def einstellungen() -> tuple[str, str, dict]:
    try:
        import yaml  # type: ignore

        daten = yaml.safe_load((WURZEL / "config.yaml").read_text(encoding="utf-8"))
        ai = daten.get("ai", {})
        primaer = ai.get("primary", {}) or {}
        schnell = (ai.get("additional", {}) or {}).get("lmstudio_fast", {}) or {}
        return (
            str(primaer.get("base_url", "http://127.0.0.1:1234/v1")).rstrip("/"),
            str(primaer.get("model", "")),
            schnell,
        )
    except Exception as fehler:  # noqa: BLE001
        sag(f"Hinweis: config.yaml nicht lesbar ({fehler}); nehme Standardwerte.")
        return "http://127.0.0.1:1234/v1", "qwen/qwen3.5-9b", {}


def modelle(basis: str) -> list[str]:
    with urllib.request.urlopen(f"{basis}/models", timeout=8) as antwort:
        daten = json.loads(antwort.read().decode("utf-8"))
    return [str(m.get("id")) for m in daten.get("data", []) if m.get("id")]


def frage(basis: str, modell: str, text: str, mit_schalter: bool) -> dict:
    system = ("Du bist Synapse, ein deutschsprachiger Assistent. "
              "Antworte in ein bis zwei kurzen Saetzen.")
    # Wie der Orb selbst (prompt_format: chatml): Vorlage roh, leerer Denkblock.
    nutzlast = {
        "model": modell,
        "stream": True,
        "max_tokens": 96,
        "temperature": 0.3,
        "stop": ["<|im_end|>", "<|im_start|>", "<|endoftext|>"],
        "prompt": f"<|im_start|>system\n{system}<|im_end|>\n"
                  f"<|im_start|>user\n{text}<|im_end|>\n"
                  "<|im_start|>assistant\n<think>\n\n</think>\n\n",
    }
    anfrage = urllib.request.Request(
        f"{basis}/completions",
        data=json.dumps(nutzlast).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    start = time.perf_counter()
    erstes = None
    denken = 0
    text_teile: list[str] = []
    with urllib.request.urlopen(anfrage, timeout=300) as antwort:
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
                delta = wahl.get("delta") or {}
                if delta.get("reasoning_content") or delta.get("reasoning"):
                    denken += 1
                stueck = wahl.get("text") or delta.get("content") or ""
                if stueck:
                    if erstes is None and stueck.strip():
                        erstes = time.perf_counter() - start
                    text_teile.append(stueck)
    gesamt = time.perf_counter() - start
    antworttext = "".join(text_teile).strip()
    if "<think>" in antworttext:
        denken += 1
    return {
        "erstes": erstes,
        "gesamt": gesamt,
        "text": antworttext,
        "denken": denken,
        "woerter": len(antworttext.split()),
    }


def main() -> int:
    basis, modell, schnell = einstellungen()
    sag("LM-Studio-Pruefung fuer den AI-Orb  " + time.strftime("%d.%m.%Y %H:%M"))
    sag(f"Adresse: {basis}")
    sag(f"Modell laut config.yaml: {modell}")
    if schnell.get("model") and schnell.get("model") != modell:
        sag(f"Schnellmodell (lmstudio_fast): {schnell.get('model')}")
    sag()

    try:
        liste = modelle(basis)
    except Exception as fehler:  # noqa: BLE001
        sag(f"FEHLER: LM Studio antwortet nicht ({fehler}).")
        sag("  -> LM Studio oeffnen, Reiter 'Developer', 'Start Server' (Port 1234).")
        return 1
    sag("LM Studio laeuft. Angebotene Modelle:")
    for eintrag in liste:
        sag(f"  - {eintrag}" + ("   <- vom Orb benutzt" if eintrag == modell else ""))
    if modell not in liste:
        sag(f"FEHLER: '{modell}' steht nicht in der Liste. In config.yaml genau eine "
            "der Kennungen oben eintragen.")
        return 1
    sag()

    mit_schalter = True
    ergebnisse = []
    for name, text in (("kalt", "Sag kurz Hallo."), ("warm", "Wie spaet ist es ungefaehr am Mittag?")):
        sag(f"Frage {name}: {text}")
        try:
            r = frage(basis, modell, text, mit_schalter)
        except urllib.error.HTTPError as fehler:
            koerper = fehler.read().decode("utf-8", errors="replace")[:300]
            if mit_schalter and "chat_template_kwargs" in koerper:
                sag("  (Server kennt chat_template_kwargs nicht - ohne wiederholt)")
                mit_schalter = False
                r = frage(basis, modell, text, mit_schalter)
            else:
                sag(f"  FEHLER HTTP {fehler.code}: {koerper}")
                return 1
        except Exception as fehler:  # noqa: BLE001
            sag(f"  FEHLER: {fehler}")
            return 1
        ergebnisse.append(r)
        erstes = f"{r['erstes']:.1f} s" if r["erstes"] is not None else "nie"
        tempo = r["woerter"] / max(0.1, r["gesamt"] - (r["erstes"] or 0))
        sag(f"  erstes Wort nach {erstes}, fertig nach {r['gesamt']:.1f} s, "
            f"~{tempo:.1f} Woerter/s")
        sag(f"  Antwort: {r['text'][:200]}")
        if r["denken"]:
            sag("  ACHTUNG: Das Modell denkt trotzdem vor der Antwort.")
        sag()

    warm = ergebnisse[-1]
    sag("Urteil:")
    if warm["erstes"] is None:
        sag("  Keine sichtbare Antwort - siehe Hinweise oben.")
    elif warm["erstes"] <= 3:
        sag("  Fluessig. Der Orb beginnt in wenigen Sekunden zu sprechen.")
    elif warm["erstes"] <= 8:
        sag("  Brauchbar. Fuer schnellere Antworten ein kleineres Modell fuer "
            "lmstudio_fast eintragen (z. B. Qwen3.5-4B).")
    else:
        sag("  Zu langsam fuer ein fluessiges Gespraech. Ein kleineres Modell "
            "(Qwen3.5-4B oder -2B) fuer lmstudio_fast laden und eintragen.")

    ziel = WURZEL / "logs" / "lmstudio-pruefung.txt"
    try:
        ziel.parent.mkdir(exist_ok=True)
        ziel.write_text("\n".join(ZEILEN) + "\n", encoding="utf-8")
        sag(f"\nBericht: {ziel}")
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
