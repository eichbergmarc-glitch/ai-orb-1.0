"""Abspielen über die TIDAL-App und Steuern über die Medientasten.

Die öffentliche TIDAL-API spielt nichts ab. Der Orb öffnet deshalb den
gefundenen Titel oder die Playlist per ``tidal://``-Link in der
TIDAL-Desktop-App und drückt danach - wenn gewünscht - die
Wiedergabe-Medientaste. Pause, weiter, zurück und Lautstärke laufen
ebenfalls über die Medientasten von Windows; die TIDAL-App hört darauf.
"""

from __future__ import annotations

import os
import sys
import threading
import time
import webbrowser

from backend.system.logging_setup import get_logger

logger = get_logger(__name__)

#: Virtuelle Tastencodes von Windows für die Medientasten.
MEDIENTASTEN: dict[str, int] = {
    "pause": 0xB3,        # Wiedergabe/Pause (dieselbe Taste)
    "weiter": 0xB3,
    "abspielen": 0xB3,
    "naechster": 0xB0,
    "vorheriger": 0xB1,
    "stopp": 0xB2,
    "lauter": 0xAF,
    "leiser": 0xAE,
    "stumm": 0xAD,
}


def taste_druecken(aktion: str, *, wiederholen: int = 1) -> bool:
    """Drückt eine Medientaste. Gibt ``False`` zurück, wenn es nicht geht."""

    code = MEDIENTASTEN.get(aktion)
    if code is None or sys.platform != "win32":
        return False
    try:
        import ctypes

        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        for _ in range(max(1, wiederholen)):
            user32.keybd_event(code, 0, 0x0001, 0)          # KEYEVENTF_EXTENDEDKEY
            user32.keybd_event(code, 0, 0x0001 | 0x0002, 0)  # ... | KEYEVENTF_KEYUP
        return True
    except Exception:  # noqa: BLE001 - ohne Medientaste läuft der Rest weiter.
        logger.exception("Die Medientaste liess sich nicht drücken.")
        return False


def in_app_oeffnen(app_link: str, web_link: str, *, danach_abspielen: bool = False, warte_sekunden: float = 4.0) -> str:
    """Öffnet einen Link in der TIDAL-App, sonst im Browser.

    Returns:
        ``"app"`` oder ``"browser"`` - wo es geöffnet wurde.
    """

    wo = "browser"
    # 22.11.2026: Zuerst die Fernsteuerung der App - sie spielt wirklich ab.
    if sys.platform == "win32" and danach_abspielen and app_link.startswith("tidal://"):
        if not _tidal_exe():
            logger.info("TIDAL-Fernsteuerung: keine TIDAL.exe gefunden - alter Weg.")
    if sys.platform == "win32" and danach_abspielen and app_link.startswith("tidal://") and _tidal_exe():
        pfad = app_link[len("tidal://"):]
        zufall = pfad.startswith("my-collection/")

        def _fernsteuern() -> None:
            try:
                protokoll = seite_abspielen(pfad, zufall=zufall)
            except Exception as fehler:  # noqa: BLE001 - z. B. Store-App laesst sich nicht direkt starten
                logger.info("TIDAL-Fernsteuerung nicht moeglich: %s", fehler)
                protokoll = "Fehler"
            if not protokoll.startswith("geklickt"):
                # Rueckfall: der bisherige Weg
                with __import__("contextlib").suppress(OSError):
                    os.startfile(app_link)  # type: ignore[attr-defined]
                time.sleep(warte_sekunden)
                taste_druecken("abspielen")

        threading.Thread(target=_fernsteuern, name="tidal-fernsteuerung", daemon=True).start()
        return "app"
    if sys.platform == "win32":
        try:
            os.startfile(app_link)  # type: ignore[attr-defined]
            wo = "app"
        except OSError:
            logger.info("Keine TIDAL-App für %s gefunden - Browser.", app_link)
    if wo == "browser":
        webbrowser.open(web_link, new=2)

    if wo == "app" and danach_abspielen:
        # Die App braucht einen Moment, bis die Seite geladen ist. Im
        # Hintergrund warten, damit der Orb nicht so lange stumm bleibt.
        def _spaeter() -> None:
            time.sleep(warte_sekunden)
            taste_druecken("abspielen")

        threading.Thread(target=_spaeter, name="tidal-abspielen", daemon=True).start()
    return wo


