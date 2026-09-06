"""Richtet den Zugang zum Orb von anderen Geraeten ein.

Seit der Orb die Verbindung beim Start selbst herstellt, ist dieses
Skript kein taeglicher Weg mehr, sondern zweierlei:

* die einmalige Einrichtung mit Administratorrechten, wenn Tailscale sie
  fuer die Weiterleitung verlangt,
* und die Auskunft, wenn etwas nicht stimmt - es sagt in ganzen Saetzen,
  woran es liegt, statt es im Protokoll zu verstecken.

Das Wissen darueber, wo Tailscale liegt und wie es angesprochen wird,
steht bewusst nicht hier, sondern in ``backend/system/ipad_verbindung``.
Der Kern braucht es beim Start ohnehin; zwei Kopien liefen auseinander,
sobald Tailscale sich das naechste Mal aendert.

Mit ``--wlan`` wird stattdessen das eigene WLAN geoeffnet: der kurze Weg
ohne Zusatzsoftware, aber ohne Verschluesselung - und damit ohne
Mikrofon und ohne Symbol auf dem Startbildschirm.
"""

from __future__ import annotations

import os
import secrets
import subprocess
import sys
from pathlib import Path

WURZEL = Path(__file__).resolve().parents[1]
ENV_DATEI = WURZEL / ".env"
SCHLUESSEL = "AI_ORB_WEB_TOKEN"

sys.path.insert(0, str(WURZEL))

#: Wohin die Mitschrift geschrieben wird.
_ZEILEN: list[str] = []


def sagen(text: str = "") -> None:
    """Sagt etwas - auf dem Bildschirm und fuer die Mitschrift."""

    _ZEILEN.append(text)
    print(text, flush=True)


def mitschrift_schreiben(ziel: Path) -> None:
    try:
        ziel.parent.mkdir(parents=True, exist_ok=True)
        ziel.write_text("\n".join(_ZEILEN) + "\n", encoding="utf-8")
    except OSError:
        pass


# --- Das Losungswort ---------------------------------------------------

#: Zeichen fuer das Losungswort. Ohne 0/O und 1/l/I - auf einem
#: iPad-Bildschirm sind die nicht auseinanderzuhalten, und ein falsch
#: abgetipptes Zeichen sieht aus wie ein kaputter Zugang.
ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"


def _ist_abtippbar(wort: str) -> bool:
    teile = wort.split("-")
    return len(teile) == 3 and all(len(teil) == 4 for teil in teile)


def neues_losungswort() -> str:
    """Wuerfelt ein kurzes, abtippbares Losungswort.

    Zwoelf Zeichen aus einunddreissig ergeben rund sechzig Bit - raten
    ist aussichtslos, abtippen dauert zehn Sekunden.
    """

    zeichen = "".join(secrets.choice(ALPHABET) for _ in range(12))
    return f"{zeichen[0:4]}-{zeichen[4:8]}-{zeichen[8:12]}"


def losungswort_holen(erneuern: bool = False) -> str:
    """Liest das vorhandene Losungswort - oder legt eines an."""

    zeilen: list[str] = []
    if ENV_DATEI.exists():
        zeilen = ENV_DATEI.read_text(encoding="utf-8").splitlines()
        if not erneuern:
            for zeile in zeilen:
                name, gleich, wert = zeile.partition("=")
                if gleich and name.strip() == SCHLUESSEL and wert.strip():
                    vorhanden = wert.strip().strip("\"'")
                    if _ist_abtippbar(vorhanden):
                        return vorhanden
                    sagen("Das bisherige Losungswort war zu lang zum Abtippen.")
                    sagen("Es wird durch ein kuerzeres ersetzt.")
                    break

    wort = neues_losungswort()
    zeilen = [z for z in zeilen if not z.startswith(f"{SCHLUESSEL}=")]
    while zeilen and not zeilen[-1].strip():
        zeilen.pop()
    if zeilen:
        zeilen.append("")
    zeilen.append("# Losungswort fuer den Zugang von anderen Geraeten (iPad, Handy).")
    zeilen.append("# Wer es kennt, kommt an den Orb. Nicht weitergeben.")
    zeilen.append(f"{SCHLUESSEL}={wort}")
    ENV_DATEI.write_text("\n".join(zeilen) + "\n", encoding="utf-8")
    sagen(f"Neues Losungswort angelegt und in {ENV_DATEI.name} gespeichert.")
    return wort


def port_lesen() -> int:
    """Holt den Port aus der Konfiguration, ohne den Orb zu starten."""

    try:
        from backend.config import get_config

        return int(get_config().section("backend").get("port", 8756))
    except Exception:
        return 8756


# --- Der Weg ueber das eigene WLAN -------------------------------------

