"""Schreibt auf, was der Rechner an Ton-Geraeten hat und was davon geht.

Der Fehler "MME error 1" aus PortAudio sagt fuer sich genommen nichts.
Er kann drei sehr verschiedene Dinge bedeuten: es gibt gar kein
Aufnahmegeraet, es gibt eines aber ein anderes Programm haelt es
exklusiv, oder Windows verweigert den Zugriff. Dieser Bericht trennt
die drei Faelle, indem er erst auflistet und dann der Reihe nach
wirklich zu oeffnen versucht.

Das Ergebnis landet in logs/mikrofon-bericht.txt.
"""

from __future__ import annotations

import sys
import traceback
from datetime import datetime
from pathlib import Path

PROJEKT = Path(__file__).resolve().parent.parent
BERICHT = PROJEKT / "logs" / "mikrofon-bericht.txt"

# Dieselben Werte, die auch backend/audio/audio_capture.py verwendet.
SAMPLE_RATE = 16000
BLOCK_SIZE = 480

zeilen: list[str] = []


def sag(text: str = "") -> None:
    print(text)
    zeilen.append(text)


sag("=" * 70)
sag("Mikrofon-Bericht  " + datetime.now().strftime("%d.%m.%Y %H:%M:%S"))
sag("=" * 70)
sag()

try:
    import sounddevice as sd
except Exception:  # noqa: BLE001
    sag("sounddevice liess sich nicht laden. Ohne das Paket geht keine Aufnahme.")
    sag(traceback.format_exc())
    BERICHT.parent.mkdir(parents=True, exist_ok=True)
    BERICHT.write_text("\n".join(zeilen), encoding="utf-8")
    sys.exit(1)

sag("Python:      " + sys.executable)
sag("sounddevice: " + getattr(sd, "__version__", "unbekannt"))
sag()

# --- Was Windows anbietet ----------------------------------------------------

sag("-" * 70)
sag("Ton-Schnittstellen (Host-APIs)")
sag("-" * 70)
try:
    for i, api in enumerate(sd.query_hostapis()):
        sag(f"  [{i}] {api['name']}  -  {len(api.get('devices', []))} Geraete, "
            f"Standard-Eingang: {api.get('default_input_device')}")
except Exception:  # noqa: BLE001
    sag("  Liste nicht lesbar:")
    sag(traceback.format_exc())
sag()

sag("-" * 70)
sag("Alle Geraete")
sag("-" * 70)
eingaenge: list[int] = []
try:
    for i, g in enumerate(sd.query_devices()):
        ein = int(g.get("max_input_channels", 0))
        aus = int(g.get("max_output_channels", 0))
        art = []
        if ein:
            art.append(f"Eingang({ein})")
            eingaenge.append(i)
        if aus:
            art.append(f"Ausgang({aus})")
        sag(f"  [{i:>2}] {g.get('name','')}")
        sag(f"       {', '.join(art) or 'nichts'}   API: "
            f"{sd.query_hostapis(g.get('hostapi', 0))['name']}   "
            f"Standardrate: {g.get('default_samplerate')}")
except Exception:  # noqa: BLE001
    sag("  Liste nicht lesbar:")
    sag(traceback.format_exc())
sag()

try:
    sag(f"Standardgeraete laut System: Eingang={sd.default.device[0]}, "
        f"Ausgang={sd.default.device[1]}")
except Exception:  # noqa: BLE001
    sag("Standardgeraete nicht lesbar.")
sag()

# --- Was sich wirklich oeffnen laesst ----------------------------------------