# --- Fernsteuerung der TIDAL-App (22.11.2026) --------------------------------
#
# Marc: "sie spielt nichts ab". Ein tidal://-Link oeffnet in der App nur die
# Seite; die Medientaste setzt danach die ALTE Warteschlange fort - oder gar
# nichts. Die App ist eine Electron-Anwendung. Mit dem Startschalter
# --remote-debugging-port laesst sie sich ueber das Chrome-DevTools-Protokoll
# steuern (so arbeitet auch das Projekt "tidal-cli"): Seite aufrufen, dann
# den Abspiel-Knopf DER SEITE druecken. Keine Anmeldung noetig - es ist
# Marcs angemeldete App.

CDP_PORT = int(os.environ.get("AI_ORB_TIDAL_CDP_PORT", "9229"))


def _tidal_exe() -> str | None:
    basis = os.path.join(os.environ.get("LOCALAPPDATA", ""), "TIDAL")
    kandidaten = [os.path.join(basis, "TIDAL.exe")]
    try:
        for name in sorted(os.listdir(basis), reverse=True):
            if name.startswith("app-"):
                kandidaten.append(os.path.join(basis, name, "TIDAL.exe"))
    except OSError:
        pass
    gefunden = next((k for k in kandidaten if os.path.isfile(k)), None)
    if gefunden:
        return gefunden
    # 22.11.2026: Marcs TIDAL stammt aus dem Microsoft Store (Paket
    # WiMPMusic.27241E05630EA). Store-Apps liegen unter WindowsApps; den
    # Ort nennt PowerShell.
    global _STORE_EXE
    if _STORE_EXE is None:
        _STORE_EXE = ""
        try:
            import subprocess

            ort = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "(Get-AppxPackage -Name 'WiMPMusic*' | Select-Object -First 1).InstallLocation"],
                capture_output=True, text=True, timeout=20,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            ).stdout.strip()
            for teil in ("app\\TIDAL.exe", "TIDAL.exe", "app\\tidal.exe"):
                pfad = os.path.join(ort, teil) if ort else ""
                if pfad and os.path.isfile(pfad):
                    _STORE_EXE = pfad
                    break
            if ort and not _STORE_EXE:
                for wurzel, _ordner, dateien in os.walk(ort):
                    if wurzel.count(os.sep) - ort.count(os.sep) > 2:
                        continue
                    if "TIDAL.exe" in dateien:
                        _STORE_EXE = os.path.join(wurzel, "TIDAL.exe")
                        break
            logger.info("TIDAL aus dem Store: %s", _STORE_EXE or f"nicht gefunden (Paketort {ort!r})")
        except Exception:  # noqa: BLE001
            logger.info("TIDAL-Store-Paket liess sich nicht ermitteln.", exc_info=True)
    return _STORE_EXE or None


_STORE_EXE: str | None = None


def _cdp_ziele() -> list[dict]:
    import json
    import urllib.request

    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json/list", timeout=1.5) as antwort:
            return list(json.loads(antwort.read().decode("utf-8")) or [])
    except Exception:  # noqa: BLE001
        return []


