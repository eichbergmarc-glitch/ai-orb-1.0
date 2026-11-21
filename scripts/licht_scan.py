"""Bluetooth-Suche fuer die Lichtsteuerung (20.11.2026).

Sucht rund 15 Sekunden nach Bluetooth-LE-Geraeten in der Naehe und schreibt
einen lesbaren Bericht. Ziel: herausfinden, ob dieser PC ueberhaupt
Bluetooth hat und ob er Marcs Lampen sieht (Philips Hue und EGLO).

Aufruf:  python licht_scan.py [ausgabedatei]
Braucht das Paket ``bleak`` (installiert die .bat vorher).
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime

# Firmen-Kennungen in der Bluetooth-Werbung (company identifier).
FIRMEN = {
    0x000B: "Philips (Signify) - spricht fuer eine Hue-Lampe",
    0x0100: "Telink - oft in guenstigen Mesh-Lampen (EGLO/AwoX)",
    0x0060: "AwoX - Hersteller der EGLO-Mesh-Technik",
}

# Namensbrocken, die auf eine der Lampen hindeuten.
HINWEISE = (
    ("hue", "Philips Hue"),
    ("eglo", "EGLO"),
    ("awox", "EGLO/AwoX"),
    ("telink", "Telink-Mesh (EGLO)"),
    ("smartlight", "Smart-Lampe"),
    ("ble", "evtl. Lampe"),
    ("light", "evtl. Lampe"),
    ("lamp", "evtl. Lampe"),
)


def _deute(name: str, firmen: list[int]) -> str:
    hinweise: list[str] = []
    klein = (name or "").lower()
    for brocken, bedeutung in HINWEISE:
        if brocken in klein:
            hinweise.append(bedeutung)
            break
    for kennung in firmen:
        if kennung in FIRMEN:
            hinweise.append(FIRMEN[kennung])
    return "  <-- " + "; ".join(dict.fromkeys(hinweise)) if hinweise else ""


async def suchen() -> list[str]:
    from bleak import BleakScanner

    zeilen: list[str] = []
    gefunden: dict[str, tuple] = {}

    def rueckruf(geraet, adv) -> None:
        firmen = list((adv.manufacturer_data or {}).keys())
        name = adv.local_name or geraet.name or ""
        # Staerkstes Signal je Geraet behalten.
        alt = gefunden.get(geraet.address)
        if alt is None or (adv.rssi or -999) > alt[2]:
            gefunden[geraet.address] = (geraet.address, name, adv.rssi or -999, firmen,
                                        list(adv.service_uuids or []))

    scanner = BleakScanner(detection_callback=rueckruf)
    await scanner.start()
    await asyncio.sleep(15.0)
    await scanner.stop()

    if not gefunden:
        zeilen.append("Es wurde KEIN Bluetooth-Geraet gefunden.")
        zeilen.append("Moegliche Gruende: Der PC hat kein Bluetooth, es ist ausgeschaltet,")
        zeilen.append("oder die Lampen sind gerade mit dem Handy/der Fernbedienung verbunden")
        zeilen.append("(dann bitte am Handy die Hue-App schliessen bzw. Bluetooth kurz aus).")
        return zeilen

    zeilen.append(f"{len(gefunden)} Bluetooth-Geraet(e) gefunden "
                  "(staerkstes Signal zuerst):")
    zeilen.append("")
    for adresse, name, rssi, firmen, dienste in sorted(
        gefunden.values(), key=lambda g: g[2], reverse=True
    ):
        anzeige = name if name else "(ohne Namen)"
        zeilen.append(f"- {anzeige}   [{adresse}]   Signal {rssi} dBm{_deute(name, firmen)}")
        if firmen:
            zeilen.append("    Hersteller-Kennungen: " + ", ".join(hex(f) for f in firmen))
        if dienste:
            zeilen.append("    Dienste: " + ", ".join(dienste[:4]))
    return zeilen


def main() -> int:
    ziel = sys.argv[1] if len(sys.argv) > 1 else "LICHT-SUCHE-ERGEBNIS.txt"
    kopf = [
        "AI-Orb - Bluetooth-Suche fuer die Lichtsteuerung",
        "Zeitpunkt: " + datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
        "=" * 60,
        "",
    ]
    try:
        zeilen = asyncio.run(suchen())
    except Exception as fehler:  # noqa: BLE001
        zeilen = [
            "Die Suche ist gescheitert:",
            f"  {type(fehler).__name__}: {fehler}",
            "",
            "Wenn hier 'WinRT'/'Bluetooth' steht, hat der PC vermutlich kein",
            "eingeschaltetes Bluetooth. Pruefe: Windows-Einstellungen -> Bluetooth.",
        ]
    bericht = "\n".join(kopf + zeilen) + "\n"
    try:
        with open(ziel, "w", encoding="utf-8") as datei:
            datei.write(bericht)
    except Exception:  # noqa: BLE001
        pass
    print(bericht)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