HOST_ALT = (
    'backend:\n'
    '  # Host, auf dem der lokale REST-/WebSocket-Server lauscht.\n'
    '  host: "127.0.0.1"'
)

HOST_NEU = (
    'backend:\n'
    '  # Host, auf dem der lokale REST-/WebSocket-Server lauscht.\n'
    '  #\n'
    '  # "127.0.0.1" heisst: nur dieser Rechner. "0.0.0.0" heisst: auch\n'
    '  # andere Geraete im selben Netz - noetig fuer iPad und Handy im\n'
    '  # Heim-WLAN. Hereingelassen wird trotzdem nur, wer das Losungswort\n'
    '  # aus der .env kennt (AI_ORB_WEB_TOKEN).\n'
    '  host: "0.0.0.0"'
)


def eigene_netzadresse() -> str | None:
    """Findet die Adresse dieses Rechners im eigenen WLAN."""

    import socket

    verbindung = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        verbindung.connect(("192.0.2.1", 9))
        return str(verbindung.getsockname()[0])
    except OSError:
        return None
    finally:
        verbindung.close()


def auf_das_netz_hoeren() -> bool:
    """Stellt den Server in der config.yaml auf das eigene Netz um."""

    datei = WURZEL / "config.yaml"
    if not datei.exists():
        sagen("config.yaml wurde nicht gefunden.")
        return False

    text = datei.read_text(encoding="utf-8")
    if 'host: "0.0.0.0"' in text:
        sagen("Der Server hoert bereits auf das ganze Netz.")
        return True
    if HOST_ALT not in text:
        sagen("Die Zeile mit host konnte nicht sicher gefunden werden.")
        sagen('Bitte in der config.yaml unter "backend:" von Hand setzen:')
        sagen('  host: "0.0.0.0"')
        return False

    (WURZEL / "config.yaml.vor-fernzugang").write_text(text, encoding="utf-8")
    datei.write_text(text.replace(HOST_ALT, HOST_NEU, 1), encoding="utf-8")
    sagen("config.yaml umgestellt (Sicherung: config.yaml.vor-fernzugang).")
    return True


def firewall_oeffnen(port: int) -> bool:
    """Laesst Windows Anfragen aus dem eigenen Netz auf diesen Port durch."""

    if os.name != "nt":
        sagen("Firewall-Regel uebersprungen (kein Windows).")
        return True

    name = "AI-Orb"
    subprocess.run(
        ["netsh", "advfirewall", "firewall", "delete", "rule", f"name={name}"],
        capture_output=True, text=True, check=False,
    )
    ergebnis = subprocess.run(
        [
            "netsh", "advfirewall", "firewall", "add", "rule",
            f"name={name}", "dir=in", "action=allow", "protocol=TCP",
            f"localport={port}",
            # Bewusst alle Profile: Stuft Windows das eigene WLAN als
            # oeffentlich ein - nach einer Neuinstallation oft der Fall -,
            # griffe eine Regel nur fuer "privat" nicht, und niemand
            # saehe warum. Der Schutz liegt hier am Losungswort.
            "profile=any",
        ],
        capture_output=True, text=True, check=False,
    )
    if ergebnis.returncode == 0:
        sagen(f"Firewall geoeffnet fuer Port {port}.")
        return True

    sagen("Die Firewall-Regel konnte nicht angelegt werden.")
    sagen("Meist fehlen dafuer Administratorrechte.")
    ausgabe = (ergebnis.stdout + ergebnis.stderr).strip()
    if ausgabe:
        sagen(f"  {ausgabe.splitlines()[0]}")
    return False


def wlan_weg(wort: str, port: int) -> int:
    """Der kurze Weg: iPad und Rechner im selben WLAN, ohne Tailscale."""

    if not auf_das_netz_hoeren():
        return 1

    firewall_ok = firewall_oeffnen(port)
    adresse = eigene_netzadresse() or "<Adresse-dieses-Rechners>"

    sagen()
    sagen("=" * 62)
    sagen("  Im eigenen WLAN eingerichtet")
    sagen("=" * 62)
    sagen()
    sagen("  1. Den Orb einmal neu starten (ORB-STARTEN.bat).")
    sagen()
    sagen("  2. Auf dem iPad in Safari eintippen:")
    sagen(f"        {adresse}:{port}")
    sagen()
    sagen("     Losungswort:")
    sagen(f"        {wort}")
    sagen()
    sagen("=" * 62)
    sagen()
    sagen("Ohne Verschluesselung gibt Apple weder das Mikrofon frei noch")
    sagen("ein Symbol auf dem Startbildschirm. Beides bringt Tailscale -")
    sagen("dieses Skript ohne --wlan aufgerufen richtet es ein.")

    if not firewall_ok:
        sagen()
        sagen("ACHTUNG: Die Firewall-Regel fehlt. Ohne sie verwirft Windows")
        sagen("die Anfrage des iPad, ohne dass jemand etwas merkt. Diese")
        sagen("Datei mit Rechtsklick > Als Administrator ausfuehren starten.")
        return 1
    return 0