def fernsteuerung_bereit(*, starten: bool = True, warten: float = 25.0) -> bool:
    """Sorgt dafuer, dass die TIDAL-App mit Fernsteuerungs-Anschluss laeuft."""

    if _cdp_ziele():
        return True
    if not starten or sys.platform != "win32":
        return False
    exe = _tidal_exe()
    if not exe:
        logger.info("TIDAL-App nicht gefunden (%%LOCALAPPDATA%%\\TIDAL).")
        return False
    import subprocess

    # Laeuft die App schon OHNE Anschluss, muss sie einmal neu starten -
    # sonst nimmt die laufende Instanz den Schalter nicht an.
    subprocess.run(["taskkill", "/IM", "TIDAL.exe", "/F"], capture_output=True, check=False,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    time.sleep(1.5)
    subprocess.Popen([exe, f"--remote-debugging-port={CDP_PORT}"],  # noqa: S603
                     creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
    ende = time.time() + warten
    while time.time() < ende:
        if any(z.get("type") == "page" for z in _cdp_ziele()):
            time.sleep(4)  # die Oberflaeche laedt nach dem Fenster noch
            return True
        time.sleep(0.7)
    logger.info("TIDAL-App meldet keinen Fernsteuerungs-Anschluss.")
    return False


async def _js_ausfuehren(ausdruck: str, *, zeitlimit: float = 20.0) -> object:
    import aiohttp

    ziele = [z for z in _cdp_ziele() if z.get("type") == "page" and z.get("webSocketDebuggerUrl")]
    if not ziele:
        raise RuntimeError("keine TIDAL-Seite zum Steuern")
    ziel = next((z for z in ziele if "tidal" in str(z.get("url", ""))), ziele[0])
    async with aiohttp.ClientSession() as sitzung:
        async with sitzung.ws_connect(ziel["webSocketDebuggerUrl"], max_msg_size=0) as ws:
            await ws.send_json({"id": 1, "method": "Runtime.evaluate", "params": {
                "expression": ausdruck, "awaitPromise": True, "returnByValue": True}})
            async def lesen() -> object:
                async for nachricht in ws:
                    daten = nachricht.json()
                    if daten.get("id") == 1:
                        ergebnis = (daten.get("result") or {}).get("result") or {}
                        return ergebnis.get("value")
                return None
            import asyncio

            return await asyncio.wait_for(lesen(), zeitlimit)


#: Ruft eine Seite der App auf und drueckt deren Abspiel- (oder Zufalls-)Knopf.
#: Gesucht wird nach data-test-Kennungen und Beschriftungen auf Deutsch und
#: Englisch; der Knopf in der Abspielleiste unten zaehlt nicht.
_SEITE_SPIELEN = r"""
(async (pfad, zufall) => {
  const warte = ms => new Promise(r => setTimeout(r, ms));
  if (pfad) {
    const ziel = location.origin + "/" + pfad.replace(/^\/+/, "");
    if (location.href !== ziel) { history.pushState({}, "", ziel); dispatchEvent(new PopStateEvent("popstate")); }
    await warte(800);
    if (!location.pathname.includes(pfad.split("?")[0])) { location.href = ziel; await warte(4000); }
  }
  const leiste = el => el.closest('[data-test="footer-player"], footer, [class*="playerBar"], [class*="nowPlaying"]');
  const passt = (el, muster) => muster.test([el.getAttribute("data-test"), el.getAttribute("aria-label"),
                                             el.getAttribute("title"), el.innerText].join(" "));
  const zuerst = zufall ? [/shuffle|zufall/i, /play|abspielen|wiedergabe|wiedergeben/i]
                        : [/play-all|^\s*play\b|abspielen|wiedergabe|wiedergeben/i, /shuffle|zufall/i];
  for (let runde = 0; runde < 25; runde++) {
    const knoepfe = [...document.querySelectorAll("button, [role=button]")].filter(b => !leiste(b) && b.offsetParent);
    for (const muster of zuerst) {
      const k = knoepfe.find(b => passt(b, muster) && !/pause|playlist|add|hinzu/i.test(b.getAttribute("data-test") || ""));
      if (k) { k.click(); return "geklickt: " + (k.getAttribute("data-test") || k.getAttribute("aria-label") || k.innerText).slice(0, 40); }
    }
    await warte(400);
  }
  return "kein Abspielknopf: " + location.pathname;
})(%s, %s)
"""


def seite_abspielen(pfad: str, *, zufall: bool = False) -> str:
    """Fernsteuerung: Seite aufrufen und abspielen. Gibt ein Kurzprotokoll zurueck."""

    import asyncio
    import json

    if not fernsteuerung_bereit():
        return "keine Fernsteuerung"
    try:
        ergebnis = asyncio.run(_js_ausfuehren(_SEITE_SPIELEN % (json.dumps(pfad), "true" if zufall else "false")))
    except Exception as fehler:  # noqa: BLE001
        logger.info("TIDAL-Fernsteuerung gescheitert: %s", fehler)
        return f"Fehler: {fehler}"
    logger.info("TIDAL-Fernsteuerung (%s): %s", pfad, ergebnis)
    return str(ergebnis)
