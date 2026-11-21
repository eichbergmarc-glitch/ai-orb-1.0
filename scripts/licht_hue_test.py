"""Steuertest fuer die Philips Hue ueber Bluetooth (20.11.2026).

Verbindet sich mit der Hue-Lampe und fuehrt sichtbare Aktionen aus:
aus/an blinken, dimmen, Farbe blau, zurueck auf warmweiss. So sieht Marc
sofort, ob der PC die Lampe steuern kann.

Aufruf:  python licht_hue_test.py [BLE-Adresse] [ausgabedatei]
Vorgabe-Adresse ist die im Scan gefundene Hue.
"""

from __future__ import annotations

import asyncio
import struct
import sys
from datetime import datetime

# Aus dem Scan: der Dienst fe0f gehoert Signify (Philips Hue).
HUE_ADRESSE = "E1:55:AF:52:A9:D1"

# Die (reverse-engineerte) Bluetooth-Schnittstelle der Hue-Lampen.
DIENST = "932c32bd-0000-47a2-835a-a8d455b859dd"
C_ANAUS = "932c32bd-0002-47a2-835a-a8d455b859dd"      # 1 Byte: 01 an / 00 aus
C_HELLIGKEIT = "932c32bd-0003-47a2-835a-a8d455b859dd"  # 1 Byte: 1..254
C_FARBTEMP = "932c32bd-0004-47a2-835a-a8d455b859dd"    # 2 Byte Mired, little-endian
C_FARBE = "932c32bd-0005-47a2-835a-a8d455b859dd"       # 4 Byte: x,y je uint16 LE


def _xy(x: float, y: float) -> bytes:
    return struct.pack("<HH", int(x * 65535), int(y * 65535))


async def test(adresse: str, protokoll: list[str]) -> bool:
    from bleak import BleakClient, BleakScanner

    protokoll.append(f"Suche die Lampe {adresse} ...")
    geraet = await BleakScanner.find_device_by_address(adresse, timeout=15.0)
    if geraet is None:
        protokoll.append("NICHT gefunden. Ist die Hue eingeschaltet und die Handy-App")
        protokoll.append("geschlossen? (Die Lampe laesst nur EINE Verbindung zu.)")
        return False

    protokoll.append("Gefunden.")
    client = BleakClient(geraet)

    # Eine alte, halbe Windows-Kopplung steht der verschluesselten Verbindung
    # oft im Weg. Erst entfernen, dann frisch koppeln.
    try:
        await client.unpair()
        protokoll.append("Alte Windows-Kopplung entfernt.")
    except Exception as fehler:  # noqa: BLE001
        protokoll.append(f"(Kein alter Kopplungseintrag / unpair: {type(fehler).__name__})")

    protokoll.append("Verbinde ...")
    await client.connect()
    try:
        protokoll.append("Verbunden. Pruefe die Hue-Schnittstelle ...")
        hat = client.services.get_service(DIENST) is not None
        protokoll.append("Hue-Dienst vorhanden: " + ("ja" if hat else "NEIN (andere Lampe?)"))

        # Verschluesselt koppeln (protection_level 2 = Encryption / "Just Works").
        try:
            try:
                gepaart = await client.pair(protection_level=2)
            except TypeError:
                gepaart = await client.pair()
            protokoll.append("Kopplung (verschluesselt): " + ("ok" if gepaart else "abgelehnt/bereits"))
        except Exception as fehler:  # noqa: BLE001
            protokoll.append(f"Kopplung per Code nicht moeglich: {type(fehler).__name__}: {fehler}")

        async def schreibe(kennung: str, daten: bytes, was: str) -> None:
            try:
                await client.write_gatt_char(kennung, daten, response=True)
                protokoll.append(f"  ok: {was}")
            except Exception as fehler:  # noqa: BLE001
                protokoll.append(f"  FEHLER bei {was}: {type(fehler).__name__}: {fehler}")

        protokoll.append("Jetzt sollte die Lampe reagieren:")
        await schreibe(C_ANAUS, b"\x01", "einschalten")
        await asyncio.sleep(1.0)
        for _ in range(2):  # zweimal blinken
            await schreibe(C_ANAUS, b"\x00", "aus")
            await asyncio.sleep(0.8)
            await schreibe(C_ANAUS, b"\x01", "an")
            await asyncio.sleep(0.8)
        await schreibe(C_HELLIGKEIT, b"\x40", "dimmen auf ~25%")
        await asyncio.sleep(1.2)
        await schreibe(C_FARBE, _xy(0.15, 0.06), "Farbe blau")
        await asyncio.sleep(1.5)
        await schreibe(C_HELLIGKEIT, b"\xfe", "voll hell")
        await schreibe(C_FARBTEMP, struct.pack("<H", 370), "warmweiss")
        protokoll.append("Test fertig.")
        return True
    finally:
        try:
            await client.disconnect()
        except Exception:  # noqa: BLE001
            pass


def main() -> int:
    adresse = sys.argv[1] if len(sys.argv) > 1 else HUE_ADRESSE
    ziel = sys.argv[2] if len(sys.argv) > 2 else "LICHT-HUE-ERGEBNIS.txt"
    protokoll = [
        "AI-Orb - Hue-Steuertest ueber Bluetooth",
        "Zeitpunkt: " + datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
        "=" * 60,
        "",
    ]
    try:
        asyncio.run(test(adresse, protokoll))
    except Exception as fehler:  # noqa: BLE001
        protokoll.append("")
        protokoll.append(f"Abbruch: {type(fehler).__name__}: {fehler}")
        protokoll.append("")
        protokoll.append("Haeufige Gruende:")
        protokoll.append("- Die Handy-Hue-App ist noch verbunden (bitte schliessen).")
        protokoll.append("- Windows will die Lampe erst koppeln: einmal in den Windows-")
        protokoll.append("  Bluetooth-Einstellungen 'Geraet hinzufuegen' und die Hue waehlen.")
    if any("Insufficient Authentication" in z for z in protokoll):
        protokoll.append("")
        protokoll.append("HINWEIS: 'Insufficient Authentication' = die Lampe muss mit")
        protokoll.append("Windows gekoppelt werden. Wenn die Kopplung oben nicht 'ok' war:")
        protokoll.append("Windows-Einstellungen -> Bluetooth & Geraete -> 'Geraet")
        protokoll.append("hinzufuegen' -> Bluetooth -> die Hue (oder E1:55:AF:52:A9:D1)")
        protokoll.append("waehlen und koppeln. Danach diesen Test noch einmal starten.")
    bericht = "\n".join(protokoll) + "\n"
    try:
        with open(ziel, "w", encoding="utf-8") as datei:
            datei.write(bericht)
    except Exception:  # noqa: BLE001
        pass
    print(bericht)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