# --- Der Weg ueber Tailscale -------------------------------------------


def tailscale_weg(wort: str, port: int) -> int:
    """Verschluesselt, auch unterwegs - und mit Mikrofon."""

    from backend.system.ipad_verbindung import einrichten

    bericht = einrichten(port)
    zustand = bericht.get("zustand", "")

    if zustand == "kein_tailscale":
        sagen("Tailscale wurde auf diesem Rechner nicht gefunden.")
        sagen()
        sagen("  1. tailscale.com/download - installieren und anmelden.")
        sagen("  2. Dieselbe Anmeldung in der Tailscale-App auf dem iPad.")
        sagen("  3. Diese Datei erneut starten.")
        sagen()
        sagen(f"Das Losungswort lautet: {wort}")
        return 1

    if zustand == "nicht_angemeldet":
        sagen("Tailscale ist installiert, aber nicht angemeldet.")
        sagen()
        sagen("Das Symbol unten rechts in der Taskleiste anklicken")
        sagen("(eventuell unter dem Pfeil verborgen) und dort anmelden.")
        sagen("Danach diese Datei erneut starten.")
        sagen()
        sagen(f"Das Losungswort lautet: {wort}")
        return 1

    if zustand == "fehlgeschlagen":
        sagen("Die Weiterleitung liess sich nicht einrichten.")
        sagen()
        for zeile in bericht.get("hinweis", "").splitlines():
            sagen(f"  {zeile}")
        sagen()
        sagen("Falls hier von HTTPS die Rede ist: In der Tailscale-Verwaltung")
        sagen("einmalig einschalten unter")
        sagen("  login.tailscale.com/admin/dns  ->  HTTPS Certificates")
        sagen()
        sagen(f"Das Losungswort lautet: {wort}")
        return 1

    adresse = bericht.get("adresse", "")
    if zustand == "stand_schon":
        sagen("Die Weiterleitung stand bereits.")
    else:
        sagen("Weiterleitung eingerichtet.")
        if bericht.get("hinweis"):
            sagen(f"  {bericht['hinweis']}")

    sagen()
    sagen("=" * 62)
    sagen("  Fertig. Auf dem iPad in Safari eingeben:")
    sagen()
    sagen(f"  {adresse}")
    sagen()
    sagen("  Losungswort (einmalig):")
    sagen(f"  {wort}")
    sagen()
    sagen("=" * 62)
    sagen()
    sagen("Danach: Teilen > Zum Home-Bildschirm. Der Orb startet dann im")
    sagen("Vollbild mit eigenem Symbol, und das Mikrofon steht bereit.")
    sagen()
    sagen("Das richtet der Orb von nun an bei jedem Start selbst ein.")
    sagen("Diese Datei wird nur noch gebraucht, wenn etwas klemmt.")
    sagen()
    sagen("Es bleibt dabei: Der Rechner muss laufen.")
    return 0