sag("-" * 70)
sag("Windows-Freigabe fuer das Mikrofon")
sag("-" * 70)
try:
    import winreg

    pfade = [
        ("Apps allgemein", r"Software\\Microsoft\\Windows\\CurrentVersion\\CapabilityAccessManager\\ConsentStore\\microphone"),
        ("Klassische Programme", r"Software\\Microsoft\\Windows\\CurrentVersion\\CapabilityAccessManager\\ConsentStore\\microphone\\NonPackaged"),
    ]
    for was, pfad in pfade:
        for wurzel, wname in ((winreg.HKEY_CURRENT_USER, "Benutzer"), (winreg.HKEY_LOCAL_MACHINE, "System")):
            try:
                with winreg.OpenKey(wurzel, pfad) as schluessel:
                    wert, _ = winreg.QueryValueEx(schluessel, "Value")
                    marke = "ERLAUBT" if str(wert).lower() == "allow" else "GESPERRT"
                    sag(f"  {wname:<8} {was:<22} {wert}   -> {marke}")
            except FileNotFoundError:
                sag(f"  {wname:<8} {was:<22} (nicht gesetzt)")
            except Exception as fehler:  # noqa: BLE001
                sag(f"  {wname:<8} {was:<22} nicht lesbar: {fehler}")
except Exception:  # noqa: BLE001
    sag("  Registry nicht lesbar (kein Windows?).")
sag()

sag("-" * 70)
sag("Oeffnungsversuche (so wie der Orb es macht: 16000 Hz, 1 Kanal, int16)")
sag("-" * 70)

if not eingaenge:
    sag("  Es gibt kein einziges Aufnahmegeraet. Dann ist entweder keines")
    sag("  angeschlossen, oder es ist in den Windows-Toneinstellungen")
    sag("  deaktiviert. Das erklaert den Fehler vollstaendig.")
else:
    geglueckt: list[tuple[int, int]] = []
    # Nicht nur 16000. Viele eingebaute Mikrofonarrays laufen im
    # geteilten Betrieb ausschliesslich mit ihrer eigenen Rate - meist
    # 48000 - und weisen alles andere ab. Genau das trennt "gesperrt"
    # von "falsch gefragt".
    raten = [16000, 32000, 44100, 48000]
    for i in eingaenge:
        g = sd.query_devices(i)
        api = sd.query_hostapis(g.get("hostapi", 0))["name"]
        sag(f"  [{i}] {g['name']}   ({api})")
        for rate in raten:
            try:
                strom = sd.RawInputStream(
                    samplerate=rate,
                    blocksize=int(rate * 0.03),
                    device=i,
                    channels=1,
                    dtype="int16",
                )
                strom.start()
                strom.stop()
                strom.close()
                sag(f"        {rate:>6} Hz   OK")
                geglueckt.append((i, rate))
            except Exception as fehler:  # noqa: BLE001
                meldung = str(fehler).replace("Error opening RawInputStream: ", "")
                sag(f"        {rate:>6} Hz   scheitert  {meldung}")

    sag()
    sag("-" * 70)
    if geglueckt:
        sag("Ergebnis: Aufnahme IST moeglich. Diese Kombinationen gehen:")
        for i, rate in geglueckt:
            sag(f"   Geraet {i:>2} bei {rate} Hz  =  {sd.query_devices(i)['name']}")
        sag()
        if not any(rate == 16000 for _, rate in geglueckt):
            sag("Keine davon bei 16000 Hz - und genau die verlangt der Orb.")
            sag("Das Mikrofon ist also nicht gesperrt, es wird nur falsch")
            sag("gefragt. Die Aufnahme muss mit der Rate des Geraets laufen")
            sag("und danach auf 16000 Hz heruntergerechnet werden.")
    else:
        sag("Ergebnis: Es gibt Aufnahmegeraete, aber keines laesst sich oeffnen.")
        sag("Das spricht fuer eine Sperre, nicht fuer fehlende Technik:")
        sag("  - Windows-Einstellungen > Datenschutz > Mikrofon: Zugriff fuer")
        sag("    Desktop-Apps erlaubt?")
        sag("  - Haelt ein anderes Programm das Mikrofon exklusiv? (Teams,")
        sag("    Zoom, Chrome mit offener Aufnahme, OBS)")
    sag("-" * 70)

BERICHT.parent.mkdir(parents=True, exist_ok=True)
BERICHT.write_text("\n".join(zeilen), encoding="utf-8")
print()
print("Geschrieben nach: " + str(BERICHT))