def pruefen(port: int) -> int:
    """Sammelt alles, was die Frage beantwortet: Warum haengt es?

    Ein haengender Browser sagt nichts. Diese Auskunft sagt etwas -
    sie fragt der Reihe nach ab, was zwischen dem iPad und dem Orb
    liegt, und schreibt jede Antwort auf. Damit laesst sich der Fehler
    benennen, statt ihn zu raten.
    """

    from backend.system.ipad_verbindung import (
        fragen,
        tailscale_finden,
        zertifikate_moeglich,
    )

    sagen("Auskunft ueber die Verbindung zum iPad")
    sagen("=" * 62)
    sagen()

    # --- 1. Antwortet der Orb ueberhaupt? ------------------------------
    sagen("[1] Laeuft der Orb auf diesem Rechner?")
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=5) as a:
            sagen(f"    Ja - Port {port} antwortet ({a.status}).")
    except urllib.error.HTTPError as fehler:
        sagen(f"    Der Port antwortet ({fehler.code}) - der Orb laeuft.")
    except Exception as fehler:  # noqa: BLE001
        sagen(f"    NEIN: {fehler}")
        sagen("    Ohne laufenden Orb kann nichts durchkommen. Erst starten.")
        return 1
    sagen()

    # --- 2. Ist Tailscale da und angemeldet? ---------------------------
    sagen("[2] Tailscale")
    programm = tailscale_finden()
    if programm is None:
        sagen("    NICHT GEFUNDEN.")
        return 1
    sagen(f"    Programm: {programm}")

    code, ausgabe = fragen(programm, "status")
    if code != 0:
        sagen(f"    Status nicht lesbar: {ausgabe[:200]}")
        return 1
    for zeile in ausgabe.splitlines()[:12]:
        sagen(f"    {zeile}")
    sagen()

    # --- 2b. Wer ist ausser diesem Rechner im Netz? --------------------
    #
    # Die entscheidende Frage, und die am leichtesten zu uebersehene:
    # Eine Adresse auf ".ts.net" laesst sich von jedem Geraet der Welt
    # aufloesen - erreichbar ist sie aber nur von Geraeten im selben
    # Netz. Ein iPad, das nicht darin ist, bekommt eine Adresse, zu der
    # es keinen Weg gibt, und wartet. Ohne Fehlermeldung.
    sagen("[2b] Andere Geraete in diesem Netz")
    import json as _json

    code, roh = fragen(programm, "status", "--json")
    geraete = []
    if code == 0:
        try:
            daten = _json.loads(roh)
            for eintrag in (daten.get("Peer") or {}).values():
                geraete.append((
                    str(eintrag.get("HostName", "?")),
                    str(eintrag.get("OS", "")),
                    bool(eintrag.get("Online", False)),
                ))
        except _json.JSONDecodeError:
            pass

    if not geraete:
        sagen("    KEINE. In diesem Netz ist nur dieser Rechner.")
        sagen()
        sagen("    Das ist die Ursache: Die Adresse ist zwar weltweit")
        sagen("    aufloesbar, erreichbar aber nur von Geraeten im selben")
        sagen("    Tailscale-Netz. Ein iPad, das nicht darin ist, findet")
        sagen("    keinen Weg dorthin und wartet - ohne Fehlermeldung.")
        sagen()
        sagen("    Auf dem iPad: Tailscale-App oeffnen, mit DEMSELBEN Konto")
        sagen("    anmelden wie auf diesem Rechner, und den Schalter")
        sagen("    einschalten. Danach steht es hier in der Liste.")
    else:
        for name, art, online in geraete:
            zustand = "erreichbar" if online else "gerade offline"
            sagen(f"    {name} ({art}) - {zustand}")
        if not any(online for _, _, online in geraete):
            sagen()
            sagen("    Alle anderen Geraete sind offline. Auf dem iPad muss")
            sagen("    der Tailscale-Schalter eingeschaltet sein.")
    sagen()

    # --- 3. Darf das Netz Zertifikate ausstellen? ----------------------
    sagen("[3] HTTPS-Zertifikate")
    moeglich = zertifikate_moeglich(programm)
    if moeglich is True:
        sagen("    Ja - das Netz darf Zertifikate ausstellen.")
    elif moeglich is False:
        sagen("    NEIN - und das ist die haeufigste Ursache fuer 'haengt'.")
        sagen("    Der Browser bekommt kein Zertifikat und wartet endlos,")
        sagen("    ohne Fehlermeldung.")
        sagen()
        sagen("    Einschalten unter:")
        sagen("      login.tailscale.com/admin/dns  ->  HTTPS Certificates")
    else:
        sagen("    Nicht zu ermitteln (aeltere Tailscale-Fassung).")
    sagen()

    # --- 4. Worauf zeigt die Weiterleitung? ---------------------------
    sagen("[4] Weiterleitung")
    for form in (("serve", "status"), ("serve", "status", "--json")):
        code, ausgabe = fragen(programm, *form)
        if code == 0 and ausgabe.strip():
            sagen(f"    ({' '.join(form)})")
            for zeile in ausgabe.splitlines()[:20]:
                sagen(f"    {zeile}")
            break
    else:
        sagen("    Keine Weiterleitung eingerichtet oder nicht lesbar.")
        sagen("    Diese Datei ohne --pruefen starten richtet sie ein.")
    sagen()

    sagen("=" * 62)
    sagen("Wichtig beim Eintippen auf dem iPad: die Adresse MIT https://")
    sagen("davor. Ohne das versucht Safari Port 80 - dort antwortet")
    sagen("nichts, und es sieht aus wie ein haengender Server.")
    sagen()
    sagen("Diese Auskunft steht in logs/ipad-einrichtung.txt.")
    return 0


def main() -> int:
    protokoll = WURZEL / "logs" / "ipad-einrichtung.txt"

    sagen("=" * 62)
    sagen("  Der Orb von anderen Geraeten aus")
    sagen("=" * 62)
    sagen()

    try:
        port = port_lesen()
        if "--pruefen" in sys.argv:
            return pruefen(port)

        wort = losungswort_holen("--neu" in sys.argv)

        if "--wlan" in sys.argv:
            return wlan_weg(wort, port)
        return tailscale_weg(wort, port)
    finally:
        mitschrift_schreiben(protokoll)


if __name__ == "__main__":
    raise SystemExit(main())
